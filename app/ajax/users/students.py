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

from flask import get_template_attribute, render_template
from jinja2 import Template

from .shared import (
    build_name_templ,
    build_active_templ,
    build_programme_templ,
    build_cohort_templ,
    build_academic_year_templ,
    build_menu_templ,
)
from ...models import User, StudentData


def build_student_data(current_user: User, students: List[StudentData]):
    name_templ: Template = build_name_templ()
    active_templ: Template = build_active_templ()
    programme_templ: Template = build_programme_templ()
    cohort_templ: Template = build_cohort_templ()
    academic_year_templ: Template = build_academic_year_templ()
    menu_templ: Template = build_menu_templ()

    simple_label = get_template_attribute("labels.html", "simple_label")

    return [
        {
            "name": render_template(name_templ, u=sd.user, simple_label=simple_label),
            "active": render_template(active_templ, u=sd.user, simple_label=simple_label),
            "programme": render_template(programme_templ, s=sd, simple_label=simple_label),
            "cohort": render_template(cohort_templ, s=sd, simple_label=simple_label),
            "acadyear": render_template(academic_year_templ, s=sd, simple_label=simple_label),
            "menu": render_template(menu_templ, user=sd.user, cuser=current_user, pane="students"),
        }
        for sd in students
    ]
