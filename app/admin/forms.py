#
# Created by David Seery on 10/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import StringField, IntegerField, SelectField, BooleanField, SubmitField, \
    TextAreaField, DateField, DateTimeField, FloatField, RadioField, ValidationError
from wtforms.validators import InputRequired, Optional, Length
from wtforms_alchemy.fields import QuerySelectField, QuerySelectMultipleField

from ..manage_users.forms import ResearchGroupMixin

from ..shared.forms.wtf_validators import globally_unique_group_name, unique_or_original_group_name, \
    globally_unique_group_abbreviation, unique_or_original_group_abbreviation, \
    globally_unique_degree_type, unique_or_original_degree_type,\
    globally_unique_degree_abbreviation, unique_or_original_degree_abbreviation,\
    globally_unique_degree_programme, unique_or_original_degree_programme, \
    globally_unique_course_code, unique_or_original_course_code, \
    globally_unique_programme_abbreviation, unique_or_original_programme_abbreviation, \
    globally_unique_transferable_skill, unique_or_original_transferable_skill, \
    globally_unique_skill_group, unique_or_original_skill_group, globally_unique_project_class, \
    unique_or_original_project_class, globally_unique_project_class_abbrev, unique_or_original_project_class_abbrev, \
    globally_unique_supervisor, unique_or_original_supervisor, globally_unique_matching_name, \
    globally_unique_supervisor_abbrev, unique_or_original_supervisor_abbrev, unique_or_original_matching_name, \
    globally_unique_assessment_name, unique_or_original_assessment_name, \
    globally_unique_building_name, unique_or_original_building_name, \
    globally_unique_room_name, unique_or_original_room_name, \
    globally_unique_schedule_name, unique_or_original_schedule_name, \
    globally_unique_schedule_tag, unique_or_original_schedule_tag, \
    globally_unique_module_code, unique_or_original_module_code, \
    globally_unique_FHEQ_level_name, unique_or_original_FHEQ_level_name, \
    globally_unique_FHEQ_short_name, unique_or_original_FHEQ_short_name, \
    globally_unique_FHEQ_year, unique_or_original_FHEQ_year, \
    globally_unique_license_name, unique_or_original_license_name, \
    globally_unique_license_abbreviation, unique_or_original_license_abbreviation, \
    per_license_unique_version, per_license_unique_or_original_version, \
    valid_json, NotOptionalIf

from ..shared.forms.queries import GetActiveDegreeTypes, GetActiveDegreeProgrammes, GetActiveSkillGroups, \
    BuildDegreeProgrammeName, GetPossibleConvenors, BuildSysadminUserName, BuildConvenorRealName, \
    GetAllProjectClasses, GetConvenorProjectClasses, GetSysadminUsers, GetAutomatedMatchPClasses, \
    GetMatchingAttempts, GetComparatorMatches, GetUnattachedSubmissionPeriods, BuildSubmissionPeriodName, \
    GetAllBuildings, GetAllRooms, BuildRoomLabel, GetFHEQLevels, BuildFHEQYearLabel, \
    ScheduleSessionQuery, BuildScheduleSessionLabel, GetComparatorSchedules, \
    BuildPossibleOfficeContacts, BuildOfficeContactName

from ..shared.forms.mixins import SaveChangesMixin, SubmissionPeriodPresentationsMixin

from ..models import BackupConfiguration, ScheduleAttempt, extent_choices, \
    matching_history_choices, solver_choices, session_choices, semester_choices, auto_enroll_year_choices, \
    DEFAULT_STRING_LENGTH

from functools import partial

import re


