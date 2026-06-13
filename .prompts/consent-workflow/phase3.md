# Consent workflow — Phase 3: Convenor dispatch

## Objective

Add a "Send consent invitations" control to the convenor's Submission Management
panel on `status.html`. When dispatched, this generates `User.consent_token`
values (if not already set), builds a single `EmailWorkflow` with one
`EmailWorkflowItem` per eligible student, and uses the standard Celery callback
mechanism to set `SubmissionRecord.consent_invitation_sent_at` after successful
send. A reminder dispatch follows the same pattern but uses
`consent_reminder_sent_at`.

---

## Reconnaissance

Read the following before writing any code:

1. `app/templates/convenor/dashboard/status.html`
    - Locate the `SUBMISSION MANAGEMENT` panel (search for `SUBMISSION MANAGEMENT`).
    - Locate the `Submitters` sub-panel within it (search for `Submitters`).
    - Identify exactly where to insert the new "Consent invitations" tile —
      it should appear after the Submitters tile, as a peer section.
    - Note the visual pattern used for existing action tiles in this panel:
      border, background colour, button styling.

2. `app/models/emails.py`
    - Re-read `EmailWorkflow.build_()` and `EmailWorkflowItem.build_()` signatures.
    - Re-read the `callbacks` field docstring: callbacks are a JSON list of
      `{"task": <task_name>, "args": [...], "kwargs": {...}}` dicts, where the
      PK of the newly created `EmailLog` item is prepended to `args` at send time.
    - Note `EmailTemplateTypesMixin.CONSENT_INVITATION = 70` (added in Phase 1)
      and `CONSENT_REMINDER = 71`.

3. `app/tasks/` — find the existing task that handles Celery callbacks from
   the email send pipeline. Search for where `callbacks_list` is consumed and
   tasks are dispatched. Understand the task name format used.

4. `app/convenor/views.py` (or wherever convenor routes live)
    - Find an existing POST route that dispatches an `EmailWorkflow` to identify
      the correct pattern (template lookup, workflow construction, db.session.add,
      db.session.commit, flash message).
    - Note the `@roles_accepted` decorator pattern used.

5. `app/shared/validators.py`
    - Find `validate_is_convenor` — used to guard convenor-only routes.

---

## Changes

### 1. New Celery task: `app/tasks/consent.py`

Create `app/tasks/consent.py`:

```python
"""
Celery tasks for the consent workflow.
"""
from datetime import datetime

from celery.utils.log import get_task_logger

from ..database import db
from ..models import SubmissionRecord

logger = get_task_logger(__name__)


def record_consent_invitation_sent(email_log_id: int, record_id: int):
    """
    Celery callback invoked after a consent invitation EmailWorkflowItem
    is successfully sent. Sets SubmissionRecord.consent_invitation_sent_at.

    Called by the email send pipeline with (email_log_id, record_id).
    email_log_id is prepended automatically by the callback dispatcher.
    """
    record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
    if record is None:
        logger.warning(
            f"record_consent_invitation_sent: SubmissionRecord #{record_id} not found"
        )
        return

    if record.consent_invitation_sent_at is None:
        record.consent_invitation_sent_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.exception(
                f"record_consent_invitation_sent: failed to update record #{record_id}",
                exc_info=e,
            )


def record_consent_reminder_sent(email_log_id: int, record_id: int):
    """
    Celery callback for consent reminder emails.
    Sets SubmissionRecord.consent_reminder_sent_at.
    """
    record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
    if record is None:
        logger.warning(
            f"record_consent_reminder_sent: SubmissionRecord #{record_id} not found"
        )
        return

    if record.consent_reminder_sent_at is None:
        record.consent_reminder_sent_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.exception(
                f"record_consent_reminder_sent: failed to update record #{record_id}",
                exc_info=e,
            )
```

Register these functions as Celery tasks in the same way as existing callback
tasks. Check the existing pattern in `app/tasks/` — look for how other
`record_*_sent` functions are registered (likely via `@celery.task` decorator
or by registering in `app/tasks/__init__.py`).

The task names (as stored in the `callbacks` JSON field) must match the fully
qualified Celery task names. Check the existing naming convention in the
codebase (e.g. `app.tasks.emails.record_marking_email_sent` or similar) and
follow it exactly.

### 2. New convenor route: dispatch consent invitations

Add the following route to the appropriate convenor views file. Identify the
correct file by searching for other submission-management POST routes such as
the period-close route.

