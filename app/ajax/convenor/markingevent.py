#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, get_template_attribute, render_template
from flask_wtf.csrf import generate_csrf
from markupsafe import escape

from ...models.markingevent import MarkingEventWorkflowStates, SubmitterReportWorkflowStates
from ...shared.forms.wtf_validators import SchemaValidationError, parse_schema

# Convenience dict injected into every render_template call so Jinja2 templates can
# reference MarkingEventWorkflowStates constants by short name.
_EVENT_STATES = {
    "WAITING": MarkingEventWorkflowStates.WAITING,
    "OPEN": MarkingEventWorkflowStates.OPEN,
    "READY_TO_CONFLATE": MarkingEventWorkflowStates.READY_TO_CONFLATE,
    "READY_TO_GENERATE_FEEDBACK": MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK,
    "READY_TO_PUSH_FEEDBACK": MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK,
    "CLOSED": MarkingEventWorkflowStates.CLOSED,
}

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
            <div>
                <i class="fas fa-clipboard-check me-1"></i>
                <span class="text-primary">{{ wf.name }}</span>
                {% if wf.completed %}
                    <span class="badge bg-success ms-1 small">Complete</span>
                {% endif %}
            </div>
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
{% set targets = event.targets_as_dict %}
{% if targets %}
    <hr class="my-2">
    <div class="small text-muted fw-semibold mb-1">Targets</div>
    {% set conflation_reports = event.conflation_reports.all() %}
    {% if conflation_reports %}
        {% set any_stale = conflation_reports | selectattr('is_stale') | list | length > 0 %}
        {% if any_stale %}
            <span class="badge bg-warning text-dark mb-1"><i class="fas fa-exclamation-triangle fa-fw"></i> Results may be stale</span>
        {% endif %}
        {# Show first record's results as a representative sample #}
        {% set sample = conflation_reports[0].conflation_report_as_dict %}
        {% for name, expr in targets.items() %}
            <div class="small font-monospace mt-1">
                <span class="text-primary">{{ name }}</span>
                {% if name in sample %}
                    = <strong>{{ "%.1f"|format(sample[name]) }}%</strong>
                    <span class="text-muted">({{ conflation_reports|length }} records)</span>
                {% else %}
                    <span class="text-muted fst-italic">— not yet conflated</span>
                {% endif %}
            </div>
        {% endfor %}
    {% else %}
        {% for name, expr in targets.items() %}
            <div class="small font-monospace mt-1"><span class="text-primary">{{ name }}</span> = <span class="text-muted fst-italic">Not yet conflated</span></div>
        {% endfor %}
    {% endif %}
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
{% if workflow.key %}
    <div class="small font-monospace mt-1 text-muted">key: <span class="text-primary">{{ workflow.key }}</span></div>
{% endif %}
<div class="small text-muted mt-1">Role: {{ workflow.role_as_str }}</div>
{% set deadline = workflow.effective_deadline %}
{% if deadline is not none %}
    <div class="small text-muted mt-1"><i class="fas fa-clock fa-fw"></i> Deadline: {{ deadline.strftime("%d/%m/%Y") }}</div>
{% endif %}
"""

# language=jinja2
_marking_workflow_scheme = """
{% if workflow.scheme is not none %}
    <div class="text-success"><i class="fas fa-check-circle"></i> {{ workflow.scheme.name }}</div>
    {% if workflow.scheme.creation_timestamp is not none
         and workflow.scheme.parent is not none
         and workflow.scheme.parent.last_edit_timestamp is not none
         and workflow.scheme.creation_timestamp < workflow.scheme.parent.last_edit_timestamp %}
        <div class="mt-1">
            <span class="badge bg-warning text-dark">
                <i class="fas fa-exclamation-triangle fa-fw"></i> Scheme has been updated
            </span>
        </div>
    {% endif %}
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
{% set failure_count = workflow.number_processing_failures %}
<div class="small">
    <div><i class="fas fa-user-graduate"></i> <strong>{{ submitter_count }}</strong> submitter report{{ 's' if submitter_count != 1 else '' }}</div>
    <div class="mt-1"><i class="fas fa-marker"></i> <strong>{{ marking_count }}</strong> marking report{{ 's' if marking_count != 1 else '' }}</div>
    {% if failure_count > 0 %}
        <div class="mt-1"><span class="badge bg-danger">{{ failure_count }} processing failure{{ 's' if failure_count != 1 else '' }}</span></div>
    {% endif %}
</div>
"""

# language=jinja2
_marking_workflow_distribution = """
{% set total = workflow.number_marking_reports %}
{% set distributed = workflow.number_marking_reports_distributed %}
{% set not_distributed = workflow.number_marking_reports_undistributed %}
{% set failure_count = workflow.number_processing_failures %}
<div class="small">
    {% if distributed > 0 %}
        <div class="text-success"><i class="fas fa-check-circle"></i> {{ distributed }} distributed</div>
    {% endif %}
    {% if not_distributed > 0 %}
        {% if workflow.event.workflow_state >= OPEN and workflow.event.workflow_state != CLOSED %}
            <div class="text-danger"><i class="fas fa-exclamation-circle"></i> {{ not_distributed }} not distributed</div>
            <div class="mt-1">
                <a href="{{ url_for('convenor.send_marking_emails_for_workflow', workflow_id=workflow.id) }}"
                   class="btn btn-xs btn-outline-secondary">
                    <i class="fas fa-envelope fa-fw"></i> Send notifications
                </a>
            </div>
        {% else %}
            <div class="text-muted"><i class="fas fa-clock fa-fw"></i> {{ not_distributed }} pending opening</div>
        {% endif %}
    {% endif %}
    {% if failure_count > 0 %}
        <div class="mt-1"><span class="badge bg-danger">{{ failure_count }} processing failure{{ 's' if failure_count != 1 else '' }}</span></div>
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
{% set asset = report.record.processed_report %}
{% if asset is not none %}
    <div class="d-flex flex-row flex-wrap justify-content-between align-items-start gap-2 mt-2">
        {% if asset.medium_thumbnail is not none and not asset.medium_thumbnail.lost %}
            <img src="{{ url_for('documents.serve_thumbnail', asset_type='GeneratedAsset', asset_id=asset.id, size='medium') }}"
                 class="img-thumbnail mb-1" style="max-width:200px; max-height:200px;" alt="Preview">
        {% elif asset.small_thumbnail is not none and not asset.small_thumbnail.lost %}
            <img src="{{ url_for('documents.serve_thumbnail', asset_type='GeneratedAsset', asset_id=asset.id, size='small') }}"
                 class="img-thumbnail mb-1" style="max-width:150px; max-height:150px;" alt="Preview">
        {% endif %}
        <a href="{{ url_for('admin.download_generated_asset', asset_id=asset.id) }}"
           class="btn btn-xs btn-outline-secondary" data-bs-toggle="tooltip" title="Download processed report">
            <i class="fas fa-file-pdf fa-fw"></i> Download
        </a>
    </div>
{% endif %}
{% if report.record.report_processing_failed %}
    <div class="d-flex flex-row flex-wrap justify-content-between align-items-start gap-2 mt-1">
        <span class="text-danger"><i class="fas fa-exclamation-triangle"></i> Processing failed</span>
        <a href="{{ url_for('convenor.restart_report_processing', record_id=report.record.id) }}"
           class="btn btn-xs btn-outline-danger ms-1">
            <i class="fas fa-redo fa-fw"></i> Restart
        </a>
    </div>
{% endif %}
"""

# language=jinja2
_submitter_report_actions = """
{% set rec = report.record %}
{% set state = report.workflow_state %}
{% set is_completed = (state == COMPLETED) %}
{% set inspector_url = url_for('convenor.submitter_reports_inspector', workflow_id=report.workflow_id) %}

{# --- Direct action buttons (shown above the dropdown) --- #}
{% if state == NEEDS_MODERATOR_ASSIGNED %}
    <a class="btn btn-danger btn-sm full-width-button mb-2"
       href="{{ url_for('convenor.assign_moderator', submitter_report_id=report.id,
                url=inspector_url, text='Submitter reports') }}">
        <i class="fas fa-user-plus fa-fw"></i> Assign moderator
    </a>
{% elif state == READY_TO_SIGN_OFF %}
    <form method="POST"
          action="{{ url_for('convenor.complete_submitter_report', sr_id=report.id) }}"
          class="mb-2">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button class="btn btn-success btn-sm full-width-button" type="submit">
            <i class="fas fa-check-double fa-fw"></i> Complete
        </button>
    </form>
{% elif is_completed %}
    <div class="mb-2">
        <span class="badge bg-success py-2 px-3">
            <i class="fas fa-check-circle fa-fw"></i> Completed
        </span>
        {% if report.completed_by is not none %}
            <div class="small text-muted mt-1">by {{ report.completed_by.name }}</div>
        {% endif %}
        {% if report.completed_timestamp is not none %}
            <div class="small text-muted">{{ report.completed_timestamp.strftime("%d/%m/%Y") }}</div>
        {% endif %}
    </div>
{% endif %}

