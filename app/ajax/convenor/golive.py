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

def golive_data(config):
    data = [{'name': {'display': f.student.user.name,
                      'sortstring': f.user.last_name + f.user.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=f.user.email),
             'projects': render_template_string(_projects, f=f, pclass=config.project_class)} for f in config.golive_required]

    return jsonify(data)
