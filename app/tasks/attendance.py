#
# Created by David Seery on 15/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime, time, timedelta
from typing import List

import holidays
import humanize
from celery import chain, group, states
from celery.exceptions import Ignore
from flask import current_app, url_for
from numpy import is_busday
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    EmailLog,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    ProjectClassConfig,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionPeriodUnit,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    SupervisionEvent,
    User,
)
from ..models.emails import encode_email_payload
from ..shared.utils import get_current_year
from ..task_queue import register_task


def register_attendance_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def check_for_attendance_prompts(self):
        self.update_state(
            state=states.STARTED, meta={"msg": "Checking for attendance prompts"}
        )

        try:
            year = get_current_year()

            # search for all SupervisionEvents belonging to non-retired submitters,
            # for which a prompt has not already been sent, and for which notifications
            # are not muted
            events: List[SupervisionEvent] = (
                db.session.query(SupervisionEvent)
                .join(SubmissionRole, SubmissionRole.id == SupervisionEvent.owner_id)
                .join(
                    SubmissionRecord,
                    SubmissionRecord.id == SupervisionEvent.sub_record_id,
                )
                .join(
                    SubmissionPeriodRecord,
                    SubmissionPeriodRecord.id == SubmissionRecord.period_id,
                )
                .join(
                    SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id
                )
                .join(
                    ProjectClassConfig,
                    ProjectClassConfig.id == SubmittingStudent.config_id,
                )
                .filter(
                    SupervisionEvent.attendance.is_(None),
                    SupervisionEvent.mute.is_(False),
                    SupervisionEvent.prompt_sent_timestamp.is_(None),
                    SubmissionPeriodRecord.feedback_open.is_(False),
                    SubmissionPeriodRecord.closed.is_(False),
                    SubmissionRole.mute.is_(False),
                    SubmissionRole.prompt_after_event.is_(True),
                    SubmittingStudent.retired.is_(False),
                    ProjectClassConfig.year == year,
                )
                .all()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        # replace ourselves with a group of tasks to check each of these events individually
        self.update_state(
            state=states.STARTED,
            meta={"msg": "Generating tasks to test for email prompts"},
        )
        tasks = group(
            check_event_for_attendance_prompt.si(event.id) for event in events
        )
        print(f"Generated {len(events)} tasks")
        return self.replace(tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def check_event_for_attendance_prompt(self, event_id: int):
        msg = f"Testing event #{event_id} for an attendance email prompt"
        print(msg)
        self.update_state(
            state=states.STARTED,
            meta={"msg": msg},
        )

        try:
            event: SupervisionEvent = (
                db.session.query(SupervisionEvent).filter_by(id=event_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if event is None:
            msg = {"msg": f"Could not load event #{event_id}"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        year = get_current_year()
        record: SubmissionRecord = event.sub_record
        owner: SubmissionRole = event.owner
        period: SubmissionPeriodRecord = record.period
        sub: SubmittingStudent = record.owner
        config: ProjectClassConfig = sub.config
        unit: SubmissionPeriodUnit = event.unit

        student_name: str = sub.student.user.name
        event_label: str = f'"{event.name}"'
        if event.time is not None:
            event_label += f" on {event.time.strftime('%A %-d %B %Y at %H:%M')}"

        # REMOVE LATER
        # restrict emails to just user #1
        # if owner.user_id != 1:
        #     self.update_state(
        #         state=states.SUCCESS,
        #         meta={"msg": f"SubmissionRole #{owner.id} is currently being ignored"},
        #     )
        #     raise Ignore()

        if config.year != year:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name} belongs to a different academic year"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if sub.retired:
            msg = {"msg": f"Event #{event_id} {event_label}: student {student_name} is retired"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if period.feedback_open:
            msg = {
                "msg": f"Event #{event_id} {event_label} for {student_name} belongs to a submission period that has been opened for feedback"
            }
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if period.closed:
            msg = {
                "msg": f"Event #{event_id} {event_label} for {student_name} belongs to a submission period that has been closed"
            }
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if event.attendance is not None:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name} already has attendance recorded"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if event.mute:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name} is muted"}
            print(msg["msg"])
            self.update_state(state=states.SUCCESS, meta=msg)
            return msg

        owner_name: str = owner.user.name

        # is this event in the past?
        # to decide that, we need to know when the owner has asked for prompts to be delivered
        if owner.mute:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name}: owner {owner_name} is muted"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if not owner.prompt_after_event:
            msg = {
                "msg": f"Event #{event_id} {event_label} for {student_name}: owner {owner_name} has not requested an email prompt"
            }
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        if event.prompt_sent_timestamp is not None:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name}: owner {owner_name} has already been notified"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        target_time: datetime
        event_time: datetime = event.get_start_time()

        if owner.prompt_at_fixed_time:
            # event_time is guaranteed to be on a weekday
            fixed_time: time = owner.prompt_at_time
            target_time = event_time.replace(
                hour=fixed_time.hour, minute=fixed_time.minute
            )
        else:
            shift: timedelta = timedelta(hours=owner.prompt_delay)
            target_time = event_time + shift

        # if the event has not yet taken place, then no need to send a prompt yet
        now = datetime.now()
        if target_time > now:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name} is not yet in the past"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        # test whether today is a working day (a "business day" or "bday"), and if not then bail out;
        # we don't want to bother people with emails at the weekend or on statutory holidays
        today = now.date()
        holiday_calendar = holidays.UK()

        # the test is in two parts: first we check for a holiday, then for a conventional working day
        # (in future perhaps allow individual users to choose their own working-day pattern).
        # Annoyingly, numpy.is_busday() won't accept objects generated by the holidays module
        # as a holiday calendar (it wants an array-like of datetime)

        # is today a UK holiday?
        if today in holiday_calendar:
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name}: today ({today}) is a UK holiday, so not sending emails"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        # is today a working day?
        if not is_busday(today):
            msg = {
                "msg": f"Event #{event_id} {event_label} for {student_name}: today ({today}) is not a working day, so not sending emails"
            }
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        # if the event took place more than a few days ago, then probably the owner previously
        # had notifications muted, and has now unmuted them.
        # They won't want to be deluged with prompts for past events.
        # So should send only if the target time passed recently.
        delta_time: timedelta = now - target_time
        if delta_time.days > 5:
            age_str = humanize.precisedelta(delta_time, minimum_unit="days", format="%d")
            msg = {"msg": f"Event #{event_id} {event_label} for {student_name} is too old to send a prompt (age: {age_str})"}
            print(msg["msg"])
            self.update_state(
                state=states.SUCCESS,
                meta=msg,
            )
            return msg

        owner_user: User = owner.user
        sd: StudentData = sub.student
        student_user: User = sd.user

        project_hub_url = url_for("projecthub.hub", subid=record.id)
        attendance_OK_api_url = url_for(
            "api.set_event_attendance",
            event_id=event_id,
            owner_id=owner.id,
            record_id=record.id,
            submitter_id=sub.id,
            value=SupervisionEvent.ATTENDANCE_ON_TIME,
        )
        attendance_late_api_url = url_for(
            "api.set_event_attendance",
            event_id=event_id,
            owner_id=owner.id,
            record_id=record.id,
            submitter_id=sub.id,
            value=SupervisionEvent.ATTENDANCE_LATE,
        )
        attendance_notified_api_url = url_for(
            "api.set_event_attendance",
            event_id=event_id,
            owner_id=owner.id,
            record_id=record.id,
            submitter_id=sub.id,
            value=SupervisionEvent.ATTENDANCE_NO_SHOW_NOTIFIED,
        )
        attendance_not_notified_api_url = url_for(
            "api.set_event_attendance",
            event_id=event_id,
            owner_id=owner.id,
            record_id=record.id,
            submitter_id=sub.id,
            value=SupervisionEvent.ATTENDANCE_NO_SHOW_UNNOTIFIED,
        )
        mute_event_api_url = url_for(
            "api.mute_event",
            event_id=event_id,
            owner_id=owner.id,
            record_id=record.id,
        )
        mute_role_api_url = url_for(
            "api.mute_role",
            role_id=owner.id,
            record_id=record.id,
        )

        human_start_time: str
        if delta_time.days == 0:
            human_start_time = f"today at {target_time.strftime('%H:%M')}"
        elif delta_time.days == -1:
            human_start_time = f"yesterday at {target_time.strftime('%H:%M')}"
        else:
            human_start_time = f"on {target_time.strftime('%A %d %B')} at {target_time.strftime('%H:%M')}"

        template = EmailTemplate.find_template_(
            EmailTemplate.ATTENDANCE_PROMPT, pclass=config.project_class
        )
        workflow = EmailWorkflow.build_(
            name=f"Attendance prompt: {config.name} — {owner_user.name} for {student_user.name}",
            template=template,
            defer=timedelta(minutes=15),
            pclasses=[config.project_class],
        )
        db.session.add(workflow)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"name": student_user.name}),
            body_payload=encode_email_payload({
                "event": event,
                "user": owner_user,
                "sd": sd,
                "pclass": config.project_class,
                "human_start_time": human_start_time,
                "projecthub_url": project_hub_url,
                "attendance_OK_api_url": attendance_OK_api_url,
                "attendance_late_api_url": attendance_late_api_url,
                "attendance_notified_api_url": attendance_notified_api_url,
                "attendance_not_notified_api_url": attendance_not_notified_api_url,
                "mute_event_api_url": mute_event_api_url,
                "mute_role_api_url": mute_role_api_url,
            }),
            recipient_list=[owner_user.email],
        )
        item.workflow = workflow
        db.session.add(item)

        # Set prompt_sent_timestamp before committing so that a crash cannot
        # cause a duplicate prompt to be queued.
        event.prompt_sent_timestamp = datetime.now()
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def mark_attendance_prompt_sent(self, result_data, event_id):
        if "outcome" not in result_data:
            print(
                f"!! mark_attendance_prompt_sent: no outcome in result_data (result_data={result_data})"
            )
            msg = {"msg": "No outcome in result_data"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        outcome = result_data["outcome"]
        if outcome in ["unknown", "failure"]:
            print(
                f"!! mark_attendance_prompt_sent: outcome was unknown or failure (result_data={result_data})"
            )
            msg = {"msg": "Outcome was unknown or failure"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        if outcome in ["no-store"]:
            print(
                f"!! mark_attendance_prompt_sent: outcome was marked no-store (result_data={result_data})"
            )
            msg = {"msg": "Outcome was marked no-store"}
            self.update_state(state=states.SUCCESS, meta=msg)
            return msg

        try:
            event: SupervisionEvent = (
                db.session.query(SupervisionEvent).filter_by(id=event_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if "key" not in result_data:
            print(
                f"!! mark_attendance_prompt_sent: no key in result_data (result_data={result_data})"
            )
            msg = {"msg": "No key in result_data"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        key = result_data["key"]
        email_log: EmailLog = (
            db.session.query(EmailLog).filter(EmailLog.id == key).first()
        )

        if email_log is None:
            print(
                f"!! mark_attendance_prompt_sent: could not find email log with key {key}"
            )
            msg = {"msg": f"Could not find email log with key {key}"}
            self.update_state(
                state=states.FAILURE,
                meta=msg,
            )
            return msg

        owner: SubmissionRole = event.owner

        event.email_log.append(email_log)
        owner.email_log.append(email_log)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        msg = {"msg": f"Marked attendance prompt sent for event #{event_id}"}
        self.update_state(
            state=states.SUCCESS,
            meta=msg,
        )
        return msg
