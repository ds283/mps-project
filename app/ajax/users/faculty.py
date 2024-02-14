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
        {{ simple_label(pclass.make_label()) }}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_settings = """
{% if f.sign_off_students %}
    <span class="badge bg-info">Require meetings</span>
{% endif %}
<span class="badge bg-primary">Default capacity {{ f.project_capacity }}</span>
{% if f.enforce_capacity %}
    <span class="badge bg-info">Enforce capacity</span>
{% endif %}
{% if f.show_popularity %}
    <span class="badge bg-info">Show popularity</span>
{% endif %}
<p>
{% if f.CATS_supervision is not none %}
    <span class="badge bg-warning text-dark">S: {{ f.CATS_supervision }} CATS</span>
{% else %}
    <span class="badge bg-secondary">S: Default CATS</span>
{% endif %}
{% if f.CATS_marking is not none %}
    <span class="badge bg-warning text-dark">Mk {{ f.CATS_marking }} CATS</span>
{% else %}
    <span class="badge bg-secondary">Mk: Default CATS</span>
{% endif %}
{% if f.CATS_moderation is not none %}
    <span class="badge bg-warning text-dark">Mo {{ f.CATS_moderation }} CATS</span>
{% else %}
    <span class="badge bg-secondary">Mo: Default</span>
{% endif %}
{% if f.CATS_presentation is not none %}
    <span class="badge bg-warning text-dark">P {{ f.CATS_presentation }} CATS</span>
{% else %}
    <span class="badge bg-secondary">P: Default CATS</span>
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

    return [
        {
            "name": render_template(name_templ, u=fd.user, f=fd, simple_label=simple_label),
            "active": render_template(active_templ, u=fd.user, simple_label=simple_label),
            "office": fd.office,
            "settings": render_template(settings_templ, f=fd),
            "affiliation": render_template(affiliation_templ, f=fd, simple_label=simple_label),
            "enrolled": render_template(enrolled_templ, f=fd, simple_label=simple_label),
            "menu": render_template(menu_templ, user=fd.user, cuser=current_user, pane="faculty"),
        }
        for fd in faculty
    ]
