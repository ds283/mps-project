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

from ...database import db
from ...models import User, Role
from ...cache import cache

from sqlalchemy.event import listens_for

from .shared import menu, name


_roles = \
"""
{% for r in user.roles %}
    {{ r.make_label()|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


_status = \
"""
{% if u.login_count is not none %}
    {% set pl = 's' %}{% if u.login_count == 1 %}{% set pl = '' %}{% endif %}
    <span class="label label-primary">{{ u.login_count }} login{{ pl }}</span>
{% else %}
    <span class="label label-danger">No logins</span>
{% endif %}
{% if u.last_active is not none %}
    <span class="label label-info">Last seen at {{ u.last_active.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="label label-warning">No last seen time</span>
{% endif %}
{% if u.last_login_at is not none %}
    <span class="label label-info">Last login at {{ u.last_login_at.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="label label-warning">No last login time</span>
{% endif %}
{% if u.last_login_ip is not none and u.last_login_ip|length > 0 %}
    <span class="label label-info">Last login IP {{ u.last_login_ip }}</span>
{% else %}
    <span class="label label-default">No last login IP</span>
{% endif %}
{% if u.last_precompute is not none %}
    <span class="label label-info">Last precompute at {{ u.last_precompute.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="label label-default">No last precompute time</span>
{% endif %}
"""


@cache.memoize()
def _element(user_id, current_user_id):
    u = db.session.query(User).filter_by(id=user_id).one()
    cu = db.session.query(User).filter_by(id=current_user_id).one()

    return {'name': {
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
                 'timestamp': 0
             },
             'active': u.active_label,
             'details': {
                 'display': render_template_string(_status, u=u),
                 'timestamp': u.last_active.timestamp() if u.last_active is not None
                 else (u.last_login_at.timestamp() if u.last_login_at is not None else 0)
             },
             'role': render_template_string(_roles, user=u),
             'menu': render_template_string(menu, user=u, cuser=cu, pane='accounts')}


@listens_for(User, 'before_insert')
def _User_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(User, 'before_update')
def _User_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(User, 'before_delete')
def _User_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(User.roles, 'append')
def _User_role_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(User.roles, 'remove')
def _User_role_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


def build_accounts_data(user_ids, current_user_id):
    data = [_element(u_id, current_user_id) for u_id in user_ids]

    return jsonify(data)
