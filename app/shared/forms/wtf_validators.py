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
from flask_security import (
    password_breached_validator,
    password_complexity_validator,
    password_length_validator,
)
from python_usernames import is_safe_username
from werkzeug.local import LocalProxy
from wtforms import ValidationError
from wtforms.validators import Optional

from ...database import db
from ...models import (
    AssetLicense,
    Building,
    DegreeProgramme,
    DegreeType,
    FacultyBatchItem,
    FeedbackAsset,
    FeedbackRecipe,
    FHEQ_Level,
    MarkingEvent,
    MarkingScheme,
    MarkingWorkflow,
    MatchingAttempt,
    Module,
    PresentationAssessment,
    Project,
    ProjectClass,
    ProjectDescription,
    ProjectTag,
    ProjectTagGroup,
    ResearchGroup,
    Role,
    Room,
    ScheduleAttempt,
    SkillGroup,
    StudentBatchItem,
    StudentData,
    SubmissionPeriodUnit,
    SupervisionEventTemplate,
    Supervisor,
    TransferableSkill,
)

_security = LocalProxy(lambda: current_app.extensions["security"])
_datastore = LocalProxy(lambda: _security.datastore)


def valid_username(form, field):
    if not is_safe_username(field.data):
        raise ValidationError('User name "{name}" is not valid'.format(name=field.data))


def globally_unique_username(form, field):
    if _datastore.find_user(username=field.data) is not None:
        raise ValidationError(
            "{name} is already associated with an account".format(name=field.data)
        )


def unique_or_original_username(form, field):
    if field.data == form.user.username:
        return

    return globally_unique_username(form, field)


def existing_username(form, field):
    user = _datastore.find_user(username=field.data)

    if user is None:
        raise ValidationError(
            "userid {name} is not an existing user".format(name=field.data)
        )
    if not user.is_active:
        raise ValidationError(
            "userid {name} exists, but it not currently active".format(name=field.data)
        )


def unique_or_original_email(form, field):
    if field.data == form.user.email:
        return

    if _datastore.find_user(email=field.data) is not None:
        raise ValidationError(
            "{name} is already associated with an account".format(name=field.data)
        )


def globally_unique_group_name(form, field):
    if ResearchGroup.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already associated with an affiliation/research group".format(
                name=field.data
            )
        )


def unique_or_original_group_name(form, field):
    if field.data == form.group.name:
        return

    return globally_unique_group_name(form, field)


def globally_unique_group_abbreviation(form, field):
    if ResearchGroup.query.filter_by(abbreviation=field.data).first():
        raise ValidationError(
            "{name} is already associated with an affiliation/research group".format(
                name=field.data
            )
        )


def unique_or_original_group_abbreviation(form, field):
    if field.data == form.group.abbreviation:
        return

    return globally_unique_group_abbreviation(form, field)


def globally_unique_degree_type(form, field):
    if DegreeType.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already associated with a degree type".format(name=field.data)
        )


def unique_or_original_degree_type(form, field):
    if field.data == form.degree_type.name:
        return

    return globally_unique_degree_type(form, field)


def globally_unique_degree_abbreviation(form, field):
    if DegreeType.query.filter_by(abbreviation=field.data).first():
        raise ValidationError(
            "{name} is already associated with a degree type".format(name=field.data)
        )


def unique_or_original_degree_abbreviation(form, field):
    if field.data == form.degree_type.abbreviation:
        return

    return globally_unique_degree_abbreviation(form, field)


def globally_unique_degree_programme(form, field):
    degree_type = form.degree_type.data
    if DegreeProgramme.query.filter_by(name=field.data, type_id=degree_type.id).first():
        raise ValidationError(
            "{name} is already associated with a degree programme of the same type".format(
                name=field.data
            )
        )


def unique_or_original_degree_programme(form, field):
    degree_type = form.degree_type.data
    if field.data == form.programme.name and degree_type.id == form.programme.type_id:
        return

    return globally_unique_degree_programme(form, field)


