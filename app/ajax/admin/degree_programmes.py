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
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li class="dropdown-header">Edit</li>
        <li>
            <a href="{{ url_for('admin.edit_degree_programme', id=programme.id) }}">
                <i class="fa fa-cogs"></i> Edit details...
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.attach_modules', id=programme.id) }}">
                <i class="fa fa-cogs"></i> Attach modules...
            </a>
        </li>
        
        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Administration</li>

        {% if programme.active %}
            <li><a href="{{ url_for('admin.deactivate_degree_programme', id=programme.id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a></li>
        {% else %}
            {% if programme.available %}
                <li><a href="{{ url_for('admin.activate_degree_programme', id=programme.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    <i class="fa fa-ban"></i> Degree type inactive
                </a></li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""


_active = \
"""
{% if p.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


_show_type = \
"""
{% if p.show_type %}
    <span class="label label-success"><i class="fa fa-check"></i> Yes</span>
{% else %}
    <span class="label label-default"><i class="fa fa-times"></i> No</span>
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
             'active': render_template_string(_active, p=p),
             'menu': render_template_string(_menu, programme=p)} for p in programmes]

    return jsonify(data)
