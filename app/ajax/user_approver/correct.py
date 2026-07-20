#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import Optional, List

from flask import current_app, get_template_attribute, render_template
from jinja2 import Template, Environment

from ...models import StudentData

# language=jinja2
_actions = """
<a href="{{ url_for('manage_users.edit_student', id=s.id, url=url_for('user_approver.correct', url=url, text=text)) }}" class="btn btn-sm btn-secondary">Edit record...</a>
"""

# language=jinja2
_rejected = """
{% if s.validated_by is not none %}
    <a class="text-decoration-none" href="mailto:{{ s.validated_by.email }}">{{ s.validated_by.name }}</a>
    {% if s.validated_timestamp is not none %}
        <p>{{ s.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</p>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


# language=jinja2
_academic_year = """
{{ simple_label(r.academic_year_label(show_details=True)) }}
"""


def _build_academic_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_academic_year)


def _build_rejected_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_rejected)


def _build_actions_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_actions)


def correction_data(url: Optional[str], text: Optional[str], records: List[StudentData]):
    simple_label = get_template_attribute("labels.html", "simple_label")

    academic_year_templ = _build_academic_year_templ()
    rejected_templ = _build_rejected_templ()
    actions_templ = _build_actions_templ()

    return [
        {
            "name": r.user.name,
            "email": r.user.email,
            "exam_number": r.exam_number,
            "registration_number": r.registration_number,
            "programme": r.programme.full_name,
            "year": render_template(academic_year_templ, r=r, simple_label=simple_label),
            "rejected_by": render_template(rejected_templ, s=r),
            "menu": render_template(actions_templ, s=r, url=url, text=text),
        }
        for r in records
    ]
