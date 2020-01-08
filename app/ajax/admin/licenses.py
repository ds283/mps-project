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
        <span class="label label-info">{{ l.version }}</span>
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
    <span class="label label-success"><i class="fa fa-check"></i> Allows redistribution</span>
{% else %}
    <span class="label label-default"><i class="fa fa-times"></i> No redistribution</span>
{% endif %}
<div style="padding-top: 5px;">
    Created by
    <a href="mailto:{{ l.created_by.email }}">{{ l.created_by.name }}</a>
    on
    {% if l.creation_timestamp is not none %}
        {{ l.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% else %}
        <span class="label label-default">Unknown</span>
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
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.edit_license', lid=l.id) }}">
                <i class="fa fa-pencil"></i> Edit details...
            </a>
        </li>

        {% if l.active %}
            <li>
                <a href="{{ url_for('admin.deactivate_license', lid=l.id) }}">
                    <i class="fa fa-wrench"></i> Make inactive
                </a>
            </li>
        {% else %}
            <li>
                <a href="{{ url_for('admin.activate_license', lid=l.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""


def licenses_data(licenses):
    data = [{'name': render_template_string(_name, l=l),
             'active': render_template_string(_active, l=l),
             'description': l.description,
             'properties': render_template_string(_properties, l=l),
             'menu': render_template_string(_menu, l=l)} for l in licenses]

    return jsonify(data)
