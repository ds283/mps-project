#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import Optional

from flask import current_app, get_template_attribute, render_template
from jinja2 import Template, Environment
from sqlalchemy import Row

from ...database import db
from ...models import (
    EnrollmentRecord,
    ProjectDescription,
    User,
    ProjectClassConfig,
    ProjectLike, ProjectLikeList, ProjectDescLikeList,
)

# language=jinja2
_name = """
{%- set desc_issues = desc is not none and desc.has_issues -%}
{%- set project_issues = project is not none and project.has_issues -%}
{%- set has_issues = desc_issues or project_issues -%}
<div class="d-flex flex-column justify-content-start align-items-start gap-1">
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1">
        <a class="text-decoration-none {% if project.active and has_issues %}link-danger{% else %}link-primary{% endif %}" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            {{ project.name }}
        </a>
        {%- if project.active and has_issues -%}
            <i class="fas fa-exclamation-triangle text-danger"></i>
        {% endif %}
    </div>
    {% if desc is not none %}
        <span class="small text-secondary"><span class="fw-semibold">Variant:</span> {{ desc.label }}</span>
    {% else %}
        {%- set num = project.num_descriptions -%}
        {% if num > 0 %}
            {% set pl = 's' %}{% if num == 1 %}{% set pl = '' %}{% endif %}
            <span class="small text-secondary">{{ num }} variant{{ pl }}</span>
        {% endif %}
    {% endif %}
    {%- set num = project.number_alternatives -%}
    {% if num > 0 %}
        {% set pl = 's' %}{% if num == 1 %}{% set pl = '' %}{% endif %}
        <span class="small text-secondary">{{ num }} alternative{{ pl }}</span>
    {% endif %}
    {% if project.active %}
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1 small">
            {% if current_user is not none and project.has_new_comments(current_user) %}
                <span class="badge bg-warning text-dark">New comments</span>
            {% endif %}
            {% if in_selector %}
                <span class="badge bg-primary" data-bs-toggle="tooltip" title="A version of this project is live for students who are selecting in the current cycle">SELECTING</span>
            {% endif %}
            {% if in_submitter %}
                <span class="badge bg-primary" data-bs-toggle="tooltip" title="A version of this project is live and can be assigned for students who are submitting in the current cycle">SUBMITTING</span>
            {% endif %}
            {% if is_running %}
                <span class="badge bg-success" data-bs-toggle="tooltip" title="One or more students are submitters for this project in the current cycle">RUNNING</span>
            {% endif %} 
        </div>
        {% if name_labels %}
            <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-1">
                {% for pclass in project.project_classes %}
                    {% if pclass.active %}
                        {% set style = pclass.make_CSS_style() %}
                        <a class="badge text-decoration-none text-nohover-dark bg-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }}</a>
                    {% endif %}
                {% else %}
                    <span class="small text-danger"><i class="fas fa-times-circle"></i> No project classes</span>
                {% endfor %}
            </div>
        {% endif %}
        {% if show_errors %}
                {% if desc_issues %}
                    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start small gap-1">
                        <span>Variant issues</span>
                        {{ error_block_popover(desc.errors, desc.warnings) }}
                    </div>
                {% endif %}
                {% if project_issues %}
                    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start small gap-1">
                        <span>Project issues</span>
                        {{ error_block_popover(project.errors, project.warnings) }}
                    </div>
                {% endif %}
            </div>
        {% endif %}
    {% endif %}
</div>
"""


# language=jinja2
_error_block = """
"""


# language=jinja2
_owner = """
{% if project.generic %}
    <div class="fw-semibold text-secondary">Generic</div>
    {% set num = project.number_supervisors() %}
    <div class="mt-1 d-flex flex-row gap-2 justify-content-start align-items-center">
        {% if num > 0 %}
            <div class="mt-1 small text-muted">Pool size = {{ num }}</div>
        {% else %}
                <div class="mt-1 small text-danger">Pool size = 0</div>
        {% endif %}
        <a class="btn btn-xs btn-outline-secondary" href="{{ url_for('convenor.edit_project_supervisors', proj_id=project.id, url=url) }}">Edit</a>
    </div>
{% else %}
    {% if project.owner is not none %}
        <a class="text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
    {% else %}
        <span class="badge bg-danger">Missing</span>
    {% endif %}
{% endif %}
"""


