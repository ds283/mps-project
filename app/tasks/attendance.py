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
from celery import group, states
from flask import current_app, url_for
from numpy import is_busday
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    EmailLog,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    MarkingEvent,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    SupervisionEvent,
    User,
)
from ..models.emails import encode_email_payload
from ..models.markingevent import MarkingEventWorkflowStates
from ..shared.utils import get_current_year
from ..shared.workflow_logging import log_db_commit


def register_attendance_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def check_for_attendance_prompts(self):
        self.update_state(
            state=states.STARTED, meta={"msg": "Checking for attendance prompts"}
        )

        now = datetime.now()
        today = now.date()
        holiday_calendar = holidays.UK()

        # check once: bail immediately on non-working days
        if today in holiday_calendar:
            msg = {
                "msg": f"Today ({today}) is a UK holiday, skipping attendance prompts"
            }
            print(msg["msg"])
            self.update_state(state=states.SUCCESS, meta=msg)
            return msg

        if not is_busday(today):
            msg = {
                "msg": f"Today ({today}) is not a working day, skipping attendance prompts"
            }
            print(msg["msg"])
            self.update_state(state=states.SUCCESS, meta=msg)
            return msg

        try:
            year = get_current_year()

            configs: List[ProjectClassConfig] = (
                db.session.query(ProjectClassConfig)
                .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
                .filter(
                    ProjectClassConfig.year == year,
                    ProjectClass.active.is_(True),
                    ProjectClass.publish.is_(True),
                )
                .all()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if not configs:
            return None

        self.update_state(
            state=states.STARTED,
            meta={
                "msg": f"Dispatching attendance prompt tasks for {len(configs)} config(s)"
            },
        )

        return self.replace(
            group(
                process_attendance_prompts_for_config.si(config.id)
                for config in configs
            )
        )

    @celery.task(bind=True, default_retry_delay=30)
    def process_attendance_prompts_for_config(self, config_id: int):
        self.update_state(
            state=states.STARTED,
            meta={"msg": f"Processing attendance prompts for config #{config_id}"},
        )

        try:
            config: ProjectClassConfig = (
                db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            msg = {"msg": f"Could not load config #{config_id}"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        try:
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
                    SubmittingStudent,
                    SubmittingStudent.id == SubmissionRecord.owner_id,
                )
                .filter(
                    SupervisionEvent.attendance.is_(None),
                    SupervisionEvent.mute.is_(False),
                    SupervisionEvent.prompt_sent_timestamp.is_(None),
                    ~SubmissionPeriodRecord.marking_events.any(
                        and_(
                            MarkingEvent.workflow_state >= MarkingEventWorkflowStates.OPEN,
                            MarkingEvent.workflow_state < MarkingEventWorkflowStates.CLOSED,
                        )
                    ),
                    SubmissionPeriodRecord.closed.is_(False),
                    SubmissionRole.mute.is_(False),
                    SubmissionRole.prompt_after_event.is_(True),
                    SubmittingStudent.retired.is_(False),
                    SubmittingStudent.config_id == config.id,
                )
                .all()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if not events:
            return None

        now = datetime.now()
        year = get_current_year()

        qualifying = []
        for event in events:
            record: SubmissionRecord = event.sub_record
            owner: SubmissionRole = event.owner
            period: SubmissionPeriodRecord = record.period
            sub: SubmittingStudent = record.owner

            # defensive guards (SQL filter is comprehensive, but guard against race conditions)
            if config.year != year:
                continue
            if sub.retired:
                continue
            if period.is_feedback_open:
                continue
            if period.closed:
                continue
            if event.attendance is not None:
                continue
            if event.mute:
                continue
            if owner.mute:
                continue
            if not owner.prompt_after_event:
                continue
            if event.prompt_sent_timestamp is not None:
                continue

            # compute target_time from owner preferences
            event_time: datetime = event.get_start_time()
            if owner.prompt_at_fixed_time:
                fixed_time: time = owner.prompt_at_time
                target_time = event_time.replace(
                    hour=fixed_time.hour, minute=fixed_time.minute
                )
            else:
                target_time = event_time + timedelta(hours=owner.prompt_delay)

            # event not yet due?
            if target_time > now:
                continue

            # event too old to prompt?
            delta_time: timedelta = now - target_time
            if delta_time.days > 5:
                continue

            qualifying.append((event, target_time, delta_time))

        if not qualifying:
            return None

        template = EmailTemplate.find_template_(
            EmailTemplate.ATTENDANCE_PROMPT, pclass=config.project_class
        )
        workflow = EmailWorkflow.build_(
            name=f"Attendance prompts: {config.name} ({datetime.now().strftime('%d/%m/%Y %H:%M')})",
            template=template,
            defer=timedelta(minutes=15),
            pclasses=[config.project_class],
            creator=config.project_class.convenor.user,
        )
        db.session.add(workflow)

        for event, target_time, delta_time in qualifying:
            record: SubmissionRecord = event.sub_record
            owner: SubmissionRole = event.owner
            sub: SubmittingStudent = record.owner
            sd: StudentData = sub.student
            owner_user: User = owner.user
            student_user: User = sd.user

            event_id = event.id
            owner_id = owner.id
            record_id = record.id
            sub_id = sub.id

            if delta_time.days == 0:
                human_start_time = f"today at {target_time.strftime('%H:%M')}"
            elif delta_time.days == -1:
                human_start_time = f"yesterday at {target_time.strftime('%H:%M')}"
            else:
                human_start_time = f"on {target_time.strftime('%A %d %B')} at {target_time.strftime('%H:%M')}"

            project_hub_url = url_for("projecthub.hub", subid=record_id)
            attendance_OK_api_url = url_for(
                "api.set_event_attendance",
                event_id=event_id,
                owner_id=owner_id,
                record_id=record_id,
                submitter_id=sub_id,
                value=SupervisionEvent.ATTENDANCE_ON_TIME,
            )
            attendance_late_api_url = url_for(
                "api.set_event_attendance",
                event_id=event_id,
                owner_id=owner_id,
                record_id=record_id,
                submitter_id=sub_id,
                value=SupervisionEvent.ATTENDANCE_LATE,
            )
            attendance_notified_api_url = url_for(
                "api.set_event_attendance",
                event_id=event_id,
                owner_id=owner_id,
                record_id=record_id,
                submitter_id=sub_id,
                value=SupervisionEvent.ATTENDANCE_NO_SHOW_NOTIFIED,
            )
            attendance_not_notified_api_url = url_for(
                "api.set_event_attendance",
                event_id=event_id,
                owner_id=owner_id,
                record_id=record_id,
                submitter_id=sub_id,
                value=SupervisionEvent.ATTENDANCE_NO_SHOW_UNNOTIFIED,
            )
            mute_event_api_url = url_for(
                "api.mute_event",
                event_id=event_id,
                owner_id=owner_id,
                record_id=record_id,
            )
            mute_role_api_url = url_for(
                "api.mute_role",
                role_id=owner_id,
                record_id=record_id,
            )

            item = EmailWorkflowItem.build_(
                subject_payload=encode_email_payload({"name": student_user.name}),
                body_payload=encode_email_payload(
                    {
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
                    }
                ),
                recipient_list=[owner_user.email],
                callbacks=[
                    {
                        "task": "app.tasks.attendance.mark_attendance_prompt_sent",
                        "args": [event_id],
                        "kwargs": {},
                    }
                ],
            )
            item.workflow = workflow
            db.session.add(item)

            # deduplication guard: set before commit so a crash cannot cause a duplicate prompt
            event.prompt_sent_timestamp = now

        try:
            db.session.commit()  # intentionally not logged: periodic attendance notification task
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def mark_attendance_prompt_sent(self, email_log_id: int, event_id: int):
        try:
            event: SupervisionEvent = (
                db.session.query(SupervisionEvent).filter_by(id=event_id).first()
            )
            email_log: EmailLog = (
                db.session.query(EmailLog).filter_by(id=email_log_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if event is None:
            msg = {"msg": f"Could not load event #{event_id}"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        if email_log is None:
            print(
                f"!! mark_attendance_prompt_sent: could not find email log with id {email_log_id}"
            )
            msg = {"msg": f"Could not find email log with id {email_log_id}"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        owner: SubmissionRole = event.owner
        record: SubmissionRecord = owner.submission
        config: ProjectClassConfig = record.owner.config

        event.email_log.append(email_log)
        owner.email_log.append(email_log)

        try:
            log_db_commit(
                f"Link attendance prompt for event #{event_id} to email logs",
                endpoint=self.name,
                project_classes=[config.project_class],
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        msg = {"msg": f"Linked attendance prompt for event #{event_id} to email logs"}
        self.update_state(
            state=states.SUCCESS,
            meta=msg,
        )
        return msg
