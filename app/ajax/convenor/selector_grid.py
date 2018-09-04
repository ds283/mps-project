#
# Created by David Seery on 31/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_cohort = \
"""
{{ sel.student.cohort_label|safe }}
{{ sel.academic_year_label|safe }}
"""

_selections = \
"""
{% if sel.has_submitted %}
    {% for item in sel.ordered_selection %}
        {% if item.rank <= sel.number_choices %}
            {% set project = item.liveproject %}
            <div class="dropdown">
                {% set style = project.group.make_CSS_style() %}
                <a class="label label-info dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">#{{ item.rank }}
                    {{ item.format_project|safe }} (No. {{ project.number }}) &ndash; {{ project.owner.user.name }}
                <span class="caret"></span></a>
                <ul class="dropdown-menu">
                    {% set menu_items = item.menu_order %}
                    {% for mi in menu_items %}
                        {% if mi is string %}
                            <li role="separator" class="divider"></li>
                            <li class="dropdown-header">{{ mi }}</li>
                        {% elif mi is number %}
                            {% set disabled = (mi == item.hint) %}
                            <li {% if disabled %}class="disabled"{% endif %}>
                                <a {% if not disabled %}href="{{ url_for('convenor.set_hint', id=item.id, hint=mi) }}"{% endif %}>
                                    {{ item.menu_item(mi)|safe }}
                                </a>
                            </li>
                        {% endif %}
                    {% endfor %}
                </ul>
                {% if item.converted_from_bookmark %}
                    <span class="label label-warning">Bookmark</span>
                {% endif %}
            </div>
        {% endif %}
    {% endfor %}
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""


def selector_grid_data(students, config):

    data = [{'name': {
                'display': s.student.user.name,
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'programme': s.student.programme.label,
             'cohort': {
                 'display': render_template_string(_cohort, sel=s),
                 'value': s.student.cohort
             },
             'selections': render_template_string(_selections, sel=s, config=config)} for s in students]

    return jsonify(data)
