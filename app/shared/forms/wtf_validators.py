#
# Created by David Seery on 01/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json

from usernames import is_safe_username
from wtforms import ValidationError
from wtforms.validators import Optional
from zxcvbn import zxcvbn

from ...models import ResearchGroup, DegreeType, DegreeProgramme, TransferableSkill, SkillGroup, ProjectClass, \
    Supervisor, Role, StudentData, MatchingAttempt

from flask import current_app
from werkzeug.local import LocalProxy

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
    if TransferableSkill.query.filter(TransferableSkill.name == field.data,
                                      TransferableSkill.group_id == form.group.data.id).first():
        raise ValidationError('{name} is already associated with a transferable skill'.format(name=field.data))


def unique_or_original_transferable_skill(form, field):
    if field.data != form.skill.name and \
            TransferableSkill.query.filter(TransferableSkill.name == field.data,
                                           TransferableSkill.group_id == form.group.data.id).first():
        raise ValidationError('{name} is already associated with a transferable skill'.format(name=field.data))


def globally_unique_skill_group(form, field):
    if SkillGroup.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a skill group'.format(name=field.data))


def unique_or_original_skill_group(form, field):
    if field.data != form.group.name and SkillGroup.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a skill group'.format(name=field.data))


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


def globally_unique_role(form, field):
    if Role.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a user role'.format(name=field.data))


def unique_or_original_role(form, field):
    if field.data != form.role.name and Role.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a user role'.format(name=field.data))


def globally_unique_exam_number(form, field):
    rec = StudentData.query.filter_by(exam_number=field.data).first()
    if rec is not None:
        raise ValidationError('Exam number {n} is already associated with student {name}'.format(n=rec.exam_number,
                                                                                                 name=rec.user.name))


def unique_or_original_exam_number(form, field):
    if field.data == form.user.student_data.exam_number:
        return

    rec = StudentData.query.filter_by(exam_number=field.data).first()
    if rec is not None:
        raise ValidationError('Exam number {n} is already associated with student {name}'.format(n=rec.exam_number,
                                                                                                 name=rec.user.name))


def globally_unique_matching_name(form, field):
    if MatchingAttempt.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already in use for a matching attempt'.format(name=field.data))


def valid_json(form, field):
    try:
        json_obj = json.loads(field.data)
    except TypeError:
        raise ValidationError('Unexpected text encoding')
    except json.JSONDecodeError:
        raise ValidationError('Could not translate to a valid JSON object')


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


class NotOptionalIf(Optional):
    """
    Makes a field optional if another field is set false
    """

    def __init__(self, other_field_name, *args, **kwargs):

        self.other_field_name = other_field_name
        super(NotOptionalIf, self).__init__(*args, **kwargs)


    def __call__(self, form, field):

        other_field = form._fields.get(self.other_field_name)

        if other_field is None:
            return

        if not bool(other_field.data):
            super(NotOptionalIf, self).__call__(form, field)
