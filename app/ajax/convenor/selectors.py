#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import jsonify, get_template_attribute, current_app, render_template
from flask_security import current_user
from jinja2 import Template, Environment

from ...models import SelectingStudent, ProjectClassConfig

# language=jinja2
_menu = """
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
        {% if is_valid_selection %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.submit_student_selection', sel_id=student.id) }}">
                <i class="fas fa-paper-plane fa-fw"></i> Submit selection
            </a>
        {% endif %}
        
        {% if student.has_submitted %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.selector_choices', id=student.id) }}">
                <i class="fas fa-eye fa-fw"></i> Show selection
            </a>
        {% elif (is_admin and not is_valid_selection) %}
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
_cohort = """
{{ simple_label(sel.student.programme.label) }}
{{ simple_label(sel.student.cohort_label) }}
{{ simple_label(sel.academic_year_label(show_details=True)) }}
"""

# language=jinja2
_bookmarks = """
{% set count = sel.number_bookmarks %}
{% if count > 0 %}
    <div class="text-success"><i class="fas fa-check-circle"></i> <strong>{{ count }}</strong> bookmark{% if count > 1 %}s{% endif %}</div>
    <div><a class="text-decoration-none link-secondary small" href="{{ url_for('convenor.selector_bookmarks', id=sel.id) }}">
        Show <i class="fas fa-chevron-circle-right"></i>
    </a></div>
{% else %}
    <span class="text-secondary"><i class="fas fa-times-circle"></i> None</span>
{% endif %}
"""

# language=jinja2
_submitted = """
{% if sel.has_submitted %}
    {% set count = sel.number_selections %}
    {% if sel.has_submission_list %}
        <div class="text-success"><i class="fas fa-check-circle"></i> <strong>{{ count }}</strong> selection{% if count > 1 %}s{% endif %}</div>
        <div><a class="text-decoration-none link-success small" href="{{ url_for('convenor.selector_choices', id=sel.id) }}">
            Show <i class="fas fa-chevron-circle-right"></i>
        </a></div>
    {% endif %}
    {% set offers = sel.number_offers_accepted %}
    {% if offers > 0 %}
        <div>
            {% for offer in sel.custom_offers_accepted %}
                <div class="text-success small"><i class="fas fa-check-circle"></i> <strong>Accepted:</strong> {{ offer.liveproject.name }}</div>
            {% endfor %}
        </div>
    {% endif %}
{% else %}
    {% if state >= config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
        <div class="text-secondary"><i class="fas fa-times-circle"></i> No</div>
        {% if is_valid_selection %}
            <div class="badge bg-success">Valid list</div>
        {% else %}
            <div class="badge bg-danger">Invalid list</div>
        {% endif %}
    {% else %}
        <div class="text-secondary"><i class="fas fa-ban"></i> Not yet open</div>
    {% endif %}
{% endif %}
"""

# language=jinja2
_confirmations = """
{% set pending = sel.number_pending %}
{% set confirmed = sel.number_confirmed %}
{% if confirmed > 0 %}<div class="text-success"><i class="fas fa-check-circle"></i> <strong>{{ confirmed }}</strong> confirmed</div>{% endif %}
{% if pending > 0 %}<div class="text-danger"><i class="fas fa-clock"></i> <strong>{{ pending }}</strong> pending</div>{% endif %}
{% if pending > 0 or confirmed > 0 %}
    <div><a class="text-decoration-none {% if pending > 0 %}link-danger{% else %}link-secondary{% endif %} small" href="{{ url_for('convenor.selector_confirmations', id=sel.id) }}">
        Show <i class="fas fa-chevron-circle-right"></i>
    </a></div>
{% else %}
    <div class="text-secondary"><i class="fas fa-times-circle"></i> None</div>
{% endif %}
{% set offers = sel.number_offers_pending + sel.number_offers_declined %}
{% if offers > 0 %}
    <div>
        {% for offer in sel.custom_offers_pending %}
            <div class="text-primary small"><strong>Offer</strong>: {{ offer.liveproject.name }}</div>
        {% endfor %}
        {% for offer in sel.custom_offers_declined %}
            <div class="text-danger small"><strong>Declined</strong>: {{ offer.liveproject.name }}</div>
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
{% if sel.has_issues %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
<div>
{% if sel.convert_to_submitter %}
    <div class="text-success small"><i class="fas fa-check-circle"></i> Convert to submitter</div>
{% else %}
    <div class="text-danger small"><i class="fas fa-times-circle"></i> No convert to submitter</div>
{% endif %}
{% set num_tasks = sel.number_available_tasks %}
{% set pl = 's' %}{% if num_tasks == 1 %}{% set pl = '' %}{% endif %}
{% if num_tasks > 0 %}
    <div class="badge bg-info">{{ num_tasks }} task{{ pl }}</div>
{% endif %}
</div>
{% if sel.has_issues %}
    <div class="mt-1">
        {% set errors = sel.errors %}
        {% set warnings = sel.warnings %}
        {% if quickfix_factory is not none %}
            {{ error_block_inline(errors, warnings, max_errors=5, max_warnings=5, quickfixes=quickfix_factory(sel)) }}
        {% else %}
            {{ error_block_inline(errors, warnings, max_errors=5, max_warnings=5) }}
        {% endif %}
    </div>
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_cohort_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_cohort)


def _build_bookmarks_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_bookmarks)


def _build_confirmations_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_confirmations)


def _build_submitted_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_submitted)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def selectors_data(students: List[SelectingStudent], config: ProjectClassConfig, quickfix_factory=None):
    # cache selector lifecycle information
    state = config.selector_lifecycle

    is_admin = current_user.has_role("admin") or current_user.has_role("root")

    simple_label = get_template_attribute("labels.html", "simple_label")
    error_block_inline = get_template_attribute("error_block.html", "error_block_inline")

    # build and cache template strings
    name_templ: Template = _build_name_templ()
    cohort_templ: Template = _build_cohort_templ()
    bookmarks_templ: Template = _build_bookmarks_templ()
    confirmations_templ: Template = _build_confirmations_templ()
    submitted_templ: Template = _build_submitted_templ()
    menu_templ: Template = _build_menu_templ()

    def _process(s: SelectingStudent):
        is_valid_selection = s.is_valid_selection[0]

        return {
            "name": {"display": render_template(name_templ, sel=s, error_block_inline=error_block_inline, quickfix_factory=quickfix_factory),
                     "sortstring": s.student.user.last_name + s.student.user.first_name},
            "cohort": {"display": render_template(cohort_templ, sel=s, simple_label=simple_label), "value": s.student.cohort},
            "bookmarks": {"display": render_template(bookmarks_templ, sel=s), "value": s.number_bookmarks},
            "confirmations": {"display": render_template(confirmations_templ, sel=s), "value": s.number_pending + s.number_confirmed},
            "submitted": render_template(submitted_templ, sel=s, config=config, state=state, is_valid_selection=is_valid_selection),
            "menu": render_template(menu_templ, student=s, config=config, state=state, is_admin=is_admin, is_valid_selection=is_valid_selection),
        }

    data = [_process(s) for s in students]

    return jsonify(data)
