#
# Created by David Seery on 2018-10-02.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from ...cache import cache

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_room', id=r.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if r.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_room', id=r.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            {% if r.available %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_room', id=r.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-ban fa-fw"></i> Building inactive
                </a>
            {% endif %}
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_active = """
{% if r.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_info = """
<span class="badge bg-primary">Capacity {{ r.capacity }}</span>
<span class="badge bg-info">Max occupancy {{ r.maximum_occupancy }}</span>
{% if r.lecture_capture %}
    <span class="badge bg-info">Lecture capture</span>
{% endif %}
"""


# language=jinja2
_building = """
{{ simple_label(r.building.make_label()) }}
"""


@cache.memoize()
def _build_building_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_building)


@cache.memoize()
def _build_info_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_info)


@cache.memoize()
def _build_active_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_active)


@cache.memoize()
def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def rooms_data(rooms):
    simple_label = get_template_attribute("labels.html", "simple_label")

    building_templ: Template = _build_building_templ()
    info_templ: Template = _build_info_templ()
    active_templ: Template = _build_active_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": r.name,
            "building": render_template(building_templ, r=r, simple_label=simple_label),
            "info": render_template(info_templ, r=r),
            "active": render_template(active_templ, r=r),
            "menu": render_template(menu_templ, r=r),
        }
        for r in rooms
    ]

    return jsonify(data)
