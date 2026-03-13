#
# Created by David Seery on 09/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from flask import current_app, render_template_string
from flask_mailman import EmailMultiAlternatives
from html2text import HTML2Text
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH
from .models import ColouredLabelMixin, EditingMetadataMixin, ProjectClass
from .tenants import Tenant

email_template_to_labels = db.Table(
    "email_templates_to_labels",
    db.Column(
        "email_template_id",
        db.Integer(),
        db.ForeignKey("email_templates.id"),
        primary_key=True,
    ),
    db.Column(
        "label_id",
        db.Integer(),
        db.ForeignKey("email_template_labels.id"),
        primary_key=True,
    ),
)


class EmailTemplateTypesMixin:
    # backups
    BACKUP_REPORT_THINNING = 1

    # close_selection
    CLOSE_SELECTION_CONVENOR = 2

    # go_live
    GO_LIVE_CONVENOR = 3
    GO_LIVE_FACULTY = 4
    GO_LIVE_SELECTOR = 5

    # maintenance
    MAINTENANCE_LOST_ASSETS = 6
    MAINTENANCE_UNATTACHED_ASSETS = 7

    # marking
    MARKING_MARKER = 8
    MARKING_SUPERVISOR = 9

    # matching
    MATCHING_DRAFT_NOTIFY_FACULTY = 10
    MATCHING_DRAFT_NOTIFY_STUDENTS = 11
    MATCHING_DRAFT_UNNEEDED_FACULTY = 12
    MATCHING_FINAL_NOTIFY_FACULTY = 13
    MATCHING_FINAL_NOTIFY_STUDENTS = 14
    MATCHING_FINAL_UNNEEDED_FACULTY = 15
    MATCHING_GENERATED = 16
    MATCHING_NOTIFY_EXCEL_REPORT = 17

    # notifications
    NOTIFICATIONS_REQUEST_MEETING = 18
    NOTIFICATIONS_FACULTY_ROLLUP = 19
    NOTIFICATIONS_FACULTY_SINGLE = 20
    NOTIFICATIONS_STUDENT_ROLLUP = 21
    NOTIFICATIONS_STUDENT_SINGLE = 22

    # project_confirmation
    PROJECT_CONFIRMATION_REMINDER = 23
    PROJECT_CONFIRMATION_REQUESTED = 24
    PROJECT_CONFIRMATION_NEW_COMMENT = 25
    PROJECT_CONFIRMATION_REVISE_REQUEST = 26

    # push_feedback
    PUSH_FEEDBACK_PUSH_TO_MARKER = 27
    PUSH_FEEDBACK_PUSH_TO_STUDENT = 28
    PUSH_FEEDBACK_PUSH_TO_SUPERVISOR = 29

    # scheduling
    SCHEDULING_AVAILABILITY_REMINDER = 30
    SCHEDULING_AVAILABILITY_REQUEST = 31
    SCHEDULING_DRAFT_NOTIFY_FACULTY = 32
    SCHEDULING_DRAFT_NOTIFY_STUDENTS = 33
    SCHEDULING_DRAFT_UNNEEDED_FACULTY = 34
    SCHEDULING_FINAL_NOTIFY_FACULTY = 35
    SCHEDULING_FINAL_NOTIFY_STUDENTS = 36
    SCHEDULING_FINAL_UNNEEDED_FACULTY = 37
    SCHEDULING_GENERATED = 38

    # services
    SERVICES_CC_EMAIL = 39
    SERVICES_SEND_EMAIL = 40

    # student_notifications
    STUDENT_NOTIFICATIONS_CHOICES_RECEIVED = 41
    STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY = 42

    # system
    SYSTEM_GARBAGE_COLLECTION = 43


