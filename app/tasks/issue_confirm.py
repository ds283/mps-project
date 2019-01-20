#
# Created by David Seery on 2019-01-20.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord, BackupRecord, ProjectClassConfig, \
    Project, FacultyData, EnrollmentRecord

from ..task_queue import progress_update

from celery import chain, group

from datetime import datetime


def register_issue_confirm_tasks(celery):

    @celery.task(bind=True, serializer='pickle')
    def pclass_issue(self, task_id, config_id, convenor_id, deadline):

        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to issue confirmation requests...', autocommit=True)

        # get database records for this project class
        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None or convenor is None:
            if convenor is not None:
                convenor.post_message('Issuing confirmation requests failed because some database records '
                                      'could not be loaded.', 'danger', autocommit=True)

            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')

            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            return issue_fail.apply_async(args=(task_id, convenor_id))

        year = config.year

        if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED:
            convenor.post_message('Confirmation requests for {name} {yra}-{yrb} '
                                  'have already been issued.'.format(name=config.name, yra=year, yrb=year + 1),
                                  'warning', autocommit=True)
            self.update_state('FAILURE', meta='Confirmation requests have not been issued')
            return issue_fail.apply_async(args=(task_id, convenor_id))

        config.golive_required = []
        confirmations_needed = set()

        # issue confirmation requests if this project is set up to require them
        if config.require_confirm:
            # select faculty that are enrolled on this particular project class
            eq = db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id) \
                .filter_by(pclass_id=config.pclass_id).subquery()
            fd = db.session.query(eq.c.owner_id, User, FacultyData) \
                .join(User, User.id == eq.c.owner_id) \
                .join(FacultyData, FacultyData.id == eq.c.owner_id) \
                .filter(User.active == True)

            for id, user, data in fd:
                if data.id not in confirmations_needed:
                    confirmations_needed.add(data.id)

            issue_group = group(issue_confirm.si(d, config_id) for d in confirmations_needed)

            # get backup task from celery instance
            celery = current_app.extensions['celery']
            backup = celery.tasks['app.tasks.backup.backup']

            seq = chain(issue_initialize.si(task_id),
                        backup.si(convenor_id, type=BackupRecord.PROJECT_ISSUE_CONFIRM_FALLBACK, tag='issue_confirm',
                                  description='Rollback snapshot for issuing confirmation requests for '
                                              '{proj} confirmations {yr}'.format(proj=config.name, yr=year)),
                        issue_group,
                        issue_finalize.si(task_id, config_id, convenor_id, deadline)).on_error(issue_fail.si(task_id, convenor_id))

            seq.apply_async()


    @celery.task()
    def issue_initialize(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building rollback confirmation requests snapshot...', autocommit=True)


    @celery.task(bind=True, serializer='pickle')
    def issue_finalize(self, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Issue confirmation requests complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is not None:
            config.requests_issued = True
            config.request_deadline = deadline
            config.requests_issued_id = convenor_id
            config.requests_timestamp = datetime.now()

        if convenor is not None:
            # send direct message to user announcing successful Go Live event
            convenor.post_message('Issue confirmation requests for "{proj}" '
                                  'for {yra}-{yrb} is now complete'.format(proj=config.name,
                                                                           yra=config.year,
                                                                           yrb=config.year+1),
                                  'success', autocommit=False)

            requests = config.golive_required.count()
            plural = 's'
            if requests == 0:
                plural = ''

            convenor.post_message('{n} confirmation request{plural} issued'.format(n=requests, plural=plural), 'info',
                                  autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def issue_fail(self, task_id, convenor_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error when issuing confirmation requests', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            convenor.post_message('Issuing confirmation requests failed. Please contact a system administrator', 'error',
                                  autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def issue_confirm(self, faculty_id, config_id):
        try:
            data = FacultyData.query.filter_by(id=faculty_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if data not in config.golive_required:      # don't object if we are generating a duplicate request
            try:
                config.golive_required.append(data)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()
