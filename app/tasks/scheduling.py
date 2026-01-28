#
# Created by David Seery on 2018-10-08.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import base64
import itertools
from datetime import datetime
from functools import partial
from io import BytesIO
from os import path
from pathlib import Path
from typing import Tuple, Dict, List

import pulp
import pulp.apis as pulp_apis
from celery import group, chain
from celery.exceptions import Ignore
from distutils.util import strtobool
from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    TaskRecord,
    ScheduleAttempt,
    ScheduleSlot,
    GeneratedAsset,
    TemporaryAsset,
    User,
    ScheduleEnumeration,
    SubmissionRecord,
    SubmissionPeriodRecord,
    AssessorAttendanceData,
    EnrollmentRecord,
    SubmitterAttendanceData,
    PresentationSession,
    Room,
    FacultyData,
    LiveProject,
    ResearchGroup,
    ProjectClassConfig,
    validate_nonce,
    SubmissionRole,
)
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.scratch import ScratchFileManager
from ..shared.sqlalchemy import get_count
from ..shared.timer import Timer
from ..task_queue import progress_update, register_task

# create type for availability matrices;
# these are mathematically matrices, but we represent them as maps from a tuple (i,j) -> value.
AvailabilityMatrix = Dict[Tuple[int, int], int]

# maps between "talks" (represented by a submission record) and their associated numerical identifier
# these map a SubmissionRecord.id to an internal identifier (used as an index into matrices), and vice versa
TalkToNumberMap = Dict[int, int]
NumberToTalkMap = Dict[int, int]
# this maps an internal identifier directly to a SubmissionRecord instances
TalkDictMap = Dict[int, SubmissionRecord]


def _enumerate_talks(schedule: ScheduleAttempt, read_serialized: bool = False) -> Tuple[int, TalkToNumberMap, NumberToTalkMap, TalkDictMap]:
    # schedule is a ScheduleAttempt instance
    talk_to_number: TalkToNumberMap = {}
    number_to_talk: NumberToTalkMap = {}

    talk_dict: TalkDictMap = {}

    # the .schedulable_talks property returns a list of of SubmissionRecord instances,
    # minus any students who are not attending the main event and need to
    # be scheduled into the make-up event.
    if not read_serialized:
        if len(schedule.owner.schedulable_talks) == 0:
            raise RuntimeError(f'No schedulable talks found for schedule {schedule.id} (name="{schedule.name}", assessment="{schedule.owner.name}")')

        talks = enumerate(schedule.owner.schedulable_talks)

    else:
        talk_data = db.session.query(ScheduleEnumeration).filter_by(category=ScheduleEnumeration.SUBMITTER, schedule_id=schedule.id).subquery()
        talks = (
            db.session.query(talk_data.c.enumeration, SubmissionRecord)
            .select_from(SubmissionRecord)
            .join(talk_data, talk_data.c.key == SubmissionRecord.id)
            .order_by(talk_data.c.enumeration.asc())
            .all()
        )

    n = 0
    for n, p in talks:
        talk_to_number[p.id] = n
        number_to_talk[n] = p.id

        talk_dict[n] = p

    return n + 1, talk_to_number, number_to_talk, talk_dict


def _enumerate_assessors(schedule: ScheduleAttempt, read_serialized: bool = False):
    # schedule is a ScheduleAttempt instance
    assessor_to_number = {}
    number_to_assessor = {}

    assessor_dict = {}
    assessor_limits = {}

    # the .assessor_list property returns a list of AssessorAttendanceData instances,
    # one for each assessor who has been invited to attend
    if not read_serialized:
        if len(schedule.owner.ordered_assessors) == 0:
            raise RuntimeError(f'No assessors found for schedule {schedule.id} (name="{schedule.name}", assessment="{schedule.owner.name}")')

        assessors = enumerate(schedule.owner.ordered_assessors)

    else:
        assessor_data = db.session.query(ScheduleEnumeration).filter_by(category=ScheduleEnumeration.ASSESSOR, schedule_id=schedule.id).subquery()
        assessors = (
            db.session.query(assessor_data.c.enumeration, AssessorAttendanceData)
            .select_from(AssessorAttendanceData)
            .join(assessor_data, assessor_data.c.key == AssessorAttendanceData.faculty_id)
            .order_by(assessor_data.c.enumeration.asc())
            .all()
        )

    n = 0
    for n, a in assessors:
        assessor_to_number[a.faculty_id] = n
        number_to_assessor[n] = a.faculty_id

        assessor_dict[n] = a.faculty

        if a.assigned_limit is not None:
            assessor_limits[n] = a.assigned_limit

    return n + 1, assessor_to_number, number_to_assessor, assessor_dict, assessor_limits


def _enumerate_periods(schedule: ScheduleAttempt, read_serialized: bool = False):
    # schedule is a ScheduleAttempt instance
    period_to_number = {}
    number_to_period = {}

    period_dict = {}

    if not read_serialized:
        if len(schedule.owner.available_periods) == 0:
            raise RuntimeError(f'No periods found for schedule {schedule.id} (name="{schedule.name}", assessment="{schedule.owner.name}")')

        periods = enumerate(schedule.owner.available_periods)

    else:
        period_data = db.session.query(ScheduleEnumeration).filter_by(category=ScheduleEnumeration.PERIOD, schedule_id=schedule.id).subquery()
        periods = (
            db.session.query(period_data.c.enumeration, SubmissionPeriodRecord)
            .select_from(SubmissionPeriodRecord)
            .join(period_data, period_data.c.key == SubmissionPeriodRecord.id)
            .order_by(period_data.c.enumeration.asc())
            .all()
        )

    n = 0
    for n, p in periods:
        period_to_number[p.id] = n
        number_to_period[n] = p.id

        period_dict[n] = p

    return n + 1, period_to_number, number_to_period, period_dict


def _enumerate_slots(schedule: ScheduleAttempt, read_serialized: bool = False):
    # schedule is a ScheduleAttempt instance
    slot_to_number = {}
    number_to_slot = {}

    slot_dict = {}

    if not read_serialized:
        if len(schedule.ordered_slots) == 0:
            raise RuntimeError(f'No slots found for schedule {schedule.id} (name="{schedule.name}", assessment="{schedule.owner.name}")')

        slots = enumerate(schedule.ordered_slots)

    else:
        slot_data = db.session.query(ScheduleEnumeration).filter_by(category=ScheduleEnumeration.SLOT, schedule_id=schedule.id).subquery()
        slots = (
            db.session.query(slot_data.c.enumeration, ScheduleSlot)
            .select_from(ScheduleSlot)
            .join(slot_data, slot_data.c.key == ScheduleSlot.id)
            .order_by(slot_data.c.enumeration.asc())
            .all()
        )

    n = 0
    for n, s in slots:
        slot_to_number[s.id] = n
        number_to_slot[n] = s.id

        slot_dict[n] = s

    return n + 1, slot_to_number, number_to_slot, slot_dict