# language=jinja2
_status = """
{% if not project.active %}
    <div class="text-danger small"><i class="fas fa-ban"></i> Project inactive</span>
{% else %}
    {% if project.is_offerable %}
        <div class="text-success small"><i class="fas fa-check-circle"></i> Project active</div>
        {% if e is not none %}
            {{ simple_label(e.supervisor_label) }}
        {% endif %}
        {% if project.has_published_pclass %}
            {% if desc is not none %}
                {% set state = desc.workflow_state %}
                {% if desc.requires_confirmation and not desc.confirmed %}
                    {% if waiting_confirmations and config is not none and desc is not none %}
                        <div class="d-flex flex-row gap-2 justify-content-left align-items-center">
                            <div class="text-danger small"><i class="fas fa-times-circle"></i> Not confirmed</div>
                            <div class="dropdown" style="display: inline-block;">
                                <a class="btn btn-xs btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">Actions</a>
                                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                                    <a class="dropdown-item d-flex gap-2" href="{{ url_for("convenor.confirm_description", config_id=config.id, did=desc.id) }}"><i class="fas fa-check fa-fw"></i> Confirm</a>
                                </div>
                            </div>
                        </div>
                    {% else %}
                        <div class="text-danger small"><i class="fas fa-times-circle"></i> Not confirmed</div>
                    {% endif %}
                {% else %}
                    {% if state == desc.WORKFLOW_APPROVAL_VALIDATED %}
                        <div class="text-success small"><i class="fas fa-check-circle"></i> Approved</div>
                        {% if desc.validated_by %}
                            <span class="small text-muted">
                                Signed off by {{ desc.validated_by.name }}
                                {% if desc.validated_timestamp %}
                                    {{ desc.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
                                {% endif %}
                            </span>
                        {% endif %}
                    {% elif state == desc.WORKFLOW_APPROVAL_QUEUED %}
                        <div class="text-danger small"><i class="fas fa-circle"></i> Approval: Confirmed</div>
                    {% elif state == desc.WORKFLOW_APPROVAL_REJECTED %}
                        <div class="text-primary small"><i class="fas fa-circle"></i> Approval: In progress</div>
                    {% else %}     
                        <span class="badge bg-danger">Unknown state</span>
                    {% endif %}
                {% endif %} 
            {% elif config is not none %}
                <span class="badge bg-warning text-dark">No description</span>
            {% else %}
                {% set state = project.approval_state %}
                {% if state == project.DESCRIPTIONS_APPROVED %}
                    <div class="text-success small"><i class="fas fa-check-circle"></i> Approved</div>
                {% elif state == project.SOME_DESCRIPTIONS_QUEUED %}
                    <div class="text-danger small"><i class="fas fa-circle"></i> Approval: Confirmed</div>
                {% elif state == project.SOME_DESCRIPTIONS_REJECTED %}
                    <div class="text-primary small"><i class="fas fa-circle"></i> Approval: In progress</div>
                {% elif state == project.SOME_DESCRIPTIONS_UNCONFIRMED %}
                    <div class="text-secondary small"><i class="fas fa-circle"></i> Approval: Not confirmed</div>
                {% elif state == project.APPROVALS_NOT_ACTIVE %}
                    <div class="text-danger small"><i class="fas fa-times-circle"></i> Approval: Not offerable/div>
                {% elif state == project.APPROVALS_NOT_OFFERABLE %}
                {% else %}
                    <span class="badge bg-danger">Approval: Unknown state</span>
                {% endif %}
            {% endif %}
        {% else %}
            <div class="text-danger small"><i class="fas fa-ban"></i> Can't approve/div>
        {% endif %}
    {% else %}
        <div class="text-secondary small"><i class="fas fa-ban"></i> Not available</div>
    {% endif %}
{% endif %}
"""


# language=jinja2
_pclasses = """
{% for pclass in project.project_classes %}
    {% set style = pclass.make_CSS_style() %}
    <a class="badge text-decoration-none text-nohover-dark bg-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
{% endfor %}
"""


# language=jinja2
_meetingreqd = """
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    <div class="text-danger small"><i class="fas fa-check-circle"></i> Required</div>
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <div class="text-secondary small"><i class="fas fa-circle"></i> Optional</div>
{% elif project.meeting_reqd == project.MEETING_NONE %}
    <div class="text-success small"><i class="fas fa-times-circle"></i> Not required</div>
{% else %}
    <div class="text-danger small"><i class="fas fa-exclamation-triangle"></i> Unknown</div>
{% endif %}
"""


