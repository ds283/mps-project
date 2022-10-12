#
# Created by David Seery on 19/02/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from email.utils import formataddr

from celery import group
from celery.exceptions import Ignore
from flask import current_app, render_template_string, render_template
from flask_mailman import EmailMultiAlternatives
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User
from ..task_queue import register_task


def register_services_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def send_distribution_list(self, list_ids, notify_addresses, subject, body, reply_to, user_id):
        work = group(send_user_record.s(x, subject, body, reply_to) for x in list_ids)

        if isinstance(notify_addresses, list) and len(notify_addresses) > 0:
            notify = group(send_notify.s(x, subject, body, reply_to) for x in notify_addresses)
            work = work | notify

        work = (work | email_success.s(subject, user_id)).on_error(email_failure.si(subject, user_id))

        raise self.replace(work)


    @celery.task(bind=True, default_retry_delay=30)
    def send_user_record(self, user_id, subject, body, reply_to):
        try:
            record: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise KeyError("User record corresponding to distribution list id={num} "
                           "is missing".format(num=user_id))

        body_text = render_template_string(body, name=record.name, first_name=record.first_name,
                                           last_name=record.last_name)

        msg = EmailMultiAlternatives(from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                                     reply_to=reply_to,
                                     to=[formataddr((record.name, record.email))],
                                     subject=subject,
                                     body=render_template('email/services/send_email.txt', body=body_text))

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send direct email to '
                                                         '{name} ({email})'.format(name=record.name,
                                                                                   email=record.email))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


    @celery.task(bind=True, default_retry_delay=30)
    def send_notify(self, prior_result, pair, subject, body, reply_to):
        to_addr = formataddr(pair)

        msg = EmailMultiAlternatives(from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                                     reply_to=reply_to,
                                     to=[to_addr],
                                     subject=subject,
                                     body=render_template('email/services/cc_email.txt', body=body))

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send copy of direct email to {addr}'.format(addr=pair[1]))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


    @celery.task(bind=True, default_retry_delay=30)
    def send_email_list(self, to_addresses, notify_addresses, subject, body, reply_to, user_id):
        work = group(send_email_addr.s(x, subject, body, reply_to) for x in to_addresses)

        if isinstance(notify_addresses, list) and len(notify_addresses) > 0:
            notify = group(send_notify.s(x, subject, body, reply_to) for x in notify_addresses)
            work = work | notify

        work = (work | email_success.s(subject, user_id)).on_error(email_failure.si(subject, user_id))

        raise self.replace(work)


    @celery.task(bind=True, default_retry_delay=30)
    def send_email_addr(self, pair, subject, body, reply_to):
        to_addr = formataddr(pair)

        msg = EmailMultiAlternatives(from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                                     reply_to=reply_to,
                                     to=[to_addr],
                                     subject=subject,
                                     body=render_template('email/services/send_email.txt', body=body))

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send direct email to {addr}'.format(addr=pair[1]))

        # queue Celery task to send the email
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


    @celery.task(bind=True, default_retry_delay=5)
    def email_success(self, prior_result, subject, user_id):
        try:
            record: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        record.post_message('Email with subject "{subj}" successfully sent to all recipients'.format(subj=subject),
                            'success', autocommit=True)

        return True


    @celery.task(bind=True, default_retry_delay=5)
    def email_failure(self, subject, user_id):
        try:
            record: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        record.post_message('An error occurred and your email with subject "{subj}" was not sent '
                            'to all recipients. Please check the email log to determine which instances were '
                            'sent correctly. You may wish to consult with a system '
                            'administrator.'.format(subj=subject),
                            'error', autocommit=True)

        return True
