#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime, timedelta
from typing import List

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import EmailLog, EmailTemplateLabel
from ..shared.sqlalchemy import get_count
from ..shared.workflow_logging import log_db_commit


def register_email(celery):
    @celery.task(bind=True)
    def prune_email_log(self, duration=52, interval="weeks"):
        self.update_state(state="STARTED")

        # get current date
        now = datetime.now()

        # construct a timedelta object corresponding to the specified duration
        delta = timedelta(**{interval: duration})

        # find the cutoff date; emails older than this should be pruned
        limit = now - delta

        try:
            # need to use SQLAlchemy session.delete() if we want the ORM unit of work to remove rows from the
            # email_log_recipients association table; if we just build a query and execute it as a DELETE command, we don't
            # get any session support from SQLAlchemy to manage related objects
            to_delete: List[EmailLog] = db.session.query(EmailLog).filter(
                EmailLog.send_date < limit
            )
            for email in to_delete:
                email: EmailLog
                db.session.delete(email)

            log_db_commit("Prune old email log entries", endpoint=self.name)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in prune_email_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="FINISHED")

    @celery.task(bind=True)
    def delete_all_email(self):
        self.update_state(state="STARTED")

        try:
            db.session.query(EmailLog).delete()
            log_db_commit("Delete all email log records", endpoint=self.name)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in delete_all_email()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="FINISHED")

    @celery.task(bind=True)
    def prune_email_template_labels(self):
        labels: List[EmailTemplateLabel] = db.session.query(EmailTemplateLabel).all()

        try:
            for label in labels:
                label: EmailTemplateLabel

                # if label is not used, prune it
                if get_count(label.templates) == 0:
                    print(
                        f'@@ prune_email_template_labels: removing unused tag "{label.name}"'
                    )
                    db.session.delete(label)

                log_db_commit("Prune unused email template labels", endpoint=self.name)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