def globally_unique_course_code(form, field):
    if DegreeProgramme.query.filter_by(course_code=field.data).first():
        raise ValidationError(
            "{code} is already associated with a degree programme".format(
                code=field.data
            )
        )


def unique_or_original_course_code(form, field):
    if field.data == form.programme.course_code:
        return

    return globally_unique_course_code(form, field)


def globally_unique_programme_abbreviation(form, field):
    degree_type = form.degree_type.data
    if DegreeProgramme.query.filter_by(
        abbreviation=field.data, type_id=degree_type.id
    ).first():
        raise ValidationError(
            "{name} is already associated with a degree programme of the same type".format(
                name=field.data
            )
        )


def unique_or_original_programme_abbreviation(form, field):
    degree_type = form.degree_type.data
    if (
        field.data == form.programme.abbreviation
        and degree_type.id == form.programme.type_id
    ):
        return

    return globally_unique_programme_abbreviation(form, field)


def globally_unique_transferable_skill(form, field):
    if TransferableSkill.query.filter(
        TransferableSkill.name == field.data,
        TransferableSkill.group_id == form.group.data.id,
    ).first():
        raise ValidationError(
            "{name} is already in use for a transferable skill".format(name=field.data)
        )


def unique_or_original_transferable_skill(form, field):
    if field.data == form.skill.name:
        return

    return globally_unique_transferable_skill(form, field)


def globally_unique_skill_group(form, field):
    if SkillGroup.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already in use for a skill group".format(name=field.data)
        )


def unique_or_original_skill_group(form, field):
    if field.data == form.group.name:
        return

    return globally_unique_skill_group(form, field)


def globally_unique_project_tag_group(form, field):
    if db.session.query(ProjectTagGroup).filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already in use for a project tag group".format(name=field.data)
        )


def unique_or_original_project_tag_group(form, field):
    if field.data == form.group.name:
        return

    return globally_unique_project_tag_group(form, field)


def globally_unique_project_tag(form, field):
    if form.group.data is None:
        raise ValidationError(
            "Cannot validate project tag name without specifying a tag group. Please select a project tag group"
        )

    check_exists = (
        db.session.query(ProjectTag)
        .join(ProjectTagGroup, ProjectTag.group_id == ProjectTagGroup.id)
        .filter(
            ProjectTag.name == field.data,
            ProjectTagGroup.name == form.group.data.name,
        )
        .first()
    )

    if check_exists is not None:
        raise ValidationError(
            f'"{field.data}" is already in use for a project tag in group "{form.group.data.name}"'
        )


def unique_or_original_project_tag(form, field):
    if field.data == form.tag.name:
        return

    return globally_unique_project_tag(form, field)


def globally_unique_project_class(form, field):
    if ProjectClass.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already associated with a project class".format(name=field.data)
        )


def unique_or_original_project_class(form, field):
    if field.data == form.project_class.name:
        return

    return globally_unique_project_class(form, field)


def globally_unique_project_class_abbrev(form, field):
    if ProjectClass.query.filter_by(abbreviation=field.data).first():
        raise ValidationError(
            "{name} is already in use as an abbreviation".format(name=field.data)
        )


def unique_or_original_project_class_abbrev(form, field):
    if field.data == form.project_class.abbreviation:
        return

    return globally_unique_project_class_abbrev(form, field)


def globally_unique_supervisor(form, field):
    if Supervisor.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already associated with a supervisory role".format(
                name=field.data
            )
        )


def unique_or_original_supervisor(form, field):
    if field.data == form.supervisor.name:
        return

    return globally_unique_supervisor(form, field)


def globally_unique_supervisor_abbrev(form, field):
    if Supervisor.query.filter_by(abbreviation=field.data).first():
        raise ValidationError(
            "{name} is already in use as an abbreviation".format(name=field.data)
        )


