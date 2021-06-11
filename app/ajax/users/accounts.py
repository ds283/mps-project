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
from sqlalchemy.event import listens_for

from .shared import menu, name
from ...cache import cache
from ...database import db
from ...models import User, Role
from ...shared.utils import detuple


# language=jinja2
_roles = \
"""
{% for r in user.roles %}
    {{ r.make_label()|safe }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
"""


# language=jinja2
_status = \
"""
{% if u.login_count is not none %}
    {% set pl = 's' %}{% if u.login_count == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge bg-primary">{{ u.login_count }} login{{ pl }}</span>
{% else %}
    <span class="badge bg-danger">No logins</span>
{% endif %}
{% if u.last_active is not none %}
    <span class="badge bg-info text-dark">Last seen at {{ u.last_active.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="badge bg-warning text-dark">No last seen time</span>
{% endif %}
{% if u.last_login_at is not none %}
    <span class="badge bg-info text-dark">Last login at {{ u.last_login_at.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="badge bg-warning text-dark">No last login time</span>
{% endif %}
{% if u.last_login_ip is not none and u.last_login_ip|length > 0 %}
    <span class="badge bg-info text-dark">Last login IP {{ u.last_login_ip }}</span>
{% else %}
    <span class="badge bg-secondary">No last login IP</span>
{% endif %}
{% if u.last_precompute is not none %}
    <span class="badge bg-info text-dark">Last precompute at {{ u.last_precompute.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="badge bg-secondary">No last precompute time</span>
{% endif %}
"""


@cache.memoize()
def _element(user_id, current_user_id):
    u = db.session.query(User).filter_by(id=user_id).one()
    cu = db.session.query(User).filter_by(id=current_user_id).one()

    return {'name': render_template_string(name, u=u),
             'user': u.username,
             'email': '<a href="mailto:{m}">{m}</a>'.format(m=u.email),
             'confirm': u.confirmed_at.strftime("%Y-%m-%d %H:%M:%S") if u.confirmed_at is not None \
                        else '<span class="badge bg-warning text-dark">Not confirmed</span>',
             'active': u.active_label,
             'details': render_template_string(_status, u=u),
             'role': render_template_string(_roles, user=u),
             'menu': render_template_string(menu, user=u, cuser=cu, pane='accounts')}


def _process(user_id, current_user_id):
    u = db.session.query(User).filter_by(id=user_id).one()

    record = _element(user_id, current_user_id)

    name = record['name']
    if u.currently_active:
        name = name.replace('REPACTIVE', '<span class="badge bg-success">ACTIVE</span>', 1)
    else:
        name = name.replace('REPACTIVE', '', 1)

    record.update({'name': name})

    return record


def _delete_cache_entry(user_id):
    ids = db.session.query(User.id).filter_by(active=True).all()
    for id in ids:
        cache.delete_memoized(_element, user_id, id[0])


@listens_for(User, 'before_insert')
def _User_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(User, 'before_update')
def _User_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(User, 'before_delete')
def _User_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(User.roles, 'append')
def _User_role_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(User.roles, 'remove')
def _User_role_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


def _delete_cache_entry_role_change(role):
    for user in role.users:
        _delete_cache_entry(user.id)


@listens_for(Role, 'before_update')
def _Role_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        # this turns out to be an extremely expensive flush, so we want to avoid it
        # if all that is happening is that we're creating a new user that modified Role's backref
        # collection 'users'
        if db.object_session(target).is_modified(target, include_collections=False):
            _delete_cache_entry_role_change(target)


@listens_for(Role, 'before_delete')
def _Role_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry_role_change(target)


def build_accounts_data(current_user_id, user_ids):
    data = [_process(detuple(u_id), current_user_id) for u_id in user_ids]

    return data
