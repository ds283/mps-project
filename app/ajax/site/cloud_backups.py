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
_error_detail = """
{% if r.object_count_error and r.error_detail %}
    <span class="badge bg-danger"
          tabindex="0"
          data-bs-toggle="popover"
          data-bs-trigger="focus"
          data-bs-title="Error detail"
          data-bs-content="{{ r.error_detail[:400] }}"
          style="cursor: pointer;">
        <i class="fas fa-exclamation-triangle me-1"></i>{{ r.object_count_error }} error{{ 's' if r.object_count_error != 1 else '' }}
    </span>
{% endif %}
"""


def cloud_backups_data(records: List[ObjectStoreBackupRecord]):
    data = [
        {
            "timestamp": r.timestamp.strftime("%a %d %b %Y %H:%M:%S") if r.timestamp else "—",
            "run_id": f"<code>{r.run_id[:8]}</code>" if r.run_id else "—",
            "bucket": f'<span class="badge bg-secondary">{r.bucket_label or "—"}</span>',
            "total": str(r.object_count_total) if r.object_count_total is not None else "—",
            "uploaded": str(r.object_count_uploaded) if r.object_count_uploaded is not None else "0",
            "skipped": str(r.object_count_skipped) if r.object_count_skipped is not None else "0",
            "errors": render_template_string(_errors, r=r),
            "bytes": r.readable_bytes_uploaded,
            "status": render_template_string(_status_badge, r=r),
            "error_detail": render_template_string(_error_detail, r=r),
        }
        for r in records
    ]
    return data