def unique_or_original_supervisor_abbrev(form, field):
    if field.data == form.supervisor.abbreviation:
        return

    return globally_unique_supervisor_abbrev(form, field)


def globally_unique_role(form, field):
    if Role.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already associated with a user role".format(name=field.data)
        )


def unique_or_original_role(form, field):
    if field.data == form.role.name:
        return

    return globally_unique_role(form, field)


def globally_unique_registration_number(form, field):
    rec = StudentData.query.filter_by(registration_number=field.data).first()
    if rec is not None:
        raise ValidationError(
            "Registration number {n} is already associated with student {name}".format(
                n=rec.registration_number, name=rec.user.name
            )
        )


def unique_or_original_registration_number(form, field):
    if field.data == form.user.student_data.registration_number:
        return

    return globally_unique_registration_number(form, field)


def globally_unique_matching_name(year, form, field):
    if MatchingAttempt.query.filter_by(name=field.data, year=year).first():
        raise ValidationError(
            "{name} is already in use for a matching attempt this year".format(
                name=field.data
            )
        )


def unique_or_original_matching_name(year, form, field):
    if field.data == form.record.name:
        return

    return globally_unique_matching_name(year, form, field)


def globally_unique_project(form, field):
    if Project.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already associated with a project".format(name=field.data)
        )


def unique_or_original_project(form, field):
    if field.data == form.project.name:
        return

    return globally_unique_project(form, field)


def project_unique_label(form, field):
    if ProjectDescription.query.filter_by(
        parent_id=form.project_id, label=field.data
    ).first():
        raise ValidationError(
            "{name} is already used as a label for this project".format(name=field.data)
        )


def project_unique_or_original_label(form, field):
    if field.data == form.desc.label:
        return

    return project_unique_label(form, field)


def value_is_nonnegative(form, field):
    if field.data < 0:
        raise ValidationError("Please enter a non-negative value")


def globally_unique_assessment_name(year, form, field):
    if PresentationAssessment.query.filter_by(name=field.data, year=year).first():
        raise ValidationError(
            "{name} is already in use as an assessment name for this year".format(
                name=field.data
            )
        )


def unique_or_original_assessment_name(year, form, field):
    if field.data == form.assessment.name:
        return

    return globally_unique_assessment_name(year, form, field)


def globally_unique_building_name(form, field):
    if Building.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already in use as a building name".format(name=field.data)
        )


def unique_or_original_building_name(form, field):
    if field.data == form.building.name:
        return

    return globally_unique_building_name(form, field)


def globally_unique_room_name(form, field):
    if Room.query.filter_by(name=field.data, building_id=form.building.data.id).first():
        raise ValidationError(
            "{building} {name} is already in use as a room name".format(
                building=form.building.data.name, name=field.data
            )
        )


def unique_or_original_room_name(form, field):
    if field.data == form.room.name and form.building.data.id == form.room.building.id:
        return

    return globally_unique_room_name(form, field)


def globally_unique_schedule_name(assessment_id, form, field):
    if ScheduleAttempt.query.filter_by(owner_id=assessment_id, name=field.data).first():
        raise ValidationError(
            "{name} is already in use for a schedule attached to this assessment".format(
                name=field.data
            )
        )


def unique_or_original_schedule_name(assessment_id, form, field):
    if field.data == form.schedule.name:
        return

    return globally_unique_schedule_name(assessment_id, form, field)


def globally_unique_schedule_tag(form, field):
    if ScheduleAttempt.query.filter_by(tag=field.data).first():
        raise ValidationError(
            "{tag} is already in use for a schedule tag".format(tag=field.data)
        )


def unique_or_original_schedule_tag(form, field):
    if field.data == form.schedule.tag:
        return

    return globally_unique_schedule_tag(form, field)


def globally_unique_module_code(form, field):
    if Module.query.filter_by(code=field.data).first():
        raise ValidationError(
            "{name} is already in use as a module code".format(name=field.data)
        )


