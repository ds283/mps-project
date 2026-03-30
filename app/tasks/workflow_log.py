#
# Created by David Seery on 26/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

from flask import current_app, render_template_string
from sqlalchemy import asc
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
    FacultyData,
    GeneratedAsset,
    ProjectClass,
    Tenant,
    User,
    WorkflowLogEntry,
)
from ..shared.asset_tools import AssetUploadManager
from ..shared.excel import _normalize_excel_sheet_name
from ..shared.scratch import ScratchFileManager
from ..shared.security import validate_nonce
from .thumbnails import dispatch_thumbnail_task


def register_workflow_log_tasks(celery):
    @celery.task(bind=True)
    def prune_workflow_log(self, max_rows=50000):
        """
        Prune the workflow log to at most max_rows rows, deleting the oldest entries first.

        The default of 50,000 rows corresponds to approximately 35 MB of storage
        (based on an estimated ~700 bytes per entry including the M2M project-class rows).
        """
        self.update_state(state="STARTED")

        try:
            total = db.session.query(WorkflowLogEntry).count()

            if total > max_rows:
                excess = total - max_rows

                # Find the timestamp of the (excess)-th oldest entry — everything at or
                # before this timestamp will be deleted.
                cutoff_entry = (
                    db.session.query(WorkflowLogEntry)
                    .order_by(asc(WorkflowLogEntry.timestamp))
                    .offset(excess - 1)
                    .limit(1)
                    .one_or_none()
                )

                if cutoff_entry is not None:
                    cutoff_ts = cutoff_entry.timestamp

                    # Delete all entries older than (or equal to) the cutoff timestamp.
                    # We delete by iterating so that SQLAlchemy cascades the M2M association
                    # rows in workflow_log_to_pclass correctly.
                    to_delete = (
                        db.session.query(WorkflowLogEntry)
                        .filter(WorkflowLogEntry.timestamp <= cutoff_ts)
                        .all()
                    )
                    for entry in to_delete:
                        db.session.delete(entry)

                    db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in prune_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="FINISHED")

    def _get_workflow_log_entries(
            user: User, pclass_id: Optional[int], tenant_id: Optional[int]
    ):
        """
        Query WorkflowLogEntry rows, applying both the user's access scope (based on role)
        and the requested pclass/tenant filter.  Returns (entries, label_suffix).
        """
        pclass: Optional[ProjectClass] = None
        if pclass_id is not None:
            pclass = db.session.query(ProjectClass).filter_by(id=pclass_id).first()

        tenant: Optional[Tenant] = None
        if tenant_id is not None:
            tenant = db.session.query(Tenant).filter_by(id=tenant_id).first()

        query = db.session.query(WorkflowLogEntry)

        # Scope restriction based on the exporting user's role
        is_root = user.has_role("root")
        is_admin = user.has_role("admin")

        if not is_root:
            if is_admin:
                user_tenant_ids = [t.id for t in user.tenants]
                query = query.filter(
                    WorkflowLogEntry.project_classes.any(
                        ProjectClass.tenant_id.in_(user_tenant_ids)
                    )
                )
            else:  # convenor
                fd = db.session.query(FacultyData).filter_by(id=user.id).first()
                if fd is not None:
                    convenor_pclass_ids = [pc.id for pc in fd.convenor_for] + [
                        pc.id for pc in fd.coconvenor_for
                    ]
                else:
                    convenor_pclass_ids = []
                query = query.filter(
                    WorkflowLogEntry.project_classes.any(
                        ProjectClass.id.in_(convenor_pclass_ids)
                    )
                )

        # Apply the requested filter (pclass takes priority over tenant)
        if pclass is not None:
            query = query.filter(
                WorkflowLogEntry.project_classes.any(ProjectClass.id == pclass.id)
            )
        elif tenant is not None:
            query = query.filter(
                WorkflowLogEntry.project_classes.any(
                    ProjectClass.tenant_id == tenant.id
                )
            )

        entries = query.order_by(asc(WorkflowLogEntry.timestamp)).all()

        label = ""
        if pclass is not None:
            label = f"_{pclass.abbreviation}"
        elif tenant is not None:
            label = f"_{tenant.name.replace(' ', '_')}"

        return entries, label

    def _build_workflow_log_records(entries):
        """Build a list of dicts from WorkflowLogEntry objects for DataFrame construction."""
        records = []
        for entry in entries:
            initiator_name = entry.initiator.name if entry.initiator is not None else ""
            student_name = entry.student.user.name if entry.student is not None else ""
            pclass_names = ", ".join(pc.name for pc in entry.project_classes)
            records.append(
                {
                    "timestamp": entry.timestamp.strftime("%a %d %b %Y %H:%M:%S")
                    if entry.timestamp
                    else "",
                    "user": initiator_name,
                    "student": student_name,
                    "endpoint": entry.endpoint or "",
                    "project_classes": pclass_names,
                    "summary": entry.summary or "",
                }
            )
        return records

    _WORKFLOW_LOG_COLUMNS = [
        "timestamp",
        "user",
        "student",
        "endpoint",
        "project_classes",
        "summary",
    ]

    # language=jinja2
    _WORKFLOW_LOG_READY_TMPL = """
    <div><strong>Your workflow log export is now available.</strong></div>
    <div class="mt-2">You can find it in your
    <a href="{{ url_for('home.download_centre') }}">Download Centre</a>.</div>
    """

    @celery.task(bind=True, default_retry_delay=30)
    def export_workflow_log(
            self,
            user_id: int,
            pclass_id: Optional[int] = None,
            tenant_id: Optional[int] = None,
    ):
        """
        Export the workflow log (optionally filtered by project class or tenant) to an Excel
        spreadsheet, store it as a GeneratedAsset, and add a DownloadCentreItem for the user.
        """
        self.update_state(
            state="STARTED", meta={"msg": "Preparing workflow log export"}
        )

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                msg = f"User #{user_id} not found"
                current_app.logger.error(msg)
                raise Exception(msg)
        except SQLAlchemyError as e:
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(
            state="STARTED", meta={"msg": "Querying workflow log entries"}
        )

        try:
            entries, label = _get_workflow_log_entries(user, pclass_id, tenant_id)
        except SQLAlchemyError as e:
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building Excel spreadsheet"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        try:
            import pandas as pd

            records = _build_workflow_log_records(entries)
            df = pd.DataFrame.from_records(records, columns=_WORKFLOW_LOG_COLUMNS)

            file_stem = f"WorkflowLog{label}-{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".xlsx") as mgr:
                output_path = mgr.path
                sheet_name = _normalize_excel_sheet_name("Workflow log")
                df.to_excel(output_path, sheet_name=sheet_name, index=False)

                asset = GeneratedAsset(
                    timestamp=now,
                    expiry=expiry,
                    target_name=file_stem,
                    parent_asset_id=None,
                    license_id=None,
                )
                size = output_path.stat().st_size
                with open(output_path, "rb") as f:
                    with AssetUploadManager(
                        asset,
                        data=BytesIO(f.read()),
                        storage=object_store,
                        audit_data="workflow_log.export_workflow_log",
                        length=size,
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        validate_nonce=validate_nonce,
                    ):
                        pass

                asset.grant_user(user)
                db.session.add(asset)
                db.session.flush()

                dispatch_thumbnail_task(asset)

                download_item = DownloadCentreItem._build(
                    asset=asset, user=user, description="Workflow log export"
                )
                db.session.add(download_item)

            message = render_template_string(_WORKFLOW_LOG_READY_TMPL)
            user.post_message(message, "success", autocommit=False)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})

    @celery.task(bind=True, default_retry_delay=30)
    def export_workflow_log_csv(
            self,
            user_id: int,
            pclass_id: Optional[int] = None,
            tenant_id: Optional[int] = None,
    ):
        """
        Export the workflow log (optionally filtered by project class or tenant) to a CSV file,
        store it as a GeneratedAsset, and add a DownloadCentreItem for the user.
        """
        self.update_state(
            state="STARTED", meta={"msg": "Preparing workflow log CSV export"}
        )

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                msg = f"User #{user_id} not found"
                current_app.logger.error(msg)
                raise Exception(msg)
        except SQLAlchemyError as e:
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log_csv()", exc_info=e
            )
            raise self.retry()

        self.update_state(
            state="STARTED", meta={"msg": "Querying workflow log entries"}
        )

        try:
            entries, label = _get_workflow_log_entries(user, pclass_id, tenant_id)
        except SQLAlchemyError as e:
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log_csv()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building CSV file"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        try:
            import pandas as pd

            records = _build_workflow_log_records(entries)
            df = pd.DataFrame.from_records(records, columns=_WORKFLOW_LOG_COLUMNS)

            file_stem = f"WorkflowLog{label}-{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".csv") as mgr:
                output_path = mgr.path
                df.to_csv(output_path, index=False)

                asset = GeneratedAsset(
                    timestamp=now,
                    expiry=expiry,
                    target_name=file_stem,
                    parent_asset_id=None,
                    license_id=None,
                )
                size = output_path.stat().st_size
                with open(output_path, "rb") as f:
                    with AssetUploadManager(
                            asset,
                            data=BytesIO(f.read()),
                            storage=object_store,
                            audit_data="workflow_log.export_workflow_log_csv",
                            length=size,
                            mimetype="text/csv",
                            validate_nonce=validate_nonce,
                    ):
                        pass

                asset.grant_user(user)
                db.session.add(asset)
                db.session.flush()

                dispatch_thumbnail_task(asset)

                download_item = DownloadCentreItem._build(
                    asset=asset, user=user, description="Workflow log CSV export"
                )
                db.session.add(download_item)

            message = render_template_string(_WORKFLOW_LOG_READY_TMPL)
            user.post_message(message, "success", autocommit=False)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log_csv()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})
