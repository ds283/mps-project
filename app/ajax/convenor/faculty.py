#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Tuple

from flask import get_template_attribute, render_template, current_app
from jinja2 import Template, Environment

from ...models import ProjectClass, ProjectClassConfig, User, FacultyData

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if userdata.is_enrolled(pclass) %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.unenroll', userid=user.id, pclassid=pclass.id) }}">
                <i class="fas fa-trash fa-fw"></i> Remove enrolment
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.enroll', userid=user.id, pclassid=pclass.id) }}">
                <i class="fas fa-plus fa-fw"></i> Enrol
            </a>
        {% endif %}
        {% set record = userdata.get_enrollment_record(pclass) %}
        <a class="dropdown-item d-flex gap-2 {% if record is none %}disabled{% endif %}" {% if record is not none %}href="{{ url_for('manage_users.edit_enrollment', id=record.id, url=url_for('convenor.faculty', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Edit enrolment...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if record is none %}disabled{% endif %}" {% if record is not none %}href="{{ url_for('convenor.custom_CATS_limits', record_id=record.id) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Custom CATS limits...
        </a>
    </div>
</div>
"""

# language=jinja2
_golive = """
{% if config.require_confirm %}
    {% if config.requests_issued %}
        {% if config.is_confirmation_required(userdata) %}
            <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Outstanding</span>
        {% else %}
            {% if userdata.is_enrolled(pclass) %}
                {% set record = userdata.get_enrollment_record(pclass.id) %}
                {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
                    <span class="badge bg-success"><i class="fas fa-check"></i> Confirmed</span>
                {% elif record.supervisor_state == record.SUPERVISOR_SABBATICAL %}
                    <span class="badge bg-secondary"><i class="fas fa-check"></i> Sabbatical</span>
                {% elif record.supervisor_state == record.SUPERVISOR_EXEMPT %}
                    <span class="badge bg-secondary"><i class="fas fa-check"></i> Exempt</span>
                {% else %}
                    <span class="badge bg-danger">Unknown</span>
                {% endif %}
            {% else %}
                <span class="badge bg-secondary">Not enrolled</span>
            {% endif %}
        {% endif %}
    {% else %}
        <span class="badge bg-danger">Not yet issued</span>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">Disabled</span>
{% endif %}
"""

# language=jinja2
_projects = """
{{ simple_label(d.projects_supervisable_label(pclass)) }}
{{ simple_label(d.projects_offered_label(pclass)) }}
{{ simple_label(d.projects_unofferable_label) }}
{{ simple_label(d.supervisor_pool_label(pclass)) }}
{{ simple_label(d.assessor_label) }}
"""

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ u.email }}">{{ u.name }}</a>
"""

# language=jinja2
_enrolments = """
{% if er is not none %}
    {{ simple_label(er.enrolled_labels) }}
    {% if er.CATS_supervision is not none or er.CATS_marking is not none or er.CATS_moderation is not none or er.CATS_presentation is not none %}
        <div class="small fw-semibold mt-1">Enrolment CATS limits</div>
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 mt-1 small">
            {% if er.CATS_supervision is not none %}
                <span class="text-primary">S: {{ er.CATS_supervision }} CATS</span>
            {% endif %}
            {% if er.CATS_marking is not none %}
                <span class="text-primary">Mk: {{ er.CATS_marking }} CATS</span>
            {% endif %}
            {% if er.CATS_moderation is not none %}
                <span class="text-primary">Mo: {{ er.CATS_moderation }} CATS</span>
            {% endif %}
            {% if er.CATS_presentation is not none %}
                <span class="text-primary">P: {{ er.CATS_presentation }} CATS</span>
            {% endif %}
        </div>
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1 mt-1 small">
            <a class="btn btn-sm btn-outline-secondary small" href="{{ url_for('convenor.remove_CATS_limits', record_id=er.id) }}"><i class="fas fa-trash"></i> Reset limits</a>
        </div>
    {% endif %}
    {% if d.CATS_supervision is not none or d.CATS_marking is not none or d.CATS_moderation is not none or d.CATS_presentation is not none %}
        <div class="small fw-semibold mt-1">Global CATS limits</div>
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 mt-1 small">
            {% if d.CATS_supervision is not none %}
                <span class="text-primary">S: {{ d.CATS_supervision }} CATS</span>
            {% endif %}
            {% if d.CATS_marking is not none %}
                <span class="text-primary">Mk: {{ d.CATS_marking }} CATS</span>
            {% endif %}
            {% if d.CATS_moderation is not none %}
                <span class="text-primary">Mo: {{ d.CATS_moderation }} CATS</span>
            {% endif %}
            {% if d.CATS_presentation is not none %}
                <span class="text-primary">P: {{ d.CATS_presentation }} CATS</span>
            {% endif %}
        </div>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">Not enrolled</span>
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_enrolments_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_enrolments)


def _build_projects_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_projects)


def _build_golive_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_golive)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def faculty_data(
        pclass: ProjectClass,
        config: ProjectClassConfig,
        row_list: List[Tuple[User, FacultyData]],
):
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    enrolments_templ: Template = _build_enrolments_templ()
    projects_templ: Template = _build_projects_templ()
    golive_templ: Template = _build_golive_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, u=u, d=fd, pclass_id=pclass.id),
            "email": '<a class="text-decoration-none" href="mailto:{em}">{em}</a>'.format(
                em=u.email
            ),
            "user": u.username,
            "enrolled": render_template(
                enrolments_templ,
                d=fd,
                er=er,
                pclass_id=pclass.id,
                simple_label=simple_label,
            ),
            "projects": render_template(
                projects_templ, d=fd, pclass=pclass, simple_label=simple_label
            ),
            "golive": render_template(
                golive_templ, config=config, pclass=pclass, user=u, userdata=fd
            ),
            "menu": render_template(menu_templ, pclass=pclass, user=u, userdata=fd),
        }
        for u, fd, er in row_list
    ]

    return data
