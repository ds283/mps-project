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

from ...models import StudentData
from ...shared.utils import get_current_year

# language=jinja2
_enrol = """
<a href="{{ url_for('convenor.enrol_submitter', sid=s.id, configid=config.id) }}" class="btn btn-warning btn-sm">
    <i class="fas fa-plus"></i> Manually enroll
</a>
"""

# language=jinja2
_cohort = """
{{ simple_label(s.cohort_label) }}
"""

# language=jinja2
_programme = """
{{ simple_label(s.programme.label) }}
"""

# language=jinja2
_academic_year = """
{{ simple_label(s.academic_year_label(desired_year=config.year, show_details=True, current_year=current_year)) }}
"""


def _build_programme_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_programme)


def _build_cohort_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_cohort)


def _build_academic_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_academic_year)


def _build_enrol_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_enrol)


def enrol_submitters_data(students: List[StudentData], config):
    current_year = get_current_year()

    simple_label = get_template_attribute("labels.html", "simple_label")

    programme_templ: Template = _build_programme_templ()
    cohort_templ: Template = _build_cohort_templ()
    academic_year_templ: Template = _build_academic_year_templ()
    enrol_templ: Template = _build_enrol_templ()

    data = [
        {
            "name": {"display": s.user.name, "sortstring": s.user.last_name + s.user.first_name},
            "programme": render_template(programme_templ, s=s, simple_label=simple_label),
            "cohort": {"display": render_template(cohort_templ, s=s, simple_label=simple_label), "sortvalue": s.cohort},
            "acadyear": {
                "display": render_template(academic_year_templ, s=s, config=config, current_year=current_year, simple_label=simple_label),
                "sortvalue": s.compute_academic_year(desired_year=config.year, current_year=current_year),
            },
            "actions": render_template(enrol_templ, s=s, config=config),
        }
        for s in students
    ]

    return jsonify(data)
