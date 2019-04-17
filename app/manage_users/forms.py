#
# Created by David Seery on 2019-04-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from functools import partial

from flask import request
from flask_security.forms import get_form_field_label, email_required, email_validator, password_length, EqualTo, Form, \
    RegisterFormMixin, UniqueEmailFormMixin, NextFormMixin
from wtforms import StringField, BooleanField, PasswordField, SelectField, SubmitField, IntegerField, RadioField, \
    TextAreaField
from wtforms.validators import InputRequired, Length, Optional
from wtforms_alchemy import QuerySelectField

from app.models import DEFAULT_STRING_LENGTH, EnrollmentRecord
from app.shared.forms.mixins import ThemeMixin, FirstLastNameMixin, FacultyDataMixinFactory, SaveChangesMixin, \
    EditUserNameMixin
from app.shared.forms.queries import GetActiveDegreeProgrammes, BuildDegreeProgrammeName
from app.shared.forms.wtf_validators import valid_username, globally_unique_username, unique_or_original_email, \
    OptionalIf, password_strength, value_is_nonnegative, globally_unique_exam_number, unique_or_original_exam_number, \
    unique_or_original_batch_item_userid, unique_or_original_batch_item_email, unique_or_original_batch_item_exam_number


class UniqueUserNameMixin():

    username = StringField('Username', validators=[InputRequired(message='Username is required'),
                                                   Length(max=DEFAULT_STRING_LENGTH),
                                                   valid_username, globally_unique_username])


class EditEmailFormMixin():

    email = StringField(
        get_form_field_label('email'),
        validators=[Length(max=DEFAULT_STRING_LENGTH), email_required, email_validator, unique_or_original_email])


class AskConfirmAddFormMixin():

    ask_confirm = BooleanField('Send confirmation email')


class AskConfirmEditFormMixin():

    ask_confirm = BooleanField('Resend confirmation email if address is changed')


# redefine NewPasswordFormMixin from flask-security to check password strength
class NewPasswordFormMixin():

    random_password = BooleanField('Generate random password', default=True)

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


class StudentDataMixin():

    foundation_year = BooleanField('Foundation year')

    cohort = IntegerField('Cohort', validators=[InputRequired(message="Cohort is required")],
                          description='Enter the year the student joined the university. '
                                      'If this needs to be adjusted because the student did a foundation year, '
                                      'or for other reasons such as resitting years, this will be accommodated '
                                      'separately.')

    repeated_years = IntegerField('Number of repeat years', default=0,
                                  validators=[InputRequired(message="Number of repeat years is required"),
                                              value_is_nonnegative],
                                  description='Enter the number of repeat years the student has used.')

    programme = QuerySelectField('Degree programme', query_factory=GetActiveDegreeProgrammes,
                                 get_label=BuildDegreeProgrammeName)

    intermitting = BooleanField('Currently intermitting')


class RegisterOfficeForm(Form, RegisterFormMixin, UniqueUserNameMixin, AskConfirmAddFormMixin, ThemeMixin,
                         UniqueEmailFormMixin, NewPasswordFormMixin, FirstLastNameMixin):

    pass


class ConfirmRegisterOfficeForm(RegisterOfficeForm, PasswordConfirmFormMixin, NextFormMixin):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        if not self.next.data:
            self.next.data = request.args.get('next', '')


class RegisterFacultyForm(RegisterOfficeForm, FacultyDataMixinFactory(admin=True)):

    save_and_exit = SubmitField('Save and exit')

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.submit.label.text = 'Next: Research group affiliations'


class ConfirmRegisterFacultyForm(ConfirmRegisterOfficeForm, FacultyDataMixinFactory(admin=True)):

    save_and_exit = SubmitField('Save and exit')

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.submit.label.text = 'Next: Research group affiliations'


class RegisterStudentForm(RegisterOfficeForm, StudentDataMixin):

    exam_number = IntegerField('Exam number', validators=[InputRequired(message="Exam number is required"),
                                                          globally_unique_exam_number])


class ConfirmRegisterStudentForm(ConfirmRegisterOfficeForm, StudentDataMixin):

    exam_number = IntegerField('Exam number', validators=[InputRequired(message="Exam number is required"),
                                                          globally_unique_exam_number])


