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

from .shared import menu


_roles = \
"""
{% if user.has_role('faculty') %}
   <span class="label label-info">faculty</span>
{% elif user.has_role('office') %}
   <span class="label label-info">office</span>
{% elif user.has_role('student') %}
   <span class="label label-info">student</span>
{% endif %}
{% if user.has_role('exec') %}
   <span class="label label-primary">exec</span>
{% endif %}
{% if user.has_role('admin') %}
   <span class="label label-warning">admin</span>
{% endif %}
{% if user.has_role('root') %}
   <span class="label label-danger">sysadmin</span>
{% endif %}
"""


def build_accounts_data(users):

    data = [{'name': {
                'display': u.name,
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
             'role': render_template_string(_roles, user=u),
             'menu': render_template_string(menu, user=u, pane='accounts')} for u in users]

    return jsonify(data)
