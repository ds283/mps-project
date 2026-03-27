#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, get_template_attribute, render_template, url_for
from jinja2 import Template
from markupsafe import escape

from ...shared.forms.wtf_validators import parse_schema

# language=jinja2
_marking_event_period = """
<div class="text-primary">{{ event.period.display_name }}</div>
<div class="small text-muted mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
    <div class="text-secondary">{{ event.config.year }}&ndash;{{ event.config.year+1 }}</div>
    {% if event.period.start_date %}
        <div class="text-secondary"><i class="fas fa-calendar"></i> Start: {{ event.period.start_date.strftime("%d/%m/%Y") }}</div>
    {% endif %}
    {% if event.period.hand_in_date %}
        <div class="text-secondary"><i class="fas fa-calendar"></i> Hand-in: {{ event.period.hand_in_date.strftime("%d/%m/%Y") }}</div>
    {% endif %}
</div>
"""

# language=jinja2
_marking_event_name = """
<div>{{ event.name }}</div>
{% set pclass = event.pclass %}
{% set swatch_colour = pclass.make_CSS_style() %}
<div class="d-flex flex-row justify-content-start align-items-center gap-2">
    {{ small_swatch(swatch_colour) }}
    <span class="small">{{ pclass.name }}</span>
</div>
"""

# language=jinja2
_marking_event_workflows = """
{% set workflows = event.workflows.all() %}
{% if workflows|length > 0 %}
    <div class="d-flex flex-column gap-1">
        {% for wf in workflows %}
            <div><i class="fas fa-clipboard-check me-1"></i> <span class="text-primary">{{ wf.name }}</span></div>
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_marking_event_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.marking_workflow_inspector', event_id=event.id, url=url_for('convenor.marking_events_inspector', pclass_id=pclass.id), text='Assessment archive') }}">
            <i class="fas fa-search fa-fw"></i> Inspect workflows&hellip;
        </a>
    </div>
</div>
"""

# language=jinja2
_marking_workflow_name = """
<div class="fw-semibold">{{ workflow.name }}</div>
<div class="small text-muted mt-1">Role: {{ workflow.role_as_str }}</div>
"""

# language=jinja2
_marking_workflow_scheme = """
{% if workflow.scheme is not none %}
    <div class="text-success"><i class="fas fa-check-circle"></i> {{ workflow.scheme.name }}</div>
{% else %}
    <span class="badge bg-warning text-dark">No scheme</span>
{% endif %}
"""

# language=jinja2
_marking_workflow_attachments = """
{% if workflow.attachments|length > 0 %}
    <div class="d-flex flex-column gap-1">
        {% for att in workflow.attachments %}
            <div class="small">
                <i class="fas fa-paperclip"></i> {{ att.filename }}
            </div>
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_marking_workflow_reports = """
{% set submitter_count = workflow.number_submitter_reports %}
{% set marking_count = workflow.number_marking_reports %}
<div class="small">
    <div><i class="fas fa-user-graduate"></i> <strong>{{ submitter_count }}</strong> submitter report{{ 's' if submitter_count != 1 else '' }}</div>
    <div class="mt-1"><i class="fas fa-marker"></i> <strong>{{ marking_count }}</strong> marking report{{ 's' if marking_count != 1 else '' }}</div>
</div>
"""

# language=jinja2
_marking_workflow_distribution = """
{% set total = workflow.number_marking_reports %}
{% set distributed = workflow.number_marking_reports_distributed %}
{% set not_distributed = total - distributed %}
<div class="small">
    {% if distributed > 0 %}
        <div class="text-success"><i class="fas fa-check-circle"></i> {{ distributed }} distributed</div>
    {% endif %}
    {% if not_distributed > 0 %}
        <div class="text-danger"><i class="fas fa-times-circle"></i> {{ not_distributed }} not distributed</div>
    {% endif %}
    {% if total == 0 %}
        <span class="badge bg-secondary">No reports</span>
    {% endif %}
