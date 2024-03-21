#
# Created by David Seery on 2019-05-06.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_student = """
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
<div>
    {% if sel.has_submitted %}
        <span class="badge bg-success">Submitted</span>
    {% else %}
        <span class="badge bg-secondary">Not submitted</span>
    {% endif %}
</div>
{% if offer is defined and offer.comment is not none and offer.comment|length > 0 %}
    <div class="mt-2 text-muted small">
        <span tabindex="0" data-bs-toggle="popover" title="Offer notes" data-bs-container="body" data-bs-trigger="focus" data-bs-content="{{ offer.comment|truncate(600) }}">Notes <i class="ms-1 fas fa-chevron-right"></i></span>
    </div>
{% endif %}
"""


# language=jinja2
_project = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.selector_custom_offers', sel_id=sel.id), text='selector custom offers') }}">
    {{ proj.name }}
</a>
{% if offer is defined and offer.comment is not none and offer.comment|length > 0 %}
    <div class="mt-2 text-muted small">
        <span tabindex="0" data-bs-toggle="popover" title="Offer notes" data-bs-container="body" data-bs-trigger="focus" data-bs-content="{{ offer.comment|truncate(600) }}">Notes <i class="ms-1 fas fa-chevron-right"></i></span>
    </div>
{% endif %}
"""


# language=jinja2
_owner = """
{% if not project.generic and project.owner is not none %}
    <a class="link-primary text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
    {% if project.group %}{{ simple_label(project.group.make_label()) }}{% endif %}
{% else %}
    <span class="badge bg-info">Generic</span>
{% endif %}
"""


# language=jinja2
_timestamp = """
<div class="small text-secondary">
    Created by <i class="fas fa-user-circle"></i>
    <a class="text-decoration-none link-primary" href="mailto:{{ offer.created_by.email }}">{{ offer.created_by.name }}</a>
    {% if offer.creation_timestamp is not none %}
        {{ offer.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% else %}
        <span class="badge bg-secondary">Unknown</span>
    {% endif %}
    {% if offer.last_edited_by is not none %}
        <div class="mt-1 text-muted">
            Last edited by <i class="fas fa-user-circle"></i>
            <a class="text-decoration-none link-primary" href="mailto:{{ offer.last_edited_by.email }}">{{ offer.last_edited_by.name }}</a>
            {% if offer.last_edit_timestamp is not none %}
                {{ offer.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
            {% endif %}
        </div>
    {% endif %}
</div>
"""


# language=jinja2
_status = """
{% set status = offer.status %}
{% if status == offer.OFFERED %}
    <div class="text-primary"><i class="fas fa-history"></i> Offered</div>
{% elif status == offer.DECLINED %}
    <div class="text-danger"><i class="fas fa-times-circle"></i> Declined</div>
{% elif status == offer.ACCEPTED %}
    <div class="text-success"><i class="fas fa-check-circle"></i> Accepted</div>
{% else %}
    <span class="badge bg-danger">Unknown status</span>
{% endif %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% set status = offer.status %}
        {% if status == offer.OFFERED %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.accept_custom_offer', offer_id=offer.id) }}">
                <i class="fas fa-check fa-fw"></i> Accept
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.decline_custom_offer', offer_id=offer.id) }}">
                <i class="fas fa-times fa-fw"></i> Decline
            </a>
        {% elif status == offer.DECLINED %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.accept_custom_offer', offer_id=offer.id) }}">
                <i class="fas fa-check fa-fw"></i> Accept
            </a>
        {% elif status == offer.ACCEPTED %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.decline_custom_offer', offer_id=offer.id) }}">
                <i class="fas fa-check fa-fw"></i> Decline
            </a>
        {% endif %}        
    
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_custom_offer', offer_id=offer.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</dic>
"""


# language=jinja2
_selector_offers = """
{% for offer in record.custom_offers_accepted %}
    <div class="text-success"><i class="fas fa-check-circle"></i> <span class="fw-semibold">Accepted:</span> {{ offer.liveproject.name }} ({{offer.liveproject.owner.user.last_name }})</div>
{% endfor %}
{% for offer in record.custom_offers_pending %}
    <div class="text-primary"><i class="fas fa-history"></i> <span class="fw-semibold">Offer:</span> {{ offer.liveproject.name }} ({{ offer.liveproject.owner.user.last_name }})</div>
{% endfor %}
{% for offer in record.custom_offers_declined %}
    <div class="text-danger"><i class="fas fa-time-circle"></i> <span class="fw-semibold">Declined:</span> {{ offer.liveproject.name }} ({{ offer.liveproject.owner.user.last_name }})</div>
{% endfor %}
"""


