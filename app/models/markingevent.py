#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH
from .live_projects import SubmittingStudent
from .model_mixins import EditingMetadataMixin
from .project_class import ProjectClass, ProjectClassConfig
from .students import StudentData
from .submissions import SubmissionRoleTypesMixin
from .users import User


@dataclass
class ConvenorAction:
    """A single call-to-action item surfaced to the convenor on a MarkingEvent inspector."""

    severity: str  # "warning", "danger", "info", "success"
    title: str
    description: str
    action_url: Optional[str] = None
    action_label: Optional[str] = None


class MarkingSchemeMixin:
    # HTML-formatted title to be displayed on the marking form
    title = db.Column(db.Text(), nullable=False)

    # HTML-formatted rubric to be displayed to markers
    rubric = db.Column(db.Text(), nullable=False)

    # JSON-serialized marking scheme schema
    schema = db.Column(db.Text(), nullable=False)

    # are the standard feedback fields (what was good/suggestions for improvement) used?
    uses_standard_feedback = db.Column(db.Boolean(), default=False, nullable=False)

    # does this mark scheme use moderators to arbitrate between different markers when they return values out of tolerance?
    uses_tolerance = db.Column(db.Boolean(), default=False, nullable=False)

    # tolerance between different markers before a moderation intervention is required,
    # expressed as a percentage
    marker_tolerance = db.Column(db.Numeric(8, 3), default=15)

    @property
    def schema_as_dict(self):
        return json.loads(self.schema)


class MarkingScheme(db.Model, MarkingSchemeMixin, EditingMetadataMixin):
    """
    Represents a marking scheme to be used as part of a marking workflow.

    The mark scheme defines what questions are asked. This is encoded in a JSON-serialized schema.
    Each schema should contain a "scheme" and "conflation_rule" element, and may optionally also
    contain a "validation" element.
        - "scheme": a scheme block, as described below
        - "validation": a validation block, as described below
        - "conflation_rule": string representing a valid Python expression the conflation rule used to generate a grade from this report,
          with variables corresponding to the keys defined in the scheme block

    SCHEME BLOCK
    This consists of an ordered list of section blocks. Each section is a dict with the following keys:
        - "title": REQUIRED, HTML-formatted string to be displayed as the title of the block
        - "description": OPTIONAL, HTML-formatted string to be displayed below the title, describing the purpose of this block
        - "fields": REQUIRED, ordered list of questions. Each question is a dict with the following keys:
            - "key": REQUIRED, string used as a unique identified for the question
            - "text": REQUIRED, text of the question, should be formatted on the marking form that is presented to the user
            - "field_type": REQUIRED, dict defining the type of response expected, containing the following keys:
                * "type": REQUIRED, one of "boolean", "text", "number", "percent"
                * "min", "max": OPTIONAL, used with the number type to specify maximum and minimum allowed values
                * "precision": OPTIONAL, used with the number type to specify the number of decimal places that are retained
                * "default": OPTIONAL, an optional default value

    The different field types map to WTForms fields:
        - "boolean" -> BooleanField, with a suitable default if the "default" key is present
        - "text" -> TextField
        - "number" -> FloatField, with a suitable default if the "default" key is present, and "min"/"max" values enforced by validators.
          The "precision" key should be implemented by rounding the output to the required precision.
        - "percent" -> FloatField, but with "min"/"max" automatically chosen to be 0 and 100, and a precision of 1

    VALIDATION BLOCK
    The block contains a list of tests used to validate the response. Each test is a dict with the following keys:
        - "test": string representing the test as a valid Python expression, with variables corresponding to the keys in the questions
        - "action": a list action to take if validation fails. The available actions are
            * "prevent_submit": the marking report should fail validation, so that it cannot be submitted at all. If "prevent_submit"
              is used it should be the only action.
            * "email": generate an email to the convenor (and possibly other users) to with a notification of the validation failure.
            * "web": show this validation failure to the convenor in the web interface
        - "message": string representing a message to display if this validation fails

    NOTES
    The validation "test" and "conflation_rule" fields should be valid Python expressions that evaluate to a boolean and a float
    representing a percentage, respectively. They should use variables corresponding to the keys defined in the questions.
    To evaluate them, these keys will be replaced with the submitted response.
    """

    __tablename__ = "marking_schemes"

    __table_args__ = (db.UniqueConstraint("pclass_id", "name"),)

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name must be unique within the parent ProjectClass
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # project class this marking scheme is for
    pclass_id = db.Column(
        db.Integer(), db.ForeignKey("project_classes.id"), nullable=False
    )
    pclass = db.relationship("ProjectClass", foreign_keys=[pclass_id], uselist=False)


