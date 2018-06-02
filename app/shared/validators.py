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

from app.models import ProjectClass, Project


def validate_administrator():
    """
    Ensure that user in an administrator
    :return:
    """

    if not current_user.has_role('admin') and not current_user.has_role('root'):

        flash('Only administrative users can view unattached projects.')
        return False

    return True


def validate_convenor(pclass):
    """
    Validate that the logged-in user is privileged to view a convenor dashboard
    :param pclass: Project class model instance
    :return: True/False
    """

    # if logged in user is convenor for this class, or is an admin user, then all is OK
    if pclass.convenor_id != current_user.id \
        and not current_user.has_role('admin') \
        and not current_user.has_role('root'):

        flash('Convenor actions are available only to project convenors and administrative users.')
        return False

    return True


def validate_user(project):
    """
    Validate that the logged-in user is privileged to edit a project
    :param project: Project model instance
    :return: True/False
    """

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if project.owner_id != current_user.id \
            and not current_user.has_role('admin') \
            and not current_user.has_role('root') \
            and not any[project.project_classes.convenor.id == current_user.id]:

        flash('This project belongs to another user. To edit it, you must be a suitable convenor or an administrator.')
        return False

    return True


def validate_open(config):
    """
    Validate that a particular ProjectClassConfig is open for student selections
    :param config:
    :return:
    """

    if not config.open:

        flash('Project "{name}" is not open for student selections'.format(name=config.project_class.name), 'error')

        return False

    return True
