#
# Created by David Seery on 24/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from celery import states
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    ScheduleAttempt,
    SubmissionRole,
)


def register_deploy_schedule_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def deploy_schedule(self, schedule_id: int, user_id: int):
        msg = f"Populating SubmissionRole records for schedule #{schedule_id}"
        self.update_state(state=states.STARTED, meta={"msg": msg})

        try:
            record: ScheduleAttempt = (
                db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = {"msg": f"Could not load ScheduleAttempt #{schedule_id}"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        created = 0
        skipped = 0

        for slot in record.slots:
            for assessor in slot.assessors:
                for talk in slot.talks:
                    # avoid creating duplicate roles
                    try:
                        existing = (
                            db.session.query(SubmissionRole)
                            .filter_by(
                                role=SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
                                submission_id=talk.id,
                                user_id=assessor.id,
                                schedule_slot_id=slot.id,
                            )
                            .first()
                        )
                    except SQLAlchemyError as e:
                        current_app.logger.exception(
                            "SQLAlchemyError exception", exc_info=e
                        )
                        raise self.retry()

                    if existing is not None:
                        skipped += 1
                        continue

                    role = SubmissionRole.build_(
                        role=SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
                        submission_id=talk.id,
                        user_id=assessor.id,
                        schedule_slot_id=slot.id,
                        mute=False,
                        marking_distributed=False,
                        weight=1.0,
                    )
                    db.session.add(role)
                    created += 1

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        msg = {
            "msg": f"Created {created} SubmissionRole record(s) for schedule #{schedule_id} (skipped {skipped} duplicate(s))"
        }
        self.update_state(state=states.SUCCESS, meta=msg)
        return msg

    @celery.task(bind=True, default_retry_delay=30)
    def undeploy_schedule(self, schedule_id: int, user_id: int):
        msg = f"Cleaning up SubmissionRole records for schedule #{schedule_id}"
        self.update_state(state=states.STARTED, meta={"msg": msg})

        try:
            record: ScheduleAttempt = (
                db.session.query(ScheduleAttempt).filter_by(id=schedule_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = {"msg": f"Could not load ScheduleAttempt #{schedule_id}"}
            self.update_state(state=states.FAILURE, meta=msg)
            return msg

        slot_ids = [slot.id for slot in record.slots]

        if not slot_ids:
            msg = {
                "msg": f"No slots found for schedule #{schedule_id}; nothing to clean up"
            }
            self.update_state(state=states.SUCCESS, meta=msg)
            return msg

        try:
            roles = (
                db.session.query(SubmissionRole)
                .filter(
                    SubmissionRole.role == SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
                    SubmissionRole.schedule_slot_id.in_(slot_ids),
                )
                .all()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        removed = 0
        unlinked = 0

        for role in roles:
            if role.submitted_feedback or role.feedback_valid:
                # feedback already entered: unlink from the schedule slot but keep the record
                role.schedule_slot_id = None
                unlinked += 1
            else:
                db.session.delete(role)
                removed += 1

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        msg = {
            "msg": f"Removed {removed} and unlinked {unlinked} SubmissionRole record(s) for schedule #{schedule_id}"
        }
        self.update_state(state=states.SUCCESS, meta=msg)
        return msg
