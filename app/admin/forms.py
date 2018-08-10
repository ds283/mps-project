#
# Created by David Seery on 10/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import request
from flask_security.forms import Form, RegisterFormMixin, UniqueEmailFormMixin, NextFormMixin, get_form_field_label
from flask_security.forms import password_length, email_required, email_validator, EqualTo
from wtforms import StringField, IntegerField, SelectField, PasswordField, BooleanField, SubmitField, \
    TextAreaField, DateTimeField, FloatField, RadioField
from wtforms.validators import DataRequired, Optional
from wtforms_alchemy.fields import QuerySelectField, QuerySelectMultipleField

from ..shared.forms.wtf_validators import valid_username, globally_unique_username, unique_or_original_username, \
    unique_or_original_email, globally_unique_group_abbreviation, unique_or_original_abbreviation, \
    globally_unique_degree_type, unique_or_original_degree_type, globally_unique_degree_programme, \
    unique_or_original_degree_programme, globally_unique_transferable_skill, unique_or_original_transferable_skill, \
    globally_unique_skill_group, unique_or_original_skill_group, globally_unique_project_class, \
    unique_or_original_project_class, globally_unique_project_class_abbrev, unique_or_original_project_class_abbrev, \
    globally_unique_supervisor, unique_or_original_supervisor, globally_unique_role, unique_or_original_role, \
    valid_json, password_strength, OptionalIf, NotOptionalIf
from ..shared.forms.queries import GetActiveDegreeTypes, GetActiveDegreeProgrammes, GetActiveSkillGroups, \
    BuildDegreeProgrammeName, GetPossibleConvenors, BuildUserRealName, BuildConvenorRealName, GetAllProjectClasses, \
    GetConvenorProjectClasses, GetSysadminUsers
from ..models import BackupConfiguration, EnrollmentRecord, submission_choices, academic_titles, \
    extent_choices, year_choices

from ..shared.forms.fields import EditFormMixin, CheckboxQuerySelectMultipleField


class UniqueUserNameMixin():

    username = StringField('Username', validators=[DataRequired(message='Username is required'),
                                                   valid_username, globally_unique_username])


class EditUserNameMixin():

    username = StringField('Username', validators=[DataRequired(message='Username is required'),
                                                   valid_username, unique_or_original_username])


class EditEmailFormMixin():

    email = StringField(
        get_form_field_label('email'),
        validators=[email_required, email_validator, unique_or_original_email])


class AskConfirmAddFormMixin():

    ask_confirm = BooleanField('Send confirmation email')


class AskConfirmEditFormMixin():

    ask_confirm = BooleanField('Resend confirmation email if address is changed')


# redefine NewPasswordFormMixin from flask-security to check password strength
class NewPasswordFormMixin():

    random_password = BooleanField('Generate random password')

    password = PasswordField(
        get_form_field_label('password'),
        validators=[OptionalIf('random_password'), password_length, password_strength])


class PasswordConfirmFormMixin():

    password_confirm = PasswordField(
        get_form_field_label('retype_password'),
        validators=[OptionalIf('random_password'), EqualTo('password', message='RETYPE_PASSWORD_MISMATCH')])


class RoleMixin():

    available_roles = [('faculty', 'Faculty'), ('student', 'Student'), ('office', 'Office')]
    roles = SelectField('Role', choices=available_roles)


class RoleSelectForm(Form, RoleMixin):

    submit = SubmitField('Select role')


class FirstLastNameMixin():

    first_name = StringField('First name', validators=[DataRequired(message='First name is required')])
    last_name = StringField('Last or family name', validators=[DataRequired(message='Last name is required')])


