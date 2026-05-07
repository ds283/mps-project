#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Dict

from flask import current_app, render_template, url_for


# language=jinja2
_student_cell = """
{% set student = record.owner.student %}
{% set user = student.user %}
{% set pclass = record.period.config.project_class %}
<div class="fw-semibold">{{ user.name }}</div>
<div class="small text-muted">
    {% if student.exam_number %}{{ student.exam_number_label }}{% endif %}
</div>
<div class="small mt-1">
    <span class="badge bg-secondary">{{ pclass.abbreviation }}</span>
    <span class="text-muted ms-1">{{ record.period.config.year }}&ndash;{{ record.period.config.year + 1 }}</span>
</div>
"""

# language=jinja2
_chunk_type_cell = """
<span class="badge"
      style="background-color: var(--db-orange-100); color: var(--db-orange-800);">
    {{ concern.chunk_type | replace("_", " ") | title }}
</span>
"""

# language=jinja2
_cosine_cell = """
{% if concern.transformer_cosine is not none %}
    {% if concern.transformer_cosine >= 0.88 %}
        {% set cls = "bg-danger-subtle text-danger-emphasis" %}
    {% elif concern.transformer_cosine >= 0.78 %}
        {% set cls = "bg-warning-subtle text-warning-emphasis" %}
    {% else %}
        {% set cls = "bg-secondary-subtle text-secondary-emphasis" %}
    {% endif %}
    <span class="badge {{ cls }}">{{ "%.3f"|format(concern.transformer_cosine) }}</span>
{% else %}
    <span class="text-muted">&mdash;</span>
{% endif %}
"""

# language=jinja2
_turnitin_cell = """
{% macro ti_score(record) %}
    {% if record.turnitin_student_overlap is not none %}
        {% if record.turnitin_student_overlap >= 20 %}
            <span class="text-danger fw-semibold">{{ record.turnitin_student_overlap }}%</span>
        {% else %}
            {{ record.turnitin_student_overlap }}%
        {% endif %}
    {% else %}
        <span class="text-muted">&mdash;</span>
    {% endif %}
{% endmacro %}
<div class="d-flex flex-column gap-0 small">
    <div>A:&nbsp;{{ ti_score(concern.record_a) }}</div>
    <div>B:&nbsp;{{ ti_score(concern.record_b) }}</div>
</div>
"""

# language=jinja2
_year_gap_cell = """
{% set gap = (concern.record_a.period.config.year - concern.record_b.period.config.year) | abs %}
{% if gap == 0 %}
    <span class="badge bg-secondary-subtle text-secondary-emphasis">Same year</span>
{% elif gap == 1 %}
    <span class="badge bg-warning-subtle text-warning-emphasis">{{ gap }} yr gap</span>
{% else %}
    <span class="badge bg-secondary-subtle text-secondary-emphasis">{{ gap }} yr gap</span>
{% endif %}
"""

# language=jinja2
_status_cell = """
{% if not concern.reviewed %}
    <span class="badge bg-warning-subtle text-warning-emphasis">
        <i class="fas fa-clock me-1"></i>Unreviewed
    </span>
{% elif concern.resolution == "cleared" %}
    <span class="badge bg-success-subtle text-success-emphasis">
        <i class="fas fa-check me-1"></i>Cleared
    </span>
{% elif concern.resolution == "referred" %}
    <span class="badge bg-info-subtle text-info-emphasis">
        <i class="fas fa-share me-1"></i>Referred
    </span>
{% elif concern.resolution == "escalated" %}
    <span class="badge bg-danger-subtle text-danger-emphasis">
        <i class="fas fa-exclamation-circle me-1"></i>Escalated
    </span>
{% else %}
    <span class="badge bg-secondary">{{ concern.resolution or "Unknown" }}</span>
{% endif %}
"""

# language=jinja2
_actions_cell = """
<div class="d-flex flex-column gap-1">
    <a href="{{ view_url }}" class="btn btn-sm btn-outline-secondary">
        <i class="fas fa-eye me-1"></i>View
    </a>
    {% if not concern.reviewed %}
        <a href="{{ review_url }}" class="btn btn-sm btn-db-orange">
            <i class="fas fa-gavel me-1"></i>Review
        </a>
    {% endif %}
</div>
"""


def similarity_concern_data(concerns) -> List[Dict]:
    """Format SimilarityConcern rows for DataTables."""
    env = current_app.jinja_env

    student_tmpl = env.from_string(_student_cell)
    chunk_type_tmpl = env.from_string(_chunk_type_cell)
    cosine_tmpl = env.from_string(_cosine_cell)
    turnitin_tmpl = env.from_string(_turnitin_cell)
    year_gap_tmpl = env.from_string(_year_gap_cell)
    status_tmpl = env.from_string(_status_cell)
    actions_tmpl = env.from_string(_actions_cell)

    rows = []
    for concern in concerns:
        view_url = url_for("dashboards.similarity_concern_detail", concern_id=concern.id)
        review_url = view_url + "#review"

        rows.append(
            {
                "student_a": render_template(student_tmpl, record=concern.record_a),
                "student_b": render_template(student_tmpl, record=concern.record_b),
                "chunk_type": render_template(chunk_type_tmpl, concern=concern),
                "cosine": render_template(cosine_tmpl, concern=concern),
                "turnitin": render_template(turnitin_tmpl, concern=concern),
                "year_gap": render_template(year_gap_tmpl, concern=concern),
                "status": render_template(status_tmpl, concern=concern),
                "actions": render_template(
                    actions_tmpl,
                    concern=concern,
                    view_url=view_url,
                    review_url=review_url,
                ),
            }
        )

    return rows
