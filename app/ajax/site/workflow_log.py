#
# Created by David Seery on 26/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template, render_template_string
from jinja2 import Environment

# language=jinja2
_user_cell = """
{% if e.initiator is not none %}
    <a class="text-decoration-none small"
       href="mailto:{{ e.initiator.email }}"><i class="fas fa-user-circle"></i> {{ e.initiator.name }}</a>
{% else %}
    <span class="badge bg-secondary">Background task</span>
{% endif %}
"""

# language=jinja2
_student_cell = """
{% if e.student is not none %}
    <div class="small"><i class="fas fa-user-circle"></i> {{ e.student.user.name }}</div>
    {% if e.student.exam_number %}
        <div class="text-muted small">{{ e.student.exam_number }}</div>
    {% endif %}
{% else %}
    <span class="text-muted small">—</span>
{% endif %}
"""

# language=jinja2
_pclasses_cell = """
{% set pclasses = e.project_classes.all() %}
{% if pclasses %}
    {% for pc in pclasses %}
        <span class="badge bg-info text-dark">{{ pc.abbreviation }}</span>
    {% endfor %}
{% else %}
    <span class="badge bg-light text-muted">—</span>
{% endif %}
"""

# language=jinja2
_summary_cell = """
<div class="text-muted small">{{ e.summary }}</div>
"""

# language=jinja2
_timestamp_cell = """
{% if e.timestamp %}
    <div class="small"><i class="fas fa-clock"></i> {{ e.timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</div>
{% else %}
    <span class="small text-danger"><i class="fas fa-ban"></i> Not recorded</span>
{% endif %}
"""

# language=jinja2
_endpoint_cell = """
{% if e.endpoint %}
    <div class="small fw-semibold text-primary">{{ e.endpoint }}</div>
{% else %}
    <span class="small text-danger"><i class="fas fa-ban"></i> Not recorded</span>
{% endif %}
"""


def workflow_log_data(entries):
    env: Environment = current_app.jinja_env

    user_tmpl = env.from_string(_user_cell)
    student_tmpl = env.from_string(_student_cell)
    pclasses_tmpl = env.from_string(_pclasses_cell)
    timestamp_tmpl = env.from_string(_timestamp_cell)
    endpoint_tmpl = env.from_string(_endpoint_cell)
    summary_tmpl = env.from_string(_summary_cell)

    data = [
        {
            "user": render_template(user_tmpl, e=e),
            "student": render_template(student_tmpl, e=e),
            "endpoint": render_template(endpoint_tmpl, e=e),
            "project_classes": render_template(pclasses_tmpl, e=e),
            "timestamp": render_template(timestamp_tmpl, e=e),
            "summary": render_template(summary_tmpl, e=e),
        }
        for e in entries
    ]

    return data
