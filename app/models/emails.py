#
# Created by David Seery on 09/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import json
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from flask import current_app, render_template_string, url_for
from flask_mailman import EmailMultiAlternatives
from html2text import HTML2Text
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from .assets import GeneratedAsset, SubmittedAsset, TemporaryAsset
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin
from .project_class import ProjectClass
from .tenants import Tenant

# default max attachment size is 10 Mb
DEFAULT_MAX_ATTACHMENT_SIZE = 1024 * 1024 * 10

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
    ## SYSTEM EMAILS

    # backups
    BACKUP_REPORT_THINNING = 1

    # maintenance
    MAINTENANCE_LOST_ASSETS = 6
    MAINTENANCE_UNATTACHED_ASSETS = 7

    # services
    SERVICES_CC_EMAIL = 39
    SERVICES_SEND_EMAIL = 40

    # system
    SYSTEM_GARBAGE_COLLECTION = 43

    ## TENANT SPECIALIZABLE

    # matching
    MATCHING_DRAFT_NOTIFY_FACULTY = 10
    MATCHING_DRAFT_NOTIFY_STUDENTS = 11
    MATCHING_DRAFT_UNNEEDED_FACULTY = 12
    MATCHING_FINAL_NOTIFY_FACULTY = 13
    MATCHING_FINAL_NOTIFY_STUDENTS = 14
    MATCHING_FINAL_UNNEEDED_FACULTY = 15
    MATCHING_GENERATED = 16
    MATCHING_NOTIFY_EXCEL_REPORT = 17

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

    ## PROJECT CLASS SPECIALIZABLE

    # close_selection
    CLOSE_SELECTION_CONVENOR = 2

    # go_live
    GO_LIVE_CONVENOR = 3
    GO_LIVE_FACULTY = 4
    GO_LIVE_SELECTOR = 5

    # marking
    MARKING_MARKER = 8
    MARKING_SUPERVISOR = 9

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

    # student_notifications
    STUDENT_NOTIFICATIONS_CHOICES_RECEIVED = 41
    STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY = 42

    # attendance reminder
    ATTENDANCE_PROMPT = 44


