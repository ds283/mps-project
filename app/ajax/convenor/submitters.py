#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute
from ...models import ProjectClassConfig


# language=jinja2
_cohort = \
"""
{{ sub.student.programme.short_label|safe }}
{{ sub.student.cohort_label|safe }}
{{ sub.academic_year_label(show_details=True)|safe }}
"""


# language=jinja2
_periods = \
"""
{% macro feedback_state_tag(obj, state=none) %}
    {% if state is none %}{% set state = obj.feedback_state %}{% endif %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="badge bg-secondary">Feedback not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <div class="badge bg-secondary">Feedback to do</div>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <div class="badge bg-success">Feedback submitted</div>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <div class="badge bg-warning text-dark">Feedback in progress</div>        
    {% elif state == obj.FEEDBACK_LATE %}
        <div class="badge bg-danger">Feedback late</div>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <div class="badge bg-danger">Feedback error &ndash; unknown state</div>
    {% endif %}        
{% endmacro %}
{% macro response_state_tag(obj, label) %}
    {% set state = obj.response_state %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="badge bg-secondary">Response not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <div class="badge bg-secondary">Response to do</div>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <div class="badge bg-success">Response submitted</div>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <div class="badge bg-warning text-dark">Response in progress</div>        
    {% elif state == obj.FEEDBACK_LATE %}
        <div class="badge bg-danger">Response late</div>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <div class="badge bg-danger">Response error &ndash; unknown state</div>
    {% endif %}        
{% endmacro %}
{% macro roles_list(roles, label) %}
    {% set num_roles = roles|length %}
    {% if num_roles > 0 %}
        <div>
            <div class="text-muted small">{{ label }}</div>
            {% for role in roles %}
                <a class="badge text-decoration-none text-nohover-light bg-info btn-table-block" href="mailto:{{ role.user.email }}">{{ role.user.name }}</a>
                {{ feedback_state_tag(role) }}
                {{ response_state_tag(role) }}
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% macro project_tag(r, show_period) %}
    {% set sub = r.owner %}
    {% set config = sub.config %}
    {% set pclass = config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set period = r.period %}
    {% set current_period = config.current_period %}
    {% set submissions = config.submissions %}
    <div class="bg-light p-2 mb-2 {% if submissions > 1 and period.submission_period == current_period.submission_period %}border border-info{% endif %}">
        {% if r.project is not none %}
            <div class="d-flex flex-row justify-content-start align-items-center gap-2">
                {% if r.project.name|length < 70 %}
                    <div>{{ r.project.name }}</div>
                {% else %}
                    <div>{{ r.project.name[0:70] }}...</div>
                {% endif %}
                {% if r.has_issues %}
                    <i class="fas fa-exclamation-triangle text-danger"></i>
                {% endif %}
                {% if r.project.generic or r.project.owner is none %}
                    <div class="badge bg-info">GENERIC</div>
                {% else %}
                    <div class="small text-muted">
                        Project owner
                        <a href="mailto:{{ r.project.owner.user.email }}">{{ r.project.owner.user.name }}</a>
                    </div>
                {% endif %}
                <div class="dropdown assignment-label">
                    <a class="badge text-decoration-none text-nohover-light bg-secondary dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">Change</a>
                    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                        {% set disabled = period.is_feedback_open or r.student_engaged %}
                        {% if disabled %}
                            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-exclamation-triangle fa-fw"></i> Can't reassign project</a>
                        {% else %}
                            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.manual_assign', id=r.id, text='convenor submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
                                <i class="fas fa-folder fa-fw"></i> Assign project...
                            </a>
                            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.deassign_project', id=r.id) }}"><i class="fas fa-times fa-fw"></i> Deassign project</a>
                        {% endif %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_roles', sub_id=sub.id, record_id=r.id, text='convenor submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"><i class="fas fa-user-circle fa-fw"></i> Edit roles...</a>
                    </div>
                </div>
            </div>
            <div class="d-flex flex-row justify-content-start align-items-center gap-2">
                {% if show_period %}<div class="small text-muted"><em><strong>{{ period.display_name }}</strong></em></div>{% endif %}
                {% if sub.published %}
                    <div class="dropdown assignment-label">
                        <a class="badge text-decoration-none {% if r.student_engaged %}bg-success text-nohover-light{% else %}bg-warning text-nohover-dark{% endif %} btn-table-block dropdown-toggle"
                            href="" role="button" aria-haspopup="true" aria-expanded="false"
                            data-bs-toggle="dropdown">{% if r.student_engaged %}<i class="fas fa-check"></i> Started{% else %}<i class="fas fa-times"></i> Waiting{% endif %}</a>
                        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                            {% if r.submission_period > config.submission_period %}
                                <a class="dropdown-item d-flex gap-2 disabled">Submission period not yet open</a>
                            {% elif not r.student_engaged %}
                                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.mark_started', id=r.id) }}">
                                    <i class="fas fa-check fa-fw"></i> Mark as started
                                </a>
                            {% else %}
                                {% set disabled = (config.submitter_lifecycle >= config.SUBMITTER_LIFECYCLE_READY_ROLLOVER) %}
                                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.mark_waiting', id=r.id) }}"{% endif %}>
                                    <i class="fas fa-times fa-fw"></i> Mark as waiting
                                </a>
                            {% endif %}
                        </div>
                    </div>
                    {% if r.report is not none %}
                        <div class="badge bg-success"><i class="fas fa-check"></i> Report</div>
                    {% endif %}
                    {% set number_attachments = r.number_record_attachments %}
                    {% if number_attachments > 0 %}
                        <div class="badge bg-success"><i class="fas fa-check"></i> Attachments ({{ number_attachments }})</div>
                    {% endif %}
                    {% if r.report is none and period.canvas_enabled and not period.closed and r.canvas_submission_available is true %}
                        <a class="link-success text-decoration-none small" href="{{ url_for('documents.pull_report_from_canvas', rid=r.id, url=url_for('convenor.submitters', id=pclass.id)) }}">Pull report from Canvas...</a>
                    {% endif %}
                {% endif %}
            </div>
            <div class="d-flex flex-row justify-content-start align-items-start gap-4 mt-1">
                {% if config.uses_supervisor %}
                    {{ roles_list(r.supervisor_roles, 'Supervisor roles') }}
                {% endif %}
                {% if config.uses_marker %}
                    {{ roles_list(r.marker_roles, 'Marker roles') }}
                {% endif %}
                {% if config.uses_moderator %}
                    {{ roles_list(r.moderator_roles, 'Moderator roles') }}
                {% endif %}
                {% if config.uses_presentations and period.has_presentation %}
                    <div>
                        <div class="small text-muted">Presentation</div>
                        {% if period.has_deployed_schedule %}
                            {% set slot = r.schedule_slot %}
                            <div class="dropdown assignment-label">
                                {% if slot is not none %}
                                    <a class="badge text-decoration-none text-nohover-dark bg-info btn-table-block dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                                        {{ slot.short_date_as_string }}
                                        {{ slot.session_type_string }}
                                    </a>
                                {% else %}
                                    <a class="badge text-decoration-none text-nohover-dark bg-warning btn-table-block dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                                        Not attending
                                    </a>
                                {% endif %}
                                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                                    {% set disabled = not r.can_assign_feedback %}
                                    <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.assign_presentation_feedback', id=r.id, url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                                        <i class="fas fa-comments fa-fw"></i> Add new feedback
                                    </a>
                                </div>
                            </div>
                            {% if slot is not none %}
                                {% set fns = namespace(flag=false) %}
                                {% for a in slot.assessors %}
                                    <div>
                                        <a class="badge text-decoration-none text-nohover-light bg-info btn-table-block" href="mailto:{{ a.user.email }}">{{ a.user.name }}</a>
                                        {{ feedback_state_tag(r, r.presentation_feedback_state(a.id)) }}
                                        {% if slot.feedback_state(a.id) > slot.FEEDBACK_NOT_YET %}
                                            {% set fns.flag = true %}
                                        {% endif %}
                                    </div>
                                {% endfor %}
                                {% if fns.flag and r.number_presentation_feedback == 0 %}
                                    <div class="badge bg-danger">Feedback required</div>
                                {% endif %}
                            {% endif %}
                        {% else %}
                            <div class="badge bg-secondary">Awaiting scheduling</div>
                        {% endif %}
                    </div>
                {% endif %}
            </div>
        {% else %}
            <div class="d-flex flex-row justify-content-start align-items-center gap-2">
                <div class="small text-muted"><em><strong>{{ period.display_name }}</strong></em></div>
                <div>
                    <a class="badge text-decoration-none text-nohover-light bg-danger" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">No project allocated</a>
                </div>
            </div>
        {% endif %}
        {% if r.has_issues %}
            {% set errors = r.errors %}
            {% set warnings = r.warnings %}
            <div class="d-flex flex-row justify-content-start align-items-center gap-2 mt-2">
                {{ error_block_popover(errors, warnings) }}
            </div>
        {% endif %}
    </div>
{% endmacro %}
{% set recs = sub.ordered_assignments.all() %}
<div class="d-flex flex-row justify-content-start align-items-start gap-2"></div>
    {% for rec in recs %}
        {% set submissions = rec.owner.config.submissions %}
        {{ project_tag(rec, submissions > 1) }}
    {% else %}
        <div class="badge bg-danger">None</div>
    {% endfor %}
</div>
"""


