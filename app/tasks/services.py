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
from flask import current_app, render_template_string
from sqlalchemy.exc import SQLAlchemyError

from datetime import timedelta

from ..database import db
from ..models import User, EmailTemplate, EmailWorkflow, EmailWorkflowItem
from ..models.emails import encode_email_payload


def register_services_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def send_distribution_list(
            self, list_ids, notify_addresses, subject, body, reply_to, user_id
    ):
        try:
            creator: User = db.session.query(User).filter_by(id=user_id).first() if user_id is not None else None
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        template = EmailTemplate.find_template_(EmailTemplate.SERVICES_SEND_EMAIL)
        workflow = EmailWorkflow.build_(
            name=f"Distribution email: {subject}",
            template=template,
            defer=timedelta(minutes=15),
            creator=creator,
        )
        db.session.add(workflow)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        workflow_id = workflow.id

        work = group(send_user_record.s(x, subject, body, reply_to, workflow_id) for x in list_ids)

        if isinstance(notify_addresses, list) and len(notify_addresses) > 0:
            notify = group(
                send_notify.s(x, subject, body, reply_to, workflow_id) for x in notify_addresses
            )
            work = work | notify

        work = (work | email_success.s(subject, user_id)).on_error(
            email_failure.si(subject, user_id)
        )

        return self.replace(work)

    @celery.task(bind=True, default_retry_delay=30)
    def send_user_record(self, user_id, subject, body, reply_to, workflow_id):
        try:
            record: User = db.session.query(User).filter_by(id=user_id).first()
            workflow: EmailWorkflow = db.session.query(EmailWorkflow).filter_by(id=workflow_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise KeyError(
                "User record corresponding to distribution list id={num} is missing".format(
                    num=user_id
                )
            )

        if workflow is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load email workflow"}
            )
            raise KeyError(
                "EmailWorkflow record corresponding to id={num} is missing".format(
                    num=workflow_id
                )
            )

        body_text = render_template_string(
            body,
            name=record.name,
            first_name=record.first_name,
            last_name=record.last_name,
        )

        if isinstance(reply_to, str):
            reply_to = [reply_to]

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"subject": subject}),
            body_payload=encode_email_payload({"body": body_text}),
            recipient_list=[formataddr((record.name, record.email))],
            reply_to=reply_to,
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def send_notify(self, prior_result, pair, subject, body, reply_to, workflow_id):
        to_addr = formataddr(pair)

        if isinstance(reply_to, str):
            reply_to = [reply_to]

        try:
            workflow: EmailWorkflow = db.session.query(EmailWorkflow).filter_by(id=workflow_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if workflow is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load email workflow"}
            )
            raise KeyError(
                "EmailWorkflow record corresponding to id={num} is missing".format(
                    num=workflow_id
                )
            )

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"subject": subject}),
            body_payload=encode_email_payload({"body": body}),
            recipient_list=[to_addr],
            reply_to=reply_to,
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def send_email_list(
            self, to_addresses, notify_addresses, subject, body, reply_to, user_id
    ):
        try:
            creator: User = db.session.query(User).filter_by(id=user_id).first() if user_id is not None else None
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        template = EmailTemplate.find_template_(EmailTemplate.SERVICES_SEND_EMAIL)
        workflow = EmailWorkflow.build_(
            name=f"Email list: {subject}",
            template=template,
            defer=timedelta(minutes=15),
            creator=creator,
        )
        db.session.add(workflow)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        workflow_id = workflow.id

        work = group(
            send_email_addr.s(x, subject, body, reply_to, workflow_id) for x in to_addresses
        )

        if isinstance(notify_addresses, list) and len(notify_addresses) > 0:
            notify = group(
                send_notify.s(x, subject, body, reply_to, workflow_id) for x in notify_addresses
            )
            work = work | notify

        work = (work | email_success.s(subject, user_id)).on_error(
            email_failure.si(subject, user_id)
        )

        return self.replace(work)

    @celery.task(bind=True, default_retry_delay=30)
    def send_email_addr(self, pair, subject, body, reply_to, workflow_id):
        to_addr = formataddr(pair)

        if isinstance(reply_to, str):
            reply_to = [reply_to]

        try:
            workflow: EmailWorkflow = db.session.query(EmailWorkflow).filter_by(id=workflow_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if workflow is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load email workflow"}
            )
            raise KeyError(
                "EmailWorkflow record corresponding to id={num} is missing".format(
                    num=workflow_id
                )
            )

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"subject": subject}),
            body_payload=encode_email_payload({"body": body}),
            recipient_list=[to_addr],
            reply_to=reply_to,
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=5)
    def email_success(self, prior_result, subject, user_id):
        try:
            record: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        record.post_message(
            'Email with subject "{subj}" successfully sent to all recipients'.format(
                subj=subject
            ),
            "success",
            autocommit=True,
        )

        return True

    @celery.task(bind=True, default_retry_delay=5)
    def email_failure(self, subject, user_id):
        try:
            record: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        record.post_message(
            'An error occurred and your email with subject "{subj}" was not sent '
            "to all recipients. Please check the email log to determine which instances were "
            "sent correctly. You may wish to consult with a system "
            "administrator.".format(subj=subject),
            "error",
            autocommit=True,
        )

        return True
