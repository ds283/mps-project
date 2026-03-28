#
# Created by David Seery on 28/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, current_app, request
from jinja2 import Template, Environment
from sqlalchemy import func

from ...database import db
from ...models import CanvasStudent, ProjectClassConfig
from ...tools.ServerSideProcessing import ServerSideSQLHandler

# language=jinja2
_name = """
{% if cs.student is not none %}
    {{ cs.student.user.name }}
{% else %}
    {{ cs.first_name }} {{ cs.last_name }}
{% endif %}
"""

# language=jinja2
_email = """
<a href="mailto:{{ cs.email }}">{{ cs.email }}</a>
"""

# language=jinja2
_status = """
{% if cs.student is not none %}
    <span class="badge bg-success">
        <i class="fas fa-check-circle fa-fw"></i> Matched
    </span>
    <div class="small text-muted mt-1">{{ cs.student.user.username }}</div>
{% else %}
    <span class="badge bg-warning text-dark"
          data-bs-toggle="tooltip"
          title="No student record was found in the MPS database for email address {{ cs.email }}. Manual action is required to resolve this.">
        <i class="fas fa-exclamation-circle fa-fw"></i> Unmatched
    </span>
{% endif %}
"""

# language=jinja2
_actions = """
{% if cs.student is not none %}
    {% if already_enrolled %}
        <span class="badge bg-success">
            <i class="fas fa-check fa-fw"></i> Already enrolled
        </span>
    {% else %}
        <a href="{{ url_for('convenor.enrol_canvas_student', cid=cs.id) }}" class="btn btn-warning btn-sm">
            <i class="fas fa-plus fa-fw"></i> Enrol
        </a>
    {% endif %}
{% else %}
    <span class="badge bg-secondary"
          data-bs-toggle="tooltip"
          title="Automatic enrolment is not possible: institutional data (student number, degree programme, cohort year) is not available from Canvas.">
        <i class="fas fa-times-circle fa-fw"></i> Cannot enrol
    </span>
{% endif %}
"""


def _build_templ(src: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(src)


def _is_enrolled(cs: CanvasStudent, config: ProjectClassConfig) -> bool:
    if cs.student_id is None:
        return False
    return (
            config.submitting_students.filter_by(student_id=cs.student_id, retired=False).first()
            is not None
    )


def canvas_missing_data(config: ProjectClassConfig):
    base_query = db.session.query(CanvasStudent).filter(CanvasStudent.config_id == config.id)

    name_col = {
        "search": func.concat(CanvasStudent.first_name, " ", CanvasStudent.last_name),
        "order": [CanvasStudent.last_name, CanvasStudent.first_name],
        "search_collation": "utf8_general_ci",
    }
    email_col = {
        "search": CanvasStudent.email,
        "order": CanvasStudent.email,
        "search_collation": "utf8_general_ci",
    }
    status_col = {}
    actions_col = {}

    columns = {
        "name": name_col,
        "email": email_col,
        "status": status_col,
        "actions": actions_col,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        name_templ = _build_templ(_name)
        email_templ = _build_templ(_email)
        status_templ = _build_templ(_status)
        actions_templ = _build_templ(_actions)

        def row_formatter(rows):
            return [
                {
                    "name": render_template(name_templ, cs=cs),
                    "email": render_template(email_templ, cs=cs),
                    "status": render_template(status_templ, cs=cs),
                    "actions": render_template(
                        actions_templ,
                        cs=cs,
                        config=config,
                        already_enrolled=_is_enrolled(cs, config),
                    ),
                }
                for cs in rows
            ]

        return handler.build_payload(row_formatter)