{# --- Actions dropdown --- #}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">

        {# Complete: shown in dropdown for READY_TO_SIGN_OFF (in addition to direct button) #}
        {% if state == READY_TO_SIGN_OFF %}
            <form method="POST"
                  action="{{ url_for('convenor.complete_submitter_report', sr_id=report.id) }}"
                  style="display:contents">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <button class="dropdown-item d-flex gap-2" type="submit">
                    <i class="fas fa-check-double fa-fw"></i> Complete&hellip;
                </button>
            </form>
            <div class="dropdown-divider"></div>
        {% endif %}

        {# Return to convenor: admin/root only, shown when COMPLETED #}
        {% if is_completed and (is_root or is_admin) %}
            <form method="POST"
                  action="{{ url_for('convenor.return_submitter_report_to_convenor', sr_id=report.id) }}"
                  style="display:contents">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <button class="dropdown-item d-flex gap-2 text-danger" type="submit">
                    <i class="fas fa-undo fa-fw"></i> Return to convenor&hellip;
                </button>
            </form>
            <div class="dropdown-divider"></div>
        {% endif %}

        {# Moderator assignment: shown for NEEDS_MODERATOR_ASSIGNED and AWAITING_MODERATOR_REPORT, disabled when COMPLETED #}
        {% if state in (NEEDS_MODERATOR_ASSIGNED, AWAITING_MODERATOR_REPORT) %}
            <a class="dropdown-item d-flex gap-2 {% if is_completed %}disabled{% endif %}"
               href="{{ url_for('convenor.assign_moderator', submitter_report_id=report.id,
                        url=inspector_url, text='Submitter reports') }}">
                <i class="fas fa-user-plus fa-fw"></i> Assign moderator&hellip;
            </a>
            <div class="dropdown-divider"></div>
        {% endif %}

        {# Risk factors: resolve (only shown when unresolved factors are present, disabled when COMPLETED) #}
        {% if rec is not none and rec.has_unresolved_risk_factors %}
            <a class="dropdown-item d-flex gap-2 {% if is_completed %}disabled{% endif %}"
               href="{{ url_for('convenor.resolve_risk_factors',
                                record_id=rec.id,
                                url=inspector_url, text='Submitter reports') }}">
                <i class="fas fa-gavel fa-fw"></i> Resolve risk factors&hellip;
            </a>
        {% endif %}

        {# Turnitin: re-fetch from Canvas or enter manually (only when score is missing, disabled when COMPLETED) #}
        {% if rec is not none and rec.turnitin_score is none %}
            {% if rec.canvas_turnitin_refetchable %}
                <form method="POST"
                      action="{{ url_for('convenor.refetch_turnitin_from_canvas',
                                         record_id=rec.id,
                                         url=inspector_url) }}"
                      style="display:contents">
                    <button class="dropdown-item d-flex gap-2{% if is_completed %} disabled{% endif %}" type="submit"
                            {% if is_completed %}disabled{% endif %}>
                        <i class="fas fa-sync fa-fw"></i> Re-fetch Turnitin from Canvas
                    </button>
                </form>
            {% endif %}
            <a class="dropdown-item d-flex gap-2 {% if is_completed %}disabled{% endif %}"
               href="{{ url_for('convenor.enter_turnitin_score',
                                record_id=rec.id,
                                url=inspector_url, text='Submitter reports') }}">
                <i class="fas fa-keyboard fa-fw"></i> Enter Turnitin score&hellip;
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_submitter_report_grade = """
{% if report.grade is not none %}
    <div class="text-primary fw-semibold fs-4">{{ "%.1f"|format(report.grade) }}%</div>
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
# Feedback is now tracked on ConflationReport, not SubmitterReport.
# This column is a placeholder until feedback generation is implemented in the next ticket.
_submitter_report_feedback = """
<span class="badge bg-secondary text-muted">Via conflation</span>
"""

# language=jinja2
_submitter_report_risk_factors = """
{% set rec = report.record %}
{% if rec is not none %}
    <div class="d-flex flex-column gap-1">
        {# ── Risk factor badges ── #}
        {% set rf = rec.risk_factors_ui_summary() %}
        {% if rf.has_any_present %}
            {% for factor in rf.factors %}
                {% if factor.resolved %}
                    <span class="badge bg-success" data-bs-toggle="tooltip" title="Resolved{% if factor.resolved_by_name %} by {{ factor.resolved_by_name }}{% endif %}">
                        <i class="fas fa-check-circle fa-fw"></i> {{ factor.label }}
                    </span>
                {% else %}
                    <span class="badge bg-danger">
                        <i class="fas fa-exclamation-triangle fa-fw"></i> {{ factor.label }}
                    </span>
                {% endif %}
            {% endfor %}
            {% if rf.has_unresolved %}
                <a href="{{ url_for('convenor.resolve_risk_factors',
                           record_id=rec.id,
                           url=url_for('convenor.submitter_reports_inspector', workflow_id=report.workflow_id),
                           text='Submitter reports') }}"
                   class="btn btn-xs btn-outline-danger mt-1">
                    <i class="fas fa-gavel fa-fw"></i> Resolve&hellip;
                </a>
            {% endif %}
        {% else %}
            <span class="badge bg-success"><i class="fas fa-check-circle fa-fw"></i> No risk factors</span>
        {% endif %}

        {# ── Language metrics summary (shown when analysis is complete) ── #}
        {% if rec.language_analysis_complete %}
            {% set la = rec.language_analysis_data %}
            {% set metrics = la.get('metrics', {}) %}
            {% set flags = la.get('flags', {}) %}
            {% set concern = flags.get('ai_concern', 'low') %}
            {% set sigma = flags.get('mahalanobis_sigma') %}
            {% set pval = flags.get('mahalanobis_pvalue') %}

            <hr class="my-1" style="border-color: rgba(0,0,0,.1);">

            {# Per-metric flags: MATTR, MTLD, CV (burstiness omitted for space) #}
            <div class="d-flex flex-wrap gap-1" style="font-size:0.75em;">
                {% for key, label in [('mattr', 'MATTR'), ('mtld', 'MTLD'), ('sentence_cv', 'CV')] %}
                    {% set val = metrics.get(key) %}
                    {% set flag = flags.get(key ~ '_flag', 'ok') %}
                    {% if val is not none %}
                        <span class="text-muted">{{ label }}:
                            <strong>
                                {% if key == 'mtld' %}{{ "%.1f"|format(val) }}
                                {% else %}{{ "%.3f"|format(val) }}{% endif %}
                            </strong>
                            {% if flag == 'strong' %}
                                <span class="badge bg-danger" style="font-size:0.75em">!</span>
                            {% elif flag == 'note' %}
                                <span class="badge bg-warning text-dark" style="font-size:0.75em">~</span>
                            {% endif %}
                        </span>
                    {% endif %}
                {% endfor %}
            </div>

            {# AI concern row with sigma and p-value #}
            <div class="d-flex flex-wrap align-items-center gap-2 mt-1" style="font-size:0.78em;">
                {% if concern == 'high' %}
                    <span class="badge bg-danger">High concern</span>
                {% elif concern == 'medium' %}
                    <span class="badge bg-warning text-dark">Medium concern</span>
                {% elif concern == 'uncalibrated' %}
                    <span class="badge bg-secondary"
                          data-bs-toggle="tooltip"
                          title="AI concern system not yet calibrated for this tenant.">
                        Not calibrated
                    </span>
                {% else %}
                    <span class="badge bg-success">Low concern</span>
                {% endif %}
                {% if sigma is not none %}
                    <span class="text-muted">σ&nbsp;=&nbsp;<strong>{{ "%.2f"|format(sigma) }}</strong></span>
                {% endif %}
                {% if pval is not none %}
                    <span class="text-muted">p&nbsp;=&nbsp;<strong>
                        {% if pval >= 0.001 %}{{ "%.3f"|format(pval) }}
                        {% elif pval >= 0.0001 %}{{ "%.1e"|format(pval) }}
                        {% else %}&lt;0.0001{% endif %}
                    </strong></span>
                {% endif %}
            </div>

            <a href="{{ url_for('documents.llm_report',
                       record_id=rec.id,
                       url=url_for('convenor.submitter_reports_inspector', workflow_id=report.workflow_id),
                       text='Submitter reports') }}"
               class="btn btn-xs btn-outline-secondary mt-1">
                <i class="fas fa-chart-bar fa-fw"></i> LLM report
            </a>
        {% endif %}
    </div>
{% else %}
    <span class="badge bg-light text-muted border">No data</span>
{% endif %}
"""

# language=jinja2
_submitter_report_reports = """
{%- set marking_reports = report.marking_reports.all() -%}
{%- set moderator_reports = report.moderator_reports.all() -%}
<div class="d-flex flex-column gap-2">
    {% for mr in marking_reports %}
        <div class="bg-light p-2 mb-2">
            <div class="d-flex flex-column justify-content-start align-items-start gap-1">
                <div class="fw-semibold">{{ mr.user.name }}</div>
                <div class="text-muted small">{{ mr.role.role_as_str }}</div>
                {% if mr.grade is not none %}
                    <span class="text-primary fw-semibold fs-4">{{ "%.1f"|format(mr.grade) }}%</span>
                {% endif %}
                {% if mr.report_submitted %}
                    <span class="text-success small"><i
                            class="fas fa-check-circle"></i> Report submitted</span>
                {% else %}
                    <span class="text-secondary small fst-italic"><i
                            class="fas fa-hourglass-half"></i> Awaiting report</span>
                {% endif %}
                {% if mr.feedback_submitted %}
                    <span class="text-success small"><i
                            class="fas fa-comment"></i> Feedback submitted</span>
                {% else %}
                    <span class="text-secondary small fst-italic"><i
                            class="fas fa-hourglass-half"></i> Awaiting feedback</span>
                {% endif %}
                {% if mr.signed_off_by is not none %}
                    <div>
                        <div class="small text-success fw-semibold"><i class="fas fa-check-circle"></i> Signed off</div>
                        <div class="small text-muted mt-1">by <i class="fas fa-user"></i> {{ mr.signed_off_by.user.name }}</div>
                        {% if mr.signed_off_timestamp is not none %}
                            <div class="small text-muted">{{ mr.signed_off_timestamp.strftime("%d/%m/%Y") }}</div>
                        {% endif %}
                    </div>
                {% else %}
                        <span class="text-secondary small fst-italic small"><i
                                class="fas fa-hourglass-half"></i> Awaiting signoff</span>
                {% endif %}
            </div>
        </div>
    {% endfor %}
    {% if moderator_reports %}
        <hr class="my-1">
        {% for mod_report in moderator_reports %}
            <div class="bg-light p-2 mb-2">
                <div class="d-flex flex-column justify-content-start align-items-start gap-1">
                    <div class="text-muted fst-italic">Moderator: {{ mod_report.user.name }}</div>
                    {% if mod_report.report_submitted %}
                        {% if mod_report.grade is not none %}
                            <span class="text-danger fw-semibold fs-4">{{ "%.1f"|format(mod_report.grade) }}%</span>
                        {% endif %}
                        <span class="text-success"><i
                                class="fas fa-check-circle"></i> Report submitted</span>
                        <form method="POST"
                              action="{{ url_for('convenor.accept_moderator_grade', mod_report_id=mod_report.id, workflow_id=report.workflow_id) }}"
                              class="d-inline ms-1">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                            <button class="btn btn-xs btn-outline-success" type="submit">
                                <i class="fas fa-check fa-fw"></i> Accept
                            </button>
                        </form>
                    {% else %}
                        <span class="text-secondary fst-italic"><i
                                class="fas fa-hourglass-half"></i> Awaiting report</span>
                    {% endif %}
                </div>
            </div>
        {% endfor %}
    {% endif %}
