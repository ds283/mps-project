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

from flask import current_app
from flask_security import password_length_validator, password_complexity_validator, password_breached_validator
from python_usernames import is_safe_username
from werkzeug.local import LocalProxy
from wtforms import ValidationError
from wtforms.validators import Optional

from ...database import db
from ...models import (
    ResearchGroup,
    DegreeType,
    DegreeProgramme,
    TransferableSkill,
    SkillGroup,
    ProjectClass,
    Supervisor,
    Role,
    StudentData,
    MatchingAttempt,
    PresentationAssessment,
    Building,
    Room,
    ScheduleAttempt,
    Module,
    Project,
    ProjectDescription,
    FHEQ_Level,
    StudentBatchItem,
    AssetLicense,
    ProjectTagGroup,
    ProjectTag,
    FeedbackAsset,
)

_security = LocalProxy(lambda: current_app.extensions["security"])
_datastore = LocalProxy(lambda: _security.datastore)


def valid_username(form, field):
    if not is_safe_username(field.data):
        raise ValidationError('User name "{name}" is not valid'.format(name=field.data))


def globally_unique_username(form, field):
    if _datastore.find_user(username=field.data) is not None:
        raise ValidationError("{name} is already associated with an account".format(name=field.data))


def unique_or_original_username(form, field):
    if field.data == form.user.username:
        return

    return globally_unique_username(form, field)


def existing_username(form, field):
    user = _datastore.find_user(username=field.data)

    if user is None:
        raise ValidationError("userid {name} is not an existing user".format(name=field.data))
    if not user.is_active:
        raise ValidationError("userid {name} exists, but it not currently active".format(name=field.data))


def unique_or_original_email(form, field):
    if field.data == form.user.email:
        return

    if _datastore.find_user(email=field.data) is not None:
        raise ValidationError("{name} is already associated with an account".format(name=field.data))


def globally_unique_group_name(form, field):
    if ResearchGroup.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already associated with an affiliation/research group".format(name=field.data))


def unique_or_original_group_name(form, field):
    if field.data == form.group.name:
        return

    return globally_unique_group_name(form, field)


def globally_unique_group_abbreviation(form, field):
    if ResearchGroup.query.filter_by(abbreviation=field.data).first():
        raise ValidationError("{name} is already associated with an affiliation/research group".format(name=field.data))


def unique_or_original_group_abbreviation(form, field):
    if field.data == form.group.abbreviation:
        return

    return globally_unique_group_abbreviation(form, field)


def globally_unique_degree_type(form, field):
    if DegreeType.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already associated with a degree type".format(name=field.data))


def unique_or_original_degree_type(form, field):
    if field.data == form.degree_type.name:
        return

    return globally_unique_degree_type(form, field)


def globally_unique_degree_abbreviation(form, field):
    if DegreeType.query.filter_by(abbreviation=field.data).first():
        raise ValidationError("{name} is already associated with a degree type".format(name=field.data))


def unique_or_original_degree_abbreviation(form, field):
    if field.data == form.degree_type.abbreviation:
        return

    return globally_unique_degree_abbreviation(form, field)


def globally_unique_degree_programme(form, field):
    degree_type = form.degree_type.data
    if DegreeProgramme.query.filter_by(name=field.data, type_id=degree_type.id).first():
        raise ValidationError("{name} is already associated with a degree programme of the same type".format(name=field.data))


def unique_or_original_degree_programme(form, field):
    degree_type = form.degree_type.data
    if field.data == form.programme.name and degree_type.id == form.programme.type_id:
        return

    return globally_unique_degree_programme(form, field)


def globally_unique_course_code(form, field):
    if DegreeProgramme.query.filter_by(course_code=field.data).first():
        raise ValidationError("{code} is already associated with a degree programme".format(code=field.data))


def unique_or_original_course_code(form, field):
    if field.data == form.programme.course_code:
        return

    return globally_unique_course_code(form, field)


