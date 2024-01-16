#
# Created by David Seery on 14/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import flash
from flask_login import current_user

from app.models import ProjectClassConfig, SubmittingStudent, SubmissionRecord, SelectingStudent
from app.shared.sqlalchemy import get_count


def verify_submitter(sub: SubmittingStudent, message: bool = False):
    if sub.student_id != current_user.id and not current_user.has_role("admin") and not current_user.has_role("root"):
        if message:
            flash(
                "You do not have permission to perform operations for this user. "
                "If you believe this is incorrect, contract the system administrator.",
                "error",
            )
        return False

    return True


def verify_submission_record(rec: SubmissionRecord, message: bool = False):
    if not verify_submitter(rec.owner, message):
        return False

    return True


def verify_selector(sel: SelectingStudent, message=False):
    """
    Validate that the logged-in user is allowed to perform operations on a particular SelectingStudent
    :param message:
    :param sel:
    :return:
    """
    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if sel.student_id != current_user.id and not current_user.has_role("admin") and not current_user.has_role("root"):
        if message:
            flash(
                "You do not have permission to perform operations for this user. "
                "If you believe this is incorrect, contract the system administrator.",
                "error",
            )
        return False

    return True


def verify_view_project(config: ProjectClassConfig, project):
    """
    Validate that a particular SelectingStudent is allowed to perform operations on a given LiveProject
    :param sel:
    :param project:
    :return:
    """
    if get_count(config.live_projects.filter_by(id=project.id)) == 0:
        flash(
            "You are not able to view or bookmark this project because it is not attached to your student "
            "record for this type of project. Return to the dashboard and try to access the project from there. "
            "If problems persist, contact the system administrator.",
            "error",
        )
        return False

    return True


def verify_open(config, state=None, strict=False, message=False):
    """
    Validate that a particular ProjectClassConfig is open for student selections
    :param message:
    :param config:
    :return:
    """
    if state is None:
        state = config.selector_lifecycle

    if strict and state != ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash("It is not possible to perform this operations because selections for " '"{proj}" are not open.'.format(proj=config.name), "error")
        return False

    if not strict and state < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash("It is not possible to perform this operations because selections for " '"{proj}" are not yet open.'.format(proj=config.name), "error")
        return False

    return True
