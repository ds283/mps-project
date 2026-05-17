#
# Created by David Seery on 17/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery task to export SubmissionRole assignment data to an Excel workbook.

The workbook contains one worksheet per ProjectClass (named by abbreviation)
and a summary worksheet with per-faculty CATS totals.
"""

from datetime import datetime, timedelta
from io import BytesIO
from typing import List

from flask import current_app, render_template_string
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
    FacultyData,
    GeneratedAsset,
    ProjectClass,
    ProjectClassConfig,
    SubmissionRole,
    SubmissionRoleTypesMixin,
    TaskRecord,
    User,
)
from ..shared.asset_tools import AssetUploadManager
from ..shared.excel import _normalize_excel_sheet_name
from ..shared.scratch import ScratchFileManager
from ..shared.sqlalchemy import get_count
from ..task_queue import progress_update
from .thumbnails import dispatch_thumbnail_task

_EXPORT_READY_TMPL = """
<div><strong>Your allocation export is now available.</strong></div>
<div class="mt-2">You can find it in your
<a href="{{ url_for('home.download_centre') }}">Download Centre</a>.</div>
"""

# Column headers for per-pclass worksheets
_ROLE_COLUMNS = [
    "faculty_last_name",
    "faculty_first_name",
    "faculty_full_name",
    "project_class_name",
    "role",
    "role_type",
    "student_last_name",
    "student_first_name",
    "project_name",
]

# Column headers for the summary worksheet
_SUMMARY_COLUMNS = [
    "faculty_last_name",
    "faculty_first_name",
    "faculty_full_name",
    "total_supervising",
    "total_marking",
    "total_moderating",
    "total_CATS",
]


def _role_type_str(role_int: int) -> str:
    if role_int in (
        SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
        SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
    ):
        return "supervisor"
    return SubmissionRoleTypesMixin._role_id.get(role_int, str(role_int))


def _build_role_rows(config: ProjectClassConfig) -> List[list]:
    rows = []
    pclass_name = config.project_class.abbreviation
    for period in config.periods:
        for sub in period.submissions:
            student = sub.owner
            if student is None:
                continue
            student_user = student.student.user if student.student else None
            student_last = student_user.last_name if student_user else ""
            student_first = student_user.first_name if student_user else ""
            project_name = sub.project.name if sub.project else ""
            for role in sub.roles:
                role: SubmissionRole
                if role.role == SubmissionRoleTypesMixin.ROLE_STUDENT:
                    continue
                fac_user = role.user
                if fac_user is None:
                    continue
                rows.append(
                    [
                        fac_user.last_name,
                        fac_user.first_name,
                        fac_user.name,
                        pclass_name,
                        role.role_as_str,
                        _role_type_str(role.role),
                        student_last,
                        student_first,
                        project_name,
                    ]
                )
    return rows


def _build_summary_rows(configs: List[ProjectClassConfig]) -> List[list]:
    # Collect unique FacultyData that appear in any SubmissionRole across all configs
    seen: dict = {}
    for config in configs:
        for period in config.periods:
            for sub in period.submissions:
                for role in sub.roles:
                    if role.role == SubmissionRoleTypesMixin.ROLE_STUDENT:
                        continue
                    fac_user = role.user
                    if fac_user is None:
                        continue
                    if fac_user.id not in seen and fac_user.faculty_data is not None:
                        seen[fac_user.id] = fac_user.faculty_data

    rows = []
    for fac in seen.values():
        fac: FacultyData
        fac_user = fac.user

        total_supv = 0
        total_mark = 0
        total_mod = 0
        total_cats = 0.0

        for config in configs:
            supv_cats, mark_cats, mod_cats, pres_cats = fac.CATS_assignment(config)
            total_cats += supv_cats + mark_cats + mod_cats + pres_cats

            if config.uses_supervisor:
                total_supv += get_count(fac.supervisor_assignments(config=config))
            if config.uses_marker:
                total_mark += get_count(fac.marker_assignments(config=config))
            if config.uses_moderator:
                total_mod += get_count(fac.moderator_assignments(config=config))

        rows.append(
            [
                fac_user.last_name,
                fac_user.first_name,
                fac_user.name,
                total_supv,
                total_mark,
                total_mod,
                total_cats,
            ]
        )

    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def register_allocation_export_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def export_allocation_xlsx(self, config_ids: List[int], user_id: int, task_id: str):
        self.update_state(state="STARTED", meta={"msg": "Loading records"})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                raise Exception(f"User #{user_id} not found")
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading user in export_allocation_xlsx", exc_info=exc
            )
            raise self.retry()

        progress_update(
            task_id, TaskRecord.RUNNING, 10, "Loading project class configs...", autocommit=True
        )

        try:
            configs: List[ProjectClassConfig] = (
                db.session.query(ProjectClassConfig)
                .filter(ProjectClassConfig.id.in_(config_ids))
                .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
                .order_by(ProjectClass.name)
                .all()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading configs in export_allocation_xlsx", exc_info=exc
            )
            raise self.retry()

        progress_update(
            task_id, TaskRecord.RUNNING, 30, "Building role data...", autocommit=True
        )

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        stem_ts = f"allocation_export_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

        try:
            import pandas as pd

            with ScratchFileManager(suffix=".xlsx") as mgr:
                with pd.ExcelWriter(mgr.path, engine="openpyxl") as writer:
                    for config in configs:
                        rows = _build_role_rows(config)
                        sheet_name = _normalize_excel_sheet_name(
                            config.project_class.abbreviation
                        )
                        df = pd.DataFrame(rows, columns=_ROLE_COLUMNS)
                        df.to_excel(writer, sheet_name=sheet_name, index=False)

                    progress_update(
                        task_id,
                        TaskRecord.RUNNING,
                        70,
                        "Building summary sheet...",
                        autocommit=True,
                    )
                    summary_rows = _build_summary_rows(configs)
                    summary_df = pd.DataFrame(summary_rows, columns=_SUMMARY_COLUMNS)
                    summary_df.to_excel(writer, sheet_name="Summary", index=False)

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
                        audit_data="allocation_export.export_allocation_xlsx",
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
                    description=f"Allocation export ({now.strftime('%Y-%m-%d %H:%M')})",
                )
                db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL)
            user.post_message(message, "success", autocommit=False)
            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in export_allocation_xlsx", exc_info=exc
            )
            raise self.retry()

        progress_update(
            task_id, TaskRecord.RUNNING, 100, "Export complete", autocommit=True
        )
        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})
