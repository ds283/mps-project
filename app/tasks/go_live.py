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
from sqlalchemy.exc import SQLAlchemyError

from ..models import db, User, TaskRecord, BackupRecord, ProjectClass, ProjectClassConfig, \
    Project, LiveProject

from ..task_queue import progress_update

from ..shared.utils import get_current_year
from ..shared.convenor import add_liveproject

from celery import chain, group

from datetime import datetime


def register_golive_tasks(celery):

    @celery.task(bind=True, serializer='pickle')
    def pclass_golive(self, task_id, pclass_id, current_id, convenor_id, deadline):

        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to Go Live...', autocommit=True)

        # get database records for this project class
        try:
            pcl = ProjectClass.query.filter_by(id=pclass_id).first()
            current_config = ProjectClassConfig.query.filter_by(id=current_id).first()
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if pcl is None or current_config is None or convenor is None:
            convenor.post_message('Go Live failed. Please contact a system administrator', 'danger',
                                  autocommit=True)
            self.update_state('FAILURE', meta='Could not load ProjectClass, ProjectClassConfig or User record from database')
            return

        year = get_current_year()

        if current_config.golive_required.first() is not None:
            convenor.post_message('Cannot yet Go Live for {name} {yra}-{yrb} '
                                  'because some confirmation requests are outstanding. '
                                  'If needed, force all confirmations and try again.'.format(name=pcl.name,
                                                                                             yra=year, yrb=year+1))
            self.update_state('FAILURE', meta='Some Go Live confirmations were still outstanding')
            return

        attached_projects = \
            db.session.query(Project.id).filter(Project.active,
                                                Project.project_classes.any(id=pclass_id)).join(
                User, User.id == Project.owner_id).order_by(User.last_name, User.first_name).all()

        if len(attached_projects) == 0:
            convenor.post_message('Cannot yet Go Live for {name} {yra}-{yrb} '
                                  'because there are no attached projects'.format(name=pcl.name, yra=year, yrb=year+1))
            self.update_state('FAILURE', meta='No attached projects')

        # build group of tasks to automatically take attached projects live
        projects_group = group(project_golive.si(n, p.id, current_id) for n, p in enumerate(attached_projects))

        # get backup task from Celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(golive_initialize.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_GOLIVE_FALLBACK, tag='golive',
                              description='Rollback snapshot for {proj} Go Live {yr}'.format(proj=pcl.name, yr=year)),
                    projects_group,
                    golive_finalize.si(task_id, current_id, convenor_id, deadline)).on_error(golive_fail.si(task_id, convenor_id))

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

        commit = False

        if config is not None:
            config.live = True
            config.live_deadline = deadline
            config.golive_id = convenor_id
            config.golive_timestamp = datetime.now()

            commit = True

        if convenor is not None:
            # send direct message to user announcing successful rollover
            convenor.post_message('Go Live "{proj}" for {yra}-{yrb} is now complete'.format(
                proj=config.project_class.name, yra=config.year, yrb=config.year+1), 'success', autocommit=False)
            convenor.send_replacetext('live-project-count', '{c}'.format(c=config.live_projects.count()))

            commit = True

        if commit:
            db.session.commit()


    @celery.task(bind=True)
    def golive_fail(self, task_id, convenor_id):

        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error during Go Live', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            convenor.post_message('Go Live failed. Please contact a system administrator', 'danger',
                                  autocommit=True)


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
