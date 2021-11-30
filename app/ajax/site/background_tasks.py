#
# Created by David Seery on 06/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

# language=jinja2
_state = \
"""
{% if state == 0 %}
    <span class="badge bg-info text-dark">PENDING</span>
{% elif state == 1 %}
    <span class="badge bg-info text-dark">RUNNING</span>
{% elif state == 2 %}
    <span class="badge bg-success">SUCCESS</span>
{% else %}
    <span class="badge bg-danger">FAILED</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-o border-0 dropdown-menu-end">
        {% if t.status == t.PENDING or t.status == t.RUNNING %}
            <a class="dropdown-item" href="{{ url_for('admin.terminate_background_task', id=t.id) }}">
                <i class="fas fa-hand-paper fa-fw"></i> Terminate
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('admin.delete_background_task', id=t.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% endif %}
    </div>
</div>
"""


def background_task_data(tasks):

    data = [{'id': t.id,
             'owner': '<a class="text-decoration-none" href="mailto:{em}">{nm}</a>'.format(nm=t.owner.name,
                                                              em=t.owner.email) if t.owner is not None
                else '<span class="badge bg-secondary">Nobody</span>',
             'name': t.name,
             'description': t.description,
             'start_at': {
                 'display': t.start_date.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': t.start_date.timestamp()
             },
             'status': render_template_string(_state, state=t.status),
             'progress': '{c}%'.format(c=t.progress),
             'message': t.message,
             'menu': render_template_string(_menu, t=t)} for t in tasks]

    return jsonify(data)
