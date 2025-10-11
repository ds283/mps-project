#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from ...models import ProjectClassConfig

# language=jinja2
_name = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">{{ project.name }}</a>
{% if project.hidden %}
    <div>
        <span class="badge bg-danger"><i class="fas fa-eye-slash"></i> HIDDEN</span>
    </div>
{% endif %}
{% set num_alternatives = project.number_alternatives %}
{% if num_alternatives > 0 %}
    <div>
        <span class="badge bg-success">{{ num_alternatives }} alternative{% if num_alternatives != 1 %}s{% endif %}</span>
    </div>
{% endif %}
"""


# language=jinja2
_owner = """
{% if project.generic %}
    <div class="fw-semibold text-secondary">Generic</div>
    {% set num = project.number_supervisors %}
    <div class="mt-1 d-flex flex-row gap-2 justify-content-start align-items-center">
        {% if num > 0 %}
            <div class="mt-1 small text-muted">Pool size = {{ num }}</div>
        {% else %}
                <div class="mt-1 small text-danger">Pool size = 0</div>
        {% endif %}
        <a class="btn btn-xs btn-outline-secondary" href="{{ url_for('convenor.edit_liveproject_supervisors', proj_id=project.id, url=url) }}">Edit</a>
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
_affiliation = """
{% set ns = namespace(affiliation=false) %}
{% if project.group %}
    {{ simple_label(project.group.make_label()) }}
    {% set ns.affiliation = true %}
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ simple_label(tag.make_label(truncate(tag.name))) }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <div class="text-secondary"><i class="fas fa-ban"></i> No affiliations</div>
{% endif %}
"""


# language=jinja2
_bookmarks = """
{% set bookmarks = project.number_bookmarks %}
{% if bookmarks > 0 %}
    <div class="text-primary"><i class="fas fa-bookmark"></i> <strong>{{ bookmarks }}</strong></div>
    <a class="text-decoration-none link-secondary small" href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
       Show...
   </a>
{% else %}
    <div class="text-secondary"><i class="fas fa-ban"></i> None</div>
{% endif %}
"""

# language=jinja2
_selections = """
{% set selections = project.number_selections %}
<div>
    {% if selections > 0 %}
        <div class="text-success"><i class="fas fa-check-circle"></i> <strong>{{ selections }}</strong></div>
        <a class="text-decoration-none link-secondary small" href="{{ url_for('convenor.project_choices', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <div class="text-secondary"><i class="fas fa-ban"></i> None</div>
    {% endif %}
</div>
{% set offers = project.number_offers_accepted() %}
{% if offers > 0 %}
    <div class="mt-2">
        {% for offer in project.custom_offers_accepted() %}
            <div class="text-success small"><span class="fw-semibold"><i class="fas fa-check-circle"></i> Accepted:</span> {{ offer.selector.student.user.name }}</div>
        {% endfor %}
    </div>
{% endif %}
"""

# language=jinja2
_confirmations = """
{% set pending = project.number_pending %}
{% set confirmed = project.number_confirmed %}
<div>
    {% if confirmed > 0 %}<div class="text-primary"><i class="fas fa-check-circle"></i> <strong>{{ confirmed }}</strong></div>{% endif %}
    {% if pending > 0 %}<div class="text-danger"><i class="fas fa-clock"></i> <strong>{{ pending }}</strong> pending</div>{% endif %}
    {% if pending > 0 or confirmed > 0 %}
        <a class="text-decoration-none link-secondary small" href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <div class="text-secondary"><i class="fas fa-ban"></i> None</div>
    {% endif %}
</div>
{% set offers = project.number_offers_pending() + project.number_offers_declined() %}
{% if offers > 0 %}
    <div class="mt-2">
        {% for offer in project.custom_offers_pending() %}
            <div class="text-primary small"><span class="fw-semibold">Offer:</span> {{ offer.selector.student.user.name }}</div>
        {% endfor %}
        {% for offer in project.custom_offers_declined() %}
            <div class="text-secondary small"><span class="fw-semibold">Declined:</span> {{ offer.selector.student.user.name }}</div>
        {% endfor %}
    </div>
{% endif %}
"""