class FacultyDataMixin():

    academic_title = SelectField('Academic title', choices=academic_titles, coerce=int)

    use_academic_title = BooleanField('Use academic title', default=True,
                                      description='Prefix your name with Dr, Professor or similar in student-facing web pages.')

    sign_off_students = BooleanField('Ask to confirm student meetings', default=True,
                                     description='If meetings are required before project selection, '
                                                 'confirmation is needed before allowing students to sign up.')

    enforce_capacity = BooleanField('Enforce maximum capacity', default=True,
                                    description='By default, enforce limits on project capacity during assignment')

    project_capacity = IntegerField('Default project capacity',
                                    description='Default number of students that can be assigned to a project',
                                    validators=[NotOptionalIf(enforce_capacity)])

    show_popularity = BooleanField('Show popularity indicators', default=True,
                                   description='By default, show popularity indicators on project webpages')

    CATS_supervision = IntegerField('Guideline number of CATS available for project supervision',
                                    description='Leave blank for default assignment',
                                    validators=[Optional()])

    CATS_marking = IntegerField('Guidline number of CATS available for marking',
                                description='Leave blank for default assignment',
                                validators=[Optional()])

    office = StringField('Office', validators=[DataRequired(message='Please enter your office details to help '
                                                                    'students find you')])


class StudentDataMixin():

    exam_number = IntegerField('Exam number', validators=[DataRequired(message="Exam number is required")])

    cohort = IntegerField('Cohort', validators=[DataRequired(message="Cohort is required")])

    programme = QuerySelectField('Degree programme', query_factory=GetActiveDegreeProgrammes,
                                 get_label=BuildDegreeProgrammeName)


class RegisterOfficeForm(Form, RegisterFormMixin, UniqueUserNameMixin, AskConfirmAddFormMixin,
                         UniqueEmailFormMixin, NewPasswordFormMixin, FirstLastNameMixin):

    pass


class ConfirmRegisterOfficeForm(RegisterOfficeForm, PasswordConfirmFormMixin, NextFormMixin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.next.data:
            self.next.data = request.args.get('next', '')


class RegisterFacultyForm(RegisterOfficeForm, FacultyDataMixin):

    pass


class ConfirmRegisterFacultyForm(ConfirmRegisterOfficeForm, FacultyDataMixin):

    pass


class RegisterStudentForm(RegisterOfficeForm, StudentDataMixin):

    pass


class ConfirmRegisterStudentForm(ConfirmRegisterOfficeForm, StudentDataMixin):

    pass


class EditOfficeForm(Form, EditFormMixin, EditUserNameMixin, AskConfirmEditFormMixin, EditEmailFormMixin, FirstLastNameMixin):

    pass


class EditFacultyForm(EditOfficeForm, FacultyDataMixin):

    pass


class EditStudentForm(EditOfficeForm, StudentDataMixin):

    pass


class FacultySettingsForm(Form, EditUserNameMixin, FacultyDataMixin, FirstLastNameMixin, EditFormMixin):

    pass


class ResearchGroupForm():

    name = StringField('Name', validators=[DataRequired(message='Name is required')])

    website = StringField('Website', description='Optional.')

    colour = StringField('Colour', description='Assign a colour to help students identify this research group.')


class AddResearchGroupForm(Form, ResearchGroupForm):

    abbreviation = StringField('Abbreviation', validators=[DataRequired(message='Abbreviation is required'),
                                                           globally_unique_group_abbreviation])

    submit = SubmitField('Add new group')


class EditResearchGroupForm(Form, ResearchGroupForm, EditFormMixin):

    abbreviation = StringField('Abbreviation', validators=[DataRequired(message='Abbreviation is required'),
                                                           unique_or_original_abbreviation])
    name = StringField('Name', validators=[DataRequired(message='Name is required')])


class AddDegreeTypeForm(Form):

    name = StringField('Name', validators=[DataRequired(message='Degree type name is required'),
                                           globally_unique_degree_type])

    submit = SubmitField('Add new degree type')


class EditDegreeTypeForm(Form, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='Degree type name is required'),
                                           unique_or_original_degree_type])


class AddDegreeProgrammeForm(Form):

    degree_type = QuerySelectField('Degree type', query_factory=GetActiveDegreeTypes, get_label='name')
    name = StringField('Name', validators=[DataRequired(message='Degree programme name is required'),
                                           globally_unique_degree_programme])

    submit = SubmitField('Add new degree programme')


