#
# Created by David Seery on 08/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Optional, Tuple

from flask import (
    get_template_attribute,
    current_app,
    render_template,
)
from jinja2 import Template, Environment

from ...models import SubmissionRecord, SubmissionRole
from ...models.markingevent import SubmitterReport

# language=jinja2
_report = """
{% macro turnitin_chips(r) %}
    {# turnitin_outcome is a legacy Canvas LMS field not used in current Turnitin outputs; hidden from display #}
    {% if r.turnitin_score is not none %}
        <span class="small text-muted fw-semibold">Turnitin</span>
        {# 5-tier colour scale per current Turnitin documentation:
           0% = green (no match), 1-24% = blue (low), 25-49% = yellow (medium),
           50-74% = orange (high), 75-100% = red (very high) #}
        {% if r.turnitin_score == 0 %}
            {% set score_class = "text-success" %}
            {% set badge_class = "bg-success" %}
            {% set score_label = "No match" %}
        {% elif r.turnitin_score < 25 %}
            {% set score_class = "text-primary" %}
            {% set badge_class = "bg-primary" %}
            {% set score_label = "Low" %}
        {% elif r.turnitin_score < 50 %}
            {% set score_class = "text-warning" %}
            {% set badge_class = "bg-warning text-dark" %}
            {% set score_label = "Medium" %}
        {% elif r.turnitin_score < 75 %}
            {% set score_class = "" %}
            {% set badge_class = "bg-warning text-dark" %}
            {% set score_label = "High" %}
        {% else %}
            {% set score_class = "text-danger" %}
            {% set badge_class = "bg-danger" %}
            {% set score_label = "Very high" %}
        {% endif %}
        <span class="small">
            Similarity:
            <strong class="{{ score_class }}"{% if r.turnitin_score >= 50 and r.turnitin_score < 75 %} style="color: #fd7e14"{% endif %}>
                {{ r.turnitin_score }}%
            </strong>
        </span>
        <span class="badge {{ badge_class }} small">{{ score_label }}</span>
        {% if r.turnitin_web_overlap is not none %}
            <span class="small text-muted">Web: {{ r.turnitin_web_overlap }}%</span>
        {% endif %}
        {% if r.turnitin_publication_overlap is not none %}
            <span class="small text-muted">Pub: {{ r.turnitin_publication_overlap }}%</span>
        {% endif %}
        {% if r.turnitin_student_overlap is not none %}
            <span class="small text-muted">Student: {{ r.turnitin_student_overlap }}%</span>
        {% endif %}
    {% endif %}
{% endmacro %}
{% macro identity_line(parts) %}
    {% if parts|length > 0 %}
        <div class="small text-muted mt-1 d-flex flex-row flex-wrap align-items-center gap-1">
            {% for part in parts %}
                {% if not loop.first %}<span>&middot;</span>{% endif %}
                <span>{{ part }}</span>
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% macro consent_badges(record) %}
    {% set avd_state = record.openday_consent_badge_state %}
    {% set ex_state = record.exemplar_consent_badge_state %}
    {% if avd_state is not none or ex_state is not none %}
        <div class="mt-1 d-flex flex-row flex-wrap align-items-center gap-2">
            {% if avd_state == 'active' %}
                <span class="badge rounded-pill badge-db-teal">
                    <i class="fas fa-graduation-cap fa-fw"></i> AVD consent active
                </span>
            {% elif avd_state == 'withdrawn' %}
                <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis">
                    <i class="fas fa-exclamation-triangle fa-fw"></i> AVD consent withdrawn
                </span>
            {% elif avd_state == 'invited' %}
                <span class="small text-muted">
                    <i class="fas fa-envelope fa-fw"></i> AVD: invited, awaiting response
                </span>
            {% endif %}

            {% if ex_state == 'active' %}
                {% if record.exemplar_supervisor_approved is sameas true %}
                    {% set supervisor_word = 'approved' %}
                {% elif record.exemplar_supervisor_approved is sameas false %}
                    {% set supervisor_word = 'declined' %}
                {% else %}
                    {% set supervisor_word = 'pending' %}
                {% endif %}
                <span class="small text-muted">Exemplar: student active, supervisor {{ supervisor_word }}</span>
            {% elif ex_state == 'withdrawn' %}
                <span class="small text-muted">Exemplar: withdrawn</span>
            {% elif ex_state == 'invited' %}
                <span class="small text-muted">Exemplar: invited, awaiting response</span>
            {% endif %}
        </div>
    {% endif %}
{% endmacro %}
{% macro flags_line(record, convenor_intervention, out_of_tolerance_unassigned) %}
    {% if convenor_intervention or out_of_tolerance_unassigned or record.turnitin_score is not none %}
        <div class="mt-1 d-flex flex-row flex-wrap align-items-center gap-2">
            {% if convenor_intervention %}
                <span class="badge rounded-pill bg-danger-subtle text-danger-emphasis border border-danger-subtle">
                    <i class="fas fa-exclamation-triangle fa-fw"></i> Convenor intervention
                </span>
            {% endif %}
            {% if out_of_tolerance_unassigned %}
                <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle">
                    <i class="fas fa-balance-scale fa-fw"></i> Out of tolerance &mdash; moderator not yet assigned
                </span>
            {% endif %}
            {{ turnitin_chips(record) }}
        </div>
    {% endif %}
{% endmacro %}
{% macro staff_roles(roles, moderator_role_id, moderation_outcome) %}
    {% if roles|length > 0 %}
        <div class="mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
            {% for role_id, group in roles|groupby('role') %}
                <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-1">
                    <span class="small text-muted fw-semibold">
                        {{ group[0].role_as_str }}{{ 's' if group|length > 1 else '' }}:
                    </span>
                    {% for role in group %}
                        <span class="small">
                            <a class="text-decoration-none" href="mailto:{{ role.user.email }}">{{ role.user.name }}</a>
                        </span>
                    {% endfor %}
                    {% if role_id == moderator_role_id and moderation_outcome %}
                        <span class="small text-muted">&mdash; {{ moderation_outcome }}</span>
                    {% endif %}
                </div>
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% set user = record.owner.student.user %}
<div class="d-flex flex-row gap-3 align-items-start">
    {# Thumbnail, or restriction indicator in the same slot #}
    {% if record.is_report_restricted %}
        <div style="width:64px; height:64px; border-radius:6px; border:0.5px solid var(--bs-danger-border-subtle);
                    background:var(--bs-danger-bg-subtle); display:flex; align-items:center; justify-content:center; flex-shrink:0"
             data-bs-toggle="tooltip" title="Restricted until {{ record.report_embargo.strftime("%a %d %b %Y %H:%M") }}">
            <i class="fas fa-lock fa-lg" style="color: var(--bs-danger-text-emphasis)"></i>
        </div>
    {% elif record.processed_report and record.processed_report.small_thumbnail and not record.processed_report.small_thumbnail.lost %}
        <img src="{{ url_for('documents.serve_thumbnail', asset_type='GeneratedAsset', asset_id=record.processed_report.id, size='small') }}"
             alt="Report thumbnail" width="64" height="64"
             style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color); flex-shrink: 0">
    {% elif record.report and record.report.small_thumbnail and not record.report.small_thumbnail.lost %}
        <img src="{{ url_for('documents.serve_thumbnail', asset_type='SubmittedAsset', asset_id=record.report_id, size='small') }}"
             alt="Report thumbnail" width="64" height="64"
             style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color); flex-shrink: 0">
    {% else %}
        <div style="width:64px; height:64px; border-radius:6px; border:0.5px solid var(--bs-border-color);
                    background:var(--bs-tertiary-bg); display:flex; align-items:center; justify-content:center; flex-shrink:0">
            <i class="fas fa-file-alt fa-lg" style="color: var(--bs-secondary-color)"></i>
        </div>
    {% endif %}

    <div class="flex-grow-1 bg-light p-2 rounded">
        <div class="d-flex flex-row justify-content-between align-items-start gap-2">
            <div class="flex-grow-1">
                {# Student name + project title #}
                <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-2">
                    <a class="text-decoration-none fw-semibold" href="mailto:{{ user.email }}">{{ user.name }}</a>
                    {% if record.project is not none %}
                        <span class="text-muted">&middot;</span>
                        <span class="fw-semibold small">{{ record.project.name }}</span>
                    {% else %}
                        <span class="small text-muted fst-italic">No project assigned</span>
                    {% endif %}
                </div>

                {# Identity line: programme, research group, project class, year, period, grades #}
                {{ identity_line(identity_parts) }}

                {# Consent badges #}
                {{ consent_badges(record) }}

                {# Convenor intervention / out-of-tolerance / Turnitin flags #}
                {{ flags_line(record, convenor_intervention, out_of_tolerance_unassigned) }}

                {# Staff roles, generic over role type #}
                {{ staff_roles(roles, moderator_role_id, moderation_outcome) }}
            </div>

            {# Download buttons #}
            <div class="d-flex flex-column justify-content-start align-items-end gap-1">
                {% if record.report_secret %}
                    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Report restricted</span>
                {% elif record.is_report_restricted %}
                    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Restricted until {{ record.report_embargo.strftime("%a %d %b %Y %H:%M") }}</span>
                {% else %}
                    {% if record.report is not none %}
                        <a class="btn btn-xs btn-outline-primary"
                           href="{{ url_for('admin.download_submitted_asset', asset_id=record.report_id) }}"
                           data-bs-toggle="tooltip" title="Download original report">
                            <i class="fas fa-file-download fa-fw"></i> Original
                        </a>
                    {% endif %}
                    {% if record.processed_report is not none %}
                        <a class="btn btn-xs btn-outline-secondary"
                           href="{{ url_for('admin.download_generated_asset', asset_id=record.processed_report_id) }}"
                           data-bs-toggle="tooltip" title="Download processed report">
                            <i class="fas fa-file-pdf fa-fw"></i> Processed
                        </a>
                    {% endif %}
                    {% if record.report is none and record.processed_report is none %}
                        <span class="badge bg-light text-muted border">No report</span>
                    {% endif %}
                {% endif %}
            </div>
        </div>
    </div>
</div>
"""