```python
@convenor.route("/dispatch_consent_invitations/<int:config_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def dispatch_consent_invitations(config_id):
    """
    Dispatch consent invitation emails to all eligible submitters for a
    ProjectClassConfig who have not yet been invited.

    Eligibility per SubmissionRecord:
      - period.closed is True
      - report_grade is not None
      - consent_invitation_sent_at is None  (not yet invited)

    Generates User.consent_token if not already set.
    Builds one EmailWorkflow, one EmailWorkflowItem per eligible record.
    Sets consent_invitation_sent_at via Celery callback after successful send.
    """
    import uuid
    from datetime import datetime

    from ..models import (
        EmailTemplate, EmailWorkflow, EmailWorkflowItem,
        ProjectClassConfig, SubmissionRecord, SubmittingStudent, User,
    )
    from ..models.emails import EmailTemplateTypesMixin, encode_email_payload
    from ..shared.validators import validate_is_convenor
    from ..tasks.consent import record_consent_invitation_sent

    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)
    pclass = config.project_class

    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    # Find eligible records
    eligible = (
        db.session.query(SubmissionRecord)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
        .filter(
            SubmittingStudent.config_id == config_id,
            SubmissionPeriodRecord.closed.is_(True),
            SubmissionRecord.report_grade.isnot(None),
            SubmissionRecord.consent_invitation_sent_at.is_(None),
        )
        .all()
    )

    if not eligible:
        flash("No eligible students without an existing invitation.", "info")
        return redirect(redirect_url())

    # Look up email template
    tmpl = EmailTemplate.find_template_(
        EmailTemplateTypesMixin.CONSENT_INVITATION,
        pclass_id=pclass.id,
    )
    if tmpl is None:
        flash(
            "No consent invitation email template is configured for this project class. "
            "Please ask an administrator to create one.",
            "danger",
        )
        return redirect(redirect_url())

    # Build workflow
    workflow = EmailWorkflow.build_(
        name=f"Consent invitations: {pclass.name} {config.submit_year_a}–{config.submit_year_b}",
        template=tmpl,
        pclasses=[pclass],
        creator=current_user,
    )
    db.session.add(workflow)
    db.session.flush()

    count = 0
    for record in eligible:
        student_user: User = record.owner.student

        # Generate consent_token eagerly if not already set
        if student_user.consent_token is None:
            student_user.consent_token = str(uuid.uuid4())

        consent_url = url_for(
            "student.consent_by_token",
            token=student_user.consent_token,
            _external=True,
        )

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({
                "pclass_name": pclass.name,
                "year_a": config.submit_year_a,
                "year_b": config.submit_year_b,
            }),
            body_payload=encode_email_payload({
                "record": record,
                "pclass": pclass,
                "config": config,
                "consent_url": consent_url,
                "grade": record.report_grade,
            }),
            recipient_list=[student_user.email],
            callbacks=[
                {
                    "task": "app.tasks.consent.record_consent_invitation_sent",
                    "args": [record.id],
                    "kwargs": {},
                }
            ],
            creator=current_user,
        )
        workflow.items.append(item)
        count += 1

    try:
        log_db_commit(
            f"Dispatched consent invitations for {count} students "
            f"({pclass.name} {config.submit_year_a}–{config.submit_year_b})",
            user=current_user,
            project_classes=pclass,
        )
        flash(
            f"Consent invitation emails queued for {count} student(s).",
            "success",
        )
    except Exception as e:
        db.session.rollback()
        flash("An error occurred dispatching invitation emails.", "danger")
        current_app.logger.exception("dispatch_consent_invitations failed", exc_info=e)

    return redirect(redirect_url())
```

Also add a parallel `dispatch_consent_reminders/<int:config_id>` route with
the same structure, but:

- Filter for records where `consent_invitation_sent_at IS NOT NULL` AND
  `consent_reminder_sent_at IS NULL` AND neither consent has been given
  (i.e. `exemplar_consent_granted_at IS NULL` AND `openday_consent_granted_at IS NULL`).
- Use `EmailTemplateTypesMixin.CONSENT_REMINDER = 71`.
- Use the `record_consent_reminder_sent` callback task.
- Set `consent_reminder_sent_at` via the callback (not directly in the route).

### 3. `app/templates/convenor/dashboard/status.html` — consent tile

Locate the `Submitters` sub-panel in the Submission Management column and add
the following tile **after** it, as a new peer section within the same period
panel. Use the existing `border rounded p-2 mb-2 mt-2` tile pattern visible in
the template.

The tile must:

- Only render when `period.closed` is True (the period must be closed for
  consent invitations to be valid).
- Show a summary: `N eligible · M invited · P consented` where:
    - N = count of records where `consent_eligible` is True
    - M = count of records where `consent_invitation_sent_at IS NOT NULL`
    - P = count of records where `exemplar_consent_active OR openday_consent_active`
- Show a **disabled** "Send invitations" button when `N == M` (all eligible
  students already invited).
- Show an **active** "Send invitations" button (POST to
  `convenor.dispatch_consent_invitations`) when `N > M`.
- Show a "Send reminder" button (POST to `convenor.dispatch_consent_reminders`)
  only when at least one student has been invited but has not yet responded AND
  `consent_reminder_sent_at IS NULL` for some records. Add a warning badge
  "reminder already sent" when a reminder has been sent.

Compute the counts in the route that renders `status.html` and pass them as
template variables, following the existing pattern for how period statistics
are passed.

---

## Verification

```bash
# Confirm new routes are registered
flask routes | grep consent

# Confirm Celery task names resolve
python3 -c "
from app.tasks.consent import record_consent_invitation_sent, record_consent_reminder_sent
print('Tasks importable')
"

# Confirm template renders without error by visiting the convenor
# overview for a project class with a closed period and graded submissions
```