def _build_faculty_availability_matrix(number_assessors, assessor_dict, number_slots, slot_dict) -> Tuple[AvailabilityMatrix, AvailabilityMatrix]:
    """
    Construct a dictionary mapping from (assessing-faculty, slot) pairs to yes/no availabilities,
    coded as 0 = not available, 1 = available
    :param number_assessors:
    :param assessor_dict:
    :param number_slots:
    :param slot_dict:
    :return:
    """
    A: AvailabilityMatrix = {}
    C: AvailabilityMatrix = {}

    for i in range(number_assessors):
        assessor = assessor_dict[i]

        for j in range(number_slots):
            idx = (i, j)
            slot = slot_dict[j]

            # is this assessor available in this slot?
            # notice that we don't distinguish *here* between 'available' and 'if needed'; both are coded
            # as A_ij = 1. The point is that A is used to generate hard constraints.
            # 'if needed' has to be enforced by an optimization goal.
            if slot.session.faculty_unavailable(assessor.id):
                A[idx] = 0
            else:
                A[idx] = 1

            # we store the 'if needed' states in a second matrix that is used to build
            # a cost function
            if slot.session.faculty_ifneeded(assessor.id):
                C[idx] = 1
            else:
                C[idx] = 0

    return A, C


def _build_student_availability_matrix(number_talks, talk_dict, number_slots, slot_dict) -> AvailabilityMatrix:
    """
    Construct a dictionary mapping from (submitting-student, slot) pairs to yes/no availabilities,
    coded a 0 = not available, 1 = available
    :param number_talks:
    :param talk_dict:
    :param number_slots:
    :param slot_dict:
    :return:
    """
    B = {}

    for i in range(number_talks):
        talk = talk_dict[i]

        for j in range(number_slots):
            idx = (i, j)
            slot = slot_dict[j]

            # is this student available in this slot?
            if slot.session.submitter_unavailable(talk.id):
                B[idx] = 0
            else:
                B[idx] = 1

    return B


def _generate_minimize_objective(C: AvailabilityMatrix, X, Y, S, number_talks, number_assessors, number_slots, record):
    """
    Generate an objective function that tries to schedule as efficiently as possible,
    with workload balancing
    :param X:
    :param Y:
    :param S:
    :param number_talks:
    :param number_assessors:
    :param number_slots:
    :return:
    """
    # generate objective function
    # note that this is a minimization problem
    objective = 0

    # ask optimizer to minimize the number of slots that are used
    objective += sum(S[idx] for idx in S)

    # optimizer should penalize any slots that use 'if needed'
    objective += sum(Y[(i, j)] * C[(i, j)] * abs(float(record.if_needed_cost)) for i in range(number_assessors) for j in range(number_slots))

    # TODO: - minimize number of days used in schedule
    # TODO: - minimize number of rooms used in schedule

    return objective


def _generate_reschedule_objective(C, oldX, oldY, X, Y, S, number_talks, number_assessors, number_slots, record):
    """
    Generate an objective function that tries to produce a feasible schedule matching oldX, oldY
    as closely as possible
    :param X:
    :param Y:
    :param S:
    :param number_talks:
    :param number_assessors:
    :param number_slots:
    :return:
    """
    # generate objective function
    # note that this is a minimization problem
    objective = 0

    # ask optimizer to choose X and Y values that match oldX, oldY as closely as possible.
    # recall that we solve a *minimization* problem, so the objective function should
    # count the number of *differences*

    for i in range(number_talks):
        for j in range(number_slots):
            idx = (i, j)
            if oldX[idx] == 0:
                objective += X[idx]
            else:
                objective += 1 - X[idx]

    for i in range(number_assessors):
        for j in range(number_slots):
            idx = (i, j)
            if oldY[idx] == 0:
                objective += Y[idx]
            else:
                objective += 1 - Y[idx]

    # optimizer should penalize any slots that use 'if needed'
    objective += sum(Y[(i, j)] * C[(i, j)] * abs(float(record.if_needed_cost)) for i in range(number_assessors) for j in range(number_slots))

    return objective


def _reconstruct_XY(self, old_record, number_talks, number_assessors, number_slots, talk_to_number, assessor_to_number, slot_dict):
    X = {}
    Y = {}

    reverse_slot_dict = {}
    for number in slot_dict:
        slot = slot_dict[number]
        reverse_slot_dict[(slot.session_id, slot.room_id)] = number

    for slot in old_record.slots:
        k = reverse_slot_dict[(slot.session_id, slot.room_id)]

        for talk in slot.talks:
            if talk.id in talk_to_number:  # key might be missing if this talk has been removed; if so, just ignore
                i = talk_to_number[talk.id]
                X[(i, k)] = 1

        for assessor in slot.assessors:
            if assessor.id in assessor_to_number:  # key might be missing if this assessor has been removed; if so, just ignore
                j = assessor_to_number[assessor.id]
                Y[(j, k)] = 1

    for k in range(number_slots):
        for i in range(number_talks):
            if (i, k) not in X:
                X[(i, k)] = 0

        for j in range(number_assessors):
            if (j, k) not in Y:
                Y[(j, k)] = 0

    return X, Y


def _forbid_unused_slots(prob, X, Y, number_assessors, number_talks, slot_dict, old_record):
    for k in slot_dict:
        slot = slot_dict[k]

        present = get_count(db.session.query(ScheduleSlot).filter_by(owner_id=old_record.id, session_id=slot.session_id, room_id=slot.room_id)) > 0

        if not present:
            print(
                "-- removing slot: session = {session} {type} {room}".format(
                    session=slot.session.short_date_as_string, type=slot.session.session_type_string, room=slot.room.full_name
                )
            )
            for i in range(number_talks):
                prob += X[(i, k)] == 0

            for i in range(number_assessors):
                prob += Y[(i, k)] == 0


