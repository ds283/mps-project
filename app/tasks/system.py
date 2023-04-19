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
from ..shared.internal_redis import get_redis

from ast import literal_eval

from datetime import datetime
from dateutil import parser

def register_system_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def reset_tasks(self, user_id):
        try:
            in_progress_matching = db.session.query(MatchingAttempt.id).filter_by(celery_finished=False).all()
            in_progress_scheduling = db.session.query(ScheduleAttempt.id).filter_by(celery_finished=False).all()
            in_progress_batches = db.session.query(StudentBatch.id).filter_by(celery_finished=False).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = reset_background_tasks.si() | reset_notifications.si()

        if len(in_progress_matching) > 0:
            task = task | group(reset_matching.si(t[0]) for t in in_progress_matching)

        if len(in_progress_scheduling) > 0:
            task = task | group(reset_scheduling.si(t[0]) for t in in_progress_scheduling)

        if len(in_progress_batches) > 0:
            task = task | group(reset_batch.si(t[0]) for t in in_progress_batches)

        task = (task | reset_tasks_notify.si(user_id)).on_error(reset_tasks_fail.si(user_id))

        raise self.replace(task)


    @celery.task(bind=True, default_retry_delay=30)
    def reset_background_tasks(self):
        # reset all background tasks
        self.update_state(state='STARTED')

        try:
            db.session.query(TaskRecord).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='FINISHED')


    @celery.task(bind=True, default_retry_delay=30)
    def reset_notifications(self):
        # reset all notification records
        self.update_state(state='STARTED')

        try:
            db.session.query(Notification).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='FINISHED')


    @celery.task(bind=True, default_retry_delay=30)
    def reset_matching(self, ident):
        try:
            record = db.session.query(MatchingAttempt).filter_by(id=ident).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        record.finished = True
        record.celery_finished = True
        record.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_scheduling(self, ident):
        try:
            record = db.session.query(ScheduleAttempt).filter_by(id=ident).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        record.finished = True
        record.celery_finished = True
        record.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def reset_batch(self, ident):
        try:
            record = db.session.query(StudentBatch).filter_by(id=ident).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        record.celery_finished = True
        record.success = False

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=5)
    def reset_tasks_notify(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        try:
            user.post_message('All background tasks have been reset successfully.', 'success', autocommit=True)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=5)
    def reset_tasks_fail(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        try:
            user.post_message('An error occurred while attempting to reset background tasks. '
                              'Please check the appropriate server logs.', 'error', autocommit=True)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def reset_precompute_times(self, user_id):
        try:
            users = db.session.query(User.id).filter_by(active=True).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        work = chain(group(reset_precompute_time.si(ident[0]) for ident in users),
                     reset_precompute_notify.si(user_id)).on_error(reset_precompute_fail.si(user_id))

        raise self.replace(work)


    @celery.task(bind=True, default_retry_delay=30)
    def reset_precompute_time(self, ident):
        try:
            user = db.session.query(User).filter_by(id=ident).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        user.last_precompute = None

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=5)
    def reset_precompute_notify(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        try:
            user.post_message('All user precompute times have been reset successfully.', 'success', autocommit=True)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=5)
    def reset_precompute_fail(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        try:
            user.post_message('An error occurred while attempting to reset user precompute times. '
                              'Please check the appropriate server logs.', 'error', autocommit=True)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=5, queue='priority')
    def process_pings(self):
        # use Redis-hosted guard flag to determine whether we're already processing some pings
        # if so, then we exit as quickly as we can; intervening pings will just be dropped, since apparently
        # we don't have capacity to process the
        redis_db = get_redis()
        processing = bool(redis_db.get('_processing_pings'))
        if processing is True:
            return

        # set flag with expiry time of 5 minutes
        # this prevents pings never being processed again if this task fails to reset its value
        redis_db.set('_processing_pings', 1, ex=300)

        ping_list = redis_db.hgetall('_pings')
        redis_db.delete('_pings')     # delete as close as possible to read, to avoid race conditions from other threads/instances
        task_list = []

        for key in ping_list:
            value = ping_list[key]

            user_id = literal_eval(key.decode('utf-8'))
            data_tuple = literal_eval(value.decode('utf-8'))

            if not isinstance(user_id, int):
                print('process_pings: decoded "user_id" is not of type int (value={v}, data_tuple={d})'.format(v=user_id, d=data_tuple))
                continue

            if not isinstance(data_tuple, tuple):
                print('process_pings: decoded "data_tuple" is not of type tuple (user_id={v}, data_tuple={d})'.format(v=user_id, d=data_tuple))
                continue

            try:
                since = data_tuple[1]
                if isinstance(since, str):
                    since = literal_eval(since)

                if not isinstance(since, int):
                    print('process_pings: decoded "since" value is not of type int (user_id={v}, since={s}, data_tuple={d})'.format(v=user_id, s=since, d=data_tuple))
                    continue

                iso_timestamp = data_tuple[0]
                if not isinstance(iso_timestamp, str):
                    print('process_pings: decoded "iso_timestamp" value is not of type str (user_id={v}, since={s}, data_tuple={d})'.format(v=user_id, s=since, d=data_tuple))
                    continue

                task_list.append((user_id, iso_timestamp, since))
            except IndexError:
                pass

        tasks = group(handle_ping.si(v[0], v[1], v[2]).set(queue='priority') for v in task_list) \
                | finalize_pings.si().set(queue='priority')
        self.replace(tasks)


    @celery.task(bind=True, default_retry_delay=3, queue='priority')
    def finalize_pings(self):
        redis_db = get_redis()

        # delete guard key from Redis
        redis_db.delete('_processing_pings')


    @celery.task(bind=True, default_retry_delay=1, queue='priority')
    def handle_ping(self, user_id, timestamp, since):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database record')

        if not isinstance(timestamp, datetime):
            timestamp = parser.parse(timestamp)

        if not isinstance(timestamp, datetime):
            self.update_state('FAILURE', meta='Could not decode timestamp parameter')
            raise Ignore()

        notifications = user.notifications \
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

        # the configuration item PRECOMPUTE_DELAY defaults to 30 minutes.
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
        #    30 minutes or so. This does cover the possibility that the 24 hour cache period expires
        #    while the user is still active. If it doesn't, at least we are only starting these jobs
        #    for users actively using the system, which is probably only a handful.
        user.last_active = timestamp

        compute_now = user.last_precompute is None
        if not compute_now:
            delta = timestamp - user.last_precompute

            delay = current_app.config.get('PRECOMPUTE_DELAY')
            if delay is None:
                delay = 1800

            if delta.seconds > delay:
                compute_now = True

        # if we need to re-run a precompute, spawn one
        if compute_now:
            celery = current_app.extensions['celery']
            precompute_at_login(user, celery, now=timestamp, autocommit=False)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
