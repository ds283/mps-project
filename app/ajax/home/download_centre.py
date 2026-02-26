#
# Created by David Seery on 26/02/2025.
# Copyright (c) 2025 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from typing import List

from flask import url_for, render_template, current_app
from jinja2 import Template, Environment

from ...models import DownloadCentreItem


# language=jinja2
_name = """
{% if item.asset is not none %}
    <div class="fw-semibold">{{ item.asset.target_name if item.asset.target_name else '(unnamed)' }}</div>
    {% if item.asset.comment %}
        <div class="text-muted small mt-1">{{ item.asset.comment }}</div>
    {% endif %}
{% else %}
    <div class="text-danger"><i class="fas fa-exclamation-triangle"></i> Asset missing</div>
{% endif %}
"""

# language=jinja2
_generated = """
{% if item.generated_at is not none %}
    <span data-bs-toggle="tooltip" title="{{ item.generated_at.strftime('%a %d %b %Y %H:%M:%S') }}">
        {{ item.generated_at.strftime('%d %b %Y') }}
    </span>
{% else %}
    <span class="text-secondary">Unknown</span>
{% endif %}
"""

# language=jinja2
_expiry = """
{% if item.expire_at is not none %}
    {% set now = now %}
    {% if item.expire_at < now %}
        <span class="badge bg-danger">Expired</span>
    {% else %}
        <span data-bs-toggle="tooltip" title="{{ item.expire_at.strftime('%a %d %b %Y %H:%M:%S') }}">
            {{ item.expire_at.strftime('%d %b %Y') }}
        </span>
    {% endif %}
{% else %}
    <span class="text-secondary"><i class="fas fa-infinity"></i> No expiry</span>
{% endif %}
"""

# language=jinja2
_size = """
{% if item.asset is not none %}
    {{ item.asset.human_file_size }}
{% else %}
    <span class="text-secondary">&mdash;</span>
{% endif %}
"""

# language=jinja2
_downloads = """
<span class="badge bg-secondary">{{ item.number_downloads }}</span>
{% if item.last_downloaded_at is not none %}
    <div class="text-muted small mt-1">
        Last: <span data-bs-toggle="tooltip" title="{{ item.last_downloaded_at.strftime('%a %d %b %Y %H:%M:%S') }}">
            {{ item.last_downloaded_at.strftime('%d %b %Y') }}
        </span>
    </div>
{% endif %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if item.asset is not none %}
            {% set expired = item.expire_at is not none and item.expire_at < now %}
            {% if not expired %}
                <a class="dropdown-item d-flex gap-2"
                   href="{{ url_for('admin.download_generated_asset', asset_id=item.asset.id, download_item_id=item.id) }}">
                    <i class="fas fa-download fa-fw"></i> Download
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-download fa-fw"></i> Download (expired)
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-exclamation-triangle fa-fw"></i> Asset unavailable
            </a>
        {% endif %}
    </div>
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_generated_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_generated)


def _build_expiry_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_expiry)


def _build_size_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_size)


def _build_downloads_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_downloads)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def download_centre_data(items: List[DownloadCentreItem]):
    if not items:
        return []

    now = datetime.now()

    name_templ: Template = _build_name_templ()
    generated_templ: Template = _build_generated_templ()
    expiry_templ: Template = _build_expiry_templ()
    size_templ: Template = _build_size_templ()
    downloads_templ: Template = _build_downloads_templ()
    menu_templ: Template = _build_menu_templ()

    def _process(item: DownloadCentreItem):
        return {
            "name": render_template(name_templ, item=item),
            "generated": render_template(generated_templ, item=item, now=now),
            "expiry": render_template(expiry_templ, item=item, now=now),
            "size": render_template(size_templ, item=item),
            "downloads": render_template(downloads_templ, item=item),
            "menu": render_template(menu_templ, item=item, now=now),
        }

    return [_process(item) for item in items]