def unique_or_original_module_code(form, field):
    if field.data == form.module.code:
        return

    return globally_unique_module_code(form, field)


def globally_unique_FHEQ_level_name(form, field):
    if FHEQ_Level.query.filter_by(name=field.data).first():
        raise ValidationError(
            "{name} is already defined as a FHEQ Level name".format(name=field.data)
        )


def unique_or_original_FHEQ_level_name(form, field):
    if field.data == form.level.name:
        return

    return globally_unique_FHEQ_level_name(form, field)


def globally_unique_FHEQ_short_name(form, field):
    if FHEQ_Level.query.filter_by(short_name=field.data).first():
        raise ValidationError(
            "{name} is already defined as a FHEQ short name".format(name=field.data)
        )


def unique_or_original_FHEQ_short_name(form, field):
    if field.data == form.level.short_name:
        return

    return globally_unique_FHEQ_short_name(form, field)


def globally_unique_FHEQ_numeric_level(form, field):
    if FHEQ_Level.query.filter_by(numeric_level=field.data).first():
        raise ValidationError(
            "Numeric level #{n} is already in use for a FHEQ level".format(n=field.data)
        )


def unique_or_original_FHEQ_numeric_level(form, field):
    if field.data == form.level.numeric_level:
        return

    return globally_unique_FHEQ_numeric_level(form, field)


def globally_unique_license_name(form, field):
    if AssetLicense.query.filter_by(name=field.data).first():
        raise ValidationError(
            'A license with the name "{name}" already exists'.format(name=field.data)
        )


def unique_or_original_license_name(form, field):
    if field.data == form.license.name:
        return

    return globally_unique_license_name(form, field)


def globally_unique_license_abbreviation(form, field):
    if AssetLicense.query.filter_by(abbreviation=field.data).first():
        raise ValidationError(
            'A license with the abbreviation "{abbv}" already exists'.format(
                abbv=field.data
            )
        )


def unique_or_original_license_abbreviation(form, field):
    if field.data == form.license.abbreviation:
        return

    return globally_unique_license_abbreviation(form, field)


def per_license_unique_version(form, field):
    name = form.name.data
    if AssetLicense.query.filter_by(name=name, version=form.version.data).first():
        raise ValidationError(
            'A license of type "{name}" with version "{ver}" already exists'.form(
                name=name, ver=form.version.data
            )
        )


def per_license_unique_or_original_version(form, field):
    if field.data == form.license.version and form.name.data == form.license.name:
        return

    return per_license_unique_version(form, field)


def globally_unique_batch_item_userid(batch_id, form, field):
    if StudentBatchItem.query.filter_by(parent_id=batch_id, user_id=field.data).first():
        raise ValidationError(
            "{name} is already in use as a user id for this batch import".format(
                name=field.data
            )
        )


def unique_or_original_batch_item_userid(batch_id, form, field):
    if field.data == form.batch_item.user_id:
        return

    return globally_unique_batch_item_userid(batch_id, form, field)


def globally_unique_batch_item_email(batch_id, form, field):
    if StudentBatchItem.query.filter_by(parent_id=batch_id, email=field.data).first():
        raise ValidationError(
            "{name} is already in use as an email address for this batch import".format(
                name=field.data
            )
        )


def unique_or_original_batch_item_email(batch_id, form, field):
    if field.data == form.batch_item.email:
        return

    return globally_unique_batch_item_email(batch_id, form, field)


def globally_unique_batch_item_exam_number(batch_id, form, field):
    if StudentBatchItem.query.filter_by(
        parent_id=batch_id, exam_number=field.data
    ).first():
        raise ValidationError(
            "{name} is already in use as an exam number for this batch import".format(
                name=field.data
            )
        )


def unique_or_original_batch_item_exam_number(batch_id, form, field):
    if field.data == form.batch_item.exam_number:
        return

    return globally_unique_batch_item_exam_number(batch_id, form, field)


