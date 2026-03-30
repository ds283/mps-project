#
# Created by David Seery on 07/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from functools import partial
from typing import List

from flask_security.forms import Form
from wtforms import (
    BooleanField,
    DateTimeField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)
from wtforms_alchemy import QuerySelectField, QuerySelectMultipleField

from ..database import db
from ..faculty.forms import ProjectMixinFactory
from ..models import (
    DEFAULT_ASSIGNED_MARKERS,
    DEFAULT_ASSIGNED_MODERATORS,
    DEFAULT_STRING_LENGTH,
    AlternativesPriorityMixin,
    ConvenorGenericTask,
    FacultyData,
    LiveProject,
    MarkingScheme,
    MarkingWorkflow,
    Project,
    ProjectClass,
    ProjectClassConfig,
    Role,
    SubmissionPeriodRecord,
    SubmissionPeriodUnit,
    SubmissionRecord,
    SubmissionRole,
    SupervisionEventTemplate,
    Tenant,
    User,
)
from ..shared.forms.mixins import (
    PeriodPresentationsMixin,
    PeriodSelectorMixinFactory,
    SaveChangesMixin,
)
from ..shared.forms.queries import (
    AllProjectClasses,
    AllResearchGroups,
    BuildActiveFacultyName,
    BuildCanvasLoginUserName,
    BuildSupervisorName,
    BuildWorkflowTemplateLabel,
    GetAccommodatableMatchings,
    GetActiveFaculty,
    GetAllPossibleSupervisors,
    GetCanvasEnabledConvenors,
    GetPossibleSupervisors,
)
from ..shared.forms.wtf_validators import (
    NotOptionalIf,
    globally_unique_project,
    globally_unique_submission_unit,
    globally_unique_supervision_event_template,
    unique_or_original_submission_unit,
    unique_or_original_supervision_event_template,
    valid_marking_schema,
)
from ..shared.utils import get_current_year


def GoLiveFormFactory(
    submit_label="Go live",
    live_and_close_label="Go live and immediately close",
    datebox_label="Deadline",
):
    class GoLiveForm(Form):
        # Go Live
        live = SubmitField(submit_label)

        # go live and close option
        if live_and_close_label is not None:
            live_and_close = SubmitField(live_and_close_label)

        # deadline field
        live_deadline = DateTimeField(
            datebox_label, format="%d/%m/%Y", validators=[InputRequired()]
        )

        # notify faculty checkbox
        notify_faculty = BooleanField("Send e-mail notifications to faculty")

        # notify selectors checkbox
        notify_selectors = BooleanField("Send e-mail notifications to selectors")

        # accommodate a matching
        accommodate_matching = QuerySelectField(
            "Accommodate existing matching",
            query_factory=GetAccommodatableMatchings,
            get_label="name",
            allow_blank=True,
            blank_text="None",
            description="If this selection workflow is part of a sequence of "
            "selections (such as BSc selections following MPhys "
            "selections and a provisional matching), you may "
            "wish projects to be removed from the list if the "
            "corresponding supervisor is already too heavily "
            "committed to take on further students. Select a "
            "published matching here to account for faculty workload "
            "commitments corresponding to that match.",
        )

        # CATS limit before a supervisor is regarded as 'full'
        full_CATS = IntegerField(
            "Maximum number of CATS before a supervisor is full",
            description="Optional. If an existing matching is being accommodated, this is "
            "the maximum number of CATS that a supervisor can carry before they "
            "are regarded as full. Leave blank to use the maximum number of "
            "supervisor CATS specified in the matching.",
            validators=[Optional()],
        )

        # email template selectors (query_factory injected by the view)
        faculty_template = QuerySelectField(
            "Email template",
            allow_blank=False,
            get_label=BuildWorkflowTemplateLabel,
            validators=[DataRequired(message="Please select an email template.")],
        )

        selector_template = QuerySelectField(
            "Email template",
            allow_blank=False,
            get_label=BuildWorkflowTemplateLabel,
            validators=[DataRequired(message="Please select an email template.")],
        )

        convenor_template = QuerySelectField(
            "Email template",
            allow_blank=False,
            get_label=BuildWorkflowTemplateLabel,
            validators=[DataRequired(message="Please select an email template.")],
        )

    return GoLiveForm


