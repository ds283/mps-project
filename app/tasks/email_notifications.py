#
# Created by David Seery on 2019-01-22.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template
from flask_mail import Message

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord, EmailNotification, ConfirmRequest, LiveProject, Role, SelectingStudent

from ..task_queue import progress_update, register_task
from ..shared.sqlalchemy import get_count

from celery import chain, group
from celery.exceptions import Ignore

from datetime import datetime, date, timedelta
from bdateutil import isbday
import holidays


def _get_outstanding_faculty_confirmation_requests(user):
    # build list of ConfirmRequest instances used in these notifications, and compute any outstanding
    # ConfirmRequests that have this user as a project supervisor.

    crqs = user.email_notifications \
        .filter(or_(EmailNotification.event_type == EmailNotification.CONFIRMATION_REQUEST_CREATED,
                    EmailNotification.event_type == EmailNotification.CONFIRMATION_TO_PENDING)).subquery()

    # find outstanding confirm requests that aren't already included in the list of pending email notifications
    outstanding_crqs = db.session.query(ConfirmRequest) \
        .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED,
                ConfirmRequest.viewed == False) \
        .join(LiveProject, LiveProject.id == ConfirmRequest.project_id) \
        .filter(LiveProject.owner_id == user.id) \
        .join(crqs, crqs.c.data_1 == ConfirmRequest.id, isouter=True) \
        .filter(crqs.c.data_1 == None) \
        .order_by(ConfirmRequest.request_timestamp.asc()).all()

    return [cr.id for cr in outstanding_crqs]


def _get_outstanding_student_confirmation_requests(user):
    # build list of confirmation requests more than a day old owned by this student and which are still outstanding

    cutoff_time = datetime.now() - timedelta(days=1)

    outstanding_crqs = db.session.query(ConfirmRequest) \
        .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED,
                ConfirmRequest.request_timestamp > cutoff_time) \
        .join(SelectingStudent, SelectingStudent.id == ConfirmRequest.owner_id) \
        .filter(SelectingStudent.student_id == user.id) \
        .order_by(ConfirmRequest.request_timestamp.asc()).all()

    return [cr.id for cr in outstanding_crqs]


