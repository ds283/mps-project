#
# Created by David Seery on 10/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import re
from functools import partial
from typing import List

from flask_security.forms import Form
from wtforms import (
    StringField,
    IntegerField,
    SelectField,
    BooleanField,
    SubmitField,
    TextAreaField,
    DateTimeField,
    FloatField,
    RadioField,
    ValidationError,
)
from wtforms.validators import InputRequired, Optional, Length, URL, NumberRange, Regexp, DataRequired
from wtforms_alchemy.fields import QuerySelectField, QuerySelectMultipleField

from ..documents.forms import LicenseMixin
from ..manage_users.forms import ResearchGroupMixin
from ..models import (
    BackupConfiguration,
    ScheduleAttempt,
    extent_choices,
    matching_history_choices,
    solver_choices,
    session_choices,
    semester_choices,
    auto_enrol_year_choices,
    student_level_choices,
    start_year_choices,
    DegreeProgramme,
    DegreeType,
    ProjectClass,
    PresentationAssessment,
    DEFAULT_ASSIGNED_MARKERS,
    DEFAULT_ASSIGNED_MODERATORS,
    DEFAULT_STRING_LENGTH,
    ProjectClassConfig,
)
from ..shared.forms.mixins import SaveChangesMixin, PeriodPresentationsMixin
from ..shared.forms.queries import (
    GetActiveDegreeTypes,
    GetActiveDegreeProgrammes,
    GetActiveSkillGroups,
    BuildDegreeProgrammeName,
    GetPossibleConvenors,
    BuildSysadminUserName,
    BuildConvenorRealName,
    GetAllProjectClasses,
    GetConvenorProjectClasses,
    GetSysadminUsers,
    GetAutomatedMatchPClasses,
    GetMatchingAttempts,
    GetComparatorMatches,
    GetUnattachedSubmissionPeriods,
    BuildSubmissionPeriodName,
    GetAllBuildings,
    GetAllRooms,
    BuildRoomLabel,
    GetFHEQLevels,
    ScheduleSessionQuery,
    BuildScheduleSessionLabel,
    GetComparatorSchedules,
    BuildPossibleOfficeContacts,
    BuildOfficeContactName,
    BuildPossibleApprovers,
    BuildApproverName,
    GetActiveProjectTagGroups,
    GetActiveFaculty,
    BuildActiveFacultyName,
    GetActiveBackupLabels,
    BuildBackupLabelName,
    GetActiveTemplateTags,
    BuildTemplateTagName,
    GetAllFeedbackTemplates,
    GetAllNonTemplateFeedbackAssets,
)
from ..shared.forms.widgets import BasicTagSelectField
from ..shared.forms.wtf_validators import (
    valid_json,
    NotOptionalIf,
    globally_unique_group_name,
    unique_or_original_group_name,
    globally_unique_group_abbreviation,
    unique_or_original_group_abbreviation,
    globally_unique_degree_type,
    unique_or_original_degree_type,
    globally_unique_degree_abbreviation,
    unique_or_original_degree_abbreviation,
    globally_unique_degree_programme,
    unique_or_original_degree_programme,
    globally_unique_course_code,
    unique_or_original_course_code,
    globally_unique_programme_abbreviation,
    unique_or_original_programme_abbreviation,
    globally_unique_transferable_skill,
    unique_or_original_transferable_skill,
    globally_unique_skill_group,
    unique_or_original_skill_group,
    globally_unique_project_class,
    unique_or_original_project_class,
    globally_unique_project_class_abbrev,
    unique_or_original_project_class_abbrev,
    globally_unique_supervisor,
    unique_or_original_supervisor,
    globally_unique_matching_name,
    globally_unique_supervisor_abbrev,
    unique_or_original_supervisor_abbrev,
    unique_or_original_matching_name,
    globally_unique_assessment_name,
    unique_or_original_assessment_name,
    globally_unique_building_name,
    unique_or_original_building_name,
    globally_unique_room_name,
    unique_or_original_room_name,
    globally_unique_schedule_name,
    unique_or_original_schedule_name,
    globally_unique_schedule_tag,
    unique_or_original_schedule_tag,
    globally_unique_module_code,
    unique_or_original_module_code,
    globally_unique_FHEQ_level_name,
    unique_or_original_FHEQ_level_name,
    globally_unique_FHEQ_short_name,
    unique_or_original_FHEQ_short_name,
    globally_unique_FHEQ_numeric_level,
    unique_or_original_FHEQ_numeric_level,
    globally_unique_license_name,
    unique_or_original_license_name,
    globally_unique_license_abbreviation,
    unique_or_original_license_abbreviation,
    per_license_unique_version,
    per_license_unique_or_original_version,
    globally_unique_project_tag_group,
    unique_or_original_project_tag_group,
    globally_unique_project_tag,
    unique_or_original_project_tag,
    globally_unique_feedback_asset_label,
    unique_or_original_feedback_asset_label,
    globally_unique_feedback_recipe_label,
    unique_or_original_feedback_recipe_label,
)


class GlobalConfigForm(Form):
    enable_canvas_sync = BooleanField("Enable Canvas integration globally")

    canvas_url = StringField(
        "Root Canvas URL",
        validators=[NotOptionalIf("enable_canvas_sync"), Length(max=DEFAULT_STRING_LENGTH), URL()],
        description="Provide the root URL for the Canvas instance that should be used for push or pull of student data.",
    )

    submit = SubmitField("Save changes")


