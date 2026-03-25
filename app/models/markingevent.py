#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from ..database import db
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import EditingMetadataMixin
from .submissions import SubmissionRoleTypesMixin


class MarkingSchemeMixin:
    # name of this marking scheme
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # HTML-formatted title to be displayed on the marking form
    title = db.Column(db.Text(), nullable=False)

    # HTML-formatted rubric to be displayed to markers
    rubric = db.Column(db.Text(), nullable=False)

    # JSON-serialized marking scheme schema
    schema = db.Column(db.Text(), nullable=False)

    # are the standard feedback fields (what was good/suggestions for improvement) used?
    uses_standard_feedback = db.Column(db.Boolean(), default=False)


class MarkingScheme(db.Model, MarkingSchemeMixin, EditingMetadataMixin):
    """
    Represents a marking scheme to be used as part of a marking workflow.
    The mark scheme defines what questions are asked. This is encoded in a JSON-serialized schema.
    The schema may is an ordered list of blocks. Each block is a dict with the following keys:
        - "title": string to be displayed as the title of the block
        - "fields": ordered list of questions. Each question is a dict with the following keys:
            - "key": string used as a unique identified for the question
            - "text": text of the question, should be formatted on the marking form that is presented to the user
            - "field_type": dict defining the type of response expected, containing the following keys:
                * "type": one of "boolean", "text", "number", "percent"
                * "min", "max": used with the number type to specify maximum and minimum allowed values
                * "precision": used with the number type to specify the number of decimal places that are retained
                * "default": an optional default value

    The different field types map to WTForms fields:
        - "boolean" -> BooleanField, with a suitable default if the "default" key is present
        - "text" -> TextField
        - "number" -> FloatField, with a suitable default if the "default" key is present, and "min"/"max" values enforced by validators. The "precision" key should be implemented by rounding the output to the required precision.
        - "percent" -> FloatField, but with "min"/"max" automatically chosen to be 0 and 100, and a precision of 1
    """

    __tablename__ = "marking_schemes"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # project class this marking scheme is for
    pclass_id = db.Column(
        db.Integer(), db.ForeignKey("project_classes.id"), nullable=False
    )
    pclass = db.relationship("ProjectClass", foreign_keys=[pclass_id], uselist=False)


class LiveMarkingScheme(db.Model, MarkingSchemeMixin):
    """
    Duplicates a MarkingScheme.
    Gives a permanent record of the marking scheme used for any particular MarkingEvent, so that subsequent changes to the marking scheme
    don't mean that we lose an understanding of the schema
    """

    __tablename__ = "live_marking_schemes"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent marking scheme
    parent_id = db.Column(
        db.Integer(), db.ForeignKey("marking_schemes.id"), nullable=False
    )
    parent = db.relationship("MarkingScheme", foreign_keys=[parent_id], uselist=False)


class MarkingEvent(db.Model, EditingMetadataMixin):
    """
    Represents a single marking event, such as grading of a PresentationAssessment, or grading of a students final report.
    Each MarkingEvent can contain multiple MarkingWorkflows, which define the marking workflow for assessor with a single role.
    In the case of a PresentationAssessor these would be for ROLE_PRESENTATION_ASSESSOR assessors.
    In the case of a final report, there would be parallel marking workflow for the supervisor ROLE_SUPERVISOR/ROLE_RESPONSIBLE_SUPERVISOR
    and for examiners/markers with ROLE_MARKER, and potentially involvement.
    Workflows may involve moderation using faculty with ROLE_MODERATOR roles.
    """

    __tablename__ = "marking_events"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # submission period this marking event is for
    period_id = db.Column(
        db.Integer(), db.ForeignKey("submission_periods.id"), nullable=False
    )
    period = db.relationship(
        "SubmissionPeriodRecord", foreign_keys=[period_id], uselist=False
    )

    # name of this event; should be unique within the parent SubmissionPeriodRecord, but does not need to be
    # globally unique
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # has this event been closed?
    closed = db.Column(db.Boolean(), default=False, nullable=False)


# association table of PeriodAttachment instances that should be included with each workflow
marking_workflow_to_attachments = db.Table(
    "marking_workflow_to_attachments",
    db.Column(
        "marking_workflow_id",
        db.Integer(),
        db.ForeignKey("marking_workflows.id"),
        primary_key=True,
    ),
    db.Column(
        "period_attachment_id",
        db.Integer(),
        db.ForeignKey("period_attachments.id"),
        primary_key=True,
    ),
)


