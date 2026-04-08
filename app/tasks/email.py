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

from celery import chain

from ..database import db
from ..models import EmailLog, EmailTemplateLabel, EmailWorkflow
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

            db.session.commit()  # intentionally not logged: periodic maintenance task

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

                db.session.commit()  # intentionally not logged: periodic maintenance task

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True)
    def prune_email_workflows(self, duration=104, interval="weeks"):
        """
        Delete EmailWorkflow instances that are either:
          (a) empty — no EmailWorkflowItems attached, regardless of age, or
          (b) completed and older than the specified cutoff.

        Case (a) catches shells left behind when prune_email_log() deleted
        EmailWorkflowItems via ORM cascade, and any other orphaned workflows.
        Case (b) retains completed workflows for the same retention period as
        the email log (default 104 weeks).

        Must be run AFTER prune_email_log() so that newly-emptied workflows
        are caught in the same maintenance window.  Use
        prune_email_log_and_workflows() to ensure correct ordering.
        """
        self.update_state(state="STARTED")

        now = datetime.now()
        delta = timedelta(**{interval: duration})
        limit = now - delta

        try:
            all_workflows: List[EmailWorkflow] = db.session.query(EmailWorkflow).all()
            deleted = 0
            for wf in all_workflows:
                empty = get_count(wf.items) == 0
                expired = wf.completed and wf.completed_timestamp is not None and wf.completed_timestamp < limit
                if empty or expired:
                    db.session.delete(wf)
                    deleted += 1

            db.session.commit()  # intentionally not logged: periodic maintenance task

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in prune_email_workflows()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="FINISHED", meta={"deleted": deleted})

    @celery.task(bind=True)
    def prune_email_log_and_workflows(self, duration=104, interval="weeks"):
        """
        Orchestrating task: prune the email log then clean up EmailWorkflow
        shells and expired completed workflows, in that order.

        prune_email_log() must run first because it cascade-deletes
        EmailWorkflowItems, which can leave EmailWorkflow instances empty.
        prune_email_workflows() then removes those newly-emptied shells in
        the same maintenance window.

        This task replaces direct scheduling of prune_email_log().
        """
        return self.replace(
            chain(
                prune_email_log.si(duration=duration, interval=interval),
                prune_email_workflows.si(duration=duration, interval=interval),
            )
        )
