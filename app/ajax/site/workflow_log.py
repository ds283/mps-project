#
# Created by David Seery on 26/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string

# language=jinja2
_user_cell = """
{% if e.initiator is not none %}
    <a class="text-decoration-none"
       href="mailto:{{ e.initiator.email }}">{{ e.initiator.name }}</a>
{% else %}
    <span class="badge bg-secondary">Background task</span>
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


def workflow_log_data(entries):
    data = [
        {
            "user": render_template_string(_user_cell, e=e),
            "endpoint": e.endpoint or "",
            "project_classes": render_template_string(_pclasses_cell, e=e),
            "timestamp": e.timestamp.strftime("%a %d %b %Y %H:%M:%S")
            if e.timestamp
            else "",
            "summary": e.summary or "",
        }
        for e in entries
    ]

    return data
