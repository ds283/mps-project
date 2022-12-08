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

from flask import render_template_string

from ...models import StudentData, ProjectClassConfig
from ...shared.utils import get_current_year

# language=jinja2
_enroll_action = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.enrol_selector', sid=s.id, configid=config.id, convert=1) }}">
            <i class="fas fa-plus fa-fw"></i> Enroll
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.enrol_selector', sid=s.id, configid=config.id, convert=0) }}">
            <i class="fas fa-plus fa-fw"></i> Enroll without conversion
        </a>
    </div>
</dic>
"""


def enrol_selectors_data(config: ProjectClassConfig, students: List[StudentData]):
    current_year = get_current_year()

    data = [{'name': s.user.name,
             'programme': s.programme.label,
             'cohort': s.cohort_label,
             'current_year': s.academic_year_label(desired_year=config.year, show_details=True,
                                                   current_year=current_year),
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return data
