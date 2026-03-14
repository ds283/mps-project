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

from ..models import (
    LiveProject,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    SupervisionEvent,
    User,
)


class HubRoleMap:
    def __init__(
        self,
        student: bool = False,
        supervisor: bool = False,
        marker: bool = False,
        moderator: bool = False,
        convenor: bool = False,
        admin: bool = False,
    ):
        self.student = student
        self.supervisor = supervisor
        self.marker = marker
        self.moderator = moderator
        self.convenor = convenor
        self.admin = admin

    def __bool__(self):
        return (
            self.student
            or self.supervisor
            or self.marker
            or self.moderator
            or self.convenor
            or self.admin
        )

    @property
    def is_student(self):
        return self.student

    @property
    def is_supervisor(self):
        return self.supervisor

    @property
    def is_marker(self):
        return self.marker

    @property
    def is_moderator(self):
        return self.moderator

    @property
    def is_convenor(self):
        return self.convenor

    @property
    def is_admin(self):
        return self.admin

    @property
    def show_student_dashboard(self):
        return self.student


def validate_project_hub(
    record: SubmissionRecord, user: User, current_role=None, message=False
) -> HubRoleMap:
    """
    Validate whether a given user instance is entitled to view the
    ProjectHub for a given SubmissionRecord
    :param current_role:
    :param record:
    :param user:
    :return:
    """

    # a student can always look at the project hub for their own projects (even if retired)
    if user.has_role("student") and user.id == record.owner.student_id:
        return HubRoleMap(student=True)

    # admin, and root users can always look
    if user.has_role("admin") or user.has_role("root"):
        return HubRoleMap(admin=True)

    # office staff, moderators, exam board members and external examiners can always look
    if user.has_role("office"):
        return HubRoleMap(admin=True)

    # supervisors, markers, moderators, exam board members, and external examiners can always look
    supervisor_roles = [
        SubmissionRole.ROLE_SUPERVISOR,
        SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
    ]
    marker_roles = [
        SubmissionRole.ROLE_MARKER,
    ]
    moderator_roles = [
        SubmissionRole.ROLE_MODERATOR,
    ]
    admin_roles = [
        SubmissionRole.ROLE_EXAM_BOARD,
        SubmissionRole.ROLE_EXTERNAL_EXAMINER,
    ]

    if current_role is None:
        for role in record.roles:
            role: SubmissionRole
            if role.user_id == user.id:
                current_role = role

    if current_role is not None:
        if current_role.user_id != user.id:
            if message:
                flash(
                    "Authorization issue for project page: current role does not match current user. Please contact a system administrator.",
                    "error",
                )
            return HubRoleMap()

        if current_role.role in supervisor_roles:
            return HubRoleMap(supervisor=True)

        if current_role.role in marker_roles:
            return HubRoleMap(marker=True)

        if current_role.role in moderator_roles:
            return HubRoleMap(moderator=True)

        if current_role.role in admin_roles:
            return HubRoleMap(admin=True)

    # project convenors can look
    owner: SubmittingStudent = record.owner
    config: ProjectClassConfig = owner.config
    pclass: ProjectClass = config.project_class
    project: LiveProject = record.project

    if pclass.is_convenor(user.id):
        return HubRoleMap(convenor=True)

    if message:
        sd: StudentData = owner.student
        suser: User = sd.user
        if project is not None:
            flash(
                f'You are not currently authorized to view the project hub for student "{suser.name}" (project "{project.name}")',
                "info",
            )
        else:
            flash(
                f'You are not currently authorized to view the project hub for student "{suser.name}"'
            )

    return HubRoleMap()


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
    if owner.user_id == user.id:
        return True

    if any([x.user_id == user.id for x in event.team]):
        return True

    if message:
        record: SubmissionRecord = event.sub_record
        owner: SubmittingStudent = record.owner
        sd: StudentData = owner.student
        suser: User = sd.user
        flash(
            f'You are not currently authorized to set attendance for event "{event.name}" and student "{suser.name}"'
        )

    return False
