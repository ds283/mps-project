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
        {% if config.state == config.LIFECYCLE_SELECTIONS_OPEN and student.bookmarks and student.bookmarks.first() %}
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

        {% if config.state == config.LIFECYCLE_SELECTIONS_OPEN and student.confirm_requests and student.confirm_requests.first() %}
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

        {% if config.state == config.LIFECYCLE_SELECTIONS_OPEN and student.confirmed and student.confirmed.first() %}
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
        
        {% if student.get_num_bookmarks > 0 %}
            <li>
                <a href="{{ url_for('convenor.selector_bookmarks', id=student.id) }}">
                    Show bookmarks
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Show bookmarks</a>
            </li>
        {% endif %}
        
        {% if student.has_submitted %}
            <li>
                <a href="{{ url_for('convenor.selector_submission', id=student.id) }}">
                    Show submission
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Show submission</s>
            </li>
        {% endif %}
    </ul>
</div>
"""

_cohort = \
"""
{{ student.user.student_data.programme.label()|safe }}
{{ student.academic_year_label()|safe }}
{{ student.user.student_data.cohort_label()|safe }}
"""

_bookmarks = \
"""
{% set count = sel.get_num_bookmarks %}
<span class="badge">{{ count }}</span>
{% if count > 0 %}
    <a href="{{ url_for('convenor.selector_bookmarks', id=sel.id) }}">
        Show ...
    </a>
{% endif %}
"""

_confirmations = \
"""
{% set pending = sel.get_num_bookmarks %}
{% set confirmed = sel.number_confirmed %}
{% if pending > 0 or confirmed > 0 %}
    Confirmed <span class="badge">{{ confirmed }}</span>
    Pending <span class="badge">{{ pending }}</span>
    <a href="{{ url_for('convenor.selector_student_confirmations', id=sel.id) }}">
        Show ...
    </a>
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""

_submitted = \
"""
{% if sel.has_submitted %}
    <span class="label label-success">Yes</span>
    <a href="{{ url_for('convenor.selector_submission', id=sel.id) }}">
        Show ...
    </a>
{% else %}
    <span class="label label-danger">No</span>
{% endif %}
"""


def selectors_data(students, config):

    data = [{'last': s.user.last_name,
             'first': s.user.first_name,
             'cohort': render_template_string(_cohort, student=s),
             'bookmarks': {
                 'display': render_template_string(_bookmarks, sel=s),
                 'value': s.get_num_bookmarks
             },
             'confirmations': render_template_string(_confirmations, sel=s),
             'submitted': render_template_string(_submitted, sel=s),
             'menu': render_template_string(_menu, student=s, config=config)} for s in students]

    return jsonify(data)


_enroll_action = \
"""
<a href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id) }}" class="btn btn-warning btn-sm">Manually enroll</a>
"""


def enroll_selectors_data(students, config):

    data = [{'last': s.user.last_name,
             'first': s.user.first_name,
             'programme': s.programme.label(),
             'admitted': s.cohort_label(),
             'acadyear': '<span class="label label-info">Y{yr}</span>'.format(yr=config.year-s.cohort+1),
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