def ChangeDeadlineFormFactory(
    submit_label="Close selections",
    change_label="Change deadline",
    datebox_label="The current deadline is",
):
    class ChangeDeadlineForm(Form):
        # Close selections
        close = SubmitField(submit_label)

        # Change deadline
        change = SubmitField(change_label)

        # deadline field
        live_deadline = DateTimeField(
            datebox_label, format="%d/%m/%Y", validators=[InputRequired()]
        )

        # send email notifications to convenor and office contacts?
        notify_convenor = BooleanField(
            "On closure, send e-mail notification to convenor and office staff"
        )

    return ChangeDeadlineForm


def IssueFacultyConfirmRequestFormFactory(
    submit_label="Issue confirmation requests",
    skip_label="Skip confirmation step",
    datebox_label="Deadline",
):
    class IssueFacultyConfirmRequestForm(Form):
        # deadline for confirmation responses
        request_deadline = DateTimeField(
            datebox_label, format="%d/%m/%Y", validators=[InputRequired()]
        )

        # skip button, if used
        if skip_label is not None:
            skip_button = SubmitField(skip_label)

        # submit button: issue requests
        submit_button = SubmitField(submit_label)

        # email template selector (query_factory injected by the view)
        confirm_template = QuerySelectField(
            "Email template",
            allow_blank=False,
            get_label=BuildWorkflowTemplateLabel,
            validators=[DataRequired(message="Please select an email template.")],
        )

    return IssueFacultyConfirmRequestForm


def OpenFeedbackFormFactory(
    submit_label="Open feedback period",
    datebox_label="Deadline",
    include_send_button=False,
    include_test_button=False,
    include_close_button=False,
):
    class OpenFeedbackForm(Form):
        # deadline for feedback
        feedback_deadline = DateTimeField(
            datebox_label, format="%d/%m/%Y", validators=[InputRequired()]
        )

        # CC emails to convenor?
        cc_me = BooleanField("CC myself in notification emails")

        # maximum size of attachments
        max_attachment = IntegerField(
            "Maximum total size of attachments, measured in Mb",
            validators=[InputRequired()],
            description="Documents with a total size larger than this will not be sent as "
            "attachments, but "
            "as download links to the original documents hosted on this site. "
            "Only authorized users can download files.",
        )

        # submit button: test
        if include_test_button:
            test_button = SubmitField("Test notifications")

        # if already open, include a 'send notifications' button
        if include_send_button:
            send_notifications = SubmitField("Send notifications")

        # direct close button
        if include_close_button:
            close_button = SubmitField("Close without notifications")

        # submit button: open feedback
        submit_button = SubmitField(submit_label)

        # email template selector (query_factory injected by the view)
        marking_template = QuerySelectField(
            "Email template",
            allow_blank=False,
            get_label=BuildWorkflowTemplateLabel,
            validators=[DataRequired(message="Please select an email template.")],
        )

    return OpenFeedbackForm


class TestOpenFeedbackForm(Form):
    # capture destinations for test emails
    target_email = StringField(
        "Target email address",
        validators=[InputRequired(), Email()],
        description="Enter an email address to which the test notification emails will be sent.",
    )

    # email template selector (query_factory injected by the view)
    marking_template = QuerySelectField(
        "Email template",
        allow_blank=False,
        get_label=BuildWorkflowTemplateLabel,
        validators=[DataRequired(message="Please select an email template.")],
    )

    # submit button
    submit_button = SubmitField("Perform test")


class CustomCATSLimitForm(Form, SaveChangesMixin):
    # custom CATS limit for supervision
    CATS_supervision = IntegerField(
        "Maximum CATS allocation for supervision", validators=[Optional()]
    )

    # custom CATS limit for marking
    CATS_marking = IntegerField(
        "Maximum CATS allocation for marking", validators=[Optional()]
    )

    # custom CATS limit for moderation
    CATS_moderation = IntegerField(
        "Maximum CATS allocation for moderation", validators=[Optional()]
    )

    # custom CATS limit for presentations
    CATS_presentation = IntegerField(
        "Maximum CATS allocation for presentation assessment", validators=[Optional()]
    )