def globally_unique_batch_item_registration_number(batch_id, form, field):
    if StudentBatchItem.query.filter_by(
        parent_id=batch_id, registration_number=field.data
    ).first():
        return ValidationError(
            "{name} is already used as a registration number for this batch import".format(
                name=field.data
            )
        )


def unique_or_original_batch_item_registration_number(batch_id, form, field):
    if field.data == form.batch_item.registration_number:
        return

    return globally_unique_batch_item_registration_number(batch_id, form, field)


def globally_unique_faculty_batch_item_userid(batch_id, form, field):
    if FacultyBatchItem.query.filter_by(parent_id=batch_id, user_id=field.data).first():
        raise ValidationError(
            "{name} is already in use as a user id for this batch import".format(
                name=field.data
            )
        )


def unique_or_original_faculty_batch_item_userid(batch_id, form, field):
    if field.data == form.batch_item.user_id:
        return

    return globally_unique_faculty_batch_item_userid(batch_id, form, field)


def globally_unique_faculty_batch_item_email(batch_id, form, field):
    if FacultyBatchItem.query.filter_by(parent_id=batch_id, email=field.data).first():
        raise ValidationError(
            "{name} is already in use as an email address for this batch import".format(
                name=field.data
            )
        )


def unique_or_original_faculty_batch_item_email(batch_id, form, field):
    if field.data == form.batch_item.email:
        return

    return globally_unique_faculty_batch_item_email(batch_id, form, field)


def globally_unique_feedback_asset_label(form, field):
    if FeedbackAsset.query.filter_by(label=field.data).first():
        raise ValidationError(
            'A feedback asset with the label "{label}" already exists'.format(
                label=field.data
            )
        )


def unique_or_original_feedback_asset_label(form, field):
    if field.data == form.asset.label:
        return

    return globally_unique_feedback_asset_label(form, field)


def globally_unique_feedback_recipe_label(form, field):
    if FeedbackRecipe.query.filter_by(label=field.data).first():
        raise ValidationError(
            'A feedback recipe with the label "{label}" already exists'.format(
                label=field.data
            )
        )


def unique_or_original_feedback_recipe_label(form, field):
    if field.data == form.recipe.label:
        return

    return globally_unique_feedback_recipe_label(form, field)


def globally_unique_submission_unit(period_id, form, field):
    if (
        db.session.query(SubmissionPeriodUnit)
        .filter(
            SubmissionPeriodUnit.owner_id == period_id,
            SubmissionPeriodUnit.name == field.data,
        )
        .first()
    ):
        raise ValidationError(
            f'A submission period unit with the name "{field.data}" already exists for this period'
        )


def unique_or_original_submission_unit(period_id, form, field):
    if field.data == form.unit.name:
        return

    return globally_unique_submission_unit(period_id, form, field)


def globally_unique_supervision_event_template(unit_id, form, field):
    if (
        db.session.query(SupervisionEventTemplate)
        .filter(
            SupervisionEventTemplate.unit_id == unit_id,
            SupervisionEventTemplate.name == field.data,
        )
        .first()
    ):
        raise ValidationError(
            f'A supervision event template with the name "{field.data}" already exists for this unit'
        )


def unique_or_original_supervision_event_template(unit_id, form, field):
    if field.data == form.template.name:
        return

    return globally_unique_supervision_event_template(unit_id, form, field)


def make_unique_marking_event_in_period(period_id, name=None):
    """
    Return a WTForms validator that checks MarkingEvent.name is unique within a
    SubmissionPeriodRecord. If event is provided, the event's own current name is
    allowed (edit case).
    """

    def validator(form, field):
        if name is not None and field.data == name:
            return
        existing = (
            db.session.query(MarkingEvent)
            .filter(
                MarkingEvent.period_id == period_id, MarkingEvent.name == field.data
            )
            .first()
        )
        if existing is not None:
            raise ValidationError(
                f'"{field.data}" is already used for a marking event in this submission period'
            )

    return validator


