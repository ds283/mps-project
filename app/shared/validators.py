#
# Created by David Seery on 02/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import flash
from flask_login import current_user

from .utils import get_current_year, get_assessment_data
from ..shared.utils import get_count
from ..models import ProjectClassConfig


def validate_is_administrator():
    """
    Ensure that user in an administrator
    :return:
    """

    if not current_user.has_role('admin') and not current_user.has_role('root'):

        flash('Only administrative users can perform this operation.')
        return False

    return True


def validate_is_convenor(pclass):
    """
    Validate that the logged-in user is privileged to view a convenor dashboard or use other convenor functions
    :param pclass: Project class model instance
    :return: True/False
    """

    # if logged in user is convenor for this class, or is an admin user, then all is OK
    if not pclass.is_convenor(current_user.id) \
            and not current_user.has_role('admin') \
            and not current_user.has_role('root'):

        flash('Convenor actions are available only to project convenors and administrative users.')
        return False

    return True


def validate_edit_project(project):
    """
    Validate that the logged-in user is privileged to edit a particular project
    :param project: Project model instance
    :return: True/False
    """

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if project.owner_id != current_user.id \
            and not current_user.has_role('admin') \
            and not current_user.has_role('root') \
            and not any([item.is_convenor(current_user.id) for item in project.project_classes]):

        flash('This project belongs to another user. To edit it, you must be a suitable convenor or an administrator.')
        return False

    return True


def validate_project_open(config):
    """
    Validate that a particular ProjectClassConfig is open for student selections
    :param config:
    :return:
    """

    if config.selector_lifecycle != ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:

        flash('{name} is not open for student selections.'.format(name=config.name), 'error')

        return False

    return True


def validate_is_admin_or_convenor():
    """
    Validate that the logged-in user is an administrator or is a convenor for any project class
    :return:
    """

    # any user with an admin role is ok
    if current_user.has_role('admin') or current_user.has_role('root'):
        return True

    # faculty users who are also convenors are ok
    if current_user.has_role('faculty') and current_user.faculty_data.is_convenor:
        return True

    flash('This operation is available only to administrative users and project convenors.', 'error')
    return False


def validate_is_project_owner(project):
    """
    Validate that the logged-in user is the project owner
    :param project:
    :return:
    """

    if project.owner_id == current_user.id:
        return True

    flash('This operation is available only to the project owner.', 'error')
    return False


def validate_match_inspector(record):
    """
    Validate that the logged-in user is entitled to view the match inspector for a given matching attempt
    :param record:
    :return:
    """
    if current_user.has_role('root') or current_user.has_role('admin'):
        return True

    if current_user.has_role('faculty'):
        if record.published:
            for pclass in record.available_pclasses:
                if pclass.is_convenor(current_user.id):
                    return True

        else:
            flash('The match owner has not yet made this match available to project convenors.', 'info')
            return False

    flash('This operation is available only to administrative users and project convenors.', 'error')
    return False


def validate_submission_supervisor(record):
    """
    Validate that the logged-in user is the project supervisor for a SubmissionRecord instance
    :param record:
    :return:
    """

    if record.project.owner_id == current_user.id:
        return True

    flash('Only project supervisors can perform this operation', 'error')
    return False


def validate_submission_marker(record):
    """
    Validate that the logged-in user is the assigned marker for a SubmissionRecord instance
    :param record:
    :return:
    """

    if record.marker_id == current_user.id:
        return True

    flash('Only 2nd markers can perform this operation', 'error')
    return False


def validate_submission_viewable(record):
    """
    Validate that the logged-in user is entitled to view a SubmissionRecord instance
    :param record:
    :return:
    """

    if record.project.owner_id == current_user.id or record.marker_id == current_user.id:
        return True

    if record.period.has_presentation:
        slot = record.schedule_slot
        if slot is not None:
            count = get_count(slot.assessors.filter_by(id=current_user.id))
            if count > 0:
                return True

    flash('Only supervisors, 2nd markers and presentation assessors can perform this operation', 'error')
    return False


def validate_using_assessment():
    # check that assessment events are actually required
    data = get_assessment_data()

    if not data['has_assessments']:
        flash('Presentation assessments are not currently required', 'error')
        return False

    return True


def validate_assessment(data, current_year=None):
    if current_year is None:
        current_year = get_current_year()

    if data.year != current_year:
        flash('Cannot edit presentation assessment {name} because it does not '
              'belong to the current year'.format(name=data.name), 'info')
        return False

    return True


def validate_schedule_inspector(record):
    """
    Validate that the logged-in user is entitled to view the schedule inspector for a given scheduling attempt
    :param record:
    :return:
    """
    if current_user.has_role('root') or current_user.has_role('admin'):
        return True

    if current_user.has_role('faculty'):
        if record.published:
            for pclass in record.available_pclasses:
                if pclass.is_convenor(current_user.id):
                    return True

        else:
            flash('The schedule owner has not yet made this match available to project convenors.', 'info')
            return False

    flash('This operation is available only to administrative users and project convenors.', 'error')
    return False


def validate_presentation_assessor(record):
    """
    Validate that the logged-in user is entitled to provide feedback on a presentation
    :param record:
    :return:
    """
    if get_count(record.assessors.filter_by(id=current_user.id)) > 0:
        return True

    flash('Only presentation assessors can provide feedback on a presentation assessment', 'error')
    return False


def validate_not_attending(talk):
    """
    Validate that a given talk is marked as 'not attending' for the assessment deployed for its
    SubmissionPeriodRecord
    :param talk:
    :return:
    """
    if not talk.period.has_presentation:
        flash('Cannot assign feedback to this submission record because it does not belong to a '
              'submission period that has presentation assessments.', 'info')
        return False

    if not talk.period.has_deployed_schedule:
        flash('Cannot assign feedback to this submission record because its submission period '
              'does not yet have a deployed schedule.', 'info')
        return False

    schedule = talk.period.deployed_schedule
    assessment = schedule.owner
    if not assessment.not_attending(talk.id):
        flash('Cannot assign feedback to this submission record because it is not marked as "not attending" '
              'for the assessment "{name}".'.format(name=assessment.name), 'info')
        return False

    return True