def globally_unique_programme_abbreviation(form, field):
    degree_type = form.degree_type.data
    if DegreeProgramme.query.filter_by(abbreviation=field.data, type_id=degree_type.id).first():
        raise ValidationError("{name} is already associated with a degree programme of the same type".format(name=field.data))


def unique_or_original_programme_abbreviation(form, field):
    degree_type = form.degree_type.data
    if field.data == form.programme.abbreviation and degree_type.id == form.programme.type_id:
        return

    return globally_unique_programme_abbreviation(form, field)


def globally_unique_transferable_skill(form, field):
    if TransferableSkill.query.filter(TransferableSkill.name == field.data, TransferableSkill.group_id == form.group.data.id).first():
        raise ValidationError("{name} is already in use for a transferable skill".format(name=field.data))


def unique_or_original_transferable_skill(form, field):
    if field.data == form.skill.name:
        return

    return globally_unique_transferable_skill(form, field)


def globally_unique_skill_group(form, field):
    if SkillGroup.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already in use for a skill group".format(name=field.data))


def unique_or_original_skill_group(form, field):
    if field.data == form.group.name:
        return

    return globally_unique_skill_group(form, field)


def globally_unique_project_tag_group(form, field):
    if db.session.query(ProjectTagGroup).filter_by(name=field.data).first():
        raise ValidationError("{name} is already in use for a project tag group".format(name=field.data))


def unique_or_original_project_tag_group(form, field):
    if field.data == form.group.name:
        return

    return globally_unique_project_tag_group(form, field)


def globally_unique_project_tag(form, field):
    if db.session.query(ProjectTag).filter_by(name=field.data).first():
        raise ValidationError("{name} is already in use for a project tag".format(name=field.data))


def unique_or_original_project_tag(form, field):
    if field.data == form.tag.name:
        return

    return globally_unique_project_tag(form, field)


def globally_unique_project_class(form, field):
    if ProjectClass.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already associated with a project class".format(name=field.data))


def unique_or_original_project_class(form, field):
    if field.data == form.project_class.name:
        return

    return globally_unique_project_class(form, field)


def globally_unique_project_class_abbrev(form, field):
    if ProjectClass.query.filter_by(abbreviation=field.data).first():
        raise ValidationError("{name} is already in use as an abbreviation".format(name=field.data))


def unique_or_original_project_class_abbrev(form, field):
    if field.data == form.project_class.abbreviation:
        return

    return globally_unique_project_class_abbrev(form, field)


def globally_unique_supervisor(form, field):
    if Supervisor.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already associated with a supervisory role".format(name=field.data))


def unique_or_original_supervisor(form, field):
    if field.data == form.supervisor.name:
        return

    return globally_unique_supervisor(form, field)


def globally_unique_supervisor_abbrev(form, field):
    if Supervisor.query.filter_by(abbreviation=field.data).first():
        raise ValidationError("{name} is already in use as an abbreviation".format(name=field.data))


def unique_or_original_supervisor_abbrev(form, field):
    if field.data == form.supervisor.abbreviation:
        return

    return globally_unique_supervisor_abbrev(form, field)


def globally_unique_role(form, field):
    if Role.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already associated with a user role".format(name=field.data))


def unique_or_original_role(form, field):
    if field.data == form.role.name:
        return

    return globally_unique_role(form, field)


def globally_unique_registration_number(form, field):
    rec = StudentData.query.filter_by(registration_number=field.data).first()
    if rec is not None:
        raise ValidationError(
            "Registration number {n} is already associated with student {name}".format(n=rec.registration_number, name=rec.user.name)
        )


def unique_or_original_registration_number(form, field):
    if field.data == form.user.student_data.registration_number:
        return

    return globally_unique_registration_number(form, field)


def globally_unique_matching_name(year, form, field):
    if MatchingAttempt.query.filter_by(name=field.data, year=year).first():
        raise ValidationError("{name} is already in use for a matching attempt this year".format(name=field.data))


def unique_or_original_matching_name(year, form, field):
    if field.data == form.record.name:
        return

    return globally_unique_matching_name(year, form, field)


