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
    <a href="{{ url_for('admin.assessment_attending', a_id=a.id, s_id=s.id) }}" class="btn btn-sm btn-default">
        Attending
    </a>
    <a class="btn btn-sm btn-danger">
        Not attending
    </a>
{% else %}
    <a class="btn btn-sm btn-success">
        Attending
    </a>
    <a href="{{ url_for('admin.assessment_not_attending', a_id=a.id, s_id=s.id) }}" class="btn btn-sm btn-default">
        Not attending
    </a>
{% endif %}
"""


def presentation_attendees_data(talks, assessment):
    data = [{'student': {'display': '<a href="mailto:{email}">{name}</a>'.format(name=s.owner.student.user.name, email=s.owner.student.user.email),
                         'sortstring': s.owner.student.user.last_name + s.owner.student.user.first_name},
             'pclass': render_template_string(_pclass, pclass=s.project.config.project_class),
             'project': '<a href="{url}">{name}</a>'.format(name=s.project.name,
                                                            url=url_for('faculty.live_project', pid=s.project.id,
                                                                        text='assessment attendee list',
                                                                        url=url_for('admin.assessment_manage_attendees', id=assessment.id))),
             'menu': render_template_string(_actions, s=s, a=assessment)} for s in talks]

    return jsonify(data)