def _create_PuLP_problem(
    A: AvailabilityMatrix,
    B: AvailabilityMatrix,
    attempt: ScheduleAttempt,
    number_talks: int,
    number_assessors: int,
    number_slots: int,
    number_periods: int,
    assessor_to_number,
    period_to_number,
    talk_dict: TalkDictMap,
    assessor_dict,
    slot_dict,
    period_dict,
    assessor_limits,
    make_objective,
):
    """
    Generate a PuLP problem to find an optimal assignment of student talks + faculty assessors to rooms
    :param assessor_limits:
    :param period_to_number:
    :param number_periods:
    :param period_dict:
    :param B:
    :param assessor_dict:
    :param talk_dict:
    :param slot_dict:
    :param attempt:
    :param A:
    :param number_talks:
    :param number_assessors:
    :param number_slots:
    :return:
    """

    print("Building PuLP problem for schedule:")
    print(" -- {l} talks, {m} assessors, {n} slots".format(l=number_talks, m=number_assessors, n=number_slots))

    # generate PuLP problem
    prob = pulp.LpProblem(attempt.name, pulp.LpMinimize)

    # generate student-to-slot assignment matrix
    # the entries of this matrix are either 0 or 1 representing 'unassigned' or 'assigned'
    X = pulp.LpVariable.dicts("x", itertools.product(range(number_talks), range(number_slots)), cat=pulp.LpBinary)

    # generate assessor-to-slot assignment matrix
    # the entries of this matrix are either 0 or 1 representing 'unassigned' or 'assigned'
    Y = pulp.LpVariable.dicts("y", itertools.product(range(number_assessors), range(number_slots)), cat=pulp.LpBinary)

    # for each period, generate a 'used' variable for each slot
    # this is used to determine (a) whether a slot is in use, and (b) which period the slot corresponds to
    S = pulp.LpVariable.dicts("s", itertools.product(range(number_periods), range(number_slots)), cat=pulp.LpBinary)

    # for each assessor, generate a 'used' variable
    # this is used to bias the optimizer to spread work around so that the minimum number of
    # assessors are left with no work
    U = pulp.LpVariable.dicts("u", range(number_assessors), cat=pulp.LpBinary)

    # for each talk and slot combination, generate a matrix to record how many assessors are drawn from the
    # corresponding assessor pool (or research group)
    # this is used to bias the optimizer to schedule students from compatible pools/groups together
    P = pulp.LpVariable.dicts("p", itertools.product(range(number_talks), range(number_slots)), cat=pulp.LpInteger)

    # variables representing maximum and minimum number of assignments
    # we use these to tension the optimization so that workload tends to be balanced
    amax = pulp.LpVariable("aMax", lowBound=0, cat=pulp.LpInteger)
    amin = pulp.LpVariable("aMin", lowBound=0, cat=pulp.LpInteger)

    # OBJECTIVE FUNCTION

    objective = make_objective(X, Y, S, number_talks, number_assessors, number_slots, attempt)
    prob += objective, "objective function"

    # keep track of how many constraints we generate
    constraints = 0

    # SLOT OCCUPATION

    # sum of occupation variables (over different periods) for each slot must be <= 1
    # this allows just one period type per slot
    for k in range(number_slots):
        prob += sum(S[(m, k)] for m in range(number_periods)) <= 1
        constraints += 1

    # if a talk is scheduled in a slot, then the corresponding occupation variable must be nonzero
    for i in range(number_talks):
        talk = talk_dict[i]
        m = period_to_number[talk.period_id]

        for k in range(number_slots):
            prob += S[(m, k)] >= X[(i, k)]
            constraints += 1

    # FACULTY (ASSESSOR) AVAILABILITY

    # faculty members should be scheduled only in slots for which they are available
    for idx in A:
        if A[idx] == 0:
            # no need to add a constraint if occupation is allowed, because the upper limit of 1 is implied
            # by use of boolean variables.
            prob += Y[idx] == 0
            constraints += 1

    # faculty members can be scheduled only up to the maximum specified multiplicity per session
    # for physical rooms this will usually be 1, but for Zoom-style teleconferences it could be larger
    # (corresponding to running different Zoom calls with different assessors)
    for session in attempt.owner.sessions:
        for j in range(number_assessors):
            prob += sum(Y[(j, k)] for k in range(number_slots) if slot_dict[k].session_id == session.id) <= attempt.assessor_multiplicity_per_session
            constraints += 1

    # number of times each faculty member is scheduled should fall below the hard limit, or the
    # exceptional limit for this faculty member (if specified)
    for j in range(number_assessors):
        if j in assessor_limits:
            print(
                '-- overwriting default assignment limit for assessor "{name}" with limit = '
                "{lim}".format(name=assessor_dict[j].user.name, lim=assessor_limits[j])
            )
            prob += sum(Y[(j, k)] for k in range(number_slots)) <= int(assessor_limits[j])
        else:
            prob += sum(Y[(j, k)] for k in range(number_slots)) <= int(attempt.assessor_assigned_limit)
        constraints += 1

    # if an assessor is scheduled in any slot, their occupation variable is allowed to become 1, otherwise
    # it is forced it zero
    for j in range(number_assessors):
        prob += U[j] <= sum(Y[(j, k)] for k in range(number_slots))
        constraints += 1

    # the purpose of U is to bias optimizer to leave the minimum number of faculty without work
    objective += sum(1 - U[j] for j in range(number_assessors))

    # STUDENT (SUBMITTER) AVAILABILITY

    # students should be scheduled only in slots for which they are available
    for idx in B:
        if B[idx] == 0:
            # no need to add a constraint if occupation is allowed, because the upper limit of 1 is implied
            # by use of boolean variables. Any constraint would just be removed in pre-solve.
            prob += X[idx] == 0
            constraints += 1

    # TALKS

    # talks should be scheduled in exactly one slot
    for i in range(number_talks):
        prob += sum(X[(i, k)] for k in range(number_slots)) == 1
        constraints += 1

    # each slot should have the required number of assessors (given its occupancy), *if* the slot is occupied:
    for m in range(number_periods):
        period: SubmissionPeriodRecord = period_dict[m]
        config: ProjectClassConfig = period.config

        # build list of enrolled assessors for this period
        allowed_assessors = set()
        for j in range(number_assessors):
            assessor: FacultyData = assessor_dict[j]
            enrolment: EnrollmentRecord = assessor.get_enrollment_record(config.pclass_id)

            if enrolment is not None and enrolment.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED:
                allowed_assessors.add(j)

        # if slot k is assigned to period m, then the sum of the assessor set should at least equal the expected
        # number of assessors
        # (note that we don't want assessor_set == S_mk * num_assessors, because if S_mk is zero this will force
        # all the Y_jk in allowed_assessors to be zero likewise, which would incorrectly prohibit faculty with multiple
        # enrolments from being assigned to this slot -- we have to impose the requirement that the total number
        # of assessors exactly matches the expected number separately)
        for k in range(number_slots):
            assessor_set = sum(Y[(j, k)] for j in allowed_assessors)

            prob += assessor_set >= S[(m, k)] * int(period.number_assessors)
            constraints += 1

    for k in range(number_slots):
        prob += sum([Y[(j, k)] for j in range(number_assessors)]) == sum(
            [S[(m, k)] * int(period_dict[m].number_assessors) for m in range(number_periods)]
        )
        constraints += 1

    # each slot should have no more than the maximum number of students:
    for m in range(number_periods):
        period: SubmissionPeriodRecord = period_dict[m]

        # build list of allowed talks for this period
        allowed_talks = set()
        for i in range(number_talks):
            talk: SubmissionRecord = talk_dict[i]

            if talk.period_id == period.id:
                allowed_talks.add(i)

        # if slot k is assigned to period m, then the sum of students assigned to slot k should not be more than
        # the maximum group size or the available room capacity, whichever is smaller
        for k in range(number_slots):
            slot: ScheduleSlot = slot_dict[k]
            room: Room = slot.room
            room_capacity = int(room.capacity)

            talk_set = sum(X[(i, k)] for i in allowed_talks)

            max_capacity = min(room_capacity - int(period.number_assessors), int(period.max_group_size))

            prob += talk_set <= S[(m, k)] * max_capacity
            constraints += 1

    # TALKS SHOULD NOT CLASH WITH OTHER TALKS BELONGING TO THE SAME PROJECT, IF THAT OPTION IS SET
    # (talk should also be scheduled only with other talks belonging to the same project class, but
    # this is taken care of by the constraints on occupation variables above, so doesn't have to be
    # done explicitly here)

    if not attempt.ignore_coscheduling:
        for i in range(number_talks):
            talk_i = talk_dict[i]

            for j in range(i):
                talk_j = talk_dict[j]

                # note that we have j strictly less than i here, so i=j is excluded
                for k in range(number_slots):
                    cant_pair = False
                    if talk_i.owner.config_id == talk_j.owner.config_id:
                        if talk_i.project_id == talk_j.project_id:
                            if talk_i.project.dont_clash_presentations:
                                cant_pair = True

                    if cant_pair:
                        prob += X[(i, k)] + X[(j, k)] <= 1
                        constraints += 1

    # TALKS CAN ONLY BE SCHEDULED WITH ASSESSORS WHO ARE SUITABLE
    # the definition of 'suitable' depends on whether we insist all assessors belong to the assessor pool
    # for each project, or not. This is controlled by the 'all_assessors_in_pool' attribute.

    def _make_assessor_objective(i: int, mode: str, not_available_predicate):
        nonlocal prob, constraints, objective

        if mode not in ["all", "one"]:
            raise RuntimeError("Unknown assessor objective mode in _make_assessor_objective()")

        talk: SubmissionRecord = talk_dict[i]

        allowed_assessors = set()
        for j in range(number_assessors):
            assessor: FacultyData = assessor_dict[j]

            if not not_available_predicate(talk, assessor):
                allowed_assessors.add(j)

        for k in range(number_slots):
            assessor_sum = sum(Y[(j, k)] for j in allowed_assessors)

            # insist that *at least one* assessor is in the assessor pool for this talk, for whichever
            prob += assessor_sum >= X[(i, k)]
            constraints += 1

            # if mode = 'all' then we *also* want to insist that every assessor belongs to allowed_assessors
            # in theory this can be done by just requiring assessor_sum == num_assessors * X_ik, but the snag
            # is that num_assessors depends on the *period*, not the *slot*, so there seems no way to write a linear
            # constraint that enforces this; we apparently have to write a group of constraints that
            # disallow assessors who don't fall in the allowed set
            if mode == "all":
                for j in range(number_assessors):
                    if j not in allowed_assessors:
                        # don't allow talk i and assessor j to be scheduled in slot k simultaneously
                        prob += X[(i, k)] + Y[(j, k)] <= 1
                        constraints += 1

            # P_ik is supposed to measure the number of assessors assigned to this slot who match the
            # allowed assessor criteria; we try to maximize that
            prob += assessor_sum >= P[(i, k)]
            objective += -P[(i, k)]
            constraints += 1

    def _make_assessor_objective_pool(i, mode: str):
        if mode not in ["all", "one"]:
            raise RuntimeError("Unknown assessor objective mode in _make_assessor_objective_pool()")

        def _not_available_predicate(talk: SubmissionRecord, assessor: FacultyData):
            # don't need to check enrolment status because that is enforced as part of the "TALKS" group above
            return not talk.project.is_assessor(assessor.id)

        return _make_assessor_objective(i, mode, _not_available_predicate)

    def _make_assessor_objective_research_group(i, mode: str):
        if mode not in ["all", "one"]:
            raise RuntimeError("Unknown assessor objective mode in _make_assessor_objective_research_group()")

        def _not_available_predicate(talk: SubmissionRecord, assessor: FacultyData):
            # don't need to check enrolment status because that is enforced as part of the "TALKS" group above
            project: LiveProject = talk.project
            group: ResearchGroup = project.group

            # a research group might not be specified - they're typically not used for generic projects, or the
            # 'advertise_research_group' flag might not be set. So, we can't assume that research group
            # data will be available.
            # In this case, we fall back on the assessor pool
            if group is None:
                return not talk.project.is_assessor(assessor.id)

            return not assessor.has_affiliation(group) and not talk.project.is_assessor(assessor.id)

        return _make_assessor_objective(i, mode, _not_available_predicate)

    if attempt.all_assessors_in_pool == ScheduleAttempt.ALL_IN_POOL:
        for i in range(number_talks):
            _make_assessor_objective_pool(i, "all")

    elif attempt.all_assessors_in_pool == ScheduleAttempt.AT_LEAST_ONE_IN_POOL:
        for i in range(number_talks):
            _make_assessor_objective_pool(i, "one")

    elif attempt.all_assessors_in_pool == ScheduleAttempt.ALL_IN_RESEARCH_GROUP:
        for i in range(number_talks):
            _make_assessor_objective_research_group(i, "all")

    elif attempt.all_assessors_in_pool == ScheduleAttempt.AT_LEAST_ONE_IN_RESEARCH_GROUP:
        for i in range(number_talks):
            _make_assessor_objective_research_group(i, "one")

    else:
        raise RuntimeError("Unknown value for ScheduleAttempt.all_assessors_in_pool in _create_PuLP_problem()")

    # TALKS CANNOT BE SCHEDULED WITH A SUPERVISOR AS AN ASSESSOR

    for i in range(number_talks):
        talk: SubmissionRecord = talk_dict[i]
        supervisors: List[SubmissionRole] = talk.supervisor_roles
        for supervisor in supervisors:
            supervisor_id = supervisor.id

            # it's not an error if supervisor_id is not in assessor_to_number; this just means that the supervisor
            # is not a possible assessor.
            # that most likely way this could happen is if the supervisor is exempt/on sabbatical from
            # presentation assessments, e.g. as HoD or HoS
            if supervisor_id in assessor_to_number:
                j = assessor_to_number[supervisor_id]

                for k in range(number_slots):
                    prob += X[(i, k)] + Y[(j, k)] <= 1
                    constraints += 1

    # TALKS SHOULD ONLY BE SCHEDULED IN ROOMS WITH SUITABLE FACILITIES

    for i in range(number_talks):
        talk = talk_dict[i]

        for k in range(number_slots):
            slot = slot_dict[k]
            slot_ok = True

            if not talk.period.has_presentation:
                raise RuntimeError("Inconsistent presentation state in SubmissionPeriodRecord")

            if talk.period.lecture_capture and not slot.room.lecture_capture:
                slot_ok = False

            # future options can be inserted here

            if not slot_ok:
                prob += X[(i, k)] == 0
                constraints += 1

    # WORKLOAD LEVELLING

    # amax and amin should bracket the workload of each faculty member
    for i in range(number_assessors):
        prob += sum(Y[(i, k)] for k in range(number_slots)) <= amax
        prob += sum(Y[(i, k)] for k in range(number_slots)) >= amin
        constraints += 2

    # optimizer should use amin and amax to (try to) balance workloads as evenly as possible
    objective += abs(float(attempt.levelling_tension)) * (amax - amin)

    print(" -- {num} total constraints".format(num=constraints))

    return prob, X, Y


