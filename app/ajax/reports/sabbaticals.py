#
# Created by David Seery on 08/09/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from typing import List

from flask import render_template_string
from flask_security import current_user

from ...models import EnrollmentRecord


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ fac.user.email }}">{{ fac.user.name }}</a>
"""


# language=jinja2
_exemptions = \
"""
{% macro display(state, sabbatical_state, exempt_state, reenroll, comment) %}
    {% if state == sabbatical_state %}
        <span class="badge bg-info">Sabbatical</span>
        {% if reenroll %}
            <span class="badge bg-secondary">Re-enroll {{ reenroll }}</span>
        {% endif %}
    {% elif state == exempt_state %}
        <span class="badge bg-danger">Exempt</span>
    {% endif %}
    {% if comment and comment|length > 0 %}
        <div class="text-muted">{{ comment }}</div>
    {% endif %}
{% endmacro %}
{% if rec.pclass.uses_supervisor and rec.supervisor_state != rec.SUPERVISOR_ENROLLED %}
    <div class="mb-2">
        <strong class="mr-1">Supervising</strong>
        {{ display(rec.supervisor_state, rec.SUPERVISOR_SABBATICAL, rec.SUPERVISOR_EXEMPT, rec.supervisor_reenroll, rec.supervisor_comment) }}
    </div>
{% endif %}
{% if rec.pclass.uses_marker and rec.marker_state != rec.MARKER_ENROLLED %}
    <div class="mb-2">
        <strong class="mr-1">Marking</strong>
        {{ display(rec.marker_state, rec.MARKER_SABBATICAL, rec.MARKER_EXEMPT, rec.marker_reenroll, rec.marker_comment) }}
    </div>
{% endif %}
{% if rec.pclass.uses_moderator and rec.moderator_state != rec.MODERATOR_ENROLLED %}
    <div class="mb-2">
        <strong class="mr-1">Moderating</strong>
        {{ display(rec.moderator_state, rec.MODERATOR_SABBATICAL, rec.MODERATOR_EXEMPT, rec.moderator_reenroll, rec.moderator_comment) }}
    </div>
{% endif %}
{% if rec.pclass.uses_presentations and rec.presentations_state != rec.PRESENTATIONS_ENROLLED %}
    <div class="mb-2">
        <strong class="mr-1">Presentations</strong>
        {{ display(rec.presentations_state, rec.PRESENTATIONS_SABBATICAL, rec.PRESENTATIONS_EXEMPT, rec.presentations_reenroll, rec.presentations_comment) }}
    </div>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2 {% if not is_admin %}disabled{% endif %}" {% if is_admin %}href="{{ url_for('manage_users.edit_enrollment', id=rec.id, url=url_for('reports.sabbaticals')) }}"{% endif %}>
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
    </div>
</div>
"""


def sabbaticals(enrolments: List[EnrollmentRecord]):
    is_admin = current_user.has_role('admin') or current_user.has_role('root') or current_user.has_role('manage_users')

    data = [{'name': render_template_string(_name, fac=e.owner),
             'pclass': e.pclass.make_label(),
             'exemptions': render_template_string(_exemptions, rec=e),
             'menu': render_template_string(_menu, rec=e, is_admin=is_admin)} for e in enrolments]

    return data