class LiveMarkingScheme(db.Model, MarkingSchemeMixin, EditingMetadataMixin):
    """
    Duplicates a MarkingScheme.
    Gives a permanent record of the marking scheme used for any particular MarkingEvent, so that subsequent changes to the marking scheme
    don't mean that we lose an understanding of the schema.
    Each LiveMarkingScheme is owned by exactly one MarkingWorkflow (enforced by the unique constraint on
    MarkingWorkflow.scheme_id). The name is copied from the parent MarkingScheme at snapshot time and is
    not required to be globally unique.
    """

    __tablename__ = "live_marking_schemes"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name copied from the parent MarkingScheme at snapshot time; not required to be globally unique
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=False
    )

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
        "SubmissionPeriodRecord",
        foreign_keys=[period_id],
        uselist=False,
        backref=db.backref("marking_events", lazy="dynamic"),
    )

    # name of this event; unique within the parent SubmissionPeriodRecord
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # has this event been formally opened (marking distribution triggered)?
    open = db.Column(db.Boolean(), default=False, nullable=False)

    # has this event been closed?
    closed = db.Column(db.Boolean(), default=False, nullable=False)

    # global marking deadline for this event; individual workflows may have earlier sub-deadlines
    deadline = db.Column(db.DateTime(), nullable=True)

    # JSON dict mapping target names (Python identifiers) to conflation expressions.
    # Each expression may reference the key fields of constituent MarkingWorkflows and should evaluate to a float.
    # Form: { "target_name": "conflation_expression", ... }
    targets = db.Column(db.Text(), nullable=True)

    __table_args__ = (db.UniqueConstraint("period_id", "name"),)

    @property
    def targets_as_dict(self) -> dict:
        if not self.targets:
            return {}
        return json.loads(self.targets)

    # convenience accessors
    @property
    def config(self) -> ProjectClassConfig:
        return self.period.config

    @property
    def pclass(self) -> ProjectClass:
        return self.period.config.project_class

    def get_convenor_actions(
        self, event_url: Optional[str] = None, open_event_url: Optional[str] = None
    ) -> list:
        """
        Return a list of ConvenorAction items representing outstanding actions for this event.
        Extend this method as the SubmitterReport workflow grows to surface new CTA items.
        """
        actions = []

        # Check for SubmitterReports in READY_TO_DISTRIBUTE state with undistributed MarkingReports
        ready_count = 0
        for workflow in self.workflows:
            for sr in workflow.submitter_reports:
                if (
                    sr.workflow_state
                    == SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
                ):
                    undistributed = sum(
                        1 for mr in sr.marking_reports if not mr.distributed
                    )
                    if undistributed > 0:
                        ready_count += undistributed

        if ready_count > 0:
            if self.open:
                actions.append(
                    ConvenorAction(
                        severity="warning",
                        title="Reports ready to distribute",
                        description=f"{ready_count} marking notification{'s' if ready_count != 1 else ''} "
                        f"ready to send to assessors.",
                        action_url=event_url,
                        action_label="Send notifications",
                    )
                )
            else:
                actions.append(
                    ConvenorAction(
                        severity="warning",
                        title="Ready to open marking event",
                        description=f"{ready_count} marking notification{'s' if ready_count != 1 else ''} "
                        f"ready. Open this event to trigger distribution.",
                        action_url=open_event_url,
                        action_label="Open event\u2026",
                    )
                )

        # Check for report processing failures
        failed_count = 0
        for workflow in self.workflows:
            if workflow.requires_report:
                for sr in workflow.submitter_reports:
                    if sr.record.report_processing_failed:
                        failed_count += 1
                        break  # count per-workflow, not per-report

        if failed_count > 0:
            actions.append(
                ConvenorAction(
                    severity="danger",
                    title="Report processing failures",
                    description=f"{failed_count} submission{'s' if failed_count != 1 else ''} "
                    f"could not have their report processed. Please restart processing.",
                    action_url=None,
                    action_label=None,
                )
            )

        return actions


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

