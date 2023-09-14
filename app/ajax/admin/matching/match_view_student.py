#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, get_template_attribute

from app import db
from app.models import SelectingStudent, StudentData, EmailLog, User

# language=jinja2
_student = \
"""
{% set config = sel.config %}
<div>
    <a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
    {% if not valid %}
        <i class="fas fa-exclamation-triangle text-danger"></i>
    {% endif %}
</div>
<a class="text-muted text-decoration-none small" role="button" data-bs-toggle="offcanvas" href="#edit_{{ sel.id }}" aria-controls="edit_{{ sel.id }}">Show details <i class="fas fa-chevron-right"></i></a>
<div class="offcanvas offcanvas-start text-bg-light" tabindex="-1" id="edit_{{ sel.id }}" aria-labelledby="editLabel_{{ sel.id }}">
    <div class="offcanvas-header">
        <h5 class="offcanas-title" id="editLabel_{{ sel.id }}">
            <a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
        </h5>
    </div>
    <div class="offcanvas-body">
        {% if not sel.convert_to_submitter %}
            <div class="text-danger">
                Conversion of this student is disabled.
                <a class="text-decoration-none" href="{{ url_for('admin.delete_match_record', attempt_id=attempt_id, selector_id=sel.id) }}">
                    Delete...
                </a>
            </div>
        {% endif %}
        {% set swatch_colour = config.project_class.make_CSS_style() %}
        <div class="d-flex flex-row justify-content-start align-items-center gap-2">
            {{ medium_swatch(swatch_colour) }}
            <span class="text-secondary">{{ config.name }}</span>
            <span>
                <i class="fa fa-user-circle me-1"></i>
                <a class="text-decoration-none" href="mailto:{{ config.convenor_email }}">{{ config.convenor_name }}</a>
            </span>
        </div>
        {% if sel.has_submission_list %}
            <div class="mt-3 card border-primary">
                <div class="card-header">Ranked selection</div>
                {% set list = sel.ordered_selections %}
                <div class="card-body">
                    <div class="row small">
                        <div class="col-1"><strong>Rank</strong></div>
                        <div class="col-6"><strong>Project</strong></div>
                        <div class="col-4"><strong>Owner</strong></div>
                        <div class="col-1"><strong>Actions</strong></div>
                    </div>
                    <hr>
                    {% for item in list %}
                        {% set project = item.liveproject %}
                        <div class="row small">
                            <div class="col-1"><strong>#{{ item.rank}}</strong></div>
                            <div class="col-6"><a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=project.id, text='student match inspector', url=url_for('admin.match_student_view', id=attempt_id, text=text, url=url)) }}">{{ item.format_project()|safe }}</a></div>
                            <div class="col-4">
                                {% if project.generic or project.owner is none %}
                                    generic
                                {% else %}
                                    <i class="fa fa-user-circle me-1"></i>
                                    <a class="text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
                                {% endif %}
                            </div>
                            <div class="col-1">
                                <button class="btn btn-xs {% if item.has_hint %}btn-danger{% else %}btn-outline-secondary{% endif %} dropdown-toggle" data-bs-toggle="dropdown" role="button" aria-haspopup="true" aria-expanded="false">
                                    Hint
                                </button>
                                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end small">
                                    {% set menu_items = item.menu_order %}
                                    {% for mi in menu_items %}
                                        {% if mi is string %}
                                            <div role="separator" class="dropdown-divider"></div>
                                            <div class="dropdown-header">{{ mi }}</div>
                                        {% elif mi is number %}
                                            {% set disabled = (mi == item.hint) %}
                                            <a class="dropdown-item d-flex gap-2 small {% if disabled %}disabled{% endif %}"
                                               {% if not disabled %}href="{{ url_for('convenor.set_hint', id=item.id, hint=mi) }}"{% endif %}>
                                                {{ item.menu_item(mi)|safe }}
                                            </a>
                                        {% endif %}
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                    {% endfor %}
                    <div class="mt-3">
                        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('convenor.selector_choices', id=sel.id, text='student match inspector', url=url_for('admin.match_student_view', id=attempt_id, text=text, url=url)) }}">Edit selection...</a>
                    </div>
                </div>
            </div>
        {% endif %}
        {% if emails and emails|length > 0 %}
            <div class="mt-3 card border-secondary">
                <div class="card-header">Recent emails</div>
                <div class="card-body">
                    <div class="row small">
                        <div class="col-3"></strong>Date</strong></div>
                        <div class="col-9"></strong>Subject</strong></div>
                    </div>
                    <hr>
                    {% for item in emails %}
                        <div class="row small">
                            <div class="col-3">{{ item.send_date.strftime("%a %d %b %Y %H:%M:%S") }}</div>
                            <div class="col-9">
                                <a class="text-decoration-none" href="{{ url_for('admin.display_email', id=item.id, text='student match inspector', url=url_for('admin.match_student_view', id=attempt_id, text=text, url=url)) }}">{{ item.subject }}</a>
                            </div>
                        </div>
                    {% endfor %}
                </div>
            </div>
        {% endif %}
    </div>
</div>
{% if not sel.convert_to_submitter %}
    <div class="text-danger small">
        Conversion of this student is disabled.
        <a class="text-decoration-none" href="{{ url_for('admin.delete_match_record', attempt_id=attempt_id, selector_id=sel.id) }}">
            Delete...
        </a>
    </div>
{% endif %}
"""


