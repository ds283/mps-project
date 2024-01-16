#
# Created by David Seery on 02/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import flash

from ..models import SubmissionRecord, User


def validate_project_hub(record: SubmissionRecord, user: User, message=False):
    """
    Validate whether a given user instance is entitled to view the
    ProjectHub for a given SubmissionRecord
    :param record:
    :param user:
    :return:
    """

    # a student can always look at the project hub for their own projects (even if retired)
    if user.has_role("student") and user.id == record.owner.student_id:
        return True

    # admin, and root users can always look
    if user.has_role("admin") or user.has_role("root"):
        return True

    # office staff, moderators, exam board members and external examiners can always look
    if user.has_role("office") or user.has_role("moderator") or user.has_role("exam_board") or user.has_role("external_examiner"):
        return True

    # supervisors, markers can always look
    if user.has_role("faculty") or user.has_role("supervisor"):
        if record.project.owner_id == user.id or record.marker_id == user.id:
            return True

    # project convenors can look
    if record.owner.config.project_class.is_convenor(user.id):
        return True

    if message:
        if record.project is not None:
            flash(
                "You are not currently authorized to view the project hub for "
                'student "{name}" (project "{title}")'.format(name=record.owner.student.user.name, title=record.project.title),
                "info",
            )
        else:
            flash("You are not currently authorized to view the project hub for " 'student "{name}"'.format(name=record.owner.student.user.name))

    return False
