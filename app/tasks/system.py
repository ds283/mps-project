#
# Created by David Seery on 2018-12-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from celery import chain, group
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord, Notification, MatchingAttempt, ScheduleAttempt, StudentBatch


def register_system_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def reset_tasks(self, user_id):
        try:
            in_progress_matching = db.session.query(MatchingAttempt.id).filter_by(celery_finished=False).all()
            in_progress_scheduling = db.session.query(ScheduleAttempt.id).filter_by(celery_finished=False).all()
            in_progress_batches = db.session.query(StudentBatch.id).filter_by(celery_finished=False).all()
        except SQLAlchemyError:
            raise self.retry()

        task = chain(group(reset_background_tasks.si(), reset_notifications.si()),
                     group(reset_matching.si(ident[0]) for ident in in_progress_matching),
                     group(reset_scheduling.si(ident[0]) for ident in in_progress_scheduling),
                     group(reset_batch.si(ident[0]) for ident in in_progress_batches),
                     reset_tasks_notify.si(user_id)).on_error(reset_tasks_fail.si(user_id))

        raise self.replace(task)


    @celery.task(bind=True, default_retry_delay=30)
    def reset_background_tasks(self):
        # reset all background tasks
        try:
            db.session.query(TaskRecord).delete()
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_notifications(self):
        # reset all notification records
        try:
            db.session.query(Notification).delete()
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_matching(self, ident):
        try:
            record = db.session.query(MatchingAttempt).filter_by(id=ident).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        record.finished = True
        record.celery_finished = True
        record.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED

        try:
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_scheduling(self, ident):
        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=ident).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        record.finished = True
        record.celery_finished = True
        record.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED

        try:
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_batch(self, ident):
        try:
            record = db.session.query(StudentBatch).filter_by(id=ident).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        record.celery_finished = True
        record.success = False

        try:
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=5)
    def reset_tasks_notify(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        try:
            user.post_message('All background tasks have been reset successfully.', 'success', autocommit=True)
        except SQLAlchemyError:
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=5)
    def reset_tasks_fail(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        try:
            user.post_message('An error occurred while attempting to reset background tasks. '
                              'Please check the appropriate server logs.', 'error', autocommit=True)
        except SQLAlchemyError:
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def reset_precompute_times(self, user_id):
        try:
            users = db.session.query(User.id).filter_by(active=True).all()
        except SQLAlchemyError:
            raise self.retry()

        work = chain(group(reset_precompute_time.si(ident[0]) for ident in users),
                     reset_precompute_notify.si(user_id)).on_error(reset_precompute_fail.si(user_id))

        raise self.replace(work)


    @celery.task(bind=True, default_retry_delay=30)
    def reset_precompute_time(self, ident):
        try:
            user = db.session.query(User).filter_by(id=ident).first()
        except SQLAlchemyError:
            raise self.retry()

        user.last_precompute = None

        try:
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=5)
    def reset_precompute_notify(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        try:
            user.post_message('All user precompute times have been reset successfully.', 'success', autocommit=True)
        except SQLAlchemyError:
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=5)
    def reset_precompute_fail(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', 'Could not read database records')
            raise Ignore()

        try:
            user.post_message('An error occurred while attempting to reset user precompute times. '
                              'Please check the appropriate server logs.', 'error', autocommit=True)
        except SQLAlchemyError:
            raise self.retry()
