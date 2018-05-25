#
# Created by David Seery on 10/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import request, current_app
from flask_security.forms import Form, RegisterFormMixin, UniqueEmailFormMixin, NextFormMixin, get_form_field_label
from flask_security.forms import password_required, password_length, email_required, email_validator, EqualTo
from werkzeug.local import LocalProxy
from wtforms import StringField, IntegerField, SelectField, PasswordField, BooleanField, SubmitField, ValidationError
from wtforms.validators import DataRequired, Optional
from wtforms_alchemy.fields import QuerySelectField

from ..models import User, Role, ResearchGroup, DegreeType, DegreeProgramme, TransferableSkill, \
    ProjectClass, Supervisor, submission_choices, academic_titles, extent_choices, year_choices

from ..fields import EditFormMixin, CheckboxQuerySelectMultipleField

from usernames import is_safe_username
from zxcvbn import zxcvbn


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


def valid_username(form, field):
    if not is_safe_username(field.data):
        raise ValidationError('User name "{name}" is not valid'.format(name=field.data))


def globally_unique_username(form, field):
    if _datastore.get_user(field.data) is not None:
        raise ValidationError('{name} is already associated with an account'.format(name=field.data))


def unique_or_original_username(form, field):
    if field.data != form.user.username and _datastore.get_user(field.data) is not None:
        raise ValidationError('{name} is already associated with an account'.format(name=field.data))


def existing_username(form, field):
    user = _datastore.get_user(field.data)

    if user is None:
        raise ValidationError('userid {name} is not an existing user'.format(name=field.data))
    if not user.is_active:
        raise ValidationError('userid {name} exists, but it not currently active'.format(name=field.data))


def unique_or_original_email(form, field):
    if field.data != form.user.email and _datastore.get_user(field.data) is not None:
        raise ValidationError('{name} is already associated with an account'.format(name=field.data))


def globally_unique_group_abbreviation(form, field):
    if ResearchGroup.query.filter_by(abbreviation=field.data).first():
        raise ValidationError('{name} is already associated with a research group'.format(name=field.data))


def unique_or_original_abbreviation(form, field):
    if field.data != form.group.abbreviation and ResearchGroup.query.filter_by(abbreviation=field.data).first():
        raise ValidationError('{name} is already associated with a research group'.format(name=field.data))


def globally_unique_degree_type(form, field):
    if DegreeType.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a degree type'.format(name=field.data))


def unique_or_original_degree_type(form, field):
    if field.data != form.degree_type.name and DegreeType.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a degree type'.format(name=field.data))


def globally_unique_degree_programme(form, field):
    degree_type = form.degree_type.data
    if DegreeProgramme.query.filter_by(name=field.data, type_id=degree_type.id).first():
        raise ValidationError('{name} is already associated with a degree programme of the same type'.format(name=field.data))


def unique_or_original_degree_programme(form, field):
    degree_type = form.degree_type.data
    if (field.data != form.programme.name or degree_type.id != form.programme.type_id) and \
            DegreeProgramme.query.filter_by(name=field.data, type_id=degree_type.id).first():
        raise ValidationError('{name} is already associated with a degree programme of the same type'.format(name=field.data))


def globally_unique_transferable_skill(form, field):
    if TransferableSkill.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a transferable skill'.format(name=field.data))


def unique_or_original_transferable_skill(form, field):
    if field.data != form.skill.name and TransferableSkill.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a transferable skill'.format(name=field.data))


def globally_unique_project_class(form, field):
    if ProjectClass.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project class'.format(name=field.data))


def unique_or_original_project_class(form, field):
    if field.data != form.project_class.name and ProjectClass.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project class'.format(name=field.data))


def globally_unique_project_class_abbrev(form, field):
    if ProjectClass.query.filter_by(abbreviation=field.data).first():
        raise ValidationError('{name} is already in use as an abbreviation'.format(name=field.data))


