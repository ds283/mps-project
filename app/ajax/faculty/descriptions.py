#
# Created by David Seery on 27/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_label = \
"""
<a href="{{ url_for('faculty.edit_description', did=d.id) }}">{{ d.label }}</a>
"""


_pclasses = \
"""
{% set ns = namespace(count=0) %}
{% if d.default is not none %}
    <span class="label label-success">Default</span>
    {% set ns.count = ns.count + 1 %}
{% endif %}
{% for pclass in d.project_classes %}
    {% if pclass.active %}
        {% set style = pclass.make_CSS_style() %}
        <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
        {% set ns.count = ns.count + 1 %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default">None</span>
{% endif %}
"""


_team = \
"""
{% for sup in d.team %}
    {{ sup.make_label(sup.name)|safe }}
{% else %}
    <span class="label label-danger">No staff selected</span>
{% endfor %}
"""


def descriptions_data(descs, menu):

    data = [{'label': render_template_string(_label, d=d),
             'pclasses': render_template_string(_pclasses, d=d),
             'team': render_template_string(_team, d=d),
             'capacity': d.capacity,
             'menu': render_template_string(menu, d=d)} for d in descs]

    return jsonify(data)
