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
        {# <span class="label label-default">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="label label-default">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="label label-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="label label-warning">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="label label-danger">{{ label }} late</span>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <span class="label label-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro project_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div>
        {% if r.project is not none %}
            <div class="dropdown assignment-label">
                <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle"
                        {% if style %}style="{{ style }}"{% endif %}
                        type="button" data-toggle="dropdown">{% if show_period %}#{{ r.submission_period }}: {% endif %}
                    {% if r.project.name|length < 35 %}
                        {{ r.project.name }}
                    {% else %}
                        {{ r.project.name[0:35] }}...
                    {% endif %}
                    ({{ r.supervisor.user.last_name }})
                <span class="caret"></span></a>
                <ul class="dropdown-menu">
                    {% set disabled = r.period.feedback_open or r.student_engaged %}
                    {% if disabled %}
                        <li class="disabled">
                            <a>Can't reassign: Feedback open or student engaged</a>
                        </li>
                    {% else %}
                        <li>
                            <a href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Manually reassign</a>
                        </li>
                        <li>
                            <a href="{{ url_for('convenor.deassign_project', id=r.id) }}">Remove assignment</a>
                        </li>
                    {% endif %}
                </ul>
            </div>
            {% if sub.published %}
                <div class="dropdown assignment-label">
                    <a class="label {% if r.student_engaged %}label-success{% else %}label-warning{% endif %} btn-table-block dropdown-toggle"
                            type="button" data-toggle="dropdown">{% if r.student_engaged %}<i class="fa fa-check"></i> Started{% else %}<i class="fa fa-times"></i> Waiting{% endif %}
                    <span class="caret"></span></a>
                    <ul class="dropdown-menu">
                        {% if r.submission_period > r.owner.config.submission_period %}
                            <li class="disabled">
                                <a>Submission period not yet open</a>
                            </li>
                        {% elif not r.student_engaged %}
                            <li>
                                <a href="{{ url_for('convenor.mark_started', id=r.id) }}">
                                    <i class="fa fa-check"></i> Mark as started
                                </a>
                            </li>
                        {% else %}
                            {% set disabled = (r.owner.config.submitter_lifecycle >= r.owner.config.SUBMITTER_LIFECYCLE_READY_ROLLOVER) %}
                            <li {% if disabled %}class="disabled"{% endif %}>
                                <a {% if not disabled %}href="{{ url_for('convenor.mark_waiting', id=r.id) }}"{% endif %}>
                                    <i class="fa fa-times"></i> Mark as waiting
                                </a>
                            </li>
                        {% endif %}
                    </ul>
                </div>
                {% if r.report is not none %}
                    <span class="label label-success"><i class="fa fa-check"></i> Report</span>
                {% endif %}
                {% if r.number_attachments > 0 %}
                    <span class="label label-success"><i class="fa fa-check"></i> Attachments</span>
                {% endif %}
            {% endif %}
        {% else %}
            <a class="label label-danger" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">No project allocated</a>
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
        <span class="label label-danger">None</span>
    {% endif %}
{% else %}
    <span class="label label-default">Not used</span>
{% endif %}
"""


_markers = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="label label-default">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="label label-default">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="label label-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="label label-warning">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="label label-danger">{{ label }} late</span>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <span class="label label-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro marker_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    <div>
        {% if r.marker is not none %}
            <div class="dropdown assignment-label">
                <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
                    {% if show_period %}#{{ r.submission_period }}: {% endif %}
                    {{ r.marker.user.name }}
                    <span class="caret"></span>
                </a>
                <ul class="dropdown-menu">
                    {% set disabled = r.period.feedback_open or r.student_engaged %}
                    {% if disabled %}
                        <li class="disabled">
                            <a>Can't reassign: Feedback open or student engaged</a>
                        </li>
                    {% else %}
                        <li>
                            <a href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Manually reassign</a>
                        </li>
                        <li>
                            <a href="{{ url_for('convenor.deassign_marker', id=r.id) }}">Remove assignment</a>
                        </li>
                    {% endif %}
                </ul>
            </div>
        {% else %}
            <a class="label label-danger" href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
                {% if r.project is none %}
                    No project allocated
                {% else %}
                    No marker allocated
                {% endif %}
            </a>
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
        <span class="label label-danger">None</span>
    {% endif %}
{% else %}
    <span class="label label-default">Not used</span>
{% endif %}
"""


_presentations = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET or state == obj.FEEDBACK_NOT_REQUIRED %}
        {# empty #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="label label-default">{{ label }}: to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="label label-success">{{ label }}: submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="label label-warning">{{ label }}: in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="label label-danger">{{ label }}: late</span>
    {% else %}
        <span class="label label-danger">{{ label }}: error &ndash; unknown state</span>
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
                <span class="label label-primary">Pd. {{ rec.submission_period }}</span>
                {% if rec.period.has_deployed_schedule %}
                    {% set slot = rec.schedule_slot %}
                    <div class="dropdown assignment-label">
                        {% if slot is not none %}
                            <a class="label label-info btn-table-block dropdown-toggle" type="button" data-toggle="dropdown">
                                {{ slot.short_date_as_string }}
                                {{ slot.session_type_string }}
                                <span class="caret"></span>
                            </a>
                        {% else %}
                            <a class="label label-warning btn-table-block dropdown-toggle" type="button" data-toggle="dropdown">
                                Not attending
                                <span class="caret"></span>
                            </a>
                        {% endif %}
                        <ul class="dropdown-menu">
                            {% set disabled = not rec.can_assign_feedback %}
                            <li {% if disabled %}class="disabled"{% endif %}>
                                <a {% if not disabled %}href="{{ url_for('convenor.assign_presentation_feedback', id=rec.id, url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                                    Add new feedback
                                </a>
                            </li>
                        </ul>
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
                            <span class="label label-danger">Feedback required</span>
                        {% endif %}
                    {% endif %}
                {% else %}
                    <span class="label label-default">Awaiting scheduling</span>
                {% endif %}
            </div>
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="label label-default">None</span>
    {% endif %}
{% else %}
    <span class="label label-default">Not used</span>
{% endif %}
"""


_menu = \
"""
{% set pclass = sub.config.project_class %}
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <li>
                <a href="{{ url_for('manage_users.edit_student', id=sub.student.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                    <i class="fa fa-pencil"></i> Edit student...
                </a>
            </li>
        {% endif %}
        {% if sub.student.has_timeline %}
            <li>
                <a href="{{ url_for('student.timeline', student_id=sub.student.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
                    <i class="fa fa-clock-o"></i> Show history... 
                </a>
            </li>
        {% endif %}
        {% if allow_delete %}
            <li>
                <a href="{{ url_for('convenor.delete_submitter', sid=sub.id) }}">
                    <i class="fa fa-trash"></i> Delete
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a><i class="fa fa-trash"></i> Delete disabled</a>
            </li>
        {% endif %}
        
        {% if sub.published and pclass.publish %}
            <li>
                <a href="{{ url_for('convenor.unpublish_assignment', id=sub.id) }}">
                    <i class="fa fa-eye-slash"></i> Unpublish
                </a>
            </li>
        {% else %}
            {% if pclass.publish %}
                <li>
                    <a href="{{ url_for('convenor.publish_assignment', id=sub.id) }}">
                        <i class="fa fa-eye"></i> Publish to student
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a>
                        <i class="fa fa-eye-slash"></i> Cannot publish
                    </a>
                </li>
            {% endif %}
        {% endif %}

        {% set recs = sub.ordered_assignments.all() %}
        
        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Manage documents</li>
        {% for r in recs %}
            {% set disabled = not pclass.publish or r.period.closed %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('convenor.submitter_documents', sid=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                    <i class="fa fa-file-text"></i> Period #{{ r.submission_period }}
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>No periods</a>
            </li>
        {% endfor %}
        
        <li role="separator" class="divider"></li>
        <li class="dropdown-header">View feedback</li>
        {% for r in recs %}
            {% set disabled = not pclass.publish %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('convenor.view_feedback', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                    <i class="fa fa-comments-o"></i> Period #{{ r.submission_period }}
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>No periods</a>
            </li>
        {% endfor %}

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Manual reassignment</li>
        {% for r in recs %}
            {% set disabled = r.period.feedback_open %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                    <i class="fa fa-wrench"></i> Period #{{ r.submission_period }}
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>No periods</a>
            </li>
        {% endfor %}
    </ul>
</div>
"""


_name = \
"""
{% set pclass = sub.config.project_class %}
<div>
    {% if show_name %}
        <a href="mailto:{{ sub.student.user.email }}">{{ sub.student.user.name }}</a>
    {% endif %}
    {% if show_number %}
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a href="{{ url_for('manage_users.edit_student', id=sub.student.id, url=url_for('convenor.submitters', id=pclass.id)) }}" class="label label-default">
                #{{ sub.student.exam_number }}
            </a>
        {% else %}
            <span class="label label-default">#{{ sub.student.exam_number }}</span>
        {% endif %}
    {% endif %}
</div>
<div>
    {% if sub.published and pclass.publish %}
        <span class="label label-primary"><i class="fa fa-eye"></i> Published</span>
    {% else %}
        <span class="label label-warning"><i class="fa fa-eye-slash"></i> Unpublished</span>
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
