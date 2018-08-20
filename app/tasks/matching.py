#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..models import db, MatchingAttempt, TaskRecord, ProjectClass, ProjectClassConfig, LiveProject, SelectingStudent

from ..shared.utils import get_current_year
from ..task_queue import progress_update

from celery import chain, group

from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime, timedelta
import itertools


def find_pclasses():
    """
    Build a list of pclasses that participate in automatic matching
    :return:
    """

    pclasses = db.session.query(ProjectClass).filter_by(active=True, do_matching=True).all()

    return pclasses


def enumerate_selectors(pclasses):
    """
    Build a list of SelectingStudents who belong to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0
    :param pclasses:
    :return:
    """

    current_year = get_current_year()

    number = 0
    sel_to_number = {}
    number_to_sel = {}

    for pclass in pclasses:
        # get current ProjectClassConfig for the current year
        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=pclass.id, year=current_year).first()

        if config is None:
            raise RuntimeError(
                'Configuration record for "{name}" and year={yr} is missing'.format(name=pclass.name, yr=current_year))

        # get SelectingStudent instances that are not retired and belong to this config instance
        selectors = db.session.query(SelectingStudent) \
            .filter_by(retired=False, config_id=config.id).all()

        for item in selectors:
            sel_to_number[item.id] = number
            number_to_sel[number] = item.id

            number += 1

    return number, sel_to_number, number_to_sel


def enumerate_liveprojects(pclasses):
    """
    Build a list of LiveProjects belonging to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0
    :param pclasses: 
    :return: 
    """

    current_year = get_current_year()

    number = 0
    lp_to_number = {}
    number_to_lp = {}

    for pclass in pclasses:
        # get current ProjectClassConfig for the current year

        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=pclass.id, year=current_year).first()

        if config is None:
            raise RuntimeError(
                'Configuration record for "{name}" and year={yr} is missing'.format(name=pclass.name, yr=current_year))

        # get LiveProject instances that belong to this config instance
        projects = db.session.query(LiveProject) \
            .filter_by(config_id=config.id).all()

        for item in projects:
            lp_to_number[item.id] = number
            number_to_lp[number] = item.id

            number += 1

    return number, lp_to_number, number_to_lp


def register_matching_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_match(self, id):

        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            return

        progress_update(record.celery_id, TaskRecord.RUNNING, 5, "Collecting information...", autocommit=True)

        try:
            pclasses = find_pclasses()
            number_sel, sel_to_number, number_to_sel = enumerate_selectors(pclasses)
            number_lp, lp_to_number, number_to_lp = enumerate_liveprojects(pclasses)

        except SQLAlchemyError:
            raise self.retry()

        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, 'Matching task complete', autocommit=False)

        record.finished = True
        record.success = True
        db.session.commit()
