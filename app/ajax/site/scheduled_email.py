#
# Created by David Seery on 28/09/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string
from typing import List

from ...models import EmailNotification


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="{{ user.email }}">{{ user.name }}</a>
"""


# language=jinja2
_type = \
"""
{{ e.event_label|safe }}
{% if e.held %}
    <span class="badge bg-warning text-dark">HELD</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        {% if e.held %}
            <a class="dropdown-item" href="{{ url_for('admin.release_notification', eid=e.id) }}">
                <i class="fas fa-play-circle fa-fw"></i> Release
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('admin.hold_notification', eid=e.id) }}">
                <i class="fas fa-pause-circle fa-fw"></i> Hold
            </a>
        {% endif %}
        <a class="dropdown-item" href="{{ url_for('admin.delete_notification', eid=e.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def scheduled_email(notifications: List[EmailNotification]):
    data = [{'recipient': render_template_string(_name, user=e.owner),
             'timestamp': e.timestamp.strftime("%a %d %b %Y %H:%M:%S"),
             'type': render_template_string(_type, e=e),
             'details': str(e),
             'menu': render_template_string(_menu, e=e)} for e in notifications]

    return data
