#
# Created by David Seery on 2018-10-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_assessors = \
"""
{% for assessor in s.assessors %}
    <div>
        <span class="label label-default">{{ assessor.user.name }}</span>
    </div>
{% endfor %}
"""


_talks = \
"""
{% for talk in s.talks %}
    <div>
        {% set style = talk.pclass.make_CSS_style() %}
        <span class="label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %}>{{ talk.owner.student.user.name }} &ndash; {{ talk.project.name }}</span>
    </div>
{% endfor %}
"""


def schedule_view_sessions(slots, record):
    data = [{'session': {'display': s.session.label,
                         'sortvalue': s.session.date.isoformat()},
             'room': s.room.label,
             'assessors': render_template_string(_assessors, s=s),
             'talks': render_template_string(_talks, s=s)} for s in slots]

    return jsonify(data)
