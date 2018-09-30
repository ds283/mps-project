#
# Created by David Seery on 2018-09-30.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li class="dropdown-header">Edit session</li>
        <li>
            <a href="{{ url_for('admin.edit_session', id=s.id) }}">
                <i class="fa fa-pencil"></i> Settings
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.delete_session', id=s.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</div>
"""


def assessment_sessions_data(sessions):

    data = [{'date': s.date_as_string,
             'session': s.session_type_label,
             'rooms': '',
             'availability': '',
             'menu': render_template_string(_menu, s=s)} for s in sessions]

    return jsonify(data)