def register_email_notification_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def send_daily_notifications(self):
        # test whether today is a working day, and if not then bail out; we don't want to bother people
        # with emails at the weekend or on statutory holidays
        today = date.today()
        if not isbday(today, holidays=holidays.UK()):
            return

        # search through all active users and dispatch notifications
        # we treat students and faculty slightly differently so we have different dispatchers for them

        # find all students
        student_recs = db.session.query(User) \
            .filter(User.active == True,
                    User.roles.any(Role.name == 'student')).all()

        student_tasks = group(dispatch_student_notifications.si(r.id) for r in student_recs if r is not None)

        # find all faculty
        faculty_recs = db.session.query(User) \
            .filter(User.active == True,
                    User.roles.any(Role.name == 'faculty')).all()

        faculty_tasks = group(dispatch_faculty_notifications.si(r.id) for r in faculty_recs if r is not None)

        task = group(student_tasks, faculty_tasks)
        raise self.replace(task)


    @celery.task(bind=True, default_retry_delay=30)
    def notify_user(self, task_id, user_id):
        progress_update(task_id, TaskRecord.RUNNING, 10, "Preparing to send email...", autocommit=True)

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        # don't use .has_role() here since that can be confused by role masking

        # we only issue notifications for faculty or students
        queue = None
        if get_count(user.roles.filter(Role.name == 'student')) > 0:
            queue = chain(dispatch_student_notifications.si(user_id),
                          notify_finalize.si(task_id)).on_error(notify_fail.si(task_id))
        elif get_count(user.roles.filter(Role.name == 'faculty')) > 0:
            queue = chain(dispatch_faculty_notifications.si(user_id),
                          notify_finalize.si(task_id)).on_error(notify_fail.si(task_id))

        if queue is not None:
            raise self.replace(queue)


    @celery.task()
    def notify_finalize(task_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Finished sending email", autocommit=True)


    @celery.task()
    def notify_fail(task_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, "Error encountered when sending email", autocommit=True)


    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_faculty_notifications(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        # create snapshot of notifications list; this is what we use *everywhere* to decide which notifications
        # to process, in order to avoid race conditions with other threads adding notifications to the database
        raw_list = [(n.id, n.event_type) for n in user.email_notifications]
        n_ids = [x[0] for x in raw_list]
        c_ids = [x[0] for x in raw_list if x[1] == EmailNotification.CONFIRMATION_REQUEST_CREATED]

        # if we are not grouping notifications into summaries for this user,
        # generate a task to send each email in the queue
        task = None
        if not user.group_summaries:
            if len(n_ids) > 0:
                task = group(dispatch_faculty_single_email.s(user_id, n_id) for n_id in n_ids)

        # we always generate a possible summary, even if the 'group summaries' option is not used,
        # to advise of confirmation requests that are not being handled in a timely fashion.
        has_summary = False
        allow_summary = user.last_email is None
        if not allow_summary:
            time_since_last_email = datetime.now() - user.last_email
            allow_summary = time_since_last_email.days > user.summary_frequency

        if allow_summary:
            cr_ids = _get_outstanding_faculty_confirmation_requests(user)
            summary_ids = n_ids if user.group_summaries else []

            if len(summary_ids) > 0 or len(cr_ids) > 0:
                has_summary = True
                if task is None:
                    task = dispatch_faculty_summary_email.s(None, user.id, summary_ids, cr_ids)
                else:
                    task = task | dispatch_faculty_summary_email.s(user.id, summary_ids, cr_ids)

        # if nothing to do, then return
        if task is None:
            return

        if not has_summary:
            task = task | no_summary_adapter.s()

        # if there *is* something to do, also dispatch paired emails to both faculty and students
        if len(c_ids) > 0:
            # we have to set up this task as a chain so that we can sequentially pass through any
            # list of previously-handled ids
            # If we used a group, each dispatch_new_request_notification() would return its own
            # copy of this list, so we would end up with a list-of-lists in reset_notifications
            if task is None:
                c_id_head = c_ids[0]
                c_ids_tail = c_ids[1:]

                if len(c_ids_tail) > 0:
                    task = dispatch_new_request_notification.s([], c_id_head) | chain(dispatch_new_request_notification.s(c_id) for c_id in c_ids_tail)
                else:
                    task = dispatch_new_request_notification.s([], c_id_head)
            else:
                task = task | chain(dispatch_new_request_notification.s(c_id) for c_id in c_ids)

        task = task | group(reset_notifications.s(), reset_last_email_time.s(user_id))
        raise self.replace(task)


    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_student_notifications(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        # create snapshot of notifications list; this is what we use *everywhere* to decide which notifications
        # to process, in order to avoid race conditions with other threads adding notifications to the database
        n_ids = [n.id for n in user.email_notifications]

        # if we are not grouping notifications into summaries for this user,
        # generate a task to send each email in the queue
        task = None
        if not user.group_summaries:
            if len(n_ids) > 0:
                task = group(dispatch_student_single_email.s(user_id, n_id) for n_id in n_ids)

        # we always generate a possible summary, even if the 'group summaries' option is not used,
        # to advise of confirmation requests that are not being handled in a timely fashion.
        has_summary = False
        allow_summary = user.last_email is None
        if not allow_summary:
            time_since_last_email = datetime.now() - user.last_email
            allow_summary = time_since_last_email.days > user.summary_frequency

        if allow_summary:
            cr_ids = _get_outstanding_student_confirmation_requests(user)
            summary_ids = n_ids if user.group_summaries else []

            if len(summary_ids) > 0 or len(cr_ids) > 0:
                has_summary = True
                if task is None:
                    task = dispatch_student_summary_email.s(None, user.id, summary_ids, cr_ids)
                else:
                    task = task | dispatch_student_summary_email.s(user.id, summary_ids, cr_ids)

        # if nothing to do, then return
        if task is None:
            return

        if not has_summary:
            task = task | no_summary_adapter.s()

        task = task | group(reset_notifications.s(), reset_last_email_time.s(user_id))
        raise self.replace(task)


    @celery.task(bind=True, defaut_retry_delay=1)
    def no_summary_adapter(self, email_outcomes):
        # email_outcomes should either be a singleton int or a list of ints
        if isinstance(email_outcomes, int):
            email_outcomes = [email_outcomes]

        if not isinstance(email_outcomes, list):
            print('!!!! email_outcomes = {x}'.format(x=email_outcomes))
            print('!!!! type of email_outcomes = {x}'.format(x=type(email_outcomes)))
            raise RuntimeError('Could not interpret reported_ids argument in no_summary_adapter')

        # behave as if we were returning from a summary email task with no outstanding confirm requests
        return email_outcomes, []


    @celery.task(bind=True, default_retry_delay=30)
    def reset_notifications(self, reported_ids):
        if not (isinstance(reported_ids, tuple) or isinstance(reported_ids, list)) or len(reported_ids) != 2:
            print('!!!! reported_ids = {x}'.format(x=reported_ids))
            print('!!!! type of reported_ids = {x}'.format(x=type(reported_ids)))
            raise RuntimeError('Could not interpret reported_ids argument in reset_notifications')

        # weed out duplicates; there shouldn't be any, but doesn't hurt
        n_ids_set = set(reported_ids[0])
        n_ids = list(n_ids_set)

        # return value from this group will become the return value from this task;
        # each delete_notification task will return its own n_id, so we will reproduce
        # the same singleton/list of n_ids that we were provided with
        task = group(delete_notification.si(n_id) for n_id in n_ids)
        raise self.replace(task)


    @celery.task(bind=True, default_retry_delay=30)
    def delete_notification(self, n_id):
        if not isinstance(n_id, int):
            raise RuntimeError('Could not interpret n_id argument in delete_notification')

        try:
            notification = db.session.query(EmailNotification).filter_by(id=n_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if notification is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        try:
            db.session.delete(notification)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        # return our value of n_id which will be passed through to reset_last_email_time
        return n_id


    @celery.task(bind=True, default_retry_delay=30)
    def reset_last_email_time(self, reported_ids, user_id):
        if not (isinstance(reported_ids, tuple) or isinstance(reported_ids, list)) or len(reported_ids) != 2:
            print('!!!! reported_ids = {x}'.format(x=reported_ids))
            print('!!!! type of reported_ids = {x}'.format(x=type(reported_ids)))
            raise RuntimeError('Could not interpret reported_ids argument in reset_notifications')

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        n_ids, cr_ids = reported_ids

        # if neither n_ids or cr_ids has any content, then no email was sent
        # this shouldn't happen; it should be weeded out in the dispatch_* functions, but we catch it here
        # just in case
        if len(n_ids) == 0 and len(cr_ids) == 0:
            raise RuntimeError('reset_last_email_time called for {name} with no work done'.format(name=user.name))

        user.last_email = datetime.now()
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()


    # dispatch_faculty_single_email is always at the front of a task chain and so does not need an
    # argument for the return value of the previous task
    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_faculty_single_email(self, user_id, n_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            notification = db.session.query(EmailNotification).filter_by(id=n_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None or notification is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        outstanding_crqs = _get_outstanding_faculty_confirmation_requests(user)

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[user.email],
                      subject=notification.msg_subject())

        msg.body = render_template('email/notifications/faculty/single.txt', user=user,
                                   notification=notification, outstanding=outstanding_crqs)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send notification email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        # return id of the notification we've just handled; this will eventually be passed through to the
        # reset_notifications and reset_last_email_time handlers
        return n_id


    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_faculty_summary_email(self, previous_ids, user_id, n_ids, cr_ids):
        if previous_ids is None:
            previous_ids = []

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        if not isinstance(n_ids, list):
            raise RuntimeError('Can not interpret n_ids argument in dispatch_faculty_summary_email')
        if not isinstance(cr_ids, list):
            raise RuntimeError('Can not interpret cr_ids argument in dispatch_faculty_summary_email')

        try:
            notifications = [db.session.query(EmailNotification).filter_by(id=n_id).first() for n_id in n_ids]
            outstanding_crqs = [db.session.query(ConfirmRequest).filter_by(id=cr_id).first() for cr_id in cr_ids]
        except SQLAlchemyError:
            raise self.retry()

        if any(n is None for n in notifications) or any(cr is None for cr in outstanding_crqs):
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        # if there are no notifications and no outstanding requests, then there is nothing to do;
        # this should have been weeded out
        if len(n_ids) == 0 and len(outstanding_crqs) == 0:
            raise RuntimeError('dispatch_faculty_summary_email called for {name} with no work '
                               'done'.format(name=user.name))

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[user.email],
                      subject='Physics & Astronomy projects: summary of notifications and events')

        msg.body = render_template('email/notifications/faculty/rollup.txt', user=user,
                                   notifications=notifications, outstanding=outstanding_crqs)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send notification email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        previous_set = set(previous_ids)
        ids_set = set(n_ids)

        previous_set = previous_set.union(ids_set)
        return list(previous_set), cr_ids


    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_new_request_notification(self, previous_ids, n_id):
        try:
            notification = db.session.query(EmailNotification).filter_by(id=n_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if notification is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        try:
            req = db.session.query(ConfirmRequest).filter_by(id=notification.data_1).first()
        except SQLAlchemyError:
            raise self.retry()

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=req.project.owner.user.email,
                      recipients=[req.owner.student.user.email, req.project.owner.user.email],
                      subject='{name}: project meeting request'.format(
                          name=req.project.config.project_class.name))

        msg.body = render_template('email/notifications/request_meeting.txt',
                                   supervisor=req.project.owner.user,
                                   student=req.owner.student, config=req.project.config,
                                   project=req.project)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send meeting setup email for "{proj}"'.format(proj=req.project.name))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        # pass through previous_ids
        return previous_ids


    # dispatch_student_single_email is always at the head of a task chain and so does not need an argument
    # for the return value of the previous task
    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_student_single_email(self, user_id, n_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            notification = db.session.query(EmailNotification).filter_by(id=n_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None or notification is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[user.email],
                      subject=notification.msg_subject())

        msg.body = render_template('email/notifications/student/single.txt', user=user, notification=notification)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send notification email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return n_id


    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_student_summary_email(self, previous_ids, user_id, n_ids, cr_ids):
        if previous_ids is None:
            previous_ids = []

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        if not isinstance(n_ids, list):
            raise RuntimeError('Can not interpret n_ids argument in dispatch_student_summary_email')
        if not isinstance(cr_ids, list):
            raise RuntimeError('Can not interpret cr_ids argument in dispatch_student_summary_email')

        try:
            notifications = [db.session.query(EmailNotification).filter_by(id=n_id).first() for n_id in n_ids]
            outstanding_crqs = [db.session.query(ConfirmRequest).filter_by(id=cr_id).first() for cr_id in cr_ids]
        except SQLAlchemyError:
            raise self.retry()

        if any(n is None for n in notifications) or any(cr is None for cr in outstanding_crqs):
            self.update_state('FAILURE', meta='Could not read database records')
            raise Ignore()

        # if there are no notifications and no outstanding requests, then there is nothing to do;
        # this should have been weeded out
        if len(n_ids) == 0 and len(outstanding_crqs) == 0:
            raise RuntimeError('dispatch_student_summary_email called for {name} with no work '
                               'done'.format(name=user.name))

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[user.email],
                      subject='Physics & Astronomy projects: summary of notifications and events')

        msg.body = render_template('email/notifications/student/rollup.txt', user=user,
                                   notifications=notifications, outstanding=outstanding_crqs)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send notification email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        previous_set = set(previous_ids)
        ids_set = set(n_ids)

        previous_set = previous_set.union(ids_set)
        return list(previous_set), cr_ids
