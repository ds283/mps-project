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
from ..models import User, TaskRecord, EmailNotification, ConfirmRequest, LiveProject, FacultyData

from ..task_queue import progress_update, register_task
from ..shared.sqlalchemy import get_count

from celery import chain, group
from celery.exceptions import Ignore

from datetime import datetime


def register_email_notification_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def send_daily_notifications(self):
        # search through all active users and dispatch notifications
        records = db.session.query(User).filter_by(active=True).all()

        task = group(send_user_notifications.si(r.id) for r in records if r is not None)
        task.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def notify_user(self, task_id, user_id):
        progress_update(task_id, TaskRecord.RUNNING, 10, "Preparing to send email...", autocommit=True)

        queue = chain(send_user_notifications.si(user_id),
                      notify_finalize.si(task_id)).on_error(notify_fail.si(task_id))
        queue.apply_async()


    @celery.task()
    def notify_finalize(task_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Finished sending email", autocommit=True)


    @celery.task()
    def notify_fail(task_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, "Error encountered when sending email", autocommit=True)


    @celery.task(bind=True, default_retry_delay=30)
    def send_user_notifications(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            raise Ignore()

        # get number of notifications
        notify_count = get_count(user.email_notifications)

        # build list of ConfirmRequest instances used in these notifications, and compute any outstanding
        # ConfirmRequests that have this user as a project supervisor.
        # We use this list to issue reminders (it will be empty for students)
        crqs = user.email_notifications \
            .filter(or_(EmailNotification.event_type == EmailNotification.CONFIRMATION_REQUEST_CREATED,
                        or_(EmailNotification.event_type == EmailNotification.CONFIRMATION_GRANTED,
                            EmailNotification.event_type == EmailNotification.CONFIRMATION_TO_PENDING))).subquery()
        outstanding_crqs = db.session.query(ConfirmRequest) \
            .join(LiveProject, LiveProject.id == ConfirmRequest.project_id) \
            .filter(LiveProject.owner_id == user.id) \
            .join(crqs, crqs.c.data_1 == ConfirmRequest.id, isouter=True) \
            .filter(crqs.c.data_1 == None) \
            .order_by(ConfirmRequest.request_timestamp.asc())

        outstanding_count = get_count(outstanding_crqs)

        # if there are no notifications and no outstanding requests, then there is nothing to do
        if notify_count == 0 and outstanding_count == 0:
            return None

        # if we get here, there is at least one notification or outstanding notification
        if user.last_email is not None:
            time_since_last_email = datetime.now() - user.last_email

            if not user.group_summaries:
                # if we are not grouping notifications into summaries, there is no summary due, and there are no
                # notifications, then there is nothing to do
                if time_since_last_email.days < user.summary_frequency and notify_count == 0:
                    return None
            else:
                # if we are grouping notifications into summaries, then there is nothing to do unless we are do
                # to issue a summary
                if time_since_last_email.days < user.summary_frequency:
                    return None

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[user.email])

        if not user.group_summaries:
            if notify_count == 1:
                notification = user.email_notifications.first()
                msg.subject = notification.msg_subject()
            else:
                msg.subject = 'Physics & Astronomy projects: new notifications'

            msg.body = render_template('email/notifications/single.txt', user=user,
                                       notifications=user.email_notifications.all(),
                                       outstanding=outstanding_crqs.all())

        else:
            msg.subject = 'Physics & Astronomy projects: summary of notifications'
            msg.body = render_template('email/notifications/rollup.txt', user=user,
                                       notifications=user.email_notifications.all(),
                                       outstanding=outstanding_crqs.all())

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']

        # register a new task in the database
        task_id = register_task(msg.subject,
                                description='Send notification email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        user.last_email = datetime.now()
        user.email_notifications = []
        db.session.commit()
