#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <div class="dropdown-header">Edit</div>
        <a class="dropdown-item" href="{{ url_for('admin.edit_degree_programme', id=programme.id) }}">
            <i class="fa fa-cogs"></i> Edit details...
        </a>
        <a class="dropdown-item" href="{{ url_for('admin.attach_modules', id=programme.id) }}">
            <i class="fa fa-cogs"></i> Attach modules...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Administration</div>

        {% if programme.active %}
            <a class="dropdown-item" href="{{ url_for('admin.deactivate_degree_programme', id=programme.id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a>
        {% else %}
            {% if programme.available %}
                <a class="dropdown-item" href="{{ url_for('admin.activate_degree_programme', id=programme.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a>
            {% else %}
                <a class="dropdown-item disabled">
                    <i class="fa fa-ban"></i> Degree type inactive
                </a>
            {% endif %}
        {% endif %}
    </div>
</div>
"""


_active = \
"""
{% if p.active %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="badge badge-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


_show_type = \
"""
{% if p.show_type %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Yes</span>
{% else %}
    <span class="badge badge-secondary"><i class="fa fa-times"></i> No</span>
{% endif %}
"""


_name = \
"""
{{ p.name }} {{ p.short_label|safe }}
<p></p>
{% for level in levels %}
    {% set num = p.number_level_modules(level.id) %} 
    {% if num > 0 %}
        {{ level.make_label(level.short_name + ' ' + num|string)|safe }} 
    {% endif %}
{% endfor %}
"""


def degree_programmes_data(programmes, levels):

    data = [{'name': render_template_string(_name, p=p, levels=levels),
             'type': p.degree_type.name,
             'show_type': render_template_string(_show_type, p=p),
             'course_code': p.course_code,
             'active': render_template_string(_active, p=p),
             'menu': render_template_string(_menu, programme=p)} for p in programmes]

    return jsonify(data)