def make_unique_marking_workflow_in_event(event_id, name=None):
    """
    Return a WTForms validator that checks MarkingWorkflow.name is unique within a
    MarkingEvent. If workflow is provided, the workflow's own current name is
    allowed (edit case).
    """

    def validator(form, field):
        if name is not None and field.data == name:
            return
        existing = (
            db.session.query(MarkingWorkflow)
            .filter(
                MarkingWorkflow.event_id == event_id, MarkingWorkflow.name == field.data
            )
            .first()
        )
        if existing is not None:
            raise ValidationError(
                f'"{field.data}" is already used for a marking workflow in this event'
            )

    return validator


def make_unique_marking_workflow_key_in_event(event_id, key=None):
    """
    Return a WTForms validator that checks MarkingWorkflow.key is unique within a
    MarkingEvent. If workflow is provided, the workflow's own current key is
    allowed (edit case).
    """

    def validator(form, field):
        if key is not None and field.data == key:
            return
        existing = (
            db.session.query(MarkingWorkflow)
            .filter(
                MarkingWorkflow.event_id == event_id, MarkingWorkflow.key == field.data
            )
            .first()
        )
        if existing is not None:
            raise ValidationError(
                f'"{field.data}" is already used as a key for a marking workflow in this event'
            )

    return validator


def make_unique_marking_scheme_in_pclass(pclass_id, name=None):
    """
    Return a WTForms validator that checks MarkingScheme.name is unique within a
    ProjectClass. If name is provided (edit case), the scheme's own current name is allowed.
    """

    def validator(form, field):
        if name is not None and field.data == name:
            return
        existing = (
            db.session.query(MarkingScheme)
            .filter(
                MarkingScheme.pclass_id == pclass_id, MarkingScheme.name == field.data
            )
            .first()
        )
        if existing is not None:
            raise ValidationError(
                f'"{field.data}" is already used as a marking scheme name in this project class'
            )

    return validator


def valid_json(form, field):
    try:
        json_obj = json.loads(field.data)
    except TypeError:
        raise ValidationError("Unexpected text encoding")
    except json.JSONDecodeError:
        raise ValidationError("Could not translate to a valid JSON object")


def valid_python_identifier(form, field):
    """WTForms validator: checks that field.data is a valid Python identifier."""
    if not field.data or not field.data.isidentifier():
        raise ValidationError(f'"{field.data}" is not a valid Python identifier')


_VALID_MARKING_FIELD_TYPES = {"boolean", "text", "number", "percent"}
_VALID_VALIDATION_ACTIONS = {"prevent_submit", "email", "web"}

_FIDUCIAL_VALUES = {
    "boolean": True,
    "number": 1.0,
    "percent": 1.0,
    "text": "test",
}

# Safe builtins exposed to eval() when checking marking-scheme expressions
_SAFE_BUILTINS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "len": len,
    "sum": sum,
}


class SchemaValidationError(Exception):
    """Raised by parse_schema() when schema fails structural or expression validation."""

    pass


