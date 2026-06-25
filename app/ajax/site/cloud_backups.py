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
_status_badge = """
{% if r.status == 0 %}
    <span class="badge bg-warning text-dark">Running</span>
{% elif r.status == 1 %}
    <span class="badge bg-success">Success</span>
{% elif r.status == 2 %}
    <span class="badge bg-danger">Failed</span>
{% elif r.status == 3 %}
    <span class="badge bg-warning text-dark">Partial</span>
{% else %}
    <span class="badge bg-secondary">Unknown</span>
{% endif %}
{% if r.error_detail %}
    <div class="mt-1 small text-muted">{{ r.object_count_error }} error(s)</div>
{% endif %}
"""

# language=jinja2
_bucket_cell = """
<div class="small fw-semibold">{{ r.bucket_label or '—' }}</div>
<div class="mt-1 small text-muted">run {{ r.run_id[:8] if r.run_id else '—' }}</div>
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if r.status in (1, 3) %}
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('admin.cloud_backup_restore', record_id=r.id) }}">
                <i class="fas fa-undo fa-fw"></i> Restore this bucket&hellip;
            </a>
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('admin.cloud_backup_restore_run', run_id=r.run_id) }}">
                <i class="fas fa-layer-group fa-fw"></i> Restore all buckets in this run&hellip;
            </a>
        {% else %}
            <span class="dropdown-item text-muted">No restore actions available</span>
        {% endif %}
    </div>
</div>
"""


def cloud_backups_data(records: List[ObjectStoreBackupRecord]):
    data = [
        {
            "timestamp": r.timestamp.strftime("%a %d %b %Y %H:%M:%S") if r.timestamp else "—",
            "run_id": r.run_id[:8] if r.run_id else "—",
            "bucket": render_template_string(_bucket_cell, r=r),
            "total": str(r.object_count_total) if r.object_count_total is not None else "—",
            "uploaded": str(r.object_count_uploaded) if r.object_count_uploaded is not None else "—",
            "errors": str(r.object_count_error) if r.object_count_error is not None else "—",
            "bytes": r.readable_bytes_uploaded,
            "status": render_template_string(_status_badge, r=r),
            "menu": render_template_string(_menu, r=r),
        }
        for r in records
    ]
    return data
