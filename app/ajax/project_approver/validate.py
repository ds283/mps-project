#
# Created by David Seery on 2019-02-24.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import Optional, List

from flask import current_app, render_template, jsonify
from jinja2 import Template, Environment

from .common import build_title_templ, build_owner_templ, build_pclasses_templ
from ...models import ProjectDescription, User

# language=jinja2
_actions = """
<a href="{{ url_for('project_approver.approve', id=r.id, url=url) }}" class="btn btn-sm btn-outline-success btn-table-block">Approve</a>
<a href="{{ url_for('project_approver.reject', id=r.id, url=url) }}" class="btn btn-sm btn-outline-danger btn-table-block">Reject</a>
"""


def build_actions_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_actions)


def validate_data(current_user: User, url: Optional[str], text: Optional[str], records: List[ProjectDescription]):
    title_templ: Template = build_title_templ()
    owner_templ: Template = build_owner_templ()
    pclasses_templ: Template = build_pclasses_templ()
    actions_templ: Template = build_actions_templ()

    data = [
        {
            "name": render_template(title_templ, r=r, url=url, text=text, current_user=current_user),
            "owner": render_template(owner_templ, p=r.parent),
            "pclasses": render_template(pclasses_templ, r=r),
            "menu": render_template(actions_templ, r=r, url=url, text=text),
        }
        for r in records
    ]

    return jsonify(data)
