#
# Created by David Seery on 2018-10-08.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..database import db
from ..models import TaskRecord, ScheduleAttempt, ScheduleSlot, GeneratedAsset, UploadedAsset, User

from ..task_queue import progress_update, register_task

from celery.exceptions import Ignore

from sqlalchemy.exc import SQLAlchemyError

import pulp
import pulp.solvers as solvers
import itertools
from functools import partial

from ..shared.timer import Timer
from ..shared.utils import make_generated_asset_filename, canonical_uploaded_asset_filename

from flask import current_app, render_template, url_for
from flask_mail import Message

from datetime import datetime
from os import path


def _enumerate_talks(assessment):
    # assessment is a PresentationAssessment instance
    number = 0
    talk_to_number = {}
    number_to_talk = {}

    talk_dict = {}

    # the .schedulable_talks property returns a list of of SubmissionRecord instances,
    # minus any students who are not attending the main assessment event and need to
    # be scheduled for the make-up event.
    for p in assessment.schedulable_talks:      # schedulable_talks comes with a defined order (needed for safe offline scheduling)
        talk_to_number[p.id] = number
        number_to_talk[number] = p.id

        talk_dict[number] = p

        number += 1

    return number, talk_to_number, number_to_talk, talk_dict


def _enumerate_assessors(record):
    # record is a PresentationAssessment instance
    number = 0
    assessor_to_number = {}
    number_to_assessor = {}

    assessor_dict = {}

    # the .assessor_list property returns a list of AssessorAttendanceData instances,
    # one for each assessor who has been invited to attend
    for assessor in record.ordered_assessors:  # ordered_assessors comes with a defined order (needed for safe offline scheduling)
        assessor_to_number[assessor.faculty_id] = number
        number_to_assessor[number] = assessor.faculty_id

        assessor_dict[number] = assessor.faculty

        number += 1

    return number, assessor_to_number, number_to_assessor, assessor_dict


def _enumerate_slots(record):
    # record is a ScheduleAttempt instance
    number = 0
    slot_to_number = {}
    number_to_slot = {}

    slot_dict = {}

    for slot in record.ordered_slots:           # ordered_slots comes with a defined order (needed for safe offline scheduling)
        slot_to_number[slot.id] = number
        number_to_slot[number] = slot.id

        slot_dict[number] = slot

        number += 1

    return number, slot_to_number, number_to_slot, slot_dict


def _build_faculty_availability_matrix(number_assessors, assessor_dict, number_slots, slot_dict):
    """
    Construct a dictionary mapping from (assessing-faculty, slot) pairs to yes/no availabilities,
    coded as 0 = not available, 1 = available
    :param number_assessors:
    :param assessor_dict:
    :param number_slots:
    :param slot_dict:
    :return:
    """
    A = {}
    C = {}

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