</div>
"""

# language=jinja2
_marking_report_marker = """
<div class="fw-semibold">{{ report.user.name }}</div>
<div class="small text-muted mt-1">{{ report.role.role_as_str }}</div>
{% if report.weight is not none %}
    <div class="mt-1 small">
        <i class="fas fa-balance-scale fa-fw"></i> Weight: <strong>{{ report.weight }}</strong>
    </div>
{% endif %}
{{ offcanvas|safe }}
"""

# language=jinja2
_marking_report_student = """
<div class="fw-semibold">{{ report.student.user.name }}</div>
<div class="small text-muted mt-1">{{ report.student.exam_number }}</div>
"""

# language=jinja2
_marking_report_grade = """
{% if report.grade is not none %}
    <div class="text-primary fw-semibold fs-4">{{ "%.1f"|format(report.grade) }}%</div>
    {% if report.grade_submitted_by is not none %}
        <div class="small text-muted mt-1">by {{ report.grade_submitted_by.name }}</div>
    {% endif %}
    {% if report.grade_submitted_timestamp is not none %}
        <div class="small text-muted">{{ report.grade_submitted_timestamp.strftime("%d %b %Y %H:%M") }}</div>
    {% endif %}
{% else %}
    <span class="badge bg-secondary">Not graded</span>
{% endif %}
"""

# language=jinja2
_marking_report_status = """
<div class="d-flex flex-column justify-content-start align-items-start gap-1 small">
    {% if report.distributed %}
        <span class="text-success fw-semibold"><i class="fas fa-check-circle"></i> Distributed to marker</span>
    {% else %}
        <span class="text-danger fst-italic"><i class="fas fa-hourglass-half"></i> Awaiting distribution</span>
    {% endif %}
    {% if report.report_submitted %}
        <span class="text-success"><i
                class="fas fa-check-circle"></i> Report submitted</span>
    {% else %}
        <span class="text-secondary fst-italic"><i
                class="fas fa-hourglass-half"></i> Awaiting report</span>
    {% endif %}
    {% if report.feedback_submitted %}
        <span class="text-success"><i
                class="fas fa-comment"></i> Feedback submitted</span>
    {% else %}
        <span class="text-secondary fst-italic"><i
                class="fas fa-hourglass-half"></i> Awaiting feedback</span>
    {% endif %}
