#
# Created by David Seery on 31/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_cohort = """
{{ simple_label(sel.student.cohort_label) }}
{{ simple_label(sel.academic_year_label(show_details=True)) }}
"""

# language=jinja2
_selections = """
{% if sel.has_submitted %}
    {% if sel.has_accepted_offer %}
        {% set offer = sel.accepted_offer %}
        {% set project = offer.liveproject %}
        {% if project %}
            <span class="badge bg-success"><i class="fas fa-check"></i> {{ project.name }} ({{ project.owner.user.last_name }})</span>
        {% else %}
            <span class="badge bg-danger">MISSING ACCEPTED PROJECT</span>
        {% endif %}
    {% else %}
        {% for item in sel.ordered_selections %}
            {% set project = item.liveproject %}
            <div class="dropdown">
                {% if project.group %}
                    {% set style = project.group.make_CSS_style() %}
                {% else %}
                    {% set style = none %}
                {% endif %}
                <a class="badge text-decoration-none text-nohover-dark bg-info dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">#{{ item.rank }}
                    {{ item.format_project()|safe }}
                    {% if not project.generic and project.owner is not none %}
                        &ndash; {{ project.owner.user.name }}
                    {% else %}
                        (generic)
                    {% endif %}
                </a>
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 small">
                    {% set menu_items = item.menu_order %}
                    {% for mi in menu_items %}
                        {% if mi is string %}
                            <div role="separator" class="dropdown-divider"></div>
                            <div class="dropdown-header">{{ mi }}</div>
                        {% elif mi is number %}
                            {% set disabled = (mi == item.hint) %}
                            <a class="dropdown-item d-flex gap-2 small {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.set_hint', id=item.id, hint=mi) }}"{% endif %}>
                                {{ item.menu_item(mi)|safe }}
                            </a>
                        {% endif %}
                    {% endfor %}
                </div>
                {% if item.converted_from_bookmark %}
                    <span class="badge bg-warning text-dark"><i class="fas fa-exclamation-triangle"></i> Bookmark</span>
                {% endif %}
                {% if item.hint != item.SELECTION_HINT_NEUTRAL %}
                    <span class="badge bg-warning text-dark"><i class="fas fa-exclamation-triangle"></i> Hint</span>
                {% endif %}
            </div>
        {% endfor %}
    {% endif %}
{% else %}
    <div class="row vertical-align">
        <div class="col-12">
            {% if sel.number_bookmarks >= sel.number_choices %}
                <span class="badge bg-info">Bookmarks available</span>
                <a class="text-decoration-none" href="{{ url_for('convenor.force_convert_bookmarks', sel_id=sel.id) }}">
                    Force conversion...
                </a>
            {% else %}
                <span class="badge bg-secondary">None</span>
            {% endif %}
        </div>
    </div>
{% endif %}
"""

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
<div>
{% if sel.convert_to_submitter %}
    <div class="text-success small"><i class="fas fa-check-circle"></i> Convert to submitter</div>
{% else %}
    <div class="text-danger small"><i class="fas fa-times-circle"></i> No convert to submitter</div>
{% endif %}
{% if sel.student.intermitting %}
    <div class="badge bg-warning text-dark">TWD</div>
{% endif %}
</div>
"""

# language=jinja2
_programme = """
{{ simple_label(s.programme.label) }}
"""


def selector_grid_data(students, config):
    simple_label = get_template_attribute("labels.html", "simple_label")

    def sel_count(sel):
        if not sel.has_submitted:
            return 0

        # group 'accepted offer' students together at the top
        if sel.has_accepted_offer:
            return 100

        if sel.has_submission_list:
            return sel.number_selections

        return -1

    data = [
        {
            "name": {"display": render_template_string(_name, sel=s), "sortstring": s.student.user.last_name + s.student.user.first_name},
            "programme": render_template_string(_programme, s=s, simple_label=simple_label),
            "cohort": {"display": render_template_string(_cohort, sel=s, simple_label=simple_label), "value": s.student.cohort},
            "selections": {"display": render_template_string(_selections, sel=s, config=config), "sortvalue": sel_count(s)},
        }
        for s in students
    ]

    return jsonify(data)
