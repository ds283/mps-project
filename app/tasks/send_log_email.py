#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from ..database import db
from ..models import User, EmailLog, TaskRecord
from ..task_queue import progress_update

from celery import chain
from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime


def register_send_log_email(celery, mail):

    # set up deferred email sender for Flask-Email; note that Flask-Email's Message object is not
    # JSON-serializable so we have to pickle instead
    @celery.task(serializer='pickle', default_retry_delay=10)
    def send_email(task_id, msg):
        progress_update(task_id, TaskRecord.RUNNING, 40, "Sending email", autocommit=True)
        mail.send(msg)


    @celery.task(bind=True, serializer='pickle', default_retry_delay=10)
    def log_email(self, task_id, msg):
        progress_update(task_id, TaskRecord.RUNNING, 80, "Logging email in database", autocommit=True)

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

        except SQLAlchemyError:

            raise self.retry()


    @celery.task()
    def email_success(task_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Task complete", autocommit=True)


    @celery.task()
    def email_failure(task_id):
        progress_update(task_id, TaskRecord.FAILURE, 0, "Task failed", autocommit=True)


    @celery.task(serializer='pickle')
    def send_log_email(task_id, msg):
        progress_update(task_id, TaskRecord.RUNNING, 0, "Preparing to send email", autocommit=True)

        seq = chain(send_email.si(task_id, msg), log_email.si(task_id, msg), email_success.si(task_id)).on_error(
            email_failure.si(task_id))
        seq.apply_async()
