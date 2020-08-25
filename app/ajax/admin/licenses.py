#
# Created by David Seery on 31/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_name = \
"""
<div>
    <strong>{{ l.name }}</strong>
</div>
<div>
    {{ l.make_label(popover=false)|safe }}
    {% if l.version and l.version|length > 0 %}
        <span class="badge badge-info">{{ l.version }}</span>
    {% endif %}
</div>
"""


_properties = \
"""
{% if l.url is not none %}
    <div>
        <a href="{{ l.url }}">{{ l.url }}</a>
    </div>
{% endif %}
{% if l.allows_redistribution %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Allows redistribution</span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-times"></i> No redistribution</span>
{% endif %}
<div style="padding-top: 5px;">
    Created by
    <a href="mailto:{{ l.created_by.email }}">{{ l.created_by.name }}</a>
    on
    {% if l.creation_timestamp is not none %}
        {{ l.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% else %}
        <span class="badge badge-secondary">Unknown</span>
    {% endif %}
    {% if l.last_edited_by is not none %}
        <p></p>
        Last edited by 
        <a href="mailto:{{ l.last_edited_by.email }}">{{ l.last_edited_by.name }}</a>
        {% if l.last_edit_timestamp is not none %}
            {{ l.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    {% endif %}
</div>
"""


_active = \
"""
{% if l.active %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('admin.edit_license', lid=l.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if l.active %}
            <a class="dropdown-item" href="{{ url_for('admin.deactivate_license', lid=l.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('admin.activate_license', lid=l.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


def licenses_data(licenses):
    data = [{'name': render_template_string(_name, l=l),
             'active': render_template_string(_active, l=l),
             'description': l.description,
             'properties': render_template_string(_properties, l=l),
             'menu': render_template_string(_menu, l=l)} for l in licenses]

    return jsonify(data)
