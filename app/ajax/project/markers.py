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
{% if proj.is_assessor(f) %}
    <span class="label label-success"><i class="fa fa-check"></i> Attached</span>
{% else %}
    <span class="label label-default"><i class-"fa fa-times"></i> Not attached</span>
{% endif %}
"""

_enrollments = \
"""
{% set ns = namespace(count=0) %}
{% for e in f.enrollments %}
    {% if e.pclass.uses_marker or e.pclass.uses_presentations %}
        {% set ns.count = ns.count + 1 %}
        {% if e.marker_state == e.MARKER_ENROLLED or e.presentations_state == e.PRESENTATIONS_ENROLLED %}
            {{ e.pclass.make_label('<i class="fa fa-check"></i> ' + e.pclass.abbreviation)|safe }}
        {% elif e.marker_state == e.MARKER_SABBATICAL and e.presentations_state == e.PRESENTATIONS_SABBATICAL %}
            <{% if not disabled %}a{% else %}span{% endif%} class="label label-default" {% if not disabled %}href="{{ url_for('admin.edit_enrollment', id=e.id, url=url) }}"{% endif %}><i class="fa fa-times"></i> {{ e.pclass.abbreviation }} (sabbat)<{% if not disabled %}/a{% else %}/span{% endif %}>
        {% elif (e.marker_state == e.MARKER_EXEMPT and e.presentations_state == e.PRESENTATIONS_SABBATICAL) or
                (e.marker_state == e.MARKER_SABBATICAL and e.presentations_state == e.PRESENTATIONS_EXEMPT) or
                (e.marker_state == e.MARKER_EXEMPT and e.presentations_state == e.PRESENTATIONS_EXEMPT)
        %}
            <{% if not disabled %}a{% else %}span{% endif%} class="label label-default" {% if not disabled %}href="{{ url_for('admin.edit_enrollment', id=e.id, url=url) }}"{% endif %}><i class="fa fa-times"></i> {{ e.pclass.abbreviation }} (exempt)<{% if not disabled %}/a{% else %}/span{% endif %}>
        {% else %}
            <{% if not disabled %}a{% else %}span{% endif%} class="label label-danger" {% if not disabled %}href="{{ url_for('admin.edit_enrollment', id=e.id, url=url) }}"{% endif %}><i class="fa fa-exclamation-triangle"></i> {{ e.pclass.abbreviation }} (unknown)<{% if not disabled %}/a{% else %}/span{% endif %}>
        {% endif %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default">None</span>
{% endif %}
"""


_attached = \
"""
<span class="label label-default">{{ f.number_assessor }}</span>
"""


def build_marker_data(faculty, proj, menu, pclass_id=None, url=None, disable_enrollment_links=False):

    data = [{'name': {
                'display': f.user.name,
                'sortstring': f.user.last_name + f.user.first_name
             },
             'attached': render_template_string(_attached, f=f),
             'groups': render_template_string(_affiliations, f=f),
             'status': render_template_string(_status, f=f, proj=proj),
             'enrollments': render_template_string(_enrollments, f=f, url=url, disabled=disable_enrollment_links),
             'menu': render_template_string(menu, f=f, proj=proj, pclass_id=pclass_id)} for f in faculty]

    return jsonify(data)
