#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string, get_template_attribute

# language=jinja2
_projects = \
"""
{% for p in config.project_confirmations_outstanding(f) %}
    {% set offerable = p.is_offerable %}
    <div class="outstanding-confirm-group">
        <div class="outstanding-confirm-row">
            {{ loop.index }} &ndash;
            <a class="text-decoration-none" href="{{ url_for('faculty.project_preview', id=p.id, pclass=pclass.id, show_selector=0, text=text, url=url) }}">
                {{ p.name }}
            </a>
            {% if not offerable %}
                <i class="fas fa-exclamation-triangle text-danger"></i>
            {% endif %}
        </div>
        <div class="outstanding-confirm-row">
            {% if offerable %}
                {% if p.active %}
                    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
                {% else %}
                    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
                {% endif %}
                {% set enrollment = f.get_enrollment_record(pclass.id) %}
                {% if enrollment %}
                    {{ simple_label(enrollment.supervisor_label) }}
                {% endif %}
            {% else %}
                <span class="badge bg-danger">Not available</span>
            {% endif %}
            {% set d = p.get_description(pclass.id) %}
            {% if d %}
                {% if d.has_new_comments(current_user) %}
                    <span class="badge bg-warning text-dark">New comments</span>
                {% endif %}
                {% set state = d.workflow_state %}
                {% set not_confirmed = d.requires_confirmation and not d.confirmed %}
                {% if not_confirmed %}
                    <div class="dropdown" style="display: inline-block;">
                        <a class="badge text-decoration-none text-nohover-light bg-secondary dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">Approval: Not confirmed</a>
                        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.confirm_description', config_id=config.id, did=d.id) }}"><i class="fas fa-check"></i> Confirm</a>
                        </div>
                    </div>
                {% else %}
                    {% if state == d.WORKFLOW_APPROVAL_VALIDATED %}
                        <span class="badge bg-success"><i class="fas fa-check"></i> Approved</span>
                    {% elif state == d.WORKFLOW_APPROVAL_QUEUED %}
                        <span class="badge bg-warning text-dark">Approval: Queued</span>
                    {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
                        <span class="badge bg-info">Approval: In progress</span>
                    {% else %}
                        <span class="badge bg-danger">Unknown approval state</span>
                    {% endif %}
                    {% if current_user.has_role('project_approver') and d.validated_by %}
                        <span class="badge bg-info">Signed-off: {{ d.validated_by.name }}</span>
                        {% if d.validated_timestamp %}
                            <span class="badge bg-info">{{ d.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
                        {% endif %}
                    {% endif %}
                {% endif %}
            {% endif %}
        </div>
    </div>
{% else %}
    <span class="badge bg-danger">No project confirmations outstanding</span>
{% endfor %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.force_confirm', id=config.id, uid=f.id) }}">
            <i class="fas fa-check fa-fw"></i> Force confirm all
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.confirmation_reminder_individual', fac_id=f.id, config_id=config.id) }}">
            <i class="fas fa-envelope fa-fw"></i> Send reminder
        </a>
    </div>
</div>
"""


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ u.email }}">{{ u.name }}</a>
<div>
    {% if config.no_explicit_confirm(f) %}
        <span class="badge bg-danger">NO RESPONSE</span>
    {% endif %}
    {% if u.last_active is not none %}
        <span class="badge bg-info">Last seen at {{ u.last_active.strftime("%Y-%m-%d %H:%M:%S") }}</span>
    {% else %}
        <span class="badge bg-warning text-dark">No last seen time</span>
    {% endif %}
</div>
<div class="mt-1">
    {{ simple_label(f.projects_offered_label(pclass)) }}
    {{ simple_label(f.projects_unofferable_label) }}
</div>
"""


def outstanding_confirm_data(config, url=None, text=None):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'name': {'display': render_template_string(_name, u=f.user, f=f, config=config,
                                                        pclass=config.project_class, simple_label=simple_label),
                      'sortstring': f.user.last_name + f.user.first_name},
             'email': '<a class="text-decoration-none" href="mailto:{em}">{em}</a>'.format(em=f.user.email),
             'projects': render_template_string(_projects, f=f, config=config, pclass=config.project_class,
                                                url=url, text=text, simple_label=simple_label),
             'menu': render_template_string(_menu, config=config, f=f)} for f in config.faculty_waiting_confirmation]

    return jsonify(data)
