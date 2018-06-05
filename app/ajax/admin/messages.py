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


_messages_pclasses = \
"""
{% for pclass in message.project_classes %}
    <span class="label label-info">{{ pclass.name }}</span>
{% else %}
    <span class="label label-default">Broadcast</span>
{% endfor %}
"""

_messages_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_message', id=message.id) }}">
                <i class="fa fa-pencil"></i> Edit message
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.delete_message', id=message.id) }}">
                <i class="fa fa-trash"></i> Delete message
            </a>
        </li>
        <li role="separator" class="divider"></li>
        {% if message.dismissible %}
            {% set dismiss_count = message.dismissed_by.count() %}
            {% set dpl = 's' %}
            {% if dismiss_count == 1 %}
                {% set dpl = '' %}
            {% endif %}
            {% if dismiss_count > 0 %}
                <li>
                    <a href="{{ url_for('admin.reset_dismissals', id=message.id) }}">
                        Reset {{ dismiss_count }} dismissal{{ dpl }}
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a>No dismissals</a>
                </li>
            {% endif %}
        {% else %}
            <li class="disabled">
                <a>Not dismissible</a>
            </li>
        {% endif %}
    </ul>
</div>
"""


def messages_data(messages):

    data = []

    for message in messages:
        data.append({ 'poster': message.user.build_name(),
                      'email': '<a href="{email}">{email}</a>'.format(email=message.user.email),
                      'date': message.issue_date.strftime("%a %d %b %Y %H:%M:%S"),
                      'students': 'Yes' if message.show_students else 'No',
                      'faculty': 'Yes' if message.show_faculty else 'No',
                      'login': 'Yes' if message.show_login else 'No',
                      'pclass': render_template_string(_messages_pclasses, message=message),
                      'title': '<a href="{url}">{msg}</a>'.format(msg=message.title,
                                                                  url=url_for('admin.edit_message', id=message.id))
                            if message.title is not None and len(message.title) > 0
                                else '<span class="label label-default">No title</span>',
                      'menu': render_template_string(_messages_menu, message=message)
                    })

    return jsonify(data)
