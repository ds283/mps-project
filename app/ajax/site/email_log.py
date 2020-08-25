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


_email_log_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('admin.delete_email', id=e.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        <a class="dropdown-item" href="{{ url_for('admin.display_email', id=e.id) }}">
            <i class="fas fa-eye fa-fw"></i> View email
        </a>
    </div>
</div>
"""


_name = \
"""
{% if e.user is not none %}
    <a href="mailto:{{ e.user.email }}" {% if e.user.last_email %}data-toggle="tooltip" title="Last notification at {{ e.user.last_email.strftime("%a %d %b %Y %H:%M:%S") }}"{% endif %}>{{ e.user.name }}</a>
{% else %}
    <span class="badge badge-warning">Not logged</span>
{% endif %}
"""


_address = \
"""
{% if e.user is not none %}
    <a href="mailto:{{ e.user.email }}">{{ e.user.email }}</a>
{% elif e.recipient %}
    {{ e.recipient }}
{% else %}
    <span class="badge badge-danger">Invalid address or recipient</span>
{% endif %}
"""

_subject = \
"""
<a href="{{ url_for('admin.display_email', id=e.id) }}">{{ e.subject }}</a>
"""


def email_log_data(emails):
    data = [{'recipient': render_template_string(_name, e=e),
             'address': render_template_string(_address, e=e),
             'date': e.send_date.strftime("%a %d %b %Y %H:%M:%S"),
             'subject': render_template_string(_subject, e=e),
             'menu': render_template_string(_email_log_menu, e=e)} for e in emails]

    return data
