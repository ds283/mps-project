#
# Created by David Seery on 10/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

_affiliations = \
"""
{% for group in f.affiliations %}
    {{ group.make_label()|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_status = \
"""
{% if proj.is_second_marker(f) %}
    <span class="label label-success"><i class="fa fa-check"></i> Enrolled</span>
{% else %}
    <span class="label label-default"><i class-"fa fa-times"></i> Not enrolled</span>
{% endif %}
"""


def build_marker_data(faculty, proj):

    data = [{'name': f.user.name,
             'groups': render_template_string(_affiliations, f=f),
             'status': render_template_string(_status, f=f, proj=proj),
             'menu': ''} for f in faculty]

    return jsonify(data)
