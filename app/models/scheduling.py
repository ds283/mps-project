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

from sqlalchemy import orm
from sqlalchemy.event import listens_for

from ..cache import cache
from ..database import db
from ..shared.sqlalchemy import get_count
from .assessment import PresentationSession
from .associations import (
    faculty_to_slots,
    orig_fac_to_slots,
    orig_sub_to_slots,
    session_to_rooms,
    submitter_to_slots,
)
from .defaults import DEFAULT_STRING_LENGTH
from .faculty import EnrollmentRecord, FacultyData
from .live_projects import LiveProject, SubmittingStudent
from .matching import PuLPMixin
from .model_mixins import (
    AssessorPoolChoicesMixin,
    ColouredLabelMixin,
    EditingMetadataMixin,
    SubmissionFeedbackStatesMixin,
)
from .project_class import ProjectClass, ProjectClassConfig, SubmissionPeriodRecord
from .submissions import SubmissionRecord
from .users import User


class Building(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Store data modelling a building that houses bookable rooms for presentation assessments
    """

    __tablename__ = "buildings"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # active flag
    active = db.Column(db.Boolean())

    def make_label(self, text=None):
        if text is None:
            text = self.name

        return self._make_label(text)

    def enable(self):
        self.active = True

        for room in self.rooms:
            room.disable()

    def disable(self):
        self.active = False


class Room(db.Model, EditingMetadataMixin):
    """
    Store data modelling a bookable room for presentation assessments
    """

    __tablename__ = "rooms"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # building
    building_id = db.Column(db.Integer(), db.ForeignKey("buildings.id"))
    building = db.relationship(
        "Building",
        foreign_keys=[building_id],
        uselist=False,
        backref=db.backref(
            "rooms", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # room name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # room capacity (currently not used)
    capacity = db.Column(db.Integer())

    # room has lecture capture?
    lecture_capture = db.Column(db.Boolean())

    # maximum allowable occupancy (i.e., multiple groups are allowed to be scheduled in the same room)
    # This could be physical (maybe the room can be partitioned), or can be used to model e.g. Zoom teleconference rooms
    maximum_occupancy = db.Column(db.Integer(), default=1, nullable=False)

    # active flag
    active = db.Column(db.Boolean())

    @property
    def full_name(self):
        return self.building.name + " " + self.name

    @property
    def label(self):
        return self.make_label()

    def make_label(self):
        return self.building.make_label(self.full_name)

    def enable(self):
        if self.available:
            self.active = True

    def disable(self):
        self.active = False

    @property
    def available(self):
        return self.building.active


@cache.memoize()
def _ScheduleAttempt_is_valid(id):
    obj = db.session.query(ScheduleAttempt).filter_by(id=id).one()

    errors = {}
    warnings = {}

    if not obj.finished:
        return True, errors, warnings

    # CONSTRAINT 1. SLOTS SHOULD SATISFY THEIR OWN CONSISTENCY RULES
    for slot in obj.slots:
        # check whether each slot validates individually
        if slot.has_issues:
            for n, e in enumerate(slot.errors):
                errors[("slots", (slot.id, n))] = (
                    f"{slot.session.label_as_string} {slot.room.full_name}: {e}"
                )

            for n, w in enumerate(slot.warnings):
                warnings[("slots", (slot.id, n))] = (
                    f"{slot.session.label_as_string} {slot.room.full_name}: {w}"
                )

    # CONSTRAINT 2. EVERY TALK SHOULD HAVE BEEN SCHEDULED IN EXACTLY ONE SLOT
    for rec in obj.owner.submitter_list:
        if rec.attending:
            if get_count(obj.get_student_slot(rec.submitter.owner_id)) == 0:
                errors[("talks", rec.submitter_id)] = (
                    'Submitter "{name}" is enrolled in this assessment, but their talk has not been '
                    "scheduled".format(name=rec.submitter.owner.student.user.name)
                )

        if get_count(obj.get_student_slot(rec.submitter.owner_id)) > 1:
            errors[("talks", rec.submitter_id)] = (
                'Submitter "{name}" has been scheduled in more than one slot'.format(
                    name=rec.submitter.owner.student.user.name
                )
            )

    # CONSTRAINT 3. CATS LIMITS SHOULD BE RESPECTED, FROM FacultyData AND EnrollmentRecords MODELS

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


class ScheduleAttempt(
    db.Model, PuLPMixin, EditingMetadataMixin, AssessorPoolChoicesMixin
):
    """
    Model configuration data for an assessment scheduling attempt
    """

    # make table name plural
    __tablename__ = "scheduling_attempts"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # owning assessment
    owner_id = db.Column(db.Integer(), db.ForeignKey("presentation_assessments.id"))
    owner = db.relationship(
        "PresentationAssessment",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "scheduling_attempts", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # a name for this matching attempt
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # tag
    tag = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True)

    # redirect tag (used to redirect earlier links that might have been published).
    # We use an explicit text field rather than linking to a ScheduleAttempt instance so that
    # the attempt we redirect to can mutate if needed, while the redirect tag stays the same
    redirect_tag = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # flag whether this attempt has been published to convenors for comments or editing
    published = db.Column(db.Boolean())

    # flag whether this attempt has been deployed as an official schedule
    deployed = db.Column(db.Boolean())

    # CONFIGURATION

    # maximum number of assignments per faculty member
    assessor_assigned_limit = db.Column(db.Integer())

    # cost of using an 'if needed' slot
    if_needed_cost = db.Column(db.Numeric(8, 3))

    # 'levelling tension', the relative cost of introducing an inequitable workload by adding an
    # extra assignment to faculty who already have the maximum assignments
    levelling_tension = db.Column(db.Numeric(8, 3))

    # must all assessors be in the assessor pool for every project, or is just one enough?
    all_assessors_in_pool = db.Column(db.Integer())

    # ignore coscheduling constraints (useful for Zoom talks)
    ignore_coscheduling = db.Column(db.Boolean())

    # allow assessors to be scheduled multiple times per session (also useful for Zoom talks)
    assessor_multiplicity_per_session = db.Column(db.Integer())

    # CIRCULATION STATUS

    # draft circulated to submitters?
    draft_to_submitters = db.Column(db.DateTime())

    # draft circulated to assessors?
    draft_to_assessors = db.Column(db.DateTime())

    # final version circulated to submitters?
    final_to_submitters = db.Column(db.DateTime())

    # final version circulated to assessors?
    final_to_assessors = db.Column(db.DateTime())

    def _init__(self, *args, **kwargs):
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
    def event_name(self):
        return self.owner.name

    @property
    def available_pclasses(self):
        return self.owner.available_pclasses

    @property
    def buildings_query(self):
        q = self.slots.subquery()

        building_ids = (
            db.session.query(Room.building_id)
            .select_from(q)
            .join(PresentationSession, PresentationSession.id == q.c.session_id)
            .join(
                session_to_rooms,
                session_to_rooms.c.session_id == PresentationSession.id,
            )
            .join(Room, Room.id == session_to_rooms.c.room_id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(Building)
            .join(building_ids, Building.id == building_ids.c.building_id)
            .order_by(Building.name.asc())
        )

    @property
    def available_buildings(self):
        return self.buildings_query.all()

    @property
    def number_buildings(self):
        return get_count(self.buildings_query)

    @property
    def rooms_query(self):
        q = self.slots.subquery()

        room_ids = (
            db.session.query(ScheduleSlot.room_id)
            .join(q, q.c.id == ScheduleSlot.id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(Room)
            .join(room_ids, room_ids.c.room_id == Room.id)
            .join(Building, Building.id == Room.building_id)
            .order_by(Building.name.asc(), Room.name.asc())
        )

    @property
    def available_rooms(self):
        return self.rooms_query.all()

    @property
    def number_rooms(self):
        return get_count(self.rooms_query)

    @property
    def sessions_query(self):
        q = self.slots.subquery()

        session_ids = (
            db.session.query(PresentationSession.id)
            .select_from(q)
            .join(PresentationSession, PresentationSession.id == q.c.session_id)
            .distinct()
            .subquery()
        )

        return (
            db.session.query(PresentationSession)
            .join(session_ids, PresentationSession.id == session_ids.c.id)
            .order_by(
                PresentationSession.date.asc(), PresentationSession.session_type.asc()
            )
        )

    @property
    def available_sessions(self):
        return self.sessions_query.all()

    @property
    def number_sessions(self):
        return get_count(self.sessions_query)

    @property
    def slots_query(self):
        q = self.slots.subquery()

        return (
            db.session.query(ScheduleSlot)
            .join(q, q.c.id == ScheduleSlot.id)
            .join(
                PresentationSession, PresentationSession.id == ScheduleSlot.session_id
            )
            .join(Room, Room.id == ScheduleSlot.room_id)
            .join(Building, Building.id == Room.building_id)
            .order_by(
                PresentationSession.date.asc(), Building.name.asc(), Room.name.asc()
            )
        )

    @property
    def ordered_slots(self):
        return self.slots_query.all()

    @property
    def number_slots(self):
        return get_count(self.slots_query)

    @property
    def is_valid(self):
        """
        Perform validation
        :return:
        """
        flag, self._errors, self._warnings = _ScheduleAttempt_is_valid(self.id)
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

    def get_faculty_slots(self, fac):
        if isinstance(fac, int):
            fac_id = fac
        elif isinstance(fac, FacultyData) or isinstance(fac, User):
            fac_id = fac.id
        else:
            raise RuntimeError("Unknown faculty id type passed to get_faculty_slots()")

        # fac_id is a FacultyData identifier
        return self.slots.filter(ScheduleSlot.assessors.any(id=fac_id))

    def get_number_faculty_slots(self, fac):
        return get_count(self.get_faculty_slots(fac))

    def get_student_slot(self, student):
        if isinstance(student, int):
            sub_id = student
        elif isinstance(student, SubmittingStudent):
            sub_id = student.id
        else:
            raise RuntimeError("Unknown submitter id type passed to get_student_slot()")

        return self.slots.filter(ScheduleSlot.talks.any(owner_id=sub_id))

    def get_original_student_slot(self, student):
        return self.slots.filter(ScheduleSlot.original_talks.any(owner_id=student))

    @property
    def number_ifneeded(self):
        count = 0

        for slot in self.slots:
            for assessor in slot.assessors:
                if slot.session.faculty_ifneeded(assessor.id):
                    count += 1

        return count

    @property
    def is_revokable(self):
        # can't revoke if parent event is closed
        if self.owner.is_closed:
            return False

        today = date.today()

        for slot in self.slots:
            # can't revoke if any schedule slot is in the past
            if slot.session.date <= today:
                return False

        return True

    @property
    def is_closable(self):
        # is closable if all scheduled slots are in the past
        today = date.today()

        for slot in self.slots:
            if slot.session.date >= today:
                return False

        return True

    @property
    def is_modified(self):
        return self.last_edit_timestamp is not None


@listens_for(ScheduleAttempt, "before_update")
def _ScheduleAttempt_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.id)
        from .assessment import _PresentationAssessment_is_valid

        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)


@listens_for(ScheduleAttempt, "before_insert")
def _ScheduleAttempt_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.id)
        from .assessment import _PresentationAssessment_is_valid

        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)


@listens_for(ScheduleAttempt, "before_delete")
def _ScheduleAttempt_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.id)
        from .assessment import _PresentationAssessment_is_valid

        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)


@cache.memoize()
def _ScheduleSlot_is_valid(id):
    obj: ScheduleSlot = db.session.query(ScheduleSlot).filter_by(id=id).one()
    attempt: ScheduleAttempt = obj.owner
    from .assessment import PresentationAssessment

    assessment: PresentationAssessment = attempt.owner
    session: PresentationSession = obj.session

    errors = {}
    warnings = {}

    # CONSTRAINT 1a. NUMBER OF TALKS SHOULD BE LESS THAN PRESCRIBED MAXIMUM
    num_talks = get_count(obj.talks)
    if num_talks > 0:
        expected_size = max(tk.period.max_group_size for tk in obj.talks)

        if num_talks > expected_size:
            errors[("basic", 0)] = (
                "This slot has a maximum group size {max}, but {sch} talks have been scheduled".format(
                    sch=num_talks, max=expected_size
                )
            )

    # CONSTRAINT 1b. NUMBER OF TALKS SHOULD BE LESS THAN THE CAPACITY OF THE ROOM, MINUS THE NUMBER OF ASSESSORS
    if num_talks > 0:
        room: Room = obj.room
        tk: SubmissionRecord = obj.talks.first()
        period: SubmissionPeriodRecord = tk.period

        room_capacity = room.capacity
        num_assessors = period.number_assessors

        max_talks = room_capacity - num_assessors
        if max_talks < 0:
            max_talks = 0

        if max_talks <= 0:
            errors[("basic", 1)] = (
                'Room "{name}" has maximum student capacity {max} (room capacity={rc}, '
                "number assessors={na})".format(
                    name=room.full_name,
                    max=max_talks,
                    rc=room.capacity,
                    na=num_assessors,
                )
            )
        elif num_talks > max_talks:
            errors[("basic", 2)] = (
                'Room "{name}" has maximum student capacity {max}, but {nt} talks have been '
                "scheduled in this slot".format(
                    name=room.full_name, max=max_talks, nt=num_talks
                )
            )

    # CONSTRAINT 2. TALKS SHOULD USUALLY BY DRAWN FROM THE SAME PROJECT CLASS (OR EQUIVALENTLY, SUBMISSION PERIOD)
    if num_talks > 0:
        tk = obj.talks.first()
        period_id = tk.period_id

        for talk in obj.talks:
            if talk.period_id != period_id:
                errors[("period", talk.id)] = (
                    'Submitter "{name}" is drawn from a mismatching project class '
                    "({pclass_a} vs. {pclass_b})".format(
                        name=talk.owner.student.user.name,
                        pclass_a=talk.period.config.project_class.name,
                        pclass_b=tk.period.config.project_class.name,
                    )
                )

    # CONSTRAINT 3. NUMBER OF ASSESSORS SHOULD BE EQUAL TO REQUIRED NUMBER FOR THE PROJECT CLASS ASSOCIATED WITH THIS SLOT
    if num_talks > 0:
        num_assessors = get_count(obj.assessors)

        tk = obj.talks.first()
        expected_assessors = tk.period.number_assessors

        if num_assessors > expected_assessors:
            errors[("basic", 1)] = (
                "Too many assessors scheduled in this slot (scheduled={sch}, required={num})".format(
                    sch=num_assessors, num=expected_assessors
                )
            )
        if num_assessors < expected_assessors:
            errors[("basic", 1)] = (
                "Too few assessors scheduled in this slot (scheduled={sch}, required={num})".format(
                    sch=num_assessors, num=expected_assessors
                )
            )

    # CONSTRAINT 4. ASSESSORS SHOULD BE ENROLLED FOR THIS PROJECT CLASS
    pclass: ProjectClass = obj.pclass
    if pclass is not None:
        for assessor in obj.assessors:
            rec = assessor.get_enrollment_record(pclass.id)
            if rec is None or (
                rec is not None
                and rec.presentations_state != EnrollmentRecord.PRESENTATIONS_ENROLLED
            ):
                errors[("enrollment", assessor.id)] = (
                    'Assessor "{name}" is scheduled in this slot, but is not '
                    'enrolled as an assessor for "{pclass}"'.format(
                        name=assessor.user.name, pclass=pclass.name
                    )
                )

    # CONSTRAINT 5. ALL ASSESSORS SHOULD BE AVAILABLE FOR THIS SESSION
    for assessor in obj.assessors:
        if session.faculty_unavailable(assessor.id):
            errors[("faculty", assessor.id)] = (
                'Assessor "{name}" is scheduled in this slot, but is not '
                "available".format(name=assessor.user.name)
            )
        elif session.faculty_ifneeded(assessor.id):
            warnings[("faculty", assessor.id)] = (
                'Assessor "{name}" is scheduled in this slot, but is marked '
                'as "if needed"'.format(name=assessor.user.name)
            )
        else:
            if not session.faculty_available(assessor.id):
                errors[("faculty", assessor.id)] = (
                    'Assessor "{name}" is scheduled in this slot, but they do not '
                    "belong to this assessment".format(name=assessor.user.name)
                )

    # CONSTRAINT 6. ASSESSORS SHOULD NOT BE PROJECT SUPERVISORS
    for talk in obj.talks:
        talk: SubmissionRecord
        if talk.project is None:
            errors[("supervisor", talk.id)] = (
                'Project supervisor for "{student}" is not set'.format(
                    student=talk.owner.student.user.name
                )
            )
        elif talk.project.owner in obj.assessors:
            errors[("supervisor", talk.id)] = (
                'Assessor "{name}" is project supervisor for "{student}"'.format(
                    name=talk.project.owner.user.name,
                    student=talk.owner.student.user.name,
                )
            )

    # CONSTRAINT 7. PREFERABLY, EACH TALK SHOULD HAVE AT LEAST ONE ASSESSOR BELONGING TO ITS ASSESSOR POOL
    # (but we mark this as a warning rather than an error)
    for talk in obj.talks:
        talk: SubmissionRecord
        project: LiveProject = talk.project

        if (
            attempt.all_assessors_in_pool == AssessorPoolChoicesMixin.ALL_IN_POOL
            or attempt.all_assessors_in_pool
            == AssessorPoolChoicesMixin.AT_LEAST_ONE_IN_POOL
        ):
            found_match = False
            for assessor in talk.project.assessor_list:
                assessor: FacultyData
                if get_count(obj.assessors.filter_by(id=assessor.id)) > 0:
                    found_match = True
                    break

            if not found_match:
                warnings[("pool", talk.id)] = (
                    'No assessor belongs to the pool for submitter "{name}"'.format(
                        name=talk.owner.student.user.name
                    )
                )

        elif (
            attempt.all_assessors_in_pool
            == AssessorPoolChoicesMixin.ALL_IN_RESEARCH_GROUP
            or attempt.all_assessors_in_pool
            == AssessorPoolChoicesMixin.AT_LEAST_ONE_IN_RESEARCH_GROUP
        ):
            found_match = False
            if project.group is not None:
                for assessor in obj.assessors:
                    if assessor.has_affiliation(project.group):
                        found_match = True
                        break

            if not found_match:
                for assessor in talk.project.assessor_list:
                    assessor: FacultyData
                    if get_count(obj.assessors.filter_by(id=assessor.id)) > 0:
                        found_match = True
                        break

            if not found_match:
                warnings[("pool_group", talk.id)] = (
                    "No assessor belongs to either the pool or affiliated "
                    "research group for submitter "
                    '"{name}"'.format(name=talk.owner.student.user.name)
                )

    # CONSTRAINT 8. SUBMITTERS MARKED 'CAN'T ATTEND' SHOULD NOT BE SCHEDULED
    for talk in obj.talks:
        talk: SubmissionRecord
        if assessment.not_attending(talk.id):
            errors[("talks", talk.id)] = (
                'Submitter "{name}" is scheduled in this slot, but this student '
                "is not attending".format(name=talk.owner.student.user.name)
            )

    # CONSTRAINT 9. SUBMITTERS SHOULD ALL BE AVAILABLE FOR THIS SESSION
    for talk in obj.talks:
        talk: SubmissionRecord
        if session.submitter_unavailable(talk.id):
            errors[("submitter", talk.id)] = (
                'Submitter "{name}" is scheduled in this slot, but is not '
                "available".format(name=talk.owner.student.user.name)
            )
        else:
            if not session.submitter_available(talk.id):
                errors[("submitter", talk.id)] = (
                    'Submitter "{name}" is scheduled in this slot, but they do not '
                    "belong to this assessment".format(
                        name=talk.owner.student.user.name
                    )
                )

    # CONSTRAINT 10. TALKS MARKED NOT TO CLASH SHOULD NOT BE SCHEDULED TOGETHER
    if not attempt.ignore_coscheduling:
        talks_list = obj.talks.all()
        for i in range(len(talks_list)):
            for j in range(i):
                talk_i = talks_list[i]
                talk_j = talks_list[j]

                if talk_i.project_id == talk_j.project_id and (
                    talk_i.project is not None
                    and talk_i.project.dont_clash_presentations
                ):
                    errors[("clash", (talk_i.id, talk_j.id))] = (
                        'Submitters "{name_a}" and "{name_b}" share a project '
                        '"{proj}" that is marked not to be co-scheduled'.format(
                            name_a=talk_i.owner.student.user.name,
                            name_b=talk_j.owner.student.user.name,
                            proj=talk_i.project.name,
                        )
                    )

    # CONSTRAINT 11. ASSESSORS SHOULD NOT BE SCHEDULED TO BE IN TOO MANY PLACES AT THE SAME TIME
    # the maximum multiplicity is given by the assessor_multiplicity_per_session field in ScheduleAttempt
    for assessor in obj.assessors:
        q = db.session.query(ScheduleSlot).filter(
            ScheduleSlot.id != obj.id,
            ScheduleSlot.owner_id == obj.owner_id,
            ScheduleSlot.session_id == obj.session_id,
            ScheduleSlot.assessors.any(id=assessor.id),
        )
        count = get_count(q)

        if count > attempt.assessor_multiplicity_per_session - 1:
            session: PresentationSession = obj.session
            errors[("assessors", assessor.id)] = (
                f'Assessor "{assessor.user.name}" is scheduled too many times in session {session.label_as_string} (maximum multiplicity = {attempt.assessor_multiplicity_per_session}'
            )

    # CONSTRAINT 12. TALKS SHOULD BE SCHEDULED IN ONLY ONE SLOT
    for talk in obj.talks:
        talk: SubmissionRecord
        q = db.session.query(ScheduleSlot).filter(
            ScheduleSlot.id != obj.id,
            ScheduleSlot.owner_id == obj.owner_id,
            ScheduleSlot.session_id == obj.session_id,
            ScheduleSlot.talks.any(id=talk.id),
        )
        count = get_count(q)

        if count > 0:
            for slot in q.all():
                errors[("assessors", (talk.id, slot.id))] = (
                    f'"{talk.owner.student.user.name}" is also scheduled in session {slot.session.label_as_string} {slot.room.full_name}'
                )

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


class ScheduleSlot(db.Model, SubmissionFeedbackStatesMixin):
    """
    Model a single slot in a schedule
    """

    __tablename__ = "schedule_slots"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # owning schedule
    owner_id = db.Column(db.Integer(), db.ForeignKey("scheduling_attempts.id"))
    owner = db.relationship(
        "ScheduleAttempt",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "slots", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # session
    session_id = db.Column(db.Integer(), db.ForeignKey("presentation_sessions.id"))
    session = db.relationship(
        "PresentationSession", foreign_keys=[session_id], uselist=False
    )

    # room
    room_id = db.Column(db.Integer(), db.ForeignKey("rooms.id"))
    room = db.relationship("Room", foreign_keys=[room_id], uselist=False)

    # occupancy label
    occupancy_label = db.Column(db.Integer(), nullable=False)

    # assessors attached to this slot
    assessors = db.relationship(
        "FacultyData",
        secondary=faculty_to_slots,
        lazy="dynamic",
        backref=db.backref("assessor_slots", lazy="dynamic"),
    )

    # talks scheduled in this slot
    talks = db.relationship(
        "SubmissionRecord",
        secondary=submitter_to_slots,
        lazy="dynamic",
        backref=db.backref("scheduled_slots", lazy="dynamic"),
    )

    # ORIGINAL VERSIONS to allow reversion later

    # original set of assessors attached to ths slot
    original_assessors = db.relationship(
        "FacultyData", secondary=orig_fac_to_slots, lazy="dynamic"
    )

    # original set of submitters attached to this slot
    original_talks = db.relationship(
        "SubmissionRecord",
        secondary=orig_sub_to_slots,
        lazy="dynamic",
        backref=db.backref("original_scheduled_slots", lazy="dynamic"),
    )

    def _init__(self, *args, **kwargs):
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
    def is_valid(self):
        """
        Perform validation
        :return:
        """
        flag, self._errors, self._warnings = _ScheduleSlot_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def is_empty(self):
        return get_count(self.talks) == 0

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

    @property
    def event_name(self):
        return self.owner.event_name

    def has_pclass(self, pclass_id):
        query = (
            db.session.query(submitter_to_slots.c.submitter_id)
            .filter(submitter_to_slots.c.slot_id == self.id)
            .subquery()
        )

        q = (
            db.session.query(SubmissionRecord)
            .join(query, query.c.submitter_id == SubmissionRecord.id)
            .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
            .join(
                ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id
            )
            .filter(ProjectClassConfig.pclass_id == pclass_id)
        )
        return get_count(q) > 0

    @property
    def pclass(self):
        if get_count(self.talks) == 0:
            return None

        tk = self.talks.first()
        if tk is None:
            return None

        return tk.project.config.project_class

    def is_assessor(self, fac_id):
        return get_count(self.assessors.filter_by(id=fac_id)) > 0

    def is_submitter(self, sub_id):
        return get_count(self.talks.filter_by(id=sub_id)) > 0

    @property
    def room_full_name(self):
        return self.room.full_name

    def belongs_to(self, period):
        return get_count(self.talks.filter_by(period_id=period.id)) > 0

    @property
    def submission_period(self):
        talk = self.talks.first()
        if talk is None:
            return None

        return talk.period

    @property
    def assessor_CATS(self):
        # assume all scheduled talks are in the same project class
        talk = self.talks.first()

        if talk is None:
            return None

        return talk.assessor_CATS

    def feedback_state(self, faculty_id):
        # determine whether feedback is enabled for the SubmissionPeriodRecord shared
        # by our talks
        period = self.submission_period
        if period is None:
            return ScheduleSlot.FEEDBACK_NOT_REQUIRED

        if not period.config.project_class.publish:
            return ScheduleSlot.FEEDBACK_NOT_REQUIRED

        count = get_count(self.assessors.filter_by(id=faculty_id))
        if count == 0:
            return ScheduleSlot.FEEDBACK_NOT_REQUIRED

        state = []
        for talk in self.talks:
            # feedback types for SubmissionRecord are the same as for ScheduleSlot, since both are controlled
            # from SubmissionFeedbackStatesMixin
            state.append(talk.presentation_feedback_state(faculty_id))

        # state is defined to be the earliest lifecycle state, taken over all the talks, except that
        # we use ENTERED rather than WAITING if possible
        s = min(state)
        if s == ScheduleSlot.FEEDBACK_WAITING and any(
            [
                s == ScheduleSlot.FEEDBACK_ENTERED
                or s == ScheduleSlot.FEEDBACK_SUBMITTED
                for s in state
            ]
        ):
            return ScheduleSlot.FEEDBACK_ENTERED

        return s

    def feedback_number(self, faculty_id):
        count = get_count(self.assessors.filter_by(id=faculty_id))
        if count == 0:
            return None

        submitted = 0
        total = 0
        for talk in self.talks:
            if talk.presentation_assessor_submitted(faculty_id):
                submitted += 1
            total += 1

        return submitted, total

    def assessor_has_overlap(self, fac_id):
        """
        Determine whether a given assessor lies in the assessor pool for at least one of the presenters,
        and is therefore a candidate to assess this slot
        :param fac_id:
        :return:
        """
        for talk in self.talks:
            if get_count(talk.project.assessors.filter_by(id=fac_id)) > 0:
                return True

        return False

    def presenter_has_overlap(self, sub):
        """
        Determine whether a given student's assessor pool includes any of the assessors already attached
        to this slot, making the student a candidate to move to this slot
        :param sub_id:
        :return:
        """
        if isinstance(sub, SubmissionRecord):
            rec = sub
        else:
            rec = db.session.query(SubmissionRecord).filter_by(id=sub).one()

        for assessor in self.assessors:
            if get_count(rec.project.assessors.filter_by(id=assessor.id)) > 0:
                return True

        return False

    def assessor_makes_valid(self, fac_id):
        no_pool_talks = []
        for talk in self.talks:
            has_match = False
            for assessor in self.assessors:
                if get_count(talk.project.assessors.filter_by(id=assessor.id)) > 0:
                    has_match = True
                    break

            if not has_match:
                no_pool_talks.append(talk)

        if len(no_pool_talks) == 0:
            return False

        for talk in no_pool_talks:
            if get_count(talk.project.assessors.filter_by(id=fac_id)) == 0:
                return False

        return True

    @property
    def alternative_rooms(self):
        needs_lecture_capture = False

        if get_count(self.talks) > 0:
            tk = self.talks.first()

            if tk is not None:
                if not tk.period.has_presentation:
                    raise RuntimeError(
                        "Inconsistent SubmissionPeriodDefinition in ScheduleSlot.alternative_rooms"
                    )
                if tk.period.lecture_capture:
                    needs_lecture_capture = True

        rooms = self.session.rooms.subquery()

        used_rooms = (
            db.session.query(ScheduleSlot.room_id)
            .filter(
                ScheduleSlot.owner_id == self.owner_id,
                ScheduleSlot.session_id == self.session_id,
            )
            .distinct()
            .subquery()
        )

        query = (
            db.session.query(Room)
            .join(rooms, rooms.c.id == Room.id)
            .join(used_rooms, used_rooms.c.room_id == Room.id, isouter=True)
            .filter(used_rooms.c.room_id == None)
        )

        if needs_lecture_capture:
            query = query.filter(Room.lecture_capture.is_(True))

        return (
            query.join(Building, Building.id == Room.building_id)
            .order_by(Building.name.asc(), Room.name.asc())
            .all()
        )


@listens_for(ScheduleSlot, "before_update")
def _ScheduleSlot_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )


@listens_for(ScheduleSlot, "before_insert")
def _ScheduleSlot_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )


@listens_for(ScheduleSlot, "before_delete")
def _ScheduleSlot_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )


@listens_for(ScheduleSlot.assessors, "append")
def _ScheduleSlot_assessors_append_handler(target, value, initiator):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )


@listens_for(ScheduleSlot.assessors, "remove")
def _ScheduleSlot_assessors_remove_handler(target, value, initiator):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )


@listens_for(ScheduleSlot.talks, "append")
def _ScheduleSlot_talks_append_handler(target, value, initiator):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )


@listens_for(ScheduleSlot.talks, "remove")
def _ScheduleSlot_talks_remove_handler(target, value, initiator):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ScheduleSlot_is_valid, target.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, target.owner_id)
        if target.owner is not None:
            from .assessment import _PresentationAssessment_is_valid

            cache.delete_memoized(
                _PresentationAssessment_is_valid, target.owner.owner_id
            )