class EditDegreeProgrammeForm(Form, EditFormMixin):

    degree_type = QuerySelectField('Degree type', query_factory=GetActiveDegreeTypes, get_label='name')
    name = StringField('Name', validators=[DataRequired(message='Degree programme name is required'),
                                           unique_or_original_degree_programme])


class TransferableSkillMixin():

    group = QuerySelectField('Skill group', query_factory=GetActiveSkillGroups, get_label='name')


class AddTransferableSkillForm(Form, TransferableSkillMixin):

    name = StringField('Skill', validators=[DataRequired(message='Name of transferable skill is required'),
                                            globally_unique_transferable_skill])

    submit = SubmitField('Add new transferable skill')


class EditTransferableSkillForm(Form, TransferableSkillMixin, EditFormMixin):

    name = StringField('Skill', validators=[DataRequired(message='Name of transferable skill is required'),
                                            unique_or_original_transferable_skill])


class ProjectClassMixin():

    colour = StringField('Colour', description='Assign a colour to help students identify this project class.')

    do_matching = BooleanField('Participate in automated global matching of faculty to projects')

    number_markers = IntegerField('Number of 2nd markers required per project',
                                  description='More than one 2nd marker is required per project to allow sufficient '
                                              'flexibility during matching.',
                                  validators=[NotOptionalIf(do_matching)])

    year = SelectField('Runs in year', choices=year_choices, coerce=int,
                       description='Select the academic year in which students join the project.')

    extent = SelectField('Duration', choices=extent_choices, coerce=int,
                         description='For how many academic years do students participate in the project?')

    require_confirm = BooleanField('Require faculty to confirm projects yearly')

    supervisor_carryover = BooleanField('For multi-year projects, automatically carry over supervisor year-to-year')

    submissions = SelectField('Submissions per year', choices=submission_choices, coerce=int,
                              description='Select number of marked reports submitted per academic year.')

    initial_choices = IntegerField('Number of initial project preferences',
                                   description='Select number of preferences students should list before joining.')

    switch_choices = IntegerField('Number of subsequent project preferences',
                                  description='Number of preferences to allow in subsequent years, '
                                              'if switching is allowed.')

    CATS_supervision = IntegerField('CATS awarded for project supervision',
                                    validators=[DataRequired(message='Please enter an integer value')])

    CATS_marking = IntegerField('CATS awarded for project 2nd marking',
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
                                                       'assisting with administration.',
                                           validators=[Optional()])

    selection_open_to_all = BooleanField('Project selection is open to undergraduates from all programmes',
                                         description='Not normally required, but use for Research Placement projects')

    programmes = CheckboxQuerySelectMultipleField('Auto-enroll students from degree programmes',
                                                  query_factory=GetActiveDegreeProgrammes,
                                                  get_label=BuildDegreeProgrammeName,
                                                  validators=[DataRequired(
                                                      message='At least one degree programme should be selected')])


class AddProjectClassForm(Form, ProjectClassMixin):

    name = StringField('Name', validators=[DataRequired(message='Name of project class is required'),
                                           globally_unique_project_class])
    abbreviation = StringField('Abbreviation', validators=[DataRequired(message='An abbreviation is required'),
                                                           globally_unique_project_class_abbrev])

    submit = SubmitField('Add new project class')


class EditProjectClassForm(Form, ProjectClassMixin, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='Name of project class is required'),
                                           unique_or_original_project_class])
    abbreviation = StringField('Abbreviation', validators=[DataRequired(message='An abbreviation is required'),
                                                           unique_or_original_project_class_abbrev])


class AddSupervisorForm(Form):

    name = StringField('Name', validators=[DataRequired(message='Name of supervisory role is required'),
                                           globally_unique_supervisor])

    submit = SubmitField('Add new supervisory role')


class EditSupervisorForm(Form, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='Name of supervisory role is required'),
                                           unique_or_original_supervisor])


