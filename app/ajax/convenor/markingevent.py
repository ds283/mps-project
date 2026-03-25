#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template, url_for
from jinja2 import Template

# language=jinja2
_marking_event_period = """
<div class="text-primary">{{ event.period.display_name }}</div>
<div class="small text-muted mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
    {% if event.period.start_date %}
        <div><i class="fas fa-calendar"></i> Start: {{ event.period.start_date.strftime("%d/%m/%Y") }}</div>
    {% endif %}
    {% if event.period.hand_in_data %}
        <div><i class="fas fa-calendar"></i> Hand-in: {{ event.period.hand_in_date.strftime("%d/%m/%Y") }}</div>
    {% endif %}
</div>
"""

# language=jinja2
_marking_event_name = """
<div>{{ event.name }}</div>
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
            <i class="fas fa-search fa-fw"></i> Inspect workflows...
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
        <div class="text-warning"><i class="fas fa-exclamation-circle"></i> {{ not_submitted }} not submitted</div>
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
            <i class="fas fa-user-graduate fa-fw"></i> Submitter reports...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.marking_reports_inspector', workflow_id=workflow.id, url=url, text=text) }}">
            <i class="fas fa-marker fa-fw"></i> Marking reports...
        </a>
    </div>
</div>
"""

# language=jinja2
_submitter_report_student = """
<div class="fw-semibold">{{ report.record.owner.student.user.name }}</div>
<div class="small text-muted mt-1">{{ report.record.owner.student.exam_number }}</div>
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
<div class="fw-semibold">{{ report.role.user.name }}</div>
<div class="small text-muted mt-1">{{ report.role.role_as_str }}</div>
"""

# language=jinja2
_marking_report_student = """
<div class="fw-semibold">{{ report.submitter_report.record.owner.student.user.name }}</div>
<div class="small text-muted mt-1">{{ report.submitter_report.record.owner.student.exam_number }}</div>
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

    def _format(event):
        pclass = event.period.config.project_class

        return {
            "period": render_template(period_tmpl, event=event),
            "name": render_template(name_tmpl, event=event),
            "workflows": render_template(workflows_tmpl, event=event),
            "menu": render_template(menu_tmpl, event=event, pclass=pclass),
        }

    return [_format(event) for event in events]


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
