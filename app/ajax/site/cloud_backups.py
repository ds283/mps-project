#
# Created by David Seery on 25/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import render_template_string

from ...models.utilities import ObjectStoreBackupRecord


# language=jinja2
_errors = """
{% if r.object_count_error %}
    <span class="text-danger fw-bold">{{ r.object_count_error }}</span>
{% else %}
    0
{% endif %}
"""

# language=jinja2
_status_badge = """
{% if r.status == 1 %}
    <span class="badge bg-success">Success</span>
{% elif r.status == 3 %}
    <span class="badge bg-warning text-dark">Partial</span>
{% elif r.status == 2 %}
    <span class="badge bg-danger">Failed</span>
{% else %}
    <span class="badge bg-secondary">Running</span>
{% endif %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if r.status in (1, 3) %}
            <a class="dropdown-item d-flex gap-2 js-restore-bucket"
               href="{{ url_for('admin.cloud_backup_restore', record_id=r.id) }}"
               data-record-id="{{ r.id }}"
               data-run-id="{{ r.run_id[:8] if r.run_id else '' }}"
               data-bucket="{{ r.bucket_label or '' }}"
               data-timestamp="{{ r.timestamp.strftime('%a %d %b %Y %H:%M:%S') if r.timestamp else '' }}"
               data-restore-url="{{ url_for('admin.cloud_backup_restore', record_id=r.id) }}">
                <i class="fas fa-undo fa-fw"></i> Restore this bucket&hellip;
            </a>
            <a class="dropdown-item d-flex gap-2 js-restore-run"
               href="{{ url_for('admin.cloud_backup_restore_run', run_id=r.run_id) }}"
               data-run-id="{{ r.run_id[:8] if r.run_id else '' }}"
               data-timestamp="{{ r.timestamp.strftime('%a %d %b %Y %H:%M:%S') if r.timestamp else '' }}"
               data-restore-url="{{ url_for('admin.cloud_backup_restore_run', run_id=r.run_id) }}">
                <i class="fas fa-layer-group fa-fw"></i> Restore all from this run&hellip;
            </a>
        {% else %}
            <span class="dropdown-item text-muted">No restore actions available</span>
        {% endif %}
        {% if r.object_count_error and r.error_detail %}
            <div class="dropdown-divider"></div>
            <div class="px-3 py-2 small text-muted" style="max-width: 300px; white-space: normal;">
                {{ r.error_detail[:200] }}
            </div>
        {% endif %}
    </div>
</div>
"""


def cloud_backups_data(records: List[ObjectStoreBackupRecord]):
    data = [
        {
            "timestamp": r.timestamp.strftime("%a %d %b %Y %H:%M:%S") if r.timestamp else "—",
            "run_id": f"<code>{r.run_id[:8]}</code>" if r.run_id else "—",
            "bucket": f'<span class="badge bg-secondary">{r.bucket_label or "—"}</span>',
            "total": str(r.object_count_total) if r.object_count_total is not None else "—",
            "uploaded": str(r.object_count_uploaded) if r.object_count_uploaded is not None else "0",
            "errors": render_template_string(_errors, r=r),
            "bytes": r.readable_bytes_uploaded,
            "status": render_template_string(_status_badge, r=r),
            "menu": render_template_string(_menu, r=r),
        }
        for r in records
    ]
    return data