class MarkingWorkflow(db.Model, EditingMetadataMixin, SubmissionRoleTypesMixin):
    """
    Represents a single workflow
    """

    __tablename__ = "marking_workflows"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name of this workflow; should be unique within the parent MarkingEvent, but does not need to be
    # globally unique
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # role that this workflow targets. All SubmissionRole instances that belong to the ProjectClassConfig for the parent MarkingEvent
    # and have this role will be assigned to this workflow
    role = db.Column(db.Integer(), nullable=False)

    # mark scheme to use for this workflow.
    # The scheme should NOT be empty, but we allow nullable for backwards compatibility with
    # old cycles where no marking scheme existed
    scheme_id = db.Column(
        db.Integer(), db.ForeignKey("live_marking_schemes.id"), nullable=True
    )
    scheme = db.relationship(
        "LiveMarkingScheme",
        foreign_keys=[scheme_id],
        uselist=False,
        backref=db.backref("marking_workflows", lazy="dynamic"),
    )

    # attachments that should be included with this workflow
    attachments = db.relationship(
        "PeriodAttachment",
        secondary=marking_workflow_to_attachments,
        backref=db.backref("marking_workflows", lazy="dynamic"),
    )


# association table of SubmitterReport to EmailLog, to track feedback emails
submitter_feedback_to_email_log = db.Table(
    "submitter_feedback_to_email_log",
    db.Column(
        "submitter_report_id",
        db.Integer(),
        db.ForeignKey("submitter_reports.id"),
        primary_key=True,
    ),
    db.Column(
        "email_log_id", db.Integer(), db.ForeignKey("email_log.id"), primary_key=True
    ),
)


class SubmitterReport(db.Model, EditingMetadataMixin):
    """
    Represents a consolidated marking report for a single submitter
    """

    __tablename__ = "submitter_reports"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent SubmissionRecord
    record_id = db.Column(
        db.Integer(), db.ForeignKey("submission_records.id"), nullable=False
    )
    record = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_id],
        uselist=False,
        backref=db.backref("submitter_reports", lazy="dynamic"),
    )

    # aggregated grade
    grade = db.Column(db.Numeric(3, 2), nullable=True)

    # signed off by
    signed_off_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    signed_off_by = db.relationship("User", foreign_keys=[signed_off_id], uselist=False)

    # has feedback been pushed out to the student for this period?
    feedback_sent = db.Column(db.Boolean(), default=False)

    # who pushed the feedback?
    feedback_push_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    feedback_push_by = db.relationship(
        "User", foreign_keys=[feedback_push_id], uselist=False
    )

    # timestamp when feedback was sent
    feedback_push_timestamp = db.Column(db.DateTime())

    # feedback emails
    feedback_emails = db.relationship(
        "EmailLog", secondary=submitter_feedback_to_email_log, lazy="dynamic"
    )


# association table of MarkingReport to EmailLog, to track distribution emails
marking_distribution_to_email_log = db.Table(
    "marking_distribuiton_to_email_log",
    db.Column(
        "marking_report_id",
        db.Integer(),
        db.ForeignKey("marking_reports.id"),
        primary_key=True,
    ),
    db.Column(
        "email_log_id", db.Integer(), db.ForeignKey("email_log.id"), primary_key=True
    ),
)


class MarkingReport(db.Model, EditingMetadataMixin):
    """
    Represents the marking report, possibly including feedback, from a single SubmissionRole
    """

    __tablename__ = "marking_reports"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent SubmissionRole
    role_id = db.Column(
        db.Integer(), db.ForeignKey("submission_roles.id"), nullable=False
    )
    role = db.relationship(
        "SubmissionRole",
        foreign_keys=[role_id],
        uselist=False,
        backref=db.backref("marking_reports", lazy="dynamic"),
    )

    # parent SubmitterReport
    submitter_report_id = db.Column(
        db.Integer(), db.ForeignKey("submitter_reports.id"), nullable=False
    )
    submitter_report = db.relationship(
        "SubmitterReport",
        foreign_keys=[submitter_report_id],
        uselist=False,
        backref=db.backref("marking_reports", lazy="dynamic"),
    )

    # JSON-serialized marking report
    report = db.Column(db.Text(), nullable=False)

    # distributed flag: has this assessor been notified of the need to return a report?
    distributed = db.Column(db.Boolean(), default=False)

    # distribution emails
    distribution_emails = db.relationship(
        "EmailLog", secondary=marking_distribution_to_email_log, lazy="dynamic"
    )

    # has the report been submitted?
    report_submitted = db.Column(db.Boolean(), default=False, nullable=False)

    # if this report is from a supervisor rather than a responsible supervisor, has it been signed off by the responsible supervisor?
    signed_off_id = db.Column(
        db.Integer(), db.ForeignKey("submission_roles.id"), nullable=True
    )
    signed_off_by = db.relationship(
        "SubmissionRole", foreign_keys=[signed_off_id], uselist=False
    )

    # signed off timestamp
    signed_off_timestamp = db.Column(db.DateTime(), nullable=True)

    # final consolidated grade, expressed as a percentage, stored as a 3-digit number with 2-digits decimal precision
    grade = db.Column(db.Numeric(3, 2), nullable=True)

    # FEEDBACK TO STUDENT

    # positive feedback: what was good?
    feedback_positive = db.Column(db.Text())

    # constructive feedback: suggestions for improvement
    feedback_improvement = db.Column(db.Text())

    # has the feedback been submitted?
    feedback_submitted = db.Column(db.Boolean(), default=False, nullable=False)

    # feedback submission timestamp
    feedback_timestamp = db.Column(db.DateTime())
