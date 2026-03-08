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

from ..models import SubmissionRecord, User, SupervisionEvent, SubmissionRole, LiveProject, SubmittingStudent, ProjectClassConfig, ProjectClass, \
    StudentData


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
    project: LiveProject = record.project
    if user.has_role("faculty") or user.has_role("supervisor"):
        if project.owner_id == user.id or record.marker_id == user.id:
            return True

    # project convenors can look
    owner: SubmittingStudent = record.owner
    config: ProjectClassConfig = owner.config
    pclass: ProjectClass = config.project_class
    if pclass.is_convenor(user.id):
        return True

    if message:
        sd: StudentData = owner.student
        suser: User = sd.user
        if project is not None:
            flash(
                f'You are not currently authorized to view the project hub for student "{suser.name}" (project "{project.title}")',
                "info",
            )
        else:
            flash(f'You are not currently authorized to view the project hub for student "{suser.name}"')

    return False


def validate_set_attendance(event: SupervisionEvent, user: User, message=False):
    """
    Validate whether a given user has privileges to set attendance for a given SupervisionEvent
    :param event:
    :param user:
    :param message:
    :return:
    """

    # admin, office and root users can always set attendance
    if user.has_role("admin") or user.has_role("office") or user.has_role("root"):
        return True

    # faculty members can set attandance if they are the event owner, or if they are an attendee
    owner: SubmissionRole = event.owner
    if owner.user == user.id:
        return True

    if any([x.user_id == user.id for x in event.team]):
        return True

    if message:
        record: SubmissionRecord = event.sub_record
        owner: SubmittingStudent = record.owner
        sd: StudentData = owner.student
        suser: User = sd.user
        flash(f'You are not currently authorized to set attendance for event "{event.name}" and student "{suser.name}"')

    return False
