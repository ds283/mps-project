#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

from .shared import menu, name


_roles = \
"""
{% for r in roles %}
    {% if user.has_role(r.name) %}
        {{ r.make_label()|safe }}
    {% endif %}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


def build_accounts_data(users, roles):

    data = [{'name': {
                'display': render_template_string(name, u=u),
                'sortvalue': u.last_name + u.first_name
             },
             'user': u.username,
             'email': '<a href="mailto:{m}">{m}</a>'.format(m=u.email),
             'confirm': {
                 'display': u.confirmed_at.strftime("%Y-%m-%d %H:%M:%S"),
                 'timestamp': u.confirmed_at.timestamp()
             } if u.confirmed_at is not None else {
                 'display': '<span class="label label-warning">Not confirmed</span>',
                 'timestamp': None
             },
             'active': u.active_label,
             'count': '{c}'.format(c=u.login_count),
             'last_login': {
                 'display': u.last_login_at.strftime("%Y-%m-%d %H:%M:%S"),
                 'timestamp': u.last_login_at.timestamp()
             } if u.last_login_at is not None else {
                 'display': '<span class="label label-default">None</a>',
                 'timestamp': None
             },
             'ip': u.last_login_ip if u.last_login_ip is not None and len(u.last_login_ip) > 0
                 else '<span class="label label-default">None</a>',
             'role': render_template_string(_roles, user=u, roles=roles),
             'menu': render_template_string(menu, user=u, pane='accounts')} for u in users]

    return jsonify(data)