class EmailTemplateLabel(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Represents a label applied to a backup
    """

    __tablename__ = "email_template_labels"

    # unique identifier used as primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name of label
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    def make_label(self, text=None):
        label_text = text if text is not None else self.name
        return self._make_label(text=label_text)


class EmailTemplate(db.Model, EmailTemplateTypesMixin, EditingMetadataMixin):
    __tablename__ = "email_templates"

    id = db.Column(db.Integer(), primary_key=True)

    # active flag
    active = db.Column(db.Boolean(), nullable=False, default=True)

    # labels applied to this template
    labels = db.relationship(
        "EmailTemplateLabel",
        secondary=email_template_to_labels,
        lazy="dynamic",
        backref=db.backref("ttemplates", lazy="dynamic"),
    )

    # tenant, if specified
    # if not specified, this template is taken to apply globally
    # otherwise it is taken to apply to all project classes in the tenant, unless they in turn have an override
    tenant_id = db.Column(db.Integer(), db.ForeignKey("tenants.id"), nullable=True)
    tenant = db.relationship(
        "Tenant", backref=db.backref("email_templates", lazy="dynamic")
    )

    # project class, if specified
    pclass_id = db.Column(
        db.Integer(), db.ForeignKey("project_classes.id"), nullable=True
    )
    pclass = db.relationship(
        "ProjectClass", backref=db.backref("email_templates", lazy="dynamic")
    )

    # specify the type of this email, drawn from EmailTemplateTypesMixin
    type = db.Column(db.Integer(), nullable=False)

    # specify the subject line
    subject = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False
    )

    # specify the body of the email in HTML format
    # we autogenerate a text equivalent
    html_body = db.Column(db.Text(), nullable=False)

    # comment/description field
    comment = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True
    )

    # version number, allowing multiple versions of an email to exist simultaneously, rather than over-writing previous versions
    version = db.Column(db.Integer(), nullable=False)

    # last used
    last_used = db.Column(db.DateTime(), nullable=True)

    @staticmethod
    def apply_(
        template_type: int,
        to: List[str],
        from_email: Optional[str] = None,
        reply_to: Optional[List[str]] = None,
        subject_kwargs: Optional[Dict[str, Any]] = None,
        body_kwargs: Optional[Dict[str, Any]] = None,
        body_attachments: Optional[Dict[str, Callable]] = None,
        tenant=None,
        pclass=None,
    ):
        """
        Apply a template to produce an email message.
        :param template_type:
        :param to:
        :param from_email:
        :param reply_to:
        :param subject_kwargs:
        :param body_kwargs:
        :param body_attachments:
        :param tenant:
        :param pclass:
        :return:
        """
        tenant_id = None
        if isinstance(tenant, int):
            tenant_id = tenant
        elif isinstance(tenant, Tenant):
            tenant_id = tenant.id
        elif tenant is None:
            pass
        else:
            raise RuntimeError(
                f'Invalid tenant type "{type(tenant)}" (value="{tenant}") in EmailTemplate.apply_()'
            )

        if from_email is None:
            from_email = current_app.config["MAIL_DEFAULT_SENDER"]

        if reply_to is None:
            reply_to = [current_app.config["MAIL_REPLY_TO"]]

        pclass_id = None
        if isinstance(pclass, int):
            pclass_obj = db.session.query(ProjectClass).filter_by(id=pclass).first()
            pclass_id = pclass
            if tenant_id is None:
                tenant_id = pclass_obj.tenant_id
            elif tenant_id != pclass_obj.tenant_id:
                raise RuntimeError(
                    f'Tenant mismatch between pclass "{pclass_obj.name}" and tenant "{tenant.name}" in EmailTemplate.apply_()'
                )
        elif isinstance(pclass, ProjectClass):
            pclass_id = pclass.id
            if tenant_id is None:
                tenant_id = pclass.tenant_id
            elif tenant_id != pclass.tenant_id:
                raise RuntimeError(
                    f'Tenant mismatch between pclass "{pclass.name}" and tenant "{tenant.name}" in EmailTemplate.apply_()'
                )
        elif pclass is None:
            pass
        else:
            raise RuntimeError(
                f'Invalid project class type "{type(pclass)}" (value="{pclass}") in EmailTemplate.apply_()'
            )

        if not isinstance(to, Iterable):
            raise RuntimeError(
                f'Invalid recipient list type "{type(to)}" (value="{to}") in EmailTemplate.apply_()'
            )

        if not isinstance(reply_to, Iterable):
            raise RuntimeError(
                f'Invalid reply_to list type "{type(reply_to)}" (value="{reply_to}") in EmailTemplate.apply_()'
            )

        # find active template at highest level of override
        templ_query = db.session.query(EmailTemplate).filter(
            EmailTemplate.type == template_type, EmailTemplate.active.is_(True)
        )
        if tenant_id is not None:
            templ_query = templ_query.filter(
                or_(
                    EmailTemplate.tenant_id == tenant_id,
                    EmailTemplate.tenant_id.is_(None),
                )
            )
        if pclass_id is not None:
            templ_query = templ_query.filter(
                or_(
                    EmailTemplate.pclass_id == pclass_id,
                    EmailTemplate.pclass_id.is_(None),
                )
            )
        templ_query = templ_query.order_by(
            EmailTemplate.tenant_id,
            EmailTemplate.pclass_id,
            EmailTemplate.version.desc(),
        )

        template: Optional[EmailTemplate] = templ_query.first()

        if template is None:
            raise RuntimeError(
                f"No active template found for EmailTemplate type {template_type}"
            )

        # format subject string
        subject_str: str = (
            template.subject.format(**subject_kwargs)
            if subject_kwargs is not None
            else template.subject
        )

        msg = EmailMultiAlternatives(
            subject=subject_str,
            from_email=from_email,
            reply_to=reply_to,
            to=to,
        )

        # perform any attachments, storing output in body_kwargs where it can be used if desired
        if body_attachments is not None:
            for label, callable in body_attachments.items():
                output = callable(msg)
                if label not in body_kwargs:
                    body_kwargs[label] = output

        # format HTML body text
        html_str: str = (
            render_template_string(template.html_body, **body_kwargs)
            if body_kwargs is not None
            else template.html_body
        )

        # generate plain text version of HTML body (html2text basically produces Markdown)
        h = HTML2Text()
        plain_str: str = h.handle(html_str)

        msg.body = plain_str
        msg.attach_alternative(html_str, "text/html")

        # update last_used field for this template
        try:
            template.last_used = datetime.now()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            pass

        return msg
