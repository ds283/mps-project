#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List, Optional
from urllib import parse

from flask import current_app, get_template_attribute, render_template
from jinja2 import Template, Environment

from ...cache import cache
from ...models import StudentData

# language=jinja2
_actions = """
<a href="{{ url_for('user_approver.approve', id=s.id, url=url, text=text) }}" class="btn btn-sm btn-outline-success btn-table-block">Approve</a>
<a href="{{ url_for('user_approver.reject', id=s.id, url=url, text=text) }}" class="btn btn-sm btn-outline-danger btn-table-block">Reject</a>
"""

# language=jinja2
_academic_year = """
{{ simple_label(r.academic_year_label(show_details=True)) }}
"""


def _build_academic_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_academic_year)


def _build_actions_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_actions)


def validate_data(url: Optional[str], text: Optional[str], records: List[StudentData]):
    bleach = current_app.extensions["bleach"]

    def urlencode(s):
        s = s.encode("utf8")
        s = parse.quote_plus(s)
        return bleach.clean(s)

    url_enc = urlencode(url) if url is not None else ""
    text_enc = urlencode(text) if text is not None else ""

    simple_label = get_template_attribute("labels.html", "simple_label")

    academic_year_templ = _build_academic_year_templ()
    actions_templ = _build_actions_templ()

    return [
        {
            "name": r.user.name,
            "email": r.user.email,
            "exam_number": r.exam_number,
            "registration_number": r.registration_number,
            "programme": r.programme.full_name,
            "year": render_template(academic_year_templ, r=r, simple_label=simple_label),
            "menu": render_template(actions_templ, s=r, url=url_enc, text=text_enc),
        }
        for r in records
    ]
