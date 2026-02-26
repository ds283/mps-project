#
# Created by David Seery on 26/02/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

import app.shared.cloud_object_store.bucket_types as buckets

# language=jinja2
_target = """
{% if target_name is not none %}
    <a class="text-secondary text-decoration-none fw-semibold" href="{{ url_for('admin.download_generated_asset', asset_id=asset.id) }}">{{ target_name|truncate(40) }}</a>
{% else %}
    <div class="text-secondary"><i class="fas fa-ban"></i> None</div>
{% endif %}
"""

# language=jinja2
_type_badge = """
{% if asset_type == 'GeneratedAsset' %}
    <span class="text-primary fw-semibold">Generated</span>
{% elif asset_type == 'TemporaryAsset' %}
    <span class="text-primary fw-semibold">Temporary</span>
{% elif asset_type == 'SubmittedAsset' %}
    <span class="text-primary fw-semibold">Submitted</span>
{% else %}
    <div class="text-secondary small"><i class="fas fa-ban"></i> Unknown</div>
{% endif %}
"""

# language=jinja2
_license = """
{% if license is not none %}
    {{ simple_label(license.make_label()) }}
{% else %}
    <div class="text-secondary small"><i class="fas fa-ban"></i> None</div>
{% endif %}
"""

# language=jinja2
_expiry = """
{% if expiry is not none %}
    <div class="text-primary small"><i class="fas fa-calendar"></i> {{ expiry.strftime("%a %d %b %Y %H:%M:%S") }}</div>
{% else %}
    <div class="text-secondary small"><i class="fas fa-ban"></i> No expiry</div>
{% endif %}
"""

# language=jinja2
_flags = """
{% if encrypted %}
    <span class="badge bg-info"><i class="fas fa-lock"></i> Encrypted</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-lock-open"></i> Not encrypted</span>
{% endif %}
{% if compressed %}
    <span class="badge bg-info"><i class="fas fa-compress"></i> Compressed</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-expand"></i> Not compressed</span>
{% endif %}
"""

# language=jinja2
_bucket = """
{% if bucket == ASSETS_BUCKET %}
    <span class="badge bg-secondary">Assets</span>
{% elif bucket == BACKUP_BUCKET %}
    <span class="badge bg-secondary">Backup</span>
{% elif bucket == INITDB_BUCKET %}
    <span class="badge bg-secondary">InitDB</span>
{% elif bucket == TELEMETRY_BUCKET %}
    <span class="badge bg-secondary">Telemetry</span>
{% elif bucket == FEEDBACK_BUCKET %}
    <span class="badge bg-secondary">Feedback</span>
{% elif bucket == PROJECT_BUCKET %}
    <span class="badge bg-secondary">Project</span>
{% else %}
    <span class="badge bg-danger">Unknown ({{ bucket }})</span>
{% endif %}
"""

# language=jinja2
_menu_generated = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.download_generated_asset', asset_id=asset.id) }}">
            <i class="fas fa-download fa-fw"></i> Download
        </a>
        {% if asset.expiry is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.asset_remove_expiry', asset_type='generated', asset_id=asset.id) }}">
                <i class="fas fa-calendar-times fa-fw"></i> Remove expiry
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-calendar-times fa-fw"></i> No expiry set
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_menu_submitted = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.download_submitted_asset', asset_id=asset.id) }}">
            <i class="fas fa-download fa-fw"></i> Download
        </a>
        {% if asset.expiry is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.asset_remove_expiry', asset_type='submitted', asset_id=asset.id) }}">
                <i class="fas fa-calendar-times fa-fw"></i> Remove expiry
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-calendar-times fa-fw"></i> No expiry set
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_menu_temporary = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if asset.expiry is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.asset_remove_expiry', asset_type='temporary', asset_id=asset.id) }}">
                <i class="fas fa-calendar-times fa-fw"></i> Remove expiry
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-calendar-times fa-fw"></i> No expiry set
            </a>
        {% endif %}
    </div>
</div>
"""


def _build_row(asset, asset_type: str, simple_label, truncate):
    has_license = hasattr(asset, 'license')
    has_download_data = hasattr(asset, 'mimetype')

    license_obj = asset.license if has_license else None
    mimetype = asset.mimetype if has_download_data else None
    target_name = asset.target_name if has_download_data else None
    human_size = asset.human_file_size if has_download_data else None
    bucket_val = asset.bucket if has_download_data else None
    comment = asset.comment if has_download_data else None
    encrypted = getattr(asset, 'encrypted', False)
    compressed = getattr(asset, 'compressed', False)

    target_html = render_template_string(_target, target_name=target_name, asset=asset, truncate=truncate)
    type_html = render_template_string(_type_badge, asset_type=asset_type)
    license_html = render_template_string(_license, license=license_obj, simple_label=simple_label)
    expiry_html = render_template_string(_expiry, expiry=asset.expiry)
    flags_html = render_template_string(_flags, encrypted=encrypted, compressed=compressed)
    bucket_html = render_template_string(
        _bucket,
        bucket=bucket_val,
        ASSETS_BUCKET=buckets.ASSETS_BUCKET,
        BACKUP_BUCKET=buckets.BACKUP_BUCKET,
        INITDB_BUCKET=buckets.INITDB_BUCKET,
        TELEMETRY_BUCKET=buckets.TELEMETRY_BUCKET,
        FEEDBACK_BUCKET=buckets.FEEDBACK_BUCKET,
        PROJECT_BUCKET=buckets.PROJECT_BUCKET,
    ) if bucket_val is not None else '<div class="text-secondary"><i class="fas fa-ban"></i> None</div>'

    if asset_type == 'GeneratedAsset':
        menu_html = render_template_string(_menu_generated, asset=asset)
    elif asset_type == 'SubmittedAsset':
        menu_html = render_template_string(_menu_submitted, asset=asset)
    else:
        menu_html = render_template_string(_menu_temporary, asset=asset)

    return {
        "id": asset.id,
        "type": type_html,
        "license": license_html,
        "expiry": expiry_html,
        "mimetype": mimetype if mimetype else '<div class="text-secondary"><i class="fas fa-ban"></i> None</div>',
        "target_name": target_html,
        "filesize": human_size if human_size else '<div class="text-secondary"><i class="fas fa-ban"></i> None</div>',
        "bucket": bucket_html,
        "comment": comment if comment else '<div class="text-secondary"><i class="fas fa-ban"></i> None</div>',
        "flags": flags_html,
        "menu": menu_html,
    }


def assets_data(assets):
    """
    Build the JSON payload for the assets DataTable.

    :param assets: iterable of (asset, asset_type_str) pairs, as produced by the
                   ServerSideInMemoryHandler row formatter callback.
    """
    simple_label = get_template_attribute("labels.html", "simple_label")
    truncate = get_template_attribute("macros.html", "truncate")

    data = []
    for asset, asset_type in assets:
        data.append(_build_row(asset, asset_type, simple_label, truncate))

    return data