def PeriodRecordMixinFactory(enable_canvas=True):
    class PeriodRecordMixin:
        name = StringField(
            "Name",
            description="Optional. Enter a textual name for this submission "
            'period, such as "Autumn Term". Leave blank to use the default name.',
            validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
        )

        number_markers = IntegerField(
            "Number of markers",
            default=DEFAULT_ASSIGNED_MARKERS,
            description="Number of markers that should be assigned to each project.",
            validators=[
                InputRequired("Please enter the required number of markers"),
                NumberRange(
                    min=0,
                    message="The required number of markers should not be negative",
                ),
            ],
        )

        number_moderators = IntegerField(
            "Number of moderators",
            default=DEFAULT_ASSIGNED_MODERATORS,
            description="Number of moderators that should be assigned to each project. "
            "If required, moderators can be added manually during the marking "
            "workflow.",
            validators=[
                InputRequired("Please enter the required number of moderators"),
                NumberRange(
                    min=0,
                    message="The required number of moderators should not be negative",
                ),
            ],
        )

        @staticmethod
        def validate_number_markers(form, field):
            if form._config.uses_marker and field.data == 0:
                raise ValidationError(
                    "This project class uses markers. The number of markers should be 1 or greater."
                )

        @staticmethod
        def validate_number_moderators(form, field):
            if form._config.uses_moderator and field.data == 0:
                raise ValidationError(
                    "This project class uses moderators. This number of moderators should be 1 or greater."
                )

        start_date = DateTimeField(
            "Period start date",
            format="%d/%m/%Y",
            validators=[Optional()],
            description="Enter an optional start date for this submission period.",
        )

        hand_in_date = DateTimeField(
            "Hand-in date",
            format="%d/%m/%Y",
            validators=[Optional()],
            description="Enter an optional hand-in date for this submission period. If present, "
            "this is used to show students how much time remains.",
        )

        collect_project_feedback = BooleanField("Collect project feedback online")

        if enable_canvas:
            canvas_module_id = IntegerField(
                "Canvas module identifier",
                validators=[Optional()],
                description="To enable Canvas integration for this submission period, "
                "enter the numeric identifier for the corresponding Canvas "
                "module. This does not need to be the same module used for "
                "synchronizing the submitter list.",
            )

            canvas_assignment_id = IntegerField(
                "Canvas assignment identifier",
                validators=[Optional()],
                description="Enter the numeric identifier for the corresponding Canvas "
                "assignment. Both the assignment id and module id need "
                "to be specified.",
            )

    return PeriodRecordMixin


def EditPeriodRecordFormFactory(config: ProjectClassConfig):
    canvas_enabled = config.main_config.enable_canvas_sync
    mixin = PeriodRecordMixinFactory(enable_canvas=canvas_enabled)

    class EditPeriodRecordForm(Form, mixin, SaveChangesMixin):
        _config = config

    return EditPeriodRecordForm


class EditSubmissionPeriodRecordPresentationsForm(
    Form, PeriodPresentationsMixin, SaveChangesMixin
):
    pass


def EditProjectConfigFormFactory(config: ProjectClassConfig):
    canvas_enabled = config.main_config.enable_canvas_sync

    class EditProjectConfigForm(Form, SaveChangesMixin):
        skip_matching = BooleanField(
            "Skip matching",
            description="Opt out of automated matching for this academic year",
        )

        requests_skipped = BooleanField(
            "Skip confirmation requests",
            description="Disable confirmation of project descriptions for this academic year",
        )

        uses_supervisor = BooleanField(
            "Uses supervisor roles",
            description="Select if the project is actively supervised by one or more members of staff",
        )

        uses_marker = BooleanField(
            "Uses marker roles",
            description="Select if the submissions are assessed by one or more members of staff",
        )

        uses_moderator = BooleanField(
            "Uses moderator roles",
            default=False,
            description="Select if submissions are moderated by one or more members of staff",
        )

        uses_presentations = BooleanField(
            "Includes one or more assessed presentations",
            description="Select if submissions are moderated by one or more members of staff",
        )

        display_marker = BooleanField("Display assessor information")

        display_presentations = BooleanField(
            "Display presentation assessment information"
        )

        full_CATS = IntegerField(
            "CAT threshold for supervisors to be full",
            description="Optional. If a partial match is being accommodated, this is the maximum "
            "number of CATS a supervisor can carry before they are regarded "
            "as full for the purposes of further allocation. If left blank, "
            "the maximum number of CATS is taken from the settings for the "
            "matching.",
            validators=[
                Optional(),
                NumberRange(
                    min=0, message="The specified number of CATS should not be negative"
                ),
            ],
        )

        CATS_supervision = IntegerField(
            "CATS awarded for project supervision",
            validators=[
                NotOptionalIf("uses_supervisor"),
                NumberRange(
                    min=0, message="The specified number of CATS should not be negative"
                ),
            ],
        )

        CATS_marking = IntegerField(
            "CATS awarded for marking submissions",
            validators=[
                NotOptionalIf("uses_marker"),
                NumberRange(
                    min=0, message="The specified number of CATS should not be negative"
                ),
            ],
        )

        CATS_moderation = IntegerField(
            "CATS awarded for moderating submissions",
            validators=[
                NotOptionalIf("uses_moderator"),
                NumberRange(
                    min=0, message="The specified number of CATS should not be negative"
                ),
            ],
        )

        CATS_presentation = IntegerField(
            "CATS awarded for assessing presentations",
            validators=[
                NotOptionalIf("uses_presentations"),
                NumberRange(
                    min=0, message="The specified number of CATS should not be negative"
                ),
            ],
        )

        # only include Canvas-related fields if Canvas integration is actually switched on
        if canvas_enabled:
            canvas_module_id = IntegerField(
                "Canvas module identifier",
                validators=[Optional()],
                description="To enable Canvas integration for this cycle, enter the numeric identifier for the corresponding Canvas module",
            )

            canvas_login = QuerySelectField(
                "Canvas login account",
                query_factory=partial(GetCanvasEnabledConvenors, config),
                allow_blank=True,
                get_label=BuildCanvasLoginUserName,
            )

    return EditProjectConfigForm


