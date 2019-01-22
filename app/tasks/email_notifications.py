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

from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord

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

        count = get_count(user.email_notifications)

        if count == 0:
            return None

        if user.group_summaries and user.last_email is not None:
            time_since_last_email = datetime.now() - user.last_email
            if time_since_last_email.days < user.summary_frequency:
                return None

        msg = Message(sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      recipients=[user.email])

        if count == 1:
            notification = user.email_notifications.first()
            msg.subject = notification.msg_subject()
            msg.body = render_template('email/notifications/single.txt', user=user, notification=notification)

        else:
            msg.subject = 'Projects: summary of notifications'
            msg.body = render_template('email/notifications/rollup.txt', user=user, notifications=user.email_notifications)

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send notification email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        user.last_email = datetime.now()
        user.email_notifications = []
        db.session.commit()
