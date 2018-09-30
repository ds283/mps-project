#
# Created by David Seery on 2018-09-28.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_name = \
"""
<a href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">{{ a.name }}</a>
"""


_periods = \
"""
{% for period in a.submission_periods %}
    {{ period.label|safe }}
{% endfor %}
"""


_sessions = \
"""
{% for session in a.ordered_sessions %}
    {{ session.label|safe }}
{% endfor %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li class="dropdown-header">Edit assessment</li>
        <li>
            <a href="{{ url_for('admin.edit_assessment', id=a.id) }}">
                <i class="fa fa-cogs"></i> Settings
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">
                <i class="fa fa-calendar"></i> Sessions
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.delete_assessment', id=a.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</div>
"""


def presentation_assessments_data(assessments):

    data=[{'name': render_template_string(_name, a=a),
           'periods': render_template_string(_periods, a=a),
           'sessions': render_template_string(_sessions, a=a),
           'menu': render_template_string(_menu, a=a)} for a in assessments]

    return jsonify(data)