class EmailLogForm(Form):

    weeks = IntegerField('Age cutoff in weeks', validators=[DataRequired(message='Cutoff is required. Emails older '
                                                                                 'than the limit will be removed.')])

    delete_age = SubmitField('Delete emails older than cutoff')


class BackupManageForm(Form):

    weeks = IntegerField('Age cutoff in weeks', validators=[DataRequired(message='Cutoff is required. Backups older '
                                                                                 'than the limit will be removed.')])

    delete_age = SubmitField('Delete backups older than cutoff')


class MessageMixin():

    show_students = BooleanField('Display to students')

    show_faculty = BooleanField('Display to faculty')

    show_login = BooleanField('Display on login screen if a broadcast message')

    dismissible = BooleanField('Allow message to be dismissed')

    title = StringField('Title', validators=[Optional()], description='Optional. Summarize your message briefly.')

    body = TextAreaField('Message', render_kw={"rows": 5},
                         validators=[DataRequired(message='You must enter a message, however short')])

    project_classes = CheckboxQuerySelectMultipleField('Display to users enrolled with',
                                                       query_factory=GetAllProjectClasses, get_label='name',
                                                       validators=[Optional()])


class AddMessageForm(Form, MessageMixin):

    def __init__(self, *args, **kwargs):

        convenor_editing = False
        if 'convenor_editing' in kwargs:
            convenor_editing = True
            del kwargs['convenor_editing']

        super().__init__(*args, **kwargs)

        if convenor_editing:
            self.projects.query_factory = GetConvenorProjectClasses
            self.projects.validators = [DataRequired(message='At least one project class should be selected')]

    submit = SubmitField('Add new message')


class EditMessageForm(Form, MessageMixin, EditFormMixin):

    def __init__(self, *args, **kwargs):

        convenor_editing = False
        if 'convenor_editing' in kwargs:
            convenor_editing = True
            del kwargs['convenor_editing']

        super().__init__(*args, **kwargs)

        if convenor_editing:
            self.projects.query_factory = GetConvenorProjectClasses
            self.projects.validators = [Optional()]


class ScheduleTypeMixin():

    available_types = [('interval', 'Fixed interval'), ('crontab', 'Crontab')]
    type = SelectField('Type of schedule', choices=available_types)


class ScheduleTypeForm(Form, ScheduleTypeMixin):

    submit = SubmitField('Select type')


class ScheduledTaskMixin():

    name = StringField('Name', validators=[DataRequired(message='A task name is required')])

    owner = QuerySelectField('Owner', query_factory=GetSysadminUsers, get_label=BuildUserRealName)

    tasks_available = [('app.tasks.prune_email.prune_email_log', 'Prune email log'),
                       ('app.tasks.backup.backup', 'Perform local backup'),
                       ('app.tasks.backup.thin', 'Thin local backups'),
                       ('app.tasks.backup.limit_size', 'Enforce limit on size of backup folder'),
                       ('app.tasks.backup.clean_up', 'Clean up backup folder'),
                       ('app.tasks.backup.drop_absent_backups', 'Drop absent backups'),
                       ('app.tasks.popularity.update_popularity_data', 'Update LiveProject popularity data'),
                       ('app.tasks.popularity.thin', 'Thin LiveProject popularity data')]
                       # ('remote_backup', 'Backup to internet location')]
    task = SelectField('Task', choices=tasks_available)

    arguments = StringField('Arguments', validators=[valid_json],
                            description='Format as a JSON list.')

    keyword_arguments = StringField('Keyword arguments', validators=[valid_json],
                                    description='Format as a JSON dictionary.')

    expires = DateTimeField('Expires at', validators=[Optional()],
                            description='Optional. Format YYYY-mm-dd HH:MM:SS. Leave blank for no expiry.')


class IntervalMixin():

    every = IntegerField('Run every', validators=[DataRequired(message='You must enter a nonzero interval')])

    available_periods = [('seconds', 'seconds'), ('minutes', 'minutes'), ('hours', 'hours'), ('days', 'days'), ('weeks', 'weeks')]
    period = SelectField('Period', choices=available_periods)