# language=jinja2
_menu = \
"""
{% set config = sub.config %}
{% set pclass = config.project_class %}
{% set period = config.current_period %}
{% set record = sub.get_assignment() %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_student', id=sub.student.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit student...
            </a>
        {% endif %}
        {% if sub.student.has_timeline %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.timeline', student_id=sub.student.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fas fa-history fa-fw"></i> Show history... 
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_tasks', type=2, sid=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
            <i class="fas fa-tasks fa-fw"></i> Tasks...
        </a>
        
        {% if sub.published and pclass.publish %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.unpublish_assignment', id=sub.id) }}">
                <i class="fas fa-eye-slash fa-fw"></i> Unpublish
            </a>
        {% else %}
            {% if pclass.publish %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.publish_assignment', id=sub.id) }}">
                    <i class="fas fa-eye fa-fw"></i> Publish to student
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-eye-slash fa-fw"></i> Cannot publish
                </a>
            {% endif %}
        {% endif %}        
        <div role="separator" class="dropdown-divider"></div>

        {% set disabled = not pclass.publish %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('documents.submitter_documents', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-file fa-fw"></i> Manage documents...
        </a>
        {% if record.report_id is none and period.canvas_enabled and not period.closed and record.canvas_submission_available is true %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('documents.pull_report_from_canvas', rid=record.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fas fa-download fa-fw"></i> Pull report from Canvas
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.view_feedback', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-comments fa-fw"></i> View feedback...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.manual_assign', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-wrench fa-fw"></i> Assign project...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_roles', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
            <i class="fas fa-user-circle fa-fw"></i> Edit roles...
        </a>

        <div role="separator" class="dropdown-divider"></div>

        {% if allow_delete %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_submitter', sid=sub.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-trash fa-fw"></i> Delete disabled</a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_name = \
"""
{% set config = sub.config %}
{% set pclass = config.project_class %}
{% set student = sub.student %}
{% set user = student.user %}
<div>
    {% if config.canvas_enabled and sub is not none %}
        {% if sub.canvas_user_id is not none %}
            <i class="fa fa-circle me-1 text-success" data-bs-toggle="tooltip" title="This student is enrolled on the linked Canvas site"></i>
        {% elif sub.canvas_missing %}
            <i class="fa fa-circle me-1 text-danger" data-bs-toggle="tooltip" title="This student is not enrolled on the linked Canvas site"></i>
        {% else %}
            <i class="fa fa-unlink me-1" data-bs-toggle="tooltip" title="Information associated with this student for the linked Canvas site has not yet been synchronized"></i> 
        {% endif %}
    {% endif %}
    {% if show_name %}
        <a class="text-decoration-none" href="mailto:{{ user.email }}">{{ user.name }}</a>
        {% if sub.has_issues %}
            <i class="fas fa-exclamation-triangle text-danger"></i>
        {% endif %}
    {% endif %}
    {% if show_number %}
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a href="{{ url_for('manage_users.edit_student', id=student.id, url=url_for('convenor.submitters', id=pclass.id)) }}" class="badge bg-secondary text-decoration-none">
                #{{ student.exam_number }}
            </a>
        {% else %}
            <span class="badge bg-secondary">#{{ student.exam_number }}</span>
        {% endif %}
    {% endif %}
    {% set num_tasks = sub.number_available_tasks %}
    {% set pl = 's' %}{% if num_tasks == 1 %}{% set pl = '' %}{% endif %}
    {% if num_tasks > 0 %}
        <span class="badge bg-info">{{ num_tasks }} task{{ pl }}</span>
    {% endif %}
