#
# Created by David Seery on 2018-10-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_pclass = \
"""
{% set style = pclass.make_CSS_style() %}
<a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
"""


_actions = \
"""
{% if a.not_attending(s.id) %}
    <a href="{{ url_for('admin.assessment_attending', a_id=a.id, s_id=s.id) }}" class="btn btn-sm btn-default btn-table-block">
        Attending
    </a>
    <a class="btn btn-sm btn-danger btn-table-block">
        Not attending
    </a>
{% else %}
    <a class="btn btn-sm btn-success btn-table-block">
        Attending
    </a>
    <a href="{{ url_for('admin.assessment_not_attending', a_id=a.id, s_id=s.id) }}" class="btn btn-sm btn-default btn-table-block">
        Not attending
    </a>
{% endif %}
{% set disabled = a.not_attending(s.id) %}
<a {% if not disabled %}href="{{ url_for('admin.assessment_submitter_availability', a_id=a.id, s_id=s.id, text='assessment attendee list', url=url_for('admin.assessment_manage_attendees', id=a.id)) }}"{% endif %} class="btn btn-sm btn-info btn-table-block {% if disabled %}disabled{% endif %}">
    Sessions
</a>
"""


_name = \
"""
<a href="mailto:{{ s.owner.student.user.email }}">{{ s.owner.student.user.name }}</a>
{% set ns = namespace(constraints=false) %}
{% for session in a.sessions %}
    {% if not session.submitter_available(s.id) %}
        {% set ns.constraints = true %}
    {% endif %}
{% endfor %}
{% if ns.constraints %}
    <p></p>
    <span class="label label-info">Has constraints</span>
{% endif %}
"""


def presentation_attendees_data(talks, assessment):
    data = [{'student': {'display': render_template_string(_name, s=s, a=assessment),
                         'sortstring': s.owner.student.user.last_name + s.owner.student.user.first_name},
             'pclass': render_template_string(_pclass, pclass=s.project.config.project_class),
             'project': '<a href="{url}">{name}</a>'.format(name=s.project.name,
                                                            url=url_for('faculty.live_project', pid=s.project.id,
                                                                        text='assessment attendee list',
                                                                        url=url_for('admin.assessment_manage_attendees', id=assessment.id))),
             'menu': render_template_string(_actions, s=s, a=assessment)} for s in talks]

    return jsonify(data)
