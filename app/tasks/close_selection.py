#
# Created by David Seery on 30/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template
from flask_mail import Message

from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import TaskRecord, ProjectClassConfig, User, BackupRecord, SelectingStudent, \
    SelectionRecord

from ..task_queue import progress_update, register_task

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
            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')
            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            print('config: {x}'.format(x=config))
            print('convenor: {x}').format(x=convenor)
            return close_fail.apply_async(args=(task_id, convenor_id))

        if not config.project_class.publish:
            return None

        year = config.year

        # build group of parallel tasks to perform maintenance on each SelectingStudent
        selectors_group = group(selector_close.si(sel.id) for sel in config.selecting_students)

        # get backup task from Celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(close_initialize.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_CLOSE_FALLBACK, tag='close',
                              description='Rollback snapshot for '
                                          '{proj} close {yr}'.format(proj=config.name, yr=year)))

        if len(selectors_group) > 0:
            seq = seq | selectors_group

        seq = (seq | close_finalize.si(task_id, config_id, convenor_id)).on_error(close_fail.si(task_id, convenor_id))

        raise self.replace(seq)


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
            # send direct message to user announcing that we have been successful
            convenor.post_message('Closure of selections for "{proj}" {yra}-{yrb} is now '
                                  'complete'.format(proj=config.name, yra=config.year, yrb=config.year+1),
                                  'success', autocommit=False)

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        if config is not None:
            recipients = set([config.project_class.convenor.user.email])
            if convenor is not None:
                recipients.add(convenor.email)

            for coconvenor in config.project_class.coconvenors:
                recipients.add(coconvenor.user.email)

            for user in config.project_class.office_contacts:
                recipients.add(user.email)

            msg = Message(subject='[mpsprojects] "{name}": student selections now '
                                  'closed'.format(name=config.project_class.name),
                          sender=current_app.config['MAIL_DEFAULT_SENDER'],
                          reply_to=current_app.config['MAIL_REPLY_TO'],
                          recipients=list(recipients))

            data = config.selector_data
            msg.body = render_template('email/close_selection/convenor.txt', pclass=config.project_class, config=config,
                                       data=data)

            # register a new task in the database
            task_id = register_task(msg.subject, description='Send convenor email notification')

            send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
            send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


    @celery.task(bind=True)
    def close_fail(self, task_id, convenor_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error while closing selections', autocommit=True)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            convenor.post_message('Close selections failed. Please contact a system administrator', 'error',
                                  autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def selector_close(self, sel_id):
        try:
            sel = db.session.query(SelectingStudent).filter_by(id=sel_id).first()
        except SQLAlchemyError:
            raise self.retry()

        # if a submission already exists, sanitize it (check that all flags are correct)
        if sel.has_submitted:
            sanitize(sel)
            return

        # if a submission does not exist, and this is not a 'submit to subscribe' type of project
        # (tagged by 'selection_open_to_all'), then convert bookmarks into a submission
        # provided they exist and are a valid selection. Otherwise treat as a non-submission.
        if not sel.config.selection_open_to_all and sel.is_valid_selection:
            convert_bookmarks(sel)
            return


def convert_bookmarks(sel):
    for item in sel.ordered_bookmarks.limit(sel.number_choices):
        data = SelectionRecord(owner_id=item.owner_id,
                               liveproject_id=item.liveproject_id,
                               rank=item.rank,
                               converted_from_bookmark=True,
                               hint=SelectionRecord.SELECTION_HINT_NEUTRAL)
        db.session.add(data)

    sel.submission_time = datetime.now()
    sel.submission_IP = None

    # allow exceptions to propagate up to calling function
    db.session.commit()


def sanitize(sel):
    for item in sel.ordered_selections:
        if item.converted_from_bookmark is None:
            item.converted_from_bookmark = False

        if item.hint != SelectionRecord.SELECTION_HINT_NEUTRAL:
            item.hint = SelectionRecord.SELECTION_HINT_NEUTRAL

    # allow exceptions to propagate up to calling function
    db.session.commit()
