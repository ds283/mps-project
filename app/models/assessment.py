#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date

from sqlalchemy import and_, or_, orm
from sqlalchemy.event import listens_for

from ..cache import cache
from ..database import db
from ..shared.formatters import format_readable_time
from ..shared.sqlalchemy import get_count
from .associations import (
    assessment_to_periods,
    assessor_available_sessions,
    assessor_ifneeded_sessions,
    assessor_unavailable_sessions,
    session_to_rooms,
    submitter_available_sessions,
    submitter_unavailable_sessions,
)
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import (
    AvailabilityRequestStateMixin,
    EditingMetadataMixin,
    PresentationSessionTypesMixin,
)


@cache.memoize()
def _PresentationAssessment_is_valid(id):
    obj = db.session.query(PresentationAssessment).filter_by(id=id).one()

    errors = {}
    warnings = {}

    # CONSTRAINT 1 - assessment should have at least one submission period attached
    if get_count(obj.submission_periods) == 0:
        errors["periods"] = "No submission periods are attached to this assessment"

    # CONSTRAINT 2 - assessment should have at least one session
    if get_count(obj.sessions) == 0:
        warnings["sessions"] = "No sessions have been created for this assessment"

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


class PresentationAssessment(
    db.Model, EditingMetadataMixin, AvailabilityRequestStateMixin
):
    """
    Store data for a presentation assessment
    """

    __tablename__ = "presentation_assessments"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # year should match an available year in MainConfig
    year = db.Column(db.Integer(), db.ForeignKey("main_config.year"))
    main_config = db.relationship(
        "MainConfig",
        foreign_keys=[year],
        uselist=False,
        backref=db.backref("presentation_assessments", lazy="dynamic"),
    )

    # CONFIGURATION

    # name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # submission sessions to which we are attached
    # (should only be one PresentationAssessment instance attached per period record)
    submission_periods = db.relationship(
        "SubmissionPeriodRecord",
        secondary=assessment_to_periods,
        lazy="dynamic",
        backref=db.backref("presentation_assessments", lazy="dynamic"),
    )

    # AVAILABILITY LIFECYCLE

    # have we sent availability requests to faculty?
    requested_availability = db.Column(db.Boolean())

    # can availabilities still be modified?
    availability_closed = db.Column(db.Boolean())

    # what deadline has been set for availability information to be returned?
    availability_deadline = db.Column(db.Date())

    # have availability requests been skipped?
    skip_availability = db.Column(db.Boolean())

    # who skipped availability requests?
    availability_skipped_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    availability_skipped_by = db.relationship(
        "User", uselist=False, foreign_keys=[availability_skipped_id]
    )

    # requests skipped timestamp
    availability_skipped_timestamp = db.Column(db.DateTime())

    # ASSESSMENT LIFECYCLE

    # is this assessment closed?
    closed = db.Column(db.Boolean(), default=False, nullable=False)

    # feedback is open
    feedback_open = db.Column(db.Boolean())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = {}
        self._warnings = {}

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = {}
        self._warnings = {}

    @property
    def availability_lifecycle(self):
        if self.skip_availability:
            return AvailabilityRequestStateMixin.AVAILABILITY_SKIPPED

        if not self.requested_availability:
            return AvailabilityRequestStateMixin.AVAILABILITY_NOT_REQUESTED

        if not self.availability_closed:
            return AvailabilityRequestStateMixin.AVAILABILITY_REQUESTED

        return AvailabilityRequestStateMixin.AVAILABILITY_CLOSED

    @property
    def is_feedback_open(self):
        return self.feedback_open

    @property
    def is_closed(self):
        return self.cloed

    @property
    def availability_outstanding_count(self):
        return get_count(self.outstanding_assessors)

    def is_faculty_outstanding(self, faculty_id):
        return (
            get_count(self.outstanding_assessors.filter_by(faculty_id=faculty_id)) > 0
        )

    @property
    def outstanding_assessors(self):
        return self.assessor_list.filter_by(confirmed=False)

    @property
    def time_to_availability_deadline(self):
        if self.availability_deadline is None:
            return "<invalid>"

        today = date.today()
        if today > self.availability_deadline:
            return "in the past"

        delta = self.availability_deadline - today
        return format_readable_time(delta)

    @property
    def ordered_sessions(self):
        return self.sessions.order_by(
            PresentationSession.date.asc(),
            PresentationSession.session_type.asc(),
            PresentationSession.name.asc(),
        )

    @property
    def number_sessions(self):
        return get_count(self.sessions)

    @property
    def number_slots(self):
        return sum(s.number_slots for s in self.sessions)

    @property
    def number_rooms(self):
        return sum(s.number_rooms for s in self.sessions)

    @property
    def number_schedules(self):
        return get_count(self.scheduling_attempts)

    @property
    def number_talks(self):
        return sum(p.number_submitters for p in self.submission_periods)

    @property
    def number_not_attending(self):
        return get_count(self.submitter_list.filter_by(attending=False))

    @property
    def is_valid(self):
        """
        Perform validation
        :return:
        """
        flag, self._errors, self._warnings = _PresentationAssessment_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def has_errors(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0

    @property
    def has_warnings(self):
        if not self._validated:
            check = self.is_valid
        return len(self._warnings) > 0

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

    @property
    def available_periods(self):
        from .project_class import ProjectClass, ProjectClassConfig
        from .submissions import SubmissionPeriodRecord

        q = self.submission_periods.subquery()

        return (
            db.session.query(SubmissionPeriodRecord)
            .join(q, q.c.id == SubmissionPeriodRecord.id)
            .join(
                ProjectClassConfig,
                ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
            )
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
            .order_by(
                ProjectClass.name.asc(),
                ProjectClassConfig.year.asc(),
                SubmissionPeriodRecord.submission_period.asc(),
            )
            .all()
        )

    @property
    def available_pclasses(self):
        from .project_class import ProjectClass, ProjectClassConfig

        q = self.submission_periods.subquery()

        pclass_ids = (
            db.session.query(ProjectClass.id)
            .select_from(q)
            .join(ProjectClassConfig, ProjectClassConfig.id == q.c.config_id)
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(ProjectClass)
            .join(pclass_ids, ProjectClass.id == pclass_ids.c.id)
            .order_by(ProjectClass.name.asc())
            .all()
        )

    @property
    def convenor_list(self):
        from .faculty import FacultyData
        from .project_class import ProjectClass, ProjectClassConfig
        from .users import User

        q = self.submission_periods.subquery()

        convenor_ids = (
            db.session.query(ProjectClass.convenor_id)
            .select_from(q)
            .join(ProjectClassConfig, ProjectClassConfig.id == q.c.config_id)
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(FacultyData)
            .join(convenor_ids, FacultyData.id == convenor_ids.c.convenor_id)
            .join(User, User.id == FacultyData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
            .all()
        )

    @property
    def available_buildings(self):
        from .scheduling import Building, Room

        q = self.sessions.subquery()

        building_ids = (
            db.session.query(Room.building_id)
            .select_from(q)
            .join(session_to_rooms, session_to_rooms.c.session_id == q.c.id)
            .join(Room, Room.id == session_to_rooms.c.room_id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(Building)
            .join(building_ids, Building.id == building_ids.c.id)
            .order_by(Building.name.asc())
            .all()
        )

    @property
    def available_rooms(self):
        from .scheduling import Building, Room

        q = self.sessions.subquery()

        room_ids = (
            db.session.query(session_to_rooms.c.room_id)
            .select_from(q)
            .join(session_to_rooms, session_to_rooms.c.session_id == q.c.id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(Room)
            .join(room_ids, Room.id == room_ids.c.id)
            .join(Building, Building.id == Room.building_id)
            .order_by(Building.name.asc(), Room.name.asc())
            .all()
        )

    @property
    def available_sessions(self):
        return self.sessions.order_by(
            PresentationSession.date.asc(), PresentationSession.session_type.asc()
        ).all()

    @property
    def available_talks(self):
        from .live_projects import SubmittingStudent
        from .project_class import ProjectClass, ProjectClassConfig
        from .students import StudentData
        from .submissions import SubmissionPeriodRecord, SubmissionRecord
        from .users import User

        q = self.submitter_list.subquery()

        return (
            db.session.query(SubmissionRecord)
            .join(q, q.c.submitter_id == SubmissionRecord.id)
            .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
            .join(StudentData, StudentData.id == SubmittingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .join(
                SubmissionPeriodRecord,
                SubmissionPeriodRecord.id == SubmissionRecord.period_id,
            )
            .join(
                ProjectClassConfig,
                ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
            )
            .order_by(
                ProjectClassConfig.year.asc(),
                ProjectClassConfig.pclass_id.asc(),
                SubmissionPeriodRecord.submission_period.asc(),
                User.last_name.asc(),
                User.first_name.asc(),
            )
        )

    @property
    def schedulable_talks(self):
        talks = self.available_talks.all()
        return [
            t for t in talks if not self.not_attending(t.id) and t.project is not None
        ]

    @property
    def assessors_query(self):
        from .faculty import FacultyData
        from .users import User

        q = self.assessor_list.subquery()

        return (
            db.session.query(AssessorAttendanceData)
            .join(q, q.c.id == AssessorAttendanceData.id)
            .join(FacultyData, FacultyData.id == AssessorAttendanceData.faculty_id)
            .join(User, User.id == FacultyData.id)
            .filter(User.active.is_(True))
            .order_by(User.last_name.asc(), User.first_name.asc())
        )

    @property
    def ordered_assessors(self):
        return self.assessors_query.all()

    def not_attending(self, record_id):
        return (
            get_count(
                self.submitter_list.filter_by(submitter_id=record_id, attending=False)
            )
            > 0
        )

    def includes_faculty(self, faculty_id):
        return get_count(self.assessor_list.filter_by(faculty_id=faculty_id)) > 0

    def includes_submitter(self, submitter_id):
        return get_count(self.submitter_list.filter_by(submitter_id=submitter_id)) > 0

    @property
    def has_published_schedules(self):
        return get_count(self.scheduling_attempts.filter_by(published=True)) > 0

    @property
    def is_deployed(self):
        count = get_count(self.scheduling_attempts.filter_by(deployed=True))

        if count > 1:
            raise RuntimeError("Too many schedules deployed at once")

        return count == 1

    @property
    def deployed_schedule(self):
        count = get_count(self.scheduling_attempts.filter_by(deployed=True))

        if count > 1:
            raise RuntimeError("Too many schedules deployed at once")

        if count == 0:
            return None

        return self.scheduling_attempts.filter_by(deployed=True).one()

    @property
    def is_closable(self):
        if self.is_closed:
            return False

        if not self.is_deployed:
            return False

        schedule = self.deployed_schedule
        return schedule.is_closable

    def submitter_not_attending(self, sub):
        record = self.submitter_list.filter_by(submitter_id=sub.id).first()

        if record is None:
            return

        record.attending = False

    def submitter_attending(self, sub):
        record = self.submitter_list.filter_by(submitter_id=sub.id).first()

        if record is None:
            return

        record.attending = True

    def faculty_set_comment(self, fac, comment):
        data = self.assessor_list.filter_by(faculty_id=fac.id).first()
        if data is None:
            return

        data.comment = comment

    def faculty_get_comment(self, fac):
        data = self.assessor_list.filter_by(faculty_id=fac.id).first()
        if data is None:
            return

        return data.comment

    @property
    def earliest_date(self):
        q = self.sessions.subquery()

        record = (
            db.session.query(PresentationSession)
            .join(q, q.c.id == PresentationSession.id)
            .order_by(PresentationSession.date.asc())
            .first()
        )

        if record is None:
            return "<unknown>"

        return record.date.strftime("%a %d %b %Y")

    @property
    def latest_date(self):
        q = self.sessions.subquery()

        record = (
            db.session.query(PresentationSession)
            .join(q, q.c.id == PresentationSession.id)
            .order_by(PresentationSession.date.desc())
            .first()
        )

        if record is None:
            return "<unknown>"

        return record.date.strftime("%a %d %b %Y")


@listens_for(PresentationAssessment, "before_update")
def _PresentationAssessment_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.id)


@listens_for(PresentationAssessment, "before_insert")
def _PresentationAssessment_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.id)


@listens_for(PresentationAssessment, "before_delete")
def _PresentationAssessment_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.id)


@cache.memoize()
def _PresentationSession_is_valid(id):
    obj = db.session.query(PresentationSession).filter_by(id=id).one()

    errors = {}
    warnings = {}

    # CONSTRAINT 1 - sessions should be scheduled on a weekday
    if obj.date.weekday() >= 5:
        errors["weekday"] = "Session scheduled on a weekend"

    # CONSTRAINT 2 - if multiple sessions are scheduled on the same morning/afternoon then they need to have
    # distinguishing labels
    count = get_count(
        obj.owner.sessions.filter(
            and_(
                PresentationSession.date == obj.date,
                PresentationSession.session_type == obj.session_type,
                or_(
                    PresentationSession.name == None,
                    PresentationSession.name == obj.name,
                ),
            )
        )
    )

    if count != 1:
        lo_rec = (
            obj.owner.sessions.filter(
                and_(
                    PresentationSession.date == obj.date,
                    PresentationSession.session_type == obj.session_type,
                    or_(
                        PresentationSession.name == None,
                        PresentationSession.name == obj.name,
                    ),
                )
            )
            .order_by(
                PresentationSession.date.asc(),
                PresentationSession.session_type.asc(),
                PresentationSession.name.asc(),
            )
            .first()
        )

        if lo_rec is not None:
            if lo_rec.id == obj.id:
                errors["duplicate"] = "A duplicate copy of this session exists"
            else:
                errors["duplicate"] = "This session is a duplicate"

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


def _trim_session_list(list):
    data = {}
    changed = False

    for item in list:
        if item.id in data:
            data[item.id].append(item)
        else:
            data[item.id] = [item]

    for item_id in data:
        l = data[item_id]
        while len(l) > 1:
            list.remove(l[0])
            l.pop(0)
            changed = True

    return changed


class AssessorAttendanceData(db.Model):
    """
    Store data about an assessors attendance constraints, per session
    """

    __tablename__ = "assessor_attendance_data"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # faculty member for whom this attendance record exists
    faculty_id = db.Column(db.Integer(), db.ForeignKey("faculty_data.id"))
    faculty = db.relationship(
        "FacultyData",
        foreign_keys=[faculty_id],
        uselist=False,
        backref=db.backref("assessment_attendance", lazy="dynamic"),
    )

    # assessment that owns this availability record
    assessment_id = db.Column(
        db.Integer(), db.ForeignKey("presentation_assessments.id")
    )
    assessment = db.relationship(
        "PresentationAssessment",
        foreign_keys=[assessment_id],
        uselist=False,
        backref=db.backref(
            "assessor_list", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # sessions for which we are available
    available = db.relationship(
        "PresentationSession",
        secondary=assessor_available_sessions,
        lazy="dynamic",
        backref=db.backref("available_faculty", lazy="dynamic"),
    )

    # sessions for which we are unavailable
    unavailable = db.relationship(
        "PresentationSession",
        secondary=assessor_unavailable_sessions,
        lazy="dynamic",
        backref=db.backref("unavailable_faculty", lazy="dynamic"),
    )

    # sessions for which we are tagged 'if needed' -- ie strongly disfavour but available if required
    if_needed = db.relationship(
        "PresentationSession",
        secondary=assessor_ifneeded_sessions,
        lazy="dynamic",
        backref=db.backref("ifneeded_faculty", lazy="dynamic"),
    )

    # optional textual comment
    comment = db.Column(db.Text(), default=None)

    # has this assessor confirmed their response?
    confirmed = db.Column(db.Boolean(), default=False)

    # log a confirmation timestamp
    confirmed_timestamp = db.Column(db.DateTime())

    # over-ride session limit on a per-faculty basis
    assigned_limit = db.Column(db.Integer(), default=None)

    # has availability request email been sent?
    request_email_sent = db.Column(db.Boolean(), default=False)

    # availability request timestamp
    request_timestamp = db.Column(db.DateTime())

    # has a reminder email been sent?
    reminder_email_sent = db.Column(db.Boolean(), default=False)

    # when was last reminder email sent? NULL = no reminder yet issued
    last_reminder_timestamp = db.Column(db.DateTime())

    @property
    def number_available(self):
        return get_count(self.available)

    @property
    def number_unavailable(self):
        return get_count(self.unavailable)

    @property
    def number_ifneeded(self):
        return get_count(self.if_needed)

    def maintenance(self):
        changed = False

        changed = _trim_session_list(self.available) or changed
        changed = _trim_session_list(self.if_needed) or changed
        changed = _trim_session_list(self.unavailable) or changed

        for item in self.available:
            if item in self.unavailable:
                self.unavailable.remove(item)
                changed = True
            if item in self.if_needed:
                self.if_needed.remove(item)
                changed = True

        for item in self.if_needed:
            if item in self.unavailable:
                self.unavailable.remove(item)
                changed = True

        for sess in self.assessment.sessions:
            if (
                sess not in self.available
                and sess not in self.unavailable
                and sess not in self.if_needed
            ):
                self.available.append(sess)
                changed = True

        return changed


@listens_for(AssessorAttendanceData, "before_update")
def _AssessorAttendanceData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData, "before_insert")
def _AssessorAttendanceData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData, "before_delete")
def _AssessorAttendanceData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData.available, "append")
def _AssessorAttendanceData_available_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData.available, "remove")
def _AssessorAttendanceData_available_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData.unavailable, "append")
def _AssessorAttendanceData_unavailable_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData.unavailable, "remove")
def _AssessorAttendanceData_unavailable_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData.if_needed, "append")
def _AssessorAttendanceData_ifneeded_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(AssessorAttendanceData.if_needed, "remove")
def _AssessorAttendanceData_ifneeded_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