def unique_or_original_project_class_abbrev(form, field):
    if field.data != form.project_class.abbreviation and ProjectClass.query.filter_by(abbreviation=field.data).first():
        raise ValidationError('{name} is already in use as an abbreviation'.format(name=field.data))


def globally_unique_supervisor(form, field):
    if Supervisor.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a supervisory role'.format(name=field.data))


def unique_or_original_supervisor(form, field):
    if field.data != form.supervisor.name and Supervisor.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a supervisory role'.format(name=field.data))


def password_strength(form, field):

    username = form.username.data or ''
    first_name = form.first_name.data or ''
    last_name = form.last_name.data or ''

    # password length validation doesn't stop the validation chain if the password is too short
    # in this case, just exit because validating the password doesn't make sense
    if len(field.data) < 6:
        return

    results = zxcvbn(field.data, user_inputs=[username, first_name, last_name])

    if 'score' in results and int(results['score']) <= 2:

        msg = ''
        if 'feedback' in results:
            if 'warning' in results['feedback']:
                msg = results['feedback']['warning']
                if msg is not None and len(msg) > 0 and msg[-1] != '.':
                    msg += '.'

        if len(msg) is 0:
            msg = 'Weak password (score {n}).'.format(n=results['score'])

        if 'feedback' in results:
            if 'suggestions' in results['feedback'] is not None:
                for m in results['feedback']['suggestions']:
                    msg = msg + " " + m
                    if msg[-1] != '.':
                        msg += '.'

        if 'crack_times_display' in results:

            if 'online_no_throttling_10_per_second' in results['crack_times_display']:

                msg = msg + " Estimated crack time: " + results['crack_times_display']['online_no_throttling_10_per_second']
                if msg[-1] != '.':
                    msg += '.'

        raise ValidationError(msg)


class OptionalIf(Optional):
    """
    Makes a field optional if another field is set true
    """

    def __init__(self, other_field_name, *args, **kwargs):

        self.other_field_name = other_field_name
        super(OptionalIf, self).__init__(*args, **kwargs)


    def __call__(self, form, field):

        other_field = form._fields.get(self.other_field_name)

        if other_field is None:
            return

        if bool(other_field.data):
            super(OptionalIf, self).__call__(form, field)


def GetActiveDegreeTypes():

    return DegreeType.query.filter_by(active=True)


def GetActiveDegreeProgrammes():

    return DegreeProgramme.query.filter_by(active=True)


def BuildDegreeProgrammeName(programme):

    return programme.name + ' ' + programme.degree_type.name


def GetActiveFaculty():

    return User.query.filter(User.active, User.roles.any(Role.name == 'faculty'))


def BuildUserRealName(user):

    return user.build_name_and_username()


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


class AskConfirmFormMixin():

    ask_confirm = BooleanField('Send confirmation email')


# redefine NewPasswordFormMixin from flask-security to check password strength
class NewPasswordFormMixin():

    null_password = BooleanField('Generate null password')

    password = PasswordField(
        get_form_field_label('password'),
        validators=[OptionalIf('null_password'), password_length, password_strength])


class PasswordConfirmFormMixin():

    password_confirm = PasswordField(
        get_form_field_label('retype_password'),
        validators=[OptionalIf('null_password'), EqualTo('password', message='RETYPE_PASSWORD_MISMATCH')])


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
                                      description='User Dr, Professor or similar in student-facing web pages')
    sign_off_students = BooleanField('Ask to confirm student meetings', default=True,
                                     description='If meetings are required before project selection, '
                                                 'confirmation is needed before allowing students to sign up ')

    office = StringField('Office', validators=[DataRequired(message='Please enter your office details to help '
                                                                    'students find you')])


class StudentDataMixin():

    exam_number = IntegerField('Exam number', validators=[DataRequired(message="Exam number is required")])

    cohort = IntegerField('Cohort', validators=[DataRequired(message="Cohort is required")])

    programme = QuerySelectField('Degree programme', query_factory=GetActiveDegreeProgrammes,
                                 get_label=BuildDegreeProgrammeName)


