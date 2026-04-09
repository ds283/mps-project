#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union

if TYPE_CHECKING:
    from .live_projects import LiveProject, SubmittingStudent

from flask_security import current_user
from numpy import nan
from sqlalchemy import and_, or_, orm
from sqlalchemy.event import listens_for
from sqlalchemy.orm import validates, with_polymorphic

from ..cache import cache
from ..database import db
from ..shared.llm_thresholds import (
    MATTR_NOTE_LOW_THRESHOLD,
    MTLD_NOTE_THRESHOLD,
    BURSTINESS_NOTE_LOW,
    SENT_CV_NOTE_LOW,
)
from ..shared.sqlalchemy import get_count
from .associations import (
    submission_record_to_feedback_report,
    submission_role_emails,
    submitted_acl,
    submitted_acr,
    submitter_to_slots,
)
from .defaults import DEFAULT_STRING_LENGTH
from .faculty import EnrollmentRecord, FacultyData
from .mixins import WeekdaysMixin
from .model_mixins import (
    CustomOfferStatesMixin,
    EditingMetadataMixin,
    SelectHintTypesMixin,
    SubmissionAttachmentTypesMixin,
    SubmissionFeedbackStatesMixin,
    SubmissionRoleTypesMixin,
)
from .project_class import (
    ProjectClass,
    ProjectClassConfig,
    SubmissionPeriodRecord,
    SubmissionPeriodUnit,
    SupervisionEvent,
    SupervisionEventTemplate,
)
from .users import Role, User
from .utilities import _MatchingAttempt_current_score, _MatchingAttempt_hint_status


class CanvasStudent(db.Model):
    """
    Represents a student that is present in the Canvas database, but not present in the submitter list
    """

    __tablename__ = "canvas_student"

    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # link to ProjectClassConfig to which we are associated
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        foreign_keys=[config_id],
        uselist=False,
        backref=db.backref(
            "missing_canvas_students",
            lazy="dynamic",
            cascade="all, delete, delete-orphan",
        ),
    )

    # link to match found in our own (student) user database, or None if no matching user is present
    student_id = db.Column(
        db.Integer(), db.ForeignKey("student_data.id"), nullable=True
    )
    student = db.relationship(
        "StudentData",
        foreign_keys=[student_id],
        uselist=False,
        backref=db.backref(
            "missing_canvas_students",
            lazy="dynamic",
            cascade="all, delete, delete-orphan",
        ),
    )

    # student email
    email = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False
    )

    # first name
    first_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), default=None
    )

    # last name
    last_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), default=None
    )

    # Canvas user id
    canvas_user_id = db.Column(db.Integer(), nullable=False)


class SubmissionRole(
    db.Model,
    SubmissionRoleTypesMixin,
    SubmissionFeedbackStatesMixin,
    WeekdaysMixin,
    EditingMetadataMixin,
):
    """
    Model for each staff member that has a role for a SubmissionRecord: that includes supervisors, markers,
    moderators, exam board members and external examiners (and possibly others)
    """

    __tablename__ = "submission_roles"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # owning submission record
    submission_id = db.Column(db.Integer(), db.ForeignKey("submission_records.id"))
    submission = db.relationship(
        "SubmissionRecord",
        foreign_keys=[submission_id],
        uselist=False,
        backref=db.backref("roles", lazy="dynamic"),
    )

    # optional link to possible owning ScheduleSlot, used for PRESENTATION_ASSESSOR roles to identify the session
    schedule_slot_id = db.Column(db.Integer(), db.ForeignKey("schedule_slots.id"))
    schedule_slot = db.relationship(
        "ScheduleSlot",
        foreign_keys=[schedule_slot_id],
        uselist=False,
        backref=db.backref("submission_roles", lazy="dynamic"),
    )

    # owning user (note: we link to a user record, rather than a FacultyData record, because the
    # assigned person does not have to be a FacultyData instance, e.g. for external examiners)
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        uselist=False,
        backref=db.backref("submission_roles", lazy="dynamic"),
    )

    # role identifier, drawn from SubmissionRoleTypesMixin
    role = db.Column(
        db.Integer(),
        default=SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        nullable=False,
    )

    @validates("role")
    def _validate_role(self, key, value):
        if value < self._MIN_ROLE:
            value = self._MIN_ROLE

        if value > self._MAX_ROLE:
            value = self._MAX_ROLE

        return value

    # NOTIFICATION PREFERENCES

    # mute all notifications for this role?
    mute = db.Column(db.Boolean(), default=False, nullable=False)

    # prompt for attendance entry after SupervisionEvents owned by this role has happened?
    prompt_after_event = db.Column(db.Boolean(), default=True, nullable=False)

    # prompt at a fixed time on the day of the event, or after a specified delay?
    prompt_at_fixed_time = db.Column(db.Boolean(), default=False, nullable=False)

    # absolute time to send a prompt (if prompting at fixed time)
    prompt_at_time = db.Column(db.Time(), nullable=True)

    # delay before sending a prompt (if prompting with a delay)
    _prompt_delay_choices = [
        (1, "1 hour after start time"),
        (2, "2 hours after start time"),
        (3, "3 hours after start time"),
        (4, "4 hours after start time"),
        (5, "5 hours after start time"),
    ]
    prompt_delay = db.Column(db.Integer(), default=1, nullable=True)

    # include events belonging to this role in reminder emails?
    prompt_in_reminder = db.Column(db.Boolean(), default=True, nullable=False)

    @validates("prompt_at_fixed_time")
    def _validate_prompt_at_fixed_time(self, key, value):
        if value and self.prompt_at_time is None:
            self.prompt_at_time = time(hour=16, minute=0)

        if not value and self.prompt_delay is None:
            self.prompt_delay = 1

        return value

    # EMAIL LOG

    # email log associated with this role
    email_log = db.relationship(
        "EmailLog", secondary=submission_role_emails, lazy="dynamic"
    )

    # SUPERVISION EVENTS (only used where the SubmissionRole is a supervisory one)

    # current regular meeting time
    regular_meeting_weekday = db.Column(db.Integer(), default=None, nullable=True)

    # current regular meeting time
    regular_meeting_time = db.Column(db.Time(), default=None, nullable=True)

    # current regular meeting location
    regular_meeting_location = db.Column(
        db.String(DEFAULT_STRING_LENGTH), default=None, nullable=True
    )

    # MARKING WORKFLOW

    # returned mark, interpreted as out of 100%
    grade = db.Column(db.Integer(), default=None)

    # resolved weight for this score
    weight = db.Column(db.Numeric(8, 3), default=None)

    # justification for score
    justification = db.Column(db.Text(), default=None)

    # marking sign off (interpreted as approval if responsible supervisor is not writing the supervision report)
    signed_off = db.Column(db.DateTime(), default=False)

    # FEEDBACK TO STUDENT

    # positive feedback
    positive_feedback = db.Column(db.Text())

    # improvements feedback
    improvements_feedback = db.Column(db.Text())

    # has the feedback been submitted?
    submitted_feedback = db.Column(db.Boolean())

    # feedback submission datestamp
    feedback_timestamp = db.Column(db.DateTime())

    # RESPONSE TO FEEDBACK FROM STUDENT (if used)

    # acknowledge seen student feedback
    acknowledge_student = db.Column(db.Boolean())

    # faculty response
    response = db.Column(db.Text())

    # faculty response submitted
    submitted_response = db.Column(db.Boolean())

    # faculty response timestamp
    response_timestamp = db.Column(db.DateTime())

    # LIFECYCLE

    # has feedback been pushed out to the student for this period?
    feedback_sent = db.Column(db.Boolean(), default=False)

    # who pushed the feedback?
    feedback_push_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    feedback_push_by = db.relationship(
        "User", foreign_keys=[feedback_push_id], uselist=False
    )

    # timestamp when feedback was sent
    feedback_push_timestamp = db.Column(db.DateTime())

    # FACTORY FUNCTION
    @classmethod
    def build_(cls, **kwargs):
        obj = cls(**kwargs)

        defaults = {
            "schedule_slot_id": None,
            "mute": False,
            "prompt_after_event": True,
            "prompt_at_fixed_time": False,
            "prompt_at_time": None,
            "prompt_delay": 1,
            "prompt_in_reminder": True,
            "email_log": [],
            "regular_meeting_weekday": None,
            "regular_meeting_time": None,
            "regular_meeting_location": None,
            "grade": None,
            "weight": 1.0,
            "justification": None,
            "signed_off": None,
            "positive_feedback": None,
            "improvements_feedback": None,
            "submitted_feedback": False,
            "feedback_timestamp": None,
            "acknowledge_student": False,
            "response": None,
            "submitted_response": False,
            "response_timestamp": None,
            "feedback_sent": False,
            "feedback_push_id": None,
            "feedback_push_cls": None,
            "last_edit_id": None,
            "last_edit_timestamp": None,
        }

        for attr in defaults:
            if attr not in kwargs:
                setattr(obj, attr, defaults[attr])

        return obj

    @property
    def role_as_str(self) -> str:
        return self._role_string.get(self.role, "Unknown")

    @property
    def roleid_as_str(self) -> str:
        return self._role_id.get(self.role, "unknown")

    @property
    def uses_supervisor_feedback(self):
        return self.submission.period.uses_supervisor_feedback

    @property
    def uses_marker_feedback(self):
        return self.submission.period.uses_marker_feedback

    @property
    def uses_presentation_feedback(self):
        return self.submission.period.uses_presentation_feedback

    @property
    def has_regular_meeting(self):
        if self.role not in [
            SubmissionRole.ROLE_SUPERVISOR,
            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
        ]:
            return False

        return (
            self.regular_meeting_weekday is not None
            and self.regular_meeting_time is not None
        )

    @property
    def regular_meeting_as_string(self):
        return {
            "day": self._weekdays_string.get(self.regular_meeting_weekday, "Unknown"),
            "time": self.regular_meeting_time.strftime("%H:%M"),
            "location": self.regular_meeting_location,
        }

    @property
    def feedback_state(self):
        if self.role in [
            SubmissionRole.ROLE_SUPERVISOR,
            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
        ]:
            return self._supervisor_feedback_state
        elif self.role in [SubmissionRole.ROLE_MARKER]:
            return self._marker_feedback_state
        elif self.role in [SubmissionRole.ROLE_MODERATOR]:
            return self._moderator_feedback_state
        elif self.role in [SubmissionRole.ROLE_PRESENTATION_ASSESSOR]:
            return self._presentation_assessor_feedback_state

        return SubmissionRole.FEEDBACK_NOT_REQUIRED

    @property
    def _supervisor_feedback_state(self):
        if not self.uses_supervisor_feedback:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        period: SubmissionPeriodRecord = self.submission.period

        if not period.config.project_class.publish:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        return self._internal_feedback_state

    @property
    def _marker_feedback_state(self):
        if not self.uses_marker_feedback:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        period: SubmissionPeriodRecord = self.submission.period

        if not period.config.project_class.publish:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        return self._internal_feedback_state

    @property
    def _moderator_feedback_state(self):
        return SubmissionRole.FEEDBACK_NOT_REQUIRED

    @property
    def _presentation_assessor_feedback_state(self):
        if not self.uses_presentation_feedback:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        period: SubmissionPeriodRecord = self.submission.period
        if not period.config.project_class.publish:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        slot = self.schedule_slot
        if slot is None:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        today = date.today()
        if today <= slot.session.date:
            return SubmissionRole.FEEDBACK_NOT_YET

        if self.submitted_feedback:
            return SubmissionRole.FEEDBACK_SUBMITTED

        if self.feedback_valid:
            return SubmissionRole.FEEDBACK_ENTERED

        closed = slot.owner.owner.is_closed
        return (
            SubmissionRole.FEEDBACK_LATE if closed else SubmissionRole.FEEDBACK_WAITING
        )

    @property
    def feedback_valid(self):
        if self.positive_feedback is None or len(self.positive_feedback) == 0:
            return False

        if self.improvements_feedback is None or len(self.improvements_feedback) == 0:
            return False

        return True

    @property
    def _internal_feedback_state(self):
        period: SubmissionPeriodRecord = self.submission.period

        if not period.is_feedback_open:
            return SubmissionRole.FEEDBACK_NOT_YET

        if self.submitted_feedback:
            return SubmissionRole.FEEDBACK_SUBMITTED

        if self.feedback_valid:
            return SubmissionRole.FEEDBACK_ENTERED

        if not period.closed:
            return SubmissionRole.FEEDBACK_WAITING

        return SubmissionRole.FEEDBACK_LATE

    @property
    def response_state(self):
        if self.role in [
            SubmissionRole.ROLE_SUPERVISOR,
            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
        ]:
            return self._supervisor_response_state

        return SubmissionRole.FEEDBACK_NOT_REQUIRED

    @property
    def _supervisor_response_state(self):
        sub: SubmissionRecord = self.submission
        period: SubmissionPeriodRecord = sub.period

        if not period.config.project_class.publish:
            return SubmissionRole.FEEDBACK_NOT_REQUIRED

        if not period.is_feedback_open:
            return SubmissionRole.FEEDBACK_NOT_YET

        if self.submitted_response:
            return SubmissionRole.FEEDBACK_SUBMITTED

        if self.response_valid:
            return SubmissionRole.FEEDBACK_ENTERED

        if not period.closed:
            return SubmissionRole.FEEDBACK_WAITING

        return SubmissionRole.FEEDBACK_LATE

    @property
    def response_valid(self):
        if self.response is None or len(self.response) == 0:
            return False

        return True

    @property
    def number_events_owned(self) -> int:
        return get_count(self.events_owner)

    @property
    def events_owned(self) -> List["SupervisionEvent"]:
        return self.events_owner.all()

    @property
    def number_events_attending(self) -> int:
        return get_count(self.events_team)

    @property
    def events_attending(self) -> List["SupervisionEvent"]:
        return self.events_team.all()

    def past_owned_events(
        self, now: Optional[datetime] = None
    ) -> List[SupervisionEvent]:
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SupervisionEvent.owner_id == self.id,
                or_(
                    and_(
                        SupervisionEvent.time == None,
                        SubmissionPeriodUnit.end_date < now.date(),
                    ),
                    and_(SupervisionEvent.time != None, SupervisionEvent.time < now),
                ),
            )
        )

        return query

    def notpast_owned_events(
        self, now: Optional[datetime] = None
    ) -> List[SupervisionEvent]:
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SupervisionEvent.owner_id == self.id,
                or_(
                    and_(
                        SupervisionEvent.time == None,
                        SubmissionPeriodUnit.end_date >= now.date(),
                    ),
                    and_(SupervisionEvent.time != None, SupervisionEvent.time >= now),
                ),
            )
        )

        return query

    def future_owned_events(
        self, now: Optional[datetime] = None
    ) -> List[SupervisionEvent]:
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SupervisionEvent.owner_id == self.id,
                or_(
                    and_(
                        SupervisionEvent.time == None,
                        SubmissionPeriodUnit.start_date > now.date(),
                    ),
                    and_(SupervisionEvent.time != None, SupervisionEvent.time > now),
                ),
            )
        )

        return query

    def current_owned_events(
        self, now: Optional[datetime] = None
    ) -> List[SupervisionEvent]:
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SupervisionEvent.owner_id == self.id,
                SubmissionPeriodUnit.start_date <= now.date(),
                SubmissionPeriodUnit.end_date >= now.date(),
            )
        )

        return query

    def number_owned_events_with_attendance(
        self, now: Optional[datetime] = None
    ) -> int:
        if now is None:
            now = datetime.now()

        query = self.past_owned_events(now)
        query = query.filter(
            SupervisionEvent.monitor_attendance.is_(True),
            SupervisionEvent.attendance != None,
        )
        return get_count(query)

    def number_owned_events_missing_attendance(
        self, now: Optional[datetime] = None
    ) -> int:
        if now is None:
            now = datetime.now()

        query = self.past_owned_events(now)
        query = query.filter(
            SupervisionEvent.monitor_attendance.is_(True),
            SupervisionEvent.attendance == None,
        )
        return get_count(query)


