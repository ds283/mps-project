#
# Created by ds283$ on 04/05/2023$.
# Copyright (c) 2023$ University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283$ <$>
#

from typing import List

from flask import render_template_string

from ...models import SubmissionRole


# language=jinja2
_name = \
"""
<a href="mailto:{{ user.email }}">{{ user.name }}</a>
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_role', role_id=role.id, url=return_url) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def edit_roles(roles: List[SubmissionRole], return_url=None):
    data = [{'name': render_template_string(_name, user=r.user),
             'role': r.role_label,
             'menu': render_template_string(_menu, role=r, return_url=return_url)} for r in roles]

    return data