</div>
"""

# language=jinja2
_marking_workflow_feedback = """
{% set total = workflow.marking_reports.count() %}
{% set submitted = workflow.number_marking_reports_with_feedback %}
{% set not_submitted = total - submitted %}
<div class="small">
    {% if submitted > 0 %}
        <div class="text-success"><i class="fas fa-check-circle"></i> {{ submitted }} submitted</div>
    {% endif %}
    {% if not_submitted > 0 %}
        <div class="text-danger"><i class="fas fa-exclamation-circle"></i> {{ not_submitted }} not submitted</div>
    {% endif %}
    {% if total == 0 %}
        <span class="badge bg-secondary">No reports</span>
    {% endif %}
</div>
"""

# language=jinja2
_marking_workflow_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.submitter_reports_inspector', workflow_id=workflow.id, url=url, text=text) }}">
            <i class="fas fa-user-graduate fa-fw"></i> Submitter reports&hellip;
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.marking_reports_inspector', workflow_id=workflow.id, url=url, text=text) }}">
            <i class="fas fa-marker fa-fw"></i> Marking reports&hellip;
        </a>
    </div>
</div>
"""

# language=jinja2
_submitter_report_student = """
<div class="fw-semibold">{{ report.student.user.name }}</div>
<div class="small text-muted mt-1">{{ report.student.exam_number }}</div>
"""

# language=jinja2
_submitter_report_project = """
{% if report.record.project is not none %}
    <div>{{ report.record.project.name }}</div>
    {% if not report.record.project.generic and report.record.project.owner is not none %}
        <div class="small text-muted mt-1">{{ report.record.project.owner.user.name }}</div>
    {% endif %}
{% else %}
    <span class="badge bg-warning text-dark">No project</span>
{% endif %}
"""

# language=jinja2
_submitter_report_grade = """
{% if report.grade is not none %}
    <div class="text-primary fw-semibold">{{ "%.1f"|format(report.grade) }}%</div>
    {% if report.grade_generated_by is not none %}
        <div class="small text-muted mt-1">by {{ report.grade_generated_by.name }}</div>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">Not graded</span>
{% endif %}
"""

# language=jinja2
_submitter_report_signoff = """
{% if report.signed_off_by is not none %}
    <div class="text-success"><i class="fas fa-check-circle"></i> Signed off</div>
    <div class="small text-muted mt-1">by {{ report.signed_off_by.name }}</div>
    {% if report.signed_off_timestamp is not none %}
        <div class="small text-muted">{{ report.signed_off_timestamp.strftime("%d/%m/%Y") }}</div>
    {% endif %}
{% else %}
    <span class="badge bg-warning text-dark">Not signed off</span>
{% endif %}
"""

# language=jinja2
_submitter_report_feedback = """
{% if report.feedback_sent %}
    <div class="text-success"><i class="fas fa-check-circle"></i> Sent</div>
    {% if report.feedback_push_timestamp is not none %}
        <div class="small text-muted mt-1">{{ report.feedback_push_timestamp.strftime("%d/%m/%Y") }}</div>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">Not sent</span>
{% endif %}
"""

# language=jinja2
_marking_report_marker = """
<div class="fw-semibold">{{ report.user.name }}</div>
<div class="small text-muted mt-1">{{ report.role.role_as_str }}</div>
"""

# language=jinja2
_marking_report_student = """
<div class="fw-semibold">{{ report.student.user.name }}</div>
<div class="small text-muted mt-1">{{ report.student.exam_number }}</div>
"""

# language=jinja2
_marking_report_grade = """
{% if report.grade is not none %}
    <div class="text-primary fw-semibold">{{ "%.1f"|format(report.grade) }}%</div>
{% else %}
    <span class="badge bg-secondary">Not graded</span>
{% endif %}
"""

