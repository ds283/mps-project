#
# Created by David Seery on 13/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery tasks for the consent workflow.
"""

from datetime import datetime

from celery.utils.log import get_task_logger

from ..database import db
from ..models import SubmissionRecord

logger = get_task_logger(__name__)


def register_consent_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def record_consent_invitation_sent(self, email_log_id: int, record_id: int):
        """
        Celery callback invoked after a consent invitation EmailWorkflowItem is successfully
        sent. Sets SubmissionRecord.consent_invitation_sent_at.

        Called by the email send pipeline with (email_log_id, record_id); email_log_id is
        prepended automatically by the callback dispatcher.
        """
        try:
            record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
        except Exception as e:
            logger.exception(f"record_consent_invitation_sent: database error loading record #{record_id}", exc_info=e)
            raise self.retry()

        if record is None:
            logger.warning(f"record_consent_invitation_sent: SubmissionRecord #{record_id} not found")
            return

        if record.consent_invitation_sent_at is None:
            record.consent_invitation_sent_at = datetime.now()
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.exception(
                    f"record_consent_invitation_sent: failed to update record #{record_id}",
                    exc_info=e,
                )
                raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def record_consent_reminder_sent(self, email_log_id: int, record_id: int):
        """
        Celery callback invoked after a consent reminder EmailWorkflowItem is successfully
        sent. Sets SubmissionRecord.consent_reminder_sent_at.

        Called by the email send pipeline with (email_log_id, record_id); email_log_id is
        prepended automatically by the callback dispatcher.
        """
        try:
            record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
        except Exception as e:
            logger.exception(f"record_consent_reminder_sent: database error loading record #{record_id}", exc_info=e)
            raise self.retry()

        if record is None:
            logger.warning(f"record_consent_reminder_sent: SubmissionRecord #{record_id} not found")
            return

        if record.consent_reminder_sent_at is None:
            record.consent_reminder_sent_at = datetime.now()
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.exception(
                    f"record_consent_reminder_sent: failed to update record #{record_id}",
                    exc_info=e,
                )
                raise self.retry()
