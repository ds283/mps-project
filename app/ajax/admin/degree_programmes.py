#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, get_template_attribute, render_template, current_app
from jinja2 import Template, Environment

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <div class="dropdown-header">Edit</div>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_degree_programme', id=programme.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Edit details...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.attach_modules', id=programme.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Attach modules...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Administration</div>

        {% if programme.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_degree_programme', id=programme.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            {% if programme.available %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_degree_programme', id=programme.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-ban fa-fw"></i> Degree type inactive
                </a>
            {% endif %}
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_active = """
{% if p.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_show_type = """
{% if p.show_type %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Yes</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-times"></i> No</span>
{% endif %}
"""


# language=jinja2
_name = """
<div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
    <span text="text-secondary fw-semibold">{{ p.name }}</span>
    {{ simple_label(p.short_label) }}
</div>
<div class="mt-2 d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 small">
    {% if p.foundation_year %}
        <span class="badge bg-info">Foundation year</span>
    {% endif %}
    {% if p.year_out %}
        <span class="badge bg-info">Year out{%- if p.year_out_value %} Y{{ p.year_out_value}}{% endif %}</span>
    {% endif %}
</div>
{% if levels|length > 0 %}
    <div class="mt-2 d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 small">
        {% for level in levels %}
            {% set num = p.number_level_modules(level.id) %} 
            {% if num > 0 %}
                {{ simple_label(level.make_label(level.short_name + ' ' + num|string)) }} 
            {% endif %}
        {% endfor %}
    </div>
{% endif %}
<div class="mt-2 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
    {% for tenant in p.tenants %}
        {{ simple_label(tenant.make_label(tenant.name)) }}
    {% endfor %}
</div>
"""


# language=jinja2
_type = """
{{ simple_label(t.make_label(show_type=true)) }}
"""


# language=jinja2
_course_code = """
<span class="text-primary">{{ p.course_code }}</span>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_type_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_type)


def _build_show_type_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_show_type)


def _build_course_code_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_course_code)


def build_active_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_active)


def build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def degree_programmes_data(levels, programmes):
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    type_templ: Template = _build_type_templ()
    show_type_templ: Template = _build_show_type_templ()
    course_code_templ: Template = _build_course_code_templ()
    active_templ: Template = build_active_templ()
    menu_templ: Template = build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, p=p, levels=levels, simple_label=simple_label),
            "type": render_template(type_templ, t=p.degree_type, simple_label=simple_label),
            "show_type": render_template(show_type_templ, p=p),
            "course_code": render_template(course_code_templ, p=p),
            "active": render_template(active_templ, p=p),
            "menu": render_template(menu_templ, programme=p),
        }
        for p in programmes
    ]

    return data