# language=jinja2
_marking_report_status = """
<div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-1">
    {% if report.distributed %}
        <span class="badge bg-success">Distributed</span>
    {% else %}
        <span class="badge bg-danger">Not distributed</span>
    {% endif %}
    {% if report.report_submitted %}
        <span class="badge bg-success">Report</span>
    {% else %}
        <span class="badge bg-warning text-dark">Report pending</span>
    {% endif %}
    {% if report.feedback_submitted %}
        <span class="badge bg-success">Feedback</span>
    {% else %}
        <span class="badge bg-secondary">Feedback pending</span>
    {% endif %}
</div>
"""

# language=jinja2
_marking_report_signoff = """
{% if report.signed_off_by is not none %}
    <div class="text-success"><i class="fas fa-check-circle"></i> Signed off</div>
    <div class="small text-muted mt-1">by {{ report.signed_off_by.user.name }}</div>
    {% if report.signed_off_timestamp is not none %}
        <div class="small text-muted">{{ report.signed_off_timestamp.strftime("%d/%m/%Y") }}</div>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">Not signed off</span>
{% endif %}
"""


def marking_event_data(events):
    """Format a MarkingEvent row for DataTables"""

    env = current_app.jinja_env

    period_tmpl = env.from_string(_marking_event_period)
    name_tmpl = env.from_string(_marking_event_name)
    workflows_tmpl = env.from_string(_marking_event_workflows)
    menu_tmpl = env.from_string(_marking_event_menu)

    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    return [
        {
            "period": render_template(period_tmpl, event=event),
            "name": render_template(name_tmpl, event=event, small_swatch=small_swatch),
            "workflows": render_template(workflows_tmpl, event=event),
            "menu": render_template(menu_tmpl, event=event, pclass=event.pclass),
        }
        for event in events
    ]


def marking_workflow_data(url, text, workflows):
    """Format a MarkingWorkflow row for DataTables"""

    env = current_app.jinja_env

    name_tmpl = env.from_string(_marking_workflow_name)
    scheme_tmpl = env.from_string(_marking_workflow_scheme)
    attachments_tmpl = env.from_string(_marking_workflow_attachments)
    reports_tmpl = env.from_string(_marking_workflow_reports)
    distribution_tmpl = env.from_string(_marking_workflow_distribution)
    feedback_tmpl = env.from_string(_marking_workflow_feedback)
    menu_tmpl = env.from_string(_marking_workflow_menu)

    return [
        {
            "name": render_template(name_tmpl, workflow=workflow),
            "scheme": render_template(scheme_tmpl, workflow=workflow),
            "attachments": render_template(attachments_tmpl, workflow=workflow),
            "reports": render_template(reports_tmpl, workflow=workflow),
            "distribution": render_template(distribution_tmpl, workflow=workflow),
            "feedback": render_template(feedback_tmpl, workflow=workflow),
            "menu": render_template(menu_tmpl, workflow=workflow, url=url, text=text),
        }
        for workflow in workflows
    ]


def submitter_report_data(reports):
    """Format a SubmitterReport row for DataTables"""

    env = current_app.jinja_env

    student_tmpl = env.from_string(_submitter_report_student)
    project_tmpl = env.from_string(_submitter_report_project)
    grade_tmpl = env.from_string(_submitter_report_grade)
    signoff_tmpl = env.from_string(_submitter_report_signoff)
    feedback_tmpl = env.from_string(_submitter_report_feedback)

    return [
        {
            "student": render_template(student_tmpl, report=report),
            "project": render_template(project_tmpl, report=report),
            "grade": render_template(grade_tmpl, report=report),
            "signoff": render_template(signoff_tmpl, report=report),
            "feedback": render_template(feedback_tmpl, report=report),
        }
        for report in reports
    ]


def marking_report_data(reports):
    """Format a MarkingReport row for DataTables"""

    env = current_app.jinja_env

    marker_tmpl = env.from_string(_marking_report_marker)
    student_tmpl = env.from_string(_marking_report_student)
    grade_tmpl = env.from_string(_marking_report_grade)
    status_tmpl = env.from_string(_marking_report_status)
    signoff_tmpl = env.from_string(_marking_report_signoff)

    return [
        {
            "marker": render_template(marker_tmpl, report=report),
            "student": render_template(student_tmpl, report=report),
            "grade": render_template(grade_tmpl, report=report),
            "status": render_template(status_tmpl, report=report),
            "signoff": render_template(signoff_tmpl, report=report),
        }
        for report in reports
    ]


