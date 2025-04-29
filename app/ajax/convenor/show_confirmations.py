#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from flask import jsonify, render_template_string, get_template_attribute

# language=jinja2
_student = """
<a class="text-decoration-none" href="mailto:{{ req.owner.student.user.email }}">{{ req.owner.student.user.name }}</a>
"""


# language=jinja2
_project = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=req.project.id, text='outstanding confirmations', url=url_for('convenor.show_confirmations', id=pclass_id)) }}">
    {{ req.project.name }}
</a>
"""


# language=jinja2
_supervisor = """
<a class="text-decoration-none" href="mailto:{{ req.project.owner.user.email }}">{{ req.project.owner.user.name }}</a>
"""


# language=jinja2
_timestamps = """
{{ format_confirm_timestamps(req, now) }}
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
    {% set sel = req.owner %}
    {% set project = req.project %}
    {% set config = sel.config %}
    {% set lifecycle = config.selector_lifecycle %}
    {% if lifecycle >= config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and lifecycle <= config.SELECTOR_LIFECYCLE_READY_MATCHING %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.confirm', sid=sel.id, pid=project.id) }}">
            <i class="fas fa-check fa-fw"></i> Confirm
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.cancel_confirm', sid=sel.id, pid=project.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    {% else %}
        <a class="dropdown-item d-flex gap-2 disabled">
            <i class="fas fa-check fa-fw"></i> Confirm
        </a>
        <a class="dropdown-item d-flex gap-2 disabled">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    {% endif %}
    </div>
</div>
"""


def show_confirmations(outstanding, pclass_id):
    now = datetime.now()
    format_confirm_timestamps = get_template_attribute("ui_elements/confirm_requests.html", "format_confirm_timestamps")

    data = [
        {
            "name": {
                "display": render_template_string(_student, req=req),
                "sortstring": req.owner.student.user.last_name + req.owner.student.user.first_name,
            },
            "project": render_template_string(_project, req=req, pclass_id=pclass_id),
            "supervisor": render_template_string(_supervisor, req=req),
            "timestamps": {
                "display": render_template_string(_timestamps, req=req, now=now, format_confirm_timestamps=format_confirm_timestamps),
                "timestamp": req.request_timestamp.timestamp() if req.request_timestamp is not None else 0,
            },
            "menu": render_template_string(_menu, req=req),
        }
        for req in outstanding
    ]

    return jsonify(data)