@listens_for(SubmissionRole, "before_update")
def _SubmissionRole_update_handler(mapper, connection, target):
    if target.submission is not None:
        target.submission._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SubmissionRecord_is_valid, target.submission_id)

        record: SubmissionRecord = (
            db.session.query(SubmissionRecord)
            .filter_by(id=target.submission_id)
            .first()
        )
        if record is not None:
            from .live_projects import _SubmittingStudent_is_valid

            cache.delete_memoized(_SubmittingStudent_is_valid, record.owner_id)


@listens_for(SubmissionRole, "before_insert")
def _SubmissionRole_insert_handler(mapper, connection, target):
    if target.submission is not None:
        target.submission._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SubmissionRecord_is_valid, target.submission_id)

        record: SubmissionRecord = (
            db.session.query(SubmissionRecord)
            .filter_by(id=target.submission_id)
            .first()
        )
        if record is not None:
            from .live_projects import _SubmittingStudent_is_valid

            cache.delete_memoized(_SubmittingStudent_is_valid, record.owner_id)


@listens_for(SubmissionRole, "before_delete")
def _SubmissionRole_delete_handler(mapper, connection, target):
    if target.submission is not None:
        target.submission._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SubmissionRecord_is_valid, target.submission_id)

        record: SubmissionRecord = (
            db.session.query(SubmissionRecord)
            .filter_by(id=target.submission_id)
            .first()
        )
        if record is not None:
            from .live_projects import _SubmittingStudent_is_valid

            cache.delete_memoized(_SubmittingStudent_is_valid, record.owner_id)


@cache.memoize()
def _SubmissionRecord_is_valid(sid):
    obj: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=sid).one()
    period: SubmissionPeriodRecord = obj.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class
    sub: "SubmittingStudent" = obj.owner
    project: "LiveProject" = obj.project

    errors = {}
    warnings = {}

    uses_supervisor = config.uses_supervisor
    uses_marker = config.uses_marker
    uses_moderator = config.uses_moderator
    markers_needed = period.number_markers
    moderators_needed = period.number_moderators

    supervisor_roles: List[SubmissionRole] = obj.supervisor_roles
    responsible_supervisor_roles: List[SubmissionRole] = [
        r
        for r in supervisor_roles
        if r.role == SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR
    ]
    marker_roles: List[SubmissionRole] = obj.marker_roles
    moderator_roles: List[SubmissionRole] = obj.moderator_roles

    supervisor_ids: Set[int] = set(r.user_id for r in supervisor_roles)
    responsible_supervisor_ids: Set[int] = set(
        r.user_id for r in responsible_supervisor_roles
    )
    marker_ids: Set[int] = set(r.user_id for r in marker_roles)
    moderator_ids: Set[int] = set(r.user_id for r in moderator_roles)

    # 1. SUPERVISOR, MARKER, AND MODERATOR ROLES SHOULD BE DISTINCT
    a = supervisor_ids.intersection(marker_ids)
    if len(a) > 0:
        errors[("basic", 0)] = "Some supervisor and marker roles coincide"

    b = supervisor_ids.intersection(moderator_ids)
    if len(b) > 0:
        errors[("basic", 1)] = "Some supervisor and moderator roles coincide"

    c = marker_ids.intersection(moderator_ids)
    if len(c) > 0:
        errors[("basic", 2)] = "Some marker and moderator roles coincide"

    supervisor_counts = {}
    marker_counts = {}
    moderator_counts = {}

    supervisor_dict = {}
    marker_dict = {}
    moderator_dict = {}

    for u in supervisor_roles:
        supervisor_dict[u.id] = u

        if u.id not in supervisor_counts:
            supervisor_counts[u.id] = 1
        else:
            supervisor_counts[u.id] += 1

    for u in marker_roles:
        marker_dict[u.id] = u

        if u.id not in marker_counts:
            marker_counts[u.id] = 1
        else:
            marker_counts[u.id] += 1

    for u in moderator_roles:
        moderator_dict[u.id] = u

        if u.id not in moderator_counts:
            moderator_counts[u.id] = 1
        else:
            moderator_counts[u.id] += 1

    if uses_supervisor:
        # 1A. IF SUPERVISORS ARE USED, AT LEAST ONE SUPERVISOR SHOULD BE PROVIDED
        if len(supervisor_ids) == 0:
            errors[("supervisors", 0)] = (
                "No supervision roles are assigned for this project"
            )

        # 1B. USUALLY THERE SHOULD BE JUST ONE RESPONSIBLE SUPERVISOR ROLE
        if len(responsible_supervisor_ids) > 1:
            warnings[("responsible-supervisors", 0)] = (
                "There are {n} responsible supervision roles assigned for this project".format(
                    n=len(supervisor_ids)
                )
            )

        # 1C. SUPERVISORS SHOULD NOT BE MULTIPLY ASSIGNED TO THE SAME ROLE
        for u_id in supervisor_counts:
            count = supervisor_counts[u_id]
            if count > 1:
                user: User = supervisor_dict[u_id]

                errors[("supervisors", 1)] = (
                    'Supervisor "{name}" is assigned {n} times for this submitter'.format(
                        name=user.name, n=count
                    )
                )

    if uses_marker:
        # 1D. THERE SHOULD BE THE RIGHT NUMBER OF ASSIGNED MARKERS
        if len(marker_ids) < markers_needed:
            errors[("markers", 0)] = (
                "Fewer marker roles are assigned than expected for this project (assigned={assgn}, expected={exp})".format(
                    assgn=len(marker_ids), exp=markers_needed
                )
            )

        # 1E. WARN IF MORE MARKERS THAN EXPECTED ASSIGNED
        if len(marker_ids) > markers_needed:
            warnings[("markers", 0)] = (
                "More marker roles are assigned than expected for this project (assigned={assgn}, expected={exp})".format(
                    assgn=len(marker_ids), exp=markers_needed
                )
            )

        # 1F. MARKERS SHOULD NOT BE MULTIPLY ASSIGNED TO THE SAME ROLE
        for u_id in marker_counts:
            count = marker_counts[u_id]
            if count > 1:
                user: User = marker_dict[u_id]

                errors[("markers", 1)] = (
                    'Marker "{name}" is assigned {n} times for this submitter'.format(
                        name=user.name, n=count
                    )
                )

    if uses_moderator:
        # 1G. THERE SHOULD BE THE RIGHT NUMBER OF ASSIGNED MODERATORS
        if len(moderator_ids) < moderators_needed:
            errors[("moderators", 0)] = (
                "Fewer moderator roles are assigned than expected for this project (assigned={assgn}, expected={exp})".format(
                    assgn=len(moderator_ids), exp=moderators_needed
                )
            )

        # 1H. WARN IF MORE MODERATORS THAN EXPECTED ASSIGNED
        if len(moderator_ids) > moderators_needed:
            warnings[("moderators", 0)] = (
                "More moderator roles are assigned than expected for this project (assigned={assgn}, expected={exp})".format(
                    assgn=len(moderator_ids), exp=moderators_needed
                )
            )

        # 1I. MODERATORS SHOULD NOT BE MULTIPLY ASSIGNED TO THE SAME ROLE
        for u_id in moderator_counts:
            count = moderator_counts[u_id]
            if count > 1:
                user: User = moderator_dict[u_id]

                errors[("moderators", 1)] = (
                    'Moderator "{name}" is assigned {n} times for this '
                    "submitter".format(name=user.name, n=count)
                )

    # 2. ASSIGNED PROJECT SHOULD BE PART OF THE PROJECT CLASS
    if obj.selection_config is not None:
        if project is not None and project.config_id != obj.selection_config_id:
            errors[("config", 0)] = (
                "Assigned project does not belong to the correct class for this submitter"
            )

    # 3. STAFF WITH SUPERVISOR ROLES SHOULD BE ENROLLED FOR THIS PROJECT CLASS
    for r in supervisor_roles:
        user: User = r.user
        if user.faculty_data is not None:
            enrolment: EnrollmentRecord = user.faculty_data.get_enrollment_record(
                pclass
            )
            if (
                enrolment is None
                or enrolment.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED
            ):
                errors[("enrolment", 0)] = (
                    '"{name}" has been assigned a supervision role, but is not currently '
                    "enrolled for this project class".format(name=user.name)
                )
        else:
            warnings[("enrolment", 0)] = (
                '"{name}" has been assigned a supervision role, but is not a faculty member'
            )

    # 4. STAFF WITH MODERATOR ROLES SHOULD BE ENROLLED FOR THIS PROJECT CLASS
    for r in marker_roles:
        user: User = r.user
        if user.faculty_data is not None:
            enrolment: EnrollmentRecord = user.faculty_data.get_enrollment_record(
                pclass
            )
            if (
                enrolment is None
                or enrolment.marker_state != EnrollmentRecord.MARKER_ENROLLED
            ):
                errors[("enrolment", 1)] = (
                    '"{name}" has been assigned a marking role, but is not currently '
                    "enrolled for this project class".format(name=user.name)
                )
        else:
            warnings[("enrolment", 1)] = (
                '"{name}" has been assigned a marking role, but is not a faculty member'
            )

    # 5. STAFF WITH MODERATOR ROLES SHOULD BE ENROLLED FOR THIS PROJECT CLASS
    for r in moderator_roles:
        user: User = r.user
        if user.faculty_data is not None:
            enrolment: EnrollmentRecord = user.faculty_data.get_enrollment_record(
                pclass
            )
            if (
                enrolment is None
                or enrolment.moderator_state != EnrollmentRecord.MODERATOR_ENROLLED
            ):
                errors[("enrolment", 2)] = (
                    '"{name}" has been assigned a moderation role, but is not currently '
                    "enrolled for this project class".format(name=user.name)
                )
        else:
            warnings[("enrolment", 2)] = (
                '"{name}" has been assigned a moderation role, but is not a faculty member'
            )

    # 6. ASSIGNED MARKERS SHOULD BE IN THE ASSESSOR POOL FOR THE ASSIGNED PROJECT
    if uses_marker and project is not None:
        for r in marker_roles:
            user: User = r.user
            count = get_count(
                project.assessor_list_query.filter(FacultyData.id == user.id)
            )

            if count != 1:
                errors[("markers", 2)] = (
                    'Assigned marker "{name}" is not in assessor pool for '
                    "assigned project".format(name=user.name)
                )

    # 7. ASSIGNED MODERATORS SHOULD BE IN THE ASSESSOR POOL FOR THE ASSIGNED PROJECT
    if uses_moderator and project is not None:
        for r in moderator_roles:
            user: User = r.user
            count = get_count(
                project.assessor_list_query.filter(FacultyData.id == user.id)
            )

            if count != 1:
                errors[("moderators", 2)] = (
                    'Assigned moderator "{name}" is not in assessor pool for '
                    "assigned project".format(name=user.name)
                )

    # 8. FOR ORDINARY PROJECTS, THE PROJECT OWNER SHOULD USUALLY BE A SUPERVISOR
    if project is not None and not project.generic:
        if project.owner is not None and project.owner_id not in supervisor_ids:
            warnings[("supervisors", 2)] = (
                'Assigned project owner "{name}" does not have a supervision '
                "role".format(name=project.owner.user.name)
            )

    # 9. For GENERIC PROJECTS, THE SUPERVISOR SHOULD BE IN THE SUPERVISION POOL
    if project is not None and project.generic:
        for r in supervisor_roles:
            user: User = r.user
            if not any(user.id == fd.id for fd in project.supervisors):
                errors[("supervisors", 3)] = (
                    'Assigned supervisor "{name}" is not in supervision pool for '
                    "assigned project".format(name=user.name)
                )

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


