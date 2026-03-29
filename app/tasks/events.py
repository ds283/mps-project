#
# Created by ds283 on 06/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283 <>
#
from typing import Optional

from celery import states
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    TaskRecord,
    SubmissionPeriodRecord,
    User,
    SubmissionRecord,
    SubmissionPeriodUnit,
    SupervisionEventTemplate,
    SupervisionEvent,
    SubmissionRole,
    StudentData,
    SubmittingStudent,
)
from ..shared.tasks import post_task_update_msg
from ..shared.workflow_logging import log_db_commit


def register_supervision_event_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def populate(self, task_id: int, period_id: int, user_id: int):
        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            10,
            "Initializing task...",
        )

        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            msg = f"Could not load SubmissionPeriodRecord id={period_id} from the database"
            post_task_update_msg(self, task_id, states.FAILURE, TaskRecord.FAILURE, 0, msg)
            raise Exception(msg)

        if user is None:
            msg = f"Could not load User id={user_id} from the database"
            post_task_update_msg(self, task_id, states.FAILURE, TaskRecord.FAILURE, 0, msg)
            raise Exception(msg)

        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            10,
            "Populating events...",
        )

        # iterate through submitters for this submission period
        for submission in period.submissions:
            submission: SubmissionRecord
            submitter: SubmittingStudent = submission.owner
            sd: StudentData = submitter.student
            suser: User = sd.user

            # iterate through submission units for this period
            for unit in period.units:
                unit: SubmissionPeriodUnit

                # iterate through templates in this unit
                for template in unit.templates:
                    template: SupervisionEventTemplate

                    # check for an existing event matching this template
                    event: Optional[SupervisionEvent] = submission.get_event(template)

                    # if no event exists, create one
                    if event is None:
                        # find a suitable person with submission role

                        # if the event is targetted at a supervisor, this might be a supervisor or responsible supervisor,
                        # but we should prefer the ordinary supervisor (because they are probably doing
                        # the day-to-day supervision)
                        target_roles = set([template.target_role])
                        if SupervisionEventTemplate.ROLE_SUPERVISOR in target_roles:
                            target_roles.add(
                                SupervisionEventTemplate.ROLE_RESPONSIBLE_SUPERVISOR
                            )

                        # NOTE: this query assumes ROLE_SUPERVISOR is numerically before ROLE_RESPONSIBLE_SUPERVISOR
                        # it may need changing if ever we are in a situation where that is no longer true
                        role = (
                            db.session.query(SubmissionRole)
                            .filter(
                                SubmissionRole.submission_id == submission.id,
                                SubmissionRole.role.in_(target_roles),
                            )
                            .order_by(SubmissionRole.role)
                        ).first()

                        if role is None:
                            print(
                                f'!! event.populate [{period.config.name}]: No suitable role found for submission #{submission.id} ({suser.name}) for template "{template.name}" in submission unit "{unit.name}" in period "{period.display_name}". This event has been ignored.'
                            )
                            continue

                        # find possible attendees
                        other_attendees = (
                            db.session.query(SubmissionRole)
                            .filter(
                                SubmissionRole.id != role.id,
                                SubmissionRole.submission_id == submission.id,
                                SubmissionRole.role.in_(target_roles),
                            )
                            .all()
                        )

                        other_attendees_string = ", ".join(
                            [x.user.name for x in other_attendees]
                        )
                        print(
                            f'** event.populate [{period.config.name}]: Created event for submission #{submission.id} ({suser.name}) for template "{template.name}" in submission unit "{unit.name}" in period "{period.display_name}" | event owner = {role.user.name} | other attendees = [{other_attendees_string}]'
                        )

                        event = SupervisionEvent(
                            unit_id=template.unit_id,
                            template_id=template.id,
                            name=template.name,
                            time=None,
                            sub_record_id=submission.id,
                            owner_id=role.id,
                            team=other_attendees,
                            type=template.type,
                            monitor_attendance=template.monitor_attendance,
                            attendance=None,
                            meeting_summary=None,
                            supervision_notes=None,
                            submitter_notes=None,
                        )

                        db.session.add(event)

        try:
            log_db_commit(
                f"Populated supervision events for submission period '{period.display_name}'",
                user=user,
                project_classes=period.config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
        else:
            post_task_update_msg(
                self,
                task_id,
                states.SUCCESS,
                TaskRecord.SUCCESS,
                0,
                "All events have been populated",
            )
