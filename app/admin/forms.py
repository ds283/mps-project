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
from wtforms import StringField, SelectField, PasswordField, SubmitField, ValidationError
from wtforms.validators import DataRequired

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


def unique_or_original_email(form, field):
    if field.data != form.user.email and _datastore.get_user(field.data) is not None:
        raise ValidationError('{name} is already associated with an account'.format(name=field.data))


def password_strength(form, field):

    username = form.username.data or ''
    first_name = form.first_name.data or ''
    last_name = form.last_name.data or ''

    results = zxcvbn(field.data, user_inputs=[username, first_name, last_name])

    if 'score' in results and int(results['score']) <= 2:

        msg = ''
        if 'feedback' in results:
            if 'warning' in results['feedback']:
                msg = results['feedback']['warning']
                if msg[-1] != '.':
                    msg += '.'

        if len(msg) is 0:
            msg = 'Weak password (score {n}).'.format(n=results['score'])

        if 'feedback' in results:
            if 'suggestions' in results['feedback'] is not None:
                for m in results['feedback']['suggestions']:
                    msg = msg + " " + m
                    if msg[-1] != '.':
                        msg += '.'

        if 'crack_times_display' and 'crack_times_seconds' in results:

            source = results['crack_times_seconds']
            crack_seconds = { k: float(source[k]) for k in source }

            minkey = min(crack_seconds, key=crack_seconds.get)
            if minkey in results['crack_times_display']:
                msg = msg + " Estimated crack time: " + results['crack_times_display'][minkey]
                if msg[-1] != '.':
                    msg += '.'

        raise ValidationError(msg)


class UniqueUserNameMixin():

    username = StringField(
        'Username',
        validators=[DataRequired(message='Username is required'), valid_username, globally_unique_username])


class EditUserNameMixin():

    username = StringField(
        'Username',
        validators=[DataRequired(message='Username is required'), valid_username, unique_or_original_username])


class EditEmailFormMixin():

    email = StringField(
        get_form_field_label('email'),
        validators=[email_required, email_validator, unique_or_original_email])


# redefine NewPasswordFormMixin from flask-security to check password strength
class NewPasswordFormMixin():

    password = PasswordField(
        get_form_field_label('password'),
        validators=[password_required, password_length, password_strength])


class PasswordConfirmFormMixin():

    password_confirm = PasswordField(
        get_form_field_label('retype_password'),
        validators=[EqualTo('password', message='RETYPE_PASSWORD_MISMATCH'),
                    password_required])


class RoleMixin():

    available_roles = [('faculty', 'Faculty'), ('student', 'Student'), ('office', 'Office')]
    roles = SelectField('Role', choices=available_roles,
                        validators=[DataRequired(message="A role must be assigned to each account")])


class EditFormMixin():

    submit = SubmitField('Save changes')


class RegisterForm(Form, RegisterFormMixin, UniqueUserNameMixin, RoleMixin,
                   UniqueEmailFormMixin, NewPasswordFormMixin):

    first_name = StringField('First name', validators=[DataRequired(message='First name is required')])
    last_name = StringField('Last or family name', validators=[DataRequired(message='Last name is required')])


class ConfirmRegisterForm(RegisterForm, PasswordConfirmFormMixin, NextFormMixin):

    def __init__(self, *args, **kwargs):
        super(RegisterForm, self).__init__(*args, **kwargs)
        if not self.next.data:
            self.next.data = request.args.get('next', '')


class EditUserForm(Form, EditFormMixin, EditUserNameMixin, EditEmailFormMixin):

    first_name = StringField('First name', validators=[DataRequired(message='First name is required')])
    last_name = StringField('Last or family name', validators=[DataRequired(message='Last name is required')])
