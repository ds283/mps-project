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
        <span class="label assignment-label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %}>{% if show_period %}#{{ r.submission_period }}: {% endif %}
            {{ r.owner.student.user.name }}</span>
        {{ feedback_state_tag(r, r.supervisor_feedback_state, 'Feedback') }}
        {{ feedback_state_tag(r, r.supervisor_response_state, 'Response') }}
    </div>
{% endmacro %}
{% set recs = f.supervisor_assignments.all() %}
{% if recs|length == 1 %}
    {{ project_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for rec in recs %}
        {% if loop.index > 1 %}<p></p>{% endif %}
        {{ project_tag(rec, true) }}
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
        <span class="label assignment-label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %}>{% if show_period %}#{{ r.submission_period }}: {% endif %}
            {{ r.owner.student.user.name }}</span>
        {{ feedback_state_tag(r, r.supervisor_feedback_state, 'Feedback') }}
        {{ feedback_state_tag(r, r.supervisor_response_state, 'Response') }}
    </div>
{% endmacro %}
{% set recs = f.marker_assignments.all() %}
{% if recs|length == 1 %}
    {{ marker_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for rec in recs %}
        {% if loop.index > 1 %}<p></p>{% endif %}
        {{ marker_tag(rec, true) }}
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


def faculty_workload_data(faculty, pclass, config):

    data = []

    for u, d in faculty:

        CATS_sup, CATS_mark = d.CATS_assignment

        data.append({'name': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=u.email, name=u.name),
                              'sortvalue': u.last_name + u.first_name},
                     'projects': render_template_string(_projects, f=d),
                     'marking': render_template_string(_marking, f=d),
                     'workload': {'display': render_template_string(_workload, CATS_sup=CATS_sup, CATS_mark=CATS_mark,
                                                                    f=d),
                                  'sortvalue': CATS_sup+CATS_mark}})

    return jsonify(data)
