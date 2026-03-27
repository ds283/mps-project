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

from celery.exceptions import Ignore
from flask import current_app, render_template_string
from sqlalchemy import asc
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
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
                self.update_state(
                    state="FAILURE",
                    meta={"msg": f"User #{user_id} not found"},
                )
                raise Ignore()

            pclass: Optional[ProjectClass] = None
            if pclass_id is not None:
                pclass = db.session.query(ProjectClass).filter_by(id=pclass_id).first()

            tenant: Optional[Tenant] = None
            if tenant_id is not None:
                tenant = db.session.query(Tenant).filter_by(id=tenant_id).first()

        except SQLAlchemyError as e:
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(
            state="STARTED", meta={"msg": "Querying workflow log entries"}
        )

        try:
            query = db.session.query(WorkflowLogEntry)

            if pclass is not None:
                query = query.filter(
                    WorkflowLogEntry.project_classes.any(ProjectClass.id == pclass.id)
                )
            elif tenant is not None:
                # Filter to entries that have at least one project class belonging to this tenant
                query = query.filter(
                    WorkflowLogEntry.project_classes.any(
                        ProjectClass.tenant_id == tenant.id
                    )
                )

            entries = query.order_by(asc(WorkflowLogEntry.timestamp)).all()

        except SQLAlchemyError as e:
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building Excel spreadsheet"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        def make_asset(source_path: Path, target_name: str) -> GeneratedAsset:
            asset = GeneratedAsset(
                timestamp=now,
                expiry=expiry,
                target_name=target_name,
                parent_asset_id=None,
                license_id=None,
            )

            size = source_path.stat().st_size

            with open(source_path, "rb") as f:
                with AssetUploadManager(
                        asset,
                        data=BytesIO(f.read()),
                        storage=object_store,
                        audit_data="workflow_log.export_workflow_log",
                        length=size,
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        validate_nonce=validate_nonce,
                ) as upload_mgr:
                    pass

            asset.grant_user(user)
            db.session.add(asset)
            db.session.flush()

            download_item: DownloadCentreItem = DownloadCentreItem._build(
                asset=asset,
                user=user,
                description="Workflow log export",
            )
            db.session.add(download_item)

            return asset

        try:
            import pandas as pd

            records = []
            for entry in entries:
                initiator_name = (
                    entry.initiator.name if entry.initiator is not None else ""
                )
                pclass_names = ", ".join(pc.name for pc in entry.project_classes)
                records.append(
                    {
                        "timestamp": entry.timestamp.strftime("%a %d %b %Y %H:%M:%S")
                        if entry.timestamp
                        else "",
                        "user": initiator_name,
                        "endpoint": entry.endpoint or "",
                        "project_classes": pclass_names,
                        "summary": entry.summary or "",
                    }
                )

            df = pd.DataFrame.from_records(
                records,
                columns=["timestamp", "user", "endpoint", "project_classes", "summary"],
            )

            label = ""
            if pclass is not None:
                label = f"_{pclass.abbreviation}"
            elif tenant is not None:
                label = f"_{tenant.abbreviation}"

            file_stem = f"WorkflowLog{label}-{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".xlsx") as mgr:
                output_path = mgr.path
                sheet_name = _normalize_excel_sheet_name("Workflow log")
                df.to_excel(output_path, sheet_name=sheet_name, index=False)
                xlsx_asset = make_asset(output_path, file_stem)

            # language=jinja2
            message_tmpl = """
            <div><strong>Your workflow log export is now available.</strong></div>
            <div class="mt-2">You can find it in your
            <a href="{{ url_for('home.download_centre') }}"
               onclick="setTimeout(location.reload.bind(location), 1)">Download Centre</a>.</div>
            """
            message = render_template_string(message_tmpl)
            user.post_message(message, "success", autocommit=False)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in export_workflow_log()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})