def globally_unique_project(form, field):
    if Project.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already associated with a project".format(name=field.data))


def unique_or_original_project(form, field):
    if field.data == form.project.name:
        return

    return globally_unique_project(form, field)


def project_unique_label(form, field):
    if ProjectDescription.query.filter_by(parent_id=form.project_id, label=field.data).first():
        raise ValidationError("{name} is already used as a label for this project".format(name=field.data))


def project_unique_or_original_label(form, field):
    if field.data == form.desc.label:
        return

    return project_unique_label(form, field)


def value_is_nonnegative(form, field):
    if field.data < 0:
        raise ValidationError("Please enter a non-negative value")


def globally_unique_assessment_name(year, form, field):
    if PresentationAssessment.query.filter_by(name=field.data, year=year).first():
        raise ValidationError("{name} is already in use as an assessment name for this year".format(name=field.data))


def unique_or_original_assessment_name(year, form, field):
    if field.data == form.assessment.name:
        return

    return globally_unique_assessment_name(year, form, field)


def globally_unique_building_name(form, field):
    if Building.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already in use as a building name".format(name=field.data))


def unique_or_original_building_name(form, field):
    if field.data == form.building.name:
        return

    return globally_unique_building_name(form, field)


def globally_unique_room_name(form, field):
    if Room.query.filter_by(name=field.data, building_id=form.building.data.id).first():
        raise ValidationError("{building} {name} is already in use as a room name".format(building=form.building.data.name, name=field.data))


def unique_or_original_room_name(form, field):
    if field.data == form.room.name and form.building.data.id == form.room.building.id:
        return

    return globally_unique_room_name(form, field)


def globally_unique_schedule_name(assessment_id, form, field):
    if ScheduleAttempt.query.filter_by(owner_id=assessment_id, name=field.data).first():
        raise ValidationError("{name} is already in use for a schedule attached to this assessment".format(name=field.data))


def unique_or_original_schedule_name(assessment_id, form, field):
    if field.data == form.schedule.name:
        return

    return globally_unique_schedule_name(assessment_id, form, field)


def globally_unique_schedule_tag(form, field):
    if ScheduleAttempt.query.filter_by(tag=field.data).first():
        raise ValidationError("{tag} is already in use for a schedule tag".format(tag=field.data))


def unique_or_original_schedule_tag(form, field):
    if field.data == form.schedule.tag:
        return

    return globally_unique_schedule_tag(form, field)


def globally_unique_module_code(form, field):
    if Module.query.filter_by(code=field.data).first():
        raise ValidationError("{name} is already in use as a module code".format(name=field.data))


def unique_or_original_module_code(form, field):
    if field.data == form.module.code:
        return

    return globally_unique_module_code(form, field)


def globally_unique_FHEQ_level_name(form, field):
    if FHEQ_Level.query.filter_by(name=field.data).first():
        raise ValidationError("{name} is already defined as a FHEQ Level name".format(name=field.data))


def unique_or_original_FHEQ_level_name(form, field):
    if field.data == form.level.name:
        return

    return globally_unique_FHEQ_level_name(form, field)


def globally_unique_FHEQ_short_name(form, field):
    if FHEQ_Level.query.filter_by(short_name=field.data).first():
        raise ValidationError("{name} is already defined as a FHEQ short name".format(name=field.data))


def unique_or_original_FHEQ_short_name(form, field):
    if field.data == form.level.short_name:
        return

    return globally_unique_FHEQ_short_name(form, field)


def globally_unique_FHEQ_numeric_level(form, field):
    if FHEQ_Level.query.filter_by(numeric_level=field.data).first():
        raise ValidationError("Numeric level #{n} is already in use for a FHEQ level".format(n=field.data))


def unique_or_original_FHEQ_numeric_level(form, field):
    if field.data == form.level.numeric_level:
        return

    return globally_unique_FHEQ_numeric_level(form, field)


def globally_unique_license_name(form, field):
    if AssetLicense.query.filter_by(name=field.data).first():
        raise ValidationError('A license with the name "{name}" already exists'.format(name=field.data))


