#
# Created by David Seery on 2018-12-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from celery import chain, group
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord, Notification, MatchingAttempt, ScheduleAttempt, StudentBatch
from ..shared.precompute import precompute_at_login

from datetime import datetime
from dateutil import parser


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
            db.rollback()
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_notifications(self):
        # reset all notification records
        try:
            db.session.query(Notification).delete()
            db.session.commit()
        except SQLAlchemyError:
            db.rollback()
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
            db.rollback()
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
            db.rollback()
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
            db.rollback()
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
            db.rollback()
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


    @celery.task(bind=True, default_retry_delay=1)
    def ping(self, since, user_id, now):
        if isinstance(now, str):
            now = parser.parse(now)

        if not isinstance(now, datetime):
            self.update_state('FAILURE', meta='Cannot interpret datetime argument')
            raise Ignore()

        try:
            current_user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if current_user is None:
            self.update_state('FAILURE', meta='Cannot load user record')
            raise Ignore()

        notifications = current_user.notifications \
            .filter(Notification.timestamp >= since) \
            .order_by(Notification.timestamp.asc()).all()

        # mark any messages or instructions (as opposed to task progress updates) for removal on next page load
        for n in notifications:
            if n.type == Notification.USER_MESSAGE \
                    or n.type == Notification.SHOW_HIDE_REQUEST \
                    or n.type == Notification.REPLACE_TEXT_REQUEST:
                n.remove_on_pageload = True

        # determine whether to kick off a background precompute task
        # currently, precompute tasks are run *here*, and *at login*, and nowhere else,
        # and the default lifetime for items in the cache is 24 hours

        # the configuration item PRECOMPUTE_DELAY defaults to 10 minutes.
        # We start a precompute task if either:
        #  - If there is no recorded last precompute time. This means that the app has restarted since this
        #    user was last seen online, and therefore the cache has been flushed. It is likely that all
        #    precomputed items have been purged, so we need to start an urgent precompute
        #  - The time since the last recorded precompute exceeds PRECOMPUTE_DELAY.
        #    If a user with a non-expired session comes back to the site after a delay, they do not
        #    (currently) go through login again. (The session is 'stale' but still treated as current.)
        #    This means no precompute is kicked off. We won't pick up that the cache likely contains no
        #    entries until we get here.
        #    Of course, this means that we *also* perform redundant precomputes for all active users every
        #    10 minutes or so. This does cover the possibility that the 24 hour cache period expires
        #    while the user is still active. If it doesn't, at least we are only starting these jobs
        #    for users actively using the system, which is probably only a handful.
        compute_now = current_user.last_precompute is None
        if not compute_now:
            delta = now - current_user.last_precompute

            delay = current_app.config.get('PRECOMPUTE_DELAY')
            if delay is None:
                delay = 600

            if delta.seconds > delay:
                compute_now = True

        # if we need to re-run a precompute, spawn one
        if compute_now:
            celery = current_app.extensions['celery']
            precompute_at_login(current_user, celery, now=now, autocommit=False)

        current_user.last_active = now

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.rollback()
            raise self.retry()