class SubmitterAttendanceData(db.Model):
    """
    Store data about a submitter's attendance constraints, per session
    """

    __tablename__ = "submitter_attendance_data"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # submitter for whom this attendance record exists
    submitter_id = db.Column(db.Integer(), db.ForeignKey("submission_records.id"))
    submitter = db.relationship(
        "SubmissionRecord",
        foreign_keys=[submitter_id],
        uselist=False,
        backref=db.backref(
            "assessment_attendance",
            lazy="dynamic",
            cascade="all, delete, delete-orphan",
        ),
    )

    # assessment that owns this availability record
    assessment_id = db.Column(
        db.Integer(), db.ForeignKey("presentation_assessments.id")
    )
    assessment = db.relationship(
        "PresentationAssessment",
        foreign_keys=[assessment_id],
        uselist=False,
        backref=db.backref(
            "submitter_list", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # in the make-up event?
    attending = db.Column(db.Boolean(), default=True)

    # sessions for which we are available
    available = db.relationship(
        "PresentationSession",
        secondary=submitter_available_sessions,
        lazy="dynamic",
        backref=db.backref("available_submitters", lazy="dynamic"),
    )

    # sessions for which we are unavailable
    unavailable = db.relationship(
        "PresentationSession",
        secondary=submitter_unavailable_sessions,
        lazy="dynamic",
        backref=db.backref("unavailable_submitters", lazy="dynamic"),
    )

    @property
    def number_available(self):
        return get_count(self.available)

    @property
    def number_unavailable(self):
        return get_count(self.unavailable)

    def maintenance(self):
        changed = False

        changed = _trim_session_list(self.available) or changed
        changed = _trim_session_list(self.unavailable) or changed

        for item in self.available:
            if item in self.unavailable:
                self.unavailable.remove(item)
                changed = True

        for sess in self.assessment.sessions:
            if sess not in self.available and sess not in self.unavailable:
                self.available.append(sess)
                changed = True

        return changed


@listens_for(SubmitterAttendanceData, "before_update")
def _SubmitterAttendanceData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(SubmitterAttendanceData, "before_insert")
def _SubmitterAttendanceData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(SubmitterAttendanceData, "before_delete")
def _SubmitterAttendanceData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(SubmitterAttendanceData.available, "append")
def _SubmitterAttendanceData_available_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(SubmitterAttendanceData.available, "remove")
def _SubmitterAttendanceData_available_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(SubmitterAttendanceData.unavailable, "append")
def _SubmitterAttendanceData_unavailable_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


@listens_for(SubmitterAttendanceData.unavailable, "remove")
def _SubmitterAttendanceData_unavailable_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.assessment_id)

        from .scheduling import (
            ScheduleAttempt,
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )

        schedules = db.session.query(ScheduleAttempt).filter_by(
            owner_id=target.assessment_id
        )
        for schedule in schedules:
            cache.delete_memoized(_ScheduleAttempt_is_valid, schedule.id)

            slots = db.session.query(ScheduleSlot).filter_by(owner_id=schedule.id)
            for slot in slots:
                cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)