# language=jinja2
_prefer = """
{% for programme in project.ordered_programmes %}
    {% if programme.active %}
        {{ simple_label(programme.short_label) }}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_skills = """
{% for skill in skills %}
    {% if skill.is_active %}
      {{ simple_label(skill.short_label) }}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_affiliation = """
{% set ns = namespace(affiliation=false) %}
{% if project.group %}
    {{ simple_label(project.group.make_label()) }}
    {% set ns.affiliation = true %}
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ simple_label(tag.make_label(truncate(tag.name[0:15]))) }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""


# language=jinja2
_faculty_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit project</div>

        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.edit_project', id=project.id, text=text, url=url) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.edit_descriptions', id=project.id) }}">
            <i class="fas fa-tools fa-fw"></i> Variants...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.attach_assessors', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.attach_skills', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Transferable skills...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.attach_programmes', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Degree programmes...
        </a>

        <div role="separator" class="dropdown-divider"></div>

        {% if project.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.deactivate_project', id=project.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.activate_project', id=project.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
        {% if project.is_deletable %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.delete_project', id=project.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-trash fa-fw"></i> Delete disabled
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_convenor_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit project</div>

        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=pclass_id, text=text, url=url) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-tools fa-fw"></i> Variants...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=pclass_id, url=url_for('convenor.attached', id=pclass_id), text='convenor projects view') }}">
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_project_alternatives', proj_id=project.id, url=url_for('convenor.attached', id=pclass_id), text='convenor projects view') }}">
            <i class="fas fa-cogs fa-fw"></i> Alternatives...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-cogs fa-fw"></i> Transferable skills...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-cogs fa-fw"></i> Degree programmes...
        </a>
        {% if select_in_previous_cycle %}
            {% if not in_selector or not in_submitter %}
                <div role="separator" class="dropdown-divider"></div>
            {% endif %}
            {% if not in_selector %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.inject_liveproject', pid=project.id, pclass_id=pclass_id, type=1) }}">
                    <i class="fas fa-cogs fa-fw"></i> Attach selector LiveProject...
                </a>
            {% endif %}
            {% if not in_submitter %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.inject_liveproject', pid=project.id, pclass_id=pclass_id, type=2) }}">
                    <i class="fas fa-cogs fa-fw"></i> Attach submitter LiveProject...
                </a>
            {% endif %}
        {% else %}
            <div role="separator" class="dropdown-divider"></div>
            {% if not in_selector %} {# in_selector and in_submitter should be the same thing #}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.inject_liveproject', pid=project.id, pclass_id=pclass_id, type=1) }}">
                    <i class="fas fa-cogs fa-fw"></i> Publish LiveProject...
                </a>
            {% endif %}
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>

        {% if project.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.duplicate_project', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-wrench fa-fw"></i> Duplicate...
        </a>
    </div>
</div>
"""


# language=jinja2
_unofferable_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit project</div>

        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=0, text=text, url=url) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=0) }}">
            <i class="fas fa-tools fa-fw"></i> Variants...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=0, url=url_for('convenor.attached', id=0), text='convenor dashboard') }}">
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=0) }}">
            <i class="fas fa-cogs fa-fw"></i> Transferable skills...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=0) }}">
            <i class="fas fa-cogs fa-fw"></i> Degree programmes...
        </a>

        <div role="separator" class="dropdown-divider"></div>

        {% if project.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=0) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=0) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_attach_button = """
<a href="{{ url_for('convenor.manual_attach_project', id=project.id, configid=config_id) }}" class="btn btn-success btn-sm">
    <i class="fas fa-plus"></i> Attach
</a>
"""


# language=jinja2
_attach_other_button = """
<a href="{{ url_for('convenor.manual_attach_other_project', id=desc.id, configid=config_id) }}" class="btn btn-success btn-sm">
    <i class="fas fa-plus"></i> Attach
</a>
"""


_menus = {
    "convenor": _convenor_menu,
    "faculty": _faculty_menu,
    "unofferable": _unofferable_menu,
    "attach": _attach_button,
    "attach_other": _attach_other_button,
    None: "",
}


