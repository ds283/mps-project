#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


# language=jinja2
_messages_pclasses = \
"""
{% for pclass in message.project_classes %}
    <span class="badge bg-info text-dark">{{ pclass.name }}</span>
{% else %}
    <span class="badge bg-secondary">Broadcast</span>
{% endfor %}
"""

# language=jinja2
_messages_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        <a class="dropdown-item" href="{{ url_for('admin.edit_message', id=message.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit message
        </a>
        <a class="dropdown-item" href="{{ url_for('admin.delete_message', id=message.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete message
        </a>

        <div role="separator" class="dropdown-divider"></div>
        {% if message.dismissible %}
            {% set dismiss_count = message.dismissed_by.count() %}
            {% set dpl = 's' %}
            {% if dismiss_count == 1 %}{% set dpl = '' %}{% endif %}
            {% if dismiss_count > 0 %}
                <a class="dropdown-item" href="{{ url_for('admin.reset_dismissals', id=message.id) }}">
                    Reset {{ dismiss_count }} dismissal{{ dpl }}
                </a>
            {% else %}
                <a class="dropdown-item disabled">No dismissals</a>
            {% endif %}
        {% else %}
            <a class="dropdown-item disabled">Not dismissible</a>
        {% endif %}
    </div>
</div>
"""


def messages_data(messages):
    data = [{'poster': m.user.name,
             'email': '<a href="{email}">{email}</a>'.format(email=m.user.email),
             'date': {
                 'display': m.issue_date.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': m.issue_date.timestamp()
             },
             'students': 'Yes' if m.show_students else 'No',
             'faculty': 'Yes' if m.show_faculty else 'No',
             'login': 'Yes' if m.show_login else 'No',
             'pclass': render_template_string(_messages_pclasses, message=m),
             'title': '<a href="{url}">{msg}</a>'.format(msg=m.title,
                                                         url=url_for('admin.edit_message', id=m.id))
                 if m.title is not None and len(m.title) > 0 else '<span class="badge bg-secondary">No title</span>',
             'menu': render_template_string(_messages_menu, message=m)} for m in messages]

    return jsonify(data)
