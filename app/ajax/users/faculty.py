#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

from .shared import menu


_affiliation = \
"""
{% for group in f.affiliations %}
    {{ group.make_label(group.name)|safe }}
{% endfor %}
"""


_enrolled = \
"""
{% for record in f.enrollments %}
    {% set pclass = record.pclass %}
    {{ pclass.make_label()|safe }}
{% endfor %}
"""


_settings = \
"""
{% if f.sign_off_students %}
    <span class="label label-info">Require meetings</span>
{% endif %}
<span class="label label-primary">Default capacity {{ f.project_capacity }}</span>
{% if f.enforce_capacity %}
    <span class="label label-info">Enforce capacity</span>
{% endif %}
{% if f.show_popularity %}
    <span class="label label-info">Show popularity</span>
{% endif %}
<p>
{% if f.CATS_supervision %}
    <span class="label label-warning">CATS supv {{ f.CATS_supervision }}</span>
{% else %}
    <span class="label label-default">Default supervisory CATS</span>
{% endif %}
{% if f.CATS_markign %}
    <span class="label label-warning">CATS mark {{ f.CATS_marking }}</span>
{% else %}
    <span class="label label-default">Default marking CATS</span>
{% endif %}
"""


def build_faculty_data(faculty):

    data = [{'name': {
                'display': u.name,
                'sortstring': u.last_name + u.first_name},
             'active': u.active_label,
             'office': f.office,
             'settings': render_template_string(_settings, f=f),
             'affiliation': render_template_string(_affiliation, f=f),
             'enrolled': render_template_string(_enrolled, f=f),
             'menu': render_template_string(menu, user=u, pane='faculty')} for f, u in faculty]

    return jsonify(data)
