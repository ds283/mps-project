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
{{ sel.academic_year_label(show_details=True)|safe }}
"""

_selections = \
"""
{% if sel.has_submitted %}
    {% if sel.has_accepted_offer %}
        {% set offer = sel.accepted_offer %}
        {% set project = offer.liveproject %}
        {% if project %}
            <span class="badge badge-success"><i class="fa fa-check"></i> {{ project.name }} ({{ project.owner.user.last_name }})</span>
        {% else %}
            <span class="badge badge-danger">MISSING ACCEPTED PROJECT</span>
        {% endif %}
    {% else %}
        {% for item in sel.ordered_selections %}
            {% set project = item.liveproject %}
            <div class="dropdown">
                {% set style = project.group.make_CSS_style() %}
                <a class="badge badge-info dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">#{{ item.rank }}
                    {{ item.format_project()|safe }} (No. {{ project.number }}) &ndash; {{ project.owner.user.name }}
                <span class="caret"></span></a>
                <div class="dropdown-menu">
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
                    <span class="badge badge-warning"><i class="fa fa-exclamation-triangle"></i> Bookmark</span>
                {% endif %}
                {% if item.hint != item.SELECTION_HINT_NEUTRAL %}
                    <span class="badge badge-warning"><i class="fa fa-exclamation-triangle"></i> Hint</span>
                {% endif %}
            </div>
        {% endfor %}
    {% endif %}
{% else %}
    <div class="row vertical-align">
        <div class="col-12">
            {% if sel.number_bookmarks >= sel.number_choices %}
                <span class="badge badge-info">Bookmarks available</span>
                <a href="{{ url_for('convenor.force_convert_bookmarks', sel_id=sel.id) }}">
                    Force conversion...
                </a>
            {% else %}
                <span class="badge badge-secondary">None</span>
            {% endif %}
        </div>
    </div>
{% endif %}
"""

_name = \
"""
<a href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
<div>
{% if sel.convert_to_submitter %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Convert</span>
{% else %}
    <span class="badge badge-danger"><i class="fa fa-times"></i> Disable convert</span>
{% endif %}
</div>
"""


def selector_grid_data(students, config):

    def sel_count(sel):
        if not sel.has_submitted:
            return 0

        # group 'accepted offer' students together at the top
        if sel.has_accepted_offer:
            return 100

        if sel.has_submission_list:
            return sel.number_selections

        return -1

    data = [{'name': {
                'display': render_template_string(_name, sel=s),
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'programme': s.student.programme.label,
             'cohort': {
                 'display': render_template_string(_cohort, sel=s),
                 'value': s.student.cohort
             },
             'selections': {
                 'display': render_template_string(_selections, sel=s, config=config),
                 'sortvalue': sel_count(s)
             }} for s in students]

    return jsonify(data)