# association table linking users to a marking workflow, who should be notified when an out-of-tolerance situation is detected and
# moderation is required
notify_on_moderation_required = db.Table(
    "notify_on_moderation_required",
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
    db.Column(
        "marking_workflow_id",
        db.Integer(),
        db.ForeignKey("marking_workflows.id"),
        primary_key=True,
    ),
)

## association table linking users to a marking workflow, who should be notified when an email is generated due to a validation failure
notify_on_validation_failure = db.Table(
    "notify_on_validation_failure",
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
    db.Column(
        "marking_workflow_id",
        db.Integer(),
        db.ForeignKey("marking_workflows.id"),
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

    # parent MarkingEvent
    event_id = db.Column(
        db.Integer(), db.ForeignKey("marking_events.id"), nullable=False
    )
    event = db.relationship(
        "MarkingEvent",
        foreign_keys=[event_id],
        uselist=False,
        backref=db.backref("workflows", lazy="dynamic"),
    )

    # name of this workflow; should be unique within the parent MarkingEvent, but does not need to be
    # globally unique
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # key for this workflow; must be a valid Python identifier and unique within the parent MarkingEvent.
    # Used to identify this workflow's contribution when computing aggregated marks via the MarkingEvent.targets expressions.
    key = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True
    )

    __table_args__ = (
        db.UniqueConstraint("event_id", "name"),
        db.UniqueConstraint("event_id", "key"),
    )

    # role that this workflow targets. All SubmissionRole instances that belong to the ProjectClassConfig for the parent MarkingEvent
    # and have this role will be assigned to this workflow
    role = db.Column(db.Integer(), nullable=False)

    # mark scheme to use for this workflow.
    # The scheme should NOT be empty, but we allow nullable for backwards compatibility with
    # old cycles where no marking scheme existed.
    # The unique constraint enforces the 1-to-1 relationship: each LiveMarkingScheme snapshot
    # belongs to exactly one MarkingWorkflow.
    scheme_id = db.Column(
        db.Integer(),
        db.ForeignKey("live_marking_schemes.id"),
        nullable=True,
        unique=True,
    )
    scheme = db.relationship(
        "LiveMarkingScheme",
        foreign_keys=[scheme_id],
        uselist=False,
        backref=db.backref("marking_workflows", lazy="dynamic"),
    )

    # should this workflow wait for the student's processed report before SubmitterReport instances
    # move to READY_TO_DISTRIBUTE? Set at creation time only; not editable afterwards.
    requires_report = db.Column(db.Boolean(), default=True, nullable=False)

    # optional sub-deadline for this workflow; if set, must be <= event.deadline
    deadline = db.Column(db.DateTime(), nullable=True)

    # email template to use when sending marking notifications for this workflow;
    # auto-assigned at creation time based on the workflow role
    template_id = db.Column(
        db.Integer(), db.ForeignKey("email_templates.id"), nullable=True
    )
    template = db.relationship(
        "EmailTemplate",
        foreign_keys=[template_id],
        uselist=False,
    )

    # attachments (already uploaded by the convenor as SubmissionPeriod attachments)
    # that should be included with this workflow
    attachments = db.relationship(
        "PeriodAttachment",
        secondary=marking_workflow_to_attachments,
        backref=db.backref("marking_workflows", lazy="dynamic"),
    )

    # list of users to notify when an out-of-tolerance situation is detected and moderation is required
    notify_on_moderation_required = db.relationship(
        "User", secondary=notify_on_moderation_required, lazy="dynamic"
    )

    # list of users to notify when an email is generated due to a validation failure
    notify_on_validation_failure = db.relationship(
        "User", secondary=notify_on_validation_failure, lazy="dynamic"
    )

    # note that the "submitter_reports" property is set back backref from the SubmitterReport relationship

    # HOWEVER, note that MarkingReport is not linked direct to MarkingWorkflow, but only indirectly
    # via SubmitterReport. We do this so that there is only one route from MarkingReport to MarkingWorkflow,
    # and they can't drift out of sync (i.e. the tables are in normalized form).
    # This means that we don't have a "marking_reports" property directly, but we can synthesize one
    @property
    def marking_reports(self):
        # TODO: This approach may not scale if self.submitter_reports is every large
        submitter_report_ids = [r.id for r in self.submitter_reports]
        return db.session.query(MarkingReport).filter(
            MarkingReport.submitter_report_id.in_(submitter_report_ids)
        )

    # obtain role name as string
    @property
    def role_as_str(self) -> str:
        return self._role_string.get(self.role, "Unknown")

    @property
    def roleid_as_str(self) -> str:
        return self._role_id.get(self.role, "unknown")

    @property
    def effective_deadline(self) -> Optional[datetime]:
        """Returns the workflow's own deadline if set, otherwise falls back to the event deadline."""
        return self.deadline if self.deadline is not None else self.event.deadline

    # convenience accessors
    @property
    def number_submitter_reports(self) -> int:
        return self.submitter_reports.count()

    @property
    def number_marking_reports(self) -> int:
        return self.marking_reports.count()

    @property
    def number_marking_reports_distributed(self) -> int:
        return self.marking_reports.filter(MarkingReport.distributed.is_(True)).count()

    @property
    def number_marking_reports_undistributed(self) -> int:
        return self.marking_reports.filter(MarkingReport.distributed.is_(False)).count()

    @property
    def number_marking_reports_with_feedback(self) -> int:
        return self.marking_reports.filter(
            MarkingReport.feedback_submitted.is_(True)
        ).count()

    @property
    def number_processing_failures(self) -> int:
        """Count of SubmitterReports whose SubmissionRecord has report_processing_failed == True."""
        if not self.requires_report:
            return 0
        return sum(
            1 for sr in self.submitter_reports if sr.record.report_processing_failed
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

# link FeedbackReports to SubmitterReports
submitter_report_to_feedback_report = db.Table(
    "submitter_report_to_feedback_report",
    db.Column(
        "submitter_report_id",
        db.Integer(),
        db.ForeignKey("submitter_reports.id"),
        primary_key=True,
    ),
    db.Column(
        "feedback_report_id",
        db.Integer(),
        db.ForeignKey("feedback_reports.id"),
        primary_key=True,
    ),
)


class SubmitterReportWorkflowStates:
    """
    Lifecycle states for SubmitterReport instances.

    STATE MACHINE
    =============

    NOT_READY (999)
        Initial state. The SubmitterReport is waiting for the student's uploaded report to be
        processed (if the MarkingWorkflow has requires_report=True). Transitions to
        READY_TO_DISTRIBUTE once the report is available, or immediately if requires_report=False.

    READY_TO_DISTRIBUTE (0)
        All preconditions are met. The convenor can now distribute marking assignments to
        assessors (sends notification emails, sets MarkingReport.distributed=True). Transitions
        to AWAITING_GRADING_REPORTS once distribution emails have been sent.

    AWAITING_GRADING_REPORTS (1)
        One or more MarkingReport instances are awaiting submission by their assessor.
        Each assessor has a 24-hour editing window after submitting their grade; the window is
        managed by the close_marking_window Celery task scheduled via DatabaseSchedulerEntry.
        Once all MarkingReport.report_submitted flags are True, the state advances (see below).

    --- After all grading reports are submitted ---

    AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF (2)
        One or more MarkingReport instances (from ROLE_SUPERVISOR assessors) are awaiting
        sign-off by ROLE_RESPONSIBLE_SUPERVISOR staff. Responsible supervisors are linked via
        the marking_report_to_responsible_supervisors association table. Each sign-off removes
        the supervisor from the collection; when all sign-offs are received the state re-evaluates.
        Transitions to AWAITING_FEEDBACK or to the tolerance check (see below).

    AWAITING_FEEDBACK (3)
        All MarkingReport instances are signed off, but one or more are still awaiting feedback
        (feedback_submitted=False). Once all feedback is submitted, re-evaluates via the
        tolerance check (see below).

    --- Tolerance check ---

    If the MarkingWorkflow's LiveMarkingScheme does NOT use tolerance (uses_tolerance=False),
    or if no scheme is configured:
        READY_TO_SIGN_OFF (9)
            A weighted average grade has been computed and stored in SubmitterReport.grade.
            The SubmitterReport is awaiting final sign-off by a convenor or senior staff.
            Continues to READY_TO_GENERATE_FEEDBACK after sign-off.

    If the MarkingScheme DOES use tolerance (uses_tolerance=True):
        SubmitterReport.out_of_tolerance is set to True. Moderation emails are sent to users in
        MarkingWorkflow.notify_on_moderation_required, deferred to 9am the following morning.

        NEEDS_MODERATOR_ASSIGNED (5)
            No ROLE_MODERATOR SubmissionRole exists for the parent SubmissionRecord.
            The convenor must use the inspector to select a moderator. Once selected, a new
            SubmissionRole with ROLE_MODERATOR is created, a ModeratorReport is generated, and
            the state advances to AWAITING_MODERATOR_REPORT.

        AWAITING_MODERATOR_REPORT (6)
            A ModeratorReport has been created for the assigned moderator. Awaiting the
            moderator's grade and justification. Once submitted:
              - If SubmitterReport.grade is None: the moderator's grade is copied in and the
                state advances to READY_TO_SIGN_OFF.
              - If SubmitterReport.grade is already set (a prior moderator has graded):
                transitions to REQUIRES_CONVENOR_INTERVENTION.

    REQUIRES_CONVENOR_INTERVENTION (7)
        Blocking state used in two scenarios:
          1. Turnitin: turnitin_score >= 25 and turnitin_resolved=False. The convenor must
             review the Turnitin report and record a resolution before marking can proceed.
             Resolution transitions back to READY_TO_DISTRIBUTE.
          2. Conflicting moderation: multiple ModeratorReport instances have been submitted with
             different grades. The convenor must accept one via the Accept button in the inspector.
             Accepting transitions to READY_TO_SIGN_OFF.

    --- Post-grading lifecycle (not yet fully implemented) ---

    READY_TO_GENERATE_FEEDBACK (10)
        Grade has been signed off. Feedback documents can now be generated.

    READY_TO_PUSH_FEEDBACK (11)
        Feedback documents generated and ready to be released to the student.

    COMPLETED (12)
        Feedback has been pushed to the student. The lifecycle for this SubmitterReport is done.

    TURNITIN OVERRIDE
    =================
    At any point, if a SubmissionRecord's turnitin_score >= 25 and the SubmitterReport's
    turnitin_resolved=False, the SubmitterReport must be in REQUIRES_CONVENOR_INTERVENTION and
    cannot advance until turnitin_resolved is set True by a convenor.
    """

    NOT_READY = 999
    READY_TO_DISTRIBUTE = 0
    AWAITING_GRADING_REPORTS = 1
    AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF = 2
    AWAITING_FEEDBACK = 3
    # REPORTS_OUT_OF_TOLERANCE = 4
    NEEDS_MODERATOR_ASSIGNED = 5
    AWAITING_MODERATOR_REPORT = 6
    # REQUIRES_CONVENOR_INTERVENTION: blocking state.
    # A SubmitterReport enters this state when turnitin_score >= 25 and turnitin_resolved=False,
    # because the convenor must review the Turnitin similarity report before marking can proceed.
    # It CANNOT be advanced to AWAITING_GRADING_REPORTS or any subsequent state until
    # turnitin_resolved is set to True by a convenor (via the convenor.resolve_turnitin_issue view).
    # Resolution transitions the report back to READY_TO_DISTRIBUTE.
    # Also used for other convenor-intervention scenarios that may be added in future.
    REQUIRES_CONVENOR_INTERVENTION = 7
    # READY_TO_GENERATE_GRADE = 8
    READY_TO_SIGN_OFF = 9
    # READY_TO_GENERATE_FEEDBACK = 10
    # READY_TO_PUSH_FEEDBACK = 11
    COMPLETED = 12


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

    # parent MarkingWorkflow
    workflow_id = db.Column(
        db.Integer(), db.ForeignKey("marking_workflows.id"), nullable=False
    )
    workflow = db.relationship(
        "MarkingWorkflow",
        foreign_keys=[workflow_id],
        uselist=False,
        backref=db.backref("submitter_reports", lazy="dynamic"),
    )

    # current workflow state
    workflow_state = db.Column(
        db.Integer(), nullable=False, default=SubmitterReportWorkflowStates.NOT_READY
    )

    # aggregated grade
    grade = db.Column(db.Numeric(6, 2), nullable=True)

    # grade generated by
    grade_generated_by_id = db.Column(
        db.Integer(), db.ForeignKey("users.id"), nullable=True
    )
    grade_generated_by = db.relationship(
        "User", foreign_keys=[grade_generated_by_id], uselist=False
    )

    # grade generated timestamp
    grade_generated_timestamp = db.Column(db.DateTime(), nullable=True)

    # signed off by
    signed_off_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    signed_off_by = db.relationship("User", foreign_keys=[signed_off_id], uselist=False)

    # signed off timestamp
    signed_off_timestamp = db.Column(db.DateTime(), nullable=True)

    # feedback reports
    feedback_reports = db.relationship(
        "FeedbackReport", secondary=submitter_report_to_feedback_report, lazy="dynamic"
    )

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

    # TURNITIN REVIEW
    # NOTE: A SubmitterReport with turnitin_score >= 25 and turnitin_resolved=False
    # MUST be placed in REQUIRES_CONVENOR_INTERVENTION state and cannot advance to
    # AWAITING_GRADING_REPORTS (or any subsequent state) until this field is set True.

    # has the turnitin score been reviewed and resolved by a convenor?
    turnitin_resolved = db.Column(db.Boolean(), default=False, nullable=False)

    # optional comment entered by the convenor explaining their review decision
    turnitin_resolved_comment = db.Column(db.Text(), nullable=True)

    # timestamp when the resolution was recorded
    turnitin_resolved_timestamp = db.Column(db.DateTime(), nullable=True)

    # which user resolved the turnitin issue?
    turnitin_resolved_id = db.Column(
        db.Integer(), db.ForeignKey("users.id"), nullable=True
    )
    turnitin_resolved_by = db.relationship(
        "User", foreign_keys=[turnitin_resolved_id], uselist=False
    )

    # flag set when the MarkingReport grades are out of tolerance and moderation is required.
    # Set by _check_tolerance_and_grade(); cleared if a convenor resets the workflow state.
    out_of_tolerance = db.Column(db.Boolean(), default=False, nullable=False)

    # convenience accessors
    @property
    def submitter(self) -> SubmittingStudent:
        return self.record.owner

    @property
    def student(self) -> StudentData:
        return self.record.owner.student


# association table linking MarkingReport instances (for ROLE_SUPERVISOR) to the
# ROLE_RESPONSIBLE_SUPERVISOR SubmissionRole instances that must sign them off
marking_report_to_responsible_supervisors = db.Table(
    "marking_report_to_responsible_supervisors",
    db.Column(
        "marking_report_id",
        db.Integer(),
        db.ForeignKey("marking_reports.id"),
        primary_key=True,
    ),
    db.Column(
        "submission_role_id",
        db.Integer(),
        db.ForeignKey("submission_roles.id"),
        primary_key=True,
    ),
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

    # has this marking report been submitted?
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

    # final consolidated grade, expressed as a percentage, stored with 2-digits decimal precision
    grade = db.Column(db.Numeric(6, 2), nullable=True)

    # who generated the grade (i.e., who submitted this individual marking report)?
    grade_submitted_by_id = db.Column(
        db.Integer(), db.ForeignKey("users.id"), nullable=True
    )
    grade_submitted_by = db.relationship(
        "User", foreign_keys=[grade_submitted_by_id], uselist=False
    )

    # when was the grade generated?
    grade_submitted_timestamp = db.Column(db.DateTime(), nullable=True)

    # weight assigned to this marking report when computing the weighted average grade.
    # Initialised from the parent SubmissionRole.weight when the MarkingReport is created,
    # but can be edited independently via the properties editor.
    weight = db.Column(db.Numeric(8, 3), nullable=True)

    # FEEDBACK TO STUDENT

    # positive feedback: what was good?
    feedback_positive = db.Column(db.Text())

    # constructive feedback: suggestions for improvement
    feedback_improvement = db.Column(db.Text())

    # has the feedback been submitted?
    feedback_submitted = db.Column(db.Boolean(), default=False, nullable=False)

    # feedback submission timestamp
    feedback_timestamp = db.Column(db.DateTime())

    @property
    def marking_form_is_open(self) -> bool:
        """
        Returns True if the marking form is currently accessible to the assessor.
        The form is open once distributed=True, and remains open until grade_submitted_timestamp
        is set and more than 1 day old. A convenor can re-open the form by clearing
        grade_submitted_by_id and grade_submitted_timestamp.
        """
        if not self.distributed:
            return False
        if self.grade_submitted_timestamp is None:
            return True
        delta = datetime.now() - self.grade_submitted_timestamp
        return delta.total_seconds() < 86400

    @property
    def workflow(self):
        """Convenience accessor — the MarkingWorkflow is authoritative via the parent SubmitterReport."""
        return self.submitter_report.workflow

    # convenience accessors
    @property
    def submitter(self) -> SubmittingStudent:
        return self.submitter_report.submitter

    @property
    def student(self) -> StudentData:
        return self.submitter_report.student

    @property
    def user(self) -> User:
        return self.role.user

    # ROLE_RESPONSIBLE_SUPERVISOR instances pending sign-off for this (supervisor) report.
    # Populated by close_marking_window when the 24-hour editing window closes.
    # Entries are removed as each responsible supervisor approves the report.
    responsible_supervisors = db.relationship(
        "SubmissionRole",
        secondary=marking_report_to_responsible_supervisors,
        lazy="dynamic",
        backref=db.backref("pending_sign_off_reports", lazy="dynamic"),
    )


class ModeratorReport(db.Model, EditingMetadataMixin):
    """
    Represents the moderation report produced by a ROLE_MODERATOR for an out-of-tolerance
    SubmitterReport. Captures the moderator's recommended grade and written justification.
    """

    __tablename__ = "moderator_reports"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # owning SubmissionRole (with ROLE_MODERATOR)
    role_id = db.Column(
        db.Integer(), db.ForeignKey("submission_roles.id"), nullable=False
    )
    role = db.relationship(
        "SubmissionRole",
        foreign_keys=[role_id],
        uselist=False,
        backref=db.backref("moderator_reports", lazy="dynamic"),
    )

    # parent SubmitterReport
    submitter_report_id = db.Column(
        db.Integer(), db.ForeignKey("submitter_reports.id"), nullable=False
    )
    submitter_report = db.relationship(
        "SubmitterReport",
        foreign_keys=[submitter_report_id],
        uselist=False,
        backref=db.backref("moderator_reports", lazy="dynamic"),
    )

    # numerical grade recommended by the moderator (percentage, 2 d.p.)
    grade = db.Column(db.Numeric(6, 2), nullable=True)

    # written justification / moderation report
    report = db.Column(db.Text(), nullable=True)

    # submission state
    report_submitted = db.Column(db.Boolean(), default=False, nullable=False)
    submitted_timestamp = db.Column(db.DateTime(), nullable=True)

    @property
    def workflow(self):
        """Convenience accessor to the parent MarkingWorkflow."""
        return self.submitter_report.workflow

    @property
    def student(self) -> StudentData:
        """Convenience accessor to the student."""
        return self.submitter_report.student

    @property
    def user(self) -> User:
        """Convenience accessor to the moderator's User record."""
        return self.role.user