# Human-readable names for each template type
_TYPE_NAMES = {
    ## SYSTEM ONLY
    EmailTemplateTypesMixin.BACKUP_REPORT_THINNING: "Backup: Report thinning",
    EmailTemplateTypesMixin.MAINTENANCE_LOST_ASSETS: "Maintenance: Lost assets",
    EmailTemplateTypesMixin.MAINTENANCE_UNATTACHED_ASSETS: "Maintenance: Unattached assets",
    EmailTemplateTypesMixin.SERVICES_CC_EMAIL: "Services: CC email",
    EmailTemplateTypesMixin.SERVICES_SEND_EMAIL: "Services: Send email",
    EmailTemplateTypesMixin.SYSTEM_GARBAGE_COLLECTION: "System: Garbage collection",
    ## TENANT SPECIALIZABLE
    EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_FACULTY: "Matching: Draft notify faculty",
    EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_STUDENTS: "Matching: Draft notify students",
    EmailTemplateTypesMixin.MATCHING_DRAFT_UNNEEDED_FACULTY: "Matching: Draft unneeded faculty",
    EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_FACULTY: "Matching: Final notify faculty",
    EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_STUDENTS: "Matching: Final notify students",
    EmailTemplateTypesMixin.MATCHING_FINAL_UNNEEDED_FACULTY: "Matching: Final unneeded faculty",
    EmailTemplateTypesMixin.MATCHING_GENERATED: "Matching: Generated",
    EmailTemplateTypesMixin.MATCHING_NOTIFY_EXCEL_REPORT: "Matching: Notify Excel report",
    EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REMINDER: "Scheduling: Availability reminder",
    EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REQUEST: "Scheduling: Availability request",
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_FACULTY: "Scheduling: Draft notify faculty",
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_STUDENTS: "Scheduling: Draft notify students",
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_UNNEEDED_FACULTY: "Scheduling: Draft unneeded faculty",
    EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_FACULTY: "Scheduling: Final notify faculty",
    EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_STUDENTS: "Scheduling: Final notify students",
    EmailTemplateTypesMixin.SCHEDULING_FINAL_UNNEEDED_FACULTY: "Scheduling: Final unneeded faculty",
    EmailTemplateTypesMixin.SCHEDULING_GENERATED: "Scheduling: Generated",
    ## PROJECT CLASS SPECIALIZABLE
    EmailTemplateTypesMixin.CLOSE_SELECTION_CONVENOR: "Close selection: Convenor",
    EmailTemplateTypesMixin.GO_LIVE_CONVENOR: "Go live: Convenor",
    EmailTemplateTypesMixin.GO_LIVE_FACULTY: "Go live: Faculty",
    EmailTemplateTypesMixin.GO_LIVE_SELECTOR: "Go live: Selector",
    EmailTemplateTypesMixin.MARKING_MARKER: "Marking: Marker",
    EmailTemplateTypesMixin.MARKING_SUPERVISOR: "Marking: Supervisor",
    EmailTemplateTypesMixin.NOTIFICATIONS_REQUEST_MEETING: "Notifications: Request meeting",
    EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_ROLLUP: "Notifications: Faculty rollup",
    EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_SINGLE: "Notifications: Faculty single",
    EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_ROLLUP: "Notifications: Student rollup",
    EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_SINGLE: "Notifications: Student single",
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REMINDER: "Project confirmation: Reminder",
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REQUESTED: "Project confirmation: Requested",
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_NEW_COMMENT: "Project confirmation: New comment",
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REVISE_REQUEST: "Project confirmation: Revise request",
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_MARKER: "Push feedback: To marker",
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_STUDENT: "Push feedback: To student",
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR: "Push feedback: To supervisor",
    EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED: "Student notifications: Choices received",
    EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY: "Student notifications: Choices received (proxy)",
    EmailTemplateTypesMixin.ATTENDANCE_PROMPT: "Attendance: Prompt",
}

TENANT_SPECIALIZABLE_TEMPLATES = [
    ## TENANT SPECIALIZABLE ONLY
    EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.MATCHING_DRAFT_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.MATCHING_FINAL_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.MATCHING_GENERATED,
    EmailTemplateTypesMixin.MATCHING_NOTIFY_EXCEL_REPORT,
    EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REMINDER,
    EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REQUEST,
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.SCHEDULING_FINAL_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_GENERATED,
    ## PROJECT CLASS SPECIALIZABLE
    EmailTemplateTypesMixin.CLOSE_SELECTION_CONVENOR,
    EmailTemplateTypesMixin.GO_LIVE_CONVENOR,
    EmailTemplateTypesMixin.GO_LIVE_FACULTY,
    EmailTemplateTypesMixin.GO_LIVE_SELECTOR,
    EmailTemplateTypesMixin.MARKING_MARKER,
    EmailTemplateTypesMixin.MARKING_SUPERVISOR,
    EmailTemplateTypesMixin.NOTIFICATIONS_REQUEST_MEETING,
    EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_ROLLUP,
    EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_SINGLE,
    EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_ROLLUP,
    EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_SINGLE,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REMINDER,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REQUESTED,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_NEW_COMMENT,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REVISE_REQUEST,
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_MARKER,
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_STUDENT,
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR,
    EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED,
    EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY,
    EmailTemplateTypesMixin.ATTENDANCE_PROMPT,
]

