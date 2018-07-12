#
# Created by David Seery on 08/06/2018.
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
    SelectingStudent, SubmittingStudent, StudentData

from ..task_queue import progress_update

from ..shared.utils import get_current_year

from ..shared.convenor import add_selector, add_submitter

from celery import chain, group

from datetime import datetime


def register_rollover_tasks(celery):

    @celery.task(bind=True)
    def pclass_rollover(self, task_id, pclass_id, current_id, convenor_id):

        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to rollover...', autocommit=True)

        # get new academic year
        year = get_current_year()

        # get database records for this project class
        try:
            pcl = ProjectClass.query.filter_by(id=pclass_id).first()
            current_config = ProjectClassConfig.query.filter_by(id=current_id).first()
        except SQLAlchemyError:
            raise self.retry()

        # build group of tasks to perform retirements
        retire_selectors = [retire_selector.si(s.id) for s in current_config.selecting_students]
        retire_submitters = [retire_submitter.si(s.id) for s in current_config.submitting_students]

        retire_group = group(retire_selectors+retire_submitters)

        # build group of tasks to perform attachment of new records
        # each task in the group gets the id of the new ProjectClassConfig record because Celery
        # forwards the result of the build_new_pclass_config() task
        attach_group = group(attach_records.s(s.id, year, pclass_id) for s in StudentData.query.all())

        # get backup task from Celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(rollover_initialize.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_ROLLOVER_FALLBACK, tag='rollover',
                              description='Rollback snapshot for {proj} rollover to {yr}'.format(proj=pcl.name, yr=year)),
                    rollover_retire.si(task_id),
                    retire_group,
                    build_new_pclass_config.si(task_id, pclass_id, convenor_id, current_id),
                    attach_group,
                    rollover_finalize.si(task_id, convenor_id)).on_error(rollover_fail.si(task_id, convenor_id))

        seq.apply_async()


    @celery.task()
    def rollover_initialize(task_id):

        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building rollback snapshot...', autocommit=True)


    @celery.task(bind=True)
    def rollover_finalize(self, task_id, convenor_id):

        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Rollover complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            # ask web page to dynamically hide the rollover panel
            convenor.send_showhide('rollover-panel', 'hide', autocommit=False)
            # send direct message to user announcing successful rollover
            convenor.post_message('Rollover of academic year is now complete', 'success', autocommit=True)


    @celery.task(bind=True)
    def rollover_fail(self, task_id, convenor_id):

        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error during rollover', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            convenor.post_message('Rollover of academic year failed. Please contact a system administrator', 'danger',
                                  autocommit=True)


    @celery.task()
    def rollover_retire(task_id):

        progress_update(task_id, TaskRecord.SUCCESS, 35, 'Retiring current student records...', autocommit=True)


    @celery.task(bind=True)
    def retire_selector(self, sid):

        # get current configuration record
        try:
            item = SelectingStudent.query.filter_by(id=sid).first()
        except SQLAlchemyError:
            raise self.retry()

        if item is not None:
            item.retired = True

            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()

            self.update_state(state='SUCCESS')

        self.update_state(state='FAILED', meta='Could not not SelectingStudent record for sid={id}'.format(id=sid))


    @celery.task(bind=True)
    def retire_submitter(self, sid):

        # get current configuration record
        try:
            item = SubmittingStudent.query.filter_by(id=sid).first()
        except SQLAlchemyError:
            raise self.retry()

        if item is not None:
            item.retired = True

            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()

            self.update_state(state='SUCCESS')

        self.update_state(state='FAILED', meta='Could not not SubmittingStudent record for sid={id}'.format(id=sid))


    @celery.task(bind=True)
    def build_new_pclass_config(self, task_id, pclass_id, convenor_id, current_id):

        progress_update(task_id, TaskRecord.RUNNING, 55, 'Generating new live master record...', autocommit=True)

        # get new, rolled-over academic year
        current_year = get_current_year()

        # get current configuration record; makes this task idempotent, so it's safe to run twice or more
        try:
            current_config = ProjectClassConfig.query.filter_by(id=current_id).first()
        except SQLAlchemyError:
            raise self.retry()

        # check whether a new configuration record needs to be inserted;
        # we expect so, but if we are retrying and there is for some reason
        # an already-inserted record then we just want to be idempotent
        if current_config.year == current_year:

            progress_update(task_id, TaskRecord.RUNNING, 75, 'Attaching new student records...', autocommit=True)
            return current_config.id

        # generate a new ProjectClassConfig for this year
        new_config = ProjectClassConfig(year=current_year,
                                        pclass_id=pclass_id,
                                        convenor_id=convenor_id,
                                        creator_id=convenor_id,
                                        creation_timestamp=datetime.now(),
                                        requests_issued=False,
                                        request_deadline=None,
                                        live=False,
                                        live_deadline=None,
                                        closed=False,
                                        CATS_supervision=current_config.project_class.CATS_supervision,
                                        CATS_marking=current_config.project_class.CATS_marking,
                                        submission_period=1)

        try:
            db.session.add(new_config)
            db.session.flush()

            new_config_id = new_config.id

            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        progress_update(task_id, TaskRecord.RUNNING, 75, 'Attaching new student records...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def attach_records(self, new_config_id, sid, current_year, pclass_id):

        # get current configuration record; makes this task idempotent, so it's safe to run twice or more
        try:
            pclass = ProjectClass.query.filter_by(id=pclass_id).first()
            student = StudentData.query.filter_by(id=sid).first()
        except SQLAlchemyError:
            raise self.retry()

        if pclass is None or student is None:
            self.update_state('FAILURE', meta='Could not load database records while attaching student records')
            return

        academic_year = current_year - student.cohort + 1

        if pclass.year - 1 <= academic_year < pclass.year + pclass.extent - 1 \
                and (pclass.selection_open_to_all or student.programme in pclass.programmes):

            # will be a selecting student
            add_selector(student, new_config_id, autocommit=False)

        if pclass.year <= academic_year < pclass.year + pclass.extent \
                and student.programme in pclass.programmes:

            # will be a submitting student
            add_submitter(student, new_config_id, autocommit=False)

        db.session.commit()
