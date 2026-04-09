#
# Created by David Seery on 07/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery tasks to export AI dashboard data to Excel or CSV.

Each task receives:
  - user_id         : int  — user to notify and attach the download to
  - record_ids      : list[int] — SubmissionRecord PKs to include
  - filename_stem   : str  — base filename without extension
  - description     : str  — human-readable description for the Download Centre item

The task builds a flat table, uploads the file to MinIO, creates a
GeneratedAsset + DownloadCentreItem, and posts an in-app notification.
"""

from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Optional

from flask import current_app, render_template_string
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
    GeneratedAsset,
    SubmissionRecord,
    User,
)
from ..shared.asset_tools import AssetUploadManager
from ..shared.excel import _normalize_excel_sheet_name
from ..shared.scratch import ScratchFileManager
from .thumbnails import dispatch_thumbnail_task

# ---------------------------------------------------------------------------
# Column definitions for the exported table
# ---------------------------------------------------------------------------

_COLUMNS = [
    "Record ID",
    "Academic Year",
    "Project Class",
    "Submission Period",
    "Analysis Complete",
    "MATTR",
    "MTLD",
    "Burstiness R",
    "CV",
    "Pages",
    "Words",
    "References",
    "MATTR Flag",
    "MTLD Flag",
    "Burstiness Flag",
    "CV Flag",
    "AI Concern",
    "Risk Flags (active)",
    "Supervision Grade (%)",
    "Report Grade (%)",
    "Presentation Grade (%)",
]

# ---------------------------------------------------------------------------
# Notification template
# ---------------------------------------------------------------------------

_EXPORT_READY_TMPL = """
<div><strong>Your AI dashboard export is now available.</strong></div>
<div class="mt-2">You can find it in your
<a href="{{ url_for('home.download_centre') }}">Download Centre</a>.</div>
"""


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------


def _build_row(record: SubmissionRecord) -> dict:
    """Extract a flat dict of export fields from one SubmissionRecord."""
    period = record.period
    config = period.config if period else None
    pclass = config.project_class if config else None

    year = config.year if config else None
    pclass_name = pclass.abbreviation if pclass else ""
    period_name = period.display_name if period else ""

    la = record.language_analysis_data
    metrics = la.get("metrics", {})
    flags = la.get("flags", {})

    def _float(val):
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    # Active (present and unresolved) risk factor keys
    active_rf = []
    rf_data = record.risk_factors_data
    for key, factor in rf_data.items():
        if factor.get("present", False) and not factor.get("resolved", False):
            active_rf.append(key)

    return {
        "Record ID": record.id,
        "Academic Year": f"{year}/{year + 1}" if year is not None else "",
        "Project Class": pclass_name,
        "Submission Period": period_name,
        "Analysis Complete": record.language_analysis_complete,
        "MATTR": _float(metrics.get("mattr")),
        "MTLD": _float(metrics.get("mtld")),
        "Burstiness R": _float(metrics.get("burstiness")),
        "CV": _float(metrics.get("sentence_cv")),
        "Pages": _float(la.get("_page_count")),
        "Words": _float(metrics.get("word_count")),
        "References": _float(metrics.get("reference_count")),
        "MATTR Flag": flags.get("mattr_flag", ""),
        "MTLD Flag": flags.get("mtld_flag", ""),
        "Burstiness Flag": flags.get("burstiness_flag", ""),
        "CV Flag": flags.get("sentence_cv_flag", ""),
        "AI Concern": flags.get("ai_concern", ""),
        "Risk Flags (active)": "; ".join(active_rf) if active_rf else "",
        "Supervision Grade (%)": _float(record.supervision_grade),
        "Report Grade (%)": _float(record.report_grade),
        "Presentation Grade (%)": _float(record.presentation_grade),
    }


def _load_and_build_rows(record_ids: List[int]) -> List[dict]:
    """Load SubmissionRecords in batches and build the export row list."""
    rows = []
    # Load in chunks to avoid very large IN clauses
    chunk_size = 200
    for start in range(0, len(record_ids), chunk_size):
        chunk = record_ids[start : start + chunk_size]
        records = (
            db.session.query(SubmissionRecord)
            .filter(SubmissionRecord.id.in_(chunk))
            .all()
        )
        # Preserve the order given by record_ids (stable for reproducible exports)
        id_to_rec = {r.id: r for r in records}
        for rid in chunk:
            rec = id_to_rec.get(rid)
            if rec is not None:
                rows.append(_build_row(rec))
    return rows


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def register_ai_dashboard_export_tasks(celery):

    # ------------------------------------------------------------------
    # Excel export
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def export_ai_dashboard_xlsx(
        self,
        user_id: int,
        record_ids: List[int],
        filename_stem: str,
        description: str,
    ):
        """
        Export AI dashboard data for the given SubmissionRecord IDs to an
        Excel workbook, upload it to MinIO, and notify the requesting user.
        """
        self.update_state(state="STARTED", meta={"msg": "Loading records"})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                raise Exception(f"User #{user_id} not found")
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading user in export_ai_dashboard_xlsx", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building export data"})

        try:
            rows = _load_and_build_rows(record_ids)
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError building rows in export_ai_dashboard_xlsx", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Writing Excel workbook"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        try:
            import pandas as pd

            df = pd.DataFrame(rows, columns=_COLUMNS)
            stem_ts = f"{filename_stem}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".xlsx") as mgr:
                df.to_excel(
                    mgr.path,
                    sheet_name=_normalize_excel_sheet_name("AI Dashboard"),
                    index=False,
                )

                asset = GeneratedAsset(
                    timestamp=now,
                    expiry=expiry,
                    target_name=stem_ts,
                    parent_asset_id=None,
                    license_id=None,
                )
                size = mgr.path.stat().st_size
                with open(mgr.path, "rb") as fh:
                    with AssetUploadManager(
                        asset,
                        data=BytesIO(fh.read()),
                        storage=object_store,
                        audit_data="ai_dashboard_export.export_ai_dashboard_xlsx",
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

                download_item = DownloadCentreItem._build(
                    asset=asset,
                    user=user,
                    description=description,
                )
                db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL)
            user.post_message(message, "success", autocommit=False)
            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in export_ai_dashboard_xlsx", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def export_ai_dashboard_csv(
        self,
        user_id: int,
        record_ids: List[int],
        filename_stem: str,
        description: str,
    ):
        """
        Export AI dashboard data for the given SubmissionRecord IDs to a CSV
        file, upload it to MinIO, and notify the requesting user.
        """
        self.update_state(state="STARTED", meta={"msg": "Loading records"})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                raise Exception(f"User #{user_id} not found")
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading user in export_ai_dashboard_csv", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building export data"})

        try:
            rows = _load_and_build_rows(record_ids)
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError building rows in export_ai_dashboard_csv", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Writing CSV file"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        try:
            import pandas as pd

            df = pd.DataFrame(rows, columns=_COLUMNS)
            stem_ts = f"{filename_stem}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".csv") as mgr:
                df.to_csv(mgr.path, index=False)

                asset = GeneratedAsset(
                    timestamp=now,
                    expiry=expiry,
                    target_name=stem_ts,
                    parent_asset_id=None,
                    license_id=None,
                )
                size = mgr.path.stat().st_size
                with open(mgr.path, "rb") as fh:
                    with AssetUploadManager(
                        asset,
                        data=BytesIO(fh.read()),
                        storage=object_store,
                        audit_data="ai_dashboard_export.export_ai_dashboard_csv",
                        length=size,
                        mimetype="text/csv",
                    ):
                        pass

                asset.grant_user(user)
                db.session.add(asset)
                db.session.flush()

                dispatch_thumbnail_task(asset)

                download_item = DownloadCentreItem._build(
                    asset=asset,
                    user=user,
                    description=description,
                )
                db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL)
            user.post_message(message, "success", autocommit=False)
            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in export_ai_dashboard_csv", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})

    return export_ai_dashboard_xlsx, export_ai_dashboard_csv
