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
{% set pclass = student.config.project_class %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <li>
                <a href="{{ url_for('manage_users.edit_student', id=student.student.id, url=url_for('convenor.selectors', id=pclass.id)) }}">
                    <i class="fa fa-pencil"></i> Edit student...
                </a>
            </li>
        {% endif %}
        {% if student.student.has_timeline %}
            <li>
                <a href="{{ url_for('student.timeline', student_id=student.student.id, text='selectors view', url=url_for('convenor.selectors', id=pclass.id)) }}">
                    <i class="fa fa-clock-o"></i> Show history... 
                </a>
            </li>
        {% endif %}
        <li>
            <a href="{{ url_for('convenor.selector_custom_offers', sel_id=student.id) }}">
                <i class="fa fa-cogs"></i> Custom offers...
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Selections</li>
        {% if student.is_valid_selection[0] %}
            <li>
                <a href="{{ url_for('convenor.submit_student_selection', sel_id=student.id) }}">
                    <i class="fa fa-paper-plane"></i> Submit selection
                </a>
            </li>
        {% endif %}
        
        {% if student.has_submitted %}
            <li>
                <a href="{{ url_for('convenor.selector_choices', id=student.id) }}">
                    <i class="fa fa-eye"></i> Show selection
                </a>
            </li>
        {% endif %}
        
        {% if student.convert_to_submitter %}
            <li>
                <a href="{{ url_for('convenor.disable_conversion', sid=student.id) }}">
                    <i class="fa fa-times"></i> Disable conversion
                </a>
            </li>
        {% else %}
            <li>
                <a href="{{ url_for('convenor.enable_conversion', sid=student.id) }}">
                    <i class="fa fa-check"></i> Enable conversion
                </a>
            </li>
        {% endif %}

        {% if student.has_bookmarks %}
            <li role="separator" class="divider"></li>
            <li class="dropdown-header">Bookmarks</li>    
            <li>
                <a href="{{ url_for('convenor.selector_bookmarks', id=student.id) }}">
                    <i class="fa fa-eye"></i> Show bookmarks
                </a>
            </li>

            {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
                <li>
                    <a href="{{ url_for('convenor.student_clear_bookmarks', sid=student.id) }}">
                        <i class="fa fa-trash"></i> Delete bookmarks
                    </a>
                </li>
            {% endif %}
        {% endif %}

        {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.number_pending > 0 %}
            <li role="separator" class="divider"></li>
            <li class="dropdown-header">Meeting requests</li>
            <li>
                <a href="{{ url_for('convenor.student_confirm_all', sid=student.id) }}">
                    <i class="fa fa-check"></i> Confirm all
                </a>
            </li>
            <li>
                <a href="{{ url_for('convenor.student_clear_requests', sid=student.id) }}">
                    <i class="fa fa-trash"></i> Delete all
                </a>
            </li>
        {% endif %}

        {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.number_confirmed > 0 %}
            <li role="separator" class="divider"></li>
            <li class="dropdown-header">Meeting confirmations</li>
            <li>
                <a href="{{ url_for('convenor.student_make_all_confirms_pending', sid=student.id) }}">
                    <i class="fa fa-clock-o"></i> Make all pending
                </a>
            </li>
            <li>
                <a href="{{ url_for('convenor.student_remove_confirms', sid=student.id) }}">
                    <i class="fa fa-trash"></i> Delete all
                </a>
            </li>
        {% endif %}
                
        {% if student.number_pending > 0 or student.number_confirmed > 0 %}
            <li>
                <a href="{{ url_for('convenor.selector_confirmations', id=student.id) }}">
                    <i class="fa fa-cogs"></i> Show confirmations
                </a>
            </li>
        {% endif %}
        
        <li role="separator" class="divider"></li>
        {% if config.selection_closed %}
            <li class="disabled"><a>
                <i class="fa fa-trash"></i> Delete disabled
            </a></li>
        {% else %}
            <li>
                <a href="{{ url_for('convenor.delete_selector', sid=student.id) }}">
                    <i class="fa fa-trash"></i> Delete
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""

_cohort = \
"""
{{ sel.student.programme.label|safe }}
{{ sel.student.cohort_label|safe }}
{{ sel.academic_year_label(show_details=True)|safe }}
"""

_bookmarks = \
"""
{% set count = sel.number_bookmarks %}
{% if count > 0 %}
    <span class="badge badge-primary">{{ count }}</span>
    <a href="{{ url_for('convenor.selector_bookmarks', id=sel.id) }}">
        Show...
    </a>
{% else %}
    <span class="badge badge-secondary">None</span>
{% endif %}
"""

_submitted = \
"""
{% if sel.has_submitted %}
    {% if sel.has_submission_list %}
        <span class="badge badge-success">Yes</span>
        <a href="{{ url_for('convenor.selector_choices', id=sel.id) }}">
            Show...
        </a>
    {% endif %}
    {% set offers = sel.number_offers_accepted %}
    {% if offers > 0 %}
        <div>
            {% for offer in sel.custom_offers_accepted %}
                <span class="badge badge-success">Accepted: {{ offer.liveproject.name }}</span>
            {% endfor %}
        </div>
    {% endif %}
{% else %}
    {% if state >= config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
        <span class="badge badge-secondary">No</span>
        {% if sel.is_valid_selection[0] %}
            <span class="badge badge-success">Valid selection</span>
        {% else %}
            <span class="badge badge-danger">Invalid selection</span>
        {% endif %}
    {% else %}
        <span class="badge badge-secondary">Not yet open</span>
    {% endif %}
{% endif %}
"""

_confirmations = \
"""
{% set pending = sel.number_pending %}
{% set confirmed = sel.number_confirmed %}
{% if confirmed > 0 %}<span class="badge badge-success"><i class="fa fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
{% if pending > 0 %}<span class="badge badge-warning"><i class="fa fa-clock-o"></i> Pending {{ pending }}</span>{% endif %}
{% if pending > 0 or confirmed > 0 %}
    <a href="{{ url_for('convenor.selector_confirmations', id=sel.id) }}">
        Show...
    </a>
{% else %}
    <span class="badge badge-secondary">None</span>
{% endif %}
{% set offers = sel.number_offers_pending + sel.number_offers_declined %}
{% if offers > 0 %}
    <div>
        {% for offer in sel.custom_offers_pending %}
            <span class="badge badge-primary">Offer: {{ offer.liveproject.name }}</span>
        {% endfor %}
        {% for offer in sel.custom_offers_declined %}
            <span class="badge badge-secondary">Declined: {{ offer.liveproject.name }}</span>
        {% endfor %}
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


def selectors_data(students, config):
    # cache selector lifecycle information
    state = config.selector_lifecycle

    data = [{'name': {
                'display': render_template_string(_name, sel=s),
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'cohort': {
                 'display': render_template_string(_cohort, sel=s),
                 'value': s.student.cohort
             },
             'bookmarks': {
                 'display': render_template_string(_bookmarks, sel=s),
                 'value': s.number_bookmarks
             },
             'confirmations': {
                 'display': render_template_string(_confirmations, sel=s),
                 'value': s.number_pending + s.number_confirmed
             },
             'submitted': render_template_string(_submitted, sel=s, config=config, state=state),
             'menu': render_template_string(_menu, student=s, config=config, state=state)} for s in students]

    return jsonify(data)