# language=jinja2
_project_offers = """
{% for offer in record.custom_offers_accepted %}
    <div class="text-success"><i class="fas fa-check-circle"></i> <span class="fw-semibold">Accepted:</span> {{ offer.selector.student.user.name }}</div>
{% endfor %}
{% for offer in record.custom_offers_pending %}
    <div class="text-primary"><i class="fas fa-history"></i> <span class="fw-semibold">Offer:</span> {{ offer.selector.student.user.name }}</div>
{% endfor %}
{% for offer in record.custom_offers_declined %}
    <div class="text-danger"><i class="fas fa-time-circle"></i> <span class="fw-semibold">Declined:</span> {{ offer.selector.student.user.name }}</div>
{% endfor %}
"""


# language=jinja2
_sel_actions = """
<div class="d-flex flex-row justify-content-end">
    <a href="{{ url_for('convenor.create_new_offer', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.selector_custom_offers', sel_id=sel.id)) }}"
       class="btn btn-sm btn-outline-primary">
       <i class="fas fa-plus"></i> Create offer
    </a>
</div>
"""


# language=jinja2
_proj_actions = """
<div class="d-flex flex-row justify-content-end">
    <a href="{{ url_for('convenor.create_new_offer', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.project_custom_offers', proj_id=project.id)) }}"
       class="btn btn-sm btn-outline-primary">
       <i class="fas fa-plus"></i> Create offer
    </a>
</div>
"""


def project_offer_data(items):
    data = [
        {
            "student": {
                "display": render_template_string(_student, offer=item, sel=item.selector),
                "sortvalue": item.selector.student.user.last_name + item.selector.student.user.first_name,
            },
            "timestamp": {
                "display": render_template_string(_timestamp, offer=item),
                "timestamp": item.creation_timestamp.timestamp(),
            },
            "status": {
                "display": render_template_string(_status, offer=item),
                "sortvalue": "{x}_{y}".format(x=item.status, y=item.last_edit_timestamp.timestamp() if item.last_edit_timestamp is not None else 0),
            },
            "menu": render_template_string(_menu, offer=item),
        }
        for item in items
    ]

    return jsonify(data)


def student_offer_data(items):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "project": render_template_string(_project, offer=item, sel=item.selector, proj=item.liveproject),
            "owner": {
                "display": render_template_string(_owner, project=item.liveproject, simple_label=simple_label),
                "sortvalue": "Generic"
                if item.liveproject.generic or item.liveproject.owner is None
                else item.liveproject.owner.user.last_name + item.liveproject.owner.user.first_name,
            },
            "timestamp": {
                "display": render_template_string(_timestamp, offer=item),
                "timestamp": item.creation_timestamp.timestamp(),
            },
            "status": {
                "display": render_template_string(_status, offer=item),
                "sortvalue": "{x}_{y}".format(x=item.status, y=item.last_edit_timestamp.timestamp() if item.last_edit_timestamp is not None else 0),
            },
            "menu": render_template_string(_menu, offer=item),
        }
        for item in items
    ]

    return jsonify(data)


def new_project_offer_selectors(selectors, project):
    data = [
        {
            "student": {
                "display": render_template_string(_student, sel=sel),
                "sortvalue": sel.student.user.last_name + sel.student.user.first_name,
            },
            "offers": render_template_string(_selector_offers, record=sel),
            "actions": render_template_string(_proj_actions, sel=sel, project=project),
        }
        for sel in selectors
    ]

    return jsonify(data)


def new_student_offer_projects(projects, sel):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "project": render_template_string(_project, sel=sel, proj=project),
            "owner": {
                "display": render_template_string(_owner, project=project, simple_label=simple_label),
                "sortvalue": "Generic" if project.generic or project.owner is None else project.owner.user.last_name + project.owner.user.first_name,
            },
            "offers": render_template_string(_project_offers, record=project),
            "actions": render_template_string(_sel_actions, sel=sel, project=project),
        }
        for project in projects
    ]

    return jsonify(data)
