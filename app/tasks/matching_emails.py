#
# Created by ds283$ on 08/06/2021$.
# Copyright (c) 2021$ University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283$ <$>
#

from datetime import datetime, timedelta
from distutils.util import strtobool
from typing import List

from celery import chain, group
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    FacultyData,
    MatchingAttempt,
    MatchingRecord,
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    TaskRecord,
    Tenant,
    User,
)
from ..models.emails import encode_email_payload
from ..task_queue import progress_update


def register_matching_email_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def publish_to_selectors(self, match_id, user_id, task_id):
        try:
            record: MatchingAttempt = (
                db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingAttempt record from database"},
            )
            raise self.retry()

        progress_update(
            task_id,
            TaskRecord.RUNNING,
            10,
            "Building list of student selectors...",
            autocommit=True,
        )

        recipients = set()
        for mrec in record.records:
            recipients.add(mrec.selector_id)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        task = chain(
            group(
                publish_email_to_selector.si(
                    match_id, sel_id, not bool(record.selected)
                )
                for sel_id in recipients
            ),
            notify.s(user_id, "{n} email notification{pl} issued", "info"),
            publish_to_selectors_finalize.si(match_id, task_id),
        )

        return self.replace(task)

    @celery.task(bind=True)
    def publish_to_selectors_finalize(self, match_id, task_id):
        try:
            record: MatchingAttempt = (
                db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingAttempt record from database"},
            )
            raise self.retry()

        progress_update(
            task_id,
            TaskRecord.SUCCESS,
            100,
            "Notification emails to selectors complete",
            autocommit=False,
        )

        # record timestamp for when emails were sent
        if record.selected:
            record.final_to_selectors = datetime.now()
        else:
            record.draft_to_selectors = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 0

    @celery.task(bind=True, default_retry_delay=30)
    def publish_email_to_selector(self, match_id, sel_id, is_draft):
        if isinstance(is_draft, str):
            is_draft = strtobool(is_draft)

        try:
            record: MatchingAttempt = (
                db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            )
            matches: List[MatchingRecord] = (
                db.session.query(MatchingRecord)
                .filter_by(matching_id=match_id, selector_id=sel_id)
                .order_by(MatchingRecord.submission_period)
                .all()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingAttempt record from database"},
            )
            raise self.retry()

        if len(matches) == 0:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingRecord record from database"},
            )
            raise self.retry()

        user: User = matches[0].selector.student.user
        config: ProjectClassConfig = matches[0].selector.config
        pclass: ProjectClass = config.project_class

        template_type = (
            EmailTemplate.MATCHING_DRAFT_NOTIFY_STUDENTS
            if is_draft
            else EmailTemplate.MATCHING_FINAL_NOTIFY_STUDENTS
        )
        template = EmailTemplate.find_template_(template_type, pclass=pclass)
        workflow = EmailWorkflow.build_(
            name=f"Matching selector notification: {config.name} — {user.name}",
            template=template,
            defer=timedelta(hours=1),
            pclasses=[pclass],
        )
        db.session.add(workflow)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({
                "name": config.name,
                "yra": record.submit_year_a,
                "yrb": record.submit_year_b,
            }),
            body_payload=encode_email_payload({
                "user": user,
                "config": config,
                "pclass": pclass,
                "attempt": record,
                "matches": matches,
                "number": len(matches),
            }),
            recipient_list=[user.email],
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

    @celery.task(bind=True, default_retry_delay=30)
    def publish_to_supervisors(self, match_id, user_id, task_id):
        try:
            record: MatchingAttempt = (
                db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingAttempt record from database"},
            )
            raise self.retry()

        progress_update(
            task_id,
            TaskRecord.RUNNING,
            10,
            "Building list of project supervisors...",
            autocommit=True,
        )

        recipients = set()
        for fac in record.supervisors:
            recipients.add(fac.id)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        task = chain(
            group(
                publish_email_to_supervisor.si(
                    match_id, fac_id, not bool(record.selected)
                )
                for fac_id in recipients
            ),
            notify.s(user_id, "{n} email notification{pl} issued", "info"),
            publish_to_supervisors_finalize.si(match_id, task_id),
        )

        return self.replace(task)

    @celery.task(bind=True)
    def publish_to_supervisors_finalize(self, match_id, task_id):
        try:
            record: MatchingAttempt = (
                db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingAttempt record from database"},
            )
            raise self.retry()

        progress_update(
            task_id,
            TaskRecord.SUCCESS,
            100,
            "Notification emails to faculty complete",
            autocommit=False,
        )

        # record timestamp for when emails were sent
        if record.selected:
            record.final_to_supervisors = datetime.now()
        else:
            record.draft_to_supervisors = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 0

    @celery.task(bind=True, default_retry_delay=30)
    def publish_email_to_supervisor(self, match_id, fac_id, is_draft):
        if isinstance(is_draft, str):
            is_draft = strtobool(is_draft)

        try:
            record: MatchingAttempt = (
                db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            )
            fac: FacultyData = (
                db.session.query(FacultyData).filter_by(id=fac_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load MatchingAttempt record from database"},
            )
            raise self.retry()

        if fac is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load FacultyData record from database"},
            )
            raise self.retry()

        user: User = fac.user
        matches: List[MatchingRecord] = record.get_supervisor_records(fac.id).all()

        matched_ids_by_pclass = {}
        pclasses = set()
        tenants = set()
        convenors = set()
        for match in matches:
            sel: SelectingStudent = match.selector
            config: ProjectClassConfig = sel.config
            pclass: ProjectClass = config.project_class

            pclass_id = pclass.id
            match_list = matched_ids_by_pclass.setdefault(pclass_id, [])
            match_list.append(match)

            pclasses.add(pclass)
            convenors.add(config.convenor)
            tenants.add(pclass.tenant)

        workflow_pclasses = list(pclasses)

        email_pclass = None
        email_tenant = None
        if len(pclasses) == 1:
            email_pclass: ProjectClass = pclasses.pop()
            email_tenant: Tenant = email_pclass.tenant

        elif len(tenants) == 1:
            email_tenant: Tenant = tenants.pop()

        if is_draft:
            template_type = (
                EmailTemplate.MATCHING_DRAFT_NOTIFY_FACULTY
                if len(matches) > 0
                else EmailTemplate.MATCHING_DRAFT_UNNEEDED_FACULTY
            )
        else:
            template_type = (
                EmailTemplate.MATCHING_FINAL_NOTIFY_FACULTY
                if len(matches) > 0
                else EmailTemplate.MATCHING_FINAL_UNNEEDED_FACULTY
            )

        template = EmailTemplate.find_template_(
            template_type, pclass=email_pclass, tenant=email_tenant
        )
        workflow = EmailWorkflow.build_(
            name=f"Matching supervisor notification: {record.name} — {user.name}",
            template=template,
            defer=timedelta(hours=1),
            pclasses=workflow_pclasses,
        )
        db.session.add(workflow)
        db.session.flush()

        if len(matches) > 0:
            body_payload = encode_email_payload({
                "user": user,
                "fac": fac,
                "attempt": record,
                "matches": matched_ids_by_pclass,
                "convenors": list(convenors),
                "yra": record.submit_year_a,
                "yrb": record.submit_year_b,
            })
        else:
            body_payload = encode_email_payload({
                "user": user,
                "fac": fac,
                "attempt": record,
                "yra": record.submit_year_a,
                "yrb": record.submit_year_b,
            })

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({
                "yra": record.submit_year_a,
                "yrb": record.submit_year_b,
            }),
            body_payload=body_payload,
            recipient_list=[user.email],
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