class RegisterOfficeForm(Form, RegisterFormMixin, UniqueUserNameMixin, AskConfirmFormMixin,
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


class EditOfficeForm(Form, EditFormMixin, EditUserNameMixin, AskConfirmFormMixin, EditEmailFormMixin, FirstLastNameMixin):

    pass


class EditFacultyForm(EditOfficeForm, FacultyDataMixin):

    pass


class EditStudentForm(EditOfficeForm, StudentDataMixin):

    pass


class FacultySettingsForm(Form, EditUserNameMixin, FacultyDataMixin, FirstLastNameMixin, EditFormMixin):

    pass


class ResearchGroupForm():

    name = StringField('Name', validators=[DataRequired(message='Name is required')])

    website = StringField('Website', description='Optional. Do not include http://')


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


class AddTransferrableSkillForm(Form):

    name = StringField('Skill', validators=[DataRequired(message='Name of transferable skill is required'),
                                            globally_unique_transferable_skill])

    submit = SubmitField('Add new transferable skill')


class EditTransferableSkillForm(Form, EditFormMixin):

    name = StringField('Skill', validators=[DataRequired(message='Name of transferable skill is required'),
                                            unique_or_original_transferable_skill])


class ProjectClassMixin():

    year = SelectField('Runs in year', choices=year_choices, coerce=int,
                       description='Select the academic year in which students join the project')
    extent = SelectField('Duration', choices=extent_choices, coerce=int,
                         description='For how many academic years do students participate in the project?')

    require_confirm = BooleanField('Require faculty to confirm projects yearly')

    supervisor_carryover = BooleanField('For multi-year projects, automatically carry over supervisor year-to-year')

    submissions = SelectField('Submissions per year', choices=submission_choices, coerce=int,
                              description='Select number of marked reports submitted per academic year')

    initial_choices = IntegerField('Number of initial project preferences',
                                   description='Select number of preferences students should list before joining')

    switch_choices = IntegerField('Number of subsequent project preferences',
                                      description='Number of preferences to allow in subsequent years, if switching is allowed')

    convenor = QuerySelectField('Convenor', query_factory=GetActiveFaculty, get_label=BuildUserRealName)

    selection_open_to_all = BooleanField('Project selection is open to undergraduates from all programmes',
                                         description='Not normally required, but use for Research Placement projects')

    programmes = CheckboxQuerySelectMultipleField('Auto-enroll students from degree programmes', query_factory=GetActiveDegreeProgrammes,
                                                  get_label=BuildDegreeProgrammeName,
                                                  validators=[DataRequired(message='At least one degree programme should be selected')])


class AddProjectClassForm(Form, ProjectClassMixin):

    name = StringField('Name', validators=[DataRequired(message='Name of project class is required'),
                                           globally_unique_project_class])
    abbreviation = StringField('Abbreviation', validators=[DataRequired(message='An abbreviation is rqwuired'),
                                                           globally_unique_project_class_abbrev])

    submit = SubmitField('Add new project class')


class EditProjectClassForm(Form, ProjectClassMixin, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='Name of project class is required'),
                                          unique_or_original_project_class])
    abbreviation = StringField('Abbreviation', validators=[DataRequired(message='An abbreviation is rqwuired'),
                                                           unique_or_original_project_class_abbrev])


class AddSupervisorForm(Form):

    name = StringField('Name', validators=[DataRequired(message='Name of supervisory role is required'),
                                           globally_unique_supervisor])

    submit = SubmitField('Add new supervisory role')


class EditSupervisorForm(Form, EditFormMixin):

    name = StringField('Name', validators=[DataRequired(message='Name of supervisory role is required'),
                                           unique_or_original_supervisor])


class GlobalRolloverForm(Form):

    submit = SubmitField('Rollover')
