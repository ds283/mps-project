#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app

from ..database import db
from ..models import User, EmailLog, TaskRecord
from ..task_queue import progress_update

from celery import chain
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime


def register_send_log_email(celery, mail):

    # set up deferred email sender for Flask-Email; note that Flask-Email's Message object is not
    # JSON-serializable so we have to pickle instead
    @celery.task(bind=True, serializer='pickle', default_retry_delay=10)
    def send_email(self, task_id, msg):
        if not current_app.config.get('EMAIL_IS_LIVE', False):
            raise Ignore()

        progress_update(task_id, TaskRecord.RUNNING, 40, "Sending email...", autocommit=True)
        try:
            mail.send(msg)
        except TimeoutError:
            raise self.retry()


    @celery.task(bind=True, serializer='pickle', default_retry_delay=10)
    def log_email(self, task_id, msg):
        progress_update(task_id, TaskRecord.RUNNING, 80, "Logging email in database...", autocommit=True)

        if not current_app.config.get('EMAIL_IS_LIVE', False):
            raise Ignore()

        try:
            log = None

            # store message in email log
            if len(msg.recipients) == 1:
                user = User.query.filter_by(email=msg.recipients[0]).first()
                if user is not None:
                    log = EmailLog(user_id=user.id,
                                   recipient=None,
                                   send_date=datetime.now(),
                                   subject=msg.subject,
                                   body=msg.body,
                                   html=msg.html)

            if log is None:
                log = EmailLog(user_id=None,
                               recipient=', '.join(msg.recipients),
                               send_date=datetime.now(),
                               subject=msg.subject,
                               body=msg.body,
                               html=msg.html)

            db.session.add(log)
            db.session.commit()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task()
    def email_success(task_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Task complete", autocommit=True)


    @celery.task()
    def email_failure(task_id):
        progress_update(task_id, TaskRecord.FAILURE, 0, "Task failed", autocommit=True)


    @celery.task(bind=True, serializer='pickle')
    def send_log_email(self, task_id, msg):
        progress_update(task_id, TaskRecord.RUNNING, 0, "Preparing to send email...", autocommit=True)

        # only send email if the EMAIL_IS_LIVE key is set in app configuration
        if current_app.config.get('EMAIL_IS_LIVE', False):
            seq = chain(send_email.si(task_id, msg), log_email.si(task_id, msg),
                        email_success.si(task_id)).on_error(email_failure.si(task_id))
            raise self.replace(seq)

        else:
            print(msg)
