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


_cohort = \
"""
{{ sub.student.programme.short_label|safe }}
{{ sub.student.cohort_label|safe }}
{{ sub.academic_year_label|safe }}
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
                    {{ r.supervisor.user.name }} (No. {{ r.project.number }})
                <span class="caret"></span></a>
                <ul class="dropdown-menu">
                    <li>
                        <a href="{{ url_for('convenor.view_feedback', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Show feedback</a>
                    </li>
                    
                    {% set disabled = r.period.feedback_open or r.student_engaged %}
                    <li {% if disabled %}class="disabled"{% endif %}>
                        <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>Manually reassign</a>
                    </li>
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
                            <li class="disabled">
                                <a><i class="fa fa-check"></i> Already started</a>
                            </li>
                        {% endif %}
                    </ul>
                </div>
            {% endif %}
        {% else %}
            <span class="label label-danger">No project allocation</span>
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
    {% else %}
        <span class="label label-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro marker_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    <div>
        {% if r.project is not none %}
            <div class="dropdown assignment-label">
                <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
                    {% if show_period %}#{{ r.submission_period }}: {% endif %}
                    {{ r.marker.user.name }}
                    <span class="caret"></span>
                </a>
                <ul class="dropdown-menu">
                    <li>
                        <a href="{{ url_for('convenor.view_feedback', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Show feedback</a>
                    </li>
                    
                    {% set disabled = r.period.feedback_open or r.student_engaged %}
                    <li {% if disabled %}class="disabled"{% endif %}>
                        <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>Manually reassign</a>
                    </li>
                </ul>
            </div>
        {% else %}
            <span class="label label-danger">No project allocation</span>
        {% endif %}
        {{ feedback_state_tag(r, r.marker_feedback_state, 'Feedback') }}
    </div>
{% endmacro %}
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
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% if sub.published %}
            <li>
                <a href="{{ url_for('convenor.unpublish_assignment', id=sub.id) }}">
                    <i class="fa fa-eye-slash"></i> Unpublish
                </a>
            </li>
        {% else %}
            <li>
                <a href="{{ url_for('convenor.publish_assignment', id=sub.id) }}">
                    <i class="fa fa-eye"></i> Publish to student
                </a>
            </li>
        {% endif %}

        {% set recs = sub.ordered_assignments.all() %}
        {% set pclass = sub.config.project_class %}

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Manual reassignment</li>
        {% for r in recs %}
            {% set disabled = r.period.feedback_open %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                    Period #{{ r.submission_period }}
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
            {% set disabled = not r.feedback_submitted %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('convenor.view_feedback', id=r.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
                    Period #{{ r.submission_period }}
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


_presentations = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="label label-default">{{ label }}: not yet required</span> #}
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
{% set recs = sub.ordered_assignments.all() %}
{% set ns = namespace(count=0) %}
{% for rec in recs %}
    {% if rec.period.has_presentation %}
        {% set pclass = rec.owner.config.project_class %}
        {% set ns.count = ns.count + 1 %}
        {% set slot = rec.schedule_slot %}
        <div>
            <span class="label label-primary">#{{ rec.submission_period}}</span>
            {% if slot is not none %}
                <div class="dropdown assignment-label">
                    <a class="label label-info btn-table-block dropdown-toggle" type="button" data-toggle="dropdown">
                        {{ slot.event_name }}
                        <span class="caret"></span>
                    </a>
                    <ul class="dropdown-menu">
                        <li>
                            <a href="{{ url_for('convenor.view_feedback', id=rec.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Show feedback</a>
                        </li>
                    </ul>
                </div>
                <span class="label label-default">{{ slot.short_date_as_string }}</span>
                <span class="label label-default">{{ slot.session_type_string }}</span>
                <span class="label label-default">{{ slot.room_full_name }}</span>
                {% for a in slot.assessors %}
                    {{ feedback_state_tag(rec, rec.presentation_feedback_state(a.id), a.user.name) }}
                {% endfor %}
            {% else %}
                <div class="dropdown assignment-label">
                    <a class="label label-warning btn-table-block dropdown-toggle" type="button" data-toggle="dropdown">
                        Not attending
                        <span class="caret"></span>
                    </a>
                    <ul class="dropdown-menu">
                        {% set ns = namespace(count=0) %}
                        {% for feedback in rec.presentation_feedback %}
                            {% set ns.count = ns.count + 1 %}
                            <li>
                                <a href="{{ url_for('convenor.edit_presentation_feedback', id=feedback.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                                    Edit feedback from {{ feedback.assessor.user.name }}
                                </a>
                            <li>
                        {% endfor %}
                        {% if ns.count > 0 %}
                            <li role="separator" class="divider">
                        {% endif %}
                        {% set ns.count = 0 %}
                        {% for feedback in rec.presentation_feedback %}
                            {% set ns.count = ns.count + 1 %}
                            <li>
                                <a href="{{ url_for('convenor.delete_presentation_feedback', id=feedback.id) }}">
                                    Delete feedback from {{ feedback.assessor.user.name }}
                                </a>
                            <li>
                        {% endfor %}
                        {% if ns.count > 0 %}
                            <li role="separator" class="divider">
                        {% endif %}
                        <li>
                            <a href="{{ url_for('convenor.assign_presentation_feedback', id=rec.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                                Add new feedback
                            </a>
                        </li>
                        {% if ns.count > 0 %}
                            <li>
                                <a href="{{ url_for('convenor.view_feedback', id=rec.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">Show feedback</a>
                            </li>
                        {% endif %}
                    </ul>
                </div>
                {% if rec.number_presentation_feedback == 0 %}
                    <span class="label label-danger">Feedback required</span>
                {% endif %}
            {% endif %}
        </div>
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default">None</span>
{% endif %}
"""


_name = \
"""
<a href="mailto:{{ sub.student.user.email }}">{{ sub.student.user.name }}</a>
<div>
{% if sub.published %}
    <span class="label label-primary"><i class="fa fa-eye"></i> Published</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-eye-slash"></i> Unpublished</span>
{% endif %}
</div>
"""


def submitters_data(students, config):

    data = [{'name': {
                'display': render_template_string(_name, sub=s),
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'cohort': render_template_string(_cohort, sub=s),
             'projects': render_template_string(_projects, sub=s),
             'markers': render_template_string(_markers, sub=s),
             'presentations': render_template_string(_presentations, sub=s),
             'menu': render_template_string(_menu, sub=s)} for s in students]

    return jsonify(data)