def ManualAssignFormFactory(config: ProjectClassConfig, is_admin: bool):
    PeriodSelectorMixin = PeriodSelectorMixinFactory(config, is_admin)

    class ManualAssignForm(Form, PeriodSelectorMixin):
        pass

    return ManualAssignForm


class ConvenorTaskMixin:
    description = StringField(
        "Description",
        description="Briefly summarize the task",
        validators=[InputRequired(), Length(max=DEFAULT_STRING_LENGTH)],
    )

    notes = TextAreaField(
        "Notes",
        description="Add any notes or commentary that you wish to associate with this task",
        render_kw={"rows": 8},
        validators=[Optional()],
    )

    blocking = BooleanField(
        "Task blocks progress to next lifecycle stage",
        description="Select if the task should block progress, eg. to Go Live or rollover to the next academic year",
        default=False,
    )

    complete = BooleanField(
        "Task has been completed",
        default=False,
        description="Select if the task has been finished.",
    )

    dropped = BooleanField(
        "Task is dropped",
        default=False,
        description="Select if the task is no longer required, but should be kept in the database rather than simply deleted.",
    )

    defer_date = DateTimeField(
        "Defer date",
        format="%d/%m/%Y %H:%M",
        description="If the task is deferred (that is, is not available to be completed) before some date, enter this here.",
        validators=[Optional()],
    )

    due_date = DateTimeField(
        "Due date",
        format="%d/%m/%Y %H:%M",
        description="If the task is due by a certain date, enter it here.",
        validators=[Optional()],
    )


class ConvenorGenericTaskMixin:
    repeat = BooleanField("Repeat task")

    repeat_interval = SelectField(
        "Repeat interval", choices=ConvenorGenericTask.repeat_options, coerce=int
    )

    repeat_frequency = IntegerField(
        "Repeat frequency", validators=[NotOptionalIf("repeat")]
    )

    repeat_from_due_date = BooleanField(
        "Repeat from due date",
        description="If selected, the due and defer dates of a repeating task "
        "are calculated from the due date of the "
        "predecessor task. Otherwise, these dates are determined "
        "from true true completion date of the predecessor task.",
    )

    rollover = BooleanField(
        "Rollover with academic year",
        description="Select if this task should be retained (if not yet complete) when rolling over between academic years.",
    )


class AddConvenorStudentTask(Form, ConvenorTaskMixin):
    submit = SubmitField("Create new task")


class EditConvenorStudentTask(Form, ConvenorTaskMixin, SaveChangesMixin):
    pass


class AddConvenorGenericTask(Form, ConvenorTaskMixin, ConvenorGenericTaskMixin):
    submit = SubmitField("Create new task")


class EditConvenorGenericTask(
    Form, ConvenorTaskMixin, ConvenorGenericTaskMixin, SaveChangesMixin
):
    pass


