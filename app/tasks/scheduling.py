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
from ..models import TaskRecord, ScheduleAttempt, SubmissionPeriodRecord, SubmissionRecord

from ..shared.sqlalchemy import get_count
from ..task_queue import progress_update

from sqlalchemy.exc import SQLAlchemyError

from celery import group, chain
from celery.exceptions import Ignore

import pulp
import pulp.solvers as solvers
import itertools
from datetime import datetime

from ..shared.timer import Timer


def _enumerate_talks(assessment):
    # periods is a list of SubmissionPeriodRecord instances

    number = 0
    talk_to_number = {}
    number_to_talk = {}

    talk_dict = {}

    for p in assessment.available_talks:
        if not assessment.not_attending(p.id):
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

    for assessor in record.assessors:
        assessor_to_number[assessor.id] = number
        number_to_assessor[number] = assessor.id

        assessor_dict[number] = assessor

        number += 1

    return number, assessor_to_number, number_to_assessor, assessor_dict


def _enumerate_slots(record):
    # record is a ScheduleAttempt instance

    number = 0
    slot_to_number = {}
    number_to_slot = {}

    slot_dict = {}

    for slot in record.slots:
        slot_to_number[slot.id] = number
        number_to_slot[number] = slot.id

        slot_dict[number] = slot

        number += 1

    return number, slot_to_number, number_to_slot, slot_dict


def _build_availability_matrix(number_assessors, assessor_dict, number_slots, slot_dict):
    """
    Construct a dictionary mapping from (assessing-faculty, slot) pairs to availabilities,
    coded as 0 = not available, 1 = available
    :param number_assessors:
    :param assessor_dict:
    :param number_slots:
    :param slot_dict:
    :return:
    """
    A = {}

    for i in range(number_assessors):
        assessor = assessor_dict[i]

        for j in range(number_slots):
            idx = (i, j)
            slot = slot_dict[j]

            # is this assessor available in this slot?
            count = get_count(slot.session.faculty.filter_by(id=assessor.id))

            if count == 1:
                A[idx] = 1
            elif count == 0:
                A[idx] = 0
            else:
                raise RuntimeError('Inconsistent availability for faculty member: '
                                   'fac={fname}, slot={slotid}, '
                                   'session={sessid}'.format(fname=assessor.user.name, slotid=slot.id,
                                                             sessid=slot.session.id))

    return A


def _generate_minimize_objective(X, Y, S, number_talks, number_assessors, number_slots):
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

    # TODO: - workload balancing: share load evenly between faculty if possible
    # TODO: - minimize number of days used in schedule
    # TODO: - minimize number of rooms used in schedule
    # TODO: - prevent talks on same subject being scheduled in same session, if possible

    return objective


