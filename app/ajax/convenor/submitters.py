#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, get_template_attribute, jsonify, render_template
from jinja2 import Template

from ...models import ProjectClassConfig

# language=jinja2
_cohort = """
{{ simple_label(sub.student.programme.short_label) }}
{{ simple_label(sub.student.cohort_label) }}
{{ simple_label(sub.academic_year_label(show_details=True)) }}
"""


# language=jinja2
_periods = """
{% set recs = sub.ordered_assignments.all() %}
<div class="d-flex flex-row justify-content-start align-items-start gap-2"></div>
    {% for rec in recs %}
        {% set number_submissions = rec.owner.config.number_submissions %}
        {{ project_tag(rec, number_submissions > 1) }}
    {% else %}
        <div class="badge bg-danger">None</div>
    {% endfor %}
</div>
"""


# language=jinja2
_menu = """
{% set config = sub.config %}
{% set pclass = config.project_class %}
{% set period = config.current_period %}
{% set record = sub.get_assignment() %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_student', id=sub.student.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit student...
            </a>
        {% endif %}
        {% if sub.student.has_timeline %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.timeline', student_id=sub.student.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fas fa-history fa-fw"></i> Show history...
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_journal_inspector', student_id=sub.student_id, url=url_for('convenor.submitters', id=pclass.id), text='submitters view') }}">
            <i class="fas fa-book fa-fw"></i> View journal...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_tasks', type=2, sid=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
            <i class="fas fa-tasks fa-fw"></i> Tasks...
        </a>

        {% if sub.published and pclass.publish %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.unpublish_assignment', id=sub.id) }}">
                <i class="fas fa-eye-slash fa-fw"></i> Unpublish
            </a>
        {% else %}
            {% if pclass.publish %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.publish_assignment', id=sub.id) }}">
                    <i class="fas fa-eye fa-fw"></i> Publish to student
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-eye-slash fa-fw"></i> Cannot publish
                </a>
            {% endif %}
        {% endif %}
        <div role="separator" class="dropdown-divider"></div>

        {% set disabled = not pclass.publish %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('documents.submitter_documents', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-file fa-fw"></i> Manage documents...
        </a>
        {% if record.report_id is none and period.canvas_enabled and not period.closed and record.canvas_submission_available is true %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('documents.pull_report_from_canvas', rid=record.id, url=url_for('convenor.submitters', id=pclass.id)) }}">
                <i class="fas fa-download fa-fw"></i> Pull report from Canvas
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.view_feedback', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-comments fa-fw"></i> View feedback...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.manual_assign', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-wrench fa-fw"></i> Assign project...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_roles', sub_id=sub.id, text='submitters view', url=url_for('convenor.submitters', id=pclass.id)) }}">
            <i class="fas fa-user-circle fa-fw"></i> Edit roles...
        </a>

        <div role="separator" class="dropdown-divider"></div>

        {% if allow_delete %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_submitter', sid=sub.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-trash fa-fw"></i> Delete disabled</a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_name = """
{% from "error_block.html" import error_block_inline %}
{% set config = sub.config %}
{% set pclass = config.project_class %}
{% set student = sub.student %}
{% set user = student.user %}
<div>
    {% if config.canvas_enabled and sub is not none %}
        {% if sub.canvas_user_id is not none %}
            <i class="fas fa-circle me-1 text-success" data-bs-toggle="tooltip" title="This student is enrolled on the linked Canvas site"></i>
        {% elif sub.canvas_missing %}
            <i class="fas fa-circle me-1 text-danger" data-bs-toggle="tooltip" title="This student is not enrolled on the linked Canvas site"></i>
        {% else %}
            <i class="fas fa-unlink me-1" data-bs-toggle="tooltip" title="Information associated with this student for the linked Canvas site has not yet been synchronized"></i>
        {% endif %}
    {% endif %}
    {% if show_name %}
        <a class="text-decoration-none" href="mailto:{{ user.email }}">{{ user.name }}</a>
        {% if sub.has_issues %}
            <i class="fas fa-exclamation-triangle text-danger"></i>
        {% endif %}
    {% endif %}
    {% if show_number %}
        {% if current_user.has_role('admin') or current_user.has_role('root') %}
            <a href="{{ url_for('manage_users.edit_student', id=student.id, url=url_for('convenor.submitters', id=pclass.id)) }}" class="badge bg-secondary text-decoration-none">
                #{{ student.exam_number }}
            </a>
        {% else %}
            <span class="badge bg-secondary">#{{ student.exam_number }}</span>
        {% endif %}
    {% endif %}
    {% set num_tasks = sub.number_available_tasks %}
    {% set pl = 's' %}{% if num_tasks == 1 %}{% set pl = '' %}{% endif %}
    {% if num_tasks > 0 %}
        <span class="badge bg-info">{{ num_tasks }} task{{ pl }}</span>
    {% endif %}
</div>
<div>
    {% if sub.published and pclass.publish %}
        <span class="badge bg-primary"><i class="fas fa-eye"></i> Published</span>
    {% else %}
        <span class="badge bg-warning text-dark"><i class="fas fa-eye-slash"></i> Unpublished</span>
    {% endif %}
</div>
{% if sub.has_issues %}
    {% set errors = sub.errors %}
    {% set warnings = sub.warnings %}
    <div class="mt-1">
        {{ error_block_inline(errors, warnings, max_errors=5, max_warnings=5) }}
    </div>
{% endif %}
"""


def _build_name_templ() -> Template:
    return current_app.jinja_env.from_string(_name)


def _build_cohort_templ() -> Template:
    return current_app.jinja_env.from_string(_cohort)


def _build_periods_templ() -> Template:
    return current_app.jinja_env.from_string(_periods)


def _build_menu_templ() -> Template:
    return current_app.jinja_env.from_string(_menu)


def submitters_data(students, config, show_name, show_number, sort_number):
    submittter_state = config.submitter_lifecycle
    allow_delete = (
        submittter_state <= ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY
    )

    # since these templates are loaded from disk, Jinja2 will cache them automatically
    simple_label = get_template_attribute("labels.html", "simple_label")
    project_tag = get_template_attribute(
        "convenor/submitters_macros.html", "project_tag"
    )

    # however, template *strings* are not cached
    # we have to do this ourselves
    name_templ: Template = _build_name_templ()
    cohort_templ: Template = _build_cohort_templ()
    periods_templ: Template = _build_periods_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": {
                "display": render_template(
                    name_templ,
                    sub=s,
                    show_name=show_name,
                    show_number=show_number,
                ),
                "sortvalue": s.student.exam_number
                if sort_number
                else s.student.user.last_name + s.student.user.first_name,
            },
            "cohort": {
                "display": render_template(
                    cohort_templ, sub=s, simple_label=simple_label
                ),
                "value": s.student.cohort,
            },
            "periods": render_template(
                periods_templ,
                sub=s,
                project_tag=project_tag,
            ),
            "menu": render_template(menu_templ, sub=s, allow_delete=allow_delete),
        }
        for s in students
    ]

    return jsonify(data)