class PresentationSession(
    db.Model, EditingMetadataMixin, PresentationSessionTypesMixin
):
    """
    Store data about a presentation session
    """

    __tablename__ = "presentation_sessions"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # assessment this session is part of
    owner_id = db.Column(db.Integer(), db.ForeignKey("presentation_assessments.id"))
    owner = db.relationship(
        "PresentationAssessment",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "sessions", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # label for this session
    name = db.Column(db.String(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")))

    # session date
    date = db.Column(db.Date())

    # morning or afternoon
    session_type = db.Column(db.Integer())

    # rooms available for this session
    rooms = db.relationship(
        "Room",
        secondary=session_to_rooms,
        lazy="dynamic",
        backref=db.backref("sessions", lazy="dynamic"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = {}
        self._warnings = {}

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = {}
        self._warnings = {}

    def make_label(self, text):
        return {"label": f"{text}", "style": None}

    @property
    def label(self):
        return self.make_label(self.label_as_string)

    @property
    def label_as_string(self) -> str:
        if self.name is not None:
            return f"{self.name} ({self._short_date_as_string}) {self._session_type_string}"

        return f"{self._short_date_as_string} {self._session_type_string}"

    @property
    def date_as_string(self):
        return self.date.strftime("%a %d %b %Y")

    @property
    def _short_date_as_string(self):
        return self.date.strftime("%d/%m/%Y")

    @property
    def _session_type_string(self):
        if self.session_type in PresentationSession.SESSION_TO_TEXT:
            type_string = PresentationSession.SESSION_TO_TEXT[self.session_type]
            return type_string

        return "<unknown>"

    @property
    def is_valid(self):
        flag, self._errors, self._warnings = _PresentationSession_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def has_errors(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0

    @property
    def has_warnings(self):
        if not self._validated:
            check = self.is_valid
        return len(self._warnings) > 0

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

    @property
    def ordered_rooms(self):
        from .scheduling import Building, Room

        query = (
            db.session.query(session_to_rooms.c.room_id)
            .filter(session_to_rooms.c.session_id == self.id)
            .subquery()
        )

        return (
            db.session.query(Room)
            .join(query, query.c.room_id == Room.id)
            .filter(Room.active.is_(True))
            .join(Building, Building.id == Room.building_id)
            .order_by(Building.name.asc(), Room.name.asc())
        )

    @property
    def number_available_faculty(self):
        return get_count(self.available_faculty)

    @property
    def number_ifneeded_faculty(self):
        return get_count(self.ifneeded_faculty)

    @property
    def number_unavailable_faculty(self):
        return get_count(self.unavailable_faculty)

    @property
    def number_submitters(self):
        return get_count(self.available_submitters)

    @property
    def number_available_submitters(self):
        return get_count(self.available_submitters)

    @property
    def number_unavailable_submitters(self):
        return get_count(self.unavailable_submitters)

    @property
    def number_rooms(self):
        return get_count(self.rooms)

    @property
    def number_slots(self):
        return sum(r.maximum_occupancy for r in self.rooms)

    @property
    def _faculty(self):
        from .faculty import FacultyData

        q = self.available_assessors.subquery()

        return db.session.query(FacultyData).join(q, q.c.faculty_id == FacultyData.id)

    @property
    def _submitters(self):
        from .submissions import SubmissionRecord

        q = self.available_submitters.subquery()

        return db.session.query(SubmissionRecord).join(
            q, q.c.submitter_id == SubmissionRecord.id
        )

    @property
    def ordered_faculty(self):
        from .faculty import FacultyData
        from .users import User

        return self._faculty.join(User, User.id == FacultyData.id).order_by(
            User.last_name.asc(), User.first_name.asc()
        )

    def faculty_available(self, faculty_id):
        return get_count(self.available_faculty.filter_by(faculty_id=faculty_id)) > 0

    def faculty_ifneeded(self, faculty_id):
        return get_count(self.ifneeded_faculty.filter_by(faculty_id=faculty_id)) > 0

    def faculty_unavailable(self, faculty_id):
        return get_count(self.unavailable_faculty.filter_by(faculty_id=faculty_id)) > 0

    def submitter_available(self, submitter_id):
        return (
            get_count(self.available_submitters.filter_by(submitter_id=submitter_id))
            > 0
        )

    def submitter_unavailable(self, submitter_id):
        return (
            get_count(self.unavailable_submitters.filter_by(submitter_id=submitter_id))
            > 0
        )

    def faculty_make_available(self, fac):
        data = (
            db.session.query(AssessorAttendanceData)
            .filter_by(assessment_id=self.owner_id, faculty_id=fac.id)
            .first()
        )
        if data is None:
            return

        if get_count(data.available.filter_by(id=self.id)) == 0:
            data.available.append(self)

        if get_count(data.unavailable.filter_by(id=self.id)) > 0:
            data.unavailable.remove(self)

        if get_count(data.if_needed.filter_by(id=self.id)) > 0:
            data.if_needed.remove(self)

    def faculty_make_unavailable(self, fac):
        data = (
            db.session.query(AssessorAttendanceData)
            .filter_by(assessment_id=self.owner_id, faculty_id=fac.id)
            .first()
        )
        if data is None:
            return

        if get_count(data.available.filter_by(id=self.id)) > 0:
            data.available.remove(self)

        if get_count(data.unavailable.filter_by(id=self.id)) == 0:
            data.unavailable.append(self)

        if get_count(data.if_needed.filter_by(id=self.id)) > 0:
            data.if_needed.remove(self)

    def faculty_make_ifneeded(self, fac):
        data = (
            db.session.query(AssessorAttendanceData)
            .filter_by(assessment_id=self.owner_id, faculty_id=fac.id)
            .first()
        )
        if data is None:
            return

        if get_count(data.available.filter_by(id=self.id)) > 0:
            data.available.remove(self)

        if get_count(data.unavailable.filter_by(id=self.id)) > 0:
            data.unavailable.remove(self)

        if get_count(data.if_needed.filter_by(id=self.id)) == 0:
            data.if_needed.append(self)

    def submitter_make_available(self, sub):
        data = (
            db.session.query(SubmitterAttendanceData)
            .filter_by(assessment_id=self.owner_id, submitter_id=sub.id)
            .first()
        )
        if data is None:
            return

        if get_count(data.available.filter_by(id=self.id)) == 0:
            data.available.append(self)

        if get_count(data.unavailable.filter_by(id=self.id)) > 0:
            data.unavailable.remove(self)

    def submitter_make_unavailable(self, sub):
        data = (
            db.session.query(SubmitterAttendanceData)
            .filter_by(assessment_id=self.owner_id, submitter_id=sub.id)
            .first()
        )
        if data is None:
            return

        if get_count(data.available.filter_by(id=self.id)) > 0:
            data.available.remove(self)

        if get_count(data.unavailable.filter_by(id=self.id)) == 0:
            data.unavailable.append(self)


@listens_for(PresentationSession, "before_update")
def _PresentationSession_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationSession_is_valid, target.id)
        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)

        # Can't filter on session_type, since we don't know the session_type prior to the update.
        # Instead, just uncache all sessions for this event on the same day.
        dups = (
            db.session.query(PresentationSession)
            .filter_by(date=target.date, owner_id=target.owner_id)
            .all()
        )
        for dup in dups:
            if dup.id != target.id:
                cache.delete_memoized(_PresentationSession_is_valid, dup.id)


@listens_for(PresentationSession, "before_insert")
def _PresentationSession_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationSession_is_valid, target.id)
        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)

        dups = (
            db.session.query(PresentationSession)
            .filter_by(
                date=target.date,
                owner_id=target.owner_id,
                session_type=target.session_type,
            )
            .all()
        )
        for dup in dups:
            if dup.id != target.id:
                cache.delete_memoized(_PresentationSession_is_valid, dup.id)


@listens_for(PresentationSession, "before_delete")
def _PresentationSession_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationSession_is_valid, target.id)
        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)

        dups = (
            db.session.query(PresentationSession)
            .filter_by(
                date=target.date,
                owner_id=target.owner_id,
                session_type=target.session_type,
            )
            .all()
        )
        for dup in dups:
            if dup.id != target.id:
                cache.delete_memoized(_PresentationSession_is_valid, dup.id)