class EditOfficeForm(Form, SaveChangesMixin, EditUserNameMixin, AskConfirmEditFormMixin, ThemeMixin,
                     EditEmailFormMixin, FirstLastNameMixin):

    pass


class EditFacultyForm(EditOfficeForm, FacultyDataMixinFactory(admin=True)):

    pass


class EditStudentForm(EditOfficeForm, StudentDataMixin):

    exam_number = IntegerField('Exam number', validators=[InputRequired(message="Exam number is required"),
                                                          unique_or_original_exam_number])


class ResearchGroupMixin():

    website = StringField('Website', description='Optional.', validators=[Length(max=DEFAULT_STRING_LENGTH)])

    colour = StringField('Colour', description='Assign a colour to help students identify this research group.',
                         validators=[Length(max=DEFAULT_STRING_LENGTH)])


class UploadBatchCreateForm(Form):

    submit = SubmitField('Upload user list')


def EditStudentBatchItemFormFactory(batch):

    class EditStudentBatchItemForm(Form, SaveChangesMixin):

        user_id = StringField('User id', validators=[InputRequired('User id is required'),
                                                     Length(max=DEFAULT_STRING_LENGTH),
                                                     partial(unique_or_original_batch_item_userid, batch.id)])

        email = StringField('Email address', validators=[InputRequired('Email address is required'),
                                                         Length(max=DEFAULT_STRING_LENGTH), email_validator,
                                                         partial(unique_or_original_batch_item_email, batch.id)])

        last_name = StringField('Last name', validators=[InputRequired('Last name is required'),
                                                         Length(max=DEFAULT_STRING_LENGTH)])

        first_name = StringField('First name', validators=[InputRequired('First name is required'),
                                                           Length(max=DEFAULT_STRING_LENGTH)])

        exam_number = IntegerField('Exam number', validators=[InputRequired('Exam number is required'),
                                                              partial(unique_or_original_batch_item_exam_number, batch.id)])

        cohort = IntegerField('Cohort', validators=[InputRequired('Cohort is required')])

        programme = QuerySelectField('Degree programme', query_factory=GetActiveDegreeProgrammes,
                                     get_label=BuildDegreeProgrammeName)

        foundation_year = BooleanField('Foundation year')

        repeated_years = IntegerField('Number of repeat years', default=0,
                                      validators=[InputRequired(message="Number of repeat years is required"),
                                                  value_is_nonnegative])

        intermitting = BooleanField('Currently intermitting')

    return EditStudentBatchItemForm


class EnrollmentRecordMixin():

    # SUPERVISOR

    supervisor_state = RadioField('Project supervision status', choices=EnrollmentRecord.supervisor_choices, coerce=int)

    supervisor_reenroll = IntegerField('Re-enroll in academic year',
                                   description='Optional. For faculty on sabbatical or buy-outs, enter a year in which '
                                               'automatic re-enrollment should occur.',
                                   validators=[Optional()])

    supervisor_comment = TextAreaField('Comment', render_kw={"rows": 3},
                                       description='Optional. Use to document sabbaticals, buy-outs and exemptions.',
                                       validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)])


    # MARKER

    marker_state = RadioField('2nd marker status', choices=EnrollmentRecord.marker_choices, coerce=int)

    marker_reenroll = IntegerField('Re-enroll in academic year',
                                   description='Optional. For faculty on sabbatical or buy-outs, enter a year in which '
                                               'automatic re-enrollment should occur.',
                                   validators=[Optional()])

    marker_comment = TextAreaField('Comment', render_kw={"rows": 3},
                                   description='Optional. Use to document sabbaticals, buy-outs and exemptions.',
                                   validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)])


    # PRESENTATIONS

    presentations_state = RadioField('2nd marker status', choices=EnrollmentRecord.presentations_choices, coerce=int)

    presentations_reenroll = IntegerField('Re-enroll in academic year',
                                         description='Optional. For faculty on sabbatical or buy-outs, enter a year '
                                                     'in which automatic re-enrollment should occur.',
                                         validators=[Optional()])

    presentations_comment = TextAreaField('Comment', render_kw={"rows": 3},
                                         description='Optional. Use to document sabbaticals, buy-outs and exemptions.',
                                         validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)])


class EnrollmentRecordForm(Form, EnrollmentRecordMixin, SaveChangesMixin):

    pass