</div>
"""

# language=jinja2
_marking_report_signoff = """
{% if report.signed_off_by is not none %}
    <div class="small text-success fw-semibold"><i class="fas fa-check-circle"></i> Signed off</div>
    <div class="small text-muted mt-1">by <i class="fas fa-user"></i> {{ report.signed_off_by.user.name }}</div>
    {% if report.signed_off_timestamp is not none %}
        <div class="small text-muted">{{ report.signed_off_timestamp.strftime("%d/%m/%Y") }}</div>
    {% endif %}
{% else %}
        <span class="text-secondary fst-italic small"><i
                class="fas fa-hourglass-half"></i> Awaiting signoff</span>
{% endif %}
"""

# language=jinja2
_mr_emails_offcanvas = """
{# Offcanvas: distribution email history for a single MarkingReport.
   Extensible: add further sections (e.g. feedback emails) below the distribution emails section. #}
<a class="text-muted text-decoration-none small" role="button" data-bs-toggle="offcanvas" href="#mr_info_{{ report.id }}"
   aria-controls="edit_{{ report.id }}">Show info <i class="fas fa-chevron-right"></i></a>
<div class="offcanvas offcanvas-start text-bg-light" tabindex="-1"
     id="mr_info_{{ report.id }}" aria-labelledby="mr_info_label_{{ report.id }}">
    <div class="offcanvas-header border-bottom">
        <h5 class="offcanvas-title" id="mr_info_label_{{ report.id }}">
            <i class="fas fa-envelope fa-fw me-1"></i> {{ report.user.name }}
        </h5>
        <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
    </div>
    <div class="offcanvas-body small">
        {# Section: distribution emails #}
        <h6 class="text-primary border-bottom pb-1 mb-2">
            <i class="fas fa-paper-plane fa-fw me-1"></i> Distribution emails
        </h6>
        {% set emails = report.distribution_emails.all() %}
        {% if emails %}
            <table class="table table-sm table-borderless">
                <thead class="text-muted">
                    <tr>
                        <th>Subject</th>
                        <th>Sent</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {% for email in emails %}
                        <tr>
                            <td>{{ email.subject or "(no subject)" }}</td>
                            <td class="text-nowrap">{{ email.send_date.strftime("%d/%m/%Y %H:%M") if email.send_date else "&mdash;"|safe }}</td>
                            <td>
                                <a href="{{ url_for('admin.display_email', id=email.id,
                                           url=url_for('convenor.marking_reports_inspector',
                                                       workflow_id=report.submitter_report.workflow_id),
                                           text='Marking reports') }}"
                                   class="btn btn-xs btn-outline-secondary"
                                   data-bs-toggle="tooltip" title="View email">
                                    <i class="fas fa-eye fa-fw"></i>
                                </a>
                            </td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p class="text-muted fst-italic">No distribution emails recorded.</p>
        {% endif %}
        {# Future sections can be appended here #}
    </div>
</div>
"""

# language=jinja2
_marking_report_actions = """
{% set event = report.submitter_report.workflow.event %}
{% set workflow = report.submitter_report.workflow %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2"
           href="{{ url_for('faculty.marking_form', report_id=report.id,
                     url=url_for('convenor.marking_reports_inspector', workflow_id=workflow.id)) }}">
            <i class="fas fa-pen fa-fw"></i> {% if report.report_submitted %}Edit{% else %}View{% endif %} report&hellip;
        </a>
        <a class="dropdown-item d-flex gap-2"
           href="{{ url_for('convenor.marking_report_properties', report_id=report.id,
                     url=url_for('convenor.marking_reports_inspector', workflow_id=workflow.id)) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Edit properties&hellip;
        </a>
        {% if report.grade_submitted_timestamp is not none %}
            <form method="POST"
                  action="{{ url_for('convenor.clear_marking_grade', report_id=report.id,
                             url=url_for('convenor.marking_reports_inspector', workflow_id=workflow.id)) }}"
                  style="display:contents">
                <button class="dropdown-item d-flex gap-2 text-warning" type="submit">
                    <i class="fas fa-undo fa-fw"></i> Clear grade&hellip;
                </button>
            </form>
        {% endif %}
        {% if event.workflow_state >= OPEN and event.workflow_state != CLOSED %}
            <div class="dropdown-divider"></div>
            {% if not report.distributed %}
                <form method="POST"
                      action="{{ url_for('convenor.dispatch_marking_report', report_id=report.id,
                                 url=url_for('convenor.marking_reports_inspector',
                                             workflow_id=report.submitter_report.workflow_id)) }}"
                      style="display:contents">
                    <button class="dropdown-item d-flex gap-2" type="submit">
                        <i class="fas fa-envelope fa-fw"></i> Dispatch email
                    </button>
                </form>
            {% else %}
                <form method="POST"
                      action="{{ url_for('convenor.dispatch_marking_report', report_id=report.id,
                                 resend='true',
                                 url=url_for('convenor.marking_reports_inspector',
                                             workflow_id=report.submitter_report.workflow_id)) }}"
                      style="display:contents">
                    <button class="dropdown-item d-flex gap-2" type="submit">
                        <i class="fas fa-redo fa-fw"></i> Re-send email
                    </button>
                </form>
            {% endif %}
        {% endif %}
        {% if report.distribution_emails.count() > 0 %}
            <button class="dropdown-item d-flex gap-2" type="button"
                    data-bs-toggle="offcanvas" data-bs-target="#mr_info_{{ report.id }}"
                    aria-controls="mr_info_{{ report.id }}">
                <i class="fas fa-envelope-open fa-fw"></i> View emails ({{ report.distribution_emails.count() }})
            </button>
        {% endif %}
    </div>