def parse_schema(data) -> dict:
    """
    Validate the structure of a deserialized marking scheme schema.
    `data` should be a Python object obtained from json.loads().
    Returns the validated schema dict on success, or raises SchemaValidationError.

    Expected layout: a dict with:
        "scheme": list of section blocks (required), each block a dict with:
            "title": str (required)
            "description": str (optional)
            "fields": list of dicts (required), each with:
                "key": str (required)
                "text": str (required)
                "field_type": dict (required) with:
                    "type" in {"boolean", "text", "number", "percent"} (required)
                    "min", "max": optional, used with number type
                    "precision": optional, used with number type
                    "rows": optional, used with text type, specifies initial number of rows to display in text area
                    "default": optional
        "conflation_rule": str (required, valid Python expression returning a number)
        "validation": list of dicts (optional), each with:
            "test": str (required, valid Python expression returning a bool)
            "action": list of strings from {"prevent_submit", "email", "web"}
                      ("prevent_submit" must be the only action if present)
    """
    if not isinstance(data, dict):
        raise SchemaValidationError("Schema must be a JSON object")

    # "conflation_rule" is required and must be a string
    if not isinstance(data.get("conflation_rule"), str):
        raise SchemaValidationError(
            "'conflation_rule' is required and must be a string"
        )

    # "scheme" is required and must be a list of section blocks
    scheme = data.get("scheme")
    if not isinstance(scheme, list):
        raise SchemaValidationError(
            "'scheme' is required and must be a list of section blocks"
        )

    # Pass 1: structural validation; build fiducial value dictionary
    fiducial: dict = {}

    for block_idx, block in enumerate(scheme):
        if not isinstance(block, dict):
            raise SchemaValidationError(
                f"Section block {block_idx} must be a JSON object"
            )
        if not isinstance(block.get("title"), str):
            raise SchemaValidationError(
                f"Section block {block_idx} is missing a 'title' string"
            )

        # Optional description
        description = block.get("description")
        if description is not None and not isinstance(description, str):
            raise SchemaValidationError(
                f"Section block {block_idx}: 'description' must be a string"
            )

        # Required fields list
        fields = block.get("fields")
        if not isinstance(fields, list):
            raise SchemaValidationError(
                f"Section block {block_idx} ('{block.get('title')}'): 'fields' must be a list"
            )
        for field_idx, field in enumerate(fields):
            if not isinstance(field, dict):
                raise SchemaValidationError(
                    f"Section block {block_idx}, field {field_idx}: must be a JSON object"
                )
            key = field.get("key")
            if not isinstance(key, str):
                raise SchemaValidationError(
                    f"Section block {block_idx}, field {field_idx}: 'key' must be a string"
                )
            if not key.isidentifier():
                raise SchemaValidationError(
                    f"Section block {block_idx}, field {field_idx}: key '{key}' is not a valid Python identifier"
                )
            if key in fiducial:
                raise SchemaValidationError(f"Duplicate field key '{key}'")
            if not isinstance(field.get("text"), str):
                raise SchemaValidationError(
                    f"Section block {block_idx}, field '{key}': 'text' must be a string"
                )
            ft = field.get("field_type")
            if not isinstance(ft, dict):
                raise SchemaValidationError(
                    f"Section block {block_idx}, field '{key}': 'field_type' must be a JSON object"
                )
            field_type_name = ft.get("type")
            if field_type_name not in _VALID_MARKING_FIELD_TYPES:
                raise SchemaValidationError(
                    f"Section block {block_idx}, field '{key}': field type '{field_type_name}' is not valid; "
                    f"must be one of {sorted(_VALID_MARKING_FIELD_TYPES)}"
                )
            fiducial[key] = _FIDUCIAL_VALUES[field_type_name]

    # Optional top-level validation list — structural check only in pass 1
    validation = data.get("validation")
    if validation is not None:
        if not isinstance(validation, list):
            raise SchemaValidationError("'validation' must be a list")
        for item_idx, test_item in enumerate(validation):
            if not isinstance(test_item, dict):
                raise SchemaValidationError(
                    f"Validation item {item_idx} must be a JSON object"
                )
            if not isinstance(test_item.get("test"), str):
                raise SchemaValidationError(
                    f"Validation item {item_idx}: 'test' must be a string"
                )
            action = test_item.get("action")
            if not isinstance(action, list):
                raise SchemaValidationError(
                    f"Validation item {item_idx}: 'action' must be a list"
                )
            if not all(a in _VALID_VALIDATION_ACTIONS for a in action):
                invalid = [a for a in action if a not in _VALID_VALIDATION_ACTIONS]
                raise SchemaValidationError(
                    f"Validation item {item_idx}: unknown action(s) {invalid}; "
                    f"must be from {sorted(_VALID_VALIDATION_ACTIONS)}"
                )
            # "prevent_submit" must be the only action if present
            if "prevent_submit" in action and len(action) != 1:
                raise SchemaValidationError(
                    f"Validation item {item_idx}: 'prevent_submit' cannot be combined with other actions"
                )

    # Pass 2: expression evaluation using fiducial values
    eval_ns = {"__builtins__": _SAFE_BUILTINS} | fiducial

    try:
        result = eval(data["conflation_rule"], eval_ns)
    except Exception as exc:
        raise SchemaValidationError(
            f"'conflation_rule' raised an error during evaluation: {exc}"
        )
    if not isinstance(result, (int, float)):
        raise SchemaValidationError(
            f"'conflation_rule' must evaluate to a number, but got {type(result).__name__}"
        )

    if validation is not None:
        for item_idx, test_item in enumerate(validation):
            try:
                result = eval(test_item["test"], eval_ns)
            except Exception as exc:
                raise SchemaValidationError(
                    f"Validation item {item_idx} 'test' expression raised an error during evaluation: {exc}"
                )
            if not isinstance(result, bool):
                raise SchemaValidationError(
                    f"Validation item {item_idx} 'test' expression must evaluate to a bool, "
                    f"but got {type(result).__name__}"
                )

    return data