def unique_or_original_license_name(form, field):
    if field.data == form.license.name:
        return

    return globally_unique_license_name(form, field)


def globally_unique_license_abbreviation(form, field):
    if AssetLicense.query.filter_by(abbreviation=field.data).first():
        raise ValidationError('A license with the abbreviation "{abbv}" already exists'.format(abbv=field.data))


def unique_or_original_license_abbreviation(form, field):
    if field.data == form.license.abbreviation:
        return

    return globally_unique_license_abbreviation(form, field)


def per_license_unique_version(form, field):
    name = form.name.data
    if AssetLicense.query.filter_by(name=name, version=form.version.data).first():
        raise ValidationError('A license of type "{name}" with version ' '"{ver}" already exists'.form(name=name, ver=form.version.data))


def per_license_unique_or_original_version(form, field):
    if field.data == form.license.version and form.name.data == form.license.name:
        return

    return per_license_unique_version(form, field)


def globally_unique_batch_item_userid(batch_id, form, field):
    if StudentBatchItem.query.filter_by(parent_id=batch_id, user_id=field.data).first():
        raise ValidationError("{name} is already in use as a user id for this batch import".format(name=field.data))


def unique_or_original_batch_item_userid(batch_id, form, field):
    if field.data == form.batch_item.user_id:
        return

    return globally_unique_batch_item_userid(batch_id, form, field)


def globally_unique_batch_item_email(batch_id, form, field):
    if StudentBatchItem.query.filter_by(parent_id=batch_id, email=field.data).first():
        raise ValidationError("{name} is already in use as an email address for this batch import".format(name=field.data))


def unique_or_original_batch_item_email(batch_id, form, field):
    if field.data == form.batch_item.email:
        return

    return globally_unique_batch_item_email(batch_id, form, field)


def globally_unique_batch_item_exam_number(batch_id, form, field):
    if StudentBatchItem.query.filter_by(parent_id=batch_id, exam_number=field.data).first():
        raise ValidationError("{name} is already in use as an exam number for this batch import".format(name=field.data))


def unique_or_original_batch_item_exam_number(batch_id, form, field):
    if field.data == form.batch_item.exam_number:
        return

    return globally_unique_batch_item_exam_number(batch_id, form, field)


def globally_unique_batch_item_registration_number(batch_id, form, field):
    if StudentBatchItem.query.filter_by(parent_id=batch_id, registration_number=field.data).first():
        return ValidationError("{name} is already used as a registration number for this batch import".format(name=field.data))


def unique_or_original_batch_item_registration_number(batch_id, form, field):
    if field.data == form.batch_item.registration_number:
        return

    return globally_unique_batch_item_registration_number(batch_id, form, field)


def globally_unique_feedback_asset_label(form, field):
    if FeedbackAsset.query.filter_by(label=field.data).first():
        raise ValidationError('A feedback asset with the label "{abbv}" already exists'.format(abbv=field.data))


def unique_or_original_feedback_asset_label(form, field):
    if field.data == form.asset.label:
        return

    return globally_unique_feedback_asset_label(form, field)


def valid_json(form, field):
    try:
        json_obj = json.loads(field.data)
    except TypeError:
        raise ValidationError("Unexpected text encoding")
    except json.JSONDecodeError:
        raise ValidationError("Could not translate to a valid JSON object")


def password_strength(form, field):
    username = form.username.data or ""
    first_name = form.first_name.data or ""
    last_name = form.last_name.data or ""

    proposed_password = field.data

    length_msgs = password_length_validator(proposed_password)
    complexity_msgs = password_complexity_validator(
        proposed_password, is_register=True, username=username, first_name=first_name, last_name=last_name
    )
    pwn_msgs = password_breached_validator(proposed_password)

    msg_lst = [length_msgs, complexity_msgs, pwn_msgs]
    msgs = None

    for l in msg_lst:
        if l is not None:
            if msgs is None:
                msgs = l
            else:
                msgs += l

    if msgs is not None:
        raise ValidationError(". ".join(msgs))


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