def _store_PuLP_solution(X, Y, record: ScheduleAttempt, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict):
    """
    Store a solution to the talk scheduling problem
    :param X:
    :param Y:
    :param record:
    :param number_talks:
    :param number_assessors:
    :param number_slots:
    :param talk_dict:
    :param assessor_dict:
    :param slot_dict:
    :return:
    """

    store_slots = []

    for i in range(number_slots):
        slot: ScheduleSlot = slot_dict[i]

        # we only store slots that are scheduled
        store = False

        for j in range(number_talks):
            X[(j, i)].round()
            if pulp.value(X[(j, i)]) == 1:
                store = True
                talk: SubmissionRecord = talk_dict[j]

                if talk not in slot.talks:
                    slot.talks.append(talk)
                    slot.original_talks.append(talk)

        for j in range(number_assessors):
            Y[(j, i)].round()
            if pulp.value(Y[(j, i)]) == 1:
                assessor: FacultyData = assessor_dict[j]

                # no need to set store = True here; we only store this slot if it actually has
                # some assigned talks

                if assessor not in slot.assessors:
                    slot.assessors.append(assessor)
                    slot.original_assessors.append(assessor)

        if store:
            store_slots.append(slot)

    # slots are marked cascade='all, delete, delete-orphan', so SQLAlchemy will tidy up after us here;
    # we don't have to *explicitly* delete any instances of ScheduleSlot
    record.slots = store_slots


