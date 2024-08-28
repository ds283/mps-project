#
# Created by David Seery on 05/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Optional, Tuple

from flask import jsonify, get_template_attribute, render_template, current_app
from jinja2 import Template, Environment

from .match_view_student import get_match_student_emails
from ....models import MatchingRecord, SelectingStudent, StudentData, User, ProjectClassConfig, MatchingAttempt

# language=jinja2
_student = """
<div>
    <a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
</div>
{{ student_offcanvas(sel, emails, none) }}
"""


# language=jinja2
_pclass = """
{% set config = sel.config %}
{% set swatch_colour = config.project_class.make_CSS_style() %}
<div class="d-flex flex-row justify-content-start align-items-center gap-2">
    {{ small_swatch(swatch_colour) }}
    <span class="small">{{ config.name }}</span>
</div>
<div class="d-flex flex-row justify-content-start align-items-center gap-2 small">
    <i class="fas fa-user-circle"></i>
    <a class="text-decoration-none" href="mailto:{{ config.convenor_email }}">{{ config.convenor_name }}</a>
</div>
"""


# language=jinja2
_record_delta = """
{% if rec is not none %}
    <div class="d-flex flex-column gap-2 justify-content-start align-items-start">
        {% if 'all' in changes or 'project' in changes or 'supervisor' in changes %}
            <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
                <span class="small fw-semibold text-secondary">PROJECT AND SUPERVISION</span>
                {{ project_tag(rec, config.number_submissions > 1, 1, none, false) }}
            </div>
        {% else %}
            <div class="d-flex flex-column gap-1 justify-content-start align-items-start"><span class="small fw-semibold text-secondary"><s>PROJECT MATCH</s></span></div>
        {% endif %}
        {% if 'all' in changes or 'marker' in changes %}
            <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
                <span class="small fw-semibold text-secondary">MARKING ASSIGNMENTS</span>
                {{ student_marker_tag(rec, false) }}
            </div>
        {% else %}
            <div class="d-flex flex-column gap-1 justify-content-start align-items-start"><span class="small fw-semibold text-secondary"><s>MARKING MATCH</s></span></div>
        {% endif %}
    </div>
{% else %}
    <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
        <span class="text-danger small fw-semibold"><s>NOT PRESENT</s></span>
    </div>
{% endif %}
"""

# language=jinja2
_rank = """
{% if rec is not none %}
    {% if 'all' in changes or 'project' in changes %}
        <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
            <div class="{% if rec.hi_ranked %}text-success fw-semibold{% elif rec.lo_ranked %}text-danger{% else %}text-primary{% endif %}">{{ rec.total_rank }}</div>
            {% if rec.alternative %}<div class="small text-muted"><i class="fas fa-info-circle"></i> Alternative</div>{% endif %}
            <div class="text-secondary small">&delta; = {{ rec.delta }}</div>
        </div>
    {% else %}
        <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
            <span class="text-secondary"><i class="fas fa-ban"></i></span>
        </div>
    {% endif %}
{% else %}
    <div class="d-flex flex-column gap-1 justify-content-start align-items-start">
        <span class="text-danger"><i class="fas fa-ban"></i></span>
    </div>
{% endif %}
"""



# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if l is not none and r is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.replace_matching_record', src_id=l.id, dest_id=r.id) }}">
                <i class="fas fa-chevron-circle-right fa-fw"></i> Replace left to right
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.replace_matching_record', src_id=r.id, dest_id=l.id) }}">
                <i class="fas fa-chevron-circle-left fa-fw"></i> Replace right to left
            </a>
        {% elif l is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.insert_matching_record', src_id=l.id, attempt_id=r_attempt_id) }}">
                <i class="fas fa-chevron-circle-right fa-fw"></i> Copy to right
            </a>
        {% elif r is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.insert_matching_record', src_id=r.id, attempt_id=l_attempt_id) }}">
                <i class="fas fa-chevron-circle-left fa-fw"></i> Copy to left
            </a>
        {% endif %}
    </div>
</div>
"""


def _build_student_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_student)


def _build_pclass_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_pclass)


def _build_rank_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_rank)

def _build_record_delta_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_record_delta)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


RecordDeltaType = Tuple[Optional[MatchingRecord], Optional[MatchingRecord], List[str]]
RecordDeltaListType = List[RecordDeltaType]


def compare_match_data(records: RecordDeltaListType, left_attempt: MatchingAttempt, right_attempt: MatchingAttempt):
    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    student_offcanvas = get_template_attribute("admin/matching/student_offcanvas.html", "student_offcanvas")
    project_tag = get_template_attribute("admin/matching/project_tag.html", "project_tag")
    student_marker_tag = get_template_attribute("admin/matching/marker_tag.html", "student_marker_tag")

    student_templ: Template = _build_student_templ()
    pclass_templ: Template = _build_pclass_templ()
    record_delta_templ: Template = _build_record_delta_templ()
    rank_templ: Template = _build_rank_templ()
    menu_templ: Template = _build_menu_templ()

    def get_selecting_student(pair: RecordDeltaType) -> Optional[SelectingStudent]:
        if pair[0] is not None:
            return pair[0].selector

        if pair[1] is not None:
            return pair[1].selector

        return None

    def build_render_data(pair: RecordDeltaType) -> Optional[dict]:
        l: MatchingRecord = pair[0]
        r: MatchingRecord = pair[1]
        sel: SelectingStudent = get_selecting_student(pair)

        if sel is None:
            return None

        changes = pair[2]
        if changes is None:
            return None

        config: ProjectClassConfig = sel.config
        sd: StudentData = sel.student
        user: User = sd.user

        sort_value = user.last_name + user.first_name

        return {
            "student": {
                "display": render_template(
                    student_templ,
                    sel=sel,
                    emails=get_match_student_emails(sel),
                    student_offcanvas=student_offcanvas
                ),
                "sortvalue": sort_value
            },
            "pclass": render_template(pclass_templ, sel=sel, small_swatch=small_swatch),
            "record1": render_template(record_delta_templ, rec=l, config=config, changes=changes, project_tag=project_tag,
                                       student_marker_tag=student_marker_tag),
            "rank1": {
                "display": render_template(rank_templ, rec=l, changes=changes),
                "sortvalue": l.delta if l is not None else -1
            },
            "record2": render_template(record_delta_templ, rec=r, config=config, changes=changes, project_tag=project_tag,
                                       student_marker_tag=student_marker_tag),
            "rank2": {
                "display": render_template(rank_templ, rec=r, changes=changes),
                "sortvalue": r.delta if r is not None else -1
            },
            "menu": render_template(menu_templ, l=l, r=r, l_attempt_id=left_attempt.id, r_attempt_id=right_attempt.id),
        }

    data = [build_render_data(pair) for pair in records]
    data_stripped = [d for d in data if d is not None]
    return jsonify(data_stripped)
