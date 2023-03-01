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
from flask_security import current_user


# language=jinja2
_menu = \
"""
{% set pclass = student.config.project_class %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_student', id=student.student.id, url=url_for('convenor.selectors', id=pclass.id)) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit student...
            </a>
        {% endif %}
        {% if student.student.has_timeline %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.timeline', student_id=student.student.id, text='selectors view', url=url_for('convenor.selectors', id=pclass.id)) }}">
                <i class="fas fa-history fa-fw"></i> Show history... 
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.selector_custom_offers', sel_id=student.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Custom offers...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_tasks', type=1, sid=student.id, text='selectors view', url=url_for('convenor.selectors', id=pclass.id)) }}">
            <i class="fas fa-tasks fa-fw"></i> Tasks...
        </a>
        {% if is_admin %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.move_selector', sid=student.id, text='selectors view', url=url_for('convenor.selectors', id=pclass.id)) }}">
                <i class="fas fa-arrow-alt-circle-right fa-fw"></i> Move...
            </a>
        {% endif %}
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Selections</div>
        {% set is_valid = student.is_valid_selection[0] %}
        {% if is_valid %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.submit_student_selection', sel_id=student.id) }}">
                <i class="fas fa-paper-plane fa-fw"></i> Submit selection
            </a>
        {% endif %}
        
        {% if student.has_submitted %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.selector_choices', id=student.id) }}">
                <i class="fas fa-eye fa-fw"></i> Show selection
            </a>
        {% elif (is_admin and not is_valid) %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.force_submit_selection', sel_id=student.id) }}">
                <i class="fas fa-exclamation-triangle fa-fw"></i> Force submission
            </a>
        {% endif %}
        
        {% if student.convert_to_submitter %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.disable_conversion', sid=student.id) }}">
                <i class="fas fa-times fa-fw"></i> Disable conversion
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.enable_conversion', sid=student.id) }}">
                <i class="fas fa-check fa-fw"></i> Enable conversion
            </a>
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Bookmarks</div>    
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.selector_bookmarks', id=student.id) }}">
            <i class="fas fa-eye fa-fw"></i> Show bookmarks
        </a>

        {% if student.has_bookmarks %}
            {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_clear_bookmarks', sid=student.id) }}">
                    <i class="fas fa-trash fa-fw"></i> Delete bookmarks
                </a>
            {% endif %}
        {% endif %}

        {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.number_pending > 0 %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Meeting requests</div>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_confirm_all', sid=student.id) }}">
                <i class="fas fa-check fa-fw"></i> Confirm all
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_clear_requests', sid=student.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete all
            </a>
        {% endif %}

        {% if state == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and student.number_confirmed > 0 %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Meeting confirmations</div>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_make_all_confirms_pending', sid=student.id) }}">
                <i class="fas fa-clock fa-fw"></i> Make all pending
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_remove_confirms', sid=student.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete all
            </a>
        {% endif %}
                
        {% if student.number_pending > 0 or student.number_confirmed > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.selector_confirmations', id=student.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Show confirmations
            </a>
        {% endif %}
        
        <div role="separator" class="dropdown-divider"></div>
        {% if config.selection_closed and not is_admin %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-trash fa-fw"></i> Delete is disabled
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_selector', sid=student.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_cohort = \
"""
{{ sel.student.programme.label|safe }}
{{ sel.student.cohort_label|safe }}
{{ sel.academic_year_label(show_details=True)|safe }}
"""

# language=jinja2
_bookmarks = \
"""
{% set count = sel.number_bookmarks %}
{% if count > 0 %}
    <span class="badge bg-primary">{{ count }}</span>
    <a class="text-decoration-none" href="{{ url_for('convenor.selector_bookmarks', id=sel.id) }}">
        Show...
    </a>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_submitted = \
