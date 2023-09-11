#
# Created by David Seery on 31/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_name = \
"""
<div>
    <strong>{{ l.name }}</strong>
</div>
<div>
    {{ simple_label(l.make_label(popover=false)) }}
    {% if l.version and l.version|length > 0 %}
        <span class="badge bg-info">{{ l.version }}</span>
    {% endif %}
</div>
"""


# language=jinja2
_properties = \
"""
{% if l.url is not none %}
    <div>
        <a class="text-decoration-none" href="{{ l.url }}">{{ l.url }}</a>
    </div>
{% endif %}
{% if l.allows_redistribution %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Allows redistribution</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-times"></i> No redistribution</span>
{% endif %}
<div class="mt-2">
    Created by
    <a class="text-decoration-none" href="mailto:{{ l.created_by.email }}">{{ l.created_by.name }}</a>
    on
    {% if l.creation_timestamp is not none %}
        {{ l.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% else %}
        <span class="badge bg-secondary">Unknown</span>
    {% endif %}
    {% if l.last_edited_by is not none %}
        <div class="mt-1 text-muted">
            Last edited by <i class="fas fa-user-circle"></i>
            <a class="text-decoration-none" href="mailto:{{ l.last_edited_by.email }}">{{ l.last_edited_by.name }}</a>
            {% if l.last_edit_timestamp is not none %}
                {{ l.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
            {% endif %}
        </div>
    {% endif %}
</div>
"""


# language=jinja2
_active = \
"""
{% if l.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_license', lid=l.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if l.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_license', lid=l.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_license', lid=l.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


def licenses_data(licenses):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'name': render_template_string(_name, l=l, simple_label=simple_label),
             'active': render_template_string(_active, l=l),
             'description': l.description,
             'properties': render_template_string(_properties, l=l),
             'menu': render_template_string(_menu, l=l)} for l in licenses]

    return jsonify(data)
