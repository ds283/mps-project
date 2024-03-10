#
# Created by David Seery on 02/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import Optional, List

from flask import flash
from flask_login import current_user
from sqlalchemy import and_

from .context.assessments import get_assessment_data
from .utils import get_current_year
from ..database import db
from ..models import ProjectClassConfig, SubmittingStudent, SubmissionRecord, SubmissionRole, ProjectClass
from ..shared.utils import get_count


def validate_is_administrator(message=True):
    """
    Ensure that user in an administrator
    :return:
    """

    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if message:
            flash("This action is available only to administrative users.", "error")
        return False

    return True


def validate_is_convenor(pclass: ProjectClass, message: bool = True, allow_roles: Optional[List[str]] = None):
    """
    Validate that the logged-in user is privileged to view a convenor dashboard or use other convenor functions
    :param pclass: Project class model instance
    :return: True/False
    """
    # any user with an admin role is OK
    if current_user.has_role("admin") or current_user.has_role("root"):
        return True

    # convenor for this pclass is ok
    if pclass.is_convenor(current_user.id):
        return True

    # if the current user has any of the specified roles, that is ok
    if allow_roles is not None:
        for role in allow_roles:
            if current_user.has_role(role):
                return True

    if message:
        flash("This action is available only to project convenors and administrative users.", "error")

    return False


def validate_is_admin_or_convenor(*roles):
    """
    Validate that the logged-in user is an administrator or is a convenor for any project class
    :return:
    """
    # any user with an admin role is ok
    if current_user.has_role("admin") or current_user.has_role("root"):
        return True

    # faculty users who are also convenors are ok
    if current_user.has_role("faculty") and current_user.faculty_data.is_convenor:
        return True

    # otherwise, check whether this user has any role in the supplied list of roles
    for role in roles:
        if current_user.has_role(role):
            return True

    flash("This action is available only to project convenors and administrative users.", "error")
    return False


def validate_view_project(project, *roles):
    """
    Validate that the logged-in user is privileged to view a particular project
    :param project: Project model instance
    :return: True/False
    """
    # if project owner is currently logged-in user
    if project.owner_id == current_user.id:
        return True

    # admin and root users can always edit everything
    if current_user.has_role("admin") or current_user.has_role("root"):
        return True

    # if the currently logged-in user has any of the specified roles
    for role in roles:
        if current_user.has_role(role):
            return True

    # if the current user is a convenor for any of the pclasses to which we're attached]
    if any([item.is_convenor(current_user.id) for item in project.project_classes]):
        return True

    # if the current user has a faculty or office role, allow view
    if current_user.has_role("faculty") or current_user.has_role("office"):
        return True

    # if current user has an approval role, allow view
    if current_user.has_role("project_approver"):
        return True

    # if current user has an exam-board related role, allow view
    if current_user.has_role("exam_board") or current_user.has_role("external_examiner") or current_user.has_role("moderator"):
        return True

    flash("This project belongs to another user. To view it, you must be a suitable convenor or an administrator.")
    return False


def validate_edit_project(project, *roles):
    """
    Validate that the logged-in user is privileged to edit a particular project
    :param project: Project model instance
    :return: True/False
    """
    # if project owner is currently logged-in user, all is ok
    if project.owner_id == current_user.id:
        return True

    # admin and root users can always edit everything
    if current_user.has_role("admin") or current_user.has_role("root"):
        return True

    # if the currently logged-in user has any of the specified roles, allow edit
    for role in roles:
        if current_user.has_role(role):
            return True

    # if the current user is a convenor for any of the pclasses to which we're attached, allow edit
    if any([item.is_convenor(current_user.id) for item in project.project_classes]):
        return True

    flash("This project belongs to another user. To edit it, you must be a suitable convenor or an administrator.")
    return False


def validate_edit_description(description, *roles):
    """
    Validate that the logged-in user is privileged to edit a particular project description
    """
    # get parent project
    project = description.parent

    # if project owner is currently logged-in user, all is ok
    if project.owner_id is not None and project.owner_id == current_user.id:
        return True

    # admin and root users can always edit everything
    if current_user.has_role("admin") or current_user.has_role("root"):
        return True

    # if the currently logged-in user has any of the specified roles, allow edit
    for role in roles:
        if current_user.has_role(role):
            return True

    # if the current user is a convenor for any of the pclasses to which we're attached, allow edit
    if any([item.is_convenor(current_user.id) for item in description.project_classes]):
        return True

    flash("This project description belongs to another user. To edit it, you must be a suitable convenor or an administrator.")
    return False


def validate_project_open(config):
    """
    Validate that a particular ProjectClassConfig is open for student selections
    :param config:
    :return:
    """
    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash("{name} is not open for student selections.".format(name=config.name), "error")
        return False

    return True


def validate_project_class(pclass):
    """
    Validate that a project class is editable/usable
    :param pclass:
    :return:
    """
    if not pclass.publish:
        flash("'{name}' is not published and is not available for certain lifecycle events.".format(name=pclass.name))
        return False

    return True


def validate_is_project_owner(project):
    """
    Validate that the logged-in user is the project owner
    :param project:
    :return:
    """
    if project.owner_id == current_user.id:
        return True

    flash("This operation is available only to the project owner.", "error")
    return False


