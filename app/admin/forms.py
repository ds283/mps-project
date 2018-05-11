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
from flask_security.forms import Form, RegisterFormMixin, UniqueEmailFormMixin, NewPasswordFormMixin,\
    PasswordConfirmFormMixin, NextFormMixin
from werkzeug.local import LocalProxy
from wtforms import StringField, ValidationError
from wtforms.validators import DataRequired

from usernames import is_safe_username


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


def valid_username(form, field):
    if not is_safe_username(field.data):
        raise ValidationError('User name "{name}" is not valid'.format(name=field.data))


def unique_username(form, field):
    if _datastore.get_user(field.data) is not None:
        raise ValidationError('{name} is already associated with an account'.format(name=field.data))


class UniqueUserNameMixin():

    username = StringField('Username',
                           validators=[DataRequired(message='Username is required'),
                                       valid_username,
                                       unique_username])


class RegisterForm(Form, RegisterFormMixin, UniqueUserNameMixin,
                   UniqueEmailFormMixin, NewPasswordFormMixin):
    first_name = StringField('First name', validators=[DataRequired(message='First name is required')])
    last_name = StringField('Last or family name', validators=[DataRequired(message='Last name is required')])

    pass


class ConfirmRegisterForm(RegisterForm, PasswordConfirmFormMixin, NextFormMixin):

    def __init__(self, *args, **kwargs):
        super(RegisterForm, self).__init__(*args, **kwargs)
        if not self.next.data:
            self.next.data = request.args.get('next', '')
