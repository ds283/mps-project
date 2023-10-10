#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import render_template_string, get_template_attribute

from ...models import BackupRecord

# language=jinja2
_manage_backups_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.download_backup', backup_id=backup.id) }}">
            <i class="fas fa-download fa-fw"></i> Download
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_backup_labels', backup_id=backup.id) }}">
            <i class="fas fa-tags fa-fw"></i> Edit labels...
        </a>
        {% if not backup.locked %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.lock_backup', backup_id=backup.id) }}">
                <i class="fas fa-lock fa-fw"></i> Lock
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.confirm_delete_backup', id=backup.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.unlock_backup', backup_id=backup.id) }}">
                <i class="fas fa-lock-open fa-fw"></i> Unlock
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_name = \
"""
<div>{{ b.date.strftime("%a %d %b %Y %H:%M:%S") }}</div>
<div class="mt-1 small text-muted">
    {% if b.encryption == 0 %}
        <i class="fas fa-lock-open"></i> Not encrypted
    {% else %}
        <i class="fas fa-lock"></i> Encrypted
    {% endif %}
</div>
{% if b.locked %}
    <div class="mt-1 small text-muted">
        <i class="fas fa-lock"></i> Locked
    </div>
{% endif %}
"""

# language=jinja2
_key = \
"""
<div class="small">{{ b.unique_name }}</div>
{% if b.last_validated %}
    <div class="mt-1 small text-muted">
        <i class="fas fa-check-circle"></i> Last validated {{ b.last_validated.strftime("%a %d %b %Y %H:%M:%S") }}
    </div>
{% endif %}
"""


# language=jinja2
_description = \
"""
{% if b.description and b.description|length > 0 %}
    <div class="small">{{ b.description }}</div>
{% else %}
    <div><span class="badge bg-secondary">None</span></div>
{% endif %}
{% set labels = b.labels.all() %}
{% if labels|length > 0 %}
    <div class="mt-1 small">
        {% for label in labels %}
            {{ simple_label(label.make_label()) }}
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_type = \
"""
<div class="small">{{ b.type_to_string() }}</div>
"""


def backups_data(backups: List[BackupRecord]):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'date': render_template_string(_name, b=b),
             'initiated': '<a class="text-decoration-none" '
                          'href="mailto:{e}">{name}</a>'.format(e=b.owner.email,
                                                                name=b.owner.name) if b.owner is not None
                          else '<span class="badge bg-secondary">Nobody</span>',
             'type': render_template_string(_type, b=b),
             'description': render_template_string(_description, b=b, simple_label=simple_label),
             'key': render_template_string(_key, b=b),
             'db_size': b.readable_db_size,
             'archive_size': b.readable_archive_size,
             'menu': render_template_string(_manage_backups_menu, backup=b)} for b in backups]

    return data
