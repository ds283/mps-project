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
_name = """
<a href="mailto:{{ user.email }}">{{ user.name }}</a>
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_role', role_id=role.id, url=return_url) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit&hellip;
        </a>
        <div role="separator" class="dropdown-divider"></div>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_role', role_id=role.id, url=return_url) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


# language=jinja2
_role = """
<div>{{ role.role_as_str }}</div>
{% if role.role in [role.ROLE_SUPERVISOR, role.ROLE_RESPONSIBLE_SUPERVISOR] %}
    {% if role.grade is not none %}
        <div class="mt-1 small">
            <i class="fas fa-star fa-fw"></i> Grade: <strong>{{ role.grade }}%</strong>
        </div>
    {% endif %}
    {% if role.weight is not none %}
        <div class="mt-1 small">
            <i class="fas fa-balance-scale fa-fw"></i> Weight: <strong>{{ role.weight }}</strong>
        </div>
    {% endif %}
{% endif %}
"""


# language=jinja2
_details = """
{% if role.created_by is not none %}
    <div class="small">
        Created by
        <i class="fas fa-user-circle"></i>
        <a class="text-decoration-none" href="mailto:{{ role.created_by.email }}">{{ role.created_by.name }}</a>
        {% if role.creation_timestamp is not none %}
            on {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    </div>
{% else %}
    {% if role.role in [role.ROLE_SUPERVISOR, role.ROLE_RESPONSIBLE_SUPERVISOR, role.ROLE_MARKER] %}
        <div class="small">
            Automatically populated
            {% if role.creation_timestamp is not none %}
                on {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
            {% endif %}
            {% if role.submission.matching_record is not none %}
                {% set attempt = role.submission.matching_record.matching_attempt %}
                from match <strong>{{ attempt.name }}</strong>
            {% endif %}
        </div>
    {% elif role.role == role.ROLE_PRESENTATION_ASSESSOR %}
        <div class="small">
            Automatically populated
            {% if role.creation_timestamp is not none %}
                on {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
            {% endif %}
            {% if role.schedule_slot is not none %}
                {% set slot = role.schedule_slot %}
                {% set attempt = slot.owner %}
                {% set assessment = attempt.owner %}
                from assessment slot
                {% if slot.session is not none %}
                    <strong>{{ slot.session.label_as_string }}</strong>
                    {% if slot.room is not none %}
                        in room <strong>{{ slot.room.full_name }}</strong>
                    {% endif %}
                {% endif %}
                in schedule <strong>{{ attempt.name }}</strong>
                (assessment: <strong>{{ assessment.name }}</strong>)
            {% endif %}
        </div>
    {% elif role.role in [role.ROLE_MODERATOR, role.ROLE_EXAM_BOARD, role.ROLE_EXTERNAL_EXAMINER] %}
        <div class="small text-muted">
            <i class="fas fa-question-circle fa-fw"></i> Origin of role is unknown
            {% if role.creation_timestamp is not none %}
                (recorded {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }})
            {% endif %}
        </div>
    {% else %}
        <div class="small">
            Automatically populated
            {% if role.creation_timestamp is not none %}
                on {{ role.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
            {% endif %}
        </div>
    {% endif %}
{% endif %}
{% if role.last_edited_by is not none %}
    <div class="mt-1 small">
        Last edited by <i class="fas fa-user-circle"></i>
        <a class="text-decoration-none" href="mailto:{{ role.last_edited_by.email }}">{{ role.last_edited_by.name }}</a>
        {% if role.last_edit_timestamp is not none %}
            on {{ role.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    </div>
{% endif %}
"""


def edit_roles(roles: List[SubmissionRole], return_url=None):
    data = [
        {
            "name": render_template_string(_name, user=r.user),
            "role": render_template_string(_role, role=r),
            "details": render_template_string(_details, role=r),
            "menu": render_template_string(_menu, role=r, return_url=return_url),
        }
        for r in roles
    ]

    return data
