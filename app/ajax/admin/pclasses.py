#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, render_template, current_app
from jinja2 import Template, Environment

from ...cache import cache

# language=jinja2
_programmes = """
{% for programme in pcl.programmes %}
    {{ simple_label(programme.short_label) }}
{% endfor %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <div class="dropdown-header">Edit</div>
        
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_pclass', id=pcl.id) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_pclass_text', id=pcl.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Customize messages...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_period_definitions', id=pcl.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Submission periods...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Admin</div>

        {% if pcl.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_pclass', id=pcl.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            {% if pcl.available %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_pclass', id=pcl.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-ban fa-fw"></i> Can't make active
                </a>
            {% endif %}
        {% endif %}
        {% if pcl.publish %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.unpublish_pclass', id=pcl.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Unpublish
            </a>
        {% else %}
            {% if pcl.available %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_pclass', id=pcl.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Publish
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-ban fa-fw"></i> Can't publish
                </a>
            {% endif %}
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_options = """
{% if p.colour and p.colour is not none %}
  {{ simple_label(p.make_label(p.colour)) }}
{% else %}
  <span class="badge bg-secondary">No colour</span>'
{% endif %}
{% if p.use_project_hub %}
    <span class="badge bg-secondary">Project Hubs</span>
{% endif %}
{% if p.is_optional %}
    <span class="badge bg-secondary">Optional</span>
{% endif %}
{% if not p.uses_selection %}
    <span class="badge bg-danger">No selections</span>
{% endif %}
{% if not p.uses_submission %}
    <span class="badge bg-danger">No submissions</span>
{% endif %}
{% if p.do_matching %}
    <span class="badge bg-secondary">Auto-match</span>
{% endif %}
{% if p.require_confirm %}
    <span class="badge bg-secondary">Confirm</span>
{% endif %}
{% if p.supervisor_carryover %}
    <span class="badge bg-secondary">Carryover</span>
{% endif %}
{% if p.include_available %}
    <span class="badge bg-secondary">Availability</span>
{% endif %}
{% if p.reenroll_supervisors_early %}
    <span class="badge bg-secondary">Re-enroll early</span>
{% endif %}
{% if p.advertise_research_group %}
    <span class="badge bg-secondary">Affiliations</span>
{% endif %}
{% if p.use_project_tags %}
    <span class="badge bg-secondary">Tags</span>
{% endif %}
"""

# language=jinja2
_workload = """
{% if p.uses_supervisor %}
    <span class="badge bg-primary">S {{ p.CATS_supervision }}</span>
{% endif %}
{% if p.uses_marker %}
    <span class="badge bg-info">Mk {{ p.CATS_marking }}</span>
{% endif %}
{% if p.uses_moderator %}
    <span class="badge bg-info">Mo {{ p.CATS_moderation }}</span>
{% endif %}
{% if p.uses_presentations %}
    <span class="badge bg-info">P {{ p.CATS_presentation }}</span>
{% endif %}
"""

# language=jinja2
_popularity = """
{% set hourly_pl = 's' %}
{% if p.keep_hourly_popularity == 1 %}{% set hourly_pl = '' %}{% endif %}
{% set daily_pl = 's' %}
{% if p.keep_daily_popularity == 1 %}{% set daily_pl = '' %}{% endif %}
<span class="badge bg-secondary">Hourly: {{ p.keep_hourly_popularity }} day{{ hourly_pl }}</span>
<span class="badge bg-secondary">Daily: {{ p.keep_daily_popularity }} week{{ daily_pl }}</span>
"""

# language=jinja2
_personnel = """
<div class="personnel-container">
    {% if p.coconvenors.first() %}
        <div>Convenors</div>
    {% else %}
        <div>Convenor</div>
    {% endif %}
    {% set style = p.make_CSS_style() %}
    <a class="badge text-decoration-none text-nohover-dark bg-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ p.convenor_email }}">
        {{ p.convenor_name }}
    </a>
    {% for fac in p.coconvenors %}
        <a class="badge text-decoration-none text-nohover-light bg-secondary" href="mailto:{{ fac.user.email }}">
            {{ fac.user.name }}
        </a>
    {% endfor %}
