#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string


# language=jinja2
_email_log_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.delete_email', id=e.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.display_email', id=e.id) }}">
            <i class="fas fa-eye fa-fw"></i> View email
        </a>
    </div>
</div>
"""


# language=jinja2
_names = \
"""
{% for user in e.recipients %}
    <div>
        <a href="mailto:{{ user.email }}" {% if user.last_email %}data-bs-toggle="tooltip" title="Last notification at {{ user.last_email.strftime("%a %d %b %Y %H:%M:%S") }}"{% endif %}>{{ user.name }}</a>
    </div>
{% else %}
  <span class="badge bg-warning">Not logged</span>
{% endfor %}
"""


# language=jinja2
_addresses = \
"""
{% for user in e.recipients %}
    <div>
        <a class="text-decoration-none" href="mailto:{{ user.email }}">{{ user.email }}</a>
    </div>
{% else %}
    <span class="badge bg-warning">Invalid/span>
{% endfor %}
"""

# language=jinja2
_subject = \
"""
<a class="text-decoration-none" href="{{ url_for('admin.display_email', id=e.id) }}">{{ e.subject }}</a>
"""


def email_log_data(emails):
    data = [{'recipient': render_template_string(_names, e=e),
             'address': render_template_string(_addresses, e=e),
             'date': e.send_date.strftime("%a %d %b %Y %H:%M:%S"),
             'subject': render_template_string(_subject, e=e),
             'menu': render_template_string(_email_log_menu, e=e)} for e in emails]

    return data