class EditSubmissionRoleForm(Form, SaveChangesMixin):
    role = SelectField("Role type", choices=SubmissionRole.role_choices, coerce=int)

    marking_distributed = BooleanField(
        "Marking distributed",
        description="Select if the marking materials have been distributed to this person.",
    )

    external_marking_url = StringField(
        "External marking URL",
        validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
        description="Optional. If an external marking link (e.g. to a Qualtrics or Google form) is needed, enter it here.",
    )

    grade = IntegerField(
        "Grade",
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="Grade should be between 0 and 100."),
        ],
        description="Optional. Enter the returned mark as a percentage (0–100).",
    )

    weight = IntegerField(
        "Weight",
        validators=[
            Optional(),
            NumberRange(min=0, message="Weight should not be negative."),
        ],
        description="Optional. Enter the resolved weight for this score.",
    )

    justification = TextAreaField(
        "Justification",
        render_kw={"rows": 5},
        validators=[Optional()],
        description="Optional. Enter a justification for the score.",
    )


class AddSubmitterRoleForm(Form):
    role = SelectField("Role type", choices=SubmissionRole.role_choices, coerce=int)

    user = QuerySelectField(
        "Assign which user?",
        query_factory=GetActiveFaculty,
        get_label=BuildActiveFacultyName,
        allow_blank=True,
    )

    @staticmethod
    def validate_user(form, field):
        if field.data is None:
            raise ValidationError("Please select a user to attach for this role")

        role_type: int = form.role.data
        fd: FacultyData = field.data

        record: SubmissionRecord = form._record
        project: LiveProject = record.project

        if project is not None:
            if role_type == SubmissionRole.ROLE_MARKER:
                pass
                # if fd not in project.assessor_list:
                #     raise ValidationError(
                #         'User "{name}" is not in the assessor pool for the assigned project. '
                #         "Please select a different user to attach for this role, or select "
                #         "a different role type.".format(name=fd.user.name)
                #     )

            if role_type in [
                SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ]:
                if project.generic:
                    if fd not in project.supervisor_list:
                        raise ValidationError(
                            "For generic projects, the assigned supervisor should be drawn from "
                            'the supervisor pool. User "{name}" is not in the supervisor pool for '
                            "this project. Please select a different user to attach for this role, "
                            "or select a different role type.".format(name=fd.user.name)
                        )

    submit = SubmitField("Add new role")


def EditRolesFormFactory(config: ProjectClassConfig):
    PeriodSelectorMixin = PeriodSelectorMixinFactory(config, True)

    class EditRolesForm(Form, PeriodSelectorMixin):
        pass

    return EditRolesForm


class AlternativePriorityMixin:
    priority = IntegerField(
        "Priority",
        description="Set the priority attached to this alternative. Low values represent high priority.",
        validators=[
            InputRequired(),
            NumberRange(
                max=AlternativesPriorityMixin.LOWEST_PRIORIY,
                min=AlternativesPriorityMixin.HIGHEST_PRIORITY,
                message=f"Please choose a priority between {AlternativesPriorityMixin.HIGHEST_PRIORITY} and {AlternativesPriorityMixin.LOWEST_PRIORIY}",
            ),
        ],
    )


class EditLiveProjectAlternativeForm(Form, AlternativePriorityMixin, SaveChangesMixin):
    pass


class EditProjectAlternativeForm(Form, AlternativePriorityMixin, SaveChangesMixin):
    pass


def EditProjectSupervisorsFactory(project: Project):
    class EditProjectSupervisors(Form, SaveChangesMixin):
        supervisors = QuerySelectMultipleField(
            "Supervisors",
            query_factory=GetAllPossibleSupervisors,
            get_label=BuildSupervisorName,
            validators=[
                InputRequired(message="Please specify at least one supervisor")
            ],
        )

    return EditProjectSupervisors


def EditLiveProjectSupervisorsFactory(project: LiveProject):
    class EditLiveProjectSupervisors(Form, SaveChangesMixin):
        supervisors = QuerySelectMultipleField(
            "Supervisors",
            query_factory=partial(GetPossibleSupervisors, project.config.pclass_id),
            get_label=BuildSupervisorName,
            validators=[
                InputRequired(message="Please specify at least one supervisor")
            ],
        )

    return EditLiveProjectSupervisors


