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

from ..task_queue import progress_update

from sqlalchemy.exc import SQLAlchemyError

from celery import group, chain

import pulp
import pulp.solvers as solvers
import itertools
from datetime import datetime

from ..shared.timer import Timer


def _enumerate_talks(periods):
    # periods is a list of SubmissionPeriodRecord instances

    number = 0
    talk_to_number = {}
    number_to_talk = {}

    talk_dict = {}

    for period in periods:
        # get SubmissionRecord instances that belong to this submission period

        projects = period.submitter_list.all()

        for p in projects:
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


def register_scheduling_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_schedule(self, id):
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
            periods = record.submission_periods
            number_talks, talk_to_number, number_to_talk, talk_dict = _enumerate_talks(periods)
            number_assessors, assessor_to_number, number_to_assessor, assessor_dict = _enumerate_assessors(record)
            number_slots, slot_to_number, number_to_slot, slot_dict = _enumerate_slots(record)
        
        except SQLAlchemyError:
            raise self.retry()
        
        # progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...", autocommit=True)
        # 
        # with Timer() as create_time:
        
        # progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...", autocommit=True)
        #
        # with Timer() as solve_time:
        #     if record.solver == ScheduleAttempt.SOLVER_CBC_PACKAGED:
        #         output = prob.solve(solvers.PULP_CBC_CMD(msg=1, maxSeconds=600, fracGap=0.01))
        #     elif record.solver == ScheduleAttempt.SOLVER_CBC_CMD:
        #         output = prob.solve(solvers.COIN_CMD(msg=1, maxSeconds=600, fracGap=0.01))
        #     elif record.solver == ScheduleAttempt.SOLVER_GLPK_CMD:
        #         output = prob.solve(solvers.GLPK_CMD())
        #     else:
        #         output = prob.solve()
        #
        # state = pulp.LpStatus[output]
        #
        # if state == 'Optimal':
        #     record.outcome = ScheduleAttempt.OUTCOME_OPTIMAL
        #     record.score = pulp.value(prob.objective)
        #
        #     record.construct_time = create_time.interval
        #     record.compute_time = solve_time.interval
        #
        #     progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing PuLP solution...", autocommit=True)
        #
        #     try:
        #         _store_PuLP_solution(X, Y, record, number_sel, number_to_sel, number_lp, number_to_lp, number_mark,
        #                              number_to_mark, multiplicity, sel_dict, sup_dict, mark_dict, lp_dict,
        #                              mean_CATS_per_project)
        #         db.session.commit()
        #
        #     except SQLAlchemyError:
        #         db.session.rollback()
        #         raise self.retry()
        # elif state == 'Not Solved':
        #     record.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED
        # elif state == 'Infeasible':
        #     record.outcome = ScheduleAttempt.OUTCOME_INFEASIBLE
        # elif state == 'Unbounded':
        #     record.outcome = ScheduleAttempt.OUTCOME_UNBOUNDED
        # elif state == 'Undefined':
        #     record.outcome = ScheduleAttempt.OUTCOME_UNDEFINED
        # else:
        #     raise RuntimeError('Unknown PuLP outcome')
        #
        # try:
        #     progress_update(record.celery_id, TaskRecord.SUCCESS, 100, 'Scheduling task complete', autocommit=False)
        #
        #     record.finished = True
        #     db.session.commit()
        #
        # except SQLAlchemyError:
        #     db.session.rollback()
        #     raise self.retry()
        #
        # return record.score