PCLASS_SPECIALIZABLE_TEMPLATES = [
    ## TENANT SPECIALIZABLE ONLY
    EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.MATCHING_DRAFT_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.MATCHING_FINAL_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REMINDER,
    EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REQUEST,
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.SCHEDULING_DRAFT_UNNEEDED_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_FACULTY,
    EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_STUDENTS,
    EmailTemplateTypesMixin.SCHEDULING_FINAL_UNNEEDED_FACULTY,
    ## PROJECT CLASS SPECIALIZABLE
    EmailTemplateTypesMixin.CLOSE_SELECTION_CONVENOR,
    EmailTemplateTypesMixin.GO_LIVE_CONVENOR,
    EmailTemplateTypesMixin.GO_LIVE_FACULTY,
    EmailTemplateTypesMixin.GO_LIVE_SELECTOR,
    EmailTemplateTypesMixin.MARKING_MARKER,
    EmailTemplateTypesMixin.MARKING_SUPERVISOR,
    EmailTemplateTypesMixin.NOTIFICATIONS_REQUEST_MEETING,
    EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_ROLLUP,
    EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_SINGLE,
    EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_ROLLUP,
    EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_SINGLE,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REMINDER,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REQUESTED,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_NEW_COMMENT,
    EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REVISE_REQUEST,
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_MARKER,
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_STUDENT,
    EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR,
    EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED,
    EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY,
    EmailTemplateTypesMixin.ATTENDANCE_PROMPT,
]


def _resolve_tenant_and_pclass(tenant, pclass) -> Tuple[Optional[int], Optional[int]]:
    """
    Resolve the tenant and pclass arguments to their integer IDs.
    Returns (tenant_id, pclass_id).
    """
    tenant_id = None
    if isinstance(tenant, int):
        tenant_id = tenant
    elif isinstance(tenant, Tenant):
        tenant_id = tenant.id
    elif tenant is not None:
        raise RuntimeError(
            f'Invalid tenant type "{type(tenant)}" (value="{tenant}") in EmailTemplate.apply_()'
        )

    pclass_id = None
    if isinstance(pclass, int):
        pclass_obj = db.session.query(ProjectClass).filter_by(id=pclass).first()
        pclass_id = pclass
        if tenant_id is None:
            tenant_id = pclass_obj.tenant_id
        elif tenant_id != pclass_obj.tenant_id:
            raise RuntimeError(
                f'Tenant mismatch between pclass "{pclass_obj.name}" and tenant in EmailTemplate.apply_()'
            )
    elif isinstance(pclass, ProjectClass):
        pclass_id = pclass.id
        if tenant_id is None:
            tenant_id = pclass.tenant_id
        elif tenant_id != pclass.tenant_id:
            raise RuntimeError(
                f'Tenant mismatch between pclass "{pclass.name}" and tenant in EmailTemplate.apply_()'
            )
    elif pclass is not None:
        raise RuntimeError(
            f'Invalid project class type "{type(pclass)}" (value="{pclass}") in EmailTemplate.apply_()'
        )

    return tenant_id, pclass_id


def _find_template(
        template_type: int,
        tenant_id: Optional[int],
        pclass_id: Optional[int],
) -> "EmailTemplate":
    """
    Find the active EmailTemplate that best matches the given type, tenant, and pclass,
    preferring the most-specific (pclass > tenant > global) and highest-versioned entry.
    """
    query = db.session.query(EmailTemplate).filter(
        EmailTemplate.type == template_type, EmailTemplate.active.is_(True)
    )
    if tenant_id is not None:
        query = query.filter(
            or_(EmailTemplate.tenant_id == tenant_id, EmailTemplate.tenant_id.is_(None))
        )
    if pclass_id is not None:
        query = query.filter(
            or_(EmailTemplate.pclass_id == pclass_id, EmailTemplate.pclass_id.is_(None))
        )
    query = query.order_by(
        EmailTemplate.pclass_id.desc(),
        EmailTemplate.tenant_id.desc(),
        EmailTemplate.version.desc(),
    )

    template = query.first()
    if template is None:
        raise RuntimeError(
            f"No active template found for EmailTemplate type {template_type}"
        )
    return template


# Manifest entry: (attached, display_name, download_url, description)
_ManifestEntry = Tuple[bool, str, Optional[str], Optional[str]]