def _create_slots(self, record: ScheduleAttempt):
    # add database records for each available slot (meaning a combination of session+room);
    # the ones we don't use will be cleaned up later
    print(f' -- creating slots for ScheduleAttempt {record.id} (presentation="{record.owner.name}")')

    count = 0
    for sess in record.owner.sessions:
        sess: PresentationSession
        print(f' -- ## creating slots for session "{sess.name}"')

        for room in sess.rooms:
            room: Room
            print(f' -- ## ## creating slots for room "{room.name}", max occupancy = {room.maximum_occupancy}')

            if room.maximum_occupancy == 0:
                print(f' !! WARNING: room "{room.name}" has maximum occupancy = 0 and will not be used')

            for s in range(0, room.maximum_occupancy):
                slot = ScheduleSlot(owner_id=record.id, session_id=sess.id, occupancy_label=s+1, room_id=room.id)
                db.session.add(slot)
                count += 1

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()
    else:
        print(f' -- created {count} slots')


def _initialize(self, record, read_serialized=False):
    progress_update(record.celery_id, TaskRecord.RUNNING, 5, "Collecting information...", autocommit=True)

    try:
        with Timer() as talk_timer:
            number_talks, talk_to_number, number_to_talk, talk_dict = _enumerate_talks(record, read_serialized=read_serialized)
        print(f" -- enumerated {number_talks} talks in time {talk_timer.interval:.5g} s")

        with Timer() as assessor_timer:
            number_assessors, assessor_to_number, number_to_assessor, assessor_dict, assessor_limits = _enumerate_assessors(
                record, read_serialized=read_serialized
            )
        print(f" -- enumerated {number_assessors} assessors in time {assessor_timer.interval:.5g} s")

        with Timer() as periods_timer:
            number_periods, period_to_number, number_to_period, period_dict = _enumerate_periods(record, read_serialized=read_serialized)
        print(f" -- enumerated {number_periods} periods in time {periods_timer.interval:.5g} s")

        with Timer() as slots_timer:
            number_slots, slot_to_number, number_to_slot, slot_dict = _enumerate_slots(record, read_serialized=read_serialized)
        print(f" -- enumerated {number_slots} slots in time {slots_timer.interval:.5g} s")

        # build faculty availability and 'ifneeded' cost matrix
        with Timer() as fac_avail_timer:
            A: AvailabilityMatrix
            C: AvailabilityMatrix
            A, C = _build_faculty_availability_matrix(number_assessors, assessor_dict, number_slots, slot_dict)
        print(f" -- computed faculty availabilities in time {fac_avail_timer.interval:.5g} s")

        # build submitter availability matrix
        with Timer() as sub_avail_timer:
            B: AvailabilityMatrix
            B = _build_student_availability_matrix(number_talks, talk_dict, number_slots, slot_dict)
        print(f" -- computed submitter availabilities in time {sub_avail_timer.interval:.5g} s")

    except SQLAlchemyError as e:
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    return (
        number_talks,
        number_assessors,
        number_slots,
        number_periods,
        talk_to_number,
        assessor_to_number,
        slot_to_number,
        period_to_number,
        number_to_talk,
        number_to_assessor,
        number_to_slot,
        number_to_period,
        talk_dict,
        assessor_dict,
        slot_dict,
        period_dict,
        assessor_limits,
        A,
        B,
        C,
    )


def _execute_live(self, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict):
    print("Solving PuLP problem for schedule")

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...", autocommit=True)

    with Timer() as solve_time:
        record.awaiting_upload = False

        if record.solver == ScheduleAttempt.SOLVER_CBC_PACKAGED:
            status = prob.solve(pulp_apis.PULP_CBC_CMD(msg=1, timeLimit=3600, gapRel=0.25))
        elif record.solver == ScheduleAttempt.SOLVER_CBC_CMD:
            status = prob.solve(pulp_apis.COIN_CMD(msg=True, timeLimit=3600, gapRel=0.25))
        elif record.solver == ScheduleAttempt.SOLVER_GLPK_CMD:
            status = prob.solve(pulp_apis.GLPK_CMD())
        elif record.solver == ScheduleAttempt.SOLVER_CPLEX_CMD:
            status = prob.solve(pulp_apis.CPLEX_CMD())
        elif record.solver == ScheduleAttempt.SOLVER_GUROBI_CMD:
            status = prob.solve(pulp_apis.GUROBI_CMD())
        elif record.solver == ScheduleAttempt.SOLVER_SCIP_CMD:
            status = prob.solve(pulp_apis.SCIP_CMD())
        else:
            status = prob.solve()

    return _process_PuLP_solution(
        self, record, prob, status, solve_time, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict
    )


def _execute_from_solution(
    self, file, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict
):
    print('Processing PuLP solution from "{name}"'.format(name=file))

    if not path.exists(file):
        progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Could not locate uploaded solution file", autocommit=True)
        raise Ignore

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Processing uploaded solution file...", autocommit=True)

    # TODO: catch pulp.pulp_apis.PulpSolverError: Unknown status returned by CPLEX
    #  and handle it gracefully (or fix it on the fly)
    with Timer() as solve_time:
        record.awaiting_upload = False
        wasNone, dummyVar = prob.fixObjective()

        if record.solver == ScheduleAttempt.SOLVER_CBC_PACKAGED:
            solver = pulp_apis.PULP_CBC_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol_LP(file, prob, prob.variables())
        elif record.solver == ScheduleAttempt.SOLVER_CBC_CMD:
            solver = pulp_apis.COIN_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol_LP(file, prob, prob.variables())
        elif record.solver == ScheduleAttempt.SOLVER_GLPK_CMD:
            solver = pulp_apis.GLPK_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol(file)
        elif record.solver == ScheduleAttempt.SOLVER_CPLEX_CMD:
            solver = pulp_apis.CPLEX_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol(file)
        elif record.solver == ScheduleAttempt.SOLVER_GUROBI_CMD:
            solver = pulp_apis.GUROBI_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol(file)
        elif record.solver == ScheduleAttempt.SOLVER_SCIP_CMD:
            solver = pulp_apis.SCIP_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol(file)
        else:
            progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Unknown solver", autocommit=True)
            raise Ignore()

        if status != pulp.LpStatusInfeasible:
            prob.assignVarsVals(values)
            prob.assignVarsDj(reducedCosts)
            prob.assignConsPi(shadowPrices)
            prob.assignConsSlack(slacks)
        prob.status = status

        prob.restoreObjective(wasNone, dummyVar)
        prob.solver = solver

    return _process_PuLP_solution(
        self, record, prob, status, solve_time, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict
    )


