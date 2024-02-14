#
# Created by David Seery on 2019-02-27.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from flask import current_app
from jinja2 import Template, Environment

_title = """
{% set project = r.parent %}
{% set pclass = project.project_classes.first() %}
{% set disabled = (pclass is none) %}
<a {% if not disabled %}href="{{ url_for('faculty.project_preview', id=r.parent.id, pclass=pclass.id, show_selector=0, url=url, text=text) }}"{% endif %}>
    {%- if project -%}{{ project.name }}{%- else -%}<unnamed project>{%- endif -%}/{%- if r.label -%}{{ r.label }}{%- else -%}<unnamed description>{%- endif -%}
</a>
{% if not project.is_offerable %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
    <div>
        This project has validation errors that will prevent it from being published.
    </div>
{% endif %}
<div>
    {% if project.has_new_comments(current_user) %}
        <span class="badge bg-warning text-dark">New comments</span>
    {% endif %}
</div>
"""


_owner = """
{% if p.generic %}
    <span class="badge bg-secondary">Generic</span>
{% else %}
    {% set fac = p.owner %}
    {% if fac is not none %}
        <a class="text-decoration-none" href="mailto:{{ fac.user.email }}">{{ fac.user.name }}</a>
    {% else %}
        <span class="badge bg-danger">Missing</span>
    {% endif %}
{% endif %}
"""


_pclasses = """
{% set ns = namespace(count=0) %}
{% if r.default is not none %}
    <span class="badge bg-success">Default</span>
    {% set ns.count = ns.count + 1 %}
{% endif %}
{% for pclass in r.project_classes %}
    {% if pclass.active %}
        {% set style = pclass.make_CSS_style() %}
        <a class="badge text-decoration-none text-nohover-dark bg-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
        {% set ns.count = ns.count + 1 %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="badge bg-secondary">None</span>
{% endif %}
{% if r.has_modules %}
    <p></p>
    <span class="badge bg-primary"><i class="fas fa-exclamation-circle"></i> Has recommended modules</span>
{% endif %}
"""


def build_title_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_title)


def build_owner_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_owner)


def build_pclasses_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_pclasses)