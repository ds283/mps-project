#
# Created by David Seery on 27/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_pclasses = \
"""
{% set ns = namespace(count=0) %}
{% if d.default is not none %}
    <span class="badge badge-success">Default</span>
    {% set ns.count = ns.count + 1 %}
{% endif %}
{% for pclass in d.project_classes %}
    {% if pclass.active %}
        {% set style = pclass.make_CSS_style() %}
        <a class="badge badge-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
        {% set ns.count = ns.count + 1 %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="badge badge-secondary">None</span>
{% endif %}
{% if d.has_modules %}
    <div>
        <span class="badge badge-primary"><i class="fas fa-exclamation-circle"></i> Has recommended modules</span>
    </div>
{% endif %}
"""


# language=jinja2
_team = \
"""
{% for sup in d.team %}
    {{ sup.make_label(sup.name)|safe }}
{% else %}
    <span class="badge badge-danger">No staff selected</span>
{% endfor %}
"""


def _get_pclass(desc):
    if desc is None:
        return None

    first = desc.project_classes.first()

    if first is None:
        return None

    return first.id


def descriptions_data(descs, label, menu, pclass_id=None, create=None, config=None, desc_validator=None):
    data = [{'label': render_template_string(label, d=d, desc_pclass_id=_get_pclass(d),
                                             pclass_id=pclass_id, create=create, config=config,
                                             desc_validator=desc_validator),
             'pclasses': render_template_string(_pclasses, d=d),
             'team': render_template_string(_team, d=d),
             'capacity': d.capacity,
             'menu': render_template_string(menu, d=d, pclass_id=pclass_id, create=create,
                                            desc_validator=desc_validator)} for d in descs]

    return jsonify(data)
