#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from .shared import build_name_templ, build_active_templ, build_menu_templ
from ...models import User, FacultyData

# language=jinja2
_affiliation = """
{% for group in f.affiliations %}
    {{ simple_label(group.make_label(group.name)) }}
{% endfor %}
"""


# language=jinja2
_enrolled = """
{% for record in f.enrollments %}
    {% set pclass = record.pclass %}
    {% if pclass.active and pclass.publish %}
        {% set swatch_colour = pclass.make_CSS_style() %}
        <div class="d-flex flex-row justify-content-start align-items-center gap-2">
            {{ small_swatch(swatch_colour) }}
            <span class="small">{{ pclass.name }}</span>
        </div>
    {% endif %}
{% endfor %}
"""


# language=jinja2
_settings = """
<div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
    <span class="small fw-semibold text-primary">Default capacity {{ f.project_capacity }}</span>
    {% if f.enforce_capacity %}
        <div class="small">
            <i class="fas fa-check-circle text-success"></i>
            <span class="text-secondary">Enforce capacity</span>
        </div>
    {% endif %}
</div>
{% if f.sign_off_students %}
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1">
        <div class="small">
            <i class="fas fa-check-circle text-success"></i>
            <span class="text-secondary">Require meetings</span>
        </div>
    </div>
{% endif %}
{% if f.show_popularity %}
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1">
        <div class="small">
            <i class="fas fa-check-circle text-success"></i>
            <span class="text-secondary">Show popularity</span>
        </div>
    </div>
{% endif %}
{% if f.CATS_supervision is not none or f.CATS_marking is not none or f.CATS_moderation is not none or f.CATS_presentation is not none %}
    <div class="small fw-semibold mt-1">CATS limits</div>
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 mt-1 small">
        {% if f.CATS_supervision is not none %}
            <span class="text-primary">S: {{ f.CATS_supervision }} CATS</span>
        {% endif %}
        {% if f.CATS_marking is not none %}
            <span class="text-primary">Mk: {{ f.CATS_marking }} CATS</span>
        {% endif %}
        {% if f.CATS_moderation is not none %}
            <span class="text-primary">Mo: {{ f.CATS_moderation }} CATS</span>
        {% endif %}
        {% if f.CATS_presentation is not none %}
            <span class="text-primary">P: {{ f.CATS_presentation }} CATS</span>
        {% endif %}
    </div>
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1 mt-1 small">
        <a class="btn btn-sm btn-outline-secondary small" href="{{ url_for('manage_users.remove_CATS_limits', fac_id=f.id) }}"><i class="fas fa-trash"></i> Reset limits</a>
    </div>
{% endif %}
"""


def _build_settings_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_settings)


def _build_affiliation_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_affiliation)


def _build_enrolled_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_enrolled)


def build_faculty_data(current_user: User, faculty: List[FacultyData]):
    name_templ: Template = build_name_templ()
    active_templ: Template = build_active_templ()
    settings_templ: Template = _build_settings_templ()
    affiliation_templ: Template = _build_affiliation_templ()
    enrolled_templ: Template = _build_enrolled_templ()
    menu_templ: Template = build_menu_templ()

    simple_label = get_template_attribute("labels.html", "simple_label")
    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    return [
        {
            "name": render_template(name_templ, u=fd.user, f=fd, simple_label=simple_label),
            "active": render_template(active_templ, u=fd.user),
            "office": fd.office,
            "settings": render_template(settings_templ, f=fd),
            "affiliation": render_template(affiliation_templ, f=fd, simple_label=simple_label),
            "enrolled": render_template(enrolled_templ, f=fd, small_swatch=small_swatch),
            "menu": render_template(menu_templ, user=fd.user, cuser=current_user, pane="faculty"),
        }
        for fd in faculty
    ]
