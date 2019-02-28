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
{% if d.has_modules %}
    <div>
        <span class="label label-primary"><i class="fa fa-exclamation-circle"></i> Has recommended modules</span>
    </div>
{% endif %}
{% set state = d.workflow_state %}
<div>
    {% if state == d.WORKFLOW_APPROVAL_VALIDATED %}
        <span class="label label-success"><i class="fa fa-check"></i> Approved</span>
    {% elif state == d.WORKFLOW_APPROVAL_QUEUED %}
        <span class="label label-warning">Approval: Queued</span>
    {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
        <span class="label label-danger">Approval: Rejected</span>
    {% else %}
        <span class="label label-danger">Unknown approval state</span>
    {% endif %}
    {% if d.validated_by %}
        <span class="label label-default">Approved by {{ d.validated_by.name }}</span>
        {% if d.validated_timestamp %}
            <span class="label label-default">{{ d.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
    {% endif %}
</div>
"""


_team = \
"""
{% for sup in d.team %}
    {{ sup.make_label(sup.name)|safe }}
{% else %}
    <span class="label label-danger">No staff selected</span>
{% endfor %}
"""


def descriptions_data(descs, label, menu, pclass_id=None, create=None):

    data = [{'label': render_template_string(label, d=d, pclass_id=pclass_id),
             'pclasses': render_template_string(_pclasses, d=d),
             'team': render_template_string(_team, d=d),
             'capacity': d.capacity,
             'menu': render_template_string(menu, d=d, pclass_id=pclass_id, create=create)} for d in descs]

    return jsonify(data)
