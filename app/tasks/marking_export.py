#
# Created by David Seery on 29/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery task to export a MarkingEvent to an Excel workbook.

Two sheets may be produced:
  <label>_overview  — ConflationReport summary (only when conflation has been run)
  <label>_register  — Full workflow register (all workflows side by side)

The workbook is uploaded to the OBJECT_STORAGE_ASSETS bucket, wrapped in a
GeneratedAsset + DownloadCentreItem, and the requesting user is notified.
"""

from datetime import datetime, timedelta
from io import BytesIO

from flask import current_app, render_template_string, url_for
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
    GeneratedAsset,
    SubmissionRecord,
    SubmittingStudent,
    TaskRecord,
    User,
)
from ..models.markingevent import (
    ConflationReport,
    MarkingReport,
    MarkingWorkflow,
    MarkingEvent,
    SubmitterReport,
)
from ..shared.asset_tools import AssetUploadManager
from ..shared.excel import _normalize_excel_sheet_name
from ..shared.scratch import ScratchFileManager
from ..shared.workflow_logging import log_db_commit
from ..task_queue import progress_update
from .thumbnails import dispatch_thumbnail_task

_EXPORT_READY_TMPL = (
    "<div><strong>Your marking export for &ldquo;{{ event_name }}&rdquo; is now available.</strong></div>"
    '<div class="mt-2">You can find it in your '
    '<a href="{{ url_for(\'home.download_centre\') }}">Download Centre</a>.</div>'
)


def _make_asset(source_path, target_name, now, expiry, object_store, user):
    """Upload a scratch file to object storage and return a persisted GeneratedAsset."""
    asset = GeneratedAsset(
        timestamp=now,
        expiry=expiry,
        target_name=target_name,
        parent_asset_id=None,
        license_id=None,
    )
    size = source_path.stat().st_size
    with open(source_path, "rb") as fh:
        with AssetUploadManager(
            asset,
            data=BytesIO(fh.read()),
            storage=object_store,
            audit_data="marking_export.generate_marking_excel_report",
            length=size,
            mimetype=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        ):
            pass
    asset.grant_user(user)
    db.session.add(asset)
    db.session.flush()
    dispatch_thumbnail_task(asset)
    return asset


def register_marking_export_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def generate_marking_excel_report(self, event_id: int, user_id: int, task_id: str):
        """
        Build an Excel workbook for the given MarkingEvent and deliver it to the
        requesting user's Download Centre.
        """
        progress_update(task_id, TaskRecord.RUNNING, 5, "Loading database records...", autocommit=True)

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            event: MarkingEvent = db.session.query(MarkingEvent).filter_by(id=event_id).first()
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading records in generate_marking_excel_report",
                exc_info=exc,
            )
            progress_update(task_id, TaskRecord.FAILURE, 100, "Database error loading records.", autocommit=True)
            raise self.retry()

        if user is None or event is None:
            progress_update(task_id, TaskRecord.FAILURE, 100, "Could not find required records.", autocommit=True)
            return

        progress_update(task_id, TaskRecord.RUNNING, 15, "Building export data...", autocommit=True)

        try:
            import pandas as pd

            config = event.config
            abbr = getattr(config, "abbreviation", None) or "MKG"
            label = f"{abbr}_{event.name}"

            workflows = list(event.workflows.order_by(MarkingWorkflow.name))

            # ----------------------------------------------------------------
            # Collect unique SubmissionRecord IDs for this event
            # ----------------------------------------------------------------
            record_id_set = set()
            for wf in workflows:
                for sr in wf.submitter_reports:
                    record_id_set.add(sr.record_id)

            # Build lookups used for both sheets
            sr_lookup = {}   # (wf_id, record_id) -> SubmitterReport
            mr_lookup = {}   # sr_id -> [MarkingReport, ...] sorted by id

            for wf in workflows:
                for sr in wf.submitter_reports:
                    sr_lookup[(wf.id, sr.record_id)] = sr
                    mr_lookup[sr.id] = sorted(sr.marking_reports.all(), key=lambda m: m.id)

            # Max MarkingReports per workflow (for column alignment)
            wf_max_mr = {}
            for wf in workflows:
                max_mr = max(
                    (len(mr_lookup.get(sr.id, [])) for sr in wf.submitter_reports),
                    default=0,
                )
                wf_max_mr[wf.id] = max_mr

            # Load all SubmissionRecords sorted by student name
            from ..models.students import StudentData

            records = (
                db.session.query(SubmissionRecord)
                .filter(SubmissionRecord.id.in_(record_id_set))
                .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
                .join(StudentData, StudentData.id == SubmittingStudent.student_id)
                .join(User, User.id == StudentData.user_id)
                .order_by(User.last_name, User.first_name)
                .all()
            )

            # ----------------------------------------------------------------
            # Sheet 1: Overview (ConflationReports) — only if conflation done
            # ----------------------------------------------------------------
            has_conflation = event.conflation_reports.count() > 0
            overview_rows = []

            if has_conflation:
                target_names = list(event.targets_as_dict.keys())
                cr_lookup = {cr.submission_record_id: cr for cr in event.conflation_reports}

                for record in records:
                    cr: ConflationReport = cr_lookup.get(record.id)
                    student_user = record.owner.student.user
                    exam_number = record.owner.student.exam_number

                    cr_data = cr.conflation_report_as_dict if cr else {}

                    row = {
                        "Student": student_user.name,
                        "Exam Number": exam_number if exam_number is not None else "",
                        "Generated By": cr.generated_by.name if cr and cr.generated_by else "",
                        "Generated At": (
                            cr.generated_timestamp.strftime("%Y-%m-%d %H:%M")
                            if cr and cr.generated_timestamp
                            else ""
                        ),
                        "Is Stale": cr.is_stale if cr else "",
                        "Feedback Sent": cr.feedback_sent if cr else "",
                    }

                    for t in target_names:
                        row[f"Target: {t}"] = cr_data.get(t)

                    for wf in workflows:
                        sr = sr_lookup.get((wf.id, record.id))
                        row[f"{wf.name}: Grade"] = (
                            float(sr.grade) if sr and sr.grade is not None else None
                        )

                    overview_rows.append(row)

            progress_update(task_id, TaskRecord.RUNNING, 50, "Building register sheet...", autocommit=True)

            # ----------------------------------------------------------------
            # Sheet 2: Register (all workflows side-by-side)
            # ----------------------------------------------------------------
            register_rows = []

            for record in records:
                student_data = record.owner.student
                student_user = student_data.user

                row = {
                    "Student": student_user.name,
                    "Exam Number": (
                        student_data.exam_number
                        if student_data.exam_number is not None
                        else ""
                    ),
                }

                for wf in workflows:
                    sr: SubmitterReport = sr_lookup.get((wf.id, record.id))
                    pfx = wf.name

                    row[f"{pfx}: Grade"] = (
                        float(sr.grade) if sr and sr.grade is not None else None
                    )
                    row[f"{pfx}: Grade Generated By"] = (
                        sr.grade_generated_by.name
                        if sr and sr.grade_generated_by
                        else ""
                    )
                    row[f"{pfx}: Grade Generated At"] = (
                        sr.grade_generated_timestamp.strftime("%Y-%m-%d %H:%M")
                        if sr and sr.grade_generated_timestamp
                        else ""
                    )
                    row[f"{pfx}: Completed At"] = (
                        sr.completed_timestamp.strftime("%Y-%m-%d %H:%M")
                        if sr and sr.completed_timestamp
                        else ""
                    )
                    row[f"{pfx}: Signed Off By"] = (
                        sr.signed_off_by.name if sr and sr.signed_off_by else ""
                    )
                    row[f"{pfx}: Signed Off At"] = (
                        sr.signed_off_timestamp.strftime("%Y-%m-%d %H:%M")
                        if sr and sr.signed_off_timestamp
                        else ""
                    )

                    mrs = mr_lookup.get(sr.id, []) if sr else []
                    max_mr = wf_max_mr[wf.id]

                    for i in range(max_mr):
                        mr: MarkingReport = mrs[i] if i < len(mrs) else None
                        n = i + 1
                        row[f"{pfx}: Assessor {n} Grade"] = (
                            float(mr.grade) if mr and mr.grade is not None else None
                        )
                        row[f"{pfx}: Assessor {n} Name"] = (
                            mr.role.user.name
                            if mr and mr.role and mr.role.user
                            else ""
                        )
                        row[f"{pfx}: Assessor {n} Submitted At"] = (
                            mr.grade_submitted_timestamp.strftime("%Y-%m-%d %H:%M")
                            if mr and mr.grade_submitted_timestamp
                            else ""
                        )
                        row[f"{pfx}: Assessor {n} Signed Off By"] = (
                            mr.signed_off_by.user.name
                            if mr and mr.signed_off_by and mr.signed_off_by.user
                            else ""
                        )
                        row[f"{pfx}: Assessor {n} Signed Off At"] = (
                            mr.signed_off_timestamp.strftime("%Y-%m-%d %H:%M")
                            if mr and mr.signed_off_timestamp
                            else ""
                        )
                        row[f"{pfx}: Assessor {n} Feedback Submitted"] = (
                            mr.feedback_submitted if mr else ""
                        )

                    # Accepted moderator report (if any)
                    mod_report = sr.accepted_moderator_report if sr else None
                    row[f"{pfx}: Accepted Moderator Grade"] = (
                        float(mod_report.grade)
                        if mod_report and mod_report.grade is not None
                        else None
                    )
                    row[f"{pfx}: Accepted Moderator"] = (
                        mod_report.role.user.name
                        if mod_report and mod_report.role and mod_report.role.user
                        else ""
                    )

                register_rows.append(row)

            progress_update(task_id, TaskRecord.RUNNING, 70, "Writing Excel workbook...", autocommit=True)

            # ----------------------------------------------------------------
            # Write workbook and upload
            # ----------------------------------------------------------------
            now = datetime.now()
            expiry = now + timedelta(weeks=4)
            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
            stem = f"Marking_{label}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".xlsx") as mgr:
                with pd.ExcelWriter(mgr.path, engine="openpyxl") as writer:
                    if has_conflation and overview_rows:
                        pd.DataFrame(overview_rows).to_excel(
                            writer,
                            sheet_name=_normalize_excel_sheet_name(f"{label}_overview"),
                            index=False,
                        )
                    pd.DataFrame(register_rows).to_excel(
                        writer,
                        sheet_name=_normalize_excel_sheet_name(f"{label}_register"),
                        index=False,
                    )

                asset = _make_asset(mgr.path, stem, now, expiry, object_store, user)

            download_item = DownloadCentreItem._build(
                asset=asset,
                user=user,
                description=f"Marking register export: {event.name}",
            )
            db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL, event_name=event.name)
            user.post_message(message, "success", autocommit=False)

            log_db_commit(
                f"Stored marking Excel export for event '{event.name}' and notified user '{user.name}'",
                user=user,
                endpoint=self.name,
            )

        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in generate_marking_excel_report", exc_info=exc
            )
            progress_update(
                task_id, TaskRecord.FAILURE, 100, "Database error during export.", autocommit=True
            )
            raise self.retry()

        except Exception as exc:
            current_app.logger.exception(
                "Unexpected error in generate_marking_excel_report", exc_info=exc
            )
            progress_update(
                task_id, TaskRecord.FAILURE, 100, "Unexpected error during export.", autocommit=True
            )
            return

        progress_update(task_id, TaskRecord.SUCCESS, 100, "Export complete.", autocommit=True)

    return (generate_marking_excel_report,)