def valid_marking_schema(form, field):
    """WTForms validator: checks that the field contains valid JSON conforming to the marking schema layout."""
    try:
        data = json.loads(field.data)
    except TypeError:
        raise ValidationError("Unexpected text encoding in schema")
    except json.JSONDecodeError:
        raise ValidationError("Schema is not valid JSON")

    try:
        parse_schema(data)
    except SchemaValidationError as exc:
        raise ValidationError(str(exc))


def parse_targets(data, fiducial) -> dict:
    """
    Validate the structure of a deserialized targets dict.
    `data` should be a Python object obtained from json.loads().
    Returns the validated targets dict on success, or raises SchemaValidationError.

    Expected layout: a dict where:
        - each key is a string and a valid Python identifier
        - each value is a string containing a syntactically valid Python expression
    """
    if not isinstance(data, dict):
        raise SchemaValidationError("targets must be a JSON object (dict)")

    eval_ns = {"__builtins__": _SAFE_BUILTINS} | fiducial

    for target, conflation_rule in data.items():
        if not isinstance(target, str) or not target.isidentifier():
            raise SchemaValidationError(
                f"Target key {target!r} must be a valid Python identifier"
            )
        if not isinstance(conflation_rule, str):
            raise SchemaValidationError(
                f"Target value for key {target!r} must be a string expression"
            )

        try:
            result = eval(conflation_rule, eval_ns)
        except Exception as exc:
            raise SchemaValidationError(
                f"Target expression for key {target!r} raised an error during evaluation: {exc}"
            )
        if not isinstance(result, (int, float)):
            raise SchemaValidationError(
                f"Target expression for key {target!r} must evaluate to a float, but got {type(result).__name__}"
            )

    return data


def make_valid_marking_targets(fiducial):

    def valid_marking_targets(form, field):
        """WTForms validator: checks that the field contains valid JSON conforming to the targets layout."""
        if not field.data:
            return
        try:
            data = json.loads(field.data)
        except TypeError:
            raise ValidationError("Unexpected text encoding in targets")
        except json.JSONDecodeError:
            raise ValidationError("Targets field is not valid JSON")

        try:
            parse_targets(data, fiducial)
        except SchemaValidationError as exc:
            raise ValidationError(str(exc))

    return valid_marking_targets


def password_strength(form, field):
    username = form.username.data or ""
    first_name = form.first_name.data or ""
    last_name = form.last_name.data or ""

    proposed_password = field.data

    length_msgs = password_length_validator(proposed_password)
    complexity_msgs = password_complexity_validator(
        proposed_password,
        is_register=True,
        username=username,
        first_name=first_name,
        last_name=last_name,
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
