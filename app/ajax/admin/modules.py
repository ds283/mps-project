#
# Created by David Seery on 2018-10-26.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string


# language=jinja2
_code = \
"""
<a href="{{ url_for('admin.edit_module', id=m.id) }}">{{ m.code }}</span>
"""


# language=jinja2
_status = \
"""
{% if m.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
    <span class="badge bg-info text-dark">First taught {{ m.first_taught }}</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-times"></i> Retired</span>
    <span class="badge bg-info text-dark">First taught {{ m.first_taught }}</span>
    <span class="badge bg-info text-dark">Last taught {{ m.last_taught }}</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        {% set disabled = not m.active %}
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.edit_module', id=m.id) }}"{% endif %}>
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if m.active %}
            <a class="dropdown-item" href="{{ url_for('admin.retire_module', id=m.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Retire
            </a>
        {% else %}
            {% set disabled = m.available %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.unretire_module', id=m.id) }}"{% endif %}>
                <i class="fas fa-wrench fa-fw"></i> Unretire
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_level = \
"""
{{ m.level_label|safe }}
{{ m.semester_label|safe }}
"""


def modules_data(modules):
    data = [{'code': render_template_string(_code, m=m),
             'name': m.name,
             'level': render_template_string(_level, m=m),
             'status': render_template_string(_status, m=m),
             'menu': render_template_string(_menu, m=m)} for m in modules]

    return data
