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
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a class="dropdown-item" href="{{ url_for('manage_users.edit_student', id=student.student.id, url=url_for('convenor.selectors', id=pclass.id)) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit student...
            </a>
        {% endif %}
        {% if student.student.has_timeline %}
            <a class="dropdown-item" href="{{ url_for('student.timeline', student_id=student.student.id, text='selectors view', url=url_for('convenor.selectors', id=pclass.id)) }}">
                <i class="fas fa-history fa-fw"></i> Show history... 
            </a>
        {% endif %}
        <a class="dropdown-item" href="{{ url_for('convenor.selector_custom_offers', sel_id=student.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Custom offers...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.student_tasks', type=0, sid=student.id, text='selectors view', url=url_for('convenor.selectors', id=pclass.id)) }}">
            <i class="fas fa-clipboard-check fa-fw"></i> Tasks...
        </a>
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Selections</div>
        {% if student.is_valid_selection[0] %}
            <a class="dropdown-item" href="{{ url_for('convenor.submit_student_selection', sel_id=student.id) }}">
                <i class="fas fa-paper-plane fa-fw"></i> Submit selection
            </a>
        {% endif %}
        
        {% if student.has_submitted %}
            <a class="dropdown-item" href="{{ url_for('convenor.selector_choices', id=student.id) }}">
                <i class="fas fa-eye fa-fw"></i> Show selection
            </a>
        {% endif %}
        
        {% if student.convert_to_submitter %}
            <a class="dropdown-item" href="{{ url_for('convenor.disable_conversion', sid=student.id) }}">
                <i class="fas fa-times fa-fw"></i> Disable conversion
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('convenor.enable_conversion', sid=student.id) }}">
                <i class="fas fa-check fa-fw"></i> Enable conversion
            </a>
        {% endif %}

        {% if student.has_bookmarks %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Bookmarks</div>    
            <a class="dropdown-item" href="{{ url_for('convenor.selector_bookmarks', id=student.id) }}">
                <i class="fas fa-eye fa-fw"></i> Show bookmarks
            </a>

            {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
                <a class="dropdown-item" href="{{ url_for('convenor.student_clear_bookmarks', sid=student.id) }}">
                    <i class="fas fa-trash fa-fw"></i> Delete bookmarks
                </a>
            {% endif %}
        {% endif %}

        {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.number_pending > 0 %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Meeting requests</div>
            <a class="dropdown-item" href="{{ url_for('convenor.student_confirm_all', sid=student.id) }}">
                <i class="fas fa-check fa-fw"></i> Confirm all
            </a>
            <a class="dropdown-item" href="{{ url_for('convenor.student_clear_requests', sid=student.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete all
            </a>
        {% endif %}

        {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.number_confirmed > 0 %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Meeting confirmations</div>
            <a class="dropdown-item" href="{{ url_for('convenor.student_make_all_confirms_pending', sid=student.id) }}">
                <i class="fas fa-clock fa-fw"></i> Make all pending
            </a>
            <a class="dropdown-item" href="{{ url_for('convenor.student_remove_confirms', sid=student.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete all
            </a>
        {% endif %}
                
        {% if student.number_pending > 0 or student.number_confirmed > 0 %}
            <a class="dropdown-item" href="{{ url_for('convenor.selector_confirmations', id=student.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Show confirmations
            </a>
        {% endif %}
        
        <div role="separator" class="dropdown-divider"></div>
        {% if config.selection_closed %}
            <a class="dropdown-item disabled">
                <i class="fas fa-trash fa-fw"></i> Delete is disabled
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('convenor.delete_selector', sid=student.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% endif %}
    </div>
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
{% if confirmed > 0 %}<span class="badge badge-success"><i class="fas fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
{% if pending > 0 %}<span class="badge badge-warning"><i class="fas fa-clock"></i> Pending {{ pending }}</span>{% endif %}
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
    <span class="badge badge-success"><i class="fas fa-check"></i> Convert</span>
{% else %}
    <span class="badge badge-danger"><i class="fas fa-times"></i> Disable convert</span>
{% endif %}
{% if sel.student.intermitting %}
    <span class="badge badge-warning">TWD</span>
{% endif %}
{% set num_tasks = sel.number_tasks %}
{% set pl = 's' %}{% if num_tasks == 1 %}{% set pl = '' %}{% endif %}
{% if num_tasks > 0 %}
    <span class="badge badge-info">{{ num_tasks }} task{{ pl }}</span>
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


