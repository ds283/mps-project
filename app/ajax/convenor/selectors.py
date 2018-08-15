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
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.has_bookmarks %}
            <li>
                <a href="{{ url_for('convenor.student_clear_bookmarks', sid=student.id) }}">
                    <i class="fa fa-trash"></i> Delete bookmarks
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-trash"></i> Delete bookmarks
                </a>
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
                <a href="{{ url_for('convenor.selector_choices', id=student.id) }}">
                    Show submitted choices
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Show submitted choices</s>
            </li>
        {% endif %}

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Meeting requests</li>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.confirm_requests and student.confirm_requests.first() %}
            <li>
                <a href="{{ url_for('convenor.student_confirm_all', sid=student.id) }}">
                    <i class="fa fa-check"></i> Confirm all requests
                </a>
            </li>
            <li>
                <a href="{{ url_for('convenor.student_clear_requests', sid=student.id) }}">
                    <i class="fa fa-trash"></i> Delete all requests
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-check"></i> Confirm all requests
                </a>
            </li>
            <li class="disabled">
                <a>
                    <i class="fa fa-trash"></i> Delete all requests
                </a>
            </li>
        {% endif %}

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Meeting confirmations</li>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.confirmed and student.confirmed.first() %}
            <li>
                <a href="{{ url_for('convenor.student_remove_confirms', sid=student.id) }}">
                    <i class="fa fa-trash"></i> Delete confirmations
                </a>
                <a href="{{ url_for('convenor.student_make_all_confirms_pending', sid=student.id) }}">
                    <i class="fa fa-clock-o"></i> Make all pending
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-trash"></i> Delete confirmations
                </a>
            </li>
            <li class="disabled">
                <a>
                    <i class="fa fa-clock-o"></i> Make all pending
                </a>
            </li>
        {% endif %}
                
        {% if student.number_pending > 0 or student.number_confirmed > 0 %}
            <li>
                <a href="{{ url_for('convenor.selector_confirmations', id=student.id) }}">
                    <i class="fa fa-pencil"></i> Show confirmations
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-pencil"></i> Show confirmations
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""

_cohort = \
"""
{{ sel.student.programme.label()|safe }}
{{ sel.academic_year_label()|safe }}
{{ sel.student.cohort_label()|safe }}
"""

_bookmarks = \
"""
{% set count = sel.get_num_bookmarks %}
{% if count > 0 %}
    <span class="label label-primary">{{ count }}</span>
    <a href="{{ url_for('convenor.selector_bookmarks', id=sel.id) }}">
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
    <a href="{{ url_for('convenor.selector_choices', id=sel.id) }}">
        Show ...
    </a>
{% else %}
    <span class="label label-danger">No</span>
{% endif %}
"""

_confirmations = \
"""
{% set pending = sel.number_pending %}
{% set confirmed = sel.number_confirmed %}
{% if confirmed > 0 %}<span class="label label-success"><i class="fa fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
{% if pending > 0 %}<span class="label label-warning"><i class="fa fa-clock-o"></i> Pending {{ pending }}</span>{% endif %}
{% if pending > 0 or confirmed > 0 %}
    <a href="{{ url_for('convenor.selector_confirmations', id=sel.id) }}">
        Show ...
    </a>
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""


def selectors_data(students, config):

    data = [{'name': {
                'display': s.student.user.name,
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'cohort': render_template_string(_cohort, sel=s),
             'bookmarks': {
                 'display': render_template_string(_bookmarks, sel=s),
                 'value': s.get_num_bookmarks
             },
             'confirmations': {
                 'display': render_template_string(_confirmations, sel=s),
                 'value': s.number_pending + s.number_confirmed
             },
             'submitted': render_template_string(_submitted, sel=s),
             'menu': render_template_string(_menu, student=s, config=config)} for s in students]

    return jsonify(data)


_enroll_action = \
"""
<a href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id) }}" class="btn btn-warning btn-sm">
    <i class="fa fa-plus"></i> Manually enroll
</a>
"""


def enroll_selectors_data(students, config):

    data = [{'name': {
                'display': s.user.name,
                'sortstring': s.user.last_name + s.user.first_name
             },
             'programme': s.programme.label(),
             'cohort': s.cohort_label(),
             'acadyear': '<span class="label label-info">Y{yr}</span>'.format(yr=config.year-s.cohort+1),
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
