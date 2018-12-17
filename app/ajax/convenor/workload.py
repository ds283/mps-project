#
# Created by David Seery on 09/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_projects = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="label label-default">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="label label-info">{{ label }} to do</span>
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
        <div class="dropdown assignment-label">
            <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {{ r.owner.student.user.name }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li>
                    <a href="{{ url_for('convenor.view_feedback', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}">Show feedback</a>
                </li>
                
                {% set disabled = r.period.feedback_open or r.student_engaged %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}"{% endif %}>Manually reassign</a>
                </li>
            </ul>
        </div>
        {% if r.owner.published %}
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
        {% endif %}
        {{ feedback_state_tag(r, r.supervisor_feedback_state, 'Feedback') }}
        {{ feedback_state_tag(r, r.supervisor_response_state, 'Response') }}
    </div>
{% endmacro %}
{% if recs|length >= 1 %}
    {% for rec in recs %}
        {% if loop.index > 1 %}<p></p>{% endif %}
        {{ project_tag(rec, config.submissions > 1) }}
    {% endfor %}
{% else %}
    <span class="label label-info">None</span>
{% endif %}
"""


_marking = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="label label-default">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="label label-info">{{ label }} to do</span>
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
    {% set style = pclass.make_CSS_style() %}
    <div>
        <div class="dropdown assignment-label">
            <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {{ r.owner.student.user.name }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li>
                    <a href="{{ url_for('convenor.view_feedback', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}">Show feedback</a>
                </li>
                
                {% set disabled = r.period.feedback_open or r.student_engaged %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}"{% endif %}>Manually reassign</a>
                </li>
            </ul>
        </div>
        {{ feedback_state_tag(r, r.marker_feedback_state, 'Feedback') }}
    </div>
{% endmacro %}
{% if recs|length >= 1 %}
    {% for rec in recs %}
        {% if loop.index > 1 %}<p></p>{% endif %}
        {{ marker_tag(rec, config.submissions > 1) }}
    {% endfor %}
{% else %}
    <span class="label label-info">None</span>
{% endif %}
"""


_presentations = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_REQUIRED or state == obj.FEEDBACK_NOT_YET %}
        {# empty #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="label label-info">{{ label }} to do</span>
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
{% if slots|length >= 1 %}
    {% for slot in slots %}
        <div {% if loop.index < loop.length %}style="padding-bottom: 10px;"{% endif %}>
            <div class="dropdown assignment-label">
                <a class="label label-info btn-table-block dropdown-toggle" type="button" data-toggle="dropdown">
                    {{ slot.event_name }}
                    <span class="caret"></span>
                </a>
                <ul class="dropdown-menu">
                    {% for rec in slot.talks %}
                        <li>
                            {% set pclass = rec.owner.config.project_class %}
                            <a href="{{ url_for('convenor.view_feedback', id=rec.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}">
                                Show feedback for {{ rec.owner.student.user.name }}
                            </a>
                        </li>
                    {% endfor %}
                </ul>
            </div>
            <span class="label label-default">{{ slot.short_date_as_string }}</span>
            <span class="label label-default">{{ slot.session_type_string }}</span>
            <span class="label label-default">{{ slot.room_full_name }}</span>
            {% set state = slot.feedback_state(f.id) %}
            {{ feedback_state_tag(slot, state, 'Feedback') }}
            {% if state > slot.FEEDBACK_NOT_YET and state < slot.FEEDBACK_SUBMITTED %}
                {% set numbers = slot.feedback_number(f.id) %}
                {% if numbers is not none %}
                    {% set submitted, total = numbers %}
                    <span class="label label-warning">{{ submitted }}/{{ total }} submitted</span>
                {% endif %}
            {% endif %}
        </div>
    {% endfor %}
{% else %}
    <span class="label label-info">None</span>
{% endif %}
"""


_workload = \
"""
{% if config.uses_supervisor %}
    <span class="label label-info">Supv {{ CATS_sup }}</span>
{% endif %}
{% if config.uses_marker %}
    <span class="label label-info">Mark {{ CATS_mark }}</span>
{% endif %}
{% if config.uses_presentations %}
    <span class="label label-info">Pres {{ CATS_pres }}</span>
{% endif %}
<span class="label label-primary">Total {{ CATS_sup+CATS_mark+CATS_pres }}</span>
"""


def faculty_workload_data(faculty, config):
    data = []

    total = len(faculty)
    count = 0
    for u, d in faculty:
        count += 1

        CATS_sup, CATS_mark, CATS_pres = d.CATS_assignment(config.project_class)
        projects = d.supervisor_assignments(config.pclass_id).all()
        marking = d.marker_assignments(config.pclass_id).all()
        presentations = d.presentation_assignments(config.pclass_id).all()

        data.append({'name': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=u.email, name=u.name),
                              'sortvalue': u.last_name + u.first_name},
                     'projects': {'display': render_template_string(_projects, f=d, config=config, recs=projects),
                                  'sortvalue': len(projects)},
                     'marking': {'display': render_template_string(_marking, f=d, config=config, recs=marking),
                                 'sortvalue': len(marking)},
                     'presentations': {'display': render_template_string(_presentations, f=d, config=config, slots=presentations),
                                       'sortvalue': len(presentations)},
                     'workload': {'display': render_template_string(_workload, CATS_sup=CATS_sup, CATS_mark=CATS_mark,
                                                                    CATS_pres=CATS_pres, f=d, config=config),
                                  'sortvalue': CATS_sup+CATS_mark+CATS_pres}})

    return jsonify(data)