def DuplicateProjectFormFactory(allowed_tenants: List[Tenant]):
    class DuplicateProjectForm(
        Form,
        ProjectMixinFactory(
            allowed_tenants,
            convenor_editing=True,
            uses_tags=True,
            uses_research_groups=True,
            project_classes_qf=AllProjectClasses,
            group_qf=AllResearchGroups,
        ),
    ):
        name = StringField(
            "Title",
            validators=[
                InputRequired(message="Project title is required"),
                Length(max=DEFAULT_STRING_LENGTH),
                globally_unique_project,
            ],
        )

        submit = SubmitField("Duplicate project")

    return DuplicateProjectForm


def _CustomOfferFormMixinFactory(pclass: ProjectClassConfig, year: int):
    class CustomOfferFormMixin:
        comment = TextAreaField(
            "Comment",
            render_kw={"rows": 3},
            description="Please enter a brief explanation or justification for this offer",
            validators=[
                InputRequired(
                    message="A brief comment is required to help document the reason this offer has been made"
                )
            ],
        )

        if pclass.number_submissions > 1:
            period = QuerySelectField(
                "Preferred submission period",
                blank_text="No preferred period",
                allow_blank=True,
                get_label=lambda d: d.display_name(year),
            )

    return CustomOfferFormMixin


def CreateCustomOfferFormFactory(pclass: ProjectClassConfig, year: int):
    mixin = _CustomOfferFormMixinFactory(pclass, year)

    class CreateCustomOfferForm(Form, mixin):
        submit = SubmitField("Create new custom offer")

    return CreateCustomOfferForm


def EditCustomOfferFormFactory(pclass: ProjectClassConfig, year: int):
    mixin = _CustomOfferFormMixinFactory(pclass, year)

    class EditCustomOfferForm(Form, mixin, SaveChangesMixin):
        pass

    return EditCustomOfferForm


class SubmissionPeriodUnitMixin:
    start_date = DateTimeField(
        "Start date",
        format="%d/%m/%Y",
        validators=[InputRequired()],
        description="Specify the (inclusive) start date for this unit",
    )

    end_date = DateTimeField(
        "End date",
        format="%d/%m/%Y",
        validators=[InputRequired()],
        description="Specify the (inclusive) end date for this unit",
    )


def AddSubmissionPeriodUnitFormFactory(period: SubmissionPeriodRecord):
    unique_name = partial(globally_unique_submission_unit, period.id)

    class AddSubmissionPeriodUnitForm(Form, SubmissionPeriodUnitMixin):
        name = StringField(
            "Name",
            validators=[
                InputRequired(message="Please enter a name for this unit"),
                Length(max=DEFAULT_STRING_LENGTH),
                unique_name,
            ],
            description="Provide a name for this unit (such as Week 2). The name should be unique within this submission period.",
        )

        submit = SubmitField("Add new unit")

    return AddSubmissionPeriodUnitForm


def EditSubmissionPeriodUnitFormFactory(period: SubmissionPeriodRecord):
    unique_name = partial(unique_or_original_submission_unit, period.id)

    class EditSubmissionPeriodUnitForm(
        Form, SubmissionPeriodUnitMixin, SaveChangesMixin
    ):
        name = StringField(
            "Name",
            validators=[
                InputRequired(message="Please enter a name for this unit"),
                Length(max=DEFAULT_STRING_LENGTH),
                unique_name,
            ],
            description="Provide a name for this unit (such as Week 2). The name should be unique within this submission period.",
        )

    return EditSubmissionPeriodUnitForm


class SupervisionEventTemplateMixin:
    target_role = SelectField(
        "Target role",
        choices=SupervisionEventTemplate.role_choices,
        coerce=int,
        description="When this event is distributed, it will be assigned to all staff with the specified submission role.",
    )

    type = SelectField(
        "Event type",
        choices=SupervisionEventTemplate.event_options,
        coerce=int,
    )

    monitor_attendance = BooleanField(
        "Monitor attendance",
        default=True,
        description="If selected, attendance data will be collected for instances of this event.",
    )


def AddSupervisionEventTemplateFormFactory(unit: SubmissionPeriodUnit):
    unique_name = partial(globally_unique_supervision_event_template, unit.id)

    class AddSupervisionEventTemplateForm(Form, SupervisionEventTemplateMixin):
        name = StringField(
            "Name",
            validators=[
                InputRequired(message="Please enter a name for this event"),
                Length(max=DEFAULT_STRING_LENGTH),
                unique_name,
            ],
            description="Provide a name for this event. The name should be unique within this submission unit.",
        )

        submit = SubmitField("Add new event")

    return AddSupervisionEventTemplateForm


