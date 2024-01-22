#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from .shared import build_active_templ, build_menu_templ, build_name_templ
from ...cache import cache
from ...models import User

# language=jinja2
_roles = """
{% for r in user.roles %}
    {{ simple_label(r.make_label()) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
"""


# language=jinja2
_status = """
{% if u.login_count is not none %}
    {% set pl = 's' %}{% if u.login_count == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge bg-primary">{{ u.login_count }} login{{ pl }}</span>
{% else %}
    <span class="badge bg-danger">No logins</span>
{% endif %}
{% if u.last_active is not none %}
    <span class="small text-muted">Last seen at {{ u.last_active.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="small text-warning">No last seen time</span>
{% endif %}
<span class="small text-muted">|</span>
{% if u.last_login_at is not none %}
    <span class="small text-muted">Last login at {{ u.last_login_at.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="small text-warning">No last login time</span>
{% endif %}
<span class="small text-muted">|</span>
{% if u.last_login_ip is not none and u.last_login_ip|length > 0 %}
    <span class="small text-muted">Last login IP {{ u.last_login_ip }}</span>
{% else %}
    <span class="small text-warning">No last login IP</span>
{% endif %}
<span class="small text-muted">|</span>
{% if u.last_precompute is not none %}
    <span class="small text-muted">Last precompute at {{ u.last_precompute.strftime("%Y-%m-%d %H:%M:%S") }}</span>
{% else %}
    <span class="small text-muted">No last precompute time</span>
{% endif %}
"""


@cache.memoize()
def _build_roles_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_roles)


@cache.memoize()
def _build_status_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_status)


def build_accounts_data(current_user: User, users: List[User]):
    name_templ: Template = build_name_templ()
    roles_templ: Template = _build_roles_templ()
    status_templ: Template = _build_status_templ()
    active_templ: Template = build_active_templ()
    menu_templ: Template = build_menu_templ()

    simple_label = get_template_attribute("labels.html", "simple_label")

    return [
        {
            "name": render_template(name_templ, u=u, simple_label=simple_label),
            "user": u.username,
            "email": '<a class="text-decoration-none" href="mailto:{m}">{m}</a>'.format(m=u.email),
            "confirm": u.confirmed_at.strftime("%Y-%m-%d %H:%M:%S")
            if u.confirmed_at is not None
            else '<span class="badge bg-warning text-dark">Not confirmed</span>',
            "active": render_template(active_templ, u=u, simple_label=simple_label),
            "details": render_template(status_templ, u=u),
            "role": render_template(roles_templ, user=u, simple_label=simple_label),
            "menu": render_template(menu_templ, user=u, cuser=current_user, pane="accounts"),
        }
        for u in users
    ]
