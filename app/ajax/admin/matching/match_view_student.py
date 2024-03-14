#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from ....database import db
from ....models import SelectingStudent, StudentData, EmailLog, User

# language=jinja2
_student = """
<div>
    <a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
    {% if not valid %}
        <i class="fas fa-exclamation-triangle text-danger"></i>
    {% endif %}
</div>
{{ student_offcanvas(sel, emails, attempt_id) }}
{% if not sel.convert_to_submitter %}
    <div class="text-danger small">
        <i class="fas fa-exclamation-circle"></i>
        Conversion of this student is disabled.
        <a class="text-decoration-none" href="{{ url_for('admin.delete_match_record', attempt_id=attempt_id, selector_id=sel.id) }}">
            Delete...
        </a>
    </div>
{% endif %}
"""


# language=jinja2
_pclass = """
{% set config = sel.config %}
{% set swatch_colour = config.project_class.make_CSS_style() %}
<div class="d-flex flex-row justify-content-start align-items-center gap-2">
    {{ small_swatch(swatch_colour) }}
    <span class="small">{{ config.name }}</span>
</div>
<div class="d-flex flex-row justify-content-start align-items-center gap-2 small">
    <i class="fas fa-user-circle"></i>
    <a class="text-decoration-none" href="mailto:{{ config.convenor_email }}">{{ config.convenor_name }}</a>
</div>
"""


# language=jinja2
_details = """
<div class="text-primary small">
    {{ unformatted_label(sel.student.programme.short_label, tag='div') }}
</div>
<div class="mt-1 text-muted small">
    {{- unformatted_label(sel.academic_year_label(show_details=True)) -}} |
    {{ unformatted_label(sel.student.cohort_label) -}}
</div>
"""


# language=jinja2
_project = """
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% if recs|length == 1 %}
        {{ project_tag(recs[0], false) }}
    {% elif recs|length > 1 %}
        {% for r in recs %}
            {{ project_tag(r, true, 1, url_for('admin.match_student_view', id=r.matching_id)) }}
        {% endfor %}
    {% endif %}
</div>
{% for r in recs %}
    {# if both not valid and overassigned, should leave error message from is_valid intact due to short-circuit evaluation #}
    {{ error_block_inline(r.errors, r.warnings) }}
{% endfor %}
"""


# language=jinja2
_marker = """
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% if recs|length == 1 %}
        {{ student_marker_tag(recs[0], false) }}
    {% elif recs|length > 1 %}
        {% for r in recs %}
            {{ student_marker_tag(r, true) }}
        {% endfor %}
    {% endif %}
</div>
"""


# language=jinja2
_rank = """
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
        <div class="{% if r.hi_ranked %}text-success fw-semibold{% elif r.lo_ranked %}text-danger{% else %}text-primary{% endif %}">{{ r.total_rank }}</div>
        {% if r.alternative %}<div class="small text-muted"><i class="fas fa-info-circle"></i> Alternative</div>{% endif %}
        <div class="text-secondary small">&delta; = {{ delta }}</div>
    </div>
{% elif recs|length > 1 %}
    <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
        {% for r in recs %}
            <div class="{% if r.hi_ranked %}text-success fw-semibold{% elif r.lo_ranked %}text-danger{% else %}text-primary{% endif %}">#{{ r.submission_period }}: {{ r.total_rank }}</div>
            {% if r.alternative %}<div class="small text-muted"><i class="fas fa-info-circle"></i> Alternative</div>{% endif %}
        {% endfor %}
        <div class="text-secondary small">&delta; = {{ delta }}</div>
    </div>
{% endif %}
"""


# language=jinja2
_scores = """
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="badge bg-primary">{{ r.current_score|round(precision=2) }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="badge bg-secondary">#{{ r.submission_period }}: {{ r.current_score|round(precision=2) }}</span>
    {% endfor %}
    <span class="badge bg-primary">Total {{ total_score|round(precision=2) }}</span>
{% endif %}
"""


def _build_student_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_student)


def _build_pclass_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_pclass)


def _build_details_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_details)


def _build_project_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project)


def _build_marker_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_marker)


def _build_rank_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_rank)


def _build_scores_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_scores)


def student_view_data(selector_data, attempt_id, text=None, url=None):
    # selector_data is a list of ((lists of) MatchingRecord, delta-value, score-value) triples

    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    unformatted_label = get_template_attribute("labels.html", "unformatted_label")

    student_offcanvas = get_template_attribute("admin/matching/student_offcanvas.html", "student_offcanvas")
    project_tag = get_template_attribute("admin/matching/project_tag.html", "project_tag")
    student_marker_tag = get_template_attribute("admin/matching/marker_tag.html", "student_marker_tag")

    error_block_inline = get_template_attribute("error_block.html", "error_block_inline")

    def get_emails(s: SelectingStudent):
        data: StudentData = s.student

        emails = db.session.query(EmailLog).filter(EmailLog.recipients.any(User.id == data.id)).order_by(EmailLog.send_date.desc()).limit(7).all()

        return emails

    student_templ: Template = _build_student_templ()
    pclass_templ: Template = _build_pclass_templ()
    details_templ: Template = _build_details_templ()
    project_templ: Template = _build_project_templ()
    marker_templ: Template = _build_marker_templ()
    rank_templ: Template = _build_rank_templ()
    scores_templ: Template = _build_scores_templ()

    data = [
        {
            "student": render_template(
                student_templ,
                sel=r[0].selector,
                attempt_id=attempt_id,
                emails=get_emails(r[0].selector),
                valid=all([not rc.has_issues for rc in r]),
                text=text,
                url=url,
                student_offcanvas=student_offcanvas,
            ),
            "pclass": render_template(pclass_templ, sel=r[0].selector, small_swatch=small_swatch),
            "details": render_template(details_templ, sel=r[0].selector, unformatted_label=unformatted_label),
            "project": render_template(project_templ, recs=r, project_tag=project_tag, error_block_inline=error_block_inline),
            "marker": render_template(marker_templ, recs=r, student_marker_tag=student_marker_tag),
            "rank": render_template(rank_templ, recs=r, delta=delta),
            "scores": render_template(scores_templ, recs=r, total_score=score),
        }
        for r, delta, score in selector_data
    ]

    return data