def _process_PuLP_solution(
    self, record, prob, status, solve_time, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict
):
    state = pulp.LpStatus[status]

    if state == "Optimal":
        record.outcome = ScheduleAttempt.OUTCOME_OPTIMAL
        record.score = pulp.value(prob.objective)

        record.construct_time = create_time.interval
        record.compute_time = solve_time.interval

        progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing PuLP solution...", autocommit=True)

        try:
            _store_PuLP_solution(X, Y, record, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    elif state == "Not Solved":
        record.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED
    elif state == "Infeasible":
        record.outcome = ScheduleAttempt.OUTCOME_INFEASIBLE
    elif state == "Unbounded":
        record.outcome = ScheduleAttempt.OUTCOME_UNBOUNDED
    elif state == "Undefined":
        record.outcome = ScheduleAttempt.OUTCOME_UNDEFINED
    else:
        raise RuntimeError("Unknown PuLP outcome")

    try:
        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, "Scheduling complete", autocommit=False)

        record.finished = True
        record.celery_finished = True
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    return record.score


def _send_offline_email(celery, record, user, lp_asset):
    send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

    msg = EmailMultiAlternatives(
        subject="Files for offline scheduling of {name} are now ready".format(name=record.name),
        from_email=current_app.config["MAIL_DEFAULT_SENDER"],
        reply_to=[current_app.config["MAIL_REPLY_TO"]],
        to=[user.email],
    )

    msg.body = render_template("email/scheduling/generated.txt", name=record.name, user=user)

    # TODO: will be problems when generated LP/MPS files are too large; should instead send a download link
    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
    lp_storage: AssetCloudAdapter = AssetCloudAdapter(lp_asset, object_store, audit_data="scheduling._send_offline_email #1")

    msg.attach(filename=str("schedule.lp"), mimetype=lp_asset.mimetype, content=lp_storage.get())

    # register a new task in the database
    task_id = register_task(msg.subject, description="Email to {r}".format(r=", ".join(msg.to)))
    send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


def _write_LP_MPS_files(record: ScheduleAttempt, prob, user):
    now = datetime.now()
    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

    def make_asset(source_path: Path, target_name: str):
        # AssetUploadManager will populate most fields later
        asset = GeneratedAsset(timestamp=now, expiry=None, target_name=target_name, parent_asset_id=None, license_id=None)

        size = source_path.stat().st_size

        with open(source_path, "rb") as f:
            with AssetUploadManager(
                asset,
                data=BytesIO(f.read()),
                storage=object_store,
                audit_data=f"scheduling._write_LP_MPS_files (schedule attempt #{record.id})",
                length=size,
                mimetype="text/plain",
                validate_nonce=validate_nonce,
            ) as upload_mgr:
                pass

        asset.grant_user(user)
        db.session.add(asset)

        return asset

    with ScratchFileManager(suffix="lp") as mgr:
        lp_path: Path = mgr.path
        prob.writeLP(lp_path)
        lp_asset = make_asset(lp_path, "schedule.lp")

    # write new assets to database, so they get a valid primary key
    db.session.flush()

    # add asset details to ScheduleAttempt record
    record.lp_file = lp_asset

    # allow exceptions to propagate up to calling function
    record.celery_finished = True
    db.session.commit()

    return lp_asset


def _store_enumeration_details(record, number_to_talk, number_to_assessor, number_to_slot, number_to_period):
    def write_out(label, block):
        for number in block:
            data = ScheduleEnumeration(schedule_id=record.id, enumeration=number, key=block[number], category=label)
            db.session.add(data)

    write_out(ScheduleEnumeration.SUBMITTER, number_to_talk)
    write_out(ScheduleEnumeration.ASSESSOR, number_to_assessor)
    write_out(ScheduleEnumeration.SLOT, number_to_slot)
    write_out(ScheduleEnumeration.PERIOD, number_to_period)

    # allow exceptions produced by SQLAlchemy to propagate up to calling function
    db.session.commit()


