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

from flask import get_template_attribute, render_template, current_app
from jinja2 import Template, Environment

from ...cache import cache
from ...models import StudentData, ProjectClassConfig
from ...shared.utils import get_current_year

# language=jinja2
_enrol = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.enrol_selector', sid=s.id, configid=config.id, convert=1) }}">
            <i class="fas fa-plus fa-fw"></i> Enrol
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.enrol_selector', sid=s.id, configid=config.id, convert=0) }}">
            <i class="fas fa-plus fa-fw"></i> Enrol without conversion
        </a>
    </div>
</dic>
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


@cache.memoize()
def build_programme_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_programme)


@cache.memoize()
def build_cohort_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_cohort)


@cache.memoize()
def build_academic_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_academic_year)


@cache.memoize()
def build_enrol_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_enrol)


def enrol_selectors_data(config: ProjectClassConfig, students: List[StudentData]):
    current_year = get_current_year()

    simple_label = get_template_attribute("labels.html", "simple_label")

    programme_templ = build_programme_templ()
    cohort_templ = build_cohort_templ()
    academic_year_templ = build_academic_year_templ()
    enrol_templ = build_enrol_templ()

    data = [
        {
            "name": s.user.name,
            "programme": render_template(programme_templ, s=s, simple_label=simple_label),
            "cohort": render_template(cohort_templ, s=s, simple_label=simple_label),
            "current_year": render_template(academic_year_templ, s=s, config=config, current_year=current_year, simple_label=simple_label),
            "actions": render_template(enrol_templ, s=s, config=config),
        }
        for s in students
    ]

    return data