def _generate_reschedule_objective(X, Y, S, number_talks, number_assessors, number_slots, Xold, Yold):
    """
    Generate an objective function that tries to produce a feasible schedule matching Xold, Yold
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

    # ask optimizer to choose X and Y values that match Xold, Yold as closely as possible.
    # recall that we solve a *minimization* problem, so the objective function should
    # count the number of *differences*

    for i in range(number_talks):
        for j in range(number_slots):
            idx = (i,j)
            if Xold[idx] == 0:
                objective += X[idx]
            else:
                objective += 1 - X[idx]

    for i in range(number_assessors):
        for j in range(number_slots):
            idx = (i,j)
            if Yold[idx] == 0:
                objective += Y[idx]
            else:
                objective += 1 - Y[idx]

    return objective


def _create_PuLP_problem(A, record, number_talks, number_assessors, number_slots,
                         assessor_to_number,
                         talk_dict, assessor_dict, slot_dict,
                         make_objective):
    """
    Generate a PuLP problem to find an optimal assignment of student talks + faculty assessors to rooms
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
    # the entries of this matrix are either 0 or 1
    X = pulp.LpVariable.dicts("x", itertools.product(range(number_talks), range(number_slots)), cat=pulp.LpBinary)

    # generate assessor-to-slot assignment matrix
    Y = pulp.LpVariable.dicts("y", itertools.product(range(number_assessors), range(number_slots)), cat=pulp.LpBinary)

    # generate a 'size counting' variable for each slot
    S = pulp.LpVariable.dicts("s", range(number_slots), cat=pulp.LpBinary)


    # OBJECTIVE FUNCTION

    objective = make_objective(X, Y, S, number_talks, number_assessors, number_slots)
    prob += objective, "objective function"


    # SIZE VARIABLES

    # size variable cannot be zero if a slot is occupied
    for i in range(number_slots):
        prob += S[i] >= sum([X[(j, i)] for j in range(number_talks)]) / (number_talks + 1.0)


    # FACULTY AVAILABILITY

    # faculty members should be scheduled only in slots for which they are available
    for key in Y:
        prob += Y[key] <= A[key]

    # faculty members can only be in one place at once, so should be scheduled only once per room per slot
    for session in record.owner.sessions:
        for i in range(number_assessors):
            prob += sum([Y[(i, j)] for j in range(number_slots) if slot_dict[j].session_id == session.id]) <= 1


    # TALKS

    # talks should be scheduled in exactly one slot
    for i in range(number_talks):
        prob += sum([X[(i, j)] for j in range(number_slots)]) == 1

    # each slot should have the required number of assessors if the slot is occupied:
    for i in range(number_slots):
        prob += sum([Y[(j, i)] for j in range(number_assessors)]) == record.owner.number_assessors * S[i]

    # each slot should have no more than the maximum number of students:
    for i in range(number_slots):
        prob += sum([X[(j, i)] for j in range(number_talks)]) <= record.max_group_size


    # TALKS CAN ONLY BE SCHEDULED WITH OTHER TALKS OF THE SAME SELECTING PERIOD

    for i in range(number_talks):
        for j in range(i):
            for k in range(number_slots):
                talk_i = talk_dict[i]
                talk_j = talk_dict[j]
                prob += X[(i, k)] + X[(j, k)] <= (2 if talk_i.owner.config_id == talk_j.owner.config_id else 1)


    # TALKS CAN ONLY BE SCHEDULED WITH ASSESSORS WHO ARE SUITABLE

    for i in range(number_talks):
        for j in range(number_assessors):
            for k in range(number_slots):
                talk = talk_dict[i]
                assessor = assessor_dict[j]
                count = get_count(talk.project.assessors.filter_by(id=assessor.id))
                prob += X[(i, k)] + Y[(j, k)] <= (2 if count == 1 else 1)


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


def compute_schedule(self, id, objective_generator):
    self.update_state(state='STARTED', meta='Looking up ScheduleAttempt record for id={id}'.format(id=id))

    try:
        record = db.session.query(ScheduleAttempt).filter_by(id=id).first()
    except SQLAlchemyError:
        raise self.retry()

    if record is None:
        self.update_state('FAILURE', meta='Could not load ScheduleAttempt record from database')
        return

    progress_update(record.celery_id, TaskRecord.RUNNING, 5, "Collecting information...", autocommit=True)

    try:
        number_talks, talk_to_number, number_to_talk, talk_dict = _enumerate_talks(record.owner)
        number_assessors, assessor_to_number, number_to_assessor, assessor_dict = _enumerate_assessors(record.owner)
        number_slots, slot_to_number, number_to_slot, slot_dict = _enumerate_slots(record)

        # build faculty availability matrix
        A = _build_availability_matrix(number_assessors, assessor_dict, number_slots, slot_dict)

    except SQLAlchemyError:
        raise self.retry()

    progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                    autocommit=True)

    with Timer() as create_time:
        prob, X, Y = _create_PuLP_problem(A, record, number_talks, number_assessors, number_slots,
                                          assessor_to_number,
                                          talk_dict, assessor_dict, slot_dict,
                                          objective_generator)

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...",
                    autocommit=True)

    with Timer() as solve_time:
        if record.solver == ScheduleAttempt.SOLVER_CBC_PACKAGED:
            output = prob.solve(solvers.PULP_CBC_CMD(msg=1, maxSeconds=600, fracGap=0.01))
        elif record.solver == ScheduleAttempt.SOLVER_CBC_CMD:
            output = prob.solve(solvers.COIN_CMD(msg=1, maxSeconds=600, fracGap=0.01))
        elif record.solver == ScheduleAttempt.SOLVER_GLPK_CMD:
            output = prob.solve(solvers.GLPK_CMD())
        else:
            output = prob.solve()

    state = pulp.LpStatus[output]

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
        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, 'Scheduling task complete', autocommit=False)

        record.finished = True
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        raise self.retry()

    return record.score


def register_scheduling_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_schedule(self, id):
        return compute_schedule(self, id, _generate_minimize_objective)