_POPOVER_TEXT_MAX = 80


def _parse_scheme_schema(scheme) -> dict | None:
    """Adapter: extract and validate schema from a MarkingScheme or LiveMarkingScheme object."""
    try:
        raw = scheme.schema_as_dict
    except Exception:
        return None
    return parse_schema(raw)


def _make_schema_block_summaries(schema) -> list | None:
    """
    Convert a validated schema dict (from parse_schema) into a list of
    summary dicts suitable for passing to the _marking_scheme_schema template.
    Returns None if schema is None.
    """
    if schema is None:
        return None

    summaries = []
    for block in schema["scheme"]:
        lines = []
        for field in block["fields"]:
            text = field["text"]
            if len(text) > _POPOVER_TEXT_MAX:
                text = text[:_POPOVER_TEXT_MAX] + "\u2026"
            field_type = field["field_type"]["type"]
            lines.append(
                f"<span class='badge bg-secondary'>{escape(field_type)}</span> {escape(text)}"
            )
        summaries.append(
            {
                "title": str(escape(block["title"])),
                "question_count": len(block["fields"]),
                "popover_html": "<br>".join(lines),
            }
        )

    return summaries


# language=jinja2
_marking_scheme_name = """
<div class="text-primary">{{ scheme.name }}</div>
"""

# language=jinja2
_marking_scheme_details = """
<div class="small d-flex flex-column justify-content-start align-items-start gap-2">
    {% if scheme.uses_standard_feedback %}
        <div class="text-success"><i class="fas fa-check-circle"></i> Standard feedback</div>
    {% endif %}
    {% if scheme.uses_tolerance %}
        <div class="text-success"><i class="fas fa-check-circle"></i> Enforce tolerance: {{ "%.1f"|format(scheme.marker_tolerance) }}%</div>
    {% endif %}
</div>
"""

# language=jinja2
_marking_scheme_schema = """
{% if schema_blocks %}
    <div class="d-flex flex-column gap-2 small">
        {% for block in schema_blocks %}
            <div>
                <span tabindex="0"
                      role="button"
                      data-bs-toggle="popover"
                      data-bs-trigger="hover focus"
                      data-bs-html="true"
                      data-bs-title="{{ block.title }}"
                      data-bs-content="{{ block.popover_html }}"
                      class="text-primary">{{ block.title }}</span>
                <span class="ms-1 text-muted">&ndash; {{ block.question_count }} question{{ 's' if block.question_count != 1 else '' }}</span>
            </div>
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">No schema</span>
{% endif %}
"""

# language=jinja2
_marking_scheme_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_marking_scheme', scheme_id=scheme.id, url=url, text=text) }}">
            <i class="fas fa-edit fa-fw"></i> Edit scheme&hellip;
        </a>
    </div>
</div>
"""


def marking_scheme_data(url, text, schemes):
    """Format a MarkingScheme row for DataTables"""

    env = current_app.jinja_env

    name_tmpl = env.from_string(_marking_scheme_name)
    details_tmpl = env.from_string(_marking_scheme_details)
    schema = env.from_string(_marking_scheme_schema)
    menu_tmpl = env.from_string(_marking_scheme_menu)

    return [
        {
            "name": render_template(name_tmpl, scheme=scheme),
            "details": render_template(details_tmpl, scheme=scheme),
            "schema": render_template(
                schema,
                scheme=scheme,
                schema_blocks=_make_schema_block_summaries(
                    _parse_scheme_schema(scheme)
                ),
            ),
            "menu": render_template(menu_tmpl, scheme=scheme, url=url, text=text),
        }
        for scheme in schemes
    ]
