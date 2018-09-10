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
        <span class="label label-default">{{ label }} not yet required</span>
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
        <div class="dropdown assignment-label">
            <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {{ r.owner.student.user.name }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li>
                    <a href="{{ url_for('convenor.view_feedback', id=r.id, text='workload view') }}">Show feedback</a>
                </li>
                
                {% set disabled = r.period.feedback_open %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='workload view') }}"{% endif %}>Manually reassign</a>
                </li>
            </ul>
        </div>
        {{ feedback_state_tag(r, r.supervisor_feedback_state, 'Feedback') }}
        {{ feedback_state_tag(r, r.supervisor_response_state, 'Response') }}
    </div>
{% endmacro %}
{% set recs = f.supervisor_assignments(config.pclass_id).all() %}
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
        <span class="label label-default">{{ label }} not yet required</span>
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
                    <a href="{{ url_for('convenor.view_feedback', id=r.id, text='workload view') }}">Show feedback</a>
                </li>
                
                {% set disabled = r.period.feedback_open %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('convenor.manual_assign', id=r.id, text='workload view') }}"{% endif %}>Manually reassign</a>
                </li>
            </ul>
        </div>
        {{ feedback_state_tag(r, r.marker_feedback_state, 'Feedback') }}
    </div>
{% endmacro %}
{% set recs = f.marker_assignments(config.pclass_id).all() %}
{% if recs|length >= 1 %}
    {% for rec in recs %}
        {% if loop.index > 1 %}<p></p>{% endif %}
        {{ marker_tag(rec, config.submissions > 1) }}
    {% endfor %}
{% else %}
    <span class="label label-info">None</span>
{% endif %}
"""


_workload = \
"""
<span class="label label-info">Supv {{ CATS_sup }}</span>
<span class="label label-info">Mark {{ CATS_mark }}</span>
<span class="label label-primary">Total {{ CATS_sup+CATS_mark }}</span>
"""


def faculty_workload_data(faculty, config):

    data = []

    for u, d in faculty:

        CATS_sup, CATS_mark = d.CATS_assignment(config.pclass_id)

        data.append({'name': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=u.email, name=u.name),
                              'sortvalue': u.last_name + u.first_name},
                     'projects': render_template_string(_projects, f=d, config=config),
                     'marking': render_template_string(_marking, f=d, config=config),
                     'workload': {'display': render_template_string(_workload, CATS_sup=CATS_sup, CATS_mark=CATS_mark,
                                                                    f=d),
                                  'sortvalue': CATS_sup+CATS_mark}})

    return jsonify(data)