"""
{% if sel.has_submitted %}
    {% if sel.has_submission_list %}
        <span class="badge bg-success">Yes</span>
        <a class="text-decoration-none" href="{{ url_for('convenor.selector_choices', id=sel.id) }}">
            Show...
        </a>
    {% endif %}
    {% set offers = sel.number_offers_accepted %}
    {% if offers > 0 %}
        <div>
            {% for offer in sel.custom_offers_accepted %}
                <span class="badge bg-success">Accepted: {{ offer.liveproject.name }}</span>
            {% endfor %}
        </div>
    {% endif %}
{% else %}
    {% if state >= config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
        <span class="badge bg-secondary">No</span>
        {% if sel.is_valid_selection[0] %}
            <span class="badge bg-success">Valid selection</span>
        {% else %}
            <span class="badge bg-danger">Invalid selection</span>
        {% endif %}
    {% else %}
        <span class="badge bg-secondary">Not yet open</span>
    {% endif %}
{% endif %}
"""

# language=jinja2
_confirmations = \
"""
{% set pending = sel.number_pending %}
{% set confirmed = sel.number_confirmed %}
{% if confirmed > 0 %}<span class="badge bg-success"><i class="fas fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
{% if pending > 0 %}<span class="badge bg-warning text-dark"><i class="fas fa-clock"></i> Pending {{ pending }}</span>{% endif %}
{% if pending > 0 or confirmed > 0 %}
    <a class="text-decoration-none" href="{{ url_for('convenor.selector_confirmations', id=sel.id) }}">
        Show...
    </a>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
{% set offers = sel.number_offers_pending + sel.number_offers_declined %}
{% if offers > 0 %}
    <div>
        {% for offer in sel.custom_offers_pending %}
            <span class="badge bg-primary">Offer: {{ offer.liveproject.name }}</span>
        {% endfor %}
        {% for offer in sel.custom_offers_declined %}
            <span class="badge bg-secondary">Declined: {{ offer.liveproject.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
{% if sel.has_issues %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
<div>
{% if sel.convert_to_submitter %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Convert</span>
{% else %}
    <span class="badge bg-danger"><i class="fas fa-times"></i> No convert</span>
{% endif %}
{% if sel.student.intermitting %}
    <span class="badge bg-warning text-dark">TWD</span>
{% endif %}
{% set num_tasks = sel.number_available_tasks %}
{% set pl = 's' %}{% if num_tasks == 1 %}{% set pl = '' %}{% endif %}
{% if num_tasks > 0 %}
    <span class="badge bg-info text-dark">{{ num_tasks }} task{{ pl }}</span>
{% endif %}
</div>
{% if sel.has_issues %}
    {% set errors = sel.errors %}
    {% set warnings = sel.warnings %}
    <div class="mt-1">
        {% if errors|length == 1 %}
            <span class="badge bg-danger">1 error</span>
        {% elif errors|length > 1 %}
            <span class="badge bg-danger">{{ errors|length }} errors</span>
        {% endif %}
        {% if warnings|length == 1 %}
            <span class="badge bg-warning text-dark">1 warning</span>
        {% elif warnings|length > 1 %}
            <span class="badge bg-warning text-dark">{{ warnings|length }} warnings</span>
        {% endif %}
        {% if errors|length > 0 %}
            <div class="error-block">
                {% for item in errors %}
                    {% if loop.index <= 5 %}
                        <div class="error-message">{{ item }}</div>
                    {% elif loop.index == 6 %}
                        <div class="error-message">Further errors suppressed...</div>
                    {% endif %}            
                {% endfor %}
            </div>
        {% endif %}
        {% if warnings|length > 0 %}
            <div class="error-block">
                {% for item in warnings %}
                    {% if loop.index <= 5 %}
                        <div class="error-message">Warning: {{ item }}</div>
                    {% elif loop.index == 6 %}
                        <div class="error-message">Further errors suppressed...</div>
                    {% endif %}
                {% endfor %}
            </div>
        {% endif %}
    </div>
{% endif %}
"""


def selectors_data(students, config):
    # cache selector lifecycle information
    state = config.selector_lifecycle

    is_admin = current_user.has_role('admin') or current_user.has_role('root')

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
             'menu': render_template_string(_menu, student=s, config=config, state=state, is_admin=is_admin)}
        for s in students]

    return jsonify(data)