_config_proxy = 999999999
_pclass_proxy = 888888888
_config_proxy_str = str(_config_proxy)
_pclass_proxy_str = str(_pclass_proxy)


# TODO: work out how to memoize these template compilations.
#  Just using @cache.memoize() seems to lead to Pickle serialization
#  problems, at least with the Redis backend for Flask-Caching, so
#  for now these have had to be left unmemoized


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_owner_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_owner)


def _build_status_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_status)


def _build_pclasses_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_pclasses)


def _build_meetingreqd_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_meetingreqd)


def _build_affiliation_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_affiliation)


def _build_prefer_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_prefer)


def _build_skills_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_skills)


def _build_menu_templ(key: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menus[key])


def build_data(
        projects: ProjectLikeList | ProjectDescLikeList,
    config: Optional[ProjectClassConfig] = None,
    current_user: Optional[User] = None,
    menu_template: Optional[str] = None,
    name_labels: Optional[bool] = False,
    text: Optional[str] = None,
    url: Optional[str] = None,
    show_approvals: Optional[bool] = False,
    show_errors: Optional[bool] = True,
):
    if hasattr(projects, "len") and len(projects) == 0:
        return []

    simple_label = get_template_attribute("labels.html", "simple_label")
    truncate = get_template_attribute("macros.html", "truncate")

    error_block_popover = get_template_attribute("error_block.html", "error_block_popover")

    name_templ: Template = _build_name_templ()
    owner_templ: Template = _build_owner_templ()
    status_templ: Template = _build_status_templ()
    pclasses_templ: Template = _build_pclasses_templ()
    meetingreqd_templ: Template = _build_meetingreqd_templ()
    affiliation_templ: Template = _build_affiliation_templ()
    prefer_templ: Template = _build_prefer_templ()
    skills_templ: Template = _build_skills_templ()
    menu_templ: Template = _build_menu_templ(menu_template) if menu_template is not None else None

    selector_lifecycle = config.selector_lifecycle if config is not None else None
    waiting_confirmations = (
        selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS if selector_lifecycle is not None else False
    )

    def _process(p: ProjectLike, d: Optional[ProjectDescription]):
        if config is not None and not p.generic and p.owner is not None:
            e = db.session.query(EnrollmentRecord).filter_by(owner_id=current_user.id, pclass_id=config.pclass_id).first()
        else:
            e = None

        if d is None and config is not None:
            d = p.get_description(config.pclass_id)

        is_running = (p.running_counterpart(config.id) is not None) if config is not None else False

        in_selector = (p.selector_live_counterpart(config.id) is not None) if config is not None else False
        in_submitter = (p.submitter_live_counterpart(config.id) is not None) if config is not None else False

        data = {
            "name": render_template(
                name_templ,
                project=p,
                desc=d,
                name_labels=name_labels,
                is_running=is_running,
                in_selector=in_selector,
                in_submitter=in_submitter,
                show_errors=show_errors,
                text=text,
                url=url,
                error_block_popover=error_block_popover,
                current_user=current_user,
            ),
            "owner": render_template(owner_templ, project=p, url=url, text=text),
            "status": render_template(
                status_templ,
                project=p,
                desc=d,
                e=e,
                config=config,
                show_approvals=show_approvals,
                waiting_confirmations=waiting_confirmations,
                simple_label=simple_label,
            ),
            "pclasses": render_template(pclasses_templ, project=p),
            "meeting": render_template(meetingreqd_templ, project=p),
            "group": render_template(affiliation_templ, project=p, simple_label=simple_label, truncate=truncate),
            "prefer": render_template(prefer_templ, project=p, simple_label=simple_label),
            "skills": render_template(skills_templ, skills=p.ordered_skills, simple_label=simple_label),
        }

        if menu_templ is not None:
            data.update(
                {
                    "menu": render_template(
                        menu_templ,
                        project=p,
                        desc=d,
                        config_id=config.id if config is not None else None,
                        pclass_id=config.pclass_id if config is not None else None,
                        in_selector=in_selector,
                        in_submitter=in_submitter,
                        select_in_previous_cycle=config.select_in_previous_cycle if config is not None else True,
                        text=text,
                        url=url,
                    ),
                }
            )

        return data

    return [_process(p=p[0], d=p[1]) if (isinstance(p, Row) or isinstance(p, tuple)) else _process(p=p, d=None) for p in projects]