def _build_student_availability_matrix(number_talks, talk_dict, number_slots, slot_dict):
    """
    Construct a dictionary mapping from (submitting-student, slot) pairs to yes/no availabilities,
    coded a 0 = not available, 1 = not available
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


def _generate_minimize_objective(C, X, Y, S, number_talks, number_assessors, number_slots,
                                 amax, amin, record):
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
    objective = 0

    # ask optimizer to minimize the number of slots that are used
    objective += sum([S[i] for i in range(number_slots)])

    # optimizer should penalize any slots that use 'if needed'
    objective += sum([Y[(i, j)] * C[(i, j)] * abs(float(record.if_needed_cost)) for i in range(number_assessors)
                                                                                for j in range(number_slots)])

    # optimizer should try to balance workloads as evenly as possible
    objective += abs(float(record.levelling_tension)) * (amax - amin)

    # TODO: - minimize number of days used in schedule
    # TODO: - minimize number of rooms used in schedule

    return objective


def _generate_reschedule_objective(oldX, oldY, X, Y, S, number_talks, number_assessors, number_slots,
                                   amax, amin, record):
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

    # optimizer should try to balance workloads as evenly as possible
    objective += abs(record.levelling_tension) * (amax - amin)

    return objective


def _reconstruct_XY(self, old_id, number_talks, number_assessors, number_slots, talk_to_number, assessor_to_number,
                    slot_dict):
    try:
        record = db.session.query(ScheduleAttempt).filter_by(id=old_id).first()
    except SQLAlchemyError:
        raise self.retry()

    if record is None:
        self.update_state('FAILURE', meta='Could not load ScheduleAttempt record from database')
        raise self.retry()

    X = {}
    Y = {}

    reverse_slot_dict = {}
    for number in slot_dict:
        slot = slot_dict[number]
        reverse_slot_dict[(slot.session_id, slot.room_id)] = number

    for slot in record.slots:
        k = reverse_slot_dict[(slot.session_id, slot.room_id)]

        for talk in slot.talks:
            if talk.id in talk_to_number:                   # key might be missing if this talk has been removed; is so, just ignore
                i = talk_to_number[talk.id]
                X[(i, k)] = 1

        for assessor in slot.assessors:
            if assessor.id in assessor_to_number:           # key might be missing if this assessor has been removed; if so, just ignore
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


def _create_PuLP_problem(A, B, record, number_talks, number_assessors, number_slots, assessor_to_number, talk_dict,
                         assessor_dict, slot_dict, make_objective):
    """
    Generate a PuLP problem to find an optimal assignment of student talks + faculty assessors to rooms
    :param B:
    :param assessor_dict:
    :param talk_dict:
    :param slot_dict:
    :param record:
    :param A:
    :param number_talks:
    :param number_assessors:
    :param number_slots:
    :return:
    """

    print('Generating PuLP problem for schedule:')
    print(' -- {l} talks, {m} assessors, {n} slots'.format(l=number_talks, m=number_assessors, n=number_slots))

    # generate PuLP problem
    prob = pulp.LpProblem(record.name, pulp.LpMinimize)

    # generate student-to-slot assignment matrix
    # the entries of this matrix are either 0 or 1 representing 'unassigned' or 'assigned'
    X = pulp.LpVariable.dicts("x", itertools.product(range(number_talks), range(number_slots)), cat=pulp.LpBinary)

    # generate assessor-to-slot assignment matrix
    # the entries of this matrix are either 0 or 1 representing 'unassigned' or 'assigned'
    Y = pulp.LpVariable.dicts("y", itertools.product(range(number_assessors), range(number_slots)), cat=pulp.LpBinary)

    # generate a 'size counting' variable for each slot
    S = pulp.LpVariable.dicts("s", range(number_slots), cat=pulp.LpBinary)

    # variables representing maximum and minimum number of assignments
    # we use these to tension the optimization so that workload tends to be balanced
    amax = pulp.LpVariable("aMax", lowBound=0, cat=pulp.LpContinuous)
    amin = pulp.LpVariable("aMin", lowBound=0, cat=pulp.LpContinuous)


    # OBJECTIVE FUNCTION

    objective = make_objective(X, Y, S, number_talks, number_assessors, number_slots, amax, amin, record)
    prob += objective, "objective function"


    constraints = 0

    # SIZE VARIABLES

    # size variable cannot be zero if a slot is occupied
    for i in range(number_slots):
        prob += S[i] >= sum([X[(j, i)] for j in range(number_talks)]) / (number_talks + 1.0)
        constraints += 1


    # FACULTY (ASSESSOR) AVAILABILITY

    # faculty members should be scheduled only in slots for which they are available
    for key in Y:
        prob += Y[key] <= A[key]
        constraints += 1

    # faculty members can only be in one place at once, so should be scheduled only once per session
    for session in record.owner.sessions:
        for i in range(number_assessors):
            prob += sum([Y[(i, j)] for j in range(number_slots) if slot_dict[j].session_id == session.id]) <= 1
            constraints += 1

    # number of times each faculty member is scheduled should fall below the limit
    for i in range(number_assessors):
        prob += sum([Y[(i, j)] for j in range(number_slots)]) <= int(record.assessor_assigned_limit)
        constraints += 1


    # STUDENT (SUBMITTER) AVAILABILITY

    # students should be scheduled only in slots for which they are available
    for key in X:
        prob += X[key] <= B[key]
        constraints += 1


    # TALKS

    # talks should be scheduled in exactly one slot
    for i in range(number_talks):
        prob += sum([X[(i, j)] for j in range(number_slots)]) == 1
        constraints += 1

    # each slot should have the required number of assessors if the slot is occupied:
    for i in range(number_slots):
        prob += sum([Y[(j, i)] for j in range(number_assessors)]) == record.owner.number_assessors * S[i]
        constraints += 1

    # each slot should have no more than the maximum number of students:
    for i in range(number_slots):
        prob += sum([X[(j, i)] for j in range(number_talks)]) <= record.max_group_size
        constraints += 1


    # TALKS CAN ONLY BE SCHEDULED WITH OTHER TALKS OF THE SAME SUBMISSION PERIOD, BUT SHOULD NOT CLASH
    # WITH OTHER TALKS ON THE SAME PROJECT, IF THAT OPTION IS SET (ON A PROJECT-BY-PROJECT BASIS)

    for i in range(number_talks):
        for j in range(i):

            # note that we have j strictly less than i here, so i=j is excluded
            for k in range(number_slots):
                talk_i = talk_dict[i]
                talk_j = talk_dict[j]

                limit = 1
                if talk_i.owner.config_id == talk_j.owner.config_id:
                    if talk_i.project_id == talk_j.project_id:
                        if talk_i.project.dont_clash_presentations:
                            limit = 1
                        else:
                            limit = 2
                    else:
                        limit = 2

                prob += X[(i, k)] + X[(j, k)] <= limit
                constraints += 1


    # TALKS CAN ONLY BE SCHEDULED WITH ASSESSORS WHO ARE SUITABLE

    for i in range(number_talks):
        for j in range(number_assessors):
            for k in range(number_slots):
                talk = talk_dict[i]
                assessor = assessor_dict[j]

                prob += X[(i, k)] + Y[(j, k)] <= (2 if talk.project.is_assessor(assessor.id) else 1)
                constraints += 1


    # TALKS CANNOT BE SCHEDULED WITH THE SUPERVISOR AS AN ASSESSOR

    for i in range(number_talks):
        for k in range(number_slots):
            talk = talk_dict[i]
            supervisor_id = talk.supervisor.id

            # it's not an error if supervisor_id is not in assessor_to_number; this just means that the supervisor
            # is not a possible assessor.
            # that most likely way this could happen is if the supervisor is exempt/on sabbatical from
            # presentation assessments, eg. as HoD or HoS
            if supervisor_id in assessor_to_number:
                j = assessor_to_number[supervisor_id]
                prob += X[(i, k)] + Y[(j, k)] <= 1
                constraints += 1


    # TALKS SHOULD ONLY BE SCHEDULED IN ROOMS WITH REQUIRED FACILITIES

    for i in range(number_talks):
        for j in range(number_slots):
            slot_ok = True

            talk = talk_dict[i]
            slot = slot_dict[j]

            if not talk.period.has_presentation:
                raise RuntimeError('Inconsistent presentation state in SubmissionPeriodRecord')

            if talk.period.lecture_capture and not slot.room.lecture_capture:
                slot_ok = False

            # future options can be inserted here

            if not slot_ok:
                prob += X[(i, j)] == 0
                constraints += 1


    # WORKLOAD LEVELLING

    # amax and amin should bracket the workload of each faculty member
    for i in range(number_assessors):
        prob += sum([Y[(i, j)] for j in range(number_slots)]) <= amax
        prob += sum([Y[(i, j)] for j in range(number_slots)]) >= amin
        constraints += 2


    print(' -- {num} total constraints'.format(num=constraints))

    return prob, X, Y


def _store_PuLP_solution(X, Y, record, number_talks, number_assessors, number_slots,
                         talk_dict, assessor_dict, slot_dict):
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
        slot = slot_dict[i]

        # we only store slots that are scheduled
        store = False

        for j in range(number_talks):
            X[(j, i)].round()
            if pulp.value(X[(j, i)]) == 1:
                store = True
                talk = talk_dict[j]

                if talk not in slot.talks:
                    slot.talks.append(talk)

        for j in range(number_assessors):
            Y[(j, i)].round()
            if pulp.value(Y[(j, i)]) == 1:
                store = True
                assessor = assessor_dict[j]

                if assessor not in slot.assessors:
                    slot.assessors.append(assessor)

        if store:
            store_slots.append(slot)

    # slots are marked cascade='all, delete, delete-orphan', so SQLAlchemy will tidy up after us here
    record.slots = store_slots


def _create_slots(self, record):
    # add database records for each available slot (meaning a combination of session+room);
    # the ones we don't use will be cleaned up later
    for sess in record.owner.sessions:
        for room in sess.rooms:
            slot = ScheduleSlot(owner_id=record.id,
                                session_id=sess.id,
                                room_id=room.id)
            db.session.add(slot)

    try:
        db.session.commit()
    except SQLAlchemyError:
        raise self.retry()


def _initialize(self, record):
    progress_update(record.celery_id, TaskRecord.RUNNING, 5, "Collecting information...", autocommit=True)

    try:
        with Timer() as talk_timer:
            number_talks, talk_to_number, number_to_talk, talk_dict = _enumerate_talks(record.owner)
        print(' -- enumerated talks in time {s}'.format(s=talk_timer.interval))

        with Timer() as assessor_timer:
            number_assessors, assessor_to_number, number_to_assessor, assessor_dict = _enumerate_assessors(record.owner)
        print(' -- enumerated assessors in time {s}'.format(s=assessor_timer.interval))

        with Timer() as slots_timer:
            number_slots, slot_to_number, number_to_slot, slot_dict = _enumerate_slots(record)
        print(' -- enumerated slots in time {s}'.format(s=slots_timer.interval))

        # build faculty availability and 'ifneeded' cost matrix
        with Timer() as fac_avail_timer:
            A, C = _build_faculty_availability_matrix(number_assessors, assessor_dict, number_slots, slot_dict)
        print(' -- computed faculty availabilities in time {s}'.format(s=fac_avail_timer.interval))

        # build submitter availability matrix
        with Timer() as sub_avail_timer:
            B = _build_student_availability_matrix(number_talks, talk_dict, number_slots, slot_dict)
        print(' -- computed submitter availabilities in time {s}'.format(s=sub_avail_timer.interval))

    except SQLAlchemyError:
        raise self.retry()

    return number_talks, number_assessors, number_slots, \
           talk_to_number, assessor_to_number, slot_to_number, \
           number_to_talk, number_to_assessor, number_to_slot, \
           talk_dict, assessor_dict, slot_dict, A, B, C


def _execute_live(self, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots,
                  talk_dict, assessor_dict, slot_dict):
    print('Solving PuLP problem for schedule')

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...",
                    autocommit=True)

    with Timer() as solve_time:
        record.awaiting_upload = False

        if record.solver == ScheduleAttempt.SOLVER_CBC_PACKAGED:
            status = prob.solve(solvers.PULP_CBC_CMD(msg=1, maxSeconds=3600, fracGap=0.25))
        elif record.solver == ScheduleAttempt.SOLVER_CBC_CMD:
            status = prob.solve(solvers.COIN_CMD(msg=1, maxSeconds=3600, fracGap=0.25))
        elif record.solver == ScheduleAttempt.SOLVER_GLPK_CMD:
            status = prob.solve(solvers.GLPK_CMD())
        elif record.solver == ScheduleAttempt.SOLVER_CPLEX_CMD:
            status = prob.solve(solvers.CPLEX_CMD())
        elif record.solver == ScheduleAttempt.SOLVER_GUROBI_CMD:
            status = prob.solve(solvers.GUROBI_CMD())
        elif record.solver == ScheduleAttempt.SOLVER_SCIP_CMD:
            status = prob.solve(solvers.SCIP_CMD())
        else:
            status = prob.solve()

    _process_PuLP_solution(record, prob, status, solve_time, X, Y, create_time, number_talks, number_assessors,
                           number_slots, talk_dict, assessor_dict, slot_dict)


def _execute_from_solution(self, file, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots,
                           talk_dict, assessor_dict, slot_dict):
    print('Processing PuLP solution from "{name}"'.format(name=file))

    if not path.exists(file):
        progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Could not locate uploaded solution file",
                        autocommit=True)
        raise Ignore

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Processing uploaded solution file...",
                    autocommit=True)

    with Timer() as solve_time:
        record.awaiting_upload = False
        wasNone, dummyVar = prob.fixObjective()

        if record.solver == ScheduleAttempt.SOLVER_CBC_PACKAGED:
            solver = solvers.PULP_CBC_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol_LP(file, prob, prob.variables())
        elif record.solver == ScheduleAttempt.SOLVER_CBC_CMD:
            solver = solvers.COIN_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol_LP(file, prob, prob.variables())
        elif record.solver == ScheduleAttempt.SOLVER_GLPK_CMD:
            solver = solvers.GLPK_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol(file)
        elif record.solver == ScheduleAttempt.SOLVER_CPLEX_CMD:
            solver = solvers.CPLEX_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol(file)
        elif record.solver == ScheduleAttempt.SOLVER_GUROBI_CMD:
            solver = solvers.GUROBI_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol(file)
        elif record.solver == ScheduleAttempt.SOLVER_SCIP_CMD:
            solver = solvers.SCIP_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol(file)
        else:
            progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Unknown solver",
                            autocommit=True)
            raise Ignore

        if status != pulp.LpStatusInfeasible:
            prob.assignVarsVals(values)
            prob.assignVarsDj(reducedCosts)
            prob.assignConsPi(shadowPrices)
            prob.assignConsSlack(slacks)
        prob.status = status

        prob.restoreObjective(wasNone, dummyVar)
        prob.solver = solver

    _process_PuLP_solution(self, record, prob, status, solve_time, X, Y, create_time, number_talks, number_assessors,
                           number_slots, talk_dict, assessor_dict, slot_dict)


def _process_PuLP_solution(self, record, prob, status, solve_time, X, Y, create_time, number_talks, number_assessors,
                           number_slots, talk_dict, assessor_dict, slot_dict):
    state = pulp.LpStatus[status]

    if state == 'Optimal':
        record.outcome = ScheduleAttempt.OUTCOME_OPTIMAL
        record.score = pulp.value(prob.objective)

        record.construct_time = create_time.interval
        record.compute_time = solve_time.interval

        progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing PuLP solution...", autocommit=True)

        try:
            _store_PuLP_solution(X, Y, record, number_talks, number_assessors, number_slots,
                                 talk_dict, assessor_dict, slot_dict)
            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()
    elif state == 'Not Solved':
        record.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED
    elif state == 'Infeasible':
        record.outcome = ScheduleAttempt.OUTCOME_INFEASIBLE
    elif state == 'Unbounded':
        record.outcome = ScheduleAttempt.OUTCOME_UNBOUNDED
    elif state == 'Undefined':
        record.outcome = ScheduleAttempt.OUTCOME_UNDEFINED
    else:
        raise RuntimeError('Unknown PuLP outcome')

    try:
        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, 'Scheduling complete', autocommit=False)

        record.finished = True
        record.celery_finished = True
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        raise self.retry()

    return record.score


def register_scheduling_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_schedule(self, id):
        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load ScheduleAttempt record from database')
            raise self.retry()

        _create_slots(self, record)

        number_talks, number_assessors, number_slots, \
        talk_to_number, assessor_to_number, slot_to_number, \
        number_to_talk, number_to_assessor, number_to_slot, \
        talk_dict, assessor_dict, slot_dict, A, B, C = _initialize(self, record)

        progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                        autocommit=True)

        with Timer() as create_time:
            prob, X, Y = _create_PuLP_problem(A, B, record, number_talks, number_assessors, number_slots,
                                              assessor_to_number, talk_dict, assessor_dict, slot_dict,
                                              partial(_generate_minimize_objective, C))

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        return _execute_live(self, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots,
                             talk_dict, assessor_dict, slot_dict)


    @celery.task(bind=True, default_retry_delay=30)
    def recompute_schedule(self, new_id, old_id):
        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=new_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load ScheduleAttempt record from database')
            raise self.retry()

        _create_slots(self, record)

        number_talks, number_assessors, number_slots, \
        talk_to_number, assessor_to_number, slot_to_number, \
        number_to_talk, number_to_assessor, number_to_slot, \
        talk_dict, assessor_dict, slot_dict, A, B, C = _initialize(self, new_id)

        progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                        autocommit=True)

        oldX, oldY = _reconstruct_XY(self, old_id, number_talks, number_assessors, number_slots,
                                     talk_to_number, assessor_to_number, slot_dict)

        with Timer() as create_time:
            prob, X, Y = _create_PuLP_problem(A, B, record, number_talks, number_assessors, number_slots,
                                              assessor_to_number, talk_dict, assessor_dict, slot_dict,
                                              partial(_generate_reschedule_objective, oldX, oldY))

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        return _execute_live(self, record, prob, X, Y, create_time, number_talks, number_assessors, number_slots,
                             talk_dict, assessor_dict, slot_dict)


    @celery.task(bind=True, default_retry_delay=30)
    def offline_schedule(self, schedule_id, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load owning User record')
            raise Ignore

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load ScheduleAttempt record from database')
            raise self.retry()

        _create_slots(self, record)

        number_talks, number_assessors, number_slots, \
        talk_to_number, assessor_to_number, slot_to_number, \
        number_to_talk, number_to_assessor, number_to_slot, \
        talk_dict, assessor_dict, slot_dict, A, B, C = _initialize(self, record)

        progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                        autocommit=True)

        with Timer() as create_time:
            prob, X, Y = _create_PuLP_problem(A, B, record, number_talks, number_assessors, number_slots,
                                              assessor_to_number, talk_dict, assessor_dict, slot_dict,
                                              partial(_generate_minimize_objective, C))

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Writing .LP and .MPS files...",
                        autocommit=True)

        lp_name, lp_abs_path = make_generated_asset_filename('lp')
        mps_name, mps_abs_path = make_generated_asset_filename('mps')
        prob.writeLP(lp_abs_path)
        prob.writeMPS(mps_abs_path)

        AssetLifetime = 24*60*60            # time to live is 24 hours

        now = datetime.now()
        lp_asset = GeneratedAsset(timestamp=now,
                                  lifetime=AssetLifetime,
                                  filename=lp_name,
                                  mimetype=None,
                                  target_name='schedule.lp')
        lp_asset.access_control_list.append(user)

        mps_asset = GeneratedAsset(timestamp=now,
                                   lifetime=AssetLifetime,
                                   filename=mps_name,
                                   mimetype=None,
                                   target_name='schedule.MPS')
        mps_asset.access_control_list.append(user)

        try:
            db.session.add(lp_asset)
            db.session.add(mps_asset)

            record.celery_finished = True
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = Message(subject='Files for offline scheduling of {name} are now ready'.format(name=record.name),
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      recipients=[user.email])

        msg.body = render_template('email/scheduling/generated.txt', name=record.name, user=user,
                                   lp_url=url_for('admin.download_generated_asset', asset_id=lp_asset.id),
                                   mps_url=url_for('admin.download_generated_asset', asset_id=mps_asset.id))

        # register a new task in the database
        task_id = register_task(msg.subject, description='Email to {r}'.format(r=', '.join(msg.recipients)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        progress_update(record.celery_id, TaskRecord.SUCCESS, 100,
                        'File generation for offline scheduling now complete', autocommit=True)

        user.post_message('The files necessary to perform offline scheduling have been generated, and a '
                          'set of download links has been emailed to you. The files will be available '
                          'for the next 24 hours.', 'info', autocommit=True)


    @celery.task(bind=True, default_retry_delay=30)
    def process_offline_solution(self, schedule_id, asset_id, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            asset = db.session.query(UploadedAsset).filter_by(id=asset_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load owning User record')
            raise Ignore

        if asset is None:
            self.update_state(state='FAILURE', meta='Could not load UploadedAsset record')
            raise Ignore

        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load ScheduleAttempt record from database')
            raise self.retry()

        number_talks, number_assessors, number_slots, \
        talk_to_number, assessor_to_number, slot_to_number, \
        number_to_talk, number_to_assessor, number_to_slot, \
        talk_dict, assessor_dict, slot_dict, A, B, C = _initialize(self, record)

        progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                        autocommit=True)

        with Timer() as create_time:
            prob, X, Y = _create_PuLP_problem(A, B, record, number_talks, number_assessors, number_slots,
                                              assessor_to_number, talk_dict, assessor_dict, slot_dict,
                                              partial(_generate_minimize_objective, C))

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        return _execute_from_solution(self, canonical_uploaded_asset_filename(asset.filename),
                                      record, prob, X, Y, create_time, number_talks, number_assessors, number_slots,
                                      talk_dict, assessor_dict, slot_dict)
