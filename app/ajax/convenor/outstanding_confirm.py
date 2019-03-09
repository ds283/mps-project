#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_projects = \
"""
{{ f.projects_offered_label(pclass)|safe }}
{{ f.projects_unofferable_label|safe }}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('convenor.force_confirm', id=config.id, uid=f.id) }}">
                <i class="fa fa-check"></i> Force confirm
            </a>
        </li>
        <li>
            <a href="{{ url_for('convenor.confirmation_reminder_individual', fac_id=f.id, config_id=config.id) }}">
                <i class="fa fa-envelope-o"></i> Send reminder
            </a>
        </li>
    </ul>
</div>
"""

def outstanding_confirm_data(config):

    data = [{'name': {'display': f.user.name,
                      'sortstring': f.user.last_name + f.user.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=f.user.email),
             'projects': render_template_string(_projects, f=f, pclass=config.project_class),
             'menu': render_template_string(_menu, config=config, f=f)} for f in config.faculty_waiting_confirmation]

    return jsonify(data)
