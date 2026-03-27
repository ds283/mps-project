#
# Created by David Seery on 2019-01-20.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import re
from datetime import datetime, timedelta

from celery import chain, group
from celery.exceptions import Ignore
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    BackupRecord,
    DescriptionComment,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    EnrollmentRecord,
    FacultyData,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    Role,
    TaskRecord,
    User,
)
from ..models.emails import encode_email_payload
from ..shared.sqlalchemy import get_count
from ..shared.workflow_logging import log_db_commit
from ..task_queue import progress_update, register_task


def register_issue_confirm_tasks(celery):
    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def pclass_issue(self, task_id, config_id, convenor_id, deadline):
        progress_update(
            task_id,
            TaskRecord.RUNNING,
            0,
            "Preparing to issue confirmation requests...",
            autocommit=True,
        )

        # get database records for this project class
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
            convenor: User = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None or convenor is None:
            if convenor is not None:
                convenor.post_message(
                    "Issuing confirmation requests failed because some database records could not be loaded.",
                    "danger",
                    autocommit=True,
                )

            if config is None:
                self.update_state(
                    "FAILURE",
                    meta={
                        "msg": "Could not load ProjectClassConfig record from database"
                    },
                )

            if convenor is None:
                self.update_state(
                    "FAILURE",
                    meta={"msg": "Could not load convenor User record from database"},
                )

            return issue_fail.apply_async(args=(task_id, convenor_id))

        if not config.project_class.publish:
            return None

        year = config.year

        if (
                config.selector_lifecycle
                > ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED
        ):
            convenor.post_message(
                "Confirmation requests for {name} {yra}-{yrb} have already been issued.".format(
                    name=config.name, yra=year, yrb=year + 1
                ),
                "warning",
                autocommit=True,
            )
            self.update_state(
                "FAILURE", meta={"msg": "Confirmation requests have not been issued"}
            )
            return issue_fail.apply_async(args=(task_id, convenor_id))

        config.confirmation_required = []

        # issue confirmation requests if this project is set up to require them
        if not config.require_confirm:
            return None

        # select faculty that are enrolled on this particular project class
        # (will exclude faculty that are eg. on sabbatical)
        fd = (
            db.session.query(FacultyData)
            .select_from(EnrollmentRecord)
            .filter(
                EnrollmentRecord.pclass_id == config.pclass_id,
                EnrollmentRecord.supervisor_state
                == EnrollmentRecord.SUPERVISOR_ENROLLED,
            )
            .join(FacultyData, FacultyData.id == EnrollmentRecord.owner_id)
            .join(User, User.id == FacultyData.id)
            .filter(User.active.is_(True))
            .distinct()
        )

        faculty = set()
        for data in fd:
            if data.id not in faculty:
                faculty.add(data.id)

        # build a task group to mark individual faculty as needing to provide confirmation of their
        # project descriptions
        issue_group = group(
            issue_confirm.si(d, config_id) for d in faculty if d is not None
        )

        # get backup task from celery instance
        celery = current_app.extensions["celery"]
        backup = celery.tasks["app.tasks.backup.backup"]

        seq = chain(
            issue_initialize.si(task_id),
            backup.si(
                convenor_id,
                type=BackupRecord.PROJECT_ISSUE_CONFIRM_FALLBACK,
                tag="issue_confirm",
                description="Rollback snapshot for issuing confirmation requests for {proj} confirmations {yr}".format(
                    proj=config.name, yr=year
                ),
            ),
            issue_group,
            issue_update_db.s(task_id, config_id, convenor_id, deadline),
            issue_notifications.s(task_id, config_id, convenor_id),
            issue_finalize.si(task_id, config_id, convenor_id),
        ).on_error(issue_fail.si(task_id, convenor_id))

        seq.apply_async()

    @celery.task()
    def issue_initialize(task_id):
        progress_update(
            task_id,
            TaskRecord.RUNNING,
            5,
            "Building rollback confirmation requests snapshot...",
            autocommit=True,
        )

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def issue_update_db(self, notify_list, task_id, config_id, convenor_id, deadline):
        progress_update(
            task_id,
            TaskRecord.RUNNING,
            80,
            "Updating database records...",
            autocommit=False,
        )

        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        config.requests_issued = True
        config.request_deadline = deadline
        config.requests_issued_id = convenor_id
        config.requests_timestamp = datetime.now()

        log_db_commit(
            f"Marked confirmation requests as issued for project class '{config.name}'",
            user=convenor_id,
            project_classes=config.project_class,
            endpoint=self.name,
        )

        return notify_list

    @celery.task(bind=True, default_retry_delay=30)
    def issue_notifications(self, notify_list, task_id, config_id, convenor_id):
        progress_update(
            task_id,
            TaskRecord.RUNNING,
            90,
            "Sending email notifications...",
            autocommit=True,
        )

        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        template = EmailTemplate.find_template_(
            EmailTemplate.PROJECT_CONFIRMATION_REQUESTED, pclass=config.project_class
        )
        workflow = EmailWorkflow.build_(
            name=f"Confirmation request: {config.project_class.name}",
            template=template,
            defer=timedelta(hours=1),
            pclasses=[config.project_class],
        )
        db.session.add(workflow)
        db.session.flush()
        workflow_id = workflow.id

        try:
            log_db_commit(
                f"Created email workflow for confirmation requests: project class '{config.project_class.name}'",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        task = chain(
            group(
                send_notification_email.si(d, config_id, workflow_id)
                for d in notify_list
                if d is not None
            ),
            notify.s(convenor_id, "{n} confirmation request{pl} issued", "info"),
        )

        return self.replace(task)

    @celery.task(bind=True, default_retry_delay=30)
    def issue_finalize(self, task_id, config_id, convenor_id):
        progress_update(
            task_id,
            TaskRecord.SUCCESS,
            100,
            "Issue confirmation requests complete",
            autocommit=False,
        )

        try:
            convenor: User = User.query.filter_by(id=convenor_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is not None:
            # send direct message to user announcing successful Go Live event
            convenor.post_message(
                'Issuing confirmation requests for "{proj}" '
                "for {yra}-{yrb} is now complete".format(
                    proj=config.name, yra=config.submit_year_a, yrb=config.submit_year_b
                ),
                "success",
                autocommit=False,
            )

        log_db_commit(
            f"Finalized issue of confirmation requests for project class '{config.name}'",
            user=convenor_id,
            project_classes=config.project_class if config is not None else None,
            endpoint=self.name,
        )

    @celery.task(bind=True, default_retry_delay=30)
    def issue_fail(self, task_id, convenor_id):
        progress_update(
            task_id,
            TaskRecord.FAILURE,
            100,
            "Encountered error when issuing confirmation requests",
            autocommit=False,
        )

        try:
            convenor: User = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        convenor.post_message(
            "Issuing confirmation requests failed. Please contact a system administrator",
            "error",
            autocommit=False,
        )
        log_db_commit(
            "Recorded failure of confirmation request issue",
            user=convenor_id,
            endpoint=self.name,
        )

    @celery.task(bind=True, default_retry_delay=30)
    def issue_confirm(self, faculty_id, config_id):
        try:
            data: FacultyData = FacultyData.query.filter_by(id=faculty_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None or config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        if not config.require_confirm:
            return None

        try:
            config.confirmation_required.append(data)
            log_db_commit(
                f"Added faculty '{data.user.name}' to confirmation required list for project class '{config.project_class.name}'",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return faculty_id

    @celery.task(bind=True, default_retry_delay=30)
    def send_notification_email(self, faculty_id, config_id, workflow_id):
        try:
            data: FacultyData = FacultyData.query.filter_by(id=faculty_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
            workflow: EmailWorkflow = EmailWorkflow.query.filter_by(id=workflow_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None or config is None or workflow is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        projects = list(data.projects_offered(config.project_class))

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"name": config.project_class.name}),
            body_payload=encode_email_payload({
                "user": data.user,
                "pclass": config.project_class,
                "config": config,
                "number_projects": len(projects),
                "projects": projects,
            }),
            recipient_list=[data.user.email],
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            log_db_commit(
                f"Queued confirmation request notification email for faculty '{data.user.name}' ({config.project_class.name})",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 1

    @celery.task(bind=True, default_retry_delay=30)
    def reminder_email(self, config_id, convenor_id):
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        recipients = set()

        for faculty in config.faculty_waiting_confirmation:
            recipients.add(faculty.id)

        template = EmailTemplate.find_template_(
            EmailTemplate.PROJECT_CONFIRMATION_REMINDER, pclass=config.project_class
        )
        workflow = EmailWorkflow.build_(
            name=f"Confirmation reminder: {config.project_class.name}",
            template=template,
            defer=timedelta(hours=1),
            pclasses=[config.project_class],
        )
        db.session.add(workflow)
        db.session.flush()
        workflow_id = workflow.id

        try:
            log_db_commit(
                f"Created email workflow for confirmation reminders: project class '{config.project_class.name}'",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        tasks = chain(
            group(
                send_reminder_email.si(r, config_id, workflow_id)
                for r in recipients
                if r is not None
            ),
            notify.s(convenor_id, "{n} reminder email{pl} issued", "info"),
        )

        return self.replace(tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def send_reminder_email(self, faculty_id, config_id, workflow_id):
        try:
            data: FacultyData = FacultyData.query.filter_by(id=faculty_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
            workflow: EmailWorkflow = EmailWorkflow.query.filter_by(id=workflow_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None or config is None or workflow is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        projects = list(data.projects_offered(config.project_class))

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"name": config.project_class.name}),
            body_payload=encode_email_payload({
                "user": data.user,
                "pclass": config.project_class,
                "config": config,
                "number_projects": len(projects),
                "projects": projects,
            }),
            recipient_list=[data.user.email],
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            log_db_commit(
                f"Queued confirmation reminder email for faculty '{data.user.name}' ({config.project_class.name})",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 1

    @celery.task(bind=True, default_retry_delay=30)
    def enroll_adjust(self, enroll_id, old_supervisor_state, current_year):
        try:
            record: EnrollmentRecord = (
                db.session.query(EnrollmentRecord).filter_by(id=enroll_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        # load current configuration record for this project
        config: ProjectClassConfig = record.pclass.get_config(current_year)

        if record is None or config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        # if confirmations not required, nothing to do
        if not config.require_confirm:
            return None

        # if confirmation requests not yet issued, nothing to do
        if not config.requests_issued:
            return None

        # if project has gone live, confirmation requests are no longer needed
        if config.live:
            return None

        # remove supervisors from confirmation list if no longer normally enrolled
        if record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
            if (
                    get_count(config.confirmation_required.filter_by(id=record.owner_id))
                    > 0
            ):
                config.confirmation_required.remove(record.owner)

        if (
                record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                and old_supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED
        ):
            if (
                    get_count(config.confirmation_required.filter_by(id=record.owner_id))
                    == 0
            ):
                config.confirmation_required.append(record.owner)

        log_db_commit(
            f"Adjusted confirmation required list for faculty after enrollment change (project class '{config.project_class.name}')",
            project_classes=config.project_class,
            endpoint=self.name,
        )

    @celery.task(bind=True, default_retry_delay=30)
    def enrollment_created(self, enroll_id, current_year):
        try:
            record: EnrollmentRecord = (
                db.session.query(EnrollmentRecord).filter_by(id=enroll_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        # load current configuration record for this project
        config: ProjectClassConfig = record.pclass.get_config(current_year)

        if record is None or config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        # if confirmations not required, nothing to do
        if not config.require_confirm:
            return None

        # if confirmation requests not yet issued, nothing to do
        if not config.requests_issued:
            return None

        # if project has gone live, confirmation requests are no longer needed
        if config.live:
            return None

        # add supervisor to confirmation list if normally enrolled
        if record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED:
            if (
                    get_count(config.confirmation_required.filter_by(id=record.owner_id))
                    == 0
            ):
                config.confirmation_required.append(record.owner)

        log_db_commit(
            f"Updated confirmation required list following enrollment creation (project class '{config.project_class.name}')",
            project_classes=config.project_class,
            endpoint=self.name,
        )

    @celery.task(bind=True, default_retry_delay=30)
    def enrollment_deleted(self, pclass_id, faculty_id, current_year):
        try:
            faculty: FacultyData = (
                db.session.query(FacultyData).filter_by(id=faculty_id).first()
            )
            pclass: ProjectClass = (
                db.session.query(ProjectClass).filter_by(id=pclass_id).first()
            )
            config: ProjectClassConfig = pclass.get_config(current_year)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if faculty is None or config is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

            # if confirmations not required, nothing to do
        if not config.require_confirm:
            return None

            # if confirmation requests not yet issued, nothing to do
        if not config.requests_issued:
            return None

            # if project has gone live, confirmation requests are no longer needed
        if config.live:
            return None

        if get_count(config.confirmation_required.filter_by(id=faculty_id)) > 0:
            config.confirmation_required.remove(faculty)
            log_db_commit(
                f"Removed faculty from confirmation required list following enrollment deletion (project class '{config.project_class.name}')",
                project_classes=config.project_class,
                endpoint=self.name,
            )

    @celery.task(bind=True, default_retry_delay=30)
    def revise_notify(self, record_id, pcl_names, user_id):
        try:
            record = (
                db.session.query(ProjectDescription).filter_by(id=record_id).first()
            )
            current_user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None or current_user is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        project = record.parent
        owner = project.owner

        template = EmailTemplate.find_template_(
            EmailTemplate.PROJECT_CONFIRMATION_REVISE_REQUEST
        )
        workflow = EmailWorkflow.build_(
            name=f"Confirmation revision request: {project.name}",
            template=template,
            defer=timedelta(hours=1),
            pclasses=list(record.project_classes),
        )
        db.session.add(workflow)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"name": project.name, "desc": record.label}),
            body_payload=encode_email_payload({
                "user": owner.user,
                "pclasses": list(record.project_classes),
                "project": project,
                "record": record,
                "pcl_names": pcl_names,
                "current_user": current_user,
            }),
            recipient_list=[owner.user.email],
            reply_to=[current_user.email],
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            log_db_commit(
                f"Queued revision request notification email for project '{project.name}'",
                user=user_id,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 1

    @celery.task(bind=True)
    def propagate_confirm(self, user_id, exclude_pclass_id):
        try:
            records = (
                db.session.query(EnrollmentRecord)
                .filter(
                    EnrollmentRecord.owner_id == user_id,
                    EnrollmentRecord.pclass_id != exclude_pclass_id,
                )
                .all()
            )
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None or user.faculty_data is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        fac_data = user.faculty_data

        for record in records:
            config: ProjectClassConfig = record.pclass.most_recent_config

            if config is not None:
                if fac_data.number_projects_offered(config.pclass_id) > 0:
                    # if no confirmations outstanding, mark this project class as confirmed automatically
                    if config.is_confirmation_required(
                            user_id
                    ) and not config.has_confirmations_outstanding(user_id):
                        config.mark_confirmed(user_id, message=False)

                        user.post_message(
                            "No further project descriptions attached to project class "
                            '"{name}" require confirmation, so it has been marked as '
                            "ready to publish.".format(name=config.project_class.name),
                            "info",
                            autocommit=False,
                        )

        db.session.commit()

    @celery.task(bind=True)
    def notify_comment(self, comment_id):
        try:
            comment: DescriptionComment = (
                db.session.query(DescriptionComment).filter_by(id=comment_id).first()
            )
            project_approver = (
                db.session.query(Role).filter_by(name="project_approver").first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if comment is None or project_approver is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            raise Ignore()

        approvals_team = set()
        for m in project_approver.users:
            approvals_team.add(m.email)

        recipients = set()

        owner: User = comment.owner
        parent: ProjectDescription = comment.parent

        for c in parent.comments.filter_by(year=comment.year):
            if c.owner_id != comment.owner_id:
                if c.visibility != DescriptionComment.VISIBILITY_PUBLISHED_BY_APPROVALS:
                    recipients.add(c.owner.email)
                else:
                    recipients = recipients.union(approvals_team)

        if (
                len(recipients) == 0
                and comment.visibility != DescriptionComment.VISIBILITY_APPROVALS_TEAM
        ):
            recipients = recipients.union(approvals_team)

        # split comment string into words and search for @-style tags
        rgx = re.compile("([\w|@][\w']*\w|\w)")
        words = re.findall(rgx, comment.comment)

        tags = [w[1:] for w in words if w[0] == "@"]

        for tag in tags:
            if tag == "team" and owner.has_role("project_approver"):
                recipients = recipients.union(approvals_team)
            else:
                user: User = db.session.query(User).filter_by(username=tag).first()
                if user is not None:
                    recipients.add(user.email)

        if len(recipients) == 0:
            return

        project: ProjectDescription = comment.parent
        desc_project = project.parent

        template = EmailTemplate.find_template_(
            EmailTemplate.PROJECT_CONFIRMATION_NEW_COMMENT
        )
        workflow = EmailWorkflow.build_(
            name=f"New comment notification: {desc_project.name}",
            template=template,
            defer=timedelta(hours=1),
        )
        db.session.add(workflow)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({
                "proj": desc_project.name,
                "desc": project.label,
            }),
            body_payload=encode_email_payload({
                "comment": comment,
                "project": desc_project,
                "desc": project,
            }),
            recipient_list=list(recipients),
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 1