</div>
<div>
    {% if sub.published and pclass.publish %}
        <span class="badge bg-primary"><i class="fas fa-eye"></i> Published</span>
    {% else %}
        <span class="badge bg-warning text-dark"><i class="fas fa-eye-slash"></i> Unpublished</span>
    {% endif %}
</div>
{% if sub.has_issues %}
    {% set errors = sub.errors %}
    {% set warnings = sub.warnings %}
    <div class="mt-1">
        {{ error_block_inline(errors, warnings, max_errors=5, max_warnings=5) }}
{% endif %}
"""


def submitters_data(students, config, show_name, show_number, sort_number):
    submittter_state = config.submitter_lifecycle
    allow_delete = submittter_state <= ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY

    error_block_popover = get_template_attribute("error_block.html", "error_block_popover")
    error_block_inline = get_template_attribute("error_block.html", "error_block_inline")

    data = [{'name': {
                'display': render_template_string(_name, sub=s, show_name=show_name, show_number=show_number,
                                                  error_block_inline=error_block_inline),
                'sortvalue': s.student.exam_number if sort_number else s.student.user.last_name + s.student.user.first_name
             },
             'cohort': {
                 'display': render_template_string(_cohort, sub=s),
                 'value': s.student.cohort
             },
             'periods': render_template_string(_periods, sub=s, config=config, error_block_popover=error_block_popover),
             'menu': render_template_string(_menu, sub=s, allow_delete=allow_delete)} for s in students]

    return jsonify(data)
