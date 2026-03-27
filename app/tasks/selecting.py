#
# Created by David Seery on 2019-03-26.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from celery import states
from celery.exceptions import Ignore
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    ConfirmRequest,
    LiveProject,
    ProjectClassConfig,
    SelectingStudent,
    TaskRecord,
    User,
)
from ..shared.tasks import post_task_update_msg
from ..shared.workflow_logging import log_db_commit


def _reassign_liveprojects(item_list, dest_config):
    delete_items = set()

    for item in item_list:
        new_liveproject = dest_config.live_projects.filter_by(
            parent_id=item.liveproject.parent_id
        ).first()

        # delete record if no match; otherwise reassign
        if new_liveproject is None:
            delete_items.add(item)
        else:
            item.liveproject_id = new_liveproject.id

    # delete records that had no match
    for item in delete_items:
        db.session.delete(item)


def register_selecting_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def remove_new(self, config_id, faculty_id):
        if isinstance(config_id, str):
            config_id = int(config_id)

        removed = 0

        # find all unseen confirmation requests for liveprojects belonging to this configuration id
        try:
            unseen_confirmations: List[ConfirmRequest] = (
                db.session.query(ConfirmRequest)
                .join(LiveProject, LiveProject.id == ConfirmRequest.project_id)
                .filter(
                    LiveProject.config_id == config_id,
                    LiveProject.owner_id == faculty_id,
                    ConfirmRequest.state == ConfirmRequest.REQUESTED,
                    ConfirmRequest.viewed.is_not(True),
                )
                .all()
            )

            if len(unseen_confirmations) > 0:
                for confirm in unseen_confirmations:
                    confirm: ConfirmRequest
                    confirm.viewed = True
                    removed += 1

                log_db_commit(
                    f"Marked unseen confirmation requests as viewed for faculty id={faculty_id} on config id={config_id}",
                    endpoint=self.name,
                )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {
            "removed": removed,
            "msg": f"Marked {removed} confirmation requests as viewed",
        }

    @celery.task(bind=True, default_retry_delay=10)
    def move_selector(self, sel_id, dest_id, user_id):
        try:
            sel: SelectingStudent = (
                db.session.query(SelectingStudent).filter_by(id=sel_id).first()
            )
            dest_config: ProjectClassConfig = (
                db.session.query(ProjectClassConfig).filter_by(id=dest_id).first()
            )
            user: User = db.session.query(User).filter_by(id=user_id).first()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if sel is None:
            self.update_state(
                "FAILURE",
                meta={
                    "msg": f"Could not load SelectingStudent id={sel_id} from database"
                },
            )
            raise Ignore()

        if dest_config is None:
            self.update_state(
                "FAILURE",
                meta={
                    "msg": f"Could not load ProjectClassConfig id={dest_id} from database"
                },
            )
            raise Ignore()

        if user is None:
            self.update_date(
                "FAILURE",
                meta={"msg": f"Could not load User id={user_id} from database"},
            )
            raise Ignore()

        # # detach any matches of which this selector is a part; they won't make sense after the move
        sel.remove_matches()

        # # reassign selector
        sel.config_id = dest_config.id

        # walk through bookmarks
        _reassign_liveprojects(sel.custom_offers, dest_config)
        _reassign_liveprojects(sel.bookmarks, dest_config)
        _reassign_liveprojects(sel.selections, dest_config)

        sel.re_rank_bookmarks()
        sel.re_rank_selections()

        try:
            log_db_commit(
                f"Moved selector {sel.student.user.name} to project class config '{dest_config.name}'",
                user=user,
                student=sel.student,
                project_classes=dest_config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        user.post_message(
            'Selector "{name}" has been moved to project class "{pcl}".'.format(
                name=sel.student.user.name, pcl=dest_config.name
            ),
            "success",
            autocommit=True,
        )
        self.update_state(
            "SUCCESS",
            meta={"msg": "Successfully moved selector to new project class"},
        )
        return {"msg": "Successfully moved selector to new project class"}

    @celery.task(bind=True, default_retry_delay=10)
    def approve_outstanding_confirms(
        self, task_id: str, config_id: int, approver_id: int
    ):
        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            10,
            "Initializing task...",
        )

        try:
            config: ProjectClassConfig = (
                db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            post_task_update_msg(
                self,
                task_id,
                states.FAILURE,
                TaskRecord.FAILURE,
                0,
                f"Could not load specified ProjectClassConfig instance id={config_id}",
            )
            self.update_state(
                "FAILURE",
                meta={
                    "msg": f"Could not load specified ProjectClassConfig instance id={config_id}"
                },
            )
            return {
                "msg": f"Could not load specified ProjectClassConfig instance id={config_id}"
            }

        if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
        ):
            post_task_update_msg(
                self,
                task_id,
                states.FAILURE,
                TaskRecord.FAILURE,
                100,
                "Approval of all outstanding confirmation requests can be performed only after student choices have opened",
            )
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Approval of all outstanding confirmation requests can be performed only after student choices have opened"
                },
            )
            return {
                "msg": "Approval of all outstanding confirmation requests can be performed only after student choices have opened"
            }

        if (
            config.selector_lifecycle
            > ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
        ):
            post_task_update_msg(
                self,
                task_id,
                states.FAILURE,
                TaskRecord.FAILURE,
                100,
                "Approval of all outstanding confirmation requests can not be performed after matching has been completed",
            )
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Approval of all outstanding confirmation requests can not be performed after matching has been completed"
                },
            )
            return {
                "msg": "Approval of all outstanding confirmation requests can not be performed after matching has been completed"
            }

        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            20,
            "Building list of outstanding confirmation requests...",
        )

        outstanding: List[ConfirmRequest] = (
            db.session.query(ConfirmRequest)
            .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED)
            .join(LiveProject, LiveProject.id == ConfirmRequest.project_id)
            .filter(LiveProject.config_id == config.id)
        )

        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            50,
            "Approving outstanding confirmation requests...",
        )

        for req in outstanding:
            req: ConfirmRequest
            req.confirm(approver_id)

        try:
            log_db_commit(
                f"Approved all outstanding confirmation requests for '{config.name}'",
                user=approver_id,
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        post_task_update_msg(
            self,
            task_id,
            states.SUCCESS,
            TaskRecord.SUCCESS,
            100,
            "All confirmation requests have been processed",
        )
        self.update_state(
            "SUCCESS",
            meta={"msg": "All confirmation requests have been processed"},
        )
        return {"msg": "All confirmation requests have been processed"}

    @celery.task(bind=True, default_retry_delay=10)
    def delete_outstanding_confirms(self, task_id: str, config_id: int):
        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            10,
            "Initializing task...",
        )

        try:
            config: ProjectClassConfig = (
                db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            post_task_update_msg(
                self,
                task_id,
                states.FAILURE,
                TaskRecord.FAILURE,
                0,
                f"Could not load specified ProjectClassConfig instance id={config_id}",
            )
            self.update_state(
                "FAILURE",
                meta={
                    "msg": f"Could not load specified ProjectClassConfig instance id={config_id}"
                },
            )
            return {
                "msg": f"Could not load specified ProjectClassConfig instance id={config_id}"
            }

        if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
        ):
            post_task_update_msg(
                self,
                task_id,
                states.FAILURE,
                TaskRecord.FAILURE,
                100,
                "Deletion of all outstanding confirmation requests can be performed only after student choices have opened",
            )
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Deletion of all outstanding confirmation requests can be performed only after student choices have opened"
                },
            )
            return {
                "msg": "Deletion of all outstanding confirmation requests can be performed only after student choices have opened"
            }

        if (
            config.selector_lifecycle
            > ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
        ):
            post_task_update_msg(
                self,
                task_id,
                states.FAILURE,
                TaskRecord.FAILURE,
                100,
                "Deletion of all outstanding confirmation requests can not be performed after matching has been completed",
            )
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Deletion of all outstanding confirmation requests can not be performed after matching has been completed"
                },
            )
            return {
                "msg": "Deletion of all outstanding confirmation requests can not be performed after matching has been completed"
            }

        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            20,
            "Building list of outstanding confirmation requests...",
        )

        outstanding: List[ConfirmRequest] = (
            db.session.query(ConfirmRequest)
            .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED)
            .join(LiveProject, LiveProject.id == ConfirmRequest.project_id)
            .filter(LiveProject.config_id == config.id)
        )

        post_task_update_msg(
            self,
            task_id,
            states.STARTED,
            TaskRecord.RUNNING,
            50,
            "Removing outstanding confirmation requests...",
        )

        for req in outstanding:
            req: ConfirmRequest
            req.remove(notify_student=True, notify_owner=False)
            db.session.delete(req)

        try:
            log_db_commit(
                f"Deleted all outstanding confirmation requests for '{config.name}'",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        post_task_update_msg(
            self,
            task_id,
            states.SUCCESS,
            TaskRecord.SUCCESS,
            100,
            "All confirmation requests have been processed",
        )
        self.update_state(
            "SUCCESS",
            meta={"msg": "All confirmation requests have been processed"},
        )
        return {"msg": "All confirmation requests have been processed"}
