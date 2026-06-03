#
# Created by David Seery on 02/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from datetime import datetime

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import ConflationReport, MarkingEvent
from ..shared.asset_tools import AssetCloudAdapter
from ..shared.canvas_api import (
    CanvasAPIError,
    build_api_url,
    make_session,
    push_grade_to_canvas,
    upload_submission_comment_file,
)
from ..shared.workflow_logging import log_db_commit


def register_canvas_push_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def push_cr_to_canvas(self, cr_id: int, grade_target: str):
        """
        Push a grade for a single ConflationReport to Canvas.
        Does NOT upload or attach the feedback PDF — that is handled separately
        by push_cr_feedback_to_canvas.

        Parameters
        ----------
        cr_id : int
            Primary key of the ConflationReport to push.
        grade_target : str
            Key in cr.conflation_report_as_dict to use as the grade value,
            e.g. "report".
        """
        # --- pre-flight: load ConflationReport ---
        try:
            cr: ConflationReport = db.session.query(ConflationReport).filter_by(id=cr_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if cr is None:
            current_app.logger.warning(f"push_cr_to_canvas: ConflationReport id={cr_id} not found")
            return

        if not cr.canvas_push_ready:
            current_app.logger.warning(
                f"push_cr_to_canvas: ConflationReport id={cr_id} not ready for Canvas push "
                f"(canvas not enabled, missing user id, or no grade data)"
            )
            return

        if grade_target not in cr.conflation_report_as_dict:
            current_app.logger.warning(
                f"push_cr_to_canvas: grade target '{grade_target}' not found in ConflationReport id={cr_id}"
            )
            return

        if cr.canvas_grade_pushed:
            current_app.logger.warning(
                f"push_cr_to_canvas: grade already pushed for ConflationReport id={cr_id}, skipping"
            )
            return

        # --- extract credentials from ORM before any API calls ---
        api_root = cr.submission_record.period.config.main_config.canvas_root_API
        api_token = cr.submission_record.period.config.canvas_login.canvas_API_token
        course_id = cr.submission_record.period.canvas_module_id
        assignment_id = cr.submission_record.period.canvas_assignment_id
        user_id = cr.submission_record.owner.canvas_user_id

        session = make_session(api_token)
        grade_value = cr.conflation_report_as_dict[grade_target]

        # --- push grade only — no file attachment ---
        try:
            push_grade_to_canvas(
                session,
                api_root,
                course_id,
                assignment_id,
                user_id,
                posted_grade=grade_value,
                file_ids=None,
            )
        except CanvasAPIError as e:
            current_app.logger.error(
                f"push_cr_to_canvas: Canvas API error pushing grade for ConflationReport "
                f"id={cr_id}: status={e.status_code}, body={e.response_body}"
            )
            raise self.retry(exc=e)

        # --- persist push state ---
        cr.canvas_grade_pushed = True
        cr.canvas_grade_push_timestamp = datetime.now()
        cr.canvas_grade_target = grade_target

        try:
            log_db_commit(
                f"Canvas push: grade pushed for ConflationReport id={cr_id} (target={grade_target})",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def push_cr_feedback_to_canvas(self, cr_id: int):
        """
        Upload the feedback PDF(s) for a single ConflationReport and attach them
        to the Canvas submission comment. Does NOT modify the grade.

        Safe to call after grades have been posted in Canvas, since it sends no
        submission[posted_grade] parameter — the existing grade is not disturbed.

        Parameters
        ----------
        cr_id : int
            Primary key of the ConflationReport whose feedback PDFs to upload.
        """
        # --- pre-flight: load ConflationReport ---
        try:
            cr: ConflationReport = db.session.query(ConflationReport).filter_by(id=cr_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if cr is None:
            current_app.logger.warning(
                f"push_cr_feedback_to_canvas: ConflationReport id={cr_id} not found"
            )
            return

        if not cr.canvas_push_ready:
            current_app.logger.warning(
                f"push_cr_feedback_to_canvas: ConflationReport id={cr_id} not ready for Canvas push"
            )
            return

        if not cr.canvas_grade_pushed:
            current_app.logger.warning(
                f"push_cr_feedback_to_canvas: grade not yet pushed for ConflationReport id={cr_id}; "
                f"feedback must not be uploaded before the grade"
            )
            return

        if cr.canvas_feedback_pushed:
            current_app.logger.warning(
                f"push_cr_feedback_to_canvas: feedback already pushed for ConflationReport id={cr_id}, skipping"
            )
            return

        # --- extract credentials from ORM before any API calls ---
        api_root = cr.submission_record.period.config.main_config.canvas_root_API
        api_token = cr.submission_record.period.config.canvas_login.canvas_API_token
        course_id = cr.submission_record.period.canvas_module_id
        assignment_id = cr.submission_record.period.canvas_assignment_id
        user_id = cr.submission_record.owner.canvas_user_id

        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        http_session = make_session(api_token)

        # --- upload feedback PDFs ---
        file_ids = []
        try:
            for report in cr.feedback_reports.all():
                adapter = AssetCloudAdapter(
                    report.asset,
                    object_store,
                    audit_data=f"push_cr_feedback_to_canvas: ConflationReport id={cr_id}",
                )
                pdf_bytes = adapter.get()
                file_id = upload_submission_comment_file(
                    http_session,
                    api_root,
                    course_id,
                    assignment_id,
                    user_id,
                    filename=report.asset.target_name,
                    file_bytes=pdf_bytes,
                )
                file_ids.append(file_id)
        except CanvasAPIError as e:
            current_app.logger.error(
                f"push_cr_feedback_to_canvas: Canvas API error uploading feedback PDF for "
                f"ConflationReport id={cr_id}: status={e.status_code}, body={e.response_body}"
            )
            raise self.retry(exc=e)

        # --- attach files via comment-only PUT — no submission[posted_grade] ---
        submission_url = build_api_url(
            api_root,
            f"api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}",
        )
        data = [("comment[file_ids][]", fid) for fid in file_ids]
        data.append(("comment[text_comment]", "Feedback document attached."))
        response = http_session.put(submission_url, data=data)
        if not response.ok:
            current_app.logger.error(
                f"push_cr_feedback_to_canvas: Canvas API error attaching files for "
                f"ConflationReport id={cr_id}: status={response.status_code}, "
                f"body={response.text[:500]}"
            )
            raise self.retry(
                exc=CanvasAPIError(
                    f"Failed to attach feedback PDF to Canvas submission for ConflationReport id={cr_id}",
                    status_code=response.status_code,
                    response_body=response.text[:500],
                )
            )

        # --- persist push state ---
        cr.canvas_file_ids = json.dumps(file_ids)
        cr.canvas_feedback_pushed = True
        cr.canvas_feedback_push_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Canvas push: feedback PDF uploaded for ConflationReport id={cr_id}",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def push_event_to_canvas(self, event_id: int, grade_target: str, mode: str = "grade"):
        """
        Fan out Canvas push tasks across all eligible ConflationReports in a MarkingEvent.

        Parameters
        ----------
        event_id : int
            Primary key of the MarkingEvent.
        grade_target : str
            Grade target name to push for each student (used only when mode="grade").
        mode : str
            "grade"    — dispatch push_cr_to_canvas for unpushed CRs
            "feedback" — dispatch push_cr_feedback_to_canvas for CRs where grade
                         is pushed but feedback is not
        """
        try:
            event: MarkingEvent = db.session.query(MarkingEvent).filter_by(id=event_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if event is None:
            current_app.logger.warning(f"push_event_to_canvas: MarkingEvent id={event_id} not found")
            return

        all_reports = event.conflation_reports.all()
        total = len(all_reports)
        n = 0

        if mode == "grade":
            for cr in all_reports:
                if cr.canvas_push_ready and not cr.canvas_grade_pushed and grade_target in cr.conflation_report_as_dict:
                    push_cr_to_canvas.apply_async(args=[cr.id, grade_target])
                    n += 1
            skipped = total - n
            current_app.logger.info(
                f"push_event_to_canvas: dispatched grade push for {n} of {total} ConflationReports "
                f"in MarkingEvent id={event_id} (grade_target='{grade_target}', {skipped} skipped)"
            )
        elif mode == "feedback":
            for cr in all_reports:
                if cr.canvas_push_ready and cr.canvas_grade_pushed and not cr.canvas_feedback_pushed:
                    push_cr_feedback_to_canvas.apply_async(args=[cr.id])
                    n += 1
            skipped = total - n
            current_app.logger.info(
                f"push_event_to_canvas: dispatched feedback push for {n} of {total} ConflationReports "
                f"in MarkingEvent id={event_id} ({skipped} skipped)"
            )
        else:
            current_app.logger.warning(
                f"push_event_to_canvas: unknown mode '{mode}' for MarkingEvent id={event_id}"
            )