</div>
{% if p.office_contacts.first() %}
    <div class="personnel-container">
        <div>Office contacts</div>
        {% for user in p.office_contacts %}
            <a class="badge text-decoration-none text-nohover-dark bg-info" href="mailto:{{ user.email }}">
                {{ user.name }}
            </a>
        {% endfor %}
    </div>
{% endif %}
"""

# language=jinja2
_submissions = """
<span class="badge bg-primary">{{ p.submissions }}/yr</span>
{% if p.uses_marker %}
    <span class="badge bg-info">Marked</span>
{% endif %}
{% if p.uses_moderator %}
    <span class="badge bg-info">Moderated</span>
{% endif %}
{% if p.uses_presentations %}
    {% for item in p.periods.all() %}
        {% if item.has_presentation %}
            <span class="badge bg-info">Present: Prd #{{ item.period }}</span>
        {% endif %}
    {% endfor %}
{% endif %}
"""


# language=jinja2
_timing = """
{% if p.start_year is not none %}
    <span class="badge bg-primary">Join Y{{ p.start_year }}</span>
{% else %}
    <span class="badge bg-danger">Start year missing</span>
{% endif %}
{% if p.select_in_previous_cycle %}
    <span class="badge bg-success">Select: previous</span>
{% else %}
    <span class="badge bg-success">Select: same</span>
{% endif %}
<span class="badge bg-secondary">Extent: {{ p.extent }} yr</span>
{% if p.auto_enrol_enable %}
    {% if p.selection_open_to_all %}
        <span class="badge bg-primary">Enrol: open</span>
    {% else %}
        <span class="badge bg-primary">Enrol: programme</span>
    {% endif %}
    {% if p.auto_enroll_years == p.AUTO_ENROLL_FIRST_YEAR %}
        <span class="badge bg-primary">Enrol: first year</span>
    {% elif p.auto_enroll_years == p.AUTO_ENROLL_ALL_YEARS %}
        <span class="badge bg-primary">Enrol: all years</span>
    {% else %}
        <span class="badge bg-danger">Enrol: unknown</span>
    {% endif %}
{% else %}
    <span class="badge bg-warning text-dark">No auto-enrol</span>
{% endif %}
"""


# language=jinja2
_name = """
{{ p.name }} {{ simple_label(p.make_label(p.abbreviation)) }}
<span class="badge {% if p.student_level >= p.LEVEL_UG and p.student_level <= p.LEVEL_PGR %}bg-secondary{% else %}bg-danger{% endif %}">
    {{ p._level_text(p.student_level) }}
</span>
{% set num_approvers = p.number_approvals_team %}
<span class="badge {% if num_approvers > 0 %}bg-secondary{% else %}bg-danger{% endif %}"
    {% if num_approvers > 0 %}data-bs-toggle="tooltip" data-html="true" title="{% for u in p.approvals_team %}{{ u.name }}<br/>{% endfor %}"{% endif %}>
    {{ num_approvers }} approver{%- if num_approvers != 1 -%}s{%- endif -%}
</span>
<div class="mt-2">
{% if p.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
{% if p.publish %}
    <span class="badge bg-success"><i class="fas fa-eye"></i> Published</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-eye-slash"></i> Unpublished</span>
{% endif %}
</div>
"""


@cache.memoize()
def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


@cache.memoize()
def _build_options_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_options)


@cache.memoize()
def _build_timing_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_timing)


@cache.memoize()
def _build_workload_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_workload)


@cache.memoize()
def _build_submissions_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_submissions)


@cache.memoize()
def _build_popularity_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_popularity)


@cache.memoize()
def _build_personnel_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_personnel)


@cache.memoize()
def _build_programmes_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_programmes)


@cache.memoize()
def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def pclasses_data(pclasses):
    name_templ: Template = _build_name_templ()
    options_templ: Template = _build_options_templ()
    timing_templ: Template = _build_timing_templ()
    workload_templ: Template = _build_workload_templ()
    submissions_templ: Template = _build_submissions_templ()
    popularity_templ: Template = _build_popularity_templ()
    personnel_templ: Template = _build_personnel_templ()
    programmes_templ: Template = _build_programmes_templ()
    menu_templ: Template = _build_menu_templ()

    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "name": render_template(name_templ, p=p, simple_label=simple_label),
            "options": render_template(options_templ, p=p, simple_label=simple_label),
            "timing": render_template(timing_templ, p=p),
            "cats": render_template(workload_templ, p=p),
            "submissions": render_template(submissions_templ, p=p),
            "popularity": render_template(popularity_templ, p=p),
            "personnel": render_template(personnel_templ, p=p),
            "programmes": render_template(programmes_templ, pcl=p, simple_label=simple_label),
            "menu": render_template(menu_templ, pcl=p),
        }
        for p in pclasses
    ]

    return jsonify(data)