def _process_attachments(
        msg: EmailMultiAlternatives,
        attachments,
        max_attachment_size: int,
) -> List[_ManifestEntry]:
    """
    Iterate over EmailWorkflowItemAttachment instances, attaching each file to *msg*
    when the running total would not exceed *max_attachment_size* (bytes), or recording
    a download link otherwise.  Returns a manifest list of _ManifestEntry tuples.
    """
    from ..shared.asset_tools import AssetCloudAdapter

    if isinstance(attachments, EmailWorkflowItemAttachment):
        attachment_list = [attachments]
    elif isinstance(attachments, Iterable):
        attachment_list = list(attachments)
    else:
        raise RuntimeError(
            f'Invalid attachments type "{type(attachments)}" in EmailTemplate.apply_()'
        )

    buckets = current_app.config.get("OBJECT_STORAGE_BUCKETS", {})
    current_size = 0
    manifest: List[_ManifestEntry] = []

    for attachment in attachment_list:
        # determine which asset type this attachment points to
        if attachment.generated_asset is not None:
            asset = attachment.generated_asset
            endpoint = "download_generated_asset"
        elif attachment.submitted_asset is not None:
            asset = attachment.submitted_asset
            endpoint = "download_submitted_asset"
        elif attachment.temporary_asset is not None:
            asset = attachment.temporary_asset
            endpoint = None  # no public download endpoint for TemporaryAsset
        else:
            continue

        object_store = buckets.get(asset.bucket)
        if object_store is None:
            current_app.logger.warning(
                f"_process_attachments: no object store for bucket '{asset.bucket}'; skipping"
            )
            continue

        storage = AssetCloudAdapter(
            asset,
            object_store,
            audit_data=f"EmailTemplate.apply_() attachment id={attachment.id}",
        )
        if not storage.exists():
            current_app.logger.warning(
                f"_process_attachments: asset {asset.id} not found in object store; skipping"
            )
            continue

        asset_size = asset.filesize or 0
        display_name = (
            attachment.name
            if attachment.name
            else (str(asset.target_name) if asset.target_name else str(asset.unique_name))
        )

        if current_size + asset_size > max_attachment_size:
            download_url: Optional[str] = None
            if endpoint is not None:
                download_url = url_for(
                    f"admin.{endpoint}",
                    asset_id=asset.id,
                    filename=display_name,
                    _external=True,
                )
            manifest.append((False, display_name, download_url, attachment.description))
        else:
            msg.attach(filename=display_name, mimetype=asset.mimetype, content=storage.get())
            current_size += asset_size
            manifest.append((True, display_name, None, attachment.description))

    return manifest


