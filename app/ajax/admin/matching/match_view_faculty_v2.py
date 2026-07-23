#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Optional

from flask import current_app, get_template_attribute, render_template
from jinja2 import Environment, Template

from ....models import MatchingAttempt

# language=jinja2
_name = """
<div>
    <a class="text-decoration-none fw-semibold" role="button" style="font-size: 15.5px;" data-bs-toggle="offcanvas"
       data-bs-target="#matchFacultyDrawer"
       data-fac-id="{{ row.faculty.id }}" data-fac-name="{{ row.faculty.user.name }}">{{ row.faculty.user.name }}</a>
</div>
<div class="d-flex flex-column gap-1 mt-1">
    {% for pclass_id, count in row.offered_by_pclass.items() %}
        {% set pclass = pclass_lookup.get(pclass_id) %}
        {% if pclass %}
            <div class="d-flex align-items-center gap-2 small text-body-secondary">
                {{ small_swatch(pclass.make_CSS_style()) }}
                <span>{{ pclass.abbreviation }} &middot; offered {{ count }}</span>
            </div>
        {% endif %}
    {% endfor %}
</div>
<div class="d-flex flex-wrap align-items-center gap-2 mt-2">
    <a class="small text-decoration-none" role="button" data-bs-toggle="offcanvas" data-bs-target="#matchFacultyDrawer"
       data-fac-id="{{ row.faculty.id }}" data-fac-name="{{ row.faculty.user.name }}">
        Show details <i class="fas fa-chevron-right"></i>
    </a>
</div>
<div class="mt-2">
    <button type="button" class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#matchFacultyReassignModal"
            data-fac-id="{{ row.faculty.id }}" data-fac-name="{{ row.faculty.user.name }}">
        Reassign&hellip;
    </button>
</div>
"""


# language=jinja2
_supervising = """
{% set ns = namespace(count=0) %}
<div class="d-flex flex-column gap-2">
    {% for pclass_id, items in row.supervising_by_pclass.items() %}
        {% if items %}
            {% set ns.count = ns.count + items|length %}
            {% set pclass = pclass_lookup.get(pclass_id) %}
            <div>
                <div class="text-body-secondary text-uppercase" style="font-size: 10.5px; letter-spacing: .4px;">
                    {{ pclass.abbreviation if pclass else '' }}
                </div>
                {% for item in items %}
                    <div class="d-flex align-items-start gap-2 mt-1">
                        {% if pclass %}{{ small_swatch(pclass.make_CSS_style()) }}{% endif %}
                        <div>
                            <a class="text-decoration-none small" role="button" data-bs-toggle="modal" data-bs-target="#matchRoleEditorModal"
                               data-rec-id="{{ item.record.id }}">{{ item.student.user.name }}</a>
                            {% if item.programme_pref is not none %}
                                {% if item.programme_pref %}
                                    <i class="fas fa-check-circle small" style="color: var(--bs-success-text-emphasis);"
                                       data-bs-toggle="tooltip" title="Meets programme prefs"></i>
                                {% else %}
                                    <i class="fas fa-times-circle small" style="color: var(--bs-warning-text-emphasis);"
                                       data-bs-toggle="tooltip" title="Programme prefs not met"></i>
                                {% endif %}
                            {% endif %}
                            <div class="small text-body-secondary mwfp-proj"
                                 title="{{ item.project.name if item.project else '' }}">{{ item.project.name if item.project else '' }}</div>
                        </div>
                    </div>
                {% endfor %}
            </div>
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="text-body-secondary small">None</span>
    {% endif %}
</div>
"""


# language=jinja2
_marking = """
{% set ns = namespace(count=0) %}
<div class="d-flex flex-column gap-2">
    {% for pclass_id, items in row.marking_by_pclass.items() %}
        {% if items %}
            {% set ns.count = ns.count + items|length %}
            {% set pclass = pclass_lookup.get(pclass_id) %}
            <div>
                <div class="text-body-secondary text-uppercase" style="font-size: 10.5px; letter-spacing: .4px;">
                    {{ pclass.abbreviation if pclass else '' }}
                </div>
                {% for item in items %}
                    <div class="small mt-1">
                        <div>{{ item.student.user.name }}</div>
                        <div class="text-body-secondary mwfp-proj"
                             title="{{ item.project.name if item.project else '' }}">{{ item.project.name if item.project else '' }}</div>
                    </div>
                {% endfor %}
            </div>
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="text-body-secondary small">None</span>
    {% endif %}
</div>
"""


# language=jinja2
_workload = """
<div class="small">
    <span class="text-body-secondary">Supervising</span> <strong>{{ row.workload.cats_supervising }}</strong>
</div>
<div class="small">
    <span class="text-body-secondary">Marking</span> <strong>{{ row.workload.cats_marking }}</strong>
</div>
<div class="small mt-1">
    <span style="color: var(--bs-primary);">Total <strong>{{ row.workload.cats_total }}</strong></span>
</div>
{% if row.binding_pills %}
    <div class="d-flex flex-column align-items-start gap-1 mt-2">
        {% for pill in row.binding_pills %}
            <span class="badge rounded-pill small" style="
                background: {% if pill.severity == 'danger' %}var(--bs-danger-bg-subtle){% else %}var(--bs-warning-bg-subtle){% endif %};
                color: {% if pill.severity == 'danger' %}var(--bs-danger-text-emphasis){% else %}var(--bs-warning-text-emphasis){% endif %};">
                <i class="fas fa-balance-scale me-1"></i>{{ pill.label }}
            </span>
        {% endfor %}
    </div>
{% endif %}
"""


def _build_templ(source: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(source)


def faculty_view_v2_data(rows: List[dict], attempt: MatchingAttempt, text: Optional[str] = None, url: Optional[str] = None) -> List[dict]:
    """
    Render the redesigned (v2) Faculty-tab DataTables rows from a list of view dicts produced by
    app.shared.matching_workspace.faculty_row(). See .prompts/matching-workspace/PLAN.md.
    """
    small_swatch = get_template_attribute("swatch.html", "small_swatch")
    pclass_lookup = {config.pclass_id: config.project_class for config in attempt.config_members}

    name_templ = _build_templ(_name)
    supervising_templ = _build_templ(_supervising)
    marking_templ = _build_templ(_marking)
    workload_templ = _build_templ(_workload)

    return [
        {
            "name": render_template(name_templ, row=row, pclass_lookup=pclass_lookup, small_swatch=small_swatch),
            "supervising": render_template(supervising_templ, row=row, pclass_lookup=pclass_lookup, small_swatch=small_swatch),
            "marking": render_template(marking_templ, row=row, pclass_lookup=pclass_lookup),
            "workload": render_template(workload_templ, row=row),
        }
        for row in rows
    ]