class CrontabMixin():

    minute = StringField('Minute pattern', validators=[DataRequired(message='You must enter a pattern')])

    hour = StringField('Hour pattern', validators=[DataRequired(message='You must enter a pattern')])

    day_of_week = StringField('Day-of-week pattern', validators=[DataRequired(message='You must enter a pattern')])

    day_of_month = StringField('Day-of-month pattern', validators=[DataRequired(message='You must enter a pattern')])

    month_of_year = StringField('Month-of-year pattern', validators=[DataRequired(message='You must enter a pattern')])


class AddIntervalScheduledTask(Form, ScheduledTaskMixin, IntervalMixin):

    submit = SubmitField('Add new task')


class EditIntervalScheduledTask(Form, ScheduledTaskMixin, IntervalMixin, EditFormMixin):

    pass


class AddCrontabScheduledTask(Form, ScheduledTaskMixin, CrontabMixin):

    submit = SubmitField('Add new task')


class EditCrontabScheduledTask(Form, ScheduledTaskMixin, CrontabMixin, EditFormMixin):

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
                             description='When hourly backups are no longer being kept, daily backups are kept '
                                         'for an extra period of time. After this, only weekly backups are retained.')

    # field names for limits are blank; to get formatting right they're included directly on the template
    backup_limit = FloatField('', validators=[Optional()],
                                description='Leave blank for no limit.')

    units_choices = [(BackupConfiguration.KEY_MB, 'Mb'),
                     (BackupConfiguration.KEY_GB, 'Gb'),
                     (BackupConfiguration.KEY_TB, 'Tb')]
    limit_units = SelectField('', choices=units_choices, coerce=int)


class EditBackupOptionsForm(Form, BackupOptionsMixin):

    submit = SubmitField('Save changes')


class EnrollmentRecordMixin():

    supervisor_state = RadioField('Project supervision status', choices=EnrollmentRecord.supervisor_choices, coerce=int)

    supervisor_reenroll = IntegerField('Re-enroll in academic year',
                                   description='Optional. For faculty on sabbatical or buy-outs, enter a year in which '
                                               'automatic re-enrollment should occur.',
                                   validators=[Optional()])

    supervisor_comment = TextAreaField('Comment', render_kw={"rows": 3},
                                       description='Optional. Use to document sabbaticals, buy-outs and exemptions.',
                                       validators=[Optional()])

    marker_state = RadioField('2nd marker status', choices=EnrollmentRecord.marker_choices, coerce=int)

    marker_reenroll = IntegerField('Re-enroll in academic year',
                                   description='Optional. For faculty on sabbatical or buy-outs, enter a year in which '
                                               'automatic re-enrollment should occur.',
                                   validators=[Optional()])

    marker_comment = TextAreaField('Comment', render_kw={"rows": 3},
                                   description='Optional. Use to document sabbaticals, buy-outs and exemptions.',
                                   validators=[Optional()])

class EnrollmentRecordForm(Form, EnrollmentRecordMixin, EditFormMixin):

    pass


class SkillGroupMixin():

    colour = StringField('Colour',
                         description='Assign a colour to help students identify skills belonging to this group')

    add_group = BooleanField('Add group name to skill labels',
                             description='Select if you wish skills in this group to be labelled as <group name>: <skill name>')


class AddSkillGroupForm(Form, SkillGroupMixin):

    name = StringField('Name', validators=[DataRequired(message='A name for the group is required'),
                                           globally_unique_skill_group])

    submit = SubmitField('Add new skill')


class EditSkillGroupForm(Form, SkillGroupMixin, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='A name for the group is required'),
                                           unique_or_original_skill_group])


class RoleMixin():

    description = StringField('Description')


class AddRoleForm(Form, RoleMixin):

    name = StringField('Name', validators=[DataRequired(message='A name for the role is required'),
                                           globally_unique_role])

    submit = SubmitField('Add new role')


class EditRoleForm(Form, RoleMixin, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='A name for the role is required'),
                                           unique_or_original_role])