def _build_attachments_footer(
        manifest: List[Tuple[bool, str, Optional[str], Optional[str]]],
) -> str:
    """
    Build a nicely-formatted HTML footer listing all attachments and download links.

    Each entry in manifest is a 4-tuple:
        (attached, display_name, download_url, description)
    where:
        attached     – True if the file was attached to the email
        display_name – human-readable filename
        download_url – URL for download (None if not applicable or no endpoint)
        description  – optional description string
    """
    if not manifest:
        return ""

    lines = [
        "<hr>",
        '<h4 style="margin-bottom: 4px;">Attachments</h4>',
        "<ul>",
    ]

    for attached, display_name, download_url, description in manifest:
        lines.append("<li>")
        if attached:
            entry_html = display_name
        else:
            if download_url:
                entry_html = f'<a href="{download_url}">{display_name}</a>'
            else:
                entry_html = display_name

        lines.append(f"<p>{entry_html}")

        sub_items = []
        if description:
            sub_items.append(description)
        if not attached:
            sub_items.append(
                "<strong>This file is too large to be sent as an attachment.</strong>"
                " Please download using the link provided."
            )

        if sub_items:
            lines.append('<ul style="line-height: 100%">')
            for item in sub_items:
                lines.append(f"<li>{item}</li>")
            lines.append("</ul>")

        lines.append("</p></li>")

    lines.append("</ul>")
    return "\n".join(lines)


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

    # property 'templates' set by backref from EmailTemplate.labels


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
        backref=db.backref("templates", lazy="dynamic"),
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

    @property
    def type_name(self):
        return _TYPE_NAMES.get(self.type, f"Unknown type ({self.type})")

    @staticmethod
    def apply_(
        template_type: int,
        to: List[str],
        from_email: Optional[str] = None,
        reply_to: Optional[List[str]] = None,
        subject_kwargs: Optional[Dict[str, Any]] = None,
        body_kwargs: Optional[Dict[str, Any]] = None,
        body_attachments: Optional[Dict[str, Callable]] = None,
            attachments=None,
            max_attachment_size: int = DEFAULT_MAX_ATTACHMENT_SIZE,
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
        :param attachments: a single EmailWorkflowItemAttachment or an iterable thereof
        :param max_attachment_size: maximum total attachment size in bytes (default 10 MB)
        :param tenant:
        :param pclass:
        :return:
        """
        tenant_id, pclass_id = _resolve_tenant_and_pclass(tenant, pclass)
        template = _find_template(template_type, tenant_id, pclass_id)

        if from_email is None:
            from_email = current_app.config["MAIL_DEFAULT_SENDER"]
        if reply_to is None:
            reply_to = [current_app.config["MAIL_REPLY_TO"]]

        if not isinstance(to, Iterable):
            raise RuntimeError(
                f'Invalid recipient list type "{type(to)}" (value="{to}") in EmailTemplate.apply_()'
            )
        if not isinstance(reply_to, Iterable):
            raise RuntimeError(
                f'Invalid reply_to list type "{type(reply_to)}" (value="{reply_to}") in EmailTemplate.apply_()'
            )

        subject_str: str = (
            template.subject.format(**subject_kwargs)
            if subject_kwargs is not None
            else template.subject
        )

        msg = EmailMultiAlternatives(
            subject=subject_str, from_email=from_email, reply_to=reply_to, to=to
        )

        # perform any legacy body_attachments, injecting results into body_kwargs
        if body_attachments is not None:
            for label, callable in body_attachments.items():
                output = callable(msg)
                if label not in body_kwargs:
                    body_kwargs[label] = output

        html_str: str = (
            render_template_string(template.html_body, **body_kwargs)
            if body_kwargs is not None
            else template.html_body
        )

        # attach files / generate download links and append manifest footer
        if attachments is not None:
            manifest = _process_attachments(msg, attachments, max_attachment_size)
            if manifest:
                html_str = html_str + _build_attachments_footer(manifest)

        plain_str: str = HTML2Text().handle(html_str)
        msg.body = plain_str
        msg.attach_alternative(html_str, "text/html")

        try:
            template.last_used = datetime.now()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return msg


class EmailWorkflowItemAttachment(db.Model):
    __tablename__ = "email_workflow_item_attachments"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # link to generated asset
    generated_asset_id = db.Column(
        db.Integer(), db.ForeignKey("generated_assets.id"), nullable=True
    )
    generated_asset = db.relationship(
        "GeneratedAsset",
        foreign_keys=[generated_asset_id],
        uselist=False,
        backref=db.backref("email_workflow_item_attachments", lazy="dynamic"),
    )

    # link to submitted asset
    submitted_asset_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), nullable=True
    )
    submitted_asset = db.relationship(
        "SubmittedAsset",
        foreign_keys=[submitted_asset_id],
        uselist=False,
        backref=db.backref("email_workflow_item_attachments", lazy="dynamic"),
    )

    # link to temporary asset
    temporary_asset_id = db.Column(
        db.Integer(), db.ForeignKey("temporary_assets.id"), nullable=True
    )
    temporary_asset = db.relationship(
        "TemporaryAsset",
        foreign_keys=[temporary_asset_id],
        uselist=False,
        backref=db.backref("email_workflow_item_attachments", lazy="dynamic"),
    )

    # manifest name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True
    )

    # manifest comment/description
    description = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True
    )

    @classmethod
    def build_(
        cls,
        name,
        description,
        generated_asset=None,
        submitted_asset=None,
        temporary_asset=None,
    ):
        # check that at only one of generated_asset, submitted_asset, and temporary_asset is specified
        num_assets = (
            (1 if generated_asset is not None else 0)
            + (1 if submitted_asset is not None else 0)
            + (1 if temporary_asset is not None else 0)
        )
        if num_assets != 1:
            raise RuntimeError(
                f"Exactly one of generated_asset, submitted_asset, and temporary_asset must be specified, but got {num_assets} instead"
            )

        if name is None or len(name) == 0:
            raise RuntimeError(
                f'Invalid name "{name}" (value="{name}") in EmailWorkflowItemAttachment.build_()'
            )

        if description is None or len(description) == 0:
            raise RuntimeError(
                f'Invalid description "{description}" (value="{description}") in EmailWorkflowItemAttachment.build_()'
            )

        generated_asset_id: Optional[int] = None
        submitted_asset_id: Optional[int] = None
        temporary_asset_id: Optional[int] = None

        if isinstance(generated_asset, GeneratedAsset):
            generated_asset_id = generated_asset.id
        elif isinstance(generated_asset, int):
            generated_asset_id = generated_asset
        elif generated_asset is not None:
            raise RuntimeError(
                f'Invalid generated_asset type "{type(generated_asset)}" (value="{generated_asset}") in EmailWorkflowItemAttachment.build_()'
            )

        if isinstance(submitted_asset, SubmittedAsset):
            submitted_asset_id = submitted_asset.id
        elif isinstance(submitted_asset, int):
            submitted_asset_id = submitted_asset
        elif submitted_asset is not None:
            raise RuntimeError(
                f'Invalid submitted_asset type "{type(submitted_asset)}" (value="{submitted_asset}") in EmailWorkflowItemAttachment.build_()'
            )

        if isinstance(temporary_asset, TemporaryAsset):
            temporary_asset_id = temporary_asset.id
        elif isinstance(temporary_asset, int):
            temporary_asset_id = temporary_asset
        elif temporary_asset is not None:
            raise RuntimeError(
                f'Invalid temporary_asset type "{type(temporary_asset)}" (value="{temporary_asset}") in EmailWorkflowItemAttachment.build_()'
            )

        return cls(
            generated_asset_id=generated_asset_id,
            submitted_asset_id=submitted_asset_id,
            temporary_asset_id=temporary_asset_id,
            description=description,
        )


# association table linking EmailWorkflowManifestItem to EmailWorkflowItem
email_workflow_item_attachment_to_workflow_item = db.Table(
    "email_workflow_item_attachment_to_workflow_item",
    db.Column(
        "email_workflow_item_attachment_id",
        db.Integer(),
        db.ForeignKey("email_workflow_item_attachments.id"),
    ),
    db.Column(
        "email_workflow_item_id", db.Integer(), db.ForeignKey("email_workflow_items.id")
    ),
)


class EmailWorkflowItem(db.Model, EditingMetadataMixin):
    __tablename__ = "email_workflow_items"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # subject payload, formatted as a JSON-serialized dictionary
    subject_payload = db.Column(db.Text())

    # body payload, formatted as a JSON-serialized dictionary
    body_payload = db.Column(db.Text())

    # explicit subject override for this email
    subject_override = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # explicit body override for this email
    body_override = db.Column(db.Text())

    # granular pause flag for this specific email item
    paused = db.Column(db.Boolean(), nullable=False, default=False)

    # email sent timestamp
    sent_timestamp = db.Column(db.DateTime(), index=True)

    # send in progress timestamp
    send_in_progress_timestamp = db.Column(db.DateTime(), index=True)

    # celery id of sending task
    celery_send_in_progress_task_id = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # number of send attempts that have been made
    send_attempts = db.Column(db.Integer(), nullable=False, default=0)

    # is there a current error condition?
    error_condition = db.Column(db.Boolean(), nullable=False, default=False)

    # any error message
    error_message = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # list of attachments
    attachments = db.relationship(
        "EmailWorkflowItemAttachment",
        secondary=email_workflow_item_attachment_to_workflow_item,
        lazy="dynamic",
        backref=db.backref("email_workflow_item", lazy="dynamic"),
    )

    # logged email identifier (valid once the email has been sent)
    # we should delete this EmailWorkflowItem if/when the EmailLog item
    # it produces is deleted
    email_log_id = db.Column(db.Integer(), db.ForeignKey("email_log.id"), nullable=True)
    email_log = db.relationship(
        "EmailLog",
        foreign_keys=[email_log_id],
        uselist=False,
        backref=db.backref(
            "email_workflow_items", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    @classmethod
    def build_(cls, subject_payload, body_payload, attachments=None):
        if attachments is None:
            attachments = []

        if isinstance(attachments, EmailWorkflowItemAttachment):
            attachments = [attachments]
        elif not isinstance(attachments, Iterable):
            raise RuntimeError(
                f'Invalid attachments type "{type(attachments)}" (value="{attachments}") in EmailWorkflowItem.build_()'
            )

        return cls(
            subject_payload=json.dumps(subject_payload),
            body_payload=json.dumps(body_payload),
            attachments=attachments,
            subject_override=None,
            body_override=None,
            paused=False,
            sent_timestamp=None,
            send_in_progress_timestamp=None,
            celery_send_in_progress_task_id=None,
            send_attempts=0,
            error_condition=False,
            error_message=None,
        )


# association table for email workflows to project classes
email_workflow_to_pclasses = db.Table(
    "email_workflow_to_pclasses",
    db.Column("email_workflow_id", db.Integer(), db.ForeignKey("email_workflows.id")),
    db.Column("project_class_id", db.Integer(), db.ForeignKey("project_classes.id")),
)


class EmailWorkflow(db.Model, EditingMetadataMixin):
    __tablename__ = "email_workflows"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # completed flag
    completed = db.Column(db.Boolean(), nullable=False, default=False)

    # completed timestamp
    completed_timestamp = db.Column(db.DateTime(), index=True)

    # send time - no emails will be sent before this time
    send_time = db.Column(db.DateTime(), nullable=False)

    # paused flag - is this workflow currently paused?
    paused = db.Column(db.Boolean(), nullable=False, default=False)

    # associated project classes
    pclasses = db.relationship(
        "ProjectClass",
        secondary=email_workflow_to_pclasses,
        lazy="dynamic",
        backref=db.backref("workflows", lazy="dynamic"),
    )

    # name of workflow
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False
    )

    # creation datestamp, userid and last edited datestamp, userid are recorded via the EditingMetadataMixin

    # link to EmailTemplate to be used
    template_id = db.Column(
        db.Integer(), db.ForeignKey("email_templates.id"), nullable=False
    )
    template = db.relationship(
        "EmailTemplate", backref=db.backref("workflows", lazy="dynamic")
    )

    # maximum attachment size
    max_attachment_size = db.Column(
        db.Integer(), nullable=False, default=DEFAULT_MAX_ATTACHMENT_SIZE
    )

    @classmethod
    def build_(
        cls,
        name,
        template,
        send_time,
        pclasses=None,
        max_attachment_size=DEFAULT_MAX_ATTACHMENT_SIZE,
    ):
        if name is None or len(name) == 0:
            raise RuntimeError(
                f'Invalid name "{name}" (value="{name}") in EmailWorkflow.build_()'
            )

        if template is None:
            raise RuntimeError(
                f'Invalid template "{template}" (value="{template}") in EmailWorkflow.build_()'
            )

        if send_time is None:
            raise RuntimeError(
                f'Invalid send_time "{send_time}" (value="{send_time}") in EmailWorkflow.build_()'
            )

        if pclasses is None:
            pclasses = []
        elif isinstance(pclasses, ProjectClass):
            pclasses = [pclasses]
        elif not isinstance(pclasses, Iterable):
            raise RuntimeError(
                f'Invalid pclasses type "{type(pclasses)}" (value="{pclasses}") in EmailWorkflow.build_()'
            )

        return cls(
            name=name,
            template=template,
            send_time=send_time,
            pclasses=pclasses,
            completed=False,
            paused=False,
            max_attachment_size=max_attachment_size,
        )
