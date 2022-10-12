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
from flask_mailman import Mail, EmailMessage
from smtplib import SMTPAuthenticationError, SMTPConnectError, SMTPDataError, SMTPException, SMTPNotSupportedError, \
    SMTPHeloError, SMTPRecipientsRefused, SMTPResponseException, SMTPSenderRefused, SMTPServerDisconnected

from ..database import db
from ..models import User, EmailLog, TaskRecord
from ..task_queue import progress_update

from celery import chain
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime
from email.utils import parseaddr


def register_send_log_email(celery, mail: Mail):

    @celery.task(bind=True, retry_backoff=True)
    def send_email(self, task_id, msg: EmailMessage):
        if not current_app.config.get('EMAIL_IS_LIVE', False):
            raise Ignore()

        progress_update(task_id, TaskRecord.RUNNING, 40, "Sending email...", autocommit=True)
        try:
            with mail.get_connection() as connection:
                msg.connection = connection
                msg.send()

        except TimeoutError as e:
            current_app.logger.info('-- send_mail() task reporting TimeoutError')
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        except (SMTPAuthenticationError, SMTPConnectError, SMTPDataError, SMTPException, SMTPNotSupportedError,
                SMTPHeloError, SMTPRecipientsRefused, SMTPResponseException, SMTPSenderRefused,
                SMTPServerDisconnected) as e:
            current_app.logger.info('-- send_mail() task SMTP exception')
            current_app.logger.exception("SMTP exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=10)
    def log_email(self, task_id, msg: EmailMessage):
        progress_update(task_id, TaskRecord.RUNNING, 80, "Logging email in database...", autocommit=True)

        # don't log if we are not on a live email platform
        if not current_app.config.get('EMAIL_IS_LIVE', False):
            raise Ignore()

        try:
            log = None

            # store message in email log
            to_list = msg.recipients()

            # extract HTML content, if any is present
            html = None
            if hasattr(msg, 'alternatives'):
                for content, mimetype in self.alternatives:
                    if mimetype == 'text/html':
                        html = content
                        break

            if len(to_list) == 1:
                # parse "to" field; email address is returned as second member of a 2-tuple
                pair = parseaddr(to_list[0])
                user = User.query.filter_by(email=pair[1]).first()
                if user is not None:
                    log = EmailLog(user_id=user.id,
                                   recipient=None,
                                   send_date=datetime.now(),
                                   subject=msg.subject,
                                   body=msg.body,
                                   html=html)

            if log is None:
                log = EmailLog(user_id=None,
                               recipient=', '.join(to_list),
                               send_date=datetime.now(),
                               subject=msg.subject,
                               body=msg.body,
                               html=html)

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
        progress_update(task_id, TaskRecord.FAILURE, 1000, "Task failed", autocommit=True)


    @celery.task(bind=True, serializer='pickle')
    def send_log_email(self, task_id, msg: EmailMessage):
        progress_update(task_id, TaskRecord.RUNNING, 0, "Preparing to send email...", autocommit=True)

        # only send email if the EMAIL_IS_LIVE key is set in app configuration
        if current_app.config.get('EMAIL_IS_LIVE', False):
            seq = chain(send_email.si(task_id, msg), log_email.si(task_id, msg),
                        email_success.si(task_id)).on_error(email_failure.si(task_id))
            raise self.replace(seq)

        else:
            print(msg.as_string())
