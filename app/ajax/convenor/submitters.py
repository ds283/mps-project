#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify
from ...models import ProjectClassConfig


_cohort = \
"""
{{ sub.student.programme.short_label|safe }}
{{ sub.student.cohort_label|safe }}
{{ sub.academic_year_label(show_details=True)|safe }}
"""


_projects = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="badge badge-secondary">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="badge badge-secondary">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="badge badge-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="badge badge-warning">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="badge badge-danger">{{ label }} late</span>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <span class="badge badge-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro project_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div>
        {% if r.project is not none %}
            <div class="dropdown assignment-label">
                <a class="badge {% if style %}badge-secondary{% else %}badge-info{% endif %} btn-table-block dropdown-toggle"
                        {% if style %}style="{{ style }}"{% endif %}
                        role="button" aria-haspopup="true" aria-expanded="false"
                        data-toggle="dropdown">{% if show_period %}#{{ r.submission_period }}: {% endif %}
                    {% if r.project.name|length < 35 %}
                        {{ r.project.name }}
                    {% else %}
                        {{ r.project.name[0:35] }}...
                    {% endif %}
                    ({{ r.supervisor.user.last_name }})</a>
                <div class="dropdown-menu">
                    {% set disabled = r.period.is_feedback_open or r.student_engaged %}
                    {% if disabled %}
                        <a class="dropdown-item disabled">Can't reassign: Feedback open or student engaged</a>
                    {% else %}
                        <a class="dropdown-item" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Manually reassign</a>
                        <a class="dropdown-item" href="{{ url_for('convenor.deassign_project', id=r.id) }}">Remove assignment</a>
                    {% endif %}
                </div>
            </div>
            {% if sub.published %}
                <div class="dropdown assignment-label">
                    <a class="badge {% if r.student_engaged %}badge-success{% else %}badge-warning{% endif %} btn-table-block dropdown-toggle"
                        role="button" aria-haspopup="true" aria-expanded="false"
                        data-toggle="dropdown">{% if r.student_engaged %}<i class="fa fa-check"></i> Started{% else %}<i class="fa fa-times"></i> Waiting{% endif %}</a>
                    <div class="dropdown-menu">
                        {% if r.submission_period > r.owner.config.submission_period %}
                            <a class="dropdown-item disabled">Submission period not yet open</a>
                        {% elif not r.student_engaged %}
                            <a class="dropdown-item" href="{{ url_for('convenor.mark_started', id=r.id) }}">
                                <i class="fa fa-check"></i> Mark as started
                            </a>
                        {% else %}
                            {% set disabled = (r.owner.config.submitter_lifecycle >= r.owner.config.SUBMITTER_LIFECYCLE_READY_ROLLOVER) %}
                            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.mark_waiting', id=r.id) }}"{% endif %}>
                                <i class="fa fa-times"></i> Mark as waiting
                            </a>
                        {% endif %}
                    </div>
                </div>
                {% if r.report is not none %}
                    <span class="badge badge-success"><i class="fa fa-check"></i> Report</span>
                {% endif %}
                {% set number_attachments = r.number_record_attachments %}
                {% if number_attachments > 0 %}
                    <span class="badge badge-success"><i class="fa fa-check"></i> Attachments ({{ number_attachments }})</span>
                {% endif %}
            {% endif %}
        {% else %}
            <a class="badge badge-danger" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">No project allocated</a>
        {% endif %}
    </div>
{% endmacro %}
{% macro tag(r, show_period) %}
    <div>
        {{ project_tag(r, show_period) }}
        {{ feedback_state_tag(r, r.supervisor_feedback_state, 'Feedback') }}
        {{ feedback_state_tag(r, r.supervisor_response_state, 'Response') }}
    </div>
{% endmacro %}
{% if config.uses_supervisor %}
    {% set recs = sub.ordered_assignments.all() %}
    {% if recs|length == 1 %}
        {{ tag(recs[0], false) }}
    {% elif recs|length > 1 %}
        {% for rec in recs %}
            {% if loop.index > 1 %}<p></p>{% endif %}
            {{ tag(rec, true) }}
        {% endfor %}
    {% else %}
        <span class="badge badge-danger">None</span>
    {% endif %}
{% else %}
    <span class="badge badge-secondary">Not used</span>
{% endif %}
"""


_markers = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="badge badge-secondary">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="badge badge-secondary">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="badge badge-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="badge badge-warning">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="badge badge-danger">{{ label }} late</span>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <span class="badge badge-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro marker_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    <div>
        {% if r.marker is not none %}
            <div class="dropdown assignment-label">
                <a class="badge {% if style %}badge-secondary{% else %}badge-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                    {% if show_period %}#{{ r.submission_period }}: {% endif %}
                    {{ r.marker.user.name }}
                </a>
                <div class="dropdown-menu">
                    {% set disabled = r.period.is_feedback_open %}
                    {% if disabled %}
                        <a class="dropdown-item disabled">Can't reassign: Feedback open or student engaged</a>
                    {% else %}
                        <a class="dropdown-item" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Manually reassign</a>
                        <a class="dropdown-item" href="{{ url_for('convenor.deassign_marker', id=r.id) }}">Remove assignment</a>
                    {% endif %}
                </div>
            </div>
        {% else %}
            <a class="badge badge-danger" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">{% if r.project is none %}No project allocated{% else %}No marker allocated{% endif %}</a>
        {% endif %}
        {{ feedback_state_tag(r, r.marker_feedback_state, 'Feedback') }}
    </div>
{% endmacro %}
{% if config.uses_marker %}
    {% set recs = sub.ordered_assignments.all() %}
    {% if recs|length == 1 %}
        {{ marker_tag(recs[0], false) }}
    {% elif recs|length > 1 %}
        {% for rec in sub.ordered_assignments %}
            {% if loop.index > 1 %}<p></p>{% endif %}
            {{ marker_tag(rec, true) }}
        {% endfor %}
    {% else %}
        <span class="badge badge-danger">None</span>
    {% endif %}
{% else %}
    <span class="badge badge-secondary">Not used</span>
{% endif %}
"""