def EditSupervisionEventTemplateFormFactory(unit: SubmissionPeriodUnit):
    unique_name = partial(unique_or_original_supervision_event_template, unit.id)

    class EditSupervisionEventTemplateForm(
        Form, SupervisionEventTemplateMixin, SaveChangesMixin
    ):
        name = StringField(
            "Name",
            validators=[
                InputRequired(message="Please enter a name for this event"),
                Length(max=DEFAULT_STRING_LENGTH),
                unique_name,
            ],
            description="Provide a name for this event. The name should be unique within this submission unit.",
        )

    return EditSupervisionEventTemplateForm


class MarkingSchemeMixin:
    title = TextAreaField(
        "Title",
        description="HTML-formatted title displayed at the top of the marking form",
    )

    rubric = TextAreaField(
        "Rubric",
        description="HTML-formatted instructions and guidance displayed to markers",
    )

    schema = TextAreaField(
        "Schema (JSON)",
        description="Specify the marking scheme by defining a series of questions. For each question, specify the field type.",
        validators=[valid_marking_schema],
    )

    uses_standard_feedback = BooleanField(
        "Uses standard feedback fields",
        default=False,
        description="Select if this scheme uses the standard feedback fields (what was good / suggestions for improvement)",
    )

    uses_tolerance = BooleanField(
        "Out-of-tolerance events between markers should trigger a moderation event",
        description="Differences that are out-of-tolerance will trigger a moderator intervention",
        default=True,
    )

    marker_tolerance = DecimalField(
        "Marker tolerance (%)",
        places=1,
        default=15,
        validators=[
            InputRequired(message="A marker tolerance value is required"),
            NumberRange(min=0, max=100, message="Tolerance must be between 0 and 100"),
        ],
    )


class AddMarkingSchemeForm(Form, MarkingSchemeMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="A name is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
        description="Unique name for this marking scheme",
    )

    submit = SubmitField("Add marking scheme")


class EditMarkingSchemeForm(Form, MarkingSchemeMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="A name is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
        description="Unique name for this marking scheme",
    )


# ---- MarkingEvent forms ----


class MarkingEventMixin:
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="A name is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
        description="Name for this marking event. Must be unique within the submission period.",
    )


class AddMarkingEventForm(Form, MarkingEventMixin):
    submit = SubmitField("Add marking event")


class EditMarkingEventForm(Form, MarkingEventMixin, SaveChangesMixin):
    pass


# ---- MarkingWorkflow forms ----

# Role choices for MarkingWorkflow: ROLE_SUPERVISOR covers both supervisor types
WORKFLOW_ROLE_CHOICES = [
    (MarkingWorkflow.ROLE_SUPERVISOR, "Supervisor"),
    (MarkingWorkflow.ROLE_MARKER, "Marker"),
    (MarkingWorkflow.ROLE_PRESENTATION_ASSESSOR, "Presentation assessor"),
    (MarkingWorkflow.ROLE_MODERATOR, "Moderator"),
    (MarkingWorkflow.ROLE_EXAM_BOARD, "Exam board member"),
    (MarkingWorkflow.ROLE_EXTERNAL_EXAMINER, "External examiner"),
]


