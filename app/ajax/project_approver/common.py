#
# Created by David Seery on 2019-02-27.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

title = \
"""
{% set project = r.parent %}
{% set pclass = r.project_classes.first() %}
{% set disabled = (pclass is none) %}
<a {% if not disabled %}href="{{ url_for('faculty.project_preview', id=r.parent.id, pclass=pclass.id, show_selector=0, url=url, text=text) }}"{% endif %}>
    {%- if project -%}{{ project.name }}{%- else -%}<unnamed project>{%- endif -%}/{%- if r.label -%}{{ r.label }}{%- else -%}<unnamed description>{%- endif -%}
</a>
{% if not project.is_offerable %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    <div>
        This project has validation errors that will prevent it from being published.
    </div>
{% endif %}
<div>
    {{ 'REPNEWCOMMENTS'|safe }}
</div>
"""


owner = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
"""


pclasses = \
"""
{% set ns = namespace(count=0) %}
{% if r.default is not none %}
    <span class="label label-success">Default</span>
    {% set ns.count = ns.count + 1 %}
{% endif %}
{% for pclass in r.project_classes %}
    {% if pclass.active %}
        {% set style = pclass.make_CSS_style() %}
        <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
        {% set ns.count = ns.count + 1 %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default">None</span>
{% endif %}
{% if r.has_modules %}
    <p></p>
    <span class="label label-primary"><i class="fa fa-exclamation-circle"></i> Has recommended modules</span>
{% endif %}
"""