# language=jinja2
_pclass = \
"""
{% set config = sel.config %}
{% set swatch_colour = config.project_class.make_CSS_style() %}
<div class="d-flex flex-row justify-content-start align-items-center gap-2">
    {{ small_swatch(swatch_colour) }}
    <span class="small">{{ config.name }}</span>
</div>
<div class="d-flex flex-row justify-content-start align-items-center gap-2 small">
    <i class="fa fa-user-circle"></i>
    <a class="text-decoration-none" href="mailto:{{ config.convenor_email }}">{{ config.convenor_name }}</a>
</div>
"""


# language=jinja2
_details = \
"""
<div class="text-primary small">
    {{ unformatted_label(sel.student.programme.short_label, tag='div') }}
</div>
<div class="mt-1 text-muted small">
    {{- unformatted_label(sel.academic_year_label(show_details=True)) -}} |
    {{ unformatted_label(sel.student.cohort_label) -}}
</div>
"""


# language=jinja2
_project = \
"""
{% macro truncate_name(name, maxlength=25) %}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{% endmacro %}
{% macro project_tag(r, show_period) %}
    {% set adjustable = false %}
    {% if r.selector.has_submission_list %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set has_issues = r.has_issues %}
    {% set supervisors = r.supervisor_roles %}
    <div>
        <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-light {% if has_issues %}bg-danger{% elif style %}bg-secondary{% else %}bg-info{% endif %} {% if adjustable %}dropdown-toggle{% endif %}"
                    {% if not has_issues and style %}style="{{ style }}"{% endif %}
                    {% if adjustable %}data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false"{% endif %}>
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {% if supervisors|length > 0 %}
                    {{ truncate_name(r.project.name) }} ({{ supervisors[0].last_name }})
                {% endif %}
            </a>
            {% if adjustable %}
                {% set list = r.selector.ordered_selections %}
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 small">
                    <div class="dropdown-header small">Quick reassignment</div>
                    {% for item in list %}
                        {% set disabled = false %}
                        {% set project = item.liveproject %}
                        {% if item.liveproject_id == r.project_id or not item.is_selectable %}{% set disabled = true %}{% endif %}
                        <a class="dropdown-item d-flex gap-2 small {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_project', id=r.id, pid=item.liveproject_id) }}"{% endif %}>
                           #{{ item.rank }}: {{ item.format_project()|safe }}
                           {% if project.generic or project.owner is none %}
                              (generic)
                           {% else %}
                              ({{ project.owner.user.name }})
                           {% endif %}
                           {% if r.original_project_id == item.liveproject_id %}
                              [automatch]
                           {% endif %}
                        </a>
                    {% endfor %}
                    <div role="separator" class="dropdown-divider"></div>
                    <a class="dropdown-item d-flex gap-2 small" href="{{ url_for('admin.reassign_supervisor_roles', rec_id=r.id, url=url_for('admin.match_student_view', id=r.matching_id)) }}">
                        Edit supervisor roles...
                    </a>                
                </div>
            {% endif %}
        </div>
        {% if r.project.generic %}
            <span class="badge bg-info">GENERIC</span>
        {% endif %}
        {% set outcome = r.hint_status %}
        {% if outcome is not none %}
            {% set satisfied, violated = outcome %}
            {% if satisfied|length > 0 %}
                <span class="badge bg-success">{%- for i in range(satisfied|length) -%}<i class="fas fa-check"></i>{%- endfor %} HINT</span>
            {% endif %}
            {% if violated|length > 0 %}
                <span class="badge bg-warning text-dark">{%- for i in range(violated|length) -%}<i class="fas fa-times"></i>{%- endfor %} HINT</span>
            {% endif %}
        {% endif %}
        {% set prog_status = r.project.satisfies_preferences(r.selector) %}
        {% if prog_status is not none %}
            {% if prog_status %}
                <span class="badge bg-success"><i class="fas fa-check"></i> PROG</span>
            {% else %}
                <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> PROG</span>
            {% endif %}
        {% endif %}
    </div>
{% endmacro %}
{% if recs|length == 1 %}
    {{ project_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for r in recs %}
        {{ project_tag(r, true) }}
    {% endfor %}
{% endif %}
{% for r in recs %}
    {# if both not valid and overassigned, should leave error message from is_valid intact due to short-circuit evaluation #}
    {% if not r.is_valid or r.has_issues %}
        <p></p>
        {% set errors = r.errors %}
        {% set warnings = r.warnings %}
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
            {% for item in errors %}
                {% if loop.index <= 10 %}
                    <div class="text-danger small">{{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="text-danger small">...</div>
                {% endif %}            
            {% endfor %}
        {% endif %}
        {% if warnings|length > 0 %}
            {% for item in warnings %}
                {% if loop.index <= 10 %}
                    <div class="text-warning small">Warning: {{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="text-warning small">Further warnings suppressed...</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_marker = \
"""
{% macro marker_tag(r, show_period) %}
    {% set markers = r.marker_roles %}
    {% for marker in markers %}
        <div class="dropdown match-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-dark bg-light dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}{{ marker.name }}
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                <div class="dropdown-header">Reassign marker</div>
                {% set assessor_list = r.project.assessor_list %}
                {% for fac in assessor_list %}
                    {% set disabled = false %}
                    {% if fac.id == marker.id %}{% set disabled = true %}{% endif %}
                    <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_marker', id=r.id, mid=fac.id) }}"{% endif %}>
                        {{ fac.user.name }}
                    </a>
                {% endfor %}
            </div>
        </div>
    {% else %}
        <span class="badge bg-light text-dark">None</span>
    {% endfor %}
{% endmacro %}
{% if recs|length == 1 %}
    {{ marker_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for r in recs %}
        {{ marker_tag(r, true) }}
    {% endfor %}
{% endif %}
"""


# language=jinja2
_rank = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="badge {% if r.hi_ranked %}bg-success{% elif r.lo_ranked %}bg-warning text-dark{% else %}bg-info{% endif %}">{{ r.rank }}</span>
    <span class="badge bg-primary">&delta; = {{ delta }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="badge {% if r.hi_ranked %}bg-success{% elif r.lo_ranked %}bg-warning text-dark{% else %}bg-info{% endif %}">#{{ r.submission_period }}: {{ r.rank }}</span>
    {% endfor %}
    <span class="badge bg-primary">&delta; = {{ delta }}</span>
{% endif %}
"""


# language=jinja2
_scores = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="badge bg-primary">{{ r.current_score|round(precision=2) }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="badge bg-secondary">#{{ r.submission_period }}: {{ r.current_score|round(precision=2) }}</span>
    {% endfor %}
    <span class="badge bg-primary">Total {{ total_score|round(precision=2) }}</span>
{% endif %}
"""


def student_view_data(selector_data, attempt_id, text=None, url=None):
    # selector_data is a list of ((lists of) MatchingRecord, delta-value, score-value) triples

    small_swatch = get_template_attribute("swatch.html", "small_swatch")
    medium_swatch = get_template_attribute("swatch.html", "medium_swatch")
    unformatted_label = get_template_attribute("labels.html", "unformatted_label")

    def get_emails(s: SelectingStudent):
        data: StudentData = s.student

        emails = db.session.query(EmailLog).filter(EmailLog.recipients.any(User.id == data.id)) \
            .order_by(EmailLog.send_date.desc()) \
            .limit(7).all()

        return emails

    data = [{'student': render_template_string(_student, sel=r[0].selector, attempt_id=attempt_id,
                                               emails=get_emails(r[0].selector),
                                               valid=all([not rc.has_issues for rc in r]), text=text, url=url,
                                               small_swatch=small_swatch, medium_swatch=medium_swatch),
             'pclass': render_template_string(_pclass, sel=r[0].selector, small_swatch=small_swatch),
             'details': render_template_string(_details, sel=r[0].selector, unformatted_label=unformatted_label),
             'project': render_template_string(_project, recs=r),
             'marker': render_template_string(_marker, recs=r),
             'rank': render_template_string(_rank, recs=r, delta=delta),
             'scores': render_template_string(_scores, recs=r, total_score=score)} for r, delta, score in selector_data]

    return data
