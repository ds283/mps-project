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


# language=jinja2
_details = \
"""
{% if role.created_by is not none %}
    <div>
        Created by
        <i class="fas fa-user-circle"></i>
        <a class="text-decoration-none" href="mailto:{{ role.created_by.email }}">{{ role.created_by.name }}</a>
        {% if role.creation_timestamp is not none %}
            on {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    </div>
{% else %}
    <div>
        Automatically populated
        {% if role.creation_timestamp is not none %}
            on {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
        {% if role.submission.matching_record is not none %}
            {% set attempt = role.submission.matching_record.matching_attempt %}
            from match <strong>{{ attempt.name }}</strong>
        {% endif %}
    </div>
{% endif %}
{% if role.last_edited_by is not none %}
    <div class="mt-1 text-muted">
        Last edited by <i class="fs fa-user-circle"></i>
        <a class="text-decoration-none" href="mailto:{{ role.last_edited_by.email }}">{{ role.last_edited_by.name }}</a>
        {% if role.last_edit_timestamp is not none %}
            on {{ role.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    </div>
{% endif %}
"""


def edit_roles(roles: List[SubmissionRole], return_url=None):
    data = [{'name': render_template_string(_name, user=r.user),
             'role': r.role_label,
             'details': render_template_string(_details, role=r),
             'menu': render_template_string(_menu, role=r, return_url=return_url)} for r in roles]

    return data
