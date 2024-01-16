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

from flask import render_template_string, jsonify, get_template_attribute

from ...models import StudentData
from ...shared.utils import get_current_year

# language=jinja2
_enroll_action = """
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


def enrol_submitters_data(students: List[StudentData], config):
    current_year = get_current_year()

    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "name": {"display": s.user.name, "sortstring": s.user.last_name + s.user.first_name},
            "programme": render_template_string(_programme, s=s, simple_label=simple_label),
            "cohort": {"display": render_template_string(_cohort, s=s, simple_label=simple_label), "sortvalue": s.cohort},
            "acadyear": {
                "display": render_template_string(_academic_year, s=s, config=config, current_year=current_year, simple_label=simple_label),
                "sortvalue": s.compute_academic_year(desired_year=config.year, current_year=current_year),
            },
            "actions": render_template_string(_enroll_action, s=s, config=config),
        }
        for s in students
    ]

    return jsonify(data)