def register_scheduling_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def create_schedule(self, id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ScheduleAttempt record for id={id}".format(id=id)})

        try:
            record: ScheduleAttempt = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise Ignore()

        _create_slots(self, record)

        with Timer() as create_time:
            (
                number_talks,
                number_assessors,
                number_slots,
                number_periods,
                talk_to_number,
                assessor_to_number,
                slot_to_number,
                period_to_number,
                number_to_talk,
                number_to_assessor,
                number_to_slot,
                number_to_period,
                talk_dict,
                assessor_dict,
                slot_dict,
                period_dict,
                assessor_limits,
                A,
                B,
                C,
            ) = _initialize(self, record)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

            prob, X, Y = _create_PuLP_problem(
                A,
                B,
                record,
                number_talks,
                number_assessors,
                number_slots,
                number_periods,
                assessor_to_number,
                period_to_number,
                talk_dict,
                assessor_dict,
                slot_dict,
                period_dict,
                assessor_limits,
                partial(_generate_minimize_objective, C),
            )

        print(f" -- creation complete in time {create_time.interval:.5g} s")

        return _execute_live(self, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict)

    @celery.task(bind=True, default_retry_delay=30)
    def recompute_schedule(self, new_id, old_id, allow_new_slots):
        if isinstance(allow_new_slots, str):
            allow_new_slots = strtobool(allow_new_slots)

        self.update_state(
            state="STARTED",
            meta={"msg": "Looking up ScheduleAttempt records for new_id={new_id}, old_id={old_id}"}.format(new_id=new_id, old_id=old_id),
        )

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=new_id).first()
            old_record = db.session.query(ScheduleAttempt).filter_by(id=old_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None or old_record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise Ignore()

        _create_slots(self, record)

        with Timer() as create_time:
            (
                number_talks,
                number_assessors,
                number_slots,
                number_periods,
                talk_to_number,
                assessor_to_number,
                slot_to_number,
                period_to_number,
                number_to_talk,
                number_to_assessor,
                number_to_slot,
                number_to_period,
                talk_dict,
                assessor_dict,
                slot_dict,
                period_dict,
                assessor_limits,
                A,
                B,
                C,
            ) = _initialize(self, record)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

            oldX, oldY = _reconstruct_XY(
                self, old_record, number_talks, number_assessors, number_slots, talk_to_number, assessor_to_number, slot_dict
            )

            prob, X, Y = _create_PuLP_problem(
                A,
                B,
                record,
                number_talks,
                number_assessors,
                number_slots,
                number_periods,
                assessor_to_number,
                period_to_number,
                talk_dict,
                assessor_dict,
                slot_dict,
                period_dict,
                assessor_limits,
                partial(_generate_reschedule_objective, C, oldX, oldY),
            )

            if not allow_new_slots:
                print(" -- new slots are not allowed; disallowing use of any slots not present in original schedule")
                _forbid_unused_slots(prob, X, Y, number_assessors, number_talks, slot_dict, old_record)

        print(f" -- creation complete in time {create_time.interval:.5g} s")

        record.solver = ScheduleAttempt.SOLVER_CBC_PACKAGED
        return _execute_live(self, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots, talk_dict, assessor_dict, slot_dict)

    @celery.task(bind=True, default_retry_delay=30)
    def offline_schedule(self, schedule_id, user_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ScheduleAttempt record for id={id}".format(id=schedule_id)})

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            record = db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise Ignore()

        _create_slots(self, record)

        with Timer() as create_time:
            (
                number_talks,
                number_assessors,
                number_slots,
                number_periods,
                talk_to_number,
                assessor_to_number,
                slot_to_number,
                period_to_number,
                number_to_talk,
                number_to_assessor,
                number_to_slot,
                number_to_period,
                talk_dict,
                assessor_dict,
                slot_dict,
                period_dict,
                assessor_limits,
                A,
                B,
                C,
            ) = _initialize(self, record)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

            prob, X, Y = _create_PuLP_problem(
                A,
                B,
                record,
                number_talks,
                number_assessors,
                number_slots,
                number_periods,
                assessor_to_number,
                period_to_number,
                talk_dict,
                assessor_dict,
                slot_dict,
                period_dict,
                assessor_limits,
                partial(_generate_minimize_objective, C),
            )

        print(f" -- creation complete in time {create_time.interval:.5g} s")

        progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Writing .LP file...", autocommit=True)

        try:
            lp_asset = _write_LP_MPS_files(record, prob, user)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        _send_offline_email(celery, record, user, lp_asset)

        progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing schedule details for later processing...", autocommit=True)

        try:
            _store_enumeration_details(record, number_to_talk, number_to_assessor, number_to_slot, number_to_period)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, "File generation for offline scheduling now complete", autocommit=True)
        user.post_message("The files necessary to perform offline scheduling have been emailed to you", "info", autocommit=True)

    @celery.task(bind=True, default_retry_delay=30)
    def process_offline_solution(self, schedule_id, asset_id, user_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up TemporaryAsset record for id={id}".format(id=asset_id)})

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            asset = db.session.query(TemporaryAsset).filter_by(id=asset_id).first()
            record = db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if asset is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load TemporaryAsset record"})
            raise Ignore()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise Ignore()

        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        storage = AssetCloudAdapter(asset, object_store, audit_data=f"scheduling.process_offline_solution(schedule id #{schedule_id})")
        with storage.download_to_scratch() as scratch_path:
            with Timer() as create_time:
                (
                    number_talks,
                    number_assessors,
                    number_slots,
                    number_periods,
                    talk_to_number,
                    assessor_to_number,
                    slot_to_number,
                    period_to_number,
                    number_to_talk,
                    number_to_assessor,
                    number_to_slot,
                    number_to_period,
                    talk_dict,
                    assessor_dict,
                    slot_dict,
                    period_dict,
                    assessor_limits,
                    A,
                    B,
                    C,
                ) = _initialize(self, record, read_serialized=True)

                progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

                prob, X, Y = _create_PuLP_problem(
                    A,
                    B,
                    record,
                    number_talks,
                    number_assessors,
                    number_slots,
                    number_periods,
                    assessor_to_number,
                    period_to_number,
                    talk_dict,
                    assessor_dict,
                    slot_dict,
                    period_dict,
                    assessor_limits,
                    partial(_generate_minimize_objective, C),
                )

            print(f" -- creation complete in time {create_time.interval:.5g} s")

            # ScheduleEnumeration records will be purged during normal database maintenance cycle,
            # so there is no need to delete them explicitly here

            soln = _execute_from_solution(
                self,
                scratch_path.path,
                record,
                prob,
                X,
                Y,
                create_time,
                number_talks,
                number_assessors,
                number_slots,
                talk_dict,
                assessor_dict,
                slot_dict,
            )

        return soln

    @celery.task(bind=True, default_retry_delay=30)
    def revert_record(self, id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ScheduleSlot record for id={id}".format(id=id)})

        try:
            record = db.session.query(ScheduleSlot).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load ScheduleSlot record from database"})
            raise Ignore

        try:
            record.talks = record.original_talks
            record.assessors = record.original_assessors
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def revert_finalize(self, id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ScheduleAttempt record for id={id}".format(id=id)})

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore

        try:
            record.last_edit_id = None
            record.last_edit_timestamp = None
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def revert(self, id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ScheduleAttempt record for id={id}".format(id=id)})

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore

        wg = group(revert_record.si(s.id) for s in record.slots.all())
        seq = chain(wg, revert_finalize.si(id))

        seq.apply_async()

    @celery.task(bind=True, default_retry_delay=30)
    def duplicate(self, id, new_name, current_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ScheduleAttempt record for id={id}".format(id=id)})

        try:
            old_record: ScheduleAttempt = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if old_record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            return

        try:
            # generate a new ScheduleAttempt
            new_record = ScheduleAttempt(
                owner_id=old_record.owner_id,
                name=new_name,
                tag=None,
                solver=old_record.solver,
                construct_time=old_record.construct_time,
                compute_time=old_record.compute_time,
                celery_id=None,
                awaiting_upload=old_record.awaiting_upload,
                outcome=old_record.outcome,
                finished=old_record.finished,
                celery_finished=True,
                score=old_record.score,
                published=old_record.published,
                deployed=False,
                assessor_assigned_limit=old_record.assessor_assigned_limit,
                assessor_multiplicity_per_session=old_record.assessor_multiplicity_per_session,
                if_needed_cost=old_record.if_needed_cost,
                levelling_tension=old_record.levelling_tension,
                ignore_coscheduling=old_record.ignore_coscheduling,
                all_assessors_in_pool=old_record.all_assessors_in_pool,
                creator_id=current_id,
                creation_timestamp=datetime.now(),
                last_edit_id=None,
                last_edit_timestamp=None,
                lp_file_id=None,
            )

            db.session.add(new_record)
            db.session.flush()

            new_record.tag = "schedule_{n}".format(n=new_record.id)

            # duplicate all slots
            slot_map = {}
            for slot in old_record.slots:
                slot: ScheduleSlot
                rec = ScheduleSlot(
                    owner_id=new_record.id,
                    session_id=slot.session_id,
                    room_id=slot.room_id,
                    occupancy_label=slot.occupancy_label,
                    assessors=slot.assessors,
                    talks=slot.talks,
                    original_assessors=slot.assessors,
                    original_talks=slot.original_talks,
                )
                db.session.add(rec)
                db.session.flush()

                # remember the mapping from old slot to new slot
                slot_map[slot.id] = rec.id

            # duplicate all enumerations
            if new_record.awaiting_upload:
                for item in old_record.enumerations:
                    if item.category != ScheduleEnumeration.SLOT:
                        new_key = item.key
                    else:
                        if item.key in slot_map:
                            new_key = slot_map[item.key]
                        else:
                            raise RuntimeError("Could not map from old to new ScheduleSlot ids")

                    en = ScheduleEnumeration(category=item.category, enumeration=item.enumeration, key=new_key, schedule_id=new_record.id)
                    db.session.add(en)

                now = datetime.now()

                object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

                def copy_asset(old_asset):
                    old_storage = AssetCloudAdapter(old_asset, object_store, audit_data=f"scheduling.duplicate.copy_asset (schedule id #{id})")
                    new_key, put_result = old_storage.duplicate(validate_nonce=validate_nonce)

                    new_base64_nonce = None
                    if "nonce" in put_result:
                        new_base64_nonce = base64.urlsafe_b64encode(put_result["nonce"]).decode("ascii")

                    # must duplicate all fields, including those usually managed by AssetUploadManager
                    new_asset = GeneratedAsset(
                        timestamp=now,
                        expiry=None,
                        unique_name=new_key,
                        filesize=old_asset.filesize,
                        mimetype=old_asset.mimetype,
                        target_name=old_asset.target_name,
                        parent_asset_id=old_asset.parent_asset_id,
                        license_id=old_asset.license_id,
                        lost=False,
                        unattached=False,
                        bucket=old_asset.bucket,
                        comment=old_asset.comment,
                        encryption=object_store.encrypted,
                        encrypted_size=put_result.get("encrypted_size", None),
                        nonce=new_base64_nonce,
                        compressed=object_store.compressed,
                        compressed_size=put_result.get("compressed_size", None),
                    )

                    # TODO: find a way to perform a deep copy without exposing implementation details
                    new_asset.access_control_list = old_asset.access_control_list
                    new_asset.access_control_roles = old_asset.access_control_roles
                    db.session.add(new_asset)

                    return new_asset

                if old_record.lp_file is not None:
                    new_record.lp_file = copy_asset(old_record.lp_file, "schedule.lp", ext="lp")

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def publish_to_submitters(self, id, user_id, task_id):
        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise self.retry()

        progress_update(task_id, TaskRecord.RUNNING, 10, "Building list of student submitters...", autocommit=True)

        recipients = set()
        for a in record.owner.submitter_list:
            if a.attending:
                recipients.add(a.id)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        task = chain(
            group(publish_email_to_submitter.si(id, a_id, not bool(record.deployed)) for a_id in recipients),
            notify.s(user_id, "{n} email notification{pl} issued", "info"),
            publish_to_submitter_finalize.si(task_id),
        )

        if record.deployed:
            record.final_to_submitters = datetime.now()
        else:
            record.draft_to_submitters = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        raise self.replace(task)

    @celery.task(bind=True)
    def publish_to_submitter_finalize(self, task_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Email job is complete", autocommit=True)

    @celery.task(bind=True, default_retry_delay=30)
    def publish_email_to_submitter(self, schedule_id, attend_id, is_draft):
        if isinstance(is_draft, str):
            is_draft = strtobool(is_draft)

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
            attend_data = db.session.query(SubmitterAttendanceData).filter_by(id=attend_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise self.retry()

        if attend_data is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmitterAttendanceData record from database"})
            raise self.retry()

        sub_record = attend_data.submitter
        student = sub_record.owner.student
        user = student.user
        event = record.owner

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        msg = EmailMultiAlternatives(
            from_email=current_app.config["MAIL_DEFAULT_SENDER"], reply_to=[current_app.config["MAIL_REPLY_TO"]], to=[user.email]
        )

        if is_draft:
            msg.subject = 'Notification: Draft timetable for project assessment "{name}"'.format(name=event.name)
            msg.body = render_template(
                "email/scheduling/draft_notify_students.txt",
                user=user,
                event=event,
                slot=record.get_student_slot(sub_record.owner_id).first(),
                period=sub_record.period,
                schedule=record,
            )

        else:
            msg.subject = 'Notification: Final timetable for project assessment "{name}"'.format(name=event.name)
            msg.body = render_template(
                "email/scheduling/final_notify_students.txt",
                user=user,
                event=event,
                slot=record.get_student_slot(sub_record.owner_id).first(),
                period=sub_record.period,
                schedule=record,
            )

        # register a new task in the database
        task_id = register_task(msg.subject, description="Send schedule email to {r}".format(r=", ".join(msg.to)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1

    @celery.task(bind=True, default_retry_delay=30)
    def publish_to_assessors(self, id, user_id, task_id):
        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise self.retry()

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        progress_update(task_id, TaskRecord.RUNNING, 10, "Building list of faculty assessors...", autocommit=True)

        task = chain(
            group(publish_email_to_assessor.si(id, a.id, not bool(record.deployed)) for a in record.owner.assessor_list.all()),
            notify.s(user_id, "{n} email notification{pl} issued", "info"),
            publish_to_assessors_finalize.si(task_id),
        )

        if record.deployed:
            record.final_to_assessors = datetime.now()
        else:
            record.draft_to_assessors = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        raise self.replace(task)

    @celery.task(bind=True)
    def publish_to_assessors_finalize(self, task_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Email job is complete", autocommit=True)

    @celery.task(bind=True, default_retry_delay=30)
    def publish_email_to_assessor(self, schedule_id, attend_id, is_draft):
        if isinstance(is_draft, str):
            is_draft = strtobool(is_draft)

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
            attend_data = db.session.query(AssessorAttendanceData).filter_by(id=attend_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load ScheduleAttempt record from database"})
            raise self.retry()

        if attend_data is None:
            self.update_state("FAILURE", meta={"msg": "Could not load AssessorAttendanceData record from database"})
            raise self.retry()

        faculty = attend_data.faculty
        user = faculty.user
        event = record.owner

        slots = record.get_faculty_slots(faculty.id).all()

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        msg = EmailMultiAlternatives(
            from_email=current_app.config["MAIL_DEFAULT_SENDER"], reply_to=[current_app.config["MAIL_REPLY_TO"]], to=[user.email]
        )

        if is_draft:
            msg.subject = 'Notification: Draft timetable for project assessment "{name}"'.format(name=event.name)

            if len(slots) > 0:
                msg.body = render_template("email/scheduling/draft_notify_faculty.txt", user=user, event=event, slots=slots, schedule=record)
            else:
                msg.body = render_template("email/scheduling/draft_unneeded_faculty.txt", user=user, event=event, schedule=record)

        else:
            msg.subject = 'Notification: Final timetable for project assessment "{name}"'.format(name=event.name)

            if len(slots) > 0:
                msg.body = render_template("email/scheduling/final_notify_faculty.txt", user=user, event=event, slots=slots, schedule=record)
            else:
                msg.body = render_template("email/scheduling/final_unneeded_faculty.txt", user=user, event=event, schedule=record)

        # register a new task in the database
        task_id = register_task(msg.subject, description="Send schedule email to {r}".format(r=", ".join(msg.to)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1
