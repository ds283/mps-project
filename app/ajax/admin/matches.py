#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_status = \
"""
{% if m.success %}
    <span class="label label-success">Success</span>
{% else %}
    <span class="label label-default">Failed</span>
{% endif %}
"""


_owner = \
"""
<a href="mailto:{{ m.owner.email }}" class="btn btn-link">{{ m.owner.name }}</a>
"""


_timestamp = \
"""
{{ m.timesstamp.strftime("%a %d %b %Y %H:%M:%S") }}
"""


_info = \
"""
<span class="label label-primary">Supervisor {{ m.supervising_limit }} CATS</span>
<span class="label label-info">2nd mark {{ m.marking_limit }} CATS</span>
{% if m.ignore_per_faculty_limits %}
    <span class="label label-warning">Ignore per-faculty limits</span>
{% else %}
    <span class="label label-default">Apply per-faculty limits</span>
{% endif %}
<span class="label label-info">Marker multiplicity {{ m.max_marking_multiplicity }}</span>
<span class="label label-info">Memory {{ m.years_memory }} yr</span>
"""


_score = \
"""
{% if m.successful %}
    <span class="label label-success">{{ m.score }}</span>
{% else %}
    <span class="label label-default">Null</span>
{% endif %}
"""


def matches_data(matches):
    """
    Build AJAX JSON payload
    :param matches:
    :return:
    """

    data = [{'name': m.name,
             'status': render_template_string(_status, m=m),
             'owner': render_template_string(_owner, m=m),
             'score': {
                 'display': render_template_string(_score, m=m),
                 'value': m.score if m.successful else 0
             },
             'timestamp': render_template_string(_timestamp, m=m),
             'info': render_template_string(_info, m=m),
             'menu': ''} for m in matches]

    return jsonify(data)
