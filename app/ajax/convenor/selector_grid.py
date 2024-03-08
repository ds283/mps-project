#
# Created by David Seery on 31/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from app.models import SelectingStudent, ProjectClassConfig

# language=jinja2
_cohort = """
{{ simple_label(sel.student.cohort_label) }}
{{ simple_label(sel.academic_year_label(show_details=True)) }}
"""

# language=jinja2
_selections = """
{% if sel.has_submitted %}
    {% if sel.has_accepted_offer %}
        {% set offer = sel.accepted_offer %}
        {% set project = offer.liveproject %}
        {% if project %}
            <span class="text-success"><i class="fas fa-check-circle"></i> <strong>Accepted:</strong> {{ project.name }} ({{ project.owner.user.last_name }})</span>
        {% else %}
            <span class="text-danger"><strong>MISSING ACCEPTED PROJECT</strong></span>
        {% endif %}
    {% else %}
        {% for item in sel.ordered_selections %}
            {% set project = item.liveproject %}
            <div class="d-flex flex-row justify-content-start align-items-start gap-1">
                <span>#{{ item.rank }}</span>
                {% if project.group %}
                    {% set swatch_color = project.group.make_CSS_style() %}
                    {{ small_swatch(swatch_color) }}
                {% endif %}
                <span class="small">
                    {{ item.format_project()|safe }}
                    {% if not project.generic and project.owner is not none %}
                        &ndash; {{ project.owner.user.name }}
                    {% else %}
                        <span class="fw-semibold text-uppercase text-info">Generic</span>
                    {% endif %}
                    {% if item.converted_from_bookmark %}
                        <span class="badge bg-warning text-dark"><i class="fas fa-exclamation-triangle"></i> Bookmark</span>
                    {% endif %}
                </span>
                <div class="dropdown">
                    {% set has_hint = item.has_hint %}
                    <a class="ms-2 btn btn-xs {% if has_hint %}btn-info{% else %}btn-outline-secondary{% endif %} dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                        {% if has_hint %}
                            Has hint
                        {% else %}
                            Set hint
                        {% endif %}
                    </a>
                    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 small">
                        {% set menu_items = item.menu_order %}
                        {% for mi in menu_items %}
                            {% if mi is string %}
                                <div role="separator" class="dropdown-divider"></div>
                                <div class="dropdown-header">{{ mi }}</div>
                            {% elif mi is number %}
                                {% set disabled = (mi == item.hint) %}
                                <a class="dropdown-item d-flex gap-2 small {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.set_hint', id=item.id, hint=mi) }}"{% endif %}>
                                    {{ item.menu_item(mi)|safe }}
                                </a>
                            {% endif %}
                        {% endfor %}
                    </div>
                </div>
            </div>
        {% endfor %}
    {% endif %}
{% else %}
    <div class="d-flex flex-row justify-content-start align-items-center gap-2">
        {% if sel.number_bookmarks > 0 %}
            <span class="small">           
                <i class="fas fa-info-circle text-danger"></i>
                <span class="text-danger">{{ sel.number_bookmarks }} bookmark{% if sel.number_bookmarks != 1 %}s{% endif %} available</span>
                <a class="text-decoration-none" href="{{ url_for('convenor.force_convert_bookmarks', sel_id=sel.id, converted=1, no_submit_IP=1, force=0, reset=1) }}">
                    Force conversion...
                </a>
            </span>
        {% else %}
            <i class="fas fa-ban"></i> <span>None</span>
        {% endif %}
    </div>
{% endif %}
"""

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
<div>
{% if sel.convert_to_submitter %}
    <div class="text-success small"><i class="fas fa-check-circle"></i> Convert to submitter</div>
{% else %}
    <div class="text-danger small"><i class="fas fa-times-circle"></i> No convert to submitter</div>
{% endif %}
{% if sel.student.intermitting %}
    <div class="badge bg-warning text-dark">TWD</div>
{% endif %}
</div>
"""

# language=jinja2
_programme = """
{{ simple_label(s.student.programme.label) }}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_programme_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_programme)


def _build_cohort_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_cohort)


def _build_selections_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_selections)


def selector_grid_data(students: List[SelectingStudent], config: ProjectClassConfig):
    simple_label = get_template_attribute("labels.html", "simple_label")
    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    name_templ: Template = _build_name_templ()
    programme_templ: Template = _build_programme_templ()
    cohort_templ: Template = _build_cohort_templ()
    selections_templ: Template = _build_selections_templ()

    def sel_count(sel: SelectingStudent):
        if not sel.has_submitted:
            return 0

        # group 'accepted offer' students together at the top
        if sel.has_accepted_offer:
            return 100

        if sel.has_submission_list:
            return sel.number_selections

        return -1

    data = [
        {
            "name": {"display": render_template(name_templ, sel=s), "sortstring": s.student.user.last_name + s.student.user.first_name},
            "programme": render_template(programme_templ, s=s, simple_label=simple_label),
            "cohort": {"display": render_template(cohort_templ, sel=s, simple_label=simple_label), "value": s.student.cohort},
            "selections": {"display": render_template(selections_templ, sel=s, config=config, small_swatch=small_swatch), "sortvalue": sel_count(s)},
        }
        for s in students
    ]

    return jsonify(data)