</div>
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
            "distribution": render_template(distribution_tmpl, workflow=workflow, **_EVENT_STATES),
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
    reports_tmpl = env.from_string(_submitter_report_reports)
    grade_tmpl = env.from_string(_submitter_report_grade)
    signoff_tmpl = env.from_string(_submitter_report_signoff)
    feedback_tmpl = env.from_string(_submitter_report_feedback)
    risk_factors_tmpl = env.from_string(_submitter_report_risk_factors)
    actions_tmpl = env.from_string(_submitter_report_actions)

    from flask_login import current_user as _cu
    from flask_security import current_user as _scu

    _roles = set(r.name for r in _cu.roles) if hasattr(_cu, "roles") else set()
    state_ctx = {
        "NEEDS_MODERATOR_ASSIGNED": SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED,
        "AWAITING_MODERATOR_REPORT": SubmitterReportWorkflowStates.AWAITING_MODERATOR_REPORT,
        "READY_TO_SIGN_OFF": SubmitterReportWorkflowStates.READY_TO_SIGN_OFF,
        "COMPLETED": SubmitterReportWorkflowStates.COMPLETED,
        "is_root": "root" in _roles,
        "is_admin": "admin" in _roles,
        "csrf_token": generate_csrf,
    }

    return [
        {
            "student": render_template(student_tmpl, report=report),
            "project": render_template(project_tmpl, report=report),
            "reports": render_template(reports_tmpl, report=report),
            "grade": render_template(grade_tmpl, report=report),
            "signoff": render_template(signoff_tmpl, report=report),
            "feedback": render_template(feedback_tmpl, report=report),
            "risk_factors": render_template(risk_factors_tmpl, report=report),
            "actions": render_template(actions_tmpl, report=report, **state_ctx),
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
    offcanvas_tmpl = env.from_string(_mr_emails_offcanvas)
    actions_tmpl = env.from_string(_marking_report_actions)

    return [
        {
            "marker": render_template(
                marker_tmpl,
                report=report,
                offcanvas=render_template(offcanvas_tmpl, report=report),
            ),
            "student": render_template(student_tmpl, report=report),
            "grade": render_template(grade_tmpl, report=report),
            "status": render_template(status_tmpl, report=report),
            "signoff": render_template(signoff_tmpl, report=report),
            "actions": render_template(actions_tmpl, report=report, **_EVENT_STATES),
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
    try:
        return parse_schema(raw)
    except SchemaValidationError:
        return None


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


# language=jinja2
_period_marking_event_status = """
{% if event.workflow_state == CLOSED %}
    <span class="text-secondary"><i class="fas fa-check-circle"></i> Closed</span>
{% elif event.workflow_state == READY_TO_PUSH_FEEDBACK %}
    <span class="text-success"><i class="fas fa-paper-plane"></i> Ready to push feedback</span>
{% elif event.workflow_state == READY_TO_GENERATE_FEEDBACK %}
    <span class="text-success"><i class="fas fa-file-alt"></i> Ready to generate feedback</span>
{% elif event.workflow_state == READY_TO_CONFLATE %}
    <span class="text-success"><i class="fas fa-calculator"></i> Ready to conflate</span>
{% elif event.workflow_state == OPEN %}
    <span class="text-primary"><i class="fas fa-check-circle"></i> Open &mdash; marking in progress</span>
{% else %}
    {% set has_workflows = event.workflows.count() > 0 %}
    {% if has_workflows %}
        <span class="text-secondary"><i class="fas fa-hourglass-half"></i> Waiting</span>
        <div class="mt-2">
            <a href="{{ url_for('convenor.open_marking_event', event_id=event.id) }}"
               class="btn btn-xs btn-outline-primary">
                <i class="fas fa-play fa-fw"></i> Open event&hellip;
            </a>
        </div>
    {% else %}
        <span class="text-secondary"><i class="fas fa-hourglass-half"></i> Waiting</span>
        <div class="mt-2">
            <span class="badge bg-secondary">No workflows configured</span>
        </div>
    {% endif %}
{% endif %}
"""

# language=jinja2
_period_marking_event_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.event_marking_workflows_inspector', event_id=event.id, url=url, text=text) }}">
            <i class="fas fa-search fa-fw"></i> Inspect workflows&hellip;
        </a>
        {% if event.workflow_state == WAITING %}
            {% if event.workflows.count() > 0 %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.open_marking_event', event_id=event.id) }}">
                    <i class="fas fa-play fa-fw"></i> Open event&hellip;
                </a>
            {% else %}
                <span class="dropdown-item d-flex gap-2 disabled text-muted">
                    <i class="fas fa-play fa-fw"></i> Open event&hellip;
                </span>
            {% endif %}
            <div class="dropdown-divider"></div>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_marking_event', event_id=event.id, url=url, text=text) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit&hellip;
        </a>
        {% if event.workflow_state != CLOSED %}
            <div class="dropdown-divider"></div>
            <a class="dropdown-item d-flex gap-2 text-warning" href="{{ url_for('convenor.close_marking_event_confirm', event_id=event.id, url=url, text=text) }}">
                <i class="fas fa-lock fa-fw"></i> Close event&hellip;
            </a>
        {% endif %}
        {% if can_delete %}
            <div class="dropdown-divider"></div>
            <a class="dropdown-item d-flex gap-2 text-danger" href="{{ url_for('convenor.delete_marking_event', event_id=event.id, url=url, text=text) }}">
                <i class="fas fa-trash fa-fw"></i> Delete&hellip;
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_event_marking_workflow_menu = """
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
        {% if can_edit %}
            <div class="dropdown-divider"></div>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_marking_workflow', workflow_id=workflow.id, url=url, text=text) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit&hellip;
            </a>
            <a class="dropdown-item d-flex gap-2 text-danger" href="{{ url_for('convenor.delete_marking_workflow', workflow_id=workflow.id, url=url, text=text) }}">
                <i class="fas fa-trash fa-fw"></i> Delete&hellip;
            </a>
        {% endif %}
    </div>
</div>
"""


def period_marking_event_data(url, text, can_delete, events):
    """Format a MarkingEvent row for the per-period CRUD inspector DataTable"""

    env = current_app.jinja_env

    period_tmpl = env.from_string(_marking_event_period)
    name_tmpl = env.from_string(_marking_event_name)
    workflows_tmpl = env.from_string(_marking_event_workflows)
    status_tmpl = env.from_string(_period_marking_event_status)
    menu_tmpl = env.from_string(_period_marking_event_menu)

    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    return [
        {
            "period": render_template(period_tmpl, event=event),
            "name": render_template(name_tmpl, event=event, small_swatch=small_swatch),
            "workflows": render_template(workflows_tmpl, event=event),
            "status": render_template(status_tmpl, event=event, **_EVENT_STATES),
            "menu": render_template(
                menu_tmpl,
                event=event,
                pclass=event.pclass,
                url=url,
                text=text,
                can_delete=can_delete,
                **_EVENT_STATES,
            ),
        }
        for event in events
    ]


def event_marking_workflow_data(url, text, can_edit, workflows):
    """Format a MarkingWorkflow row for the per-event CRUD inspector DataTable"""

    env = current_app.jinja_env

    name_tmpl = env.from_string(_marking_workflow_name)
    scheme_tmpl = env.from_string(_marking_workflow_scheme)
    attachments_tmpl = env.from_string(_marking_workflow_attachments)
    reports_tmpl = env.from_string(_marking_workflow_reports)
    distribution_tmpl = env.from_string(_marking_workflow_distribution)
    feedback_tmpl = env.from_string(_marking_workflow_feedback)
    menu_tmpl = env.from_string(_event_marking_workflow_menu)

    return [
        {
            "name": render_template(name_tmpl, workflow=workflow),
            "scheme": render_template(scheme_tmpl, workflow=workflow),
            "attachments": render_template(attachments_tmpl, workflow=workflow),
            "reports": render_template(reports_tmpl, workflow=workflow),
            "distribution": render_template(distribution_tmpl, workflow=workflow, **_EVENT_STATES),
            "feedback": render_template(feedback_tmpl, workflow=workflow),
            "menu": render_template(
                menu_tmpl, workflow=workflow, url=url, text=text, can_edit=can_edit
            ),
        }
        for workflow in workflows
    ]


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
