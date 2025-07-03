#
# Created by David Seery on 2019-02-28.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from celery import group
from celery.exceptions import Ignore
from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import SubmissionPeriodRecord, SubmissionRecord, ProjectClassConfig, ProjectClass, SubmissionRole, User, SubmittingStudent, StudentData
from ..task_queue import register_task


def register_push_feedback_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def push_period(self, period_id, user_id):
        try:
            period = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        recipients = set()

        for submitter in period.submissions:
            if not submitter.feedback_sent and submitter.has_feedback:
                recipients.add(submitter.id)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        # student notifications cc the supervisor
        tasks = group(
            send_notification_emails.s(r, user_id) for r in recipients if r is not None)
        ) | notify_feedback_push(period_id, user_id)

        raise self.replace(tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def send_notification_emails(self, record_id, user_id):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        # do nothing if feedback has already been sent
        if record.feedback_sent:
            return {'ignored': 1}

        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class

        sub: SubmittingStudent = record.submitting_student
        sd: StudentData = sub.student
        student: User = sd.user

        supervisor_emails = []
        for role in record.supervisor_roles:
            role: SubmissionRole
            person: User = role.user
            supervisor_emails.append(person.email)

        marker_emails = []
        for role in record.marker_roles:
            role: SubmissionRole
            person: User = role.user
            marker_emails.append(person.email)

        # STEP 1 - DISPATCH EMAIL TO STUDENT AND SUPERVISION TEAM

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        msg = EmailMultiAlternatives(
            subject="{proj}: Feedback for {name}".format(proj=pclass.name, name=period.display_name),
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=[record.owner.student.user.email],
            cc=supervisor_emails,
        )

        msg.body = render_template("email/push_feedback/push_to_student.txt", sub=sub, sd=sd, student=student, period=period, pclass=pclass, record=record)

        # register a new task in the database
        task_id = register_task(
            msg.subject, description="{proj}: Push {name} feedback to {r}".format(r=", ".join(msg.to), proj=pclass.name, name=period.display_name)
        )
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        record.feedback_sent = True
        record.feedback_push_id = user_id
        record.feedback_push_timestamp = datetime.now()
        db.session.commit()

        return 1
