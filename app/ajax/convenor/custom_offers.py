#
# Created by David Seery on 2019-05-06.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_student = \
"""
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
<div>
    {% if sel.has_submitted %}
        <span class="badge bg-success">Submitted</span>
    {% else %}
        <span class="badge bg-secondary">Not submitted</span>
    {% endif %}
</div>
"""


# language=jinja2
_project = \
"""
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.selector_custom_offers', sel_id=sel.id), text='selector custom offers') }}">
    {{ proj.name }}
</a>
"""


# language=jinja2
_owner = \
"""
<a class="text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
{{ project.group.make_label()|safe }}
"""


# language=jinja2
_status = \
"""
{% set status = offer.status %}
{% if status == offer.OFFERED %}
    <span class="badge bg-primary">Offered</span>
{% elif status == offer.DECLINED %}
    <span class="badge bg-danger">Declined</span>
{% elif status == offer.ACCEPTED %}
    <span class="badge bg-success">Accepted</span>
{% else %}
    <span class="badge bg-danger">Unknown status</span>
{% endif %}
"""

# language=jinja2
_menu = \
"""
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
_selector_offers = \
"""
{% for offer in record.custom_offers_accepted %}
    <span class="badge bg-success">Accepted: {{ offer.liveproject.name }} ({{offer.liveproject.owner.user.last_name }})</span>
{% endfor %}
{% for offer in record.custom_offers_pending %}
    <span class="badge bg-primary">Offer: {{ offer.liveproject.name }} ({{ offer.liveproject.owner.user.last_name }})</span>
{% endfor %}
{% for offer in record.custom_offers_declined %}
    <span class="badge bg-danger">Declined: {{ offer.liveproject.name }} ({{ offer.liveproject.owner.user.last_name }})</span>
{% endfor %}
"""


# language=jinja2
_project_offers = \
"""
{% for offer in record.custom_offers_accepted %}
    <span class="badge bg-success">Accepted: {{ offer.selector.student.user.name }}</span>
{% endfor %}
{% for offer in record.custom_offers_pending %}
    <span class="badge bg-primary">Offer: {{ offer.selector.student.user.name }}</span>
{% endfor %}
{% for offer in record.custom_offers_declined %}
    <span class="badge bg-danger">Declined: {{ offer.selector.student.user.name }}</span>
{% endfor %}
"""


# language=jinja2
_sel_actions = \
"""
<div class="float-end">
    <a href="{{ url_for('convenor.create_new_offer', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.selector_custom_offers', sel_id=sel.id)) }}"
       class="btn btn-sm btn-secondary">
       Make offer
    </a>
</div>
"""


# language=jinja2
_proj_actions = \
"""
<div class="float-end">
    <a href="{{ url_for('convenor.create_new_offer', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.project_custom_offers', proj_id=project.id)) }}"
       class="btn btn-sm btn-secondary">
       Make offer
    </a>
</div>
"""


def project_offer_data(items):
    data = [{'student': {
                 'display': render_template_string(_student, sel=item.selector),
                 'sortvalue': item.selector.student.user.last_name + item.selector.student.user.first_name
             },
             'timestamp': {
                 'display': item.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': item.creation_timestamp.timestamp()
             },
             'status': {
                 'display': render_template_string(_status, offer=item),
                 'sortvalue': '{x}_{y}'.format(x=item.status,
                                               y=item.last_edit_timestamp.timestamp() if item.last_edit_timestamp is not None else 0)
             },
             'menu': render_template_string(_menu, offer=item)} for item in items]

    return jsonify(data)


def student_offer_data(items):
    data = [{'project': render_template_string(_project, sel=item.selector, proj=item.liveproject),
             'owner': {
                 'display': render_template_string(_owner, project=item.liveproject),
                 'sortvalue': item.liveproject.owner.user.last_name + item.liveproject.owner.user.first_name
             },
             'timestamp': {
                 'display': item.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': item.creation_timestamp.timestamp()
             },
             'status': {
                 'display': render_template_string(_status, offer=item),
                 'sortvalue': '{x}_{y}'.format(x=item.status,
                                               y=item.last_edit_timestamp.timestamp() if item.last_edit_timestamp is not None else 0)
             },
             'menu': render_template_string(_menu, offer=item)} for item in items]

    return jsonify(data)


def project_offer_selectors(selectors, project):
    data = [{'student': {
                 'display': render_template_string(_student, sel=sel),
                 'sortvalue': sel.student.user.last_name + sel.student.user.first_name
            },
            'offers': render_template_string(_selector_offers, record=sel),
            'actions': render_template_string(_proj_actions, sel=sel, project=project)} for sel in selectors]

    return jsonify(data)


def student_offer_projects(projects, sel):
    data = [{'project': render_template_string(_project, sel=sel, proj=project),
             'owner': {
                 'display': render_template_string(_owner, project=project),
                 'sortvalue': project.owner.user.last_name + project.owner.user.first_name
             },
             'offers': render_template_string(_project_offers, record=project),
             'actions': render_template_string(_sel_actions, sel=sel, project=project)} for project in projects]

    return jsonify(data)