class AddResearchGroupForm(Form, ResearchGroupMixin):
    name = StringField("Name", validators=[InputRequired(message="Name is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_group_name])

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="Abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_group_abbreviation],
    )

    submit = SubmitField("Add new group")


class EditResearchGroupForm(Form, ResearchGroupMixin, SaveChangesMixin):
    name = StringField(
        "Name", validators=[InputRequired(message="Name is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_group_name]
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="Abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_group_abbreviation],
    )


class DegreeTypeMixin:
    colour = StringField("Colour", description="Assign a colour to help identify this degree type.", validators=[Length(max=DEFAULT_STRING_LENGTH)])

    duration = IntegerField(
        "Duration",
        description="Enter the number of years study before a student graduates.",
        validators=[InputRequired(message="Degree duration is required")],
    )

    level = SelectField(
        "Student level", description="Is this degree type associated with UG, PGT or PGT students?", choices=student_level_choices, coerce=int
    )


class AddDegreeTypeForm(Form, DegreeTypeMixin):
    name = StringField(
        "Name", validators=[InputRequired(message="Degree type name is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_degree_type]
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="Abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_degree_abbreviation],
    )

    submit = SubmitField("Add new degree type")


class EditDegreeTypeForm(Form, DegreeTypeMixin, SaveChangesMixin):
    name = StringField(
        "Name", validators=[InputRequired(message="Degree type name is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_degree_type]
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="Abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_degree_abbreviation],
    )


class DegreeProgrammeMixin:
    degree_type = QuerySelectField("Degree type", query_factory=GetActiveDegreeTypes, get_label="name")

    show_type = BooleanField(
        "Show degree type in name",
        default=True,
        description="Select if the degree type, such as BSc (Hons) or MPhys, should be included in the programme's full name",
    )

    foundation_year = BooleanField("Includes foundation year", default=False)

    year_out = BooleanField(
        "Includes year out",
        default=False,
        description="Select if this programme includes a year abroad, an industrial "
        "placement year, or another type of year away from the University",
    )

    year_out_value = IntegerField(
        "Year out",
        default=3,
        description="Enter the numerical value of the year that should be regarded as the year out. Ignored if the 'year out' flag is not set.",
        validators=[NotOptionalIf("year_out")],
    )


class AddDegreeProgrammeForm(Form, DegreeProgrammeMixin):
    name = StringField(
        "Name",
        validators=[InputRequired(message="Degree programme name is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_degree_programme],
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="Abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_programme_abbreviation],
    )

    course_code = StringField(
        "Course code", validators=[InputRequired(message="Course code is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_course_code]
    )

    submit = SubmitField("Add new degree programme")


class EditDegreeProgrammeForm(Form, DegreeProgrammeMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Degree programme name is required"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_degree_programme,
        ],
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="Abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_programme_abbreviation],
    )

    course_code = StringField(
        "Course code",
        validators=[InputRequired(message="Course code is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_course_code],
    )


class ModuleMixin:
    name = StringField("Module name", validators=[InputRequired(message="Module name is required"), Length(max=DEFAULT_STRING_LENGTH)])

    level = QuerySelectField("Level", query_factory=GetFHEQLevels, get_label="name")

    semester = SelectField("Semester", choices=semester_choices, coerce=int)


class AddModuleForm(Form, ModuleMixin):
    code = StringField(
        "Module code", validators=[InputRequired(message="Module code is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_module_code]
    )

    submit = SubmitField("Add new module")


class EditModuleForm(Form, ModuleMixin, SaveChangesMixin):
    code = StringField(
        "Module code",
        validators=[InputRequired(message="Module code is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_module_code],
    )


class ProjectClassMixin:
    colour = StringField(
        "Colour", description="Assign a colour to help students identify this project class.", validators=[Length(max=DEFAULT_STRING_LENGTH)]
    )

    do_matching = BooleanField("Use automated global matching of faculty to projects", default=True)

    number_assessors = IntegerField(
        "Number of assessors required per project",
        description="Assessors are used to assign markers, moderators and presentation assessors. "
        "Significantly more than one assessor is required per project to allow "
        "sufficient flexibility during matching.",
        validators=[NotOptionalIf("do_matching"), NumberRange(min=0, message="Required number of assessors cannot be zero")],
    )

    use_project_hub = BooleanField(
        "Use Project Hubs (caution: not production quality)",
        description="The Project Hub is a lightweight learning management system that "
        "allows resources to be published to students, and provides a journal "
        "and to-do list. It is a central "
        "location to manage projects.",
    )

    student_level = SelectField(
        "Student level",
        description="Determines whether this project type applies to UG, PGT or PGR students.",
        choices=student_level_choices,
        coerce=int,
    )

    start_year = SelectField(
        "Starts in academic year",
        description="Determines the academic year in which students join the project.",
        choices=start_year_choices,
        coerce=int,
    )

    extent = SelectField(
        "Duration", choices=extent_choices, coerce=int, description="For how many academic years do students participate in the project?"
    )

    is_optional = BooleanField("This project is optional", default=False)

    uses_selection = BooleanField(
        "Students are required to submit a ranked list of project choices",
        default=True,
        description="Disable for projects types where only the project list is published, and selection takes place through a different workflow.",
    )

    uses_submission = BooleanField("Students submit work requiring marking or feedback", default=True)

    require_confirm = BooleanField("Require faculty to confirm projects yearly", default=True)

    supervisor_carryover = BooleanField("For multi-year projects, automatically carry over supervisor year-to-year")

    include_available = BooleanField("Include this project class in supervisor availability calculations")

    uses_supervisor = BooleanField(
        "Uses supervisor roles", default=True, description="Select if the project is actively supervised by one or more members of staff"
    )

    uses_marker = BooleanField(
        "Uses marker roles", default=True, description="Select if the submissions are assessed by one or more members of staff"
    )

    uses_moderator = BooleanField(
        "Uses moderator roles", default=False, description="Select if submissions are moderated by one or more members of staff"
    )

    uses_presentations = BooleanField("Includes one or more assessed presentations")

    display_marker = BooleanField("Display assessor information")

    display_presentations = BooleanField("Display presentation assessment information")

    reenroll_supervisors_early = BooleanField("Re-enroll supervisors one year before end of sabbatical/buyout", default=True)

    initial_choices = IntegerField(
        "Number of initial project preferences",
        description="Select number of preferences students should list before joining.",
        validators=[NotOptionalIf("uses_selection"), NumberRange(min=1, message="The required number of preferences should be at least 1")],
    )

    allow_switching = BooleanField(
        "Allow switching supervisors in subsequent years",
        description="Some project types may allow switching supervisors after the first year. "
        "If this is allowed, students may be required to submit a different number of ranked preferences.",
        default=False,
    )

    switch_choices = IntegerField(
        "Number of subsequent project preferences",
        description="Number of preferences to allow in subsequent years, if switching is allowed.",
        validators=[NotOptionalIf("uses_selection"), NumberRange(min=1, message="The required number of preferences should be at least 1")],
    )

    faculty_maximum = IntegerField(
        "Limit selections per faculty member",
        description="Optional. Specify a maximum number of projects that "
        "students can select if they are offered by the same "
        "faculty supervisor. Leave blank to disable.",
        validators=[Optional(), NumberRange(min=1, message="Specified maximum cannot be less than 1")],
    )

    CATS_supervision = IntegerField(
        "CATS awarded for project supervision",
        validators=[NotOptionalIf("uses_supervisor"), NumberRange(min=0, message="The specified number of CATS should not be negative")],
    )

    CATS_marking = IntegerField(
        "CATS awarded for marking submissions",
        validators=[NotOptionalIf("uses_marker"), NumberRange(min=0, message="The specified number of CATS should not be negative")],
    )

    CATS_moderation = IntegerField(
        "CATS awarded for moderating submissions",
        validators=[NotOptionalIf("uses_moderator"), NumberRange(min=0, message="The specified number of CATS should not be negative")],
    )

    CATS_presentation = IntegerField(
        "CATS awarded for assessing presentations",
        validators=[NotOptionalIf("uses_presentations"), NumberRange(min=0, message="The specified number of CATS should not be negative")],
    )

    hourly_choices = [
        (1, "1 day"),
        (2, "2 days"),
        (3, "3 days"),
        (4, "4 days"),
        (5, "5 days"),
        (6, "6 days"),
        (7, "7 days"),
        (8, "8 days"),
        (9, "9 days"),
        (10, "10 days"),
        (11, "11 days"),
        (12, "12 days"),
        (13, "13 days"),
        (14, "14 days"),
    ]
    keep_hourly_popularity = SelectField("Keep hourly popularity data for", choices=hourly_choices, coerce=int)

    daily_choices = [(1, "1 week"), (2, "2 weeks"), (3, "3 weeks"), (4, "4 weeks"), (5, "5 weeks"), (6, "6 weeks"), (7, "7 weeks"), (8, "8 weeks")]
    keep_daily_popularity = SelectField("Keep daily popularity data for", choices=daily_choices, coerce=int)

    convenor = QuerySelectField("Convenor", query_factory=GetPossibleConvenors, get_label=BuildConvenorRealName)

    coconvenors = QuerySelectMultipleField(
        "Co-convenors",
        query_factory=GetPossibleConvenors,
        get_label=BuildConvenorRealName,
        description="Co-convenors have the same administrative privileges "
        "as convenors, but are not identified to students. "
        "For example, they might be previous convenors who are "
        "helping with administration during a transition period.",
        validators=[Optional()],
    )

    office_contacts = QuerySelectMultipleField(
        "Professional Services contacts",
        query_factory=BuildPossibleOfficeContacts,
        get_label=BuildOfficeContactName,
        description="Specify one or more members of the professional services "
        "(School Office) team "
        "who act as contacts for this project type. Professional "
        "services contacts "
        "receive email updates to keep them appraised of the "
        "project lifecycle.",
        validators=[Optional()],
    )

    approvals_team = QuerySelectMultipleField(
        "Approvals team",
        query_factory=BuildPossibleApprovers,
        get_label=BuildApproverName,
        description="Specify one or members of the approvals pool who will be able to approve changes to project descriptions.",
        allow_blank=False,
    )

    @staticmethod
    def validate_approvals_team(form, field):
        if field.data is None or not isinstance(field.data, list) or len(field.data) == 0:
            raise ValidationError("At least one member of the approvals pool should be selected to join the approvals team.")

    select_in_previous_cycle = BooleanField(
        "Project selection occurs in previous cycle",
        description="Select this option if selectors submit their preferences in the "
        "academic cycle before the project runs. This is commonly the case for UG "
        "projects, but not for PGT projects.",
    )

    selection_open_to_all = BooleanField(
        "This is an opt-in project open to all students, regardless of their degree programme",
        description="By default, selectors are auto-enrolled based on their degree programme. "
        "If this option is selected then selectors from all eligible years will be "
        "auto-enrolled as selectors. If no project selection is made, the selector "
        "is assumed not to have opted-in.",
    )

    auto_enrol_enable = BooleanField(
        "Automatically enrol selectors during rollover",
        description="If selected, students participating in the specified programmes and "
        "at the appropriate stage will automatically be enrolled as "
        "selectors during rollover of the academic year.",
    )

    auto_enroll_years = RadioField("In which years should students be auto-enrolled as selectors?", choices=auto_enrol_year_choices, coerce=int)

    programmes = QuerySelectMultipleField(
        "Auto-enrol students as selectors from degree programmes", query_factory=GetActiveDegreeProgrammes, get_label=BuildDegreeProgrammeName
    )

    # validate_programmes() is an inline validator that is called automatically by WTForms to validate
    # the programmes field; see https://wtforms.readthedocs.io/en/2.3.x/forms/#inline-validators
    @staticmethod
    def validate_programmes(form, field):
        # if selection is open to anyone, there is no need to specify a particular set of programmes
        if form.selection_open_to_all.data:
            return

        # otherwise, at least one programme should be specified
        if field.data is None or not isinstance(field.data, list) or len(field.data) == 0:
            raise ValidationError("At least one degree programme should be selected")

        # check all programmes are consistent with the specified project level
        for programme in field.data:
            programme: DegreeProgramme
            programme_type: DegreeType = programme.degree_type
            if programme_type.level != form.student_level.data:
                raise ValidationError("The selected degree programmes are not consistent with the required student level")

    advertise_research_group = BooleanField(
        "Advertise affiliations/research groups to students",
        description="Students will be shown the research group "
        "or other affiliation "
        "associated with each project. For example, this could be "
        "used to drive improved awareness of research teams "
        "within the department.",
    )

    use_project_tags = BooleanField("Use tags", description="Each project variant can be given one or more tags, which are advertised to students.")

    force_tag_groups = QuerySelectMultipleField(
        "Require tags from specific groups",
        query_factory=GetActiveProjectTagGroups,
        get_label="name",
        description="Forces projects to be tagged with at least one tag "
        "from a specified set of groups. For instance, this "
        "could be used "
        "to enforce a consistent labelling convention.",
    )


class AddProjectClassForm(Form, ProjectClassMixin):
    name = StringField(
        "Name",
        validators=[InputRequired(message="Name of project class is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_project_class],
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="An abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_project_class_abbrev],
    )

    submit = SubmitField("Add new project class")


class EditProjectClassForm(Form, ProjectClassMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[InputRequired(message="Name of project class is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_project_class],
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="An abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_project_class_abbrev],
    )


class EditProjectTextForm(Form, SaveChangesMixin):
    card_text_normal = TextAreaField("Text seen by normal selectors", render_kw={"rows": 5}, validators=[Optional()])

    card_text_optional = TextAreaField("Text seen by selectors for whom this project is optional", render_kw={"rows": 5}, validators=[Optional()])

    card_text_noninitial = TextAreaField("Text seen by selectors who may be changing supervisor", render_kw={"rows": 5}, validators=[Optional()])

    email_text_draft_match_preamble = TextAreaField("Preamble for notification of draft matching", render_kw={"rows": 5}, validators=[Optional()])

    email_text_final_match_preamble = TextAreaField("Preamble for notification of final matching", render_kw={"rows": 5}, validators=[Optional()])


class PeriodDefinitionMixin:
    name = StringField(
        "Name",
        description="Optional. Enter an alternative text name for this submission " 'period, such as "Autumn Term"',
        validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
    )

    start_date = DateTimeField(
        "Period start date", format="%d/%m/%Y", validators=[Optional()], description="The year will increment when a rollover takes place"
    )

    number_markers = IntegerField(
        "Number of markers to be assigned",
        default=DEFAULT_ASSIGNED_MARKERS,
        description="Number of markers that should be assigned to each project. Used during automated matching.",
        validators=[
            InputRequired("Please enter the required number of markers"),
            NumberRange(min=0, message="The required number of markers should not be negative"),
        ],
    )

    number_moderators = IntegerField(
        "Number of moderators to be assigned",
        default=DEFAULT_ASSIGNED_MODERATORS,
        description="Number of moderators that should be assigned to each project "
        "by default. Used during automated matching. Usually this should be "
        "set to zero. If required, moderators can be added manually during "
        "the marking workflow.",
        validators=[
            InputRequired("Please enter the required number of moderators"),
            NumberRange(min=0, message="The required number of moderators should not be negative"),
        ],
    )

    @staticmethod
    def validate_number_markers(form, field):
        if form._pclass.uses_marker and field.data == 0:
            raise ValidationError("This project class uses markers. The number of markers should be 1 or greater.")

    @staticmethod
    def validate_number_moderators(form, field):
        if form._pclass.uses_moderator and field.data == 0:
            raise ValidationError("This project class uses moderators. This number of moderators should be 1 or greater.")

    collect_project_feedback = BooleanField("Collect project feedback online")


def AddPeriodDefinitionFormFactory(pclass: ProjectClass):
    class AddPeriodDefinitionForm(Form, PeriodDefinitionMixin, PeriodPresentationsMixin):
        _pclass = pclass

        submit = SubmitField("Add new submission period")

    return AddPeriodDefinitionForm


def EditPeriodDefinitionFormFactory(pclass: ProjectClass):
    class EditPeriodDefinitionForm(Form, PeriodDefinitionMixin, PeriodPresentationsMixin, SaveChangesMixin):
        _pclass = pclass

    return EditPeriodDefinitionForm


class SupervisorMixin:
    colour = StringField(
        "Colour", validators=[Length(max=DEFAULT_STRING_LENGTH)], description="Assign a colour to help students identify the roles of team members"
    )


class AddSupervisorForm(Form, SupervisorMixin):
    name = StringField(
        "Name",
        validators=[InputRequired(message="Name of supervisory role is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_supervisor],
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="An abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), globally_unique_supervisor_abbrev],
    )
    submit = SubmitField("Add new supervisory role")


class EditSupervisorForm(Form, SupervisorMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[InputRequired(message="Name of supervisory role is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_supervisor],
    )

    abbreviation = StringField(
        "Abbreviation",
        validators=[InputRequired(message="An abbreviation is required"), Length(max=DEFAULT_STRING_LENGTH), unique_or_original_supervisor_abbrev],
    )


class EmailLogForm(Form):
    weeks = IntegerField(
        "Age cutoff in weeks", validators=[InputRequired(message="Cutoff is required. Emails older than the limit will be removed.")]
    )

    delete_age = SubmitField("Delete older emails")


class BackupManageForm(Form):
    weeks = IntegerField(
        "Age cutoff in weeks", validators=[InputRequired(message="Cutoff is required. Backups older than the limit will be removed.")]
    )

    delete_age = SubmitField("Delete older backups")


def MessageMixinFactory(query_factory, convenor_editing):
    class MessageMixin:
        show_students = BooleanField("Students")

        show_faculty = BooleanField("Faculty")

        show_office = BooleanField("School Office/Professional Services")

        if not convenor_editing:
            show_login = BooleanField("Display on login screen if a broadcast message")

        dismissible = BooleanField("Allow message to be dismissed")

        title = StringField(
            "Title", validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)], description="Optional. Briefly summarize your message."
        )

        # TODO: would prefer to validate that the message length is not zero, but this is not trivial
        #  with TinyMCE. Various suggested solutions, not yet implemented here:
        #    https://stackoverflow.com/questions/60834085/how-to-make-textarea-filed-mandatory-when-ive-applied-tinymce/66032994#66032994
        #    https://stackoverflow.com/questions/37701600/validating-tinymce-for-empty-inputs
        #    https://stackoverflow.com/questions/38558091/tinymce-empty-validation-check
        body = TextAreaField("Message", render_kw={"rows": 10})

        project_classes = QuerySelectMultipleField("Display to users enrolled for", query_factory=query_factory, get_label="name")

    return MessageMixin


# we *must* implement this form using a factory function because we have to adjust its class members
def AddMessageFormFactory(convenor_editing=False):
    Mixin = MessageMixinFactory(GetConvenorProjectClasses if convenor_editing else GetAllProjectClasses, convenor_editing=convenor_editing)

    class AddMessageForm(Form, Mixin):
        submit = SubmitField("Add new message")

        _validator = InputRequired(message="At least one project class should be selected") if convenor_editing else Optional()

        @staticmethod
        def validate_project_classes(form, field):
            return form._validator(form, field)

    return AddMessageForm


def EditMessageFormFactory(convenor_editing=False):
    Mixin = MessageMixinFactory(GetConvenorProjectClasses if convenor_editing else GetAllProjectClasses, convenor_editing=convenor_editing)

    class EditMessageForm(Form, Mixin, SaveChangesMixin):
        _validator = InputRequired(message="At least one project class should be selected") if convenor_editing else Optional()

        @staticmethod
        def validate_project_classes(form, field):
            return form._validator(form, field)

    return EditMessageForm


class ScheduleTypeMixin:
    available_types = [("interval", "Fixed interval"), ("crontab", "Crontab")]
    type = SelectField("Type of schedule", choices=available_types)


class ScheduleTypeForm(Form, ScheduleTypeMixin):
    submit = SubmitField("Select type")


class ScheduledTaskMixin:
    name = StringField("Name", validators=[InputRequired(message="A task name is required"), Length(max=DEFAULT_STRING_LENGTH)])

    owner = QuerySelectField("Owner", query_factory=GetSysadminUsers, get_label=BuildSysadminUserName)

    tasks_available = [
        ("app.tasks.prune_email.prune_email_log", "Prune email log"),
        ("app.tasks.background_tasks.prune_background_tasks", "Prune background tasks"),
        ("app.tasks.backup.backup", "Perform local backup"),
        ("app.tasks.backup.thin", "Thin local backups"),
        ("app.tasks.backup.limit_size", "Enforce limit on size of backup folder"),
        ("app.tasks.backup.clean_up", "Clean up backup folder"),
        ("app.tasks.backup.drop_absent_backups", "Drop absent backups"),
        ("app.tasks.popularity.update_popularity_data", "Update LiveProject popularity data"),
        ("app.tasks.popularity.thin", "Thin LiveProject popularity data"),
        ("app.tasks.maintenance.maintenance", "Perform regular database maintenance"),
        ("app.tasks.maintenance.fix_unencrypted_assets", "Test for and fix unencrypted assets"),
        ("app.tasks.email_notifications.send_daily_notifications", "Send daily email notifications"),
        ("app.tasks.maintenance.asset_garbage_collection", "Garbage collection for expired assets"),
        ("app.tasks.batch_create.garbage_collection", "Garbage collection for batch student import"),
        ("app.tasks.maintenance.asset_check_lost", "Test for lost assets"),
        ("app.tasks.maintenance.asset_check_unattached", "Test for unattached assets"),
        ("app.tasks.system.process_pings", "Process pings from front end instances"),
        ("app.tasks.sessions.sift_sessions", "Perform MongoDB session maintenance"),
        ("app.tasks.canvas.canvas_user_checkin", "Synchronize Canvas user database with submitter databases"),
        ("app.tasks.canvas.canvas_submission_checkin", "Synchronize Canvas submission availability for active submission periods"),
        ("app.tasks.marking.conflate_marks_for_period", "Conflate marks for a specified submission period"),
        ("app.tasks.marking.generate_feedback_reports", "Generate feedback reports for a specified submission period and recipe"),
        ("app.tasks.cloud_api_audit.send_api_events_to_telemetry", "Send Cloud API audit events to telemetry object store"),
        ("celery.backend_cleanup", "Periodic Celery backend cleanup"),
    ]

    task = SelectField("Task", choices=tasks_available)

    queues_available = [("default", "Default (for ordinary or long-running tasks)"), ("priority", "High-priority")]

    queue = SelectField("Queue", choices=queues_available)

    arguments = StringField("Arguments", validators=[valid_json, Length(max=DEFAULT_STRING_LENGTH)], description="Format as a JSON list.")

    keyword_arguments = StringField(
        "Keyword arguments", validators=[valid_json, Length(max=DEFAULT_STRING_LENGTH)], description="Format as a JSON dictionary."
    )

    expires = DateTimeField("Expires at", validators=[Optional()], description="Optional. Format YYYY-mm-dd HH:MM:SS. Leave blank for no expiry.")


class IntervalMixin:
    every = IntegerField("Run every", validators=[InputRequired(message="You must enter a nonzero interval")])

    available_periods = [("seconds", "seconds"), ("minutes", "minutes"), ("hours", "hours"), ("days", "days"), ("weeks", "weeks")]
    period = SelectField("Period", choices=available_periods)


class CrontabMixin:
    minute = StringField("Minute pattern", validators=[InputRequired(message="You must enter a pattern"), Length(max=DEFAULT_STRING_LENGTH)])

    hour = StringField("Hour pattern", validators=[InputRequired(message="You must enter a pattern"), Length(max=DEFAULT_STRING_LENGTH)])

    day_of_week = StringField(
        "Day-of-week pattern", validators=[InputRequired(message="You must enter a pattern"), Length(max=DEFAULT_STRING_LENGTH)]
    )

    day_of_month = StringField(
        "Day-of-month pattern", validators=[InputRequired(message="You must enter a pattern"), Length(max=DEFAULT_STRING_LENGTH)]
    )

    month_of_year = StringField(
        "Month-of-year pattern", validators=[InputRequired(message="You must enter a pattern"), Length(max=DEFAULT_STRING_LENGTH)]
    )


class AddIntervalScheduledTask(Form, ScheduledTaskMixin, IntervalMixin):
    submit = SubmitField("Add new task")


class EditIntervalScheduledTask(Form, ScheduledTaskMixin, IntervalMixin, SaveChangesMixin):
    pass


class AddCrontabScheduledTask(Form, ScheduledTaskMixin, CrontabMixin):
    submit = SubmitField("Add new task")


class EditCrontabScheduledTask(Form, ScheduledTaskMixin, CrontabMixin, SaveChangesMixin):
    pass


class BackupOptionsMixin:
    hourly_choices = [
        (1, "1 day"),
        (2, "2 days"),
        (3, "3 days"),
        (4, "4 days"),
        (5, "5 days"),
        (6, "6 days"),
        (7, "7 days"),
        (8, "8 days"),
        (9, "9 days"),
        (10, "10 days"),
        (11, "11 days"),
        (12, "12 days"),
        (13, "13 days"),
        (14, "14 days"),
    ]
    keep_hourly = SelectField("Keep hourly backups for", choices=hourly_choices, coerce=int)

    daily_choices = [(1, "1 week"), (2, "2 weeks"), (3, "3 weeks"), (4, "4 weeks"), (5, "5 weeks"), (6, "6 weeks"), (7, "7 weeks"), (8, "8 weeks")]
    keep_daily = SelectField(
        "Keep daily backups for",
        choices=daily_choices,
        coerce=int,
        description="Daily backups are kept when hourly backups are no longer being retained. "
        "Use this field to determine for how long daily backups are stored. "
        "After this time backups are retained only weekly.",
    )

    # field names for limits are blank; to get formatting right they're included directly on the template
    backup_limit = FloatField("Limit total size of backups", validators=[Optional()], description="Leave blank for no limit.")

    units_choices = [(BackupConfiguration.KEY_MB, "Mb"), (BackupConfiguration.KEY_GB, "Gb"), (BackupConfiguration.KEY_TB, "Tb")]
    limit_units = SelectField("Units", choices=units_choices, coerce=int)


class EditBackupOptionsForm(Form, BackupOptionsMixin):
    submit = SubmitField("Save changes")


class SkillGroupMixin:
    colour = StringField(
        "Colour",
        validators=[Length(max=DEFAULT_STRING_LENGTH)],
        description="Assign a colour to help students identify skills belonging to this group",
    )

    add_group = BooleanField("Add group name to skill labels", description="Skills in this group to be labelled as group-name: skill-name")


class AddSkillGroupForm(Form, SkillGroupMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Please supply a unique name for this group"),
            Length(max=DEFAULT_STRING_LENGTH),
            globally_unique_skill_group,
        ],
    )

    submit = SubmitField("Add new group")


class EditSkillGroupForm(Form, SkillGroupMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Please supply a unique name for this group"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_skill_group,
        ],
    )


class TransferableSkillMixin:
    group = QuerySelectField("Skill group", query_factory=GetActiveSkillGroups, get_label="name")


class AddTransferableSkillForm(Form, TransferableSkillMixin):
    name = StringField(
        "Skill",
        validators=[
            InputRequired(message="Name of transferable skill is required"),
            Length(max=DEFAULT_STRING_LENGTH),
            globally_unique_transferable_skill,
        ],
    )

    submit = SubmitField("Add new transferable skill")


class EditTransferableSkillForm(Form, TransferableSkillMixin, SaveChangesMixin):
    name = StringField(
        "Skill",
        validators=[
            InputRequired(message="Name of transferable skill is required"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_transferable_skill,
        ],
    )


class ProjectTagGroupMixin:
    add_group = BooleanField("Add group name to tag labels", description="Tags in this group will be labelled as group-name: tag-name")

    default = BooleanField("Default group for new tags", description="New dynamically generated tags will be added to this group")


class AddProjectTagGroupForm(Form, ProjectTagGroupMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Please supply a unique name for this group"),
            Length(max=DEFAULT_STRING_LENGTH),
            globally_unique_project_tag_group,
        ],
    )

    submit = SubmitField("Add new group")


class EditProjectTagGroupForm(Form, ProjectTagGroupMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Please supply a unique name for this group"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_project_tag_group,
        ],
    )


class ProjectTagMixin:
    group = QuerySelectField("Tag group", query_factory=GetActiveProjectTagGroups, get_label="name")

    colour = StringField(
        "Colour", validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)], description="Assign a colour to help students recognize this tag"
    )


class AddProjectTagForm(Form, ProjectTagMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Please supply a unique name for this tag"),
            Length(max=DEFAULT_STRING_LENGTH),
            globally_unique_project_tag,
        ],
    )

    submit = SubmitField("Add new tag")


class EditProjectTagForm(Form, ProjectTagMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        validators=[
            InputRequired(message="Please supply a unique name for this tag"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_project_tag,
        ],
    )


class PuLPSolverMixin:
    solver = SelectField(
        "Solver",
        choices=solver_choices,
        coerce=int,
        description="The optimizer can use a number of different solvers. If in doubt, use the "
        "CBC external solver, which should work on amd64 and arm64 architectures. "
        "CBC is substantially more performant than GLPK. "
        "Alternatively, download a version of the optimization "
        "problem as a .LP file and perform the optimization offline using "
        "CPLEX, Gurobi or SCIP. These options are not available by default to "
        "run in the cloud.",
    )


def MatchingMixinFactory(pclasses_query, include_matches_query, base_match):
    class MatchingMixin:
        name = StringField(
            "Name",
            description="Enter a short tag to identify this match",
            validators=[InputRequired(message="Please supply a unique name"), Length(max=DEFAULT_STRING_LENGTH)],
        )

        pclasses_to_include = QuerySelectMultipleField(
            "Select project classes to include in this match", query_factory=pclasses_query, get_label="name"
        )

        if base_match is None or base_match.include_only_submitted is True:
            include_only_submitted = BooleanField("Include only selectors who submitted preferences")

        ignore_per_faculty_limits = BooleanField("Ignore CATS limits specified in faculty accounts")

        ignore_programme_prefs = BooleanField("Ignore degree programme preferences")

        years_memory = SelectField("Include how many years history when levelling workloads?", choices=matching_history_choices, coerce=int)

        supervising_limit = IntegerField(
            "CATS limit for supervising",
            validators=[InputRequired(message="Please specify the maximum number of CATS that can be allocated per faculty")],
        )

        marking_limit = IntegerField(
            "CATS limit for marking",
            validators=[InputRequired(message="Please specify the maximum number of CATS that can be allocated per faculty")],
        )

        max_marking_multiplicity = IntegerField(
            "Maximum multiplicity for markers",
            description="Markers may be assigned multiple instances of the same project, up to the maximum multiplicity specified",
            validators=[InputRequired(message="Please specify a multiplicity")],
        )

        max_different_group_projects = IntegerField(
            "Maximum number of different group project types that can be assigned to a single supervisor",
            description="Students from different types of group projects can "
            "be assigned to a single supervisor, but for "
            "efficiency it may be preferable to have a single "
            "project type. This determines the maximum number of "
            "different project types assigned to a single "
            "supervisor. Leave blank to impose no limit.",
            validators=[Optional(), NumberRange(min=1, message="The maximum number of group project types cannot be less than 1.")],
        )

        max_different_all_projects = IntegerField(
            "Maximum number of different projects (ordinary or group) that can be assigned to a single supervisor",
            description="Similar to above, but including projects of any "
            "type (either ordinary projects or group projects). "
            "If a limit has been specified for group projects, this "
            "limit must be at least as large. Leave blank to "
            "impose no limit.",
            validators=[Optional(), NumberRange(min=1, message="The maximum number of project types cannot be less than 1.")],
        )

        @staticmethod
        def validate_max_different_all_projects(form, field):
            # if no limit for group-type projects is specified, nothing to do
            if form.max_different_group_projects.data is None:
                return

            # if no limit is specified, nothing to do (even if a limit for group-type projects is specified)
            if field.data is None:
                return

            if field.data < form.max_different_group_projects.data:
                raise ValidationError("The maximum number of project types must be at least as large as the maximum number of group project types.")

        include_matches = QuerySelectMultipleField(
            "When levelling workloads, include CATS from existing matches", query_factory=include_matches_query, get_label="name"
        )

        if base_match is not None:
            base_bias = FloatField(
                "Bias to base match",
                default=10.0,
                description="Choose large values to bias the fit towards the base match. "
                "Smaller values allow the optimizer to modify the base match to "
                "improve the fit in other ways, such as levelling workloads or "
                "including the preferences of selectors who did not appear in "
                "the base.",
                validators=[InputRequired(message="Please specify a base bias")],
            )

            force_base = BooleanField('Force agreement with assignments in "{name}"'.format(name=base_match.name))

        levelling_bias = FloatField(
            "Workload levelling bias",
            default=1.0,
            description="This sets the normalization of the workload levelling tension in "
            "the objective function. This term tensions good student matches against "
            "roughly equal workload for all faculty members who supervise, "
            "perform marking, or both. Set to 0 to turn off workload levelling. "
            "Set to values less than 1 to "
            "prioritize matching to high-ranked projects rather than equal workloads. "
            "Set to large values to prioritize equal workloads rather than "
            "student matches to high-ranked projects.",
            validators=[InputRequired(message="Please specify a levelling bias")],
        )

        intra_group_tension = FloatField(
            "Intra-group tension",
            default=2.0,
            description="This sets the tension with which the typical workload for "
            "each faculty group (supervisors, markers, and those who do both) "
            "are held together. Set to large values to keep workloads "
            "as closely matched as possible.",
            validators=[InputRequired(message="Please specify an intra-group tension")],
        )

        supervising_pressure = FloatField(
            "Supervising downward pressure",
            default=1.0,
            description="Sets the pressure to apply to the maximum supervisory allocation for any individual faculty member.",
            validators=[InputRequired(message="Please specify a supervising pressure")],
        )

        marking_pressure = FloatField(
            "Marking downward pressure",
            default=1.0,
            description="Sets the pressure to apply to the maximum marking allocation for any individual faculty member.",
            validators=[InputRequired(message="Please specify a marking pressure")],
        )

        CATS_violation_penalty = FloatField(
            "CATS limit violation penalty",
            default=5.0,
            description="Determines the penalty imposed for violating CATS limits.",
            validators=[InputRequired(message="Please specify a penalty")],
        )

        no_assignment_penalty = FloatField(
            "No assignment penalty",
            default=5.0,
            description="Determines the penalty imposed for leaving supervisory faculty without a project assignment.",
            validators=[InputRequired(message="Please specify a penalty")],
        )

        programme_bias = FloatField(
            "Degree programme preference bias",
            default=1.5,
            description="Values greater than 1 bias the optimization to match students "
            "on given degree programmes with projects that "
            "are marked as preferring that programme. "
            "A value of 1 disables this preference.",
            validators=[InputRequired(message="Please specify a programme preference bias")],
        )

        bookmark_bias = FloatField(
            "Penalty for using bookmarks",
            default=0.333,
            description="Values less than 1 penalize preferences taken from bookmark data "
            "rather than a verified submission. Set to 1 if you do not wish "
            "to distinguish these cases.",
            validators=[InputRequired(message="Please specify a bookmark bias")],
        )

        use_hints = BooleanField(
            "Use convenor hints",
            default=True,
            description='Enforce "require"/"forbid" hints and ask optimizer to respect '
            '(strong) "encourage"/"discourage" hints. Adjust the bias for '
            "encourage/discourage hints below.",
        )

        require_to_encourage = BooleanField(
            'Treat "require" as "strongly encouraged"',
            default=False,
            description='Convert all "require" hints to "strongly encouraged". Use to '
            "debug infeasibility issues when too many hints have been "
            "specified, making the problem over-determined.",
        )

        forbid_to_discourage = BooleanField(
            'Treat "forbid" as "strongly discouraged"',
            default=False,
            description='Convert all "forbid" hints to "strongly discouraged". Use to '
            "debug infeasibility issues when too many hints have been "
            "specified, making the problem over-determined.",
        )

        encourage_bias = FloatField('Bias for convenor "encouraged" hint', default=2.0, validators=[InputRequired(message="Please specify a bias")])

        discourage_bias = FloatField('Bias for convenor "discouraged" hint', default=0.5, validators=[InputRequired(message="Please specify a bias")])

        strong_encourage_bias = FloatField(
            'Bias for convenor "strongly encouraged" hint', default=5.0, validators=[InputRequired(message="Please specify a bias")]
        )

        strong_discourage_bias = FloatField(
            'Bias for convenor "strongly discouraged" hint', default=0.2, validators=[InputRequired(message="Please specify a bias")]
        )

    return MatchingMixin


def NewMatchFormFactory(year, base_id=None, base_match=None):
    Mixin = MatchingMixinFactory(
        partial(GetAutomatedMatchPClasses, year, base_id), partial(GetMatchingAttempts, year, base_id), base_match=base_match
    )

    class NewMatchForm(Form, Mixin, PuLPSolverMixin):
        submit = SubmitField("Run match in the cloud")

        offline = SubmitField("Generate .LP file for processing offline")

        @staticmethod
        def validate_name(form, field):
            return globally_unique_matching_name(year, form, field)

    return NewMatchForm


class UploadMatchForm(Form):
    solver = SelectField(
        "Solver", choices=solver_choices, coerce=int, description="Select the solver used to produce the solution file you are uploading."
    )

    submit = SubmitField("Upload solution")


def RenameMatchFormFactory(year):
    class RenameMatchForm(Form):
        name = StringField(
            "New name",
            description="Enter a short tag to identify this match",
            validators=[InputRequired(message="Please supply a unique name"), Length(max=DEFAULT_STRING_LENGTH)],
        )

        submit = SubmitField("Rename match")

        @staticmethod
        def validate_name(form, field):
            return unique_or_original_matching_name(year, form, field)

    return RenameMatchForm


def CompareMatchFormFactory(year: int, self_id: int, pclasses: ProjectClassConfig | int | List[int] | None, is_root: bool):
    class CompareMatchForm(Form):
        target = QuerySelectField("Compare to", query_factory=partial(GetComparatorMatches, year, self_id, pclasses, is_root), get_label="name")

        compare = SubmitField("Compare")

    return CompareMatchForm


class EditSupervisorRolesForm(Form):
    supervisors = QuerySelectMultipleField("Supervisors", query_factory=GetActiveFaculty, get_label=BuildActiveFacultyName)

    @staticmethod
    def validate_supervisors(form, field):
        if field.data is None or not isinstance(field.data, list) or len(field.data) == 0:
            raise ValidationError("At least one supervisor should be selected.")

    submit = SubmitField("Save changes")


def PresentationAssessmentMixinFactory(assessment: PresentationAssessment, query_factory):
    class PresentationAssessmentMixin:
        name = StringField(
            "Name",
            description="Enter a short name to identify this assessment event",
            validators=[InputRequired(message="Please supply a unique name"), Length(max=DEFAULT_STRING_LENGTH)],
        )

        if assessment is None or (assessment is not None and not assessment.requested_availability and not assessment.skip_availability):
            submission_periods = QuerySelectMultipleField(
                "Select those submission periods for which project presentations will be given",
                query_factory=query_factory,
                get_label=BuildSubmissionPeriodName,
            )

    return PresentationAssessmentMixin


def AddPresentationAssessmentFormFactory(year):
    Mixin = PresentationAssessmentMixinFactory(None, partial(GetUnattachedSubmissionPeriods, None))

    class AddPresentationAssessmentForm(Form, Mixin):
        submit = SubmitField("Add new assessment")

        @staticmethod
        def validate_name(form, field):
            return globally_unique_assessment_name(year, form, field)

    return AddPresentationAssessmentForm


def EditPresentationAssessmentFormFactory(year, assessment: PresentationAssessment):
    Mixin = PresentationAssessmentMixinFactory(assessment, partial(GetUnattachedSubmissionPeriods, assessment.id))

    class EditPresentationAssessmentForm(Form, Mixin, SaveChangesMixin):
        @staticmethod
        def validate_name(form, field):
            return unique_or_original_assessment_name(year, form, field)

    return EditPresentationAssessmentForm


class SessionMixin:
    name = StringField("Session label", validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)])

    date = DateTimeField("Date", format="%d/%m/%Y", validators=[InputRequired()], description="Specify the date for this session")

    session_type = SelectField("Session type", choices=session_choices, coerce=int)

    rooms = QuerySelectMultipleField("Select the rooms that are available for this session", query_factory=GetAllRooms, get_label=BuildRoomLabel)


class AddSessionForm(Form, SessionMixin):
    submit = SubmitField("Add session")


class EditSessionForm(Form, SessionMixin, SaveChangesMixin):
    pass


class BuildingMixin:
    name = StringField(
        "Name",
        description="Enter a short name or identifier for the building",
        validators=[InputRequired("A unique name is required"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    colour = StringField(
        "Colour", validators=[Length(max=DEFAULT_STRING_LENGTH)], description="Specify a colour to help identify rooms located in this building"
    )


class AddBuildingForm(Form, BuildingMixin):
    submit = SubmitField("Add building")

    @staticmethod
    def validate_name(form, field):
        return globally_unique_building_name(form, field)


class EditBuildingForm(Form, BuildingMixin, SaveChangesMixin):
    @staticmethod
    def validate_name(form, field):
        return unique_or_original_building_name(form, field)


class RoomMixin:
    name = StringField(
        "Name",
        description="Enter a number or label for the venue",
        validators=[InputRequired("A unique name is required"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    building = QuerySelectField("Building", query_factory=GetAllBuildings, get_label="name")

    capacity = IntegerField(
        "Capacity",
        description="How many people will this room accommodate?",
        validators=[InputRequired("Enter the number of people who can be accommodated")],
    )

    maximum_occupancy = IntegerField(
        "Maximum number of occupying groups",
        description="Some rooms may be physically partitioned, allowing multiple groups "
        "to be specified in the same space. Alternatively, this can be used to "
        "model teleconference meeting rooms such as Zoom rooms, where multiple "
        'groups will be assigned to the same "venue" even though they are '
        "really distinct.",
        validators=[
            InputRequired("Enter the maximum number of occupying groups. Enter 1 if the room can only be singly occupupied."),
            NumberRange(min=1, max=100, message="The specified occupancy should be between 1 and 100."),
        ],
    )

    lecture_capture = BooleanField("Lecture capture available")


class AddRoomForm(Form, RoomMixin):
    submit = SubmitField("Add room")

    @staticmethod
    def validate_name(form, field):
        return globally_unique_room_name(form, field)


class EditRoomForm(Form, RoomMixin, SaveChangesMixin):
    @staticmethod
    def validate_name(form, field):
        return unique_or_original_room_name(form, field)


class AssetLicenseMixin:
    name = StringField(
        "Name",
        description="Enter a name to identify this license",
        validators=[InputRequired(message="Please supply a unique name"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    colour = StringField(
        "Colour", validators=[Length(max=DEFAULT_STRING_LENGTH)], description="Assign a colour to identify assets tagged with this license"
    )

    abbreviation = StringField(
        "Abbreviation",
        description="Enter a short name used to visually tag content provided under this license",
        validators=[InputRequired(message="Please supply a unique abbreviation"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    description = TextAreaField(
        "Description", render_kw={"rows": 5}, validators=[InputRequired(message="Please supply a brief description of the license conditions")]
    )

    version = StringField(
        "Version",
        description="Please enter a version number or identifier for this license",
        validators=[InputRequired(message="Please supply a valid version string"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    url = StringField("Web address", description="Optional. Enter a web address for this license.")

    allows_redistribution = BooleanField("License allows content to be redistributed")


class AddAssetLicenseForm(Form, AssetLicenseMixin):
    @staticmethod
    def validate_name(form, field):
        return globally_unique_license_name(form, field)

    @staticmethod
    def validate_abbreviation(form, field):
        return globally_unique_license_abbreviation(form, field)

    @staticmethod
    def validate_version(form, field):
        return per_license_unique_version(form, field)

    submit = SubmitField("Add new license")


class EditAssetLicenseForm(Form, AssetLicenseMixin, SaveChangesMixin):
    @staticmethod
    def validate_name(form, field):
        return unique_or_original_license_name(form, field)

    @staticmethod
    def validate_abbreviation(form, field):
        return unique_or_original_license_abbreviation(form, field)

    @staticmethod
    def validatE_version(form, field):
        return per_license_unique_or_original_version(form, field)


def AvailabilityFormFactory(assessment: PresentationAssessment):
    class AvailabilityForm(Form):
        # deadline for response
        availability_deadline = DateTimeField("Deadline", format="%d/%m/%Y", validators=[InputRequired()])

        if not assessment.skip_availability:
            # submit button: open feedback
            issue_requests = SubmitField("Issue availability requests")

    return AvailabilityForm


class ScheduleNameMixin:
    name = StringField(
        "Name",
        description="Enter a short name to identify this schedule",
        validators=[InputRequired(message="Please supply a unique name"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    tag = StringField(
        "Tag",
        description="Enter a unique tag (containing no white space) for use as part of a URL",
        validators=[InputRequired(message="Please supply a unique tag"), Length(max=DEFAULT_STRING_LENGTH)],
    )


def ScheduleNameCreateValidatorFactory(assessment: PresentationAssessment):
    class Validator:
        @staticmethod
        def validate_name(form, field):
            return globally_unique_schedule_name(assessment.id, form, field)

        @staticmethod
        def validate_tag(form, field):
            isvalid = re.match(r"[\w-]*$", field.data)
            if not isvalid:
                raise ValidationError("The tag should contain only letters, numbers, underscores or dashes, and be valid as part of a URL")

            return globally_unique_schedule_tag(form, field)

    return Validator


def ScheduleNameRenameValidatorFactory(assessment: PresentationAssessment):
    class Validator:
        @staticmethod
        def validate_name(form, field):
            return unique_or_original_schedule_name(assessment.id, form, field)

        @staticmethod
        def validate_tag(form, field):
            isvalid = re.match(r"[\w-]*$", field.data)
            if not isvalid:
                raise ValidationError("The tag should contain only letters, numbers, underscores or dashes, and be valid as part of a URL")

            return unique_or_original_schedule_tag(form, field)

    return Validator


class ScheduleSettingsMixin:
    assessor_assigned_limit = IntegerField(
        "Maximum number of assignments per assessor",
        default=3,
        description="Enter the maximum number of times each assessor can be scheduled.",
        validators=[InputRequired("Please enter a positive integer"), NumberRange(min=0, message="Please enter a postive integer")],
    )

    if_needed_cost = FloatField(
        "Cost for using faculty tagged as if-needed",
        default=1.5,
        description="Normalized relative to the cost for using a new slot.",
        validators=[InputRequired("Please enter a suitable positive decimal.")],
    )

    levelling_tension = FloatField(
        "Tension used to level workloads",
        default=1.5,
        description="Cost of introducing a workload inequality of one session, normalized to the cost of using a new slot.",
        validators=[InputRequired("Please enter a suitable positive decimal.")],
    )

    ignore_coscheduling = BooleanField(
        "Ignore coscheduling constraints",
        default=False,
        description="Ignore constraints on students taking the same presentation being scheduled in the same slot.",
    )

    assessor_multiplicity_per_session = IntegerField(
        "Maximum number of times assessors to be scheduled per session",
        default=1,
        description="This can be useful for presentations delivered "
        "remotely via Zoom or Teams. In this case, "
        "assessors need not necessarily form fixed groups.",
        validators=[InputRequired("Please enter a positive integer"), NumberRange(min=1, message="Please enter a positive integer")],
    )

    @staticmethod
    def validate_assessor_multiplicity_per_session(form, field):
        multiplicity = field.data
        assigned_limit = form.assessor_assigned_limit.data

        if multiplicity is not None and assigned_limit is not None:
            if multiplicity > assigned_limit:
                raise ValidationError("The specified multiplicity should be less than or equal to the maximum number of assignments per assessor")

    all_assessors_in_pool = RadioField("Assessor configuration", choices=ScheduleAttempt.ASSESSOR_CHOICES, coerce=int)


def NewScheduleFormFactory(assessment):
    validator = ScheduleNameCreateValidatorFactory(assessment)

    class NewScheduleForm(Form, ScheduleNameMixin, validator, ScheduleSettingsMixin, PuLPSolverMixin):
        submit = SubmitField("Run scheduling in the cloud")

        offline = SubmitField("Generate .LP file for processing offline")

    return NewScheduleForm


class UploadScheduleForm(Form):
    solver = SelectField(
        "Solver", choices=solver_choices, coerce=int, description="Select the solver used to produce the solution file you are uploading."
    )

    submit = SubmitField("Upload solution")


def RenameScheduleFormFactory(assessment):
    validator = ScheduleNameRenameValidatorFactory(assessment)

    class RenameScheduleForm(Form, ScheduleNameMixin, validator):
        submit = SubmitField("Rename schedule")

    return RenameScheduleForm


def ImposeConstraintsScheduleFormFactory(assessment):
    validator = ScheduleNameCreateValidatorFactory(assessment)

    class ImposeConstraintsScheduleForm(Form, ScheduleNameMixin, validator):
        allow_new_slots = BooleanField("Allow new slots to be created", default=False)

        submit = SubmitField("Perform adjustment")

    return ImposeConstraintsScheduleForm


class AssignmentLimitForm(Form, SaveChangesMixin):
    assigned_limit = IntegerField("Maximum number of sessions to assign to this assessor", validators=[Optional()])


class LevelSelectorMixin:
    selector = QuerySelectField("Select courses from FHEQ level", query_factory=GetFHEQLevels, get_label="name")


class LevelSelectorForm(Form, LevelSelectorMixin):
    pass


class FHEQLevelMixin:
    colour = StringField(
        "Colour", validators=[Length(max=DEFAULT_STRING_LENGTH)], description="Assign a colour to help distinguish modules belonging to this level"
    )


class AddFHEQLevelForm(Form, FHEQLevelMixin):
    name = StringField(
        "Name",
        description="Provide a name for this level",
        validators=[
            InputRequired(message="Please specify a name for this level"),
            Length(max=DEFAULT_STRING_LENGTH),
            globally_unique_FHEQ_level_name,
        ],
    )

    short_name = StringField(
        "Short name",
        description="A shortened name is used to save space on some displays",
        validators=[
            InputRequired(message="Please specify a short name for this level"),
            Length(max=DEFAULT_STRING_LENGTH),
            globally_unique_FHEQ_short_name,
        ],
    )

    numeric_level = IntegerField(
        "Numerical level", validators=[InputRequired(message="Please specify a numerical level"), globally_unique_FHEQ_numeric_level]
    )

    submit = SubmitField("Create new level")


class EditFHEQLevelForm(Form, FHEQLevelMixin, SaveChangesMixin):
    name = StringField(
        "Name",
        description="Provide a name for this level",
        validators=[
            InputRequired(message="Please specify a name for this level"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_FHEQ_level_name,
        ],
    )

    short_name = StringField(
        "Short name",
        description="A shortened name is used to save space on some displays",
        validators=[
            InputRequired(message="Please specify a short name for this level"),
            Length(max=DEFAULT_STRING_LENGTH),
            unique_or_original_FHEQ_short_name,
        ],
    )

    numeric_level = IntegerField(
        "Numerical level", validators=[InputRequired(message="Please specify a numerical level"), unique_or_original_FHEQ_numeric_level]
    )


def PublicScheduleFormFactory(schedule):
    class PublicScheduleForm(Form):
        selector = QuerySelectField(
            "Select the session you wish to view:", query_factory=partial(ScheduleSessionQuery, schedule.id), get_label=BuildScheduleSessionLabel
        )

    return PublicScheduleForm


def CompareScheduleFormFactory(assessment_id, self_id, is_root):
    class CompareScheduleForm(Form):
        target = QuerySelectField("Compare to", query_factory=partial(GetComparatorSchedules, assessment_id, self_id, is_root), get_label="name")

        compare = SubmitField("Compare")

    return CompareScheduleForm


def SelectMatchingYearFormFactory(allowed_years):
    class SelectMatchingYearForm(Form):
        selector = SelectField("Select year", choices=allowed_years, coerce=int)

    return SelectMatchingYearForm


def BackupMixinFactory(lock_default=False):
    class BackupMixin:
        labels = BasicTagSelectField(
            "Add labels to identify this backup",
            query_factory=GetActiveBackupLabels,
            get_label=BuildBackupLabelName,
            description="Use labels to identify backups with specific properties, or to collect backups into groups.",
            blank_text="Add labels...",
        )

        locked = BooleanField("Lock this backup to prevent removal during thinning", default=lock_default)

        unlock_date = DateTimeField(
            "Automatically unlock on",
            format="%d/%m/%Y",
            validators=[Optional()],
            description="Optionally specify a date when this backup will be automatically unlocked. Use to prevent a build-up of locked backup records that cannot be thinned.",
        )

    return BackupMixin


class EditBackupForm(Form, BackupMixinFactory(lock_default=False), SaveChangesMixin):
    pass


class ManualBackupForm(Form, BackupMixinFactory(lock_default=True)):
    description = StringField(
        "Description",
        description="Provide a short description of the purpose of this backup",
        validators=[InputRequired(message="Please provide a description"), Length(max=DEFAULT_STRING_LENGTH)],
    )

    submit = SubmitField("Backup now")


class FeedbackAssetMixin(LicenseMixin):
    project_classes = QuerySelectMultipleField("Available for use with project classes", query_factory=GetAllProjectClasses, get_label="name")

    tags = BasicTagSelectField(
        "Add tags to identify this asset",
        query_factory=GetActiveTemplateTags,
        get_label=BuildTemplateTagName,
        description="Use tags to identify assets with specific properties, or to organize them into groups.",
        blank_text="Add tags...",
    )

    is_template = BooleanField("This is a template that can be used to generate a feedback report", default=False)

    description = StringField(
        "Description",
        description="Optionally provide a short description of this asset",
        validators=[
            Optional(),
            Length(max=DEFAULT_STRING_LENGTH),
        ]
    )


class UploadFeedbackAssetForm(Form, FeedbackAssetMixin):
    label = StringField(
        "Label",
        description="Provide a label for this asset",
        validators=[
            InputRequired(message="Please provide a label"),
            Length(max=DEFAULT_STRING_LENGTH),
            Regexp(r"^[\w.]+$", message="The label should contain only letters, numbers and the underscore."),
            globally_unique_feedback_asset_label,
        ],
    )

    submit = SubmitField("Upload")


class EditFeedbackAssetForm(Form, FeedbackAssetMixin, SaveChangesMixin):
    label = StringField(
        "Label",
        description="Provide a label for this asset",
        validators=[
            InputRequired(message="Please provide a label"),
            Length(max=DEFAULT_STRING_LENGTH),
            Regexp(r"^[\w.]+$", message="The label should contain only letters, numbers and the underscore."),
            unique_or_original_feedback_asset_label,
        ],
    )


class FeedbackRecipeMixin:
    project_classes = QuerySelectMultipleField("Available for use with project classes", query_factory=GetAllProjectClasses, get_label="name")

    template = QuerySelectField(
        "Select a primary template to be used to generate the feedback report",
        query_factory=GetAllFeedbackTemplates,
        get_label="label",
        validators=[DataRequired(message="Please select a template")],
    )

    asset_list = QuerySelectMultipleField(
        "Optionally, make the following assets available", query_factory=GetAllNonTemplateFeedbackAssets, get_label="label", validators=[Optional()]
    )

    @staticmethod
    def validate_template(form, field):
        pclass_list = {pc.id: pc.abbreviation for pc in form.project_classes.data}

        for pc in form.template.data.project_classes:
            if pc.id in pclass_list:
                pclass_list.pop(pc.id)

        if len(pclass_list) > 0:
            raise ValidationError(f'Template "{form.template.data.label}" is not available for project classes {", ".join(pclass_list.values())}')

    @staticmethod
    def validate_asset_list(form, field):
        for asset in form.asset_list.data:
            pclass_list = {pc.id: pc.abbreviation for pc in form.project_classes.data}

            for pc in asset.project_classes:
                if pc.id in pclass_list:
                    pclass_list.pop(pc.id)

            if len(pclass_list) > 0:
                raise ValidationError(f'Asset "{asset.label}" is not available for project classes {", ".join(pclass_list.values())}')


class AddFeedbackRecipeForm(Form, FeedbackRecipeMixin):
    label = StringField(
        "Label",
        description="Provide a label for this recipe",
        validators=[
            InputRequired(message="Please provide a label"),
            Length(max=DEFAULT_STRING_LENGTH),
            Regexp(r"^[\w.]+$", message="The label should contain only letters, numbers and the underscore."),
            globally_unique_feedback_recipe_label,
        ],
    )

    submit = SubmitField("Create recipe")


class EditFeedbackRecipeForm(Form, FeedbackRecipeMixin, SaveChangesMixin):
    label = StringField(
        "Label",
        description="Provide a label for this recipe",
        validators=[
            InputRequired(message="Please provide a label"),
            Length(max=DEFAULT_STRING_LENGTH),
            Regexp(r"^[\w.]+$", message="The label should contain only letters, numbers and the underscore."),
            unique_or_original_feedback_recipe_label,
        ],
    )
