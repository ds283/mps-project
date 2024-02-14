#
# Created by David Seery on 05/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, render_template, current_app
from jinja2 import Template, Environment

# language=jinja2
_student = """
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
"""


# language=jinja2
_cohort = """
{{ simple_label(sel.student.programme.short_label) }}
{{ simple_label(sel.academic_year_label(show_details=True)) }}
{{ simple_label(sel.student.cohort_label) }}
"""


# language=jinja2
_records = """
{% if r.project_id != c.project_id %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style()|safe %}
    <span class="badge bg-info" {% if style %}style="{{ style }}"{% endif %}>#{{ r.submission_period }}:
        {{ r.supervisor.user.name }} (No. {{ r.project.number }})</span>
{% else %}
    <span class="badge bg-success">PROJECT MATCH</span>
{% endif %}
{% if r.marker_id != c.marker_id %}
    <span class="badge bg-secondary">#{{ r.submission_period }}:
        {{ r.marker.user.name }}</span>
{% else %}
    <span class="badge bg-success">MARKER MATCH</span>
{% endif %}
"""


# language=jinja2
_delta = """
<span class="badge {% if r.hi_ranked %}bg-success{% elif r.lo_ranked %}bg-warning text-dark{% else %}bg-info{% endif %}">{{ r.rank }}</span>
<span class="badge bg-primary">&delta; = {{ r.delta }}</span>
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.merge_replace_records', src_id=l.id, dest_id=r.id) }}">
            <i class="fas fa-chevron-circle-right fa-fw"></i> Replace left to right
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.merge_replace_records', src_id=r.id, dest_id=l.id) }}">
            <i class="fas fa-chevron-circle-left fa-fw"></i> Replace right to left
        </a>
    </div>
</div>
"""


def _build_student_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_student)


def _build_cohort_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_cohort)


def _build_records_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_records)


def _build_delta_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_delta)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def compare_match_data(records):
    simple_label = get_template_attribute("labels.html", "simple_label")

    student_templ: Template = _build_student_templ()
    cohort_templ: Template = _build_cohort_templ()
    records_templ: Template = _build_records_templ()
    delta_templ: Template = _build_delta_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "student": {
                "display": render_template(student_templ, sel=l.selector),
                "sortvalue": l.selector.student.user.last_name + l.selector.student.user.first_name,
            },
            "cohort": render_template(cohort_templ, sel=l.selector, simple_label=simple_label),
            "record1": render_template(records_templ, r=l, c=r),
            "delta1": {"display": render_template(delta_templ, r=l), "sortvalue": l.delta},
            "record2": render_template(records_templ, r=r, c=l),
            "delta2": {"display": render_template(delta_templ, r=r), "sortvalue": r.delta},
            "menu": render_template(menu_templ, l=l, r=r),
        }
        for l, r in records
    ]

    return jsonify(data)
