#
# Created by David Seery on 09/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from ..models import db, User, TaskRecord, BackupRecord, ProjectClassConfig, \
    Project, FacultyData, EnrollmentRecord

from ..task_queue import progress_update

from ..shared.convenor import add_liveproject

from celery import chain, group

from datetime import datetime


def register_golive_tasks(celery):

    @celery.task(bind=True, serializer='pickle')
    def pclass_golive(self, task_id, config_id, convenor_id, deadline, allow_empty):

        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to Go Live...', autocommit=True)

        # get database records for this project class
        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None or convenor is None:
            if convenor is not None:
                convenor.post_message('Go Live failed because some database records could not be loaded.', 'danger',
                                      autocommit=True)

            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')

            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            return golive_fail.apply_async(args=(task_id, convenor_id))

        year = config.year

        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED:
            convenor.post_message('Cannot yet Go Live for {name} {yra}-{yrb} '
                                  'because confirmation requests have not been '
                                  'issued.'.format(name=config.name, yra=year, yrb=year + 1),
                                  'warning', autocommit=True)
            self.update_state('FAILURE', meta='Confirmation requests have not been issued')
            return golive_fail.apply_async(args=(task_id, convenor_id))

        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
            convenor.post_message('Cannot yet Go Live for {name} {yra}-{yrb} '
                                  'because not all confirmation reponses have not been '
                                  'received. If needed, use Force Confirm to remove any blocking '
                                  'responses.'.format(name=config.name, yra=year, yrb=year + 1),
                                  'warning', autocommit=True)
            self.update_state('FAILURE', meta='Some Go Live confirmations are still outstanding')
            return golive_fail.apply_async(args=(task_id, convenor_id))

        pclass_id = config.pclass_id

        # build list of projects to be attached when we go live
        # note that we exclude any projects where the supervisor is not normally enrolled
        attached_projects = db.session.query(Project) \
            .filter(Project.active,
                    Project.project_classes.any(id=pclass_id)) \
            .join(User, User.id == Project.owner_id) \
            .join(FacultyData, FacultyData.id == Project.owner_id) \
            .join(EnrollmentRecord,
                  and_(EnrollmentRecord.pclass_id == pclass_id, EnrollmentRecord.owner_id == Project.owner_id)) \
            .filter(User.active) \
            .filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED) \
            .order_by(User.last_name, User.first_name).all()

        # weed out projects that do not satisfy is_offerable
        for proj in attached_projects:
            if not proj.is_offerable:
                attached_projects.remove(proj)

        if len(attached_projects) == 0 and not allow_empty:
            convenor.post_message('Cannot yet Go Live for {name} {yra}-{yrb} '
                                  'because there would be no attached projects. If this is not what you expect, '
                                  'check active flags and sabbatical/exemption status for all enrolled faculty.'
                                  ''.format(name=config.name, yra=year, yrb=year+1),
                                  'error', autocommit=True)
            self.update_state('FAILURE', meta='No attached projects')
            return golive_fail.apply_async(args=(task_id, convenor_id))

        # build group of parallel tasks to automatically take attached projects live
        projects_group = group(project_golive.si(n + 1, p.id, config_id) for n, p in enumerate(attached_projects))

        # get backup task from Celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(golive_initialize.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_GOLIVE_FALLBACK, tag='golive',
                              description='Rollback snapshot for '
                                          '{proj} Go Live {yr}'.format(proj=config.name, yr=year)),
                    projects_group,
                    golive_finalize.si(task_id, config_id, convenor_id, deadline)).on_error(golive_fail.si(task_id, convenor_id))

        seq.apply_async()


    @celery.task()
    def golive_initialize(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building Go Live snapshot...', autocommit=True)


    @celery.task(bind=True, serializer='pickle')
    def golive_finalize(self, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Go Live complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is not None:
            config.live = True
            config.live_deadline = deadline
            config.golive_id = convenor_id
            config.golive_timestamp = datetime.now()

        if convenor is not None:
            # send direct message to user announcing successful Go Live event
            convenor.post_message('Go Live "{proj}" '
                                  'for {yra}-{yrb} is now complete'.format(proj=config.name,
                                                                           yra=config.year,
                                                                           yrb=config.year+1),
                                  'success', autocommit=False)
            convenor.send_replacetext('live-project-count', '{c}'.format(c=config.live_projects.count()), autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def golive_fail(self, task_id, convenor_id):

        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error during Go Live', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            convenor.post_message('Go Live failed. Please contact a system administrator', 'error',
                                  autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def project_golive(self, number, pid, config_id):
        try:
            add_liveproject(number, pid, config_id, autocommit=True)
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()
        except KeyError as e:
            db.session.rollback()
            self.update_state(state='FAILURE', meta='Database error: {msg}'.format(msg=str(e)))


    @celery.task(bind=True)
    def golive_close(self, config_id, convenor_id):
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
            convenor.post_message('Student selections for "{name}" {yeara}-{yearb} have now been'
                                  ' closed'.format(name=config.name, yeara=config.year,
                                                   yearb=config.year+1), 'success')

        db.session.commit()
