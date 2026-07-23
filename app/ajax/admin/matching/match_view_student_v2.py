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

# language=jinja2
_student = """
<div>
    <a class="text-decoration-none fw-semibold" href="mailto:{{ row.user.email }}">{{ row.user.name }}</a>
    {% if not row.record.selector.convert_to_submitter %}
        <i class="fas fa-exclamation-triangle text-danger ms-1" data-bs-toggle="tooltip"
           title="Conversion to submitter is disabled"></i>
    {% endif %}
</div>
<div class="d-flex flex-wrap align-items-center gap-2 mt-1">
    <a class="small text-decoration-none" role="button" data-bs-toggle="offcanvas" data-bs-target="#matchStudentDrawer"
       data-rec-id="{{ row.record.id }}" data-student-name="{{ row.user.name }}">
        Show details <i class="fas fa-chevron-right"></i>
    </a>
    {% if row.journal.visible %}
        <span class="badge rounded-pill border text-body-secondary small">
            <i class="fas fa-book me-1"></i>{{ row.journal.visible }}
        </span>
    {% endif %}
    {% if row.open_tickets %}
        <span class="badge rounded-pill small"
              style="background: var(--bs-warning-bg-subtle); color: var(--bs-warning-text-emphasis);">
            <i class="fas fa-ticket-alt me-1"></i>{{ row.open_tickets }}
        </span>
    {% endif %}
</div>
"""


# language=jinja2
_pclass = """
<div class="d-flex flex-row justify-content-start align-items-center gap-2">
    {{ small_swatch(row.pclass.instance.make_CSS_style()) }}
    <span class="small">{{ label_text(row.pclass.label) }}</span>
</div>
{% if row.cohort %}<div class="small text-primary">Cohort {{ row.cohort }}</div>{% endif %}
{% if row.project.owner %}
    <div class="small text-body-secondary"><i class="fas fa-user-circle me-1"></i>{{ row.project.owner }}</div>
{% endif %}
"""


# language=jinja2
_project = """
<div class="d-flex flex-column align-items-start gap-1">
    {% if row.project.instance %}
        <a class="text-decoration-none" role="button" data-bs-toggle="modal" data-bs-target="#matchRoleEditorModal"
           data-rec-id="{{ row.record.id }}">{{ row.project.name }} <i class="fas fa-caret-down"></i></a>
    {% else %}
        <a class="text-decoration-none text-danger" role="button" data-bs-toggle="modal"
           data-bs-target="#matchRoleEditorModal" data-rec-id="{{ row.record.id }}">Unassigned <i
                class="fas fa-caret-down"></i></a>
    {% endif %}
    {% if row.modified %}
        <span class="badge rounded-pill small" style="border: 1px solid var(--bs-primary); color: var(--bs-primary);">Modified</span>
    {% endif %}
</div>
{% if row.programme_pref is not none %}
    {% if row.programme_pref %}
        <div class="small" style="color: var(--bs-success-text-emphasis);">
            <i class="fas fa-check-circle me-1"></i>Meets programme prefs
        </div>
    {% else %}
        <div class="small" style="color: var(--bs-warning-text-emphasis);">
            <i class="fas fa-exclamation-circle me-1"></i>Programme prefs not met
        </div>
    {% endif %}
{% endif %}
"""


# language=jinja2
_markers = """
{% if row.markers %}
    {% for m in row.markers %}
        <div>
            <a class="text-decoration-none" role="button" data-bs-toggle="modal" data-bs-target="#matchRoleEditorModal"
               data-rec-id="{{ row.record.id }}">{{ m.name }} <i class="fas fa-caret-down"></i></a>
        </div>
    {% endfor %}
{% else %}
    <a class="text-decoration-none text-body-secondary" role="button" data-bs-toggle="modal"
       data-bs-target="#matchRoleEditorModal" data-rec-id="{{ row.record.id }}">Assign marker&hellip; <i
            class="fas fa-caret-down"></i></a>
{% endif %}
"""


# language=jinja2
_rank = """
{% set band = row.rank_band %}
<div class="fw-bold" style="font-size: 22px; line-height: 1.1;
    {% if band == 'success' %}color: var(--bs-success-text-emphasis);
    {% elif band == 'warning' %}color: var(--bs-warning-text-emphasis);
    {% elif band == 'danger' %}color: var(--bs-danger-text-emphasis);
    {% endif %}">
    {{ row.rank if row.rank is not none else '&mdash;'|safe }}
</div>
<div class="small text-body-secondary">preference</div>
"""


# language=jinja2
_score = """
<span class="small text-body-secondary">{{ '%0.2f'|format(row.score) if row.score is not none else '&mdash;'|safe }}</span>
"""


def _build_templ(source: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(source)


def student_view_v2_data(rows: List[dict], attempt_id: int, text: Optional[str] = None, url: Optional[str] = None) -> List[dict]:
    """
    Render the redesigned (v2) Student-tab DataTables rows from a list of view dicts produced
    by app.shared.matching_workspace.student_row(). See .prompts/matching-workspace/PLAN.md.
    """
    small_swatch = get_template_attribute("swatch.html", "small_swatch")
    label_text = get_template_attribute("labels.html", "label_text")

    student_templ = _build_templ(_student)
    pclass_templ = _build_templ(_pclass)
    project_templ = _build_templ(_project)
    markers_templ = _build_templ(_markers)
    rank_templ = _build_templ(_rank)
    score_templ = _build_templ(_score)

    return [
        {
            "student": render_template(student_templ, row=row),
            "pclass": render_template(pclass_templ, row=row, small_swatch=small_swatch, label_text=label_text),
            "project": render_template(project_templ, row=row),
            "markers": render_template(markers_templ, row=row),
            "rank": render_template(rank_templ, row=row),
            "score": render_template(score_templ, row=row),
        }
        for row in rows
    ]