_presentations = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET or state == obj.FEEDBACK_NOT_REQUIRED %}
        {# empty #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="badge badge-secondary">{{ label }}: to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="badge badge-success">{{ label }}: submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="badge badge-warning">{{ label }}: in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="badge badge-danger">{{ label }}: late</span>
    {% else %}
        <span class="badge badge-danger">{{ label }}: error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% if config.uses_presentations %}
    {% set recs = sub.ordered_assignments.all() %}
    {% set ns = namespace(count=0) %}
    {% for rec in recs %}
        {% if rec.period.has_presentation %}
            {% set pclass = rec.owner.config.project_class %}
            {% set ns.count = ns.count + 1 %}
            <div>
                <span class="badge badge-primary">Pd. {{ rec.submission_period }}</span>
                {% if rec.period.has_deployed_schedule %}
                    {% set slot = rec.schedule_slot %}
                    <div class="dropdown assignment-label">
                        {% if slot is not none %}
                            <a class="badge badge-info btn-table-block dropdown-toggle" data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                                {{ slot.short_date_as_string }}
                                {{ slot.session_type_string }}
                            </a>
                        {% else %}
                            <a class="badge badge-warning btn-table-block dropdown-toggle" data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                                Not attending
                            </a>
                        {% endif %}
                        <div class="dropdown-menu">
                            {% set disabled = not rec.can_assign_feedback %}
                            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.assign_presentation_feedback', id=rec.id, url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                                Add new feedback
                            </a>
                        </div>
                    </div>
                    {% if slot is not none %}
                        {% set fns = namespace(flag=false) %}
                        {% for a in slot.assessors %}
                            {{ feedback_state_tag(rec, rec.presentation_feedback_state(a.id), a.user.name) }}
                            {% if slot.feedback_state(a.id) > slot.FEEDBACK_NOT_YET %}
                                {% set fns.flag = true %}
                            {% endif %}
                        {% endfor %}
                        {% if fns.flag and rec.number_presentation_feedback == 0 %}
                            <span class="badge badge-danger">Feedback required</span>
                        {% endif %}
                    {% endif %}
                {% else %}
                    <span class="badge badge-secondary">Awaiting scheduling</span>
                {% endif %}
            </div>
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="badge badge-secondary">None</span>
    {% endif %}
{% else %}
    <span class="badge badge-secondary">Not used</span>
{% endif %}
"""


_menu = \
"""
{% set pclass = sub.config.project_class %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a class="dropdown-item" href="{{ url_for('manage_users.edit_student', id=sub.student.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fa fa-pencil"></i> Edit student...
            </a>
        {% endif %}
        {% if sub.student.has_timeline %}
            <a class="dropdown-item" href="{{ url_for('student.timeline', student_id=sub.student.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fa fa-clock-o"></i> Show history... 
            </a>
        {% endif %}
        {% if allow_delete %}
            <a class="dropdown-item" href="{{ url_for('convenor.delete_submitter', sid=sub.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item disabled"><i class="fa fa-trash"></i> Delete is disabled</a>
        {% endif %}
        
        {% if sub.published and pclass.publish %}
            <a class="dropdown-item" href="{{ url_for('convenor.unpublish_assignment', id=sub.id) }}">
                <i class="fa fa-eye-slash"></i> Unpublish
            </a>
        {% else %}
            {% if pclass.publish %}
                <a class="dropdown-item" href="{{ url_for('convenor.publish_assignment', id=sub.id) }}">
                    <i class="fa fa-eye"></i> Publish to student
                </a>
            {% else %}
                <a class="dropdown-item disabled">
                    <i class="fa fa-eye-slash"></i> Cannot publish
                </a>
            {% endif %}
        {% endif %}

        {% set recs = sub.ordered_assignments.all() %}
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Manage documents</div>
        {% for r in recs %}
            {% set disabled = not pclass.publish %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('documents.submitter_documents', sid=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                <i class="fa fa-file-text"></i> Period #{{ r.submission_period }}
            </a>
        {% else %}
            <a class="dropdown-item disabled">No periods</a>
        {% endfor %}
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">View feedback</div>
        {% for r in recs %}
            {% set disabled = not pclass.publish %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.view_feedback', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                <i class="fa fa-comments-o"></i> Period #{{ r.submission_period }}
            </a>
        {% else %}
            <a class="dropdown-item disabled">No periods</a>
        {% endfor %}

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Manual reassignment</div>
        {% for r in recs %}
            {% set disabled = r.period.is_feedback_open %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                <i class="fa fa-wrench"></i> Period #{{ r.submission_period }}
            </a>
        {% else %}
            <a class="dropdown-item disabled">No periods</a>
        {% endfor %}
    </div>
</div>
"""


_name = \
"""
{% set pclass = sub.config.project_class %}
<div>
    {% if show_name %}
        <a href="mailto:{{ sub.student.user.email }}">{{ sub.student.user.name }}</a>
    {% endif %}
    {% if sub.student.intermitting %}
        <span class="badge badge-warning">TWD</span>
    {% endif %}
    {% if show_number %}
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a href="{{ url_for('manage_users.edit_student', id=sub.student.id, url=url_for('convenor.submitters', id=pclass.id)) }}" class="badge badge-secondary">
                #{{ sub.student.exam_number }}
            </a>
        {% else %}
            <span class="badge badge-secondary">#{{ sub.student.exam_number }}</span>
        {% endif %}
    {% endif %}
</div>
<div>
    {% if sub.published and pclass.publish %}
        <span class="badge badge-primary"><i class="fa fa-eye"></i> Published</span>
    {% else %}
        <span class="badge badge-warning"><i class="fa fa-eye-slash"></i> Unpublished</span>
    {% endif %}
</div>
"""


def submitters_data(students, config, show_name, show_number, sort_number):
    submittter_state = config.submitter_lifecycle
    allow_delete = submittter_state <= ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY

    data = [{'name': {
                'display': render_template_string(_name, sub=s, show_name=show_name, show_number=show_number),
                'sortvalue': s.student.exam_number if sort_number else s.student.user.last_name + s.student.user.first_name
             },
             'cohort': {
                 'display': render_template_string(_cohort, sub=s),
                 'value': s.student.cohort
             },
             'projects': render_template_string(_projects, sub=s, config=config),
             'markers': render_template_string(_markers, sub=s, config=config),
             'presentations': render_template_string(_presentations, sub=s, config=config),
             'menu': render_template_string(_menu, sub=s, allow_delete=allow_delete)} for s in students]

    return jsonify(data)