def MarkingWorkflowFormFactory(pclass, scheme_locked=False):
    """
    Build Add/Edit form classes for MarkingWorkflow bound to a specific ProjectClass.

    scheme_locked should be True when any MarkingReport for the workflow has distributed=True
    or a non-empty report field, meaning the scheme can no longer be changed.
    """

    def get_schemes():
        return MarkingScheme.query.filter_by(pclass_id=pclass.id).order_by(MarkingScheme.name).all()

    def get_notify_users():
        return (
            db.session.query(User)
            .join(User.roles)
            .filter(
                User.tenants.any(id=pclass.tenant_id),
                Role.name.in_(["faculty", "office", "exam_board", "external_examiner"]),
            )
            .order_by(User.last_name, User.first_name)
            .all()
        )

    class MarkingWorkflowMixin:
        name = StringField(
            "Name",
            validators=[
                InputRequired(message="A name is required"),
                Length(max=DEFAULT_STRING_LENGTH),
            ],
            description="Name for this workflow. Must be unique within the parent marking event.",
        )

        scheme = QuerySelectField(
            "Marking scheme",
            query_factory=get_schemes,
            get_label="name",
            allow_blank=True,
            blank_text="— No scheme —",
            render_kw={"disabled": True} if scheme_locked else {},
        )

        notify_on_moderation_required = QuerySelectMultipleField(
            "Notify on moderation required",
            query_factory=get_notify_users,
            get_label=lambda u: u.name,
            description="Users to notify when an out-of-tolerance situation requires moderation.",
        )

        notify_on_validation_failure = QuerySelectMultipleField(
            "Notify on validation failure",
            query_factory=get_notify_users,
            get_label=lambda u: u.name,
            description="Users to notify when a marking report fails validation.",
        )

    class AddMarkingWorkflowForm(Form, MarkingWorkflowMixin):
        role = SelectField(
            "Role",
            choices=WORKFLOW_ROLE_CHOICES,
            coerce=int,
            description="The assessor role this workflow targets.",
        )

        submit = SubmitField("Add workflow")

    class EditMarkingWorkflowForm(Form, MarkingWorkflowMixin, SaveChangesMixin):
        pass

    return AddMarkingWorkflowForm, EditMarkingWorkflowForm


def _build_journal_pclass_config_query(user):
    """
    Return a callable that queries ProjectClassConfig instances accessible to the given user,
    scoped by role and tenant membership.
    """
    if user.has_role("root"):

        def query_factory():
            year = get_current_year()
            return (
                db.session.query(ProjectClassConfig)
                .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
                .filter(ProjectClass.active.is_(True), ProjectClassConfig.year == year)
                .order_by(ProjectClass.name)
                .all()
            )
    elif user.has_role("admin") or user.has_role("office"):
        tenant_ids = [t.id for t in user.tenants]

        def query_factory():
            year = get_current_year()
            q = (
                db.session.query(ProjectClassConfig)
                .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
                .filter(ProjectClass.active.is_(True), ProjectClassConfig.year == year)
            )
            if tenant_ids:
                q = q.filter(ProjectClass.tenant_id.in_(tenant_ids))
            else:
                # user has no tenant associations: show nothing
                return []
            return q.order_by(ProjectClass.name).all()
    else:
        # convenor: only pclasses they manage (convenor or co-convenor)
        faculty_data = user.faculty_data
        convenor_pclass_ids = (
            [pc.id for pc in faculty_data.convenor_projects] if faculty_data else []
        )

        def query_factory():
            if not convenor_pclass_ids:
                return []
            year = get_current_year()
            return (
                db.session.query(ProjectClassConfig)
                .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
                .filter(
                    ProjectClass.active.is_(True),
                    ProjectClassConfig.year == year,
                    ProjectClass.id.in_(convenor_pclass_ids),
                )
                .order_by(ProjectClass.name)
                .all()
            )

    return query_factory


def _journal_pclass_config_label(config):
    year = config.year
    return f"{config.project_class.name} ({year}/{str(year + 1)[-2:]})"


class JournalEntryMixin:
    title = StringField(
        "Title",
        validators=[
            InputRequired(message="A title is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
    )
    entry = TextAreaField(
        "Journal entry",
    )


def AddJournalEntryFormFactory(user):
    query_factory = _build_journal_pclass_config_query(user)

    class AddJournalEntryForm(Form, JournalEntryMixin):
        project_classes = QuerySelectMultipleField(
            "Project classes",
            query_factory=query_factory,
            get_label=_journal_pclass_config_label,
        )
        submit = SubmitField("Save entry")

    return AddJournalEntryForm


def EditJournalEntryFormFactory(user):
    query_factory = _build_journal_pclass_config_query(user)

    class EditJournalEntryForm(Form, JournalEntryMixin, SaveChangesMixin):
        project_classes = QuerySelectMultipleField(
            "Project classes",
            query_factory=query_factory,
            get_label=_journal_pclass_config_label,
        )

    return EditJournalEntryForm


class ConfirmDeleteWithReasonForm(Form):
    reason = TextAreaField(
        "Reason for deletion",
        render_kw={"rows": 4},
        description="Please provide a brief explanation for why this record is being deleted",
        validators=[InputRequired(message="A reason for deletion is required")],
    )
    submit = SubmitField("Delete")
