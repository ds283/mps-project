#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        {% if config.open and student.bookmarks and student.bookmarks.first() %}
            <li>
                <a href="{{ url_for('convenor.student_clear_bookmarks', sid=student.id) }}">
                    Clear bookmarks
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Clear bookmarks</a>
            </li>
        {% endif %}

        {% if config.open and student.confirm_requests and student.confirm_requests.first() %}
            <li>
                <a href="{{ url_for('convenor.student_confirm_all', sid=student.id) }}">
                    Confirm all requests
                </a>
            </li>
            <li>
                <a href="{{ url_for('convenor.student_clear_requests', sid=student.id) }}">
                    Clear all requests
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Confirm all requests</a>
            </li>
            <li class="disabled">
                <a>Clear all requests</a>
            </li>
        {% endif %}

        {% if config.open and student.confirmed and student.confirmed.first() %}
            <li>
                <a href="{{ url_for('convenor.student_remove_confirms', sid=student.id) }}">
                    Remove confirmations
                </a>
                <a href="{{ url_for('convenor.student_make_all_confirms_pending', sid=student.id) }}">
                    Make all pending
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Remove confirmations</a>
            </li>
            <li class="disabled">
                <a>Make all pending</a>
            </li>
        {% endif %}
    </ul>
</div>
"""

_cohort = \
"""
<span class="label label-default">{{ student.user.student_data.programme.name }}</span>
<span class="label label-info">Y{{ student.get_academic_year }}</span>
<span class="label label-success">Cohort {{ student.user.student_data.cohort }}</span>
"""

_bookmarks = \
"""
{% for bookmark in student.bookmarks %}
    {% if loop.index < 7 %}
        {% set project = bookmark.liveproject %}
        {% set style = project.group.make_CSS_style() %}
        <a href="{{ url_for('faculty.live_project', pid=project.id) }}"
           class="label label-info table-button"
           {% if style is not none %}style="{{ style }}"{% endif %}>
            {% if project.name|length > 20 %}{{ project.name[0:20] }}...{% else %}{{ project.name }}{% endif %}
        </a>
    {% elif loop.index == 7 %}
        <span class="label label-default">...</span>
    {% endif %}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_pending = \
"""
{% for project in student.confirm_requests %}
    <div class="dropdown">
        <a class="label label-success dropdown-toggle table-button"
                type="button" data-toggle="dropdown">
            <i class="fa fa-plus"></i> {% if project.name|length > 20 %}{{ project.name[0:20] }}...{% else %}{{ project.name }}{% endif %}
        </a>
        <ul class="dropdown-menu">
            {% if config.open %}
                <li>
                    <a href="{{ url_for('convenor.confirm', sid=student.id, pid=project.id) }}">
                        Confirm
                    </a>
                </li>
                <li>
                    <a href="{{ url_for('convenor.cancel_confirm', sid=student.id, pid=project.id) }}">
                        Remove
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a>Confirm</a>
                </li>
                <li class="disabled">
                    <a>Remove</a>
                </li>
            {% endif %}
        </ul>
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_confirmed = \
"""
{% for liveproject in student.confirmed %}
    <div class="dropdown">
        <a class="label label-warning dropdown-toggle table-button"
                type="button" data-toggle="dropdown">
            <i class="fa fa-times"></i> {% if liveproject.name|length > 20 %}{{ liveproject.name[0:20] }}...{% else %}{{ liveproject.name }}{% endif %}
        </a>
        <ul class="dropdown-menu">
            {% if config.open %}
                <li>
                    <a href="{{ url_for('convenor.deconfirm', sid=student.id, pid=liveproject.id, tabid=4) }}">
                        Remove
                    </a>
                </li>
                <li>
                    <a href="{{ url_for('convenor.deconfirm_to_pending', sid=student.id, pid=liveproject.id, tabid=4) }}">
                        Make pending
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a>Remove</a>
                </li>
                <li class="disabled">
                    <a>Make pending</a>
                </li>
            {% endif %}
        </ul>
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


def selectors_data(students, config):

    data = [{'last': s.user.last_name,
             'first': s.user.first_name,
             'cohort': render_template_string(_cohort, student=s),
             'bookmarks': render_template_string(_bookmarks, student=s),
             'pending': render_template_string(_pending, student=s, config=config),
             'confirmed': render_template_string(_confirmed, student=s, config=config),
             'ok': '<span class="label label-success">OK</span>' if s.is_valid_selection
             else '<span class="label label-danger">No</span>',
             'menu': render_template_string(_menu, student=s, config=config)} for s in students]

    return jsonify(data)


_enroll_action = \
"""
<a href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id) }}" class="btn btn-warning btn-sm">Manually enroll</a>
"""


def enroll_selectors_data(students, config):

    data = [{'last': s.user.last_name,
             'first': s.user.first_name,
             'programme': '<span class="label label-default">{prog}</span>'.format(prog=s.programme.name),
             'admitted': '<span class="label label-info">{yra}-{yrb}</span>'.format(yra=s.cohort, yrb=s.cohort+1),
             'acadyear': '<span class="label label-info">Y{yr}</span>'.format(yr=config.year-s.cohort+1),
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