class AddResearchGroupForm(Form, ResearchGroupMixin):

    name = StringField('Name', validators=[InputRequired(message='Name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           globally_unique_group_name])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='Abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           globally_unique_group_abbreviation])

    submit = SubmitField('Add new group')


class EditResearchGroupForm(Form, ResearchGroupMixin, SaveChangesMixin):

    name = StringField('Name', validators=[InputRequired(message='Name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           unique_or_original_group_name])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='Abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           unique_or_original_group_abbreviation])


class DegreeTypeMixin():

    colour = StringField('Colour', description='Assign a colour to help identify this degree type.',
                         validators=[Length(max=DEFAULT_STRING_LENGTH)])

    duration = IntegerField('Duration', description='Enter the number of years study before a student graduates.',
                            validators=[InputRequired(message='Degree duration is required')])


class AddDegreeTypeForm(Form, DegreeTypeMixin):

    name = StringField('Name', validators=[InputRequired(message='Degree type name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           globally_unique_degree_type])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='Abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           globally_unique_degree_abbreviation])

    submit = SubmitField('Add new degree type')


class EditDegreeTypeForm(Form, DegreeTypeMixin, SaveChangesMixin):

    name = StringField('Name', validators=[InputRequired(message='Degree type name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           unique_or_original_degree_type])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='Abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           unique_or_original_degree_abbreviation])


class DegreeProgrammeMixin():

    degree_type = QuerySelectField('Degree type', query_factory=GetActiveDegreeTypes, get_label='name')

    show_type = BooleanField('Show degree type in name', default=True,
                             description="Select if the degree type, such as BSc (Hons) or MPhys, should be "
                                         "included in the programme's full name")

    foundation_year = BooleanField('Includes foundation year', default=False)

    year_out = BooleanField('Includes year out', default=False,
                            description="Select if this programme includes a year abroad, and industrial "
                                        "placement year, or another type of year away from the University")

    year_out_value = IntegerField("Year out", default=3,
                                  description="Enter the numerical value of the year that should be regarded "
                                              "as the year out. Ignored if the 'year out' flag is not set.",
                                  validators=[NotOptionalIf('year_out')])


class AddDegreeProgrammeForm(Form, DegreeProgrammeMixin):

    name = StringField('Name', validators=[InputRequired(message='Degree programme name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           globally_unique_degree_programme])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='Abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           globally_unique_programme_abbreviation])

    course_code = StringField('Course code', validators=[InputRequired(message='Course code is required'),
                                                         Length(max=DEFAULT_STRING_LENGTH),
                                                         globally_unique_course_code])

    submit = SubmitField('Add new degree programme')


class EditDegreeProgrammeForm(Form, DegreeProgrammeMixin, SaveChangesMixin):

    name = StringField('Name', validators=[InputRequired(message='Degree programme name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           unique_or_original_degree_programme])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='Abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           unique_or_original_programme_abbreviation])

    course_code = StringField('Course code', validators=[InputRequired(message='Course code is required'),
                                                         Length(max=DEFAULT_STRING_LENGTH),
                                                         unique_or_original_course_code])


class ModuleMixin():

    name = StringField('Module name', validators=[InputRequired(message='Module name is required'),
                                                  Length(max=DEFAULT_STRING_LENGTH)])

    level = QuerySelectField('Level', query_factory=GetFHEQLevels, get_label='name')

    semester = SelectField('Semester', choices=semester_choices, coerce=int)


class AddModuleForm(Form, ModuleMixin):

    code = StringField('Module code', validators=[InputRequired(message='Module code is required'),
                                                  Length(max=DEFAULT_STRING_LENGTH),
                                                  globally_unique_module_code])

    submit = SubmitField('Add new module')


class EditModuleForm(Form, ModuleMixin, SaveChangesMixin):

    code = StringField('Module code', validators=[InputRequired(message='Module code is required'),
                                                  Length(max=DEFAULT_STRING_LENGTH),
                                                  unique_or_original_module_code])


class TransferableSkillMixin():

    group = QuerySelectField('Skill group', query_factory=GetActiveSkillGroups, get_label='name')


class AddTransferableSkillForm(Form, TransferableSkillMixin):

    name = StringField('Skill', validators=[InputRequired(message='Name of transferable skill is required'),
                                            Length(max=DEFAULT_STRING_LENGTH),
                                            globally_unique_transferable_skill])

    submit = SubmitField('Add new transferable skill')


class EditTransferableSkillForm(Form, TransferableSkillMixin, SaveChangesMixin):

    name = StringField('Skill', validators=[InputRequired(message='Name of transferable skill is required'),
                                            Length(max=DEFAULT_STRING_LENGTH),
                                            unique_or_original_transferable_skill])


class ProjectClassMixin():

    colour = StringField('Colour', description='Assign a colour to help students identify this project class.',
                         validators=[Length(max=DEFAULT_STRING_LENGTH)])

    do_matching = BooleanField('Participate in automated global matching of faculty to projects',
                               default=True)

    number_assessors = IntegerField('Number of assessors required per project',
                                    description='Assessors are used to assign 2nd markers and presentation assessors. '
                                                'Significantly more than one assessor is required per project to allow '
                                                'sufficient flexibility during matching.',
                                    validators=[NotOptionalIf('do_matching')])

    use_project_hub = BooleanField('Use Project Hubs',
                                   description='The Project Hub is a lightweight learning management system that '
                                               'allows resources to be published to students, and provides a journal '
                                               'and to-do list. It is a central '
                                               'location to manage projects.')

    start_level = QuerySelectField('Starts in academic year',
                                   description='Select the academic year in which students join the project.',
                                   query_factory=GetFHEQLevels, get_label=BuildFHEQYearLabel)

    extent = SelectField('Duration', choices=extent_choices, coerce=int,
                         description='For how many academic years do students participate in the project?')

    require_confirm = BooleanField('Require faculty to confirm projects yearly', default=True)

    supervisor_carryover = BooleanField('For multi-year projects, automatically carry over supervisor year-to-year')

    include_available = BooleanField('Include this project class in supervisor availability calculations')

    uses_supervisor = BooleanField('Projects are supervised by a named faculty member',
                                   default=True)

    uses_marker = BooleanField('Submissions are second-marked')

    uses_presentations = BooleanField('Includes one or more assessed presentations')

    reenroll_supervisors_early = BooleanField('Re-enroll supervisors one year before end of sabbatical/buyout',
                                              default=True)

    initial_choices = IntegerField('Number of initial project preferences',
                                   description='Select number of preferences students should list before joining.')

    switch_choices = IntegerField('Number of subsequent project preferences',
                                  description='Number of preferences to allow in subsequent years, '
                                              'if switching is allowed.')

    faculty_maximum = IntegerField('Limit selections per faculty member',
                                   description='Optional. Specify a maximum number of projects that '
                                               'students can select if they are offered by the same '
                                               'faculty supervisor. Leave blank to disable.',
                                   validators=[Optional()])

    CATS_supervision = IntegerField('CATS awarded for project supervision',
                                    validators=[InputRequired(message='Please enter an integer value')])

    CATS_marking = IntegerField('CATS awarded for project 2nd marking',
                                validators=[Optional()])

    CATS_presentation = IntegerField('CATS awarded for assessing presentations',
                                     validators=[Optional()])

    hourly_choices = [(1, '1 day'),
                      (2, '2 days'),
                      (3, '3 days'),
                      (4, '4 days'),
                      (5, '5 days'),
                      (6, '6 days'),
                      (7, '7 days'),
                      (8, '8 days'),
                      (9, '9 days'),
                      (10, '10 days'),
                      (11, '11 days'),
                      (12, '12 days'),
                      (13, '13 days'),
                      (14, '14 days')]
    keep_hourly_popularity = SelectField('Keep hourly popularity data for', choices=hourly_choices, coerce=int)

    daily_choices = [(1, '1 week'),
                     (2, '2 weeks'),
                     (3, '3 weeks'),
                     (4, '4 weeks'),
                     (5, '5 weeks'),
                     (6, '6 weeks'),
                     (7, '7 weeks'),
                     (8, '8 weeks')]
    keep_daily_popularity = SelectField('Keep daily popularity data for', choices=daily_choices, coerce=int)

    convenor = QuerySelectField('Convenor', query_factory=GetPossibleConvenors, get_label=BuildConvenorRealName)

    coconvenors = QuerySelectMultipleField('Co-convenors', query_factory=GetPossibleConvenors,
                                           get_label=BuildConvenorRealName,
                                           description='Co-convenors have the same administrative privileges '
                                                       'as convenors, but are not identified to students. '
                                                       'For example, they might be previous convenors who are '
                                                       'helping with administration during a transition period.',
                                           validators=[Optional()])

    office_contacts = QuerySelectMultipleField('School Office contacts', query_factory=BuildPossibleOfficeContacts,
                                               get_label=BuildOfficeContactName,
                                               description='Specify one or more members of the office team '
                                                           'who act as contacts for this project type. Office contacts '
                                                           'receive email updates to keep them appraised of the '
                                                           'project lifecycle.',
                                               validators=[Optional()])

    selection_open_to_all = BooleanField('This is an opt-in project open to all eligible undergraduates',
                                         description='By default, selectors are auto-enrolled based on their degree programme '
                                                     'and participation is mandatory. '
                                                     'If this option is selected then all selectors from eligible years will be '
                                                     'auto-enrolled as selectors. If no project selection is made, the selector '
                                                     'is assumed not to have opted-in.')

    auto_enroll_years = RadioField('Auto enroll students as selectors in which years?',
                                   choices=auto_enroll_year_choices, coerce=int)

    programmes = QuerySelectMultipleField('Auto-enroll students from degree programmes',
                                          query_factory=GetActiveDegreeProgrammes,
                                          get_label=BuildDegreeProgrammeName)

    @staticmethod
    def validate_programmes(form, field):
        if form.selection_open_to_all.data:
            return

        if field.data is None or (isinstance(field.data, list) and len(field.data) == 0):
            raise ValidationError('At least one degree programme should be selected')


class AddProjectClassForm(Form, ProjectClassMixin):

    name = StringField('Name', validators=[InputRequired(message='Name of project class is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           globally_unique_project_class])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='An abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           globally_unique_project_class_abbrev])

    submit = SubmitField('Add new project class')


class EditProjectClassForm(Form, ProjectClassMixin, SaveChangesMixin):

    name = StringField('Name', validators=[InputRequired(message='Name of project class is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           unique_or_original_project_class])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='An abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           unique_or_original_project_class_abbrev])


class EditProjectTextForm(Form, SaveChangesMixin):

    card_text_normal = TextAreaField('Text seen by normal selectors', render_kw={"rows": 5},
                                     validators=[Optional()])

    card_text_optional = TextAreaField('Text seen by selectors for whom this project is optional',
                                       render_kw={"rows": 5}, validators=[Optional()])

    card_text_noninitial = TextAreaField('Text seen by selectors who may be changing supervisor',
                                         render_kw={"rows": 5}, validators=[Optional()])

    email_text_draft_match_preamble = TextAreaField('Preamble for notification of draft matching',
                                                    render_kw={"rows": 5}, validators=[Optional()])

    email_text_final_match_preamble = TextAreaField('Preamble for notification of final matching',
                                                    render_kw={"rows": 5}, validators=[Optional()])


class SubmissionPeriodSettingsMixin():

    name = StringField('Name', description='Optional. Enter an alternative text name for this submission '
                                           'period, such as "Autumn Term"',
                       validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)])

    start_date = DateField('Period start date', format='%d/%m/%Y', validators=[Optional()],
                           description='The year will increment when a rollover takes place')

    collect_project_feedback = BooleanField('Collect project feedback online')


class AddSubmissionPeriodForm(Form, SubmissionPeriodSettingsMixin, SubmissionPeriodPresentationsMixin):

    submit = SubmitField('Add new submission period')


class EditSubmissionPeriodForm(Form, SubmissionPeriodSettingsMixin, SubmissionPeriodPresentationsMixin, SaveChangesMixin):

    pass


class SupervisorMixin():

    colour = StringField('Colour', validators=[Length(max=DEFAULT_STRING_LENGTH)],
                         description='Assign a colour to help students identify the roles of team members')


class AddSupervisorForm(Form, SupervisorMixin):

    name = StringField('Name', validators=[InputRequired(message='Name of supervisory role is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           globally_unique_supervisor])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='An abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           globally_unique_supervisor_abbrev])
    submit = SubmitField('Add new supervisory role')


class EditSupervisorForm(Form, SupervisorMixin, SaveChangesMixin):

    name = StringField('Name', validators=[InputRequired(message='Name of supervisory role is required'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           unique_or_original_supervisor])

    abbreviation = StringField('Abbreviation', validators=[InputRequired(message='An abbreviation is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH),
                                                           unique_or_original_supervisor_abbrev])


class EmailLogForm(Form):

    weeks = IntegerField('Age cutoff in weeks', validators=[InputRequired(message='Cutoff is required. Emails older '
                                                                                 'than the limit will be removed.')])

    delete_age = SubmitField('Delete emails older than cutoff')


class BackupManageForm(Form):

    weeks = IntegerField('Age cutoff in weeks', validators=[InputRequired(message='Cutoff is required. Backups older '
                                                                                 'than the limit will be removed.')])

    delete_age = SubmitField('Delete backups older than cutoff')


def MessageMixinFactory(query_factory, convenor_editing):

    class MessageMixin():

        show_students = BooleanField('Display to students')

        show_faculty = BooleanField('Display to faculty')

        if not convenor_editing:
            show_login = BooleanField('Display on login screen if a broadcast message')

        dismissible = BooleanField('Allow message to be dismissed')

        title = StringField('Title', validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
                            description='Optional. Briefly summarize your message.')

        body = TextAreaField('Message', render_kw={"rows": 10},
                             validators=[InputRequired(message='You must enter a message, however short')])

        project_classes = QuerySelectMultipleField('Display to users enrolled for',
                                                   query_factory=query_factory, get_label='name')

    return MessageMixin


# we *must* implement this form using a factory function because we have to adjust its class members
def AddMessageFormFactory(convenor_editing=False):

    Mixin = MessageMixinFactory(GetConvenorProjectClasses if convenor_editing else GetAllProjectClasses,
                                convenor_editing=convenor_editing)

    class AddMessageForm(Form, Mixin):

        submit = SubmitField('Add new message')

        _validator = InputRequired(message='At least one project class should be selected') if convenor_editing \
            else Optional()

        @staticmethod
        def validate_project_classes(form, field):
            return form._validator(form, field)

    return AddMessageForm


def EditMessageFormFactory(convenor_editing=False):

    Mixin = MessageMixinFactory(GetConvenorProjectClasses if convenor_editing else GetAllProjectClasses,
                                convenor_editing=convenor_editing)

    class EditMessageForm(Form, Mixin, SaveChangesMixin):

        _validator = InputRequired(message='At least one project class should be selected') if convenor_editing \
            else Optional()

        @staticmethod
        def validate_project_classes(form, field):
            return form._validator(form, field)

    return EditMessageForm


class ScheduleTypeMixin():

    available_types = [('interval', 'Fixed interval'), ('crontab', 'Crontab')]
    type = SelectField('Type of schedule', choices=available_types)


class ScheduleTypeForm(Form, ScheduleTypeMixin):

    submit = SubmitField('Select type')


class ScheduledTaskMixin():

    name = StringField('Name', validators=[InputRequired(message='A task name is required'),
                                           Length(max=DEFAULT_STRING_LENGTH)])

    owner = QuerySelectField('Owner', query_factory=GetSysadminUsers, get_label=BuildSysadminUserName)

    tasks_available = [('app.tasks.prune_email.prune_email_log', 'Prune email log'),
                       ('app.tasks.backup.backup', 'Perform local backup'),
                       ('app.tasks.backup.thin', 'Thin local backups'),
                       ('app.tasks.backup.limit_size', 'Enforce limit on size of backup folder'),
                       ('app.tasks.backup.clean_up', 'Clean up backup folder'),
                       ('app.tasks.backup.drop_absent_backups', 'Drop absent backups'),
                       ('app.tasks.popularity.update_popularity_data', 'Update LiveProject popularity data'),
                       ('app.tasks.popularity.thin', 'Thin LiveProject popularity data'),
                       ('app.tasks.maintenance.maintenance', 'Perform regular database maintenance'),
                       ('app.tasks.maintenance.asset_garbage_collection', 'Garbage collection for temporary assets'),
                       ('app.tasks.email_notifications.send_daily_notifications', 'Send daily email notifications'),
                       ('app.tasks.batch_create.garbage_collection', 'Garbage collection for batch student import'),
                       ('app.tasks.system.process_pings', 'Process pings from front end instances'),
                       ('app.tasks.sessions.sift_sessions', 'Perform MongoDB session maintenance')]

    task = SelectField('Task', choices=tasks_available)

    queues_available = [('default', 'Default (for ordinary or long-running tasks)'),
                        ('priority', 'High-priority')]

    queue = SelectField('Queue', choices=queues_available)

    arguments = StringField('Arguments', validators=[valid_json, Length(max=DEFAULT_STRING_LENGTH)],
                            description='Format as a JSON list.')

    keyword_arguments = StringField('Keyword arguments', validators=[valid_json, Length(max=DEFAULT_STRING_LENGTH)],
                                    description='Format as a JSON dictionary.')

    expires = DateTimeField('Expires at', validators=[Optional()],
                            description='Optional. Format YYYY-mm-dd HH:MM:SS. Leave blank for no expiry.')


class IntervalMixin():

    every = IntegerField('Run every', validators=[InputRequired(message='You must enter a nonzero interval')])

    available_periods = [('seconds', 'seconds'), ('minutes', 'minutes'), ('hours', 'hours'), ('days', 'days'), ('weeks', 'weeks')]
    period = SelectField('Period', choices=available_periods)


class CrontabMixin():

    minute = StringField('Minute pattern', validators=[InputRequired(message='You must enter a pattern'),
                                                       Length(max=DEFAULT_STRING_LENGTH)])

    hour = StringField('Hour pattern', validators=[InputRequired(message='You must enter a pattern'),
                                                   Length(max=DEFAULT_STRING_LENGTH)])

    day_of_week = StringField('Day-of-week pattern', validators=[InputRequired(message='You must enter a pattern'),
                                                                 Length(max=DEFAULT_STRING_LENGTH)])

    day_of_month = StringField('Day-of-month pattern', validators=[InputRequired(message='You must enter a pattern'),
                                                                   Length(max=DEFAULT_STRING_LENGTH)])

    month_of_year = StringField('Month-of-year pattern', validators=[InputRequired(message='You must enter a pattern'),
                                                                     Length(max=DEFAULT_STRING_LENGTH)])


class AddIntervalScheduledTask(Form, ScheduledTaskMixin, IntervalMixin):

    submit = SubmitField('Add new task')


class EditIntervalScheduledTask(Form, ScheduledTaskMixin, IntervalMixin, SaveChangesMixin):

    pass


class AddCrontabScheduledTask(Form, ScheduledTaskMixin, CrontabMixin):

    submit = SubmitField('Add new task')


class EditCrontabScheduledTask(Form, ScheduledTaskMixin, CrontabMixin, SaveChangesMixin):

    pass


class BackupOptionsMixin():

    hourly_choices = [(1, '1 day'),
                      (2, '2 days'),
                      (3, '3 days'),
                      (4, '4 days'),
                      (5, '5 days'),
                      (6, '6 days'),
                      (7, '7 days'),
                      (8, '8 days'),
                      (9, '9 days'),
                      (10, '10 days'),
                      (11, '11 days'),
                      (12, '12 days'),
                      (13, '13 days'),
                      (14, '14 days')]
    keep_hourly = SelectField('Keep hourly backups for', choices=hourly_choices, coerce=int)

    daily_choices = [(1, '1 week'),
                     (2, '2 weeks'),
                     (3, '3 weeks'),
                     (4, '4 weeks'),
                     (5, '5 weeks'),
                     (6, '6 weeks'),
                     (7, '7 weeks'),
                     (8, '8 weeks')]
    keep_daily = SelectField('Keep daily backups for', choices=daily_choices, coerce=int,
                             description='Daily backups are kept when hourly backups are no longer being retained. '
                                         'Use this field to determine for how long daily backups are stored. '
                                         'After this time backups are retained only weekly.')

    # field names for limits are blank; to get formatting right they're included directly on the template
    backup_limit = FloatField('Limit total size of backups', validators=[Optional()],
                              description='Leave blank for no limit.')

    units_choices = [(BackupConfiguration.KEY_MB, 'Mb'),
                     (BackupConfiguration.KEY_GB, 'Gb'),
                     (BackupConfiguration.KEY_TB, 'Tb')]
    limit_units = SelectField('Units', choices=units_choices, coerce=int)


class EditBackupOptionsForm(Form, BackupOptionsMixin):

    submit = SubmitField('Save changes')


class SkillGroupMixin():

    colour = StringField('Colour', validators=[Length(max=DEFAULT_STRING_LENGTH)],
                         description='Assign a colour to help students identify skills belonging to this group')

    add_group = BooleanField('Add group name to skill labels',
                             description='Select if you wish skills in this group to be labelled as <group name>: <skill name>')


class AddSkillGroupForm(Form, SkillGroupMixin):

    name = StringField('Name', validators=[InputRequired(message='Please supply a unique name for the group'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           globally_unique_skill_group])

    submit = SubmitField('Add new skill')


class EditSkillGroupForm(Form, SkillGroupMixin, SaveChangesMixin):

    name = StringField('Name', validators=[InputRequired(message='Please supply a unique name for the group'),
                                           Length(max=DEFAULT_STRING_LENGTH),
                                           unique_or_original_skill_group])


class PuLPSolverMixin():

    solver = SelectField('Solver', choices=solver_choices, coerce=int,
                         description='The optimizer can use a number of different solvers. If in doubt, use the '
                                     'packaged CBC solver. Alternatively, download a version of the optimization '
                                     'problem as a .LP or .MPS file and perform the optimization offline.')


def MatchingMixinFactory(pclasses_query, include_matches_query, base_match):

    class MatchingMixin():

        name = StringField('Name',
                           description='Enter a short tag to identify this match',
                           validators=[InputRequired(message='Please supply a unique name'),
                                       Length(max=DEFAULT_STRING_LENGTH)])

        pclasses_to_include = QuerySelectMultipleField('Select project classes to include in this match',
                                                       query_factory=pclasses_query, get_label='name')

        if base_match is None or base_match.include_only_submitted is True:
            include_only_submitted = BooleanField('Include only selectors who submitted preferences')

        ignore_per_faculty_limits = BooleanField('Ignore CATS limits specified in faculty accounts')

        ignore_programme_prefs = BooleanField('Ignore degree programme preferences')

        years_memory = SelectField('Include how many years history when levelling workloads?',
                                   choices=matching_history_choices, coerce=int)

        supervising_limit = IntegerField('CATS limit for supervising',
                                         validators=[InputRequired(message='Please specify the maximum number of CATS '
                                                                          'that can be allocated per faculty')])

        marking_limit = IntegerField('CATS limit for marking',
                                     validators=[InputRequired(message='Please specify the maximum number of CATS '
                                                                       'that can be allocated per faculty')])

        max_marking_multiplicity = IntegerField('Maximum multiplicity for 2nd markers',
                                                description='2nd markers may be assigned multiple instances of the same '
                                                            'project, up to the maximum multiplicity specified',
                                                validators=[InputRequired(message='Please specify a multiplicity')])

        include_matches = QuerySelectMultipleField('When levelling workloads, include CATS from existing matches',
                                                   query_factory=include_matches_query, get_label='name')

        if base_match is not None:
            base_bias = FloatField('Bias to base match', default=10.0,
                                   description='Choose large values to bias the fit towards the base match. '
                                               'Smaller values allow the optimizer to modify the base match to '
                                               'improve the fit in other ways, such as levelling workloads or '
                                               'including the preferences of selectors who did not appear in '
                                               'the base.',
                                   validators=[InputRequired(message='Please specify a base bias')])

            force_base = BooleanField('Force agreement with assignments in "{name}"'.format(name=base_match.name))

        levelling_bias = FloatField('Workload levelling bias', default=1.0,
                                    description='This sets the normalization of the workload levelling tension in '
                                                'the objective function. This term tensions good student matches against '
                                                'roughly equal workload for all faculty members who supervise, '
                                                'perform marking, or both. Set to 0 to turn off workload levelling. '
                                                'Set to values less than 1 to '
                                                'prioritize matching to high-ranked projects rather than equal workloads. '
                                                'Set to large values to prioritize equal workloads rather than '
                                                'student matches to high-ranked projects.',
                                    validators=[InputRequired(message='Please specify a levelling bias')])

        intra_group_tension = FloatField('Intra-group tension', default=2.0,
                                         description='This sets the tension with which the typical workload for '
                                                     'each faculty group (supervisors, markers, and those who do both) '
                                                     'are held together. Set to large values to keep workloads '
                                                     'as closely matched as possible.',
                                         validators=[InputRequired(message='Please specify an intra-group tension')])

        supervising_pressure = FloatField('Supervising downward pressure', default=1.0,
                                          description='Sets the pressure to apply to the maximum supervisory '
                                                      'allocation for any individual faculty member.',
                                          validators=[InputRequired(message='Please specify a supervising pressure')])

        marking_pressure = FloatField('Marking downward pressure', default=1.0,
                                      description='Sets the pressure to apply to the maximum marking allocation for '
                                                  'any individual faculty member.',
                                      validators=[InputRequired(message='Please specify a marking pressure')])

        CATS_violation_penalty = FloatField('CATS limit violation penalty', default=5.0,
                                            description='Determines the penalty imposed for violating CATS limits.',
                                            validators=[InputRequired(message='Please specify a penalty')])

        no_assignment_penalty = FloatField('No assignment penalty', default=5.0,
                                           description='Determines the penalty imposed for leaving supervisory '
                                                       'faculty without a project assignment.',
                                           validators=[InputRequired(message='Please specify a penalty')])

        programme_bias = FloatField('Degree programme preference bias', default=1.5,
                                    description='Values greater than 1 bias the optimization to match students '
                                                'on given degree programmes with projects that '
                                                'are marked as preferring that programme. '
                                                'A value of 1 disables this preference.',
                                    validators=[InputRequired(message='Please specify a programme preference bias')])

        bookmark_bias = FloatField('Penalty for using bookmarks', default=0.333,
                                   description='Values less than 1 penalize preferences taken from bookmark data '
                                               'rather than a verified submission. Set to 1 if you do not wish '
                                               'to distinguish these cases.',
                                   validators=[InputRequired(message='Please specify a bookmark bias')])

        use_hints = BooleanField('Use convenor hints')

        encourage_bias = FloatField('Bias for convenor "encouraged" hint', default=2.0,
                                    validators=[InputRequired(message='Please specify a bias')])

        discourage_bias = FloatField('Bias for convenor "discouraged" hint', default=0.5,
                                     validators=[InputRequired(message='Please specify a bias')])

        strong_encourage_bias = FloatField('Bias for convenor "strongly encouraged" hint', default=5.0,
                                           validators=[InputRequired(message='Please specify a bias')])

        strong_discourage_bias = FloatField('Bias for convenor "strongly discouraged" hint', default=0.2,
                                            validators=[InputRequired(message='Please specify a bias')])

    return MatchingMixin


def NewMatchFormFactory(year, base_id=None, base_match=None):

    Mixin = MatchingMixinFactory(partial(GetAutomatedMatchPClasses, year, base_id),
                                 partial(GetMatchingAttempts, year, base_id),
                                 base_match=base_match)

    class NewMatchForm(Form, Mixin, PuLPSolverMixin):

        submit = SubmitField('Create new match')

        offline = SubmitField('Perform matching offline')

        @staticmethod
        def validate_name(form, field):
            return globally_unique_matching_name(year, form, field)

    return NewMatchForm


class UploadMatchForm(Form):

    solver = SelectField('Solver', choices=solver_choices, coerce=int,
                         description='Select the solver used to produce the solution file you are uploading.')

    submit = SubmitField('Upload solution')


def RenameMatchFormFactory(year):

    class RenameMatchForm(Form):

        name = StringField('New name', description='Enter a short tag to identify this match',
                           validators=[InputRequired(message='Please supply a unique name'),
                                       Length(max=DEFAULT_STRING_LENGTH)])

        submit = SubmitField('Rename match')

        @staticmethod
        def validate_name(form, field):
            return unique_or_original_matching_name(year, form, field)

    return RenameMatchForm


def CompareMatchFormFactory(year, self_id, pclasses, is_root):

    class CompareMatchForm(Form):

        target = QuerySelectField('Compare to',
                                  query_factory=partial(GetComparatorMatches, year, self_id, pclasses, is_root),
                                  get_label='name')

        compare = SubmitField('Compare')

    return CompareMatchForm


def PresentationAssessmentMixinFactory(query_factory):

    class PresentationAssessmentMixin():

        name = StringField('Name', description='Enter a short name to identify this assessment event',
                           validators=[InputRequired(message='Please supply a unique name'),
                                       Length(max=DEFAULT_STRING_LENGTH)])

        submission_periods = QuerySelectMultipleField('Select those submission periods for which project '
                                                      'presentations will be given',
                                                      query_factory=query_factory, get_label=BuildSubmissionPeriodName)

    return PresentationAssessmentMixin


def AddPresentationAssessmentFormFactory(year):

    Mixin = PresentationAssessmentMixinFactory(partial(GetUnattachedSubmissionPeriods, None))

    class AddPresentationAssessmentForm(Form, Mixin):

        submit = SubmitField('Add new assessment')

        @staticmethod
        def validate_name(form, field):
            return globally_unique_assessment_name(year, form, field)

    return AddPresentationAssessmentForm


def EditPresentationAssessmentFormFactory(year, assessment_id):

    Mixin = PresentationAssessmentMixinFactory(partial(GetUnattachedSubmissionPeriods, assessment_id))

    class EditPresentationAssessmentForm(Form, Mixin, SaveChangesMixin):

        @staticmethod
        def validate_name(form, field):
            return unique_or_original_assessment_name(year, form, field)

    return EditPresentationAssessmentForm


class SessionMixin():

    date = DateField('Date', format='%d/%m/%Y', validators=[InputRequired()],
                     description='Specify the date for this session')

    session_type = SelectField('Session type', choices=session_choices, coerce=int)

    rooms = QuerySelectMultipleField('Select the rooms that are available for this session',
                                     query_factory=GetAllRooms, get_label=BuildRoomLabel)


class AddSessionForm(Form, SessionMixin):

    submit = SubmitField('Add session')


class EditSessionForm(Form, SessionMixin, SaveChangesMixin):

    pass


class BuildingMixin():

    name = StringField('Name', description='Enter a short name or identifier for the building',
                       validators=[InputRequired('A unique name is required'),
                                   Length(max=DEFAULT_STRING_LENGTH)])

    colour = StringField('Colour', validators=[Length(max=DEFAULT_STRING_LENGTH)],
                         description='Specify a colour to help identify rooms located in this building')


class AddBuildingForm(Form, BuildingMixin):

    submit = SubmitField('Add building')

    @staticmethod
    def validate_name(form, field):
        return globally_unique_building_name(form, field)


class EditBuildingForm(Form, BuildingMixin, SaveChangesMixin):

    @staticmethod
    def validate_name(form, field):
        return unique_or_original_building_name(form, field)


class RoomMixin():

    name = StringField('Name', description='Enter a number or label for the venue',
                       validators=[InputRequired('A unique name is required'),
                                   Length(max=DEFAULT_STRING_LENGTH)])

    building = QuerySelectField('Building', query_factory=GetAllBuildings, get_label='name')

    capacity = IntegerField('Capacity', description='How many people will this room accommodate?',
                            validators=[InputRequired('Enter the number of people who can be accommodated')])

    lecture_capture = BooleanField('Lecture capture available')


class AddRoomForm(Form, RoomMixin):

    submit = SubmitField('Add room')

    @staticmethod
    def validate_name(form, field):
        return globally_unique_room_name(form, field)


class EditRoomForm(Form, RoomMixin, SaveChangesMixin):

    @staticmethod
    def validate_name(form, field):
        return unique_or_original_room_name(form, field)


class AssetLicenseMixin():

    name = StringField('Name',
                       description='Enter a name to identify this license',
                       validators=[InputRequired(message='Please supply a unique name'),
                                   Length(max=DEFAULT_STRING_LENGTH)])

    colour = StringField('Colour', validators=[Length(max=DEFAULT_STRING_LENGTH)],
                         description='Assign a colour to identify assets tagged with this license')

    abbreviation = StringField('Abbreviation',
                               description='Enter a short name used to visually tag content provided '
                                           'under this license',
                               validators=[InputRequired(message='Please supply a unique abbreviation'),
                                           Length(max=DEFAULT_STRING_LENGTH)])

    description = TextAreaField('Description', render_kw={"rows": 5},
                                validators=[InputRequired(message='Please supply a brief description of the '
                                                                  'license conditions')])

    version = StringField('Version',
                          description='Please enter a version number or identifier '
                                      'for this license',
                          validators=[InputRequired(message='Please supply a valid version string'),
                                      Length(max=DEFAULT_STRING_LENGTH)])

    url = StringField('Web address',
                      description='Optional. Enter a web address for this license.')

    allows_redistribution = BooleanField('License allows content to be redistributed')


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


    submit = SubmitField('Add new license')


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


class AvailabilityForm(Form):

    # deadline for response
    availability_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[InputRequired()])

    # submit button: open feedback
    issue_requests = SubmitField('Issue availability requests')


class ScheduleNameMixin():

    name = StringField('Name',
                       description='Enter a short name to identify this schedule',
                       validators=[InputRequired(message='Please supply a unique name'),
                                   Length(max=DEFAULT_STRING_LENGTH)])

    tag = StringField('Tag',
                      description='Enter a unique tag (containing no white space) for use as part of a URL',
                      validators=[InputRequired(message='Please supply a unique tag'),
                                  Length(max=DEFAULT_STRING_LENGTH)])


def ScheduleNameCreateValidatorFactory(assessment):

    class Validator():

        @staticmethod
        def validate_name(form, field):
            return globally_unique_schedule_name(assessment.id, form, field)

        @staticmethod
        def validate_tag(form, field):
            isvalid = re.match(r'[\w-]*$', field.data)
            if not isvalid:
                raise ValidationError('The tag should contain only letters, numbers, underscores or dashes, '
                                      'and be valid as part of a URL')

            return globally_unique_schedule_tag(form, field)

    return Validator


def ScheduleNameRenameValidatorFactory(assessment):

    class Validator():

        @staticmethod
        def validate_name(form, field):
            return unique_or_original_schedule_name(assessment.id, form, field)

        @staticmethod
        def validate_tag(form, field):
            isvalid = re.match(r'[\w-]*$', field.data)
            if not isvalid:
                raise ValidationError('The tag should contain only letters, numbers, underscores or dashes, '
                                      'and be valid as part of a URL')

            return unique_or_original_schedule_tag(form, field)

    return Validator


class ScheduleSettingsMixin():

    assessor_assigned_limit = IntegerField('Maximum number of assignments per assessor', default=3,
                                           description='Enter the maximum number of times each assessor can be '
                                                       'scheduled.',
                                           validators=[InputRequired('Please enter a positive integer')])

    if_needed_cost = FloatField('Cost for using faculty tagged as <i>if needed</i>', default=1.5,
                                description='Normalized relative to the cost for using a new slot.',
                                validators=[InputRequired('Please enter a suitable positive decimal.')])

    levelling_tension = FloatField('Tension used to level workloads', default=1.5,
                                   description='Cost of introducing a workload inequality of one session, '
                                               'normalized to the cost of using a new slot.',
                                   validators=[InputRequired('Please enter a suitable positive decimal.')])

    all_assessors_in_pool = RadioField('Assessor configuration', choices=ScheduleAttempt.assessor_choices, coerce=int)


def NewScheduleFormFactory(assessment):

    validator = ScheduleNameCreateValidatorFactory(assessment)

    class NewScheduleForm(Form, ScheduleNameMixin, validator, ScheduleSettingsMixin, PuLPSolverMixin):

        submit = SubmitField('Create new schedule')

        offline = SubmitField('Perform scheduling offline')

    return NewScheduleForm


class UploadScheduleForm(Form):

    solver = SelectField('Solver', choices=solver_choices, coerce=int,
                         description='Select the solver used to produce the solution file you are uploading.')

    submit = SubmitField('Upload solution')


def RenameScheduleFormFactory(assessment):

    validator = ScheduleNameRenameValidatorFactory(assessment)

    class RenameScheduleForm(Form, ScheduleNameMixin, validator):

        submit = SubmitField('Rename schedule')

    return RenameScheduleForm


def ImposeConstraintsScheduleFormFactory(assessment):

    validator = ScheduleNameCreateValidatorFactory(assessment)

    class ImposeConstraintsScheduleForm(Form, ScheduleNameMixin, validator):

        allow_new_slots = BooleanField('Allow new slots to be created', default=False)

        submit = SubmitField('Perform adjustment')

    return ImposeConstraintsScheduleForm


class AssignmentLimitForm(Form, SaveChangesMixin):

    assigned_limit = IntegerField('Maximum number of sessions to assign to this assessor',
                                  validators=[Optional()])


class LevelSelectorMixin():

    selector = QuerySelectField('Select courses from FHEQ level', query_factory=GetFHEQLevels, get_label='name')


class LevelSelectorForm(Form, LevelSelectorMixin):

    pass


class FHEQLevelMixin():

    colour = StringField('Colour', validators=[Length(max=DEFAULT_STRING_LENGTH)],
                         description='Assign a colour to help distinguish modules belonging to this level')


class AddFHEQLevelForm(Form, FHEQLevelMixin):

    name = StringField('Name', description='Provide a name for this level',
                       validators=[InputRequired(message='Please specify a name for this level'),
                                   Length(max=DEFAULT_STRING_LENGTH),
                                   globally_unique_FHEQ_level_name])

    short_name = StringField('Short name', description='A shortened name is used to save space on some displays',
                             validators=[InputRequired(message='Please specify a short name for this level'),
                                         Length(max=DEFAULT_STRING_LENGTH),
                                         globally_unique_FHEQ_short_name])

    academic_year = IntegerField('Academic year', validators=[InputRequired(message='Please specify a year'),
                                                              globally_unique_FHEQ_year])

    submit = SubmitField('Create new level')


class EditFHEQLevelForm(Form, FHEQLevelMixin, SaveChangesMixin):

    name = StringField('Name', description='Provide a name for this level',
                       validators=[InputRequired(message='Please specify a name for this level'),
                                   Length(max=DEFAULT_STRING_LENGTH),
                                   unique_or_original_FHEQ_level_name])

    short_name = StringField('Short name', description='A shortened name is used to save space on some displays',
                             validators=[InputRequired(message='Please specify a short name for this level'),
                                         Length(max=DEFAULT_STRING_LENGTH),
                                         unique_or_original_FHEQ_short_name])

    academic_year = IntegerField('Academic year', validators=[InputRequired(message='Please specify a year'),
                                                              unique_or_original_FHEQ_year])


def PublicScheduleFormFactory(schedule):

    class PublicScheduleForm(Form):

        selector = QuerySelectField('Select the session you wish to view:',
                                    query_factory=partial(ScheduleSessionQuery, schedule.id),
                                    get_label=BuildScheduleSessionLabel)

    return PublicScheduleForm


def CompareScheduleFormFactory(assessment_id, self_id, is_root):

    class CompareScheduleForm(Form):

        target = QuerySelectField('Compare to',
                                  query_factory=partial(GetComparatorSchedules, assessment_id, self_id, is_root),
                                  get_label='name')

        compare = SubmitField('Compare')

    return CompareScheduleForm
