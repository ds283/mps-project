#
# Created by David Seery on 09/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string

from ...models import ProjectClassConfig, User, FacultyData

# language=jinja2
_projects = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="badge bg-secondary">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="badge bg-info text-dark">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="badge bg-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="badge bg-warning text-dark">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="badge bg-danger">{{ label }} late</span>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <span class="badge bg-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro project_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    {% set enable_engagement = (r.submission_period <= r.owner.config.submission_period) and (r.owner.config.submitter_lifecycle < r.owner.config.SUBMITTER_LIFECYCLE_READY_ROLLOVER) %}
    {% set colour = "bg-secondary" %}
    {% if enable_engagement %}
        {% if r.student_engaged %}
            {% set colour = "bg-success" %}
        {% else %}
            {% set colour = "bg-warning" %}
        {% endif %}
    {% endif %}
    <div>
        <div class="dropdown assignment-label">
            <a class="badge text-decoration-none text-nohover-light {{ colour }} btn-table-block dropdown-toggle" data-bs-toggle="dropdown" href="" role="button" aria-haspopup="true" aria-expanded="false">
                {% if enable_engagement %}
                    {% if r.student_engaged %}
                        <i class="fas fa-check"></i>
                    {% else %}
                        <i class="fas fa-times"></i>
                    {% endif %}
                {% endif %}
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {{ r.owner.student.user.name }}
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                {% set disabled = not pclass.publish %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}"{% if not disabled %}href="{{ url_for('convenor.view_feedback', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}"{% endif %}>
                    <i class="fas fa-comments fa-fw"></i> Show feedback
                </a>
                
                {% if not disabled and r.owner.published and enable_engagement %}
                    {% if not r.student_engaged %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.mark_started', id=r.id) }}">
                            <i class="fas fa-check fa-fw"></i> Mark as started
                        </a>
                    {% else %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.mark_waiting', id=r.id) }}">
                            <i class="fas fa-times fa-fw"></i> Mark as waiting
                        </a>
                    {% endif %}
                {% endif %}
                
                {% set no_reassign = r.period.is_feedback_open or r.student_engaged %}
                <div role="separator" class="dropdown-divider"></div>
                {% if no_reassign %}
                    <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-exclamation-triangle fa-fw"></i> Can't reassign</a>
                {% else %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.manual_assign', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}">
                        <i class="fas fa-folder fa-fw"></i> Manually reassign
                    </a>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.deassign_project', id=r.id) }}"><i class="fas fa-times fa-fw"></i> Remove assignment</a>
                {% endif %}
            </div>
        </div>
        {{ feedback_state_tag(r, r.supervisor_feedback_state, 'Feedback') }}
        {{ feedback_state_tag(r, r.supervisor_response_state, 'Response') }}
    </div>
{% endmacro %}
{% if recs|length >= 1 %}
    <div class="d-flex flex-row justify-content-start gap-2"></div>
        {% for rec in recs %}
            {{ project_tag(rec, config.submissions > 1) }}
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


# language=jinja2
_marking = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_YET %}
        {# <span class="badge bg-secondary">{{ label }} not yet required</span> #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="badge bg-info text-dark">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="badge bg-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="badge bg-warning text-dark">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="badge bg-danger">{{ label }} late</span>
    {% elif state == obj.FEEDBACK_NOT_REQUIRED %}
    {% else %}
        <span class="badge bg-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% macro marker_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    <div>
        <div class="dropdown assignment-label">
            <a class="badge text-decoration-none text-nohover-light bg-secondary btn-table-block dropdown-toggle" href="" role="button" aria-haspopup="true" aria-expanded="false" data-bs-toggle="dropdown">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {{ r.owner.student.user.name }}
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                {% set disabled = not pclass.publish %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.view_feedback', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}"{% endif %}>
                    <i class="fas fa-comments fa-fw"></i> Show feedback
                </a>
                
                {% set no_reassign = r.period.is_feedback_open %}
                {% if no_reassign %}
                    <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-exclamation-triangle fa-fw"></i> Can't reassign</a>
                {% else %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.manual_assign', id=r.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}">
                        <i class="fas fa-folder fa-fw"></i> Manually reassign
                    </a>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.deassign_marker', id=r.id) }}"><i class="fas fa-times fa-fw"></i> Remove assignment</a>
                {% endif %}
            </div>
        </div>
        {{ feedback_state_tag(r, r.marker_feedback_state, 'Feedback') }}
    </div>
{% endmacro %}
{% if recs|length >= 1 %}
    <div class="d-flex flex-row justify-content-start gap-2"></div>
        {% for rec in recs %}
            {{ marker_tag(rec, config.submissions > 1) }}
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


# language=jinja2
_presentations = \
"""
{% macro feedback_state_tag(obj, state, label) %}
    {% if state == obj.FEEDBACK_NOT_REQUIRED or state == obj.FEEDBACK_NOT_YET %}
        {# empty #}
    {% elif state == obj.FEEDBACK_WAITING %}
        <span class="badge bg-info text-dark">{{ label }} to do</span>
    {% elif state == obj.FEEDBACK_SUBMITTED %}
        <span class="badge bg-success">{{ label }} submitted</span>        
    {% elif state == obj.FEEDBACK_ENTERED %}
        <span class="badge bg-warning text-dark">{{ label }} in progress</span>        
    {% elif state == obj.FEEDBACK_LATE %}
        <span class="badge bg-danger">{{ label }} late</span>
    {% else %}
        <span class="badge bg-danger">{{ label }} error &ndash; unknown state</span>
    {% endif %}        
{% endmacro %}
{% if slots|length >= 1 %}
    {% for slot in slots %}
        <div {% if loop.index < loop.length %}style="padding-bottom: 10px;"{% endif %}>
            <div class="dropdown assignment-label">
                <a class="badge text-decoration-none text-nohover-light bg-info text-dark btn-table-block dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                    {{ slot.short_date_as_string }}
                    {{ slot.session_type_string }}
                    {{ slot.room_full_name }}
                </a>
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                    {% for rec in slot.talks %}
                        {% set pclass = rec.owner.config.project_class %}
                        {% set disabled = not pclass.publish %}
                        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('convenor.view_feedback', id=rec.id, text='workload view', url=url_for('convenor.faculty_workload', id=pclass.id)) }}"{% endif %}>
                            <i class="fas fa-comments fa-fw"></i>  Show feedback for {{ rec.owner.student.user.last_name }}
                        </a>
                    {% endfor %}
                </div>
            </div>
            {% set state = slot.feedback_state(f.id) %}
            {{ feedback_state_tag(slot, state, 'Feedback') }}
            {% if state > slot.FEEDBACK_NOT_YET and state < slot.FEEDBACK_SUBMITTED %}
                {% set numbers = slot.feedback_number(f.id) %}
                {% if numbers is not none %}
                    {% set submitted, total = numbers %}
                    <span class="badge bg-warning text-dark">{{ submitted }}/{{ total }} submitted</span>
                {% endif %}
            {% endif %}
        </div>
    {% endfor %}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


# language=jinja2
_workload = \
"""
{% if config.uses_supervisor %}
    <span class="badge bg-info text-dark">S {{ CATS_sup }}</span>
{% endif %}
{% if config.uses_marker %}
    <span class="badge bg-info text-dark">M {{ CATS_mark }}</span>
{% endif %}
{% if config.uses_presentations %}
    <span class="badge bg-info text-dark">P {{ CATS_pres }}</span>
{% endif %}
<span class="badge bg-primary">Total {{ CATS_sup+CATS_mark+CATS_pres }}</span>
"""


def faculty_workload_data(config: ProjectClassConfig, faculty):
    data = []

    count = 0

    u: User
    d: FacultyData
    for u, d in faculty:
        count += 1

        CATS_sup, CATS_mark, CATS_pres = d.CATS_assignment(config)
        projects = d.supervisor_assignments(config_id=config.id).all()
        marking = d.marker_assignments(config_id=config.id).all()
        presentations = d.presentation_assignments(config_id=config.id).all()

        data.append({'name': '<a class="text-decoration-none" '
                             'href="mailto:{email}">{name}</a>'.format(email=u.email, name=u.name),
                     'projects': render_template_string(_projects, f=d, config=config, recs=projects),
                     'marking': render_template_string(_marking, f=d, config=config, recs=marking),
                     'presentations': render_template_string(_presentations, f=d, config=config, slots=presentations),
                     'workload': render_template_string(_workload, CATS_sup=CATS_sup, CATS_mark=CATS_mark,
                                                        CATS_pres=CATS_pres, f=d, config=config)})

    return data
