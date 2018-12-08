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


_submitter_actions = \
"""
<div style="text-align: right;">
    <div class="pull-right">
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
        <a {% if not disabled %}href="{{ url_for('admin.assessment_submitter_availability', a_id=a.id, s_id=s.id, text='submitter management list', url=url_for('admin.assessment_manage_attendees', id=a.id)) }}"{% endif %} class="btn btn-sm btn-info btn-table-block {% if disabled %}disabled{% endif %}">
            Sessions
        </a>
    </div>
</div>
"""


_session_actions = \
"""
<div style="text-align: right;">
    <div class="pull-right">
        {% if sess.submitter_available(s.id) %}
            <a class="btn btn-success btn-sm"><i class="fa fa-check"></i> Available</a>
            <a href="{{ url_for('admin.submitter_unavailable', sess_id=sess.id, s_id=s.id) }}" class="btn btn-default btn-sm"><i class="fa fa-times"></i> Not available</a>
        {% else %}
            <a href="{{ url_for('admin.submitter_available', sess_id=sess.id, s_id=s.id) }}" class="btn btn-default btn-sm"><i class="fa fa-check"></i> Available</a>
            <a class="btn btn-danger btn-sm"><i class="fa fa-times"></i> Not available</a>
        {% endif %}
    </div>
</div>
"""


_global_name = \
"""
<a href="mailto:{{ s.submitter.owner.student.user.email }}">{{ s.submitter.owner.student.user.name }}</a>
{% set constraints = s.number_unavailable %}
{% if constraints > 0 %}
    &emsp;
    <span class="label label-warning">{{ constraints }} session constraints</span>
{% endif %}
"""


_project_name = \
"""
<a href="{{ dest_url }}">{{ p.name }}</a>
&emsp;
<a class="label label-info" href="{{ url_for('convenor.attach_assessors', id=p.parent_id, pclass_id=p.config.pclass_id, url=url, text=text) }}">
    {{ p.number_assessors }} assessors
</a>
"""


def submitter_session_availability_data(assessment, session, talks):
    data = [{'student': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=s.submitter.owner.student.user.email,
                                                                                 name=s.submitter.owner.student.user.name),
                         'sortstring': s.submitter.owner.student.user.last_name + s.submitter.owner.student.user.first_name},
             'pclass': render_template_string(_pclass, pclass=s.submitter.project.config.project_class),
             'project': render_template_string(_project_name, p=s.submitter.project,
                                               dest_url=url_for('faculty.live_project',
                                                                pid=s.submitter.project.id,
                                                                text='session attendee list',
                                                                url=url_for('admin.submitter_session_availability',
                                                                            id=session.id)),
                                               url=url_for('admin.submitter_session_availability', id=session.id),
                                               text='submitter availability for session'),
             'menu': render_template_string(_session_actions, s=s.submitter, a=assessment, sess=session)} for s in talks]

    return jsonify(data)


def presentation_attendees_data(assessment, talks):
    data = [{'student': {'display': render_template_string(_global_name, s=s, a=assessment),
                         'sortstring': s.submitter.owner.student.user.last_name + s.submitter.owner.student.user.first_name},
             'pclass': render_template_string(_pclass, pclass=s.submitter.project.config.project_class),
             'project': render_template_string(_project_name, p=s.submitter.project,
                                               dest_url=url_for('faculty.live_project', pid=s.submitter.project.id,
                                                                text='submitter management list',
                                                                url=url_for('admin.assessment_manage_attendees',
                                                                            id=assessment.id)),
                                               url=url_for('admin.assessment_manage_attendees', id=assessment.id),
                                               text='submitter management view'),
             'menu': render_template_string(_submitter_actions, s=s.submitter, a=assessment)} for s in talks]

    return jsonify(data)