class SubmissionRecord(db.Model, SubmissionFeedbackStatesMixin):
    """
    Collect details for a student submission
    """

    __tablename__ = "submission_records"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # owning submission period
    period_id = db.Column(db.Integer(), db.ForeignKey("submission_periods.id"))
    period = db.relationship(
        "SubmissionPeriodRecord",
        foreign_keys=[period_id],
        uselist=False,
        backref=db.backref("submissions", lazy="dynamic"),
    )

    # retired flag, set by rollover code
    retired = db.Column(db.Boolean(), index=True)

    # id of owning SubmittingStudent
    owner_id = db.Column(db.Integer(), db.ForeignKey("submitting_students.id"))
    owner = db.relationship(
        "SubmittingStudent",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "records", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # assigned project
    project_id = db.Column(
        db.Integer(), db.ForeignKey("live_projects.id"), default=None
    )
    project = db.relationship(
        "LiveProject",
        foreign_keys=[project_id],
        uselist=False,
        backref=db.backref("submission_records", lazy="dynamic"),
    )

    # link to ProjectClassConfig that selections were drawn from; used to offer a list of LiveProjects
    # if the convenor wishes to reassign
    selection_config_id = db.Column(
        db.Integer(), db.ForeignKey("project_class_config.id")
    )
    selection_config = db.relationship(
        "ProjectClassConfig", foreign_keys=[selection_config_id], uselist=None
    )

    # capture parent MatchingRecord, if one exists
    matching_record_id = db.Column(
        db.Integer(), db.ForeignKey("matching_records.id"), default=None
    )
    matching_record = db.relationship(
        "MatchingRecord",
        foreign_keys=[matching_record_id],
        uselist=False,
        backref=db.backref("submission_record", uselist=False),
    )

    # REPORT UPLOAD

    # main report
    report_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), default=None
    )
    report = db.relationship(
        "SubmittedAsset",
        foreign_keys=[report_id],
        uselist=False,
        backref=db.backref("submission_record", uselist=False),
    )

    # processed version of report; if report is not None, then a value of None indicates that processing has not
    # yet been done
    processed_report_id = db.Column(
        db.Integer(), db.ForeignKey("generated_assets.id"), default=None
    )
    processed_report = db.relationship(
        "GeneratedAsset",
        foreign_keys=[processed_report_id],
        uselist=False,
        backref=db.backref("submission_record", uselist=False),
    )

    # launched Celery task for process report?
    celery_started = db.Column(db.Boolean(), default=False)

    # is the celery processing task finished?
    celery_finished = db.Column(db.Boolean(), default=False)

    # did the celery processing task fail? (set by the error handler in the process_report chain)
    celery_failed = db.Column(db.Boolean(), default=False)

    # timestamp for generation of report
    timestamp = db.Column(db.DateTime())

    # is this report marked as suitable for an exemplar?
    report_exemplar = db.Column(db.Boolean(), default=False)

    # is this report embargoed?
    report_embargo = db.Column(db.DateTime(), default=None)

    # is this report secret or private? (e.g. contains commercially sensitive content)
    report_secret = db.Column(db.Boolean(), default=False)

    # any comments on the report that can be exposed in the UI when offered as an exemplar
    exemplar_comment = db.Column(db.Text(), default=None)

    # attachments incorporated via back-reference under 'attachments' data member

    # LANGUAGE ANALYSIS

    # JSON blob storing all language analysis results: metrics, flags, patterns, llm_result, errors.
    # Uses Text rather than a native JSON column, consistent with the existing project pattern.
    language_analysis = db.Column(db.Text(length=16777215), default=None)

    # has the language analysis workflow been started?
    language_analysis_started = db.Column(db.Boolean(), default=False)

    # has the language analysis workflow completed successfully?
    language_analysis_complete = db.Column(db.Boolean(), default=False)

    # did the LLM submission step fail? Separate boolean so the UI can query it directly without
    # parsing the JSON blob. Only set for LLM inference / JSON parsing failures; not for
    # statistical computation errors, which are recorded in language_analysis['errors'].
    llm_analysis_failed = db.Column(db.Boolean(), default=False)

    # human-readable reason for LLM failure, for display to administrators
    llm_failure_reason = db.Column(db.Text(), default=None)

    # did the feedback LLM step fail?
    llm_feedback_failed = db.Column(db.Boolean(), default=False)

    # human-readable reason for feedback LLM failure, for display to administrators
    llm_feedback_failure_reason = db.Column(db.Text(), default=None)

    # LLM pipeline provenance — captured at submission time so past runs can be
    # evaluated if a larger model or larger context window becomes available later.
    llm_model_name = db.Column(db.String(200, collation="utf8_bin"), nullable=True)
    llm_context_size = db.Column(db.Integer(), nullable=True)
    llm_num_chunks = db.Column(db.Integer(), nullable=True)

    # RISK FACTORS
    # JSON blob recording which risk conditions are present and whether each has been resolved.
    # Using a JSON blob allows new risk factor types to be added without schema changes.
    # Schema per factor key:
    #   { "present": bool, "resolved": bool, "resolved_by_id": int|null,
    #     "resolved_at": str|null (ISO datetime), "annotation": str|null,
    #     ... factor-specific fields ... }
    risk_factors = db.Column(db.Text(), default=None)

    # MARKING WORKFLOW

    # assigned supervision grade (determined from SubmissionRole instances by some conflation rule)
    supervision_grade = db.Column(db.Numeric(8, 3), default=None)

    # who back-populated the supervision grade from a ConflationReport?
    supervision_generated_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    supervision_generated_by = db.relationship(
        "User", foreign_keys=[supervision_generated_id], uselist=False
    )

    # when was the supervision grade back-populated?
    supervision_generated_timestamp = db.Column(db.DateTime())

    # assigned report grade (determined from SubmissionRole instances by some conflation rule)
    report_grade = db.Column(db.Numeric(8, 3), default=None)

    # who back-populated the report grade from a ConflationReport?
    report_generated_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    report_generated_by = db.relationship(
        "User", foreign_keys=[report_generated_id], uselist=False
    )

    # when was the report grade back-populated?
    report_generated_timestamp = db.Column(db.DateTime())

    # assigned presentation grade (from 'presentation' target in a ConflationReport)
    presentation_grade = db.Column(db.Numeric(8, 3), default=None)

    # who back-populated the presentation grade from a ConflationReport?
    presentation_generated_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    presentation_generated_by = db.relationship(
        "User", foreign_keys=[presentation_generated_id], uselist=False
    )

    # when was the presentation grade back-populated?
    presentation_generated_timestamp = db.Column(db.DateTime())

    # GRADE PROVENANCE: which MarkingEvent was used to populate each grade?
    # These are cross-references (not ownership FKs), recorded when _propagate_grade_to_records() runs.

    supervision_event_id = db.Column(
        db.Integer(), db.ForeignKey("marking_events.id"), nullable=True
    )
    supervision_event = db.relationship(
        "MarkingEvent", foreign_keys="SubmissionRecord.supervision_event_id", uselist=False
    )

    report_event_id = db.Column(
        db.Integer(), db.ForeignKey("marking_events.id"), nullable=True
    )
    report_event = db.relationship(
        "MarkingEvent", foreign_keys="SubmissionRecord.report_event_id", uselist=False
    )

    presentation_event_id = db.Column(
        db.Integer(), db.ForeignKey("marking_events.id"), nullable=True
    )
    presentation_event = db.relationship(
        "MarkingEvent", foreign_keys="SubmissionRecord.presentation_event_id", uselist=False
    )

    # CANVAS SYNCHRONIZATION

    # is a submission available for this student?
    # this flag is set (or cleared) by a periodically running Celery task
    canvas_submission_available = db.Column(db.Boolean(), default=False)

    # TURNITIN SYNCHRONIZATION

    # outcome reported by Turnitin
    turnitin_outcome = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
        default=None,
        nullable=True,
    )

    # final similarity score reported by Turnitin
    turnitin_score = db.Column(db.Integer(), default=None, nullable=True)

    # web overlap score reported by Turnitin
    turnitin_web_overlap = db.Column(db.Integer(), default=None, nullable=True)

    # publication overlap score reported by Turnitin
    turnitin_publication_overlap = db.Column(db.Integer(), default=None, nullable=True)

    # student overlap score reportd by Turnitin
    turnitin_student_overlap = db.Column(db.Integer(), default=None, nullable=True)

    # LIFECYCLE DATA

    # TODO: THE FIELDS BELOW ARE NOW OBSOLETE AND SHOULD EVENTUALLY BE REMOVED

    # has a feedback report geen generated?
    feedback_generated = db.Column(db.Boolean(), default=False)

    # feedback reports
    feedback_reports = db.relationship(
        "FeedbackReport",
        secondary=submission_record_to_feedback_report,
        lazy="dynamic",
        backref=db.backref("owner", uselist=False),
    )

    # has feedback been pushed out to the student for this period?
    feedback_sent = db.Column(db.Boolean(), default=False)

    # who pushed the feedback?
    feedback_push_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    feedback_push_by = db.relationship(
        "User", foreign_keys=[feedback_push_id], uselist=False
    )

    # timestamp when feedback was sent
    feedback_push_timestamp = db.Column(db.DateTime())

    # ROLES

    # 'roles' member created by back-reference from SubmissionRole

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = False
        self._warnings = False

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = False
        self._warnings = False

    @property
    def report_processing_failed(self) -> bool:
        """True if the report was uploaded but processing crashed without generating a processed_report."""
        return (
            self.report is not None
            and self.processed_report is None
            and bool(self.celery_failed)
        )

    @property
    def canvas_turnitin_refetchable(self) -> bool:
        """True if a Canvas Turnitin re-fetch is possible for this submission record."""
        return (
            self.period.canvas_enabled
            and self.owner is not None
            and self.owner.canvas_user_id is not None
        )

    @property
    def submission_period(self):
        return self.period.submission_period

    def belongs_to(self, period):
        return self.period_id == period.id

    @property
    def student_identifier(self):
        """
        Return a suitable student identifier. Markers should only see the candidate number,
        whereas admin users can see student names
        :return:
        """
        current_role = None
        for role in self.roles:
            if role.user_id == current_user.id:
                current_role = role
                break

        # roles associated with this submission always trump admin rights, even for 'root' and 'admin' users
        if current_role is not None:
            # marker roles, moderator roles, exam board and external examiners can only see exam number
            if current_role.role in [
                SubmissionRole.ROLE_MARKER,
                SubmissionRole.ROLE_MODERATOR,
                SubmissionRole.ROLE_EXAM_BOARD,
                SubmissionRole.ROLE_EXTERNAL_EXAMINER,
            ]:
                return self.owner.student.exam_number_label

            # supervision team  can see student name
            if current_role.role in [
                SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ]:
                return {"label": self.owner.student.user.name}

        # root, admin, and office roles can always see student name; so can project convenor or co-convenors
        if (
            current_user.has_role("root")
            or current_user.has_role("admin")
            or current_user.has_role("office")
            or self.pclass.is_convenor(current_user.id)
        ):
            return {"label": self.owner.student.user.name}

        # by default, other users see only the exam number
        return self.owner.student.exam_number_label

    def get_roles(self, role: str) -> List[SubmissionRole]:
        """
        Return attached SubmissionRole instances for role type 'role'
        :param role: specified role type
        :return:
        """
        role = role.lower()
        role_map = {
            "supervisor": [
                SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ],
            "marker": [SubmissionRole.ROLE_MARKER],
            "moderator": [SubmissionRole.ROLE_MODERATOR],
        }

        if role not in role_map:
            raise KeyError(
                'Unknown role "{role}" in SubmissionRecord.get_roles()'.format(
                    role=role
                )
            )

        role_ids = role_map[role]
        return [r for r in self.roles if r.role in role_ids]

    def get_role_ids(self, role: str) -> Set[int]:
        """
        Return a set of user ids for User instances obtained from get_roles()
        :return:
        """
        return set(u.user.id for u in self.get_roles(role))

    def get_role_user(self, role, user):
        """
        Return SubmissionRole instance for role=<role> and specified user
        :param role:
        :param user:
        :return:
        """
        if isinstance(user, User):
            _user_id = user.id
        elif isinstance(user, FacultyData):
            _user_id = user.id
        elif isinstance(user, int):
            _user_id = user
        else:
            raise RuntimeError(
                "Unexpected user object passed to SubmissionRecord.get_role_user()"
            )

        roles = self.get_roles(role)
        for role in roles:
            role: SubmissionRole
            if role.user_id == _user_id:
                return role

        return None

    def get_role(self, user) -> SubmissionRole:
        """
        Return SubmissionRole instance for specified user, if one exists
        :param user:
        :return:
        """
        if isinstance(user, User):
            _user_id = user.id
        elif isinstance(user, FacultyData):
            _user_id = user.id
        elif isinstance(user, int):
            _user_id = user
        else:
            raise RuntimeError(
                "Unexpected user object passed to SubmissionRecord.get_role()"
            )

        for role in self.roles:
            role: SubmissionRole
            if role.user_id == _user_id:
                return role

        return None

    @property
    def supervisor_roles(self) -> List[SubmissionRole]:
        """
        Convenience function for get_roles() with role='supervisor'
        :return:
        """
        return self.get_roles("supervisor")

    @property
    def supervisor_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='supervisor'
        :return:
        """
        return self.get_role_ids("supervisor")

    def get_supervisor(self, user):
        """
        Convenience function to get the SubmissionRole record for a specific user with role='supervisor'
        :param user:
        :return:
        """
        return self.get_role_user("supervisor", user)

    @property
    def marker_roles(self) -> List[SubmissionRole]:
        """
        Convenience function for get_roles() with role='marker'
        :return:
        """
        return self.get_roles("marker")

    @property
    def marker_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='marker'
        :return:
        """
        return self.get_role_ids("marker")

    def get_marker(self, user):
        """
        Convenience function to get the SubmissionRole record for a specific user with role='marker'
        :param user:
        :return:
        """
        return self.get_role_user("marker", user)

    @property
    def moderator_roles(self) -> List[SubmissionRole]:
        """
        Convenience function for get_roles() with role='moderator'
        :return:
        """
        return self.get_roles("moderator")

    @property
    def moderator_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='moderator'
        :return:
        """
        return self.get_role_ids("moderator")

    def get_moderator(self, user):
        """
        Convenience function to get the SubmissionRole record for a specific user with role='moderator'
        :param user:
        :return:
        """
        return self.get_role_user("supervisor", user)

    def _role_feedback_valid(self, roles: List[SubmissionRole]):
        for role in roles:
            role: SubmissionRole

            if role.positive_feedback is None or len(role.positive_feedback) == 0:
                return False

            if (
                role.improvements_feedback is None
                or len(role.improvements_feedback) == 0
            ):
                return False

        return True

    def _role_feedback_submitted(self, roles: List[SubmissionRole]):
        for role in roles:
            role: SubmissionRole

            if not role.submitted_feedback:
                return False

        return True

    @property
    def is_supervisor_feedback_valid(self):
        return self._role_feedback_valid(self.supervisor_roles)

    @property
    def is_marker_feedback_valid(self):
        return self._role_feedback_valid(self.marker_roles)

    @property
    def is_supervisor_feedback_submitted(self):
        return self._role_feedback_submitted(self.supervisor_roles)

    @property
    def is_marker_feedback_submitted(self):
        return self._role_feedback_submitted(self.marker_roles)

    def is_presentation_assessor_valid(self, fac):
        # find ScheduleSlot to check that current user is actually required to submit feedback
        if isinstance(fac, int):
            fac_id = fac
        elif isinstance(fac, FacultyData) or isinstance(fac, User):
            fac_id = fac.id
        else:
            raise RuntimeError(
                "Unknown faculty id type passed to get_supervisor_records()"
            )

        slot = self.schedule_slot
        if get_count(slot.assessors.filter_by(id=fac_id)) == 0:
            return None

        feedback = self.presentation_feedback.filter_by(assessor_id=fac_id).first()

        if feedback is None:
            return False

        if feedback.positive is None or len(feedback.positive) == 0:
            return False

        if feedback.negative is None or len(feedback.negative) == 0:
            return False

        return True

    def presentation_assessor_submitted(self, fac):
        if isinstance(fac, int):
            fac_id = fac
        elif isinstance(fac, FacultyData) or isinstance(fac, User):
            fac_id = fac.id
        else:
            raise RuntimeError(
                "Unknown faculty id type passed to get_supervisor_records()"
            )

        # find ScheduleSlot to check that current user is actually required to submit feedback
        slot = self.schedule_slot
        if get_count(slot.assessors.filter_by(id=fac_id)) == 0:
            return None

        feedback = self.presentation_feedback.filter_by(assessor_id=fac_id).first()
        if feedback is None:
            return False

        return feedback.submitted

    @property
    def is_feedback_valid(self):
        return self.is_supervisor_feedback_valid or self.is_marker_feedback_valid

    def _feedback_state(self, valid, submitted):
        period = self.period

        if not period.config.project_class.publish:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        if not period.is_feedback_open:
            return SubmissionRecord.FEEDBACK_NOT_YET

        if submitted:
            return SubmissionRecord.FEEDBACK_SUBMITTED

        if valid:
            return SubmissionRecord.FEEDBACK_ENTERED

        if not period.closed:
            return SubmissionRecord.FEEDBACK_WAITING

        return SubmissionRecord.FEEDBACK_LATE

    @property
    def uses_supervisor_feedback(self):
        return self.period.uses_supervisor_feedback

    @property
    def uses_marker_feedback(self):
        return self.period.uses_marker_feedback

    @property
    def uses_presentation_feedback(self):
        return self.period.uses_presentation_feedback

    @property
    def supervisor_feedback_state(self):
        if not self.uses_supervisor_feedback:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        return self._feedback_state(
            self.is_supervisor_feedback_valid, self.is_supervisor_feedback_submitted
        )

    @property
    def marker_feedback_state(self):
        if not self.uses_marker_feedback:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        return self._feedback_state(
            self.is_marker_feedback_valid, self.is_marker_feedback_submitted
        )

    @property
    def presentation_feedback_late(self):
        if not self.uses_presentation_feedback:
            return False

        if not self.period.config.project_class.publish:
            return False

        slot = self.schedule_slot
        if slot is None:
            return False

        states = [
            self.presentation_feedback_state(a.id) == SubmissionRecord.FEEDBACK_LATE
            for a in slot.assessors
        ]
        return any(states)

    def presentation_feedback_state(self, faculty_id):
        if not self.period.has_presentation:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        if not self.period.config.project_class.publish:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        slot = self.schedule_slot
        count = get_count(slot.assessors.filter_by(id=faculty_id))
        if count == 0:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        closed = slot.owner.owner.is_closed

        today = date.today()
        if today <= slot.session.date:
            return SubmissionRecord.FEEDBACK_NOT_YET

        if not self.is_presentation_assessor_valid(faculty_id):
            return (
                SubmissionRecord.FEEDBACK_LATE
                if closed
                else SubmissionRecord.FEEDBACK_WAITING
            )

        if not self.presentation_assessor_submitted(faculty_id):
            return (
                SubmissionRecord.FEEDBACK_LATE
                if closed
                else SubmissionRecord.FEEDBACK_ENTERED
            )

        return SubmissionRecord.FEEDBACK_SUBMITTED

    @property
    def supervisor_response_state(self):
        supervisor_roles = [
            role
            for role in self.roles
            if role.role
            in [
                SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ]
        ]
        if not supervisor_roles:
            return SubmissionRecord.FEEDBACK_NOT_REQUIRED

        states = [role._supervisor_response_state for role in supervisor_roles]
        if any(s == SubmissionRecord.FEEDBACK_LATE for s in states):
            return SubmissionRecord.FEEDBACK_LATE
        return max(states)

    @property
    def feedback_submitted(self):
        """
        Determines whether any feedback is available, irrespective of whether it is visible to the student
        :return:
        """
        if self.period.has_presentation:
            for feedback in self.presentation_feedback:
                if feedback.submitted:
                    return True

        allowed_roles = [
            SubmissionRole.ROLE_SUPERVISOR,
            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            SubmissionRole.ROLE_MARKER,
        ]
        return any(
            role.submitted_feedback for role in self.roles if role.role in allowed_roles
        )

    @property
    def has_feedback(self):
        """
        Determines whether feedback should be offered to the student
        :return:
        """

        # is there any presentation feedback available? (legacy infrastructure)
        flag: bool = False
        if self.period.has_presentation:
            allowed_roles = [
                SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
            ]
            flag = flag | any(
                role.submitted_feedback
                for role in self.roles
                if role.role in allowed_roles
            )

        # otherwise, is there any feedback available from other supervision/marker roles? (legacy infrastructure)
        if self.period.closed:
            allowed_roles = [
                SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                SubmissionRole.ROLE_MARKER,
            ]
            flag = flag | any(
                role.submitted_feedback
                for role in self.roles
                if role.role in allowed_roles
            )

        if flag:
            return True

        # new infrastructure: check for closed MarkingEvents with a SubmitterReport at a
        # sufficiently advanced workflow state
        from .markingevent import (
            MarkingEvent,
            MarkingWorkflow,
            SubmitterReport,
            SubmitterReportWorkflowStates,
        )

        closed_events = (
            db.session.query(MarkingEvent)
            .filter_by(period_id=self.period_id, closed=True)
            .all()
        )
        for event in closed_events:
            sr = (
                self.submitter_reports.join(
                    MarkingWorkflow, SubmitterReport.workflow_id == MarkingWorkflow.id
                )
                .filter(MarkingWorkflow.event_id == event.id)
                .first()
            )
            if (
                sr is not None
                and sr.workflow_state
                >= SubmitterReportWorkflowStates.READY_TO_GENERATE_FEEDBACK
            ):
                return True

        return False

    @property
    def has_feedback_to_push(self):
        if not self.feedback_generated:
            return False

        return self.has_feedback

    @property
    def number_presentation_feedback(self):
        return get_count(self.presentation_feedback)

    @property
    def number_submitted_presentation_feedback(self):
        return get_count(self.presentation_feedback.filter_by(submitted=True))

    @property
    def can_assign_feedback(self):
        if not self.period.has_presentation:
            return False

        slot = self.schedule_slot
        if slot is None:
            return True

        space = False
        for assessor in slot.assessors:
            if (
                get_count(self.presentation_feedback.filter_by(assessor_id=assessor.id))
                == 0
            ):
                space = True
                break

        return space

    @property
    def current_config(self):
        return self.owner.config

    @property
    def selector_config(self):
        # if we already have a cached record of the ProjectClassConfig that was used during selection, use that
        if self.selection_config:
            return self.selection_config

        # otherwise, we have to work it out "by hand"
        current_config: ProjectClassConfig = self.current_config

        if current_config.select_in_previous_cycle:
            return current_config.previous_config

        return current_config

    @property
    def pclass_id(self):
        return self.current_config.pclass_id

    @property
    def pclass(self):
        return self.current_config.project_class

    @property
    def supervising_CATS(self):
        # TODO: consider whether we really need this method
        if self.project is not None:
            return self.project.CATS_supervision

        return 0

    @property
    def marking_CATS(self):
        # TODO: consider whether we really need this method
        if self.project is not None:
            return self.project.CATS_marking

        return 0

    @property
    def moderation_CATS(self):
        # TODO: consider whether we really need this method
        if self.project is not None:
            return self.project.CATS_moderation

        return 0

    @property
    def assessor_CATS(self):
        # TODO: consider whether we really need this method
        return self.project.CATS_presentation

    @property
    def schedule_slot(self):
        from .scheduling import ScheduleAttempt, ScheduleSlot

        if not self.period.has_deployed_schedule:
            return None

        query = (
            db.session.query(submitter_to_slots.c.slot_id)
            .filter(submitter_to_slots.c.submitter_id == self.id)
            .subquery()
        )

        slot_query = (
            db.session.query(ScheduleSlot)
            .join(query, query.c.slot_id == ScheduleSlot.id)
            .join(ScheduleAttempt, ScheduleAttempt.id == ScheduleSlot.owner_id)
            .filter(ScheduleAttempt.deployed.is_(True))
        )

        slots = get_count(slot_query)
        if slots > 1:
            raise RuntimeError(
                "Too many deployed ScheduleSlot instances attached to a SubmissionRecord"
            )
        elif slots == 0:
            return None

        return slot_query.first()

    @property
    def presentation_assessor_roles(self) -> List[SubmissionRole]:
        """
        Return all SubmissionRole instances with role ROLE_PRESENTATION_ASSESSOR
        """
        return [
            r for r in self.roles if r.role == SubmissionRole.ROLE_PRESENTATION_ASSESSOR
        ]

    def presentation_assessor_roles_by_slot(self) -> List[tuple]:
        """
        Return PRESENTATION_ASSESSOR SubmissionRole instances grouped by ScheduleSlot.
        Returns a list of (slot, [roles]) pairs in first-seen order.
        """
        groups: dict = {}
        slot_order: list = []

        for role in self.roles:
            if role.role == SubmissionRole.ROLE_PRESENTATION_ASSESSOR:
                slot = role.schedule_slot
                if slot not in groups:
                    groups[slot] = []
                    slot_order.append(slot)
                groups[slot].append(role)

        return [(slot, groups[slot]) for slot in slot_order]

    @property
    def has_scheduled_presentation_slots(self) -> bool:
        """
        Returns True if this SubmissionRecord has any PRESENTATION_ASSESSOR roles
        with an associated ScheduleSlot.
        """
        return any(
            role.schedule_slot is not None
            for role in self.roles
            if role.role == SubmissionRole.ROLE_PRESENTATION_ASSESSOR
        )

    def is_in_assessor_pool(self, fac_id):
        """
        Determine whether a given faculty member is in the assessor pool for this submission
        :param fac_id:
        :return:
        """
        return get_count(self.project.assessors.filter_by(id=fac_id)) > 0

    def _build_submitted_attachment_query(
        self,
        role: Optional[int] = None,
        allowed_users: Optional[List[User]] = None,
        allowed_roles: Optional[List[Role]] = None,
        ordering: Optional[List] = None,
    ):
        from .assets import SubmittedAsset

        allowed_user_ids = (
            [x.id for x in allowed_users] if allowed_users is not None else None
        )
        allowed_role_ids = (
            [x.id for x in allowed_roles] if allowed_roles is not None else None
        )

        query = db.session.query(SubmissionAttachment).filter(
            SubmissionAttachment.parent_id == self.id
        )

        # Role-based filtering: include attachments that are either unrestricted (no entries in
        # submission_attachment_roles) or have an entry matching the requested role.
        if role is not None:
            restricted_ids = db.session.query(
                SubmissionAttachmentRole.attachment_id
            ).subquery()
            query = query.outerjoin(
                SubmissionAttachmentRole,
                and_(
                    SubmissionAttachmentRole.attachment_id == SubmissionAttachment.id,
                    SubmissionAttachmentRole.role == role,
                ),
            ).filter(
                or_(
                    ~SubmissionAttachment.id.in_(restricted_ids),
                    SubmissionAttachmentRole.role.isnot(None),
                )
            )

        query = (
            query.join(
                SubmittedAsset, SubmittedAsset.id == SubmissionAttachment.attachment_id
            )
            .join(submitted_acl, submitted_acl.c.asset_id == SubmittedAsset.id)
            .join(submitted_acr, submitted_acr.c.asset_id == SubmittedAsset.id)
            .join(User, User.id == submitted_acl.c.user_id)
            .join(Role, Role.id == submitted_acr.c.role_id)
        )

        conditions = []
        if allowed_user_ids is not None and len(allowed_user_ids) > 0:
            conditions.append(User.id.in_(allowed_user_ids))
        if allowed_role_ids is not None and len(allowed_role_ids) > 0:
            conditions.append(Role.id.in_(allowed_role_ids))

        # initial False is needed because or_ requires at least one argument, so we need something that evaluates to False if conditions is empty
        query = query.filter(or_(False, *conditions))

        if ordering is not None and len(ordering) > 0:
            query = query.order_by(*ordering)

        query = query.distinct()
        return query

    def _build_period_attachment_query(
        self,
        role: Optional[int] = None,
        allowed_users: Optional[List[User]] = None,
        allowed_roles: Optional[List[Role]] = None,
        ordering: Optional[List] = None,
    ):
        """
        Build a query returning PeriodAttachment instances for this record's parent period.

        :param role: If set, restrict to attachments visible to this role integer (from
            SubmissionRoleTypesMixin, including ROLE_STUDENT=7). Attachments with an empty
            role set are always included (unrestricted). Pass None to skip role filtering
            (used by admin/convenor views that may see all attachments).
        :param allowed_users: Asset-level ACL filter — only include assets accessible by one
            of these users.
        :param allowed_roles: Asset-level ACL filter — only include assets accessible by one
            of these Flask-Security roles.
        :param ordering: Optional SQLAlchemy ordering clauses.
        """
        from .assets import SubmittedAsset

        allowed_user_ids = (
            [x.id for x in allowed_users] if allowed_users is not None else None
        )
        allowed_role_ids = (
            [x.id for x in allowed_roles] if allowed_roles is not None else None
        )

        query = db.session.query(PeriodAttachment).filter(
            PeriodAttachment.parent_id == self.period.id
        )

        # Role-based filtering: include attachments that are either unrestricted (no entries in
        # period_attachment_roles) or have an entry matching the requested role.
        if role is not None:
            restricted_ids = db.session.query(
                PeriodAttachmentRole.attachment_id
            ).subquery()
            query = query.outerjoin(
                PeriodAttachmentRole,
                and_(
                    PeriodAttachmentRole.attachment_id == PeriodAttachment.id,
                    PeriodAttachmentRole.role == role,
                ),
            ).filter(
                or_(
                    ~PeriodAttachment.id.in_(
                        restricted_ids
                    ),  # unrestricted: no role entries at all
                    PeriodAttachmentRole.role.isnot(None),  # has a matching role entry
                )
            )

        query = (
            query.join(
                SubmittedAsset, SubmittedAsset.id == PeriodAttachment.attachment_id
            )
            .join(submitted_acl, submitted_acl.c.asset_id == SubmittedAsset.id)
            .join(submitted_acr, submitted_acr.c.asset_id == SubmittedAsset.id)
            .join(User, User.id == submitted_acl.c.user_id)
            .join(Role, Role.id == submitted_acr.c.role_id)
        )

        conditions = []
        if allowed_user_ids is not None and len(allowed_user_ids) > 0:
            conditions.append(User.id.in_(allowed_user_ids))
        if allowed_role_ids is not None and len(allowed_role_ids) > 0:
            conditions.append(Role.id.in_(allowed_role_ids))

        # initial False is needed because or_ requires at least one argument, so we need something that evaluates to False if conditions is empty
        query = query.filter(or_(False, *conditions))

        if ordering is not None and len(ordering) > 0:
            query = query.order_by(*ordering)

        query = query.distinct()
        return query

    @property
    def number_attachments(self):
        """
        Get total number of attachments for this record, including documents provided by the convenor
        and any uploaded report
        :return:
        """
        submission_attachments = self._build_submitted_attachment_query(
            role=None,
            allowed_users=[current_user],
            allowed_roles=current_user.roles,
        )
        period_attachments = self._build_period_attachment_query(
            role=None,
            allowed_users=[current_user],
            allowed_roles=current_user.roles,
        )

        return (
            get_count(submission_attachments)
            + get_count(period_attachments)
            + (
                1
                if (self.report is not None or self.processed_report is not None)
                else 0
            )
        )

    @property
    def number_attachments_internal(self):
        """
        Get total number of attachments only for this record. This excludes a report and any documents
        provided by the convenor
        :return:
        """
        return get_count(self.attachments)

    @property
    def ordered_attachments(self):
        from .assets import SubmittedAsset

        query = self._build_submitted_attachment_query(
            allowed_users=None,
            allowed_roles=None,
            ordering=[
                SubmissionAttachment.type.asc(),
                SubmittedAsset.target_name.asc(),
            ],
        )
        return query.all()

    @property
    def number_attachments_student(self):
        """
        Get total number of attachments for this record that are visible to the student.
        Students can only see documents they uploaded, or which have been made explicitly available to them.
        They can only see convenor-provided attachments that have been marked as 'publish to students'
        :return:
        """
        submission_attachments = self._build_submitted_attachment_query(
            role=SubmissionRoleTypesMixin.ROLE_STUDENT,
            allowed_users=[current_user],
            allowed_roles=current_user.roles,
        )
        period_attachments = self._build_period_attachment_query(
            role=SubmissionRoleTypesMixin.ROLE_STUDENT,
            allowed_users=[current_user],
            allowed_roles=current_user.roles,
        )

        return (
            get_count(submission_attachments)
            + get_count(period_attachments)
            + (
                1
                if (self.report is not None or self.processed_report is not None)
                else 0
            )
        )

    @property
    def article_list(self):
        from .content import (
            ConvenorSubmitterArticle,
            FormattedArticle,
            ProjectSubmitterArticle,
        )

        articles = with_polymorphic(
            FormattedArticle, [ConvenorSubmitterArticle, ProjectSubmitterArticle]
        )

        return db.session.query(articles).filter(
            or_(
                and_(
                    articles.ConvenorSubmitterArticle.published.is_(True),
                    articles.ConvenorSubmitterArticle.period_id == self.period_id,
                ),
                and_(
                    articles.ProjectSubmitterArticle.published.is_(True),
                    articles.ProjectSubmitterArticle.record_id == self.id,
                ),
            )
        )

    @property
    def has_articles(self):
        return self.article_list.first() is not None

    def get_event(
        self, template: "SupervisionEventTemplate"
    ) -> Optional["SupervisionEvent"]:
        if not isinstance(template, SupervisionEventTemplate):
            raise RuntimeError(
                f'Unknown template type "{type(template)}" passed to get_meeting()'
            )

        # find if anyone with a submission role for this record has an event matching this template
        return (
            db.session.query(SupervisionEvent)
            .select_from(SubmissionRole)
            .filter(SubmissionRole.submission_id == self.id)
            .join(SupervisionEvent, SupervisionEvent.owner_id == SubmissionRole.id)
            .filter(
                SupervisionEvent.unit_id == template.unit_id,
                SupervisionEvent.template_id == template.id,
            )
            .first()
        )

    def get_ordered_past_events(self, now: Optional[datetime] = None):
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(SubmissionRole, SubmissionRole.id == SupervisionEvent.owner_id)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SubmissionRole.submission_id == self.id,
                SubmissionPeriodUnit.end_date < now.date(),
            )
            .order_by(
                SubmissionPeriodUnit.end_date.desc(),
                SupervisionEvent.time.desc(),
                SupervisionEvent.name,
            )
        )

        return query

    def get_ordered_future_events(self, now: Optional[datetime] = None):
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(SubmissionRole, SubmissionRole.id == SupervisionEvent.owner_id)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SubmissionRole.submission_id == self.id,
                SubmissionPeriodUnit.start_date > now.date(),
            )
            .order_by(
                SubmissionPeriodUnit.start_date,
                SupervisionEvent.time,
                SupervisionEvent.name,
            )
        )

        return query

    def get_ordered_current_events(self, now: Optional[datetime] = None):
        if now is None:
            now = datetime.now()

        query = (
            db.session.query(SupervisionEvent)
            .join(SubmissionRole, SubmissionRole.id == SupervisionEvent.owner_id)
            .join(
                SubmissionPeriodUnit,
                SubmissionPeriodUnit.id == SupervisionEvent.unit_id,
            )
            .filter(
                SubmissionRole.submission_id == self.id,
                SubmissionPeriodUnit.start_date <= now.date(),
                SubmissionPeriodUnit.end_date >= now.date(),
            )
            .order_by(
                SubmissionPeriodUnit.start_date,
                SupervisionEvent.time,
                SupervisionEvent.name,
            )
        )

        return query

    def get_attendance_data(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        if now is None:
            now = datetime.now()

        attended_values = [
            SupervisionEvent.ATTENDANCE_ON_TIME,
            SupervisionEvent.ATTENDANCE_LATE,
        ]

        def in_past(event: SupervisionEvent):
            if event.time is not None:
                return event.time < now

            return event.unit.end_date < now.date()

        past_events = [e for e in self.events if e.monitor_attendance and in_past(e)]
        total_events_attended = sum(
            [e.attendance in attended_values for e in past_events]
        )
        total_events_recorded_attendance = sum(
            [e.attendance is not None for e in past_events]
        )
        total_events_missing_attendance = sum(
            [e.attendance is None for e in past_events]
        )

        return {
            "attendance": 100.0
            * float(total_events_attended)
            / float(total_events_recorded_attendance)
            if total_events_recorded_attendance > 0
            else nan,
            "total": len(past_events),
            "missing": total_events_missing_attendance,
            "recorded": total_events_recorded_attendance,
        }

    def number_events_with_attendance(self, now: Optional[datetime] = None):
        if now is None:
            now = datetime.now()

        query = self.get_ordered_past_events(now=now)
        query = query.filter(
            SupervisionEvent.monitor_attendance.is_(True),
            SupervisionEvent.attendance != None,
        )
        return get_count(query)

    def number_events_missing_attendance(self, now: Optional[datetime] = None):
        if now is None:
            now = datetime.now()

        query = self.get_ordered_past_events(now=now)
        query = query.filter(
            SupervisionEvent.monitor_attendance.is_(True),
            SupervisionEvent.attendance == None,
        )
        return get_count(query)

    def _check_access_control_groups(self, asset):
        from .assets import GeneratedAsset, SubmittedAsset

        asset: Union[SubmittedAsset, GeneratedAsset]
        modified = False

        allowed_roles = ["archive_reports"]
        for allowed_role in allowed_roles:
            if not asset.in_role_acl(allowed_role):
                asset.grant_role(allowed_role)
                modified = True

        return modified

    def _check_access_control_users(self, asset, allow_student=False):
        from .assets import GeneratedAsset, SubmittedAsset

        asset: Union[SubmittedAsset, GeneratedAsset]
        modified = False

        config: ProjectClassConfig = self.current_config

        supervisor_roles: List[SubmissionRole] = self.supervisor_roles
        marker_roles: List[SubmissionRole] = self.marker_roles
        moderator_roles: List[SubmissionRole] = self.moderator_roles

        supervisor_ids: Set[int] = set(role.user.id for role in supervisor_roles)
        marker_ids: Set[int] = set(role.user.id for role in marker_roles)
        moderator_ids: Set[int] = [role.user.id for role in moderator_roles]

        if config.uses_supervisor:
            for role in supervisor_roles:
                if not asset.has_access(role.user):
                    asset.grant_user(role.user)
                    modified = True

        if config.uses_marker:
            for role in marker_roles:
                if not asset.has_access(role.user):
                    asset.grant_user(role.user)
                    modified = True

        if config.uses_moderator:
            for role in moderator_roles:
                if not asset.has_access(role.user):
                    asset.grant_user(role.user)
                    modified = True

        for user in asset.access_control_list:
            # OK for assigned supervisors to have download rights
            if config.uses_supervisor and user.id in supervisor_ids:
                continue

            # OK for assigned markers to have download rights
            if config.uses_marker and user.id in marker_ids:
                continue

            # OK for assigned moderators to have download rights
            if config.uses_moderator and user.id in moderator_ids:
                continue

            # if allow_student flag is set, OK for student to download
            if allow_student and user.id == self.owner.student.id:
                continue

            # emit warning message to log
            print(
                "@@ Access control warning: Asset id={asset_id} (target={target}, unique_name={uniq}) for "
                "SubmissionRecord id={record_id} grants access to user {name} who does not have a supervisor, marker, or moderator "
                "role.".format(
                    asset_id=asset.id,
                    target=asset.target_name,
                    uniq=asset.unique_name,
                    record_id=self.id,
                    name=user.name,
                )
            )

        return modified

    def maintenance(self):
        """
        Fix (some) issues with record configuration.
        Ensures that asset access control is consistent with the role sets on each attachment
        and that all SubmissionRole holders can access the report and processed report.
        """
        from .assets import GeneratedAsset, SubmittedAsset
        from .users import User as _User

        modified = False
        all_submission_roles = list(self.roles)
        student_user: _User = self.owner.student.user

        def _ensure_asset_access(asset, include_student: bool) -> bool:
            """Ensure all SubmissionRole users can access this asset (report / processed report).
            Prefers role-based access; removes redundant user-based entries where possible.
            Student access is always user-based.
            """
            m = False
            for sr in all_submission_roles:
                user = sr.user
                if asset.has_role_access(user):
                    # user already has access via a role grant — remove redundant user entry
                    if asset.in_user_acl(user):
                        asset.revoke_user(user)
                        m = True
                elif not asset.in_user_acl(user):
                    asset.grant_user(user)
                    m = True
            # student access (always user-based for reports)
            if include_student:
                if not asset.has_access(student_user):
                    asset.grant_user(student_user)
                    m = True
            else:
                if asset.in_user_acl(student_user):
                    asset.revoke_user(student_user)
                    m = True
            # ensure archive_reports role is in the role ACR
            if not asset.in_role_acl("archive_reports"):
                asset.grant_role("archive_reports")
                m = True
            return m

        def _ensure_attachment_access(asset, role_set: set) -> bool:
            """Ensure correct access for a SubmissionAttachment asset.
            Only users whose SubmissionRole.role is in role_set (or all if role_set is empty)
            should have access. Student access is user-based only (never via role grant).
            """
            m = False
            if not role_set:
                authorized = all_submission_roles
            else:
                authorized = [sr for sr in all_submission_roles if sr.role in role_set]

            for sr in authorized:
                user = sr.user
                if asset.has_role_access(user):
                    # user already covered by a role grant — remove redundant user entry
                    if asset.in_user_acl(user):
                        asset.revoke_user(user)
                        m = True
                elif not asset.in_user_acl(user):
                    # grant user-based access (role-based would be too broad for per-submission docs)
                    asset.grant_user(user)
                    m = True

            # student: user-based only, never role-based
            student_should_have = SubmissionRoleTypesMixin.ROLE_STUDENT in role_set
            if student_should_have:
                if not asset.has_access(student_user):
                    asset.grant_user(student_user)
                    m = True
            else:
                if asset.in_user_acl(student_user):
                    asset.revoke_user(student_user)
                    m = True

            # ensure archive_reports role is in the role ACR
            if not asset.in_role_acl("archive_reports"):
                asset.grant_role("archive_reports")
                m = True
            return m

        # report: all SubmissionRole users + student
        if self.report is not None:
            modified |= _ensure_asset_access(self.report, include_student=True)

        # processed report: all SubmissionRole users, no student access
        if self.processed_report is not None:
            modified |= _ensure_asset_access(self.processed_report, include_student=False)

        # attachments: access controlled by each attachment's role_set
        for attachment in self.attachments:
            attachment: SubmissionAttachment
            if attachment.attachment is not None:
                modified |= _ensure_attachment_access(attachment.attachment, attachment.role_set)

        return modified

    # LANGUAGE ANALYSIS HELPERS

    @property
    def language_analysis_data(self) -> dict:
        """
        Deserialise the language_analysis JSON blob.
        Returns an empty dict if no analysis has been stored.
        """
        import json

        if self.language_analysis is None:
            return {}
        try:
            return json.loads(self.language_analysis)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_language_analysis_data(self, data: dict) -> None:
        """Serialise *data* and store it in the language_analysis column."""
        import json

        self.language_analysis = json.dumps(data)

    # RISK FACTOR HELPERS

    # Known risk factor type keys
    RISK_TURNITIN = "turnitin"
    RISK_AI_COMPLIANCE = "ai_compliance"
    RISK_AI_USE = "ai_use"
    RISK_DOCUMENT_LENGTH = "document_length"
    RISK_WORD_COUNT_DISCREPANCY = "word_count_discrepancy"

    ALL_RISK_TYPES = [
        RISK_TURNITIN,
        RISK_AI_COMPLIANCE,
        RISK_AI_USE,
        RISK_DOCUMENT_LENGTH,
        RISK_WORD_COUNT_DISCREPANCY,
    ]

    @property
    def risk_factors_data(self) -> dict:
        """Deserialise the risk_factors JSON blob. Returns an empty dict if nothing stored."""
        import json

        if self.risk_factors is None:
            return {}
        try:
            return json.loads(self.risk_factors)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_risk_factors_data(self, data: dict) -> None:
        """Serialise *data* and store in the risk_factors column."""
        import json

        self.risk_factors = json.dumps(data)

    @property
    def has_unresolved_risk_factors(self) -> bool:
        """Return True if any risk factor is present and unresolved."""
        data = self.risk_factors_data
        for key in self.ALL_RISK_TYPES:
            factor = data.get(key, {})
            if factor.get("present", False) and not factor.get("resolved", False):
                return True
        return False

    def get_present_risk_factors(self) -> list:
        """Return a list of (key, factor_dict) pairs for all present risk factors."""
        data = self.risk_factors_data
        return [(key, data[key]) for key in self.ALL_RISK_TYPES if data.get(key, {}).get("present", False)]

    def get_unresolved_risk_factors(self) -> list:
        """Return a list of (key, factor_dict) pairs for present, unresolved risk factors."""
        return [
            (key, factor)
            for key, factor in self.get_present_risk_factors()
            if not factor.get("resolved", False)
        ]

    def resolve_risk_factor(self, factor_type: str, user, annotation: str = None) -> None:
        """
        Mark a specific risk factor as resolved.

        :param factor_type: one of the RISK_* constants
        :param user: the User resolving the factor
        :param annotation: optional explanation text
        """
        from datetime import datetime

        data = self.risk_factors_data
        factor = data.get(factor_type, {})
        if factor:
            factor["resolved"] = True
            factor["resolved_by_id"] = user.id if user else None
            factor["resolved_at"] = datetime.now().isoformat()
            factor["annotation"] = annotation
            data[factor_type] = factor
            self.set_risk_factors_data(data)

    # Human-readable labels for each risk factor type
    RISK_FACTOR_LABELS = {
        RISK_TURNITIN: "Turnitin similarity",
        RISK_AI_COMPLIANCE: "AI compliance statement",
        RISK_AI_USE: "AI use metrics",
        RISK_DOCUMENT_LENGTH: "Document length",
        RISK_WORD_COUNT_DISCREPANCY: "Word count discrepancy",
    }

    def risk_factors_ui_summary(self) -> dict:
        """
        Return a dict with pre-computed UI summary data for the risk factors column.

        Structure:
          {
            "has_any_present": bool,
            "has_unresolved": bool,
            "unresolved_count": int,
            "resolved_count": int,
            "factors": [
              { "key": str, "label": str, "present": bool, "resolved": bool,
                "resolved_by_name": str|None, "resolved_at": str|None,
                "annotation": str|None }
            ]
          }
        """
        data = self.risk_factors_data
        factors = []
        for key in self.ALL_RISK_TYPES:
            factor = data.get(key, {})
            if not factor.get("present", False):
                continue
            resolved_by_name = None
            resolved_by_id = factor.get("resolved_by_id")
            if resolved_by_id:
                try:
                    user = db.session.query(User).filter_by(id=resolved_by_id).first()
                    if user:
                        resolved_by_name = user.name
                except Exception:
                    pass
            factors.append({
                "key": key,
                "label": self.RISK_FACTOR_LABELS.get(key, key),
                "present": True,
                "resolved": factor.get("resolved", False),
                "resolved_by_name": resolved_by_name,
                "resolved_at": factor.get("resolved_at"),
                "annotation": factor.get("annotation"),
            })
        unresolved = [f for f in factors if not f["resolved"]]
        resolved = [f for f in factors if f["resolved"]]
        return {
            "has_any_present": len(factors) > 0,
            "has_unresolved": len(unresolved) > 0,
            "unresolved_count": len(unresolved),
            "resolved_count": len(resolved),
            "factors": factors,
        }

    def grade_display_data(self) -> list:
        """
        Return a list of grade display dicts for supervision, report, and presentation grades.
        Each entry is always present (even when the grade is not yet set) so the template
        can render a consistent layout with "–" placeholders.

        Structure per entry:
          {
            "label": str,           — display label, e.g. "Supervision"
            "grade": float|None,    — grade value or None if not yet set
            "event_name": str|None, — name of the MarkingEvent that generated the grade, or None
            "event_timestamp": datetime|None  — creation timestamp of that event, or None
          }
        """
        entries = []
        grade_specs = [
            ("Supervision", self.supervision_grade, self.supervision_event),
            ("Report", self.report_grade, self.report_event),
        ]
        # Only include presentation if the project class uses presentations; we don't have
        # direct access to config here so always include it — the template can gate on pclass.
        grade_specs.append(("Presentation", self.presentation_grade, self.presentation_event))
        for label, grade, event in grade_specs:
            entries.append({
                "label": label,
                "grade": float(grade) if grade is not None else None,
                "event_name": event.name if event is not None else None,
                "event_timestamp": event.creation_timestamp if event is not None else None,
            })
        return entries

    def llm_metrics_for_display(self) -> dict:
        """
        Prepare structured display data for the LLM metrics section of the report page.
        Returns thresholds alongside measured values so templates can render progress bars
        without needing to know threshold constants.
        """
        la = self.language_analysis_data
        metrics = la.get("metrics", {})
        flags = la.get("flags", {})
        patterns = la.get("patterns", {})
        refs = la.get("references", {})
        timings = la.get("timings", {})
        llm_result = la.get("llm_result", {})

        flag_label = {"ok": "Normal", "note": "Elevated", "strong": "Strongly elevated"}
        flag_severity = {"ok": "success", "note": "warning", "strong": "danger"}

        def metric_entry(value, threshold, flag_key):
            flag = flags.get(flag_key, "ok")
            return {
                "value": value,
                "threshold": threshold,
                "flag": flag,
                "flag_label": flag_label.get(flag, flag),
                "flag_severity": flag_severity.get(flag, "secondary"),
                "elevated": flag in {"note", "strong"},
            }

        mattr = metrics.get("mattr")
        mtld = metrics.get("mtld")
        burstiness = metrics.get("burstiness")
        sentence_cv = metrics.get("sentence_cv")

        measured_words = metrics.get("word_count")
        stated_words = llm_result.get("stated_word_count") if llm_result.get("stated_word_count_found") else None

        rf = self.risk_factors_data
        wc_discrepancy = rf.get(self.RISK_WORD_COUNT_DISCREPANCY, {})

        return {
            "mattr": metric_entry(mattr, MATTR_NOTE_LOW_THRESHOLD, "mattr_flag"),
            "mtld": metric_entry(mtld, MTLD_NOTE_THRESHOLD, "mtld_flag"),
            "burstiness": metric_entry(burstiness, BURSTINESS_NOTE_LOW, "burstiness_flag"),
            "sentence_cv": metric_entry(sentence_cv, SENT_CV_NOTE_LOW, "sentence_cv_flag"),
            "hedging_count": patterns.get("hedging_total"),
            "filler_count": patterns.get("filler_total"),
            "em_dash_count": patterns.get("em_dash_count"),
            "measured_word_count": measured_words,
            "stated_word_count": stated_words,
            "discrepancy_pct": wc_discrepancy.get("discrepancy_pct"),
            "tolerance_pct": wc_discrepancy.get("tolerance_pct"),
            "reference_count": metrics.get("reference_count"),
            "uncited_refs": refs.get("uncited", []),
            "figure_count": metrics.get("figure_count"),
            "unreferenced_figures": refs.get("uncaptioned_figures", []),
            "table_count": metrics.get("table_count"),
            "unreferenced_tables": refs.get("uncaptioned_tables", []),
            "timings": {
                "extraction_s": timings.get("extraction_s"),
                "counting_s": timings.get("counting_s"),
                "ai_metrics_s": timings.get("ai_metrics_s"),
                "llm_grade_s": timings.get("llm_s"),
                "llm_feedback_s": timings.get("llm_feedback_s"),
            },
            "llm_model_name": self.llm_model_name,
            "llm_context_size": self.llm_context_size,
            "llm_num_chunks": self.llm_num_chunks,
        }

    def risk_factor_display_items(self) -> list:
        """
        Return a list of dicts prepared for rendering the resolve_risk_factors template.
        Each dict contains:
          key, label, present, resolved, resolved_by_name, resolved_at, annotation,
          severity ("danger"/"warning"), summary_items (list of (label, value) tuples for display)
        """
        data = self.risk_factors_data
        la = self.language_analysis_data
        metrics = la.get("metrics", {})
        flags = la.get("flags", {})
        llm_result = la.get("llm_result", {})

        items = []

        def _resolved_by_name(factor_dict):
            uid = factor_dict.get("resolved_by_id")
            if uid:
                user = db.session.query(User).filter_by(id=uid).first()
                return user.name if user else None
            return None

        # --- TURNITIN ---
        t = data.get(self.RISK_TURNITIN, {})
        if t.get("present", False):
            score = self.turnitin_score
            summary = [("Similarity score", f"{score}%" if score is not None else "—")]
            if self.turnitin_web_overlap is not None:
                summary.append(("Web overlap", f"{self.turnitin_web_overlap}%"))
            if self.turnitin_publication_overlap is not None:
                summary.append(("Publication overlap", f"{self.turnitin_publication_overlap}%"))
            if self.turnitin_student_overlap is not None:
                summary.append(("Student overlap", f"{self.turnitin_student_overlap}%"))
            items.append({
                "key": self.RISK_TURNITIN,
                "label": self.RISK_FACTOR_LABELS[self.RISK_TURNITIN],
                "present": True,
                "resolved": t.get("resolved", False),
                "resolved_by_name": _resolved_by_name(t),
                "resolved_at": t.get("resolved_at"),
                "annotation": t.get("annotation"),
                "severity": "danger",
                "description": "The Turnitin similarity score is ≥25%, which requires convenor review before marking can proceed.",
                "summary_items": summary,
            })

        # --- AI COMPLIANCE ---
        ac = data.get(self.RISK_AI_COMPLIANCE, {})
        if ac.get("present", False):
            statement = llm_result.get("genai_statement", "")
            summary = [("Detected statement", statement[:200] + "…" if len(statement) > 200 else statement)]
            items.append({
                "key": self.RISK_AI_COMPLIANCE,
                "label": self.RISK_FACTOR_LABELS[self.RISK_AI_COMPLIANCE],
                "present": True,
                "resolved": ac.get("resolved", False),
                "resolved_by_name": _resolved_by_name(ac),
                "resolved_at": ac.get("resolved_at"),
                "annotation": ac.get("annotation"),
                "severity": "warning",
                "description": "An AI/generative-AI compliance statement was detected in the document. Please review and confirm this has been noted.",
                "summary_items": summary,
            })

        # --- AI USE METRICS ---
        au = data.get(self.RISK_AI_USE, {})
        if au.get("present", False):
            elevated = au.get("elevated_metrics", [])
            metric_labels = {"mattr": "MATTR", "mtld": "MTLD", "burstiness": "Burstiness"}
            summary = []
            for m in ("mattr", "mtld", "burstiness"):
                flag = flags.get(f"{m}_flag", "ok")
                val = metrics.get(m)
                label_str = metric_labels.get(m, m)
                flag_str = {"ok": "Normal", "note": "Elevated", "strong": "Strongly elevated"}.get(flag, flag)
                summary.append((label_str, f"{val:.3f}" if val is not None else "—" + f" ({flag_str})"))
            items.append({
                "key": self.RISK_AI_USE,
                "label": self.RISK_FACTOR_LABELS[self.RISK_AI_USE],
                "present": True,
                "resolved": au.get("resolved", False),
                "resolved_by_name": _resolved_by_name(au),
                "resolved_at": au.get("resolved_at"),
                "annotation": au.get("annotation"),
                "severity": "warning",
                "description": f"Two or more AI-use metrics ({', '.join(metric_labels[m] for m in elevated)}) are elevated, which may indicate AI-assisted writing.",
                "summary_items": summary,
            })

        # --- DOCUMENT LENGTH ---
        dl = data.get(self.RISK_DOCUMENT_LENGTH, {})
        if dl.get("present", False):
            limit_type = dl.get("limit_type", "words")
            limit = dl.get("limit")
            measured = dl.get("measured")
            summary = [
                ("Limit type", limit_type.capitalize()),
                ("Configured limit", str(limit) if limit else "—"),
                ("Measured count", str(measured) if measured else "—"),
            ]
            items.append({
                "key": self.RISK_DOCUMENT_LENGTH,
                "label": self.RISK_FACTOR_LABELS[self.RISK_DOCUMENT_LENGTH],
                "present": True,
                "resolved": dl.get("resolved", False),
                "resolved_by_name": _resolved_by_name(dl),
                "resolved_at": dl.get("resolved_at"),
                "annotation": dl.get("annotation"),
                "severity": "warning",
                "description": f"The measured document {limit_type} count exceeds the configured limit.",
                "summary_items": summary,
            })

        # --- WORD COUNT DISCREPANCY ---
        wd = data.get(self.RISK_WORD_COUNT_DISCREPANCY, {})
        if wd.get("present", False):
            measured = wd.get("measured")
            stated = wd.get("stated")
            pct = wd.get("discrepancy_pct")
            tol = wd.get("tolerance_pct")
            summary = [
                ("Measured word count", str(measured) if measured else "—"),
                ("Student-reported word count", str(stated) if stated else "—"),
                ("Discrepancy", f"{pct:.1f}%" if pct is not None else "—"),
                ("Tolerance", f"{tol:.1f}%" if tol is not None else "—"),
            ]
            items.append({
                "key": self.RISK_WORD_COUNT_DISCREPANCY,
                "label": self.RISK_FACTOR_LABELS[self.RISK_WORD_COUNT_DISCREPANCY],
                "present": True,
                "resolved": wd.get("resolved", False),
                "resolved_by_name": _resolved_by_name(wd),
                "resolved_at": wd.get("resolved_at"),
                "annotation": wd.get("annotation"),
                "severity": "warning",
                "description": "The student-reported word count differs from the measured word count by more than the configured tolerance.",
                "summary_items": summary,
            })

        return items

    def compute_risk_factors(self, config) -> None:
        """
        Evaluate all risk conditions against current analysis data and configuration,
        then update the risk_factors JSON blob.

        Preserves existing resolved/resolved_by_id/resolved_at/annotation values for
        factors that remain present after re-evaluation.

        :param config: ProjectClassConfig instance providing word/page limit settings
        """
        la = self.language_analysis_data
        metrics = la.get("metrics", {})
        flags = la.get("flags", {})
        llm_result = la.get("llm_result", {})

        existing = self.risk_factors_data
        new_data = {}

        def _carry_resolution(key: str, factor: dict) -> dict:
            """Copy resolved/annotation fields from existing data if the factor is still present."""
            prev = existing.get(key, {})
            if prev.get("resolved", False):
                factor["resolved"] = True
                factor["resolved_by_id"] = prev.get("resolved_by_id")
                factor["resolved_at"] = prev.get("resolved_at")
                factor["annotation"] = prev.get("annotation")
            else:
                factor["resolved"] = False
                factor["resolved_by_id"] = None
                factor["resolved_at"] = None
                factor["annotation"] = None
            return factor

        # --- TURNITIN ---
        turnitin_score = self.turnitin_score
        turnitin_present = turnitin_score is not None and turnitin_score >= 25
        turnitin_factor = {"present": turnitin_present, "score": turnitin_score}
        if turnitin_present:
            turnitin_factor = _carry_resolution(self.RISK_TURNITIN, turnitin_factor)
        else:
            turnitin_factor.update({"resolved": False, "resolved_by_id": None, "resolved_at": None, "annotation": None})
        new_data[self.RISK_TURNITIN] = turnitin_factor

        # --- AI COMPLIANCE STATEMENT ---
        genai_found = llm_result.get("genai_statement_found", False)
        genai_factor = {
            "present": bool(genai_found),
            "statement_precis": llm_result.get("genai_statement", None),
        }
        if genai_found:
            genai_factor = _carry_resolution(self.RISK_AI_COMPLIANCE, genai_factor)
        else:
            genai_factor.update({"resolved": False, "resolved_by_id": None, "resolved_at": None, "annotation": None})
        new_data[self.RISK_AI_COMPLIANCE] = genai_factor

        # --- AI USE METRICS ---
        # Elevated if 2+ of {mattr_flag, mtld_flag, burstiness_flag, sentence_cv_flag} are "note" or "strong"
        elevated_thresholds = {"note", "strong"}
        elevated_metrics = [
            m
            for m in ("mattr", "mtld", "burstiness", "sentence_cv")
            if flags.get(f"{m}_flag", "ok") in elevated_thresholds
        ]
        ai_use_present = len(elevated_metrics) >= 2
        ai_use_factor = {"present": ai_use_present, "elevated_metrics": elevated_metrics}
        if ai_use_present:
            ai_use_factor = _carry_resolution(self.RISK_AI_USE, ai_use_factor)
        else:
            ai_use_factor.update({"resolved": False, "resolved_by_id": None, "resolved_at": None, "annotation": None})
        new_data[self.RISK_AI_USE] = ai_use_factor

        # --- DOCUMENT LENGTH ---
        measured_words = metrics.get("word_count", None)
        length_present = False
        length_factor = {"present": False, "limit_type": None, "limit": None, "measured": measured_words}
        if config is not None and measured_words is not None:
            if config.effective_word_limit_enabled and config.effective_word_limit:
                limit = config.effective_word_limit
                if measured_words > limit:
                    length_present = True
                    length_factor.update({"present": True, "limit_type": "words", "limit": limit})
            elif config.effective_page_limit_enabled and config.effective_page_limit:
                page_count = metrics.get("page_count", None)
                limit = config.effective_page_limit
                if page_count is not None and page_count > limit:
                    length_present = True
                    length_factor.update({"present": True, "limit_type": "pages", "limit": limit, "measured": page_count})
        if length_present:
            length_factor = _carry_resolution(self.RISK_DOCUMENT_LENGTH, length_factor)
        else:
            length_factor.update({"resolved": False, "resolved_by_id": None, "resolved_at": None, "annotation": None})
        new_data[self.RISK_DOCUMENT_LENGTH] = length_factor

        # --- WORD COUNT DISCREPANCY ---
        stated_found = llm_result.get("stated_word_count_found", False)
        stated_words = llm_result.get("stated_word_count", None) if stated_found else None
        tolerance = float(config.effective_word_count_tolerance) if config is not None else 0.15
        discrepancy_present = False
        discrepancy_pct = None
        if measured_words and stated_words and measured_words > 0:
            discrepancy_pct = abs(measured_words - stated_words) / measured_words
            discrepancy_present = discrepancy_pct > tolerance
        discrepancy_factor = {
            "present": discrepancy_present,
            "measured": measured_words,
            "stated": stated_words,
            "discrepancy_pct": round(discrepancy_pct * 100, 1) if discrepancy_pct is not None else None,
            "tolerance_pct": round(tolerance * 100, 1),
        }
        if discrepancy_present:
            discrepancy_factor = _carry_resolution(self.RISK_WORD_COUNT_DISCREPANCY, discrepancy_factor)
        else:
            discrepancy_factor.update({"resolved": False, "resolved_by_id": None, "resolved_at": None, "annotation": None})
        new_data[self.RISK_WORD_COUNT_DISCREPANCY] = discrepancy_factor

        self.set_risk_factors_data(new_data)

    @property
    def validate_documents(self):
        """
        Return a list of possible issues with the current SubmissionRecord.
        Access control correctness is now enforced by maintenance(); only non-access issues
        (missing report, unexpected license) are reported here.
        """
        from .content import AssetLicense

        messages = []

        # get license used for exam submission
        exam_license: AssetLicense = (
            db.session.query(AssetLicense).filter_by(abbreviation="Exam").first()
        )

        if self.period.closed and self.report is None:
            messages.append(
                "This submission period is closed, but no report has been uploaded."
            )

        if exam_license is not None:
            if self.report is not None and self.report.license_id != exam_license.id:
                messages.append(
                    'The uploaded report is tagged with an unexpected license type '
                    '"{license}"'.format(license=self.report.license.name)
                )
            if self.processed_report is not None and self.processed_report.license_id != exam_license.id:
                messages.append(
                    'The processed report is tagged with an unexpected license type '
                    '"{license}"'.format(license=self.processed_report.license.name)
                )

        return messages

    @property
    def is_valid(self):
        flag, self._errors, self._warnings = _SubmissionRecord_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def errors(self):
        if not self._validated:
            check = self.is_valid
        return self._errors.values()

    @property
    def warnings(self):
        if not self._validated:
            check = self.is_valid
        return self._warnings.values()


@listens_for(SubmissionRecord, "before_update")
def _SubmissionRecord_update_handler(mapper, connection, target):
    target._validated = False

    if target.owner is not None:
        target.owner._validated = False

    with db.session.no_autoflush:
        from .live_projects import _SubmittingStudent_is_valid

        cache.delete_memoized(_SubmissionRecord_is_valid, target.id)
        cache.delete_memoized(_SubmittingStudent_is_valid, target.owner_id)


@listens_for(SubmissionRecord, "before_insert")
def _SubmissionRecord_insert_handler(mapper, connection, target):
    target._validated = False

    if target.owner is not None:
        target.owner._validated = False

    with db.session.no_autoflush:
        from .live_projects import _SubmittingStudent_is_valid

        cache.delete_memoized(_SubmissionRecord_is_valid, target.id)
        cache.delete_memoized(_SubmittingStudent_is_valid, target.owner_id)


@listens_for(SubmissionRecord, "before_delete")
def _SubmissionRecord_delete_handler(mapper, connection, target):
    target._validated = False

    if target.owner is not None:
        target.owner._validated = False

    with db.session.no_autoflush:
        from .live_projects import _SubmittingStudent_is_valid

        cache.delete_memoized(_SubmissionRecord_is_valid, target.id)
        cache.delete_memoized(_SubmittingStudent_is_valid, target.owner_id)


class SubmissionAttachmentRole(db.Model):
    """
    Associates a SubmissionAttachment with one or more submission roles (integer constants from
    SubmissionRoleTypesMixin, including ROLE_STUDENT=7) that are permitted to access it.
    An empty role set means the attachment is unrestricted and visible to all participants.
    """

    __tablename__ = "submission_attachment_roles"

    attachment_id = db.Column(
        db.Integer(), db.ForeignKey("submission_attachments.id"), primary_key=True
    )
    # raw integer from SubmissionRoleTypesMixin; not a FK to another table
    role = db.Column(db.Integer(), primary_key=True)


class SubmissionAttachment(db.Model, SubmissionAttachmentTypesMixin):
    """
    Model an attachment to a submission
    """

    __tablename__ = "submission_attachments"

    # unique ID
    id = db.Column(db.Integer(), primary_key=True)

    # parent submission record, i.e., what submission is this attached to?
    parent_id = db.Column(
        db.Integer(), db.ForeignKey("submission_records.id"), nullable=False
    )
    parent = db.relationship(
        "SubmissionRecord",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref("attachments", lazy="dynamic"),
    )

    # attached file
    # TODO: in the longer term, this field should be renamed asset_id rather than attachment_id
    attachment_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), default=None
    )
    attachment = db.relationship(
        "SubmittedAsset",
        foreign_keys=[attachment_id],
        uselist=False,
        backref=db.backref("submission_attachment", uselist=False),
    )

    # textual description of attachment
    description = db.Column(db.Text())

    # LEGACY boolean flags — retained for data migration; replaced by role_records below
    publish_to_students = db.Column(db.Boolean(), default=False)
    include_marker_emails = db.Column(db.Boolean(), default=False)
    include_supervisor_emails = db.Column(db.Boolean(), default=False)

    # role-based access control
    role_records = db.relationship(
        "SubmissionAttachmentRole",
        foreign_keys=[SubmissionAttachmentRole.attachment_id],
        backref=db.backref("attachment", uselist=False),
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    @property
    def role_set(self) -> set:
        """Return the set of integer role values that may access this attachment."""
        return {r.role for r in self.role_records}

    def has_role_access(self, role: int) -> bool:
        """
        Return True if the given role integer may access this attachment.
        An empty role set means unrestricted (all roles may access).
        """
        roles = self.role_set
        return not roles or role in roles

    def has_role_access_for_set(self, role_set) -> bool:
        """
        Return True if any role in role_set may access this attachment.
        An empty role set on the attachment means unrestricted.
        Accepts any iterable (set, list, tuple).
        """
        my_roles = self.role_set
        return not my_roles or bool(my_roles & set(role_set))

    def set_roles(self, role_ints) -> None:
        """
        Replace the role set for this attachment.
        Pass an empty iterable to make the attachment unrestricted (visible to all roles).
        """
        self.role_records.delete()
        for r in role_ints:
            db.session.add(SubmissionAttachmentRole(attachment_id=self.id, role=r))


class PeriodAttachmentRole(db.Model):
    """
    Associates a PeriodAttachment with one or more submission roles (integer constants from
    SubmissionRoleTypesMixin, including ROLE_STUDENT=7) that are permitted to access it.
    An empty role set means the attachment is unrestricted and visible to all participants.
    """

    __tablename__ = "period_attachment_roles"

    attachment_id = db.Column(
        db.Integer(), db.ForeignKey("period_attachments.id"), primary_key=True
    )
    # raw integer from SubmissionRoleTypesMixin; not a FK to another table
    role = db.Column(db.Integer(), primary_key=True)


class PeriodAttachment(db.Model):
    """
    Model an attachment to a SubmissionPeriodRecord (eg. mark scheme)
    """

    __tablename__ = "period_attachments"

    # unique ID
    id = db.Column(db.Integer(), primary_key=True)

    # parent SubmissionPeriodRecord
    parent_id = db.Column(
        db.Integer(), db.ForeignKey("submission_periods.id"), nullable=False
    )
    parent = db.relationship(
        "SubmissionPeriodRecord",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref("attachments", lazy="dynamic"),
    )

    # attached file
    # TODO: in the longer term, this field should be renamed to asset_id rather than attachment_id
    attachment_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), default=None
    )
    attachment = db.relationship(
        "SubmittedAsset",
        foreign_keys=[attachment_id],
        uselist=False,
        backref=db.backref("period_attachment", uselist=False),
    )

    # publish to students (LEGACY — retained for data migration; use role_records instead)
    publish_to_students = db.Column(db.Boolean(), default=False)

    # include in marking notification emails sent to examiners? (LEGACY — retained for data migration)
    include_marker_emails = db.Column(db.Boolean(), default=False)

    # include in marking notification emails sent to project supervisors? (LEGACY — retained for data migration)
    include_supervisor_emails = db.Column(db.Boolean(), default=False)

    # textual description of attachment
    description = db.Column(db.Text())

    # rank order for inclusion in emails
    rank_order = db.Column(db.Integer())

    # role-based access control: which submission roles may access this attachment.
    # An empty role_records set means the attachment is unrestricted (visible to all roles).
    role_records = db.relationship(
        "PeriodAttachmentRole",
        foreign_keys=[PeriodAttachmentRole.attachment_id],
        backref=db.backref("attachment", uselist=False),
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    @property
    def role_set(self) -> set:
        """Return the set of integer role values that may access this attachment."""
        return {r.role for r in self.role_records}

    def has_role_access(self, role: int) -> bool:
        """
        Return True if the given role integer may access this attachment.
        An empty role set means unrestricted (all roles may access).
        """
        roles = self.role_set
        return not roles or role in roles

    def has_role_access_for_set(self, role_set) -> bool:
        """
        Return True if any role in role_set may access this attachment.
        An empty role set on the attachment means unrestricted (all roles may access).
        Accepts any iterable (set, list, tuple).
        """
        my_roles = self.role_set
        return not my_roles or bool(my_roles & set(role_set))

    def set_roles(self, role_ints) -> None:
        """
        Replace the role set for this attachment.
        Pass an empty iterable to make the attachment unrestricted (visible to all roles).
        """
        self.role_records.delete()
        for r in role_ints:
            db.session.add(PeriodAttachmentRole(attachment_id=self.id, role=r))


class Bookmark(db.Model):
    """
    Model an (orderable) bookmark
    """

    __tablename__ = "bookmarks"

    # unique ID for this bookmark
    id = db.Column(db.Integer(), primary_key=True)

    # id of owning SelectingStudent
    # note we tag the backref with 'delete-orphan' to ensure that orphaned bookmark records are automatically
    # removed from the database
    owner_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"))
    owner = db.relationship(
        "SelectingStudent",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "bookmarks", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    liveproject = db.relationship(
        "LiveProject",
        foreign_keys=[liveproject_id],
        uselist=False,
        backref=db.backref("bookmarks", lazy="dynamic"),
    )

    # rank in owner's list
    rank = db.Column(db.Integer())

    def format_project(self, **kwargs):
        return {"name": self.liveproject.name}

    def format_name(self, **kwargs):
        return {
            "name": self.owner.student.user.name,
            "email": self.owner.student.user.email,
        }

    @property
    def owner_email(self):
        return self.owner.student.user.email


@listens_for(Bookmark, "before_insert")
def _Bookmark_insert_handler(mapping, connection, target):
    with db.session.no_autoflush:
        from .live_projects import _SelectingStudent_is_valid

        cache.delete_memoized(_SelectingStudent_is_valid, target.owner_id)


@listens_for(Bookmark, "before_update")
def _Bookmark_update_handler(mapping, connection, target):
    with db.session.no_autoflush:
        from .live_projects import _SelectingStudent_is_valid

        cache.delete_memoized(_SelectingStudent_is_valid, target.owner_id)


@listens_for(Bookmark, "before_delete")
def _Bookmark_delete_handler(mapping, connection, target):
    with db.session.no_autoflush:
        from .live_projects import _SelectingStudent_is_valid

        cache.delete_memoized(_SelectingStudent_is_valid, target.owner_id)


class SelectionRecord(db.Model, SelectHintTypesMixin):
    """
    Model an ordered list of project selections
    """

    __tablename__ = "selections"

    # unique ID for this preference record
    id = db.Column(db.Integer(), primary_key=True)

    # id of owning SelectingStudent
    # note we tag the backref with 'delete-orphan' to ensure that orphaned selection records are automatically
    # removed from the database
    owner_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"))
    owner = db.relationship(
        "SelectingStudent",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "selections", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    liveproject = db.relationship(
        "LiveProject",
        foreign_keys=[liveproject_id],
        uselist=False,
        backref=db.backref("selections", lazy="dynamic"),
    )

    # rank in owner's list
    rank = db.Column(db.Integer())

    # was this record converted from a bookmark when selections were closed?
    converted_from_bookmark = db.Column(db.Boolean())

    # HINTING

    # convenor hint for this match
    hint = db.Column(db.Integer())

    @property
    def is_selectable(self):
        # generic projects are always selectable
        if self.liveproject.generic:
            return True

        if not self.liveproject.owner:
            # something is wrong; default to False
            return False

        # determine whether the project tagged in this selection is really selectable; eg. the supervisor
        # might now be marked on sabbatical or exempted
        record = self.liveproject.owner.get_enrollment_record(
            self.liveproject.config.pclass_id
        )
        return (
            record is not None
            and record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
        )

    def format_project(self, **kwargs):
        show_hint = kwargs.get("show_hint", True)

        if show_hint and self.hint in self._icons:
            tag = self._icons[self.hint]
        else:
            tag = ""

        if len(tag) > 0:
            tag += " "

        style = ""
        if self.hint == self.SELECTION_HINT_FORBID:
            style = "delete"

        return {"name": self.liveproject.name, "tag": tag, "style": style}

    def format_name(self, **kwargs):
        show_hint = kwargs.get("show_hint", True)

        if show_hint and self.hint in self._icons:
            tag = self._icons[self.hint]
        else:
            tag = ""

        if len(tag) > 0:
            tag += " "

        return {
            "name": self.owner.student.user.name,
            "email": self.owner.student.user.email,
            "tag": tag,
        }

    @property
    def owner_email(self):
        return self.owner.student.user.email

    @property
    def menu_order(self):
        return self._menu_order

    def menu_item(self, number):
        if number not in self._menu_items:
            return None

        if number in self._icons:
            tag = self._icons[number]

        value = self._menu_items[number]
        if len(tag) > 0:
            return f'<i class="fas fa-fw fa-{tag}"></i> {value}'

        return value

    def set_hint(self, hint):
        if (
            hint < SelectionRecord.SELECTION_HINT_NEUTRAL
            or hint > SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG
        ):
            return

        if self.hint == hint:
            return

        if hint == SelectionRecord.SELECTION_HINT_REQUIRE:
            # count number of other 'require' flags attached to this selector
            count = 0
            for item in self.owner.selections:
                if (
                    item.id != self.id
                    and item.hint == SelectionRecord.SELECTION_HINT_REQUIRE
                ):
                    count += 1

            # if too many, remove one
            target = self.owner.config.number_submissions
            if count >= target:
                for item in self.owner.selections:
                    if (
                        item.id != self.id
                        and item.hint == SelectionRecord.SELECTION_HINT_REQUIRE
                    ):
                        item.hint = SelectionRecord.SELECTION_HINT_NEUTRAL
                        count -= 1

                        if count < target:
                            break

        # note: database has to be committed separately
        self.hint = hint

    @property
    def has_hint(self):
        return self.hint != self.SELECTION_HINT_NEUTRAL


@listens_for(SelectionRecord, "before_update")
def _SelectionRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score)
        cache.delete_memoized(_MatchingAttempt_hint_status)

        from .live_projects import _SelectingStudent_is_valid

        cache.delete_memoized(_SelectingStudent_is_valid, target.owner_id)


@listens_for(SelectionRecord, "before_insert")
def _SelectionRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score)
        cache.delete_memoized(_MatchingAttempt_hint_status)

        from .live_projects import _SelectingStudent_is_valid

        cache.delete_memoized(_SelectingStudent_is_valid, target.owner_id)


@listens_for(SelectionRecord, "before_delete")
def _SelectionRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score)
        cache.delete_memoized(_MatchingAttempt_hint_status)

        from .live_projects import _SelectingStudent_is_valid

        cache.delete_memoized(_SelectingStudent_is_valid, target.owner_id)


class CustomOffer(db.Model, EditingMetadataMixin, CustomOfferStatesMixin):
    """
    Model a customized offer to an individual student
    """

    __tablename__ = "custom_offers"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # id of LiveProject for which this offer has been made
    # 'cascade' is set to delete-orphan, so the LiveProject record is the notional 'owner' of this one
    liveproject_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    liveproject = db.relationship(
        "LiveProject",
        foreign_keys=[liveproject_id],
        uselist=False,
        backref=db.backref(
            "custom_offers", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # id of SelectingStudent to whom this custom offer has been made
    selector_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"))
    selector = db.relationship(
        "SelectingStudent",
        foreign_keys=[selector_id],
        uselist=False,
        backref=db.backref("custom_offers", lazy="dynamic"),
    )

    # status of offer
    status = db.Column(
        db.Integer(), default=CustomOfferStatesMixin.OFFERED, nullable=False
    )

    # for specified submission period?
    # set to None if can be used for any period
    period_id = db.Column(
        db.Integer(),
        db.ForeignKey("period_definitions.id"),
        default=None,
        nullable=True,
    )
    period = db.relationship(
        "SubmissionPeriodDefinition", foreign_keys=[period_id], uselist=False
    )

    # document reason/explanation for offer
    comment = db.Column(db.Text())


class CustomOfferHint(db.Model, EditingMetadataMixin):
    """
    Hint suggesting that a CustomOffer should be made to a SelectingStudent, based on
    a previous supervision relationship discovered from retired SubmissionRecord history.
    Generated automatically after Go Live and after inject_liveproject.
    """

    __tablename__ = "custom_offer_hints"

    id = db.Column(db.Integer(), primary_key=True)

    # SelectingStudent in the current live cycle
    selector_id = db.Column(
        db.Integer(), db.ForeignKey("selecting_students.id"), index=True, nullable=False
    )
    selector = db.relationship(
        "SelectingStudent",
        foreign_keys=[selector_id],
        uselist=False,
        backref=db.backref("custom_offer_hints", lazy="dynamic"),
    )

    # Retired SubmissionRecord that triggered this hint
    submission_record_id = db.Column(
        db.Integer(), db.ForeignKey("submission_records.id"), nullable=False
    )
    submission_record = db.relationship(
        "SubmissionRecord",
        foreign_keys=[submission_record_id],
        uselist=False,
        backref=db.backref("custom_offer_hints", lazy="dynamic"),
    )

    # Denormalized faculty owner id (from submission_record.project.owner_id at hint creation time).
    # Avoids traversing the retired LiveProject chain at dashboard display time.
    faculty_id = db.Column(
        db.Integer(), db.ForeignKey("faculty_data.id"), nullable=False, index=True
    )
    faculty = db.relationship("FacultyData", foreign_keys=[faculty_id], uselist=False)

    __table_args__ = (
        db.UniqueConstraint(
            "selector_id",
            "submission_record_id",
            name="uq_custom_offer_hint_selector_record",
        ),
    )