# language=jinja2
_popularity = """
{% set R = project.popularity_rank(live=require_live) %}
{% if R is not none %}
    {% set rank, total = R %}
    <div><a href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}" class="link-primary text-decoration-none">Popularity <strong>{{ rank }}</strong>/{{ total }}</a></div>
{% else %}
    <div class="text-secondary"><i class="fas fa-exclamation-circle"></i> Popularity updating...</div>
{% endif %}
<div class="mt-2">
    {% set R = project.views_rank(live=require_live) %}
    {% if R is not none %}
        {% set rank, total = R %}
        <div><a href="{{ url_for('reports.liveproject_analytics', pane='views', proj_id=project.id, url=url, text=text) }}" class="link-secondary text-decoration-none small">Views rank <strong>{{ rank }}</strong>/{{ total }}</a></div>
    {% else %}
        <div class="text-secondary small"><i class="fas fa-exclamation-circle"></i> Views updating...</div>
    {% endif %}
    {% set R = project.selections_rank(live=require_live) %}
    {% if R is not none %}
        {% set rank, total = R %}
        <div><a href="{{ url_for('reports.liveproject_analytics', pane='selections', proj_id=project.id, url=url, text=text) }}" class="link-secondary text-decoration-none small">Selections rank <strong>{{ rank }}</strong>/{{ total }}</a></div>
    {% else %}
        <div class="text-secondary small"><i class="fas fa-exclamation-circle"></i> Selections updating...</div>
    {% endif %}
    {% set R = project.bookmarks_rank(live=require_live) %}
    {% if R is not none %}
        {% set rank, total = R %}
        <div><a href="{{ url_for('reports.liveproject_analytics', pane='bookmarks', proj_id=project.id, url=url, text=text) }}" class="link-secondary text-decoration-none small">Bookmarks rank <strong>{{ rank }}</strong>/{{ total }}</a></div>
    {% else %}
        <div class="text-secondary small"><i class="fas fa-exclamation-circle"></i> Bookmarks updating...</div>
    {% endif %}
</div>
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.live_project', pid=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">
            <i class="fas fa-eye fa-fw"></i> View web page...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}">
            <i class="fas fa-wrench fa-fw"></i> View analytics...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_liveproject_alternatives', lp_id=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">
            <i class="fas fa-wrench fa-fw"></i> Alternatives...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_live_project', pid=project.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        {% if project.hidden %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.unhide_liveproject', id=project.id) }}">
                <i class="fas fa-eye fa-fw"></i> Unhide
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.hide_liveproject', id=project.id) }}">
                <i class="fas fa-eye-slash fa-fw"></i> Hide
            </a>
        {% endif %}        
        <div role="separator" class="dropdown-divider"></div>
        {% if project.number_bookmarks > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Bookmarks...
            </a>
        {% endif %}
        
        {% if project.number_selections > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_choices', id=project.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Selecting students...
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-cogs fa-fw"></i> Selecting students</a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_custom_offers', proj_id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Custom offers...
        </a>

        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_pending > 0 %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Meeting requests</div>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_confirm_all', pid=project.id) }}">
                <i class="fas fa-check fa-fw"></i> Confirm all requests
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_clear_requests', pid=project.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete all requests
            </a>
        {% endif %}

        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_confirmed > 0 %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Meeting confirmations</div>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_remove_confirms', pid=project.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete confirmations
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_make_all_confirms_pending', pid=project.id) }}">
                <i class="fas fa-clock fa-fw"></i> Make all pending
            </a>
        {% endif %}
        
        {% if project.number_pending > 0 or project.number_confirmed > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Show confirmations...
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-cogs fa-fw"></i> Show confirmations...
            </a>
        {% endif %}
    </div>
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_owner_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_owner)


def _build_affiliation_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_affiliation)


def _build_bookmarks_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_bookmarks)


def _build_selections_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_selections)


def _build_confirmations_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_confirmations)


def _build_popularity_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_popularity)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def liveprojects_data(projects, config: ProjectClassConfig, url=None, text=None):
    lifecycle = config.selector_lifecycle
    require_live = lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN

    simple_label = get_template_attribute("labels.html", "simple_label")
    truncate = get_template_attribute("macros.html", "truncate")

    name_templ: Template = _build_name_templ()
    owner_templ: Template = _build_owner_templ()
    affiliation_templ: Template = _build_affiliation_templ()
    bookmarks_templ: Template = _build_bookmarks_templ()
    selections_templ: Template = _build_selections_templ()
    confirmations_templ: Template = _build_confirmations_templ()
    popularity_templ: Template = _build_popularity_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, project=p, config=config),
            "owner": render_template(owner_templ, project=p, text=text, url=url),
            "group": render_template(affiliation_templ, project=p, simple_label=simple_label, truncate=truncate),
            "bookmarks": render_template(bookmarks_templ, project=p),
            "selections": render_template(selections_templ, project=p),
            "confirmations": render_template(confirmations_templ, project=p),
            "popularity": render_template(popularity_templ, project=p, require_live=require_live, url=url, text=text),
            "menu": render_template(menu_templ, project=p, config=config, url=url, text=text),
        }
        for p in projects
    ]

    return data
