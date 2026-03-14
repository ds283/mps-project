#
# Created by David Seery on 02/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from collections import namedtuple
from math import pi

from bokeh.embed import components
from bokeh.models import Label
from bokeh.plotting import figure
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
from ..shared.utils import grouper

DoughnutDiagram = namedtuple("DoughnutDiagram", ["script", "div"])


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

        self._tiles = None
        self._tile_list = None
        self._ui_elements = None

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

    def set_role(self, role: str, value: bool):
        if role in [
            "student",
            "supervisor",
            "marker",
            "moderator",
            "convenor",
            "admin",
        ]:
            setattr(self, role, value)
            self._tiles = None
            self._ui_elements = None
        else:
            raise ValueError(f"Invalid role: {role}")

    def _compute_tiles(self):
        self._tile_list = []

        # most admin roles can see attendance
        if self.supervisor or self.convenor or self.admin:
            self._tile_list.append("attendance")

            # supervisors, convenors, admin can see regular meetings tile
        if self.supervisor or self.convenor or self.admin:
            self._tile_list.append("regular_meetings")

        self._tiles = grouper(self._tile_list, 4, incomplete="fill")

    def get_tiles(self):
        if self._tiles is None:
            self._compute_tiles()

        return self._tiles

    def _compute_ui_elements(self):
        # everyone gets a header and can see the event list
        self._ui_elements = {"header", "events"}

    def get_ui_elements(self):
        if self._ui_elements is None:
            self._compute_ui_elements()

        return self._ui_elements


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

    my_role = HubRoleMap()

    # a student can always look at the project hub for their own projects (even if retired)
    if user.has_role("student") and user.id == record.owner.student_id:
        my_role.set_role("student", True)

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
            my_role.set_role("supervisor", True)

        if current_role.role in marker_roles:
            my_role.set_role("marker", True)

        if current_role.role in moderator_roles:
            my_role.set_role("moderator", True)

        if current_role.role in admin_roles:
            my_role.set_role("admin", True)

    # project convenors can look
    owner: SubmittingStudent = record.owner
    config: ProjectClassConfig = owner.config
    pclass: ProjectClass = config.project_class
    project: LiveProject = record.project

    if pclass.is_convenor(user.id):
        my_role.set_role("convenor", True)

    # admin, and root users can always look
    if user.has_role("admin") or user.has_role("root"):
        my_role.set_role("admin", True)

    # office staff, moderators, exam board members and external examiners can always look
    if user.has_role("office"):
        my_role.set_role("admin", True)

    if not my_role and message:
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

    return my_role


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


def doughnut_diagram(
    burn_fraction: float, burned_colour="tomato", unburned_colour="palegreen"
) -> DoughnutDiagram:
    angle = 2 * pi * min(burn_fraction, 0.995)
    start_angle = pi / 2.0
    end_angle = pi / 2.0 - angle if angle < pi / 2.0 else 5.0 * pi / 2.0 - angle

    plot = figure(width=80, height=80, toolbar_location=None)
    plot.sizing_mode = "fixed"
    plot.annular_wedge(
        x=0,
        y=0,
        inner_radius=0.75,
        outer_radius=1,
        direction="clock",
        line_color=None,
        start_angle=start_angle,
        end_angle=end_angle,
        fill_color=burned_colour,
    )
    if burn_fraction < 1.0:
        plot.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=end_angle,
            end_angle=start_angle,
            fill_color=unburned_colour,
        )
    plot.axis.visible = False
    plot.xgrid.visible = False
    plot.ygrid.visible = False
    plot.border_fill_color = None
    plot.toolbar.logo = None
    plot.background_fill_color = None
    plot.outline_line_color = None
    plot.toolbar.active_drag = None

    annotation = Label(
        x=0,
        y=0,
        x_units="data",
        y_units="data",
        text="{p:.2g}%".format(p=burn_fraction * 100)
        if burn_fraction < 1.0
        else "100%",
        background_fill_alpha=0.0,
        text_align="center",
        text_baseline="middle",
        text_font_style="bold",
    )
    plot.add_layout(annotation)

    script, div = components(plot)
    return DoughnutDiagram(script=script, div=div)