def _build_report_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_report)


def _supervision_presentation_grades(
    record: SubmissionRecord,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (supervision_grade, presentation_grade), or None for either when
    not yet graded or not applicable to this period's configuration."""
    grades = {g["label"]: g["grade"] for g in record.grade_display_data()}
    return grades.get("Supervision"), grades.get("Presentation")


def _identity_line_parts(
    record: SubmissionRecord,
    simple_label,
    supervision_grade: Optional[float],
    presentation_grade: Optional[float],
) -> List:
    """Build the ordered list of fragments for the Report panel's identity line:
    programme, research group, project class (colour badge, kept inline per the
    agreed two-column design), year, submission period, supervision grade,
    presentation grade. All plain text except the project-class badge."""
    period = record.period
    config = period.config
    programme = record.owner.student.programme
    group = record.project.group if record.project is not None else None

    parts = []
    if programme is not None:
        parts.append(programme.full_name)
    if group is not None:
        parts.append(group.name)
    parts.append(simple_label(config.project_class.make_label()))
    parts.append("{0}–{1}".format(config.year, config.year + 1))
    if period is not None:
        parts.append(period.display_name)
    parts.append("Supervision {0}".format("{:.1f}%".format(supervision_grade) if supervision_grade is not None else "—"))
    parts.append("Presentation {0}".format("{:.1f}%".format(presentation_grade) if presentation_grade is not None else "—"))
    return parts


def _latest_submitter_report(record: SubmissionRecord) -> Optional[SubmitterReport]:
    """The most recently created SubmitterReport for this record, or None if the record
    has not (yet) entered a marking workflow. A record can accumulate more than one
    SubmitterReport across re-marking events; the most recent is the one relevant to the
    dashboard's marking-history display."""
    return record.submitter_reports.order_by(
        SubmitterReport.creation_timestamp.desc(), SubmitterReport.id.desc()
    ).first()


def _moderation_outcome_text(sr: Optional[SubmitterReport]) -> Optional[str]:
    """Outcome text for the moderator role-group's line, derived from the record's latest
    SubmitterReport. Returns None when there is nothing to report (tolerance never breached,
    or this is an unchosen second moderator role on a record with more than one)."""
    if sr is None:
        return None
    if sr.accepted_moderator_report_id is not None:
        return "grade accepted"
    if sr.was_moderated:
        if any(r.report_submitted for r in sr.moderator_reports):
            return "moderator report submitted, awaiting acceptance"
        return "awaiting moderator's report"
    return None


def avd_dashboard_rows(records: List[SubmissionRecord]):
    """Row formatter for the AVD dashboard: one row per SubmissionRecord
    belonging to a closed SubmissionPeriodRecord. Two columns: a single rich
    "Report" panel (student, project, identity line, consent, flags, staff
    roles, downloads) and the sortable "Report grade" column."""
    simple_label = get_template_attribute("labels.html", "simple_label")

    report_templ: Template = _build_report_templ()

    data = []
    for record in records:
        supervision_grade, presentation_grade = _supervision_presentation_grades(record)

        report_grade = float(record.report_grade) if record.report_grade is not None else None

        roles = record.roles.all()
        has_moderator_role = any(r.role == SubmissionRole.ROLE_MODERATOR for r in roles)
        latest_sr = _latest_submitter_report(record)
        moderation_outcome = _moderation_outcome_text(latest_sr) if has_moderator_role else None
        convenor_intervention = bool(latest_sr is not None and latest_sr.convenor_intervention)
        out_of_tolerance_unassigned = bool(
            latest_sr is not None and latest_sr.out_of_tolerance and not has_moderator_role
        )

        identity_parts = _identity_line_parts(record, simple_label, supervision_grade, presentation_grade)

        data.append(
            {
                "report": {
                    "display": render_template(
                        report_templ,
                        record=record,
                        identity_parts=identity_parts,
                        roles=roles,
                        moderator_role_id=SubmissionRole.ROLE_MODERATOR,
                        moderation_outcome=moderation_outcome,
                        convenor_intervention=convenor_intervention,
                        out_of_tolerance_unassigned=out_of_tolerance_unassigned,
                    ),
                    "sortstring": record.owner.student.user.last_name + record.owner.student.user.first_name,
                },
                "report_grade": {
                    "display": "{:.1f}%".format(report_grade) if report_grade is not None else "&mdash;",
                    "sortvalue": report_grade,
                },
            }
        )

    return data
