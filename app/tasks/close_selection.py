#
# Created by David Seery on 30/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..models import db, TaskRecord, ProjectClassConfig, User, BackupRecord, SelectingStudent, \
    SelectionRecord

from ..task_queue import progress_update

from celery import chain, group

from datetime import datetime


def register_close_selection_tasks(celery):

    @celery.task(bind=True)
    def pclass_close(self, task_id, config_id, convenor_id):

        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to close...', autocommit=True)

        # get database records for this project class
        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None or convenor is None:
            if convenor is not None:
                convenor.post_message('Close selection failed. Please contact a system administrator', 'error',
                                      autocommit=True)

            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')
            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            return close_fail.apply_async(args=(task_id, convenor_id))

        year = config.year

        # build group of parallel tasks to perform maintenance on each SelectingStudent
        selectors_group = group(selector_close.si(sel.id) for sel in config.selecting_students)

        # get backup task from Celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(close_initialize.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_CLOSE_FALLBACK, tag='close',
                              description='Rollback snapshot for '
                                          '{proj} close {yr}'.format(proj=config.project_class.name, yr=year)),
                    selectors_group,
                    close_finalize.si(task_id, config_id, convenor_id)).on_error(close_fail.si(task_id, convenor_id))

        seq.apply_async()


    @celery.task()
    def close_initialize(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building closure snapshot...', autocommit=True)


    @celery.task(bind=True)
    def close_finalize(self, task_id, config_id, convenor_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Closure of selection complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is not None:
            config.selection_closed = True
            config.closed_id = convenor_id
            config.closed_timestamp = datetime.now()

        if convenor is not None:
            # send direct message to user announcing successful
            convenor.post_message('Closure of selection '
                                  'for "{proj}" {yra}-{yrb} is now complete'.format(proj=config.project_class.name,
                                                                                    yra=config.year,
                                                                                    yrb=config.year+1),
                                  'success', autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def close_fail(self, task_id, convenor_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error while closing selections', autocommit=True)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            convenor.post_message('Close selection failed. Please contact a system administrator', 'error',
                                  autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def selector_close(self, sel_id):
        try:
            sel = db.session.query(SelectingStudent).filter_by(id=sel_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if sel.has_submitted:
            return sanitize(sel)

        if sel.has_bookmarks:
            return convert_bookmarks(sel)


def convert_bookmarks(sel):
    for item in sel.ordered_bookmarks:
        data = SelectionRecord(owner_id=item.owner_id,
                               liveproject_id=item.liveproject_id,
                               rank=item.rank,
                               converted_from_bookmark=True,
                               hint=SelectionRecord.SELECTION_HINT_NEUTRAL)
        db.session.add(data)

    sel.submission_time = datetime.now()

    db.session.commit()


def sanitize(sel):
    for item in sel.ordered_selection:
        if item.converted_from_bookmark is None:
            item.converted_from_bookmark = False
        if item.hint != SelectionRecord.SELECTION_HINT_NEUTRAL:
            item.hint = SelectionRecord.SELECTION_HINT_NEUTRAL

    db.session.commit()
