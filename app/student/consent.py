#
# Created by David Seery on 13/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Consent management routes for the student blueprint.

Two entry points:
  - /student/use_of_work  — authenticated, @login_required, session-based
  - /student/consent/<token>  — unauthenticated, token-based (no @login_required)

Both render the same template: student/consent/manage.html
"""

from datetime import datetime

from flask import abort, redirect, render_template, request, url_for
from flask_security.forms import Form

from ..database import db
from ..models import (
    ConsentAuditEvent,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    User,
)
from ..models.project_class import ProjectClassConfig, SubmissionPeriodRecord
from . import student


class ConsentRecordForm(Form):
    """WTForms backing form for token-based consent updates. CSRF is disabled because
    the token-in-URL provides equivalent anti-CSRF protection for unauthenticated requests."""

    class Meta:
        csrf = False


class AuthConsentRecordForm(Form):
    """WTForms backing form for session-authenticated consent updates. CSRF is enabled."""

    pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _get_eligible_records_for_user(user: User):
    """
    Return all SubmissionRecords that are consent-eligible for this User,
    ordered by most recent first (by config year descending).
    Eligible: period.closed is True AND report_grade is not None.
    """
    from sqlalchemy import desc

    return (
        db.session.query(SubmissionRecord)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
        .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
        .filter(
            SubmittingStudent.student_id == user.id,
            SubmissionPeriodRecord.closed.is_(True),
            SubmissionRecord.report_grade.isnot(None),
        )
        .order_by(desc(ProjectClassConfig.year))
        .all()
    )


def _request_supervisor_approval(record: SubmissionRecord):
    """
    Send a one-time approval-request email to all responsible supervisors for this record.
    Only called when exemplar_supervisor_approved IS None — i.e. the supervisor has never
    been contacted. Subsequent student consent changes do not trigger further emails.
    """
    from flask import current_app, url_for

    from ..models import EmailTemplate, EmailWorkflow, EmailWorkflowItem
    from ..models.emails import EmailTemplateTypesMixin, encode_email_payload

    pclass = record.period.config.project_class
    config = record.period.config

    tmpl = EmailTemplate.find_template_(
        EmailTemplateTypesMixin.CONSENT_SUPERVISOR_APPROVAL_REQUEST,
        pclass=pclass,
    )
    if tmpl is None:
        current_app.logger.warning(
            f"No CONSENT_SUPERVISOR_APPROVAL_REQUEST template for pclass #{pclass.id}; supervisor approval email not sent for record #{record.id}"
        )
        return

    supervisor_roles = record.roles.filter(
        SubmissionRole.role.in_(
            [
                SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ]
        )
    ).all()

    if not supervisor_roles:
        current_app.logger.warning(f"No supervisor roles found for record #{record.id}; supervisor approval email not sent")
        return

    workflow = EmailWorkflow.build_(
        name=f"Exemplar approval request: record #{record.id}",
        template=tmpl,
        pclasses=[pclass],
        send_time=datetime.now(),
    )
    db.session.add(workflow)
    db.session.flush()

    approval_url = url_for("faculty.my_students", _external=True)

    for role in supervisor_roles:
        supervisor_user = role.user
        if supervisor_user is None or not supervisor_user.email:
            continue
        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload(
                {
                    "pclass_name": pclass.name,
                    "year_a": config.submit_year_a,
                    "year_b": config.submit_year_b,
                }
            ),
            body_payload=encode_email_payload(
                {
                    "record": record,
                    "role": role,
                    "pclass": pclass,
                    "config": config,
                    "approval_url": approval_url,
                }
            ),
            recipient_list=[supervisor_user.email],
        )
        workflow.items.append(item)


def _apply_consent_update(record: SubmissionRecord, actor_id, ip_address: str) -> bool:
    """
    Read consent toggle values from the current POST request and apply them
    to the given SubmissionRecord, writing ConsentAuditEvent rows as needed.
    Returns True if any changes were made.
    """
    now = datetime.now()
    changed = False

    exemplar_new = request.form.get("exemplar_consent") == "1"
    openday_new = request.form.get("openday_consent") == "1"

    # --- Exemplar consent ---
    exemplar_currently_active = record.exemplar_consent_active

    if exemplar_new and not exemplar_currently_active:
        first_ever_grant = record.exemplar_consent_granted_at is None
        if first_ever_grant:
            record.exemplar_consent_granted_at = now
        record.exemplar_consent_withdrawn = False
        record.exemplar_consent_withdrawn_at = None
        db.session.add(
            ConsentAuditEvent(
                record_id=record.id,
                actor_id=actor_id,
                event_type=ConsentAuditEvent.EXEMPLAR_GRANTED,
                timestamp=now,
                ip_address=ip_address,
            )
        )
        if first_ever_grant and record.exemplar_supervisor_approved is None:
            _request_supervisor_approval(record)
        changed = True

    elif not exemplar_new and exemplar_currently_active:
        record.exemplar_consent_withdrawn = True
        record.exemplar_consent_withdrawn_at = now
        db.session.add(
            ConsentAuditEvent(
                record_id=record.id,
                actor_id=actor_id,
                event_type=ConsentAuditEvent.EXEMPLAR_WITHDRAWN,
                timestamp=now,
                ip_address=ip_address,
            )
        )
        changed = True

    # --- Open day consent ---
    openday_currently_active = record.openday_consent_active

    if openday_new and not openday_currently_active:
        if record.openday_consent_granted_at is None:
            record.openday_consent_granted_at = now
        record.openday_consent_withdrawn = False
        record.openday_consent_withdrawn_at = None
        db.session.add(
            ConsentAuditEvent(
                record_id=record.id,
                actor_id=actor_id,
                event_type=ConsentAuditEvent.OPENDAY_GRANTED,
                timestamp=now,
                ip_address=ip_address,
            )
        )
        changed = True

    elif not openday_new and openday_currently_active:
        record.openday_consent_withdrawn = True
        record.openday_consent_withdrawn_at = now
        db.session.add(
            ConsentAuditEvent(
                record_id=record.id,
                actor_id=actor_id,
                event_type=ConsentAuditEvent.OPENDAY_WITHDRAWN,
                timestamp=now,
                ip_address=ip_address,
            )
        )
        changed = True

    return changed


# ---------------------------------------------------------------------------
# Token-authenticated route (no Flask session required)
# ---------------------------------------------------------------------------


@student.route("/consent/<string:token>", methods=["GET", "POST"])
def consent_by_token(token):
    """
    Render and process the consent management page for a student identified
    by their User.consent_token. No Flask-Security session is required.

    GET  — render consent form for all eligible SubmissionRecords
    POST — update consent for a single SubmissionRecord identified by the
           hidden 'record_id' field; redirect back to GET on success
    """
    user: User = User.query.filter_by(consent_token=token).first()
    if user is None:
        abort(404)

    ip = request.remote_addr

    if request.method == "POST":
        record_id = request.form.get("record_id", type=int)
        if record_id is None:
            abort(400)

        record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
        if record is None:
            abort(404)

        if record.owner is None or record.owner.student_id != user.id:
            abort(403)

        if not record.consent_eligible:
            abort(403)

        changed = _apply_consent_update(record, actor_id=None, ip_address=ip)

        if changed:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                records = _get_eligible_records_for_user(user)
                return render_template(
                    "student/consent/manage.html",
                    user=user,
                    records=records,
                    token_mode=True,
                    token=token,
                    form=ConsentRecordForm(),
                    error="An error occurred saving your preferences. Please try again.",
                )

        return redirect(url_for("student.consent_by_token", token=token))

    records = _get_eligible_records_for_user(user)
    return render_template(
        "student/consent/manage.html",
        user=user,
        records=records,
        token_mode=True,
        token=token,
        form=ConsentRecordForm(),
        error=None,
    )
