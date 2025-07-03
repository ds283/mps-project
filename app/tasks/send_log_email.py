#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime
from email.utils import parseaddr
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPDataError,
    SMTPException,
    SMTPNotSupportedError,
    SMTPHeloError,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

from celery import chain
from celery.exceptions import Ignore
from flask import current_app
from flask_mailman import Mail, EmailMessage
from flask_mailman.message import sanitize_address
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, EmailLog, TaskRecord
from ..task_queue import progress_update


def register_send_log_email(celery, mail: Mail):
    @celery.task(bind=True, retry_backoff=True, serializer="pickle")
    def send_email_live(self, task_id, msg: EmailMessage):
        if not current_app.config.get("EMAIL_IS_LIVE", False):
            return {'outcome': 'ignore'}

        progress_update(task_id, TaskRecord.RUNNING, 40, "Sending email...", autocommit=True)
        try:
            # a problem here is that the SMTP connection object used by Flask-Mailman uses an RLock
            # object, which cannot be pickled.
            # So we need NOT to have the connection object stored in msg (as it normally would be
            # via the data member msg.connection in the Flask-Mailman workflow) when we exit, because that could
            # affect downstream pickling
            if hasattr(msg, "body") and msg.body is not None:
                with mail.get_connection() as connection:
                    connection.send_messages([msg])
            else:
                current_app.logger.error("-- send_mail() ignored attempt to send email with empty body")
                with mail.get_connection(backend="console") as connection:
                    msg.connection = connection
                    msg.send()

        except TimeoutError as e:
            current_app.logger.info("-- send_mail() task reporting TimeoutError")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        except (
            SMTPAuthenticationError,
            SMTPConnectError,
            SMTPDataError,
            SMTPException,
            SMTPNotSupportedError,
            SMTPHeloError,
            SMTPRecipientsRefused,
            SMTPResponseException,
            SMTPSenderRefused,
            SMTPServerDisconnected,
        ) as e:
            current_app.logger.info("-- send_mail() task SMTP exception")

            encoding = msg.encoding or "utf-8"
            from_email = sanitize_address(msg.from_email, encoding)
            recipients = [sanitize_address(addr, encoding) for addr in msg.recipients()]
            message = msg.message()

            current_app.logger.info('**   from_email = "{email}"'.format(email=from_email))
            current_app.logger.info('**   recipients = "{recipients}"'.format(recipients=recipients))
            current_app.logger.info('**   message = "{msg}"'.format(msg=message))

            current_app.logger.exception("SMTP exception", exc_info=e)
            raise self.retry()

        return {'outcome': 'success'}

    @celery.task(bind=True, retry_backoff=True, serializer="pickle")
    def send_email_to_console(self, task_id, msg: EmailMessage):
        progress_update(task_id, TaskRecord.RUNNING, 40, "Logging email message to the console...", autocommit=True)

        with mail.get_connection(backend="console") as connection:
            msg.connection = connection
            msg.send()

        return {'outcome': 'no-store'}

    @celery.task(bind=True, default_retry_delay=10, serializer="pickle")
    def log_email(self, result_data, task_id, msg: EmailMessage):
        progress_update(task_id, TaskRecord.RUNNING, 80, "Logging email in database...", autocommit=True)

        if result_data is None:
            return {'outcome': 'unknown'}

        if 'outcome' not in result_data:
            return {'outcome': 'unknown'}

        if 'outcome' in result_data:
            outcome = result_data['outcome']
            if outcome == 'ignore':
                return {'outcome': 'ignore'}

            if outcome == 'no-store':
                return {'outcome': 'no-store'}

            if result_data['outcome'] != 'success':
                return {'outcome': 'failure'}

        # don't log if we are not on a live email platform
        if not current_app.config.get("EMAIL_IS_LIVE", False):
            return {'outcome': 'no-store'}

        # store message in email log
        to_list = msg.recipients()

        # extract HTML content, if any is present
        html = None
        if hasattr(msg, "alternatives"):
            for content, mimetype in msg.alternatives:
                if mimetype == "text/html":
                    html = content
                    break

        recipients = []
        for rcpt in to_list:
            pair = parseaddr(rcpt)
            user = db.session.query(User).filter_by(email=pair[1]).first()
            if user is not None:
                recipients.append(user)

        log = EmailLog(recipients=recipients, send_date=datetime.now(), subject=msg.subject, body=msg.body, html=html)

        try:
            db.session.add(log)
            db.session.commit()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {'outcome': 'success',
                'key': log.id}

    @celery.task()
    def email_success(task_id, result_data):
        if 'outcome' not in result_data:
            progress_update(task_id, TaskRecord.FAILURE, 100, "Task failed with no outcome reported", autocommit=True)
            return

        outcome = result_data['outcome']
        if outcome == 'unknown':
            progress_update(task_id, TaskRecord.FAILURE, 100, "Task failed with unknown outcome", autocommit=True)
            return

        if outcome == 'ignore':
            progress_update(task_id, TaskRecord.SUCCESS, 100, "Task complete (no email sent)", autocommit=True)
            return

        if outcome == 'failure':
            progress_update(task_id, TaskRecord.FAILURE, 100, "Task failed", autocommit=True)
            return

        progress_update(task_id, TaskRecord.SUCCESS, 100, "Task complete", autocommit=True)

        return result_data

    @celery.task()
    def email_failure(task_id):
        progress_update(task_id, TaskRecord.FAILURE, 1000, "Task failed", autocommit=True)

    @celery.task(bind=True, serializer="pickle")
    def send_log_email(self, task_id, msg: EmailMessage):
        progress_update(task_id, TaskRecord.RUNNING, 0, "Preparing to send email...", autocommit=True)

        # only send email (and record it in the email log) if the EMAIL_IS_LIVE key is set in app configuration
        if current_app.config.get("EMAIL_IS_LIVE", False):
            seq = chain(send_email_live.s(task_id, msg), log_email.s(task_id, msg), email_success.s(task_id)).on_error(email_failure.si(task_id))
            raise self.replace(seq)

        seq = chain(send_email_to_console.s(task_id, msg), email_success.s(task_id)).on_error(email_failure.si(task_id))
        raise self.replace(seq)