def validate_match_inspector(record):
    """
    Validate that the logged-in user is entitled to view the match inspector for a given matching attempt
    :param record:
    :return:
    """
    if current_user.has_role("root") or current_user.has_role("admin"):
        return True

    if current_user.has_role("faculty"):
        if record.published:
            for pclass in record.available_pclasses:
                if pclass.is_convenor(current_user.id):
                    return True

        else:
            flash("The match owner has not yet made this match available to project convenors.", "info")
            return False

    flash("This operation is available only to administrative users and project convenors.", "error")
    return False


def validate_submission_role(role: SubmissionRole, allow_roles=None):
    """
    Validate that the logged-in user has an allowed role associated with this SubmissionRole instance
    :param role:
    :return:
    """
    if role.user_id != current_user.id:
        flash("This operation is not permitted. Your login credentials do not match those of the provided role.", "error")
        return False

    role_map = {"supervisor": SubmissionRole.ROLE_SUPERVISOR, "marker": SubmissionRole.ROLE_MARKER, "moderator": SubmissionRole.ROLE_MODERATOR}

    for r in allow_roles:
        r = r.lower()

        if r in role_map:
            if role.role == role_map[r]:
                return True

    flash(
        "This operation is not permitted because your role associated with this submission does not confer "
        "the necessary privileges. If you think this is an error, please contact a system "
        "administrator",
        "warning",
    )
    return False


def validate_submission_supervisor(record):
    """
    Validate that the logged-in user is the project supervisor for a SubmissionRecord instance
    :param record:
    :return:
    """

    if record.project.owner_id == current_user.id:
        return True

    flash("Only project supervisors can perform this operation", "error")
    return False


def validate_submission_marker(record):
    """
    Validate that the logged-in user is the assigned marker for a SubmissionRecord instance
    :param record:
    :return:
    """
    if record.marker_id == current_user.id:
        return True

    flash("Only markers can perform this operation", "error")
    return False


def validate_submission_viewable(record: SubmissionRecord, message: bool = True):
    """
    Validate that the logged-in user is entitled to view a SubmissionRecord instance, usually because they
    have a role associated with it
    :param record:
    :return:
    """
    role: SubmissionRole = record.get_role(current_user.id)

    # if the current user has an assigned role for this submission record, they can view the submission
    if role is not None:
        return True

    # if a project has been specified and the current user is the owner of the project, then they are able
    # to view the submission
    if record.project is not None and not record.project.generic and record.project.owner_id is not None:
        if current_user.id == record.project.owner_id:
            return True

    # project convenors, root/admin users, and users with exam board privileges can always view
    if current_user.allow_roles(["convenor", "admin", "root", "exam_board", "external_examiner"]):
        return True

    # if this submission period has a presentation, and the logged-in user is one of the specified
    # assessors for the presentation, then it is possible to view
    if record.period.has_presentation:
        slot = record.schedule_slot
        if slot is not None:
            count = get_count(slot.assessors.filter_by(id=current_user.id))
            if count > 0:
                return True

    # if the logged-in user has a supervisor role on one of this student's currently active projects,
    # then they are able to view
    owner_query = (
        db.session.query(SubmissionRecord.id)
        .filter(SubmissionRecord.retired == False)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .filter(SubmittingStudent.student_id == record.owner.student_id)
        .filter(SubmissionRecord.roles.any(and_(SubmissionRole.user_id == current_user.id, SubmissionRole.role == SubmissionRole.ROLE_SUPERVISOR)))
    )

    if get_count(owner_query) > 0:
        return True

    if message:
        flash(
            "This operation is not permitted. You do not have sufficient privileges to view details "
            "of the specified submission record. If you think this is an error, please contact "
            "a system administrator.",
            "warning",
        )
    return False


def validate_using_assessment():
    # check that assessment events are actually required
    data = get_assessment_data()

    if not data["has_assessments"]:
        flash("Presentation assessments are not currently required", "error")
        return False

    return True


def validate_assessment(data, current_year=None):
    if current_year is None:
        current_year = get_current_year()

    if data.year != current_year:
        flash("Cannot edit presentation assessment {name} because it does not belong to the current year".format(name=data.name), "info")
        return False

    return True


def validate_schedule_inspector(record):
    """
    Validate that the logged-in user is entitled to view the schedule inspector for a given scheduling attempt
    :param record:
    :return:
    """
    if current_user.has_role("root") or current_user.has_role("admin"):
        return True

    if current_user.has_role("faculty"):
        if record.published:
            for pclass in record.available_pclasses:
                if pclass.is_convenor(current_user.id):
                    return True

        else:
            flash("The schedule owner has not yet made this match available to project convenors.", "info")
            return False

    flash("This operation is available only to administrative users and project convenors.", "error")
    return False


def validate_presentation_assessor(record):
    """
    Validate that the logged-in user is entitled to provide feedback on a presentation
    :param record:
    :return:
    """
    if get_count(record.assessors.filter_by(id=current_user.id)) > 0:
        return True

    flash("Only presentation assessors can provide feedback on a presentation assessment", "error")
    return False


def validate_assign_feedback(talk):
    """
    Validate that a given talk is marked as 'not attending' for the assessment deployed for its
    SubmissionPeriodRecord
    :param talk:
    :return:
    """
    if not talk.period.has_presentation:
        flash(
            "Cannot assign feedback to this submission record because it does not belong to a "
            "submission period that has presentation assessments.",
            "info",
        )
        return False

    if not talk.period.has_deployed_schedule:
        flash("Cannot assign feedback to this submission record because its submission period does not yet have a deployed schedule.", "info")
        return False

    if not talk.can_assign_feedback:
        flash("It is not possible to assign further feedback to this record.", "error")
        return False

    return True
