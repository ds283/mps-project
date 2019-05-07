#
# Created by David Seery on 2019-05-06.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_student = \
"""
<a href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
<div>
    {% if sel.has_submitted %}
        <span class="label label-success">Submitted</span>
    {% else %}
        <span class="label label-default">Not submitted</span>
    {% endif %}
</div>
"""


_project = \
"""
<a href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.selector_custom_offers', sel_id=sel.id), text='selector custom offers') }}">
    {{ proj.name }}
</a>
"""


_owner = \
"""
<a href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
{{ project.group.make_label()|safe }}
"""


_status = \
"""
{% set status = offer.status %}
{% if status == offer.OFFERED %}
    <span class="label label-primary">Offered</span>
{% elif status == offer.DECLINED %}
    <span class="label label-danger">Declined</span>
{% elif status == offer.ACCEPTED %}
    <span class="label label-success">Accepted</span>
{% else %}
    <span class="label label-danger">Unknown status</span>
{% endif %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle table-button" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% set status = offer.status %}
        {% if status == offer.OFFERED and not offer.selector.has_submitted %}
            <li>
                <a href="{{ url_for('convenor.accept_custom_offer', offer_id=offer.id) }}">
                    <i class="fa fa-check"></i> Accept
                </a>
            <li>
            <li>
                <a href="{{ url_for('convenor.decline_custom_offer', offer_id=offer.id) }}">
                    <i class="fa fa-times"></i> Decline
                </a>
            <li>
        {% elif status == offer.DECLINED and not offer.selector.has_submitted %}
            <li>
                <a href="{{ url_for('convenor.accept_custom_offer', offer_id=offer.id) }}">
                    <i class="fa fa-check"></i> Accept
                </a>
            <li>
        {% elif status == offer.ACCEPTED %}
            <li>
                <a href="{{ url_for('convenor.decline_custom_offer', offer_id=offer.id) }}">
                    <i class="fa fa-check"></i> Decline
                </a>
            <li>
        {% endif %}        
    
        <li>
            <a href="{{ url_for('convenor.delete_custom_offer', offer_id=offer.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</dic>
"""


_selector_offers = \
"""
{% for offer in record.custom_offers_accepted %}
    <span class="label label-success">Accepted: {{ offer.liveproject.name }} ({{offer.liveproject.owner.user.last_name }})</span>
{% endfor %}
{% for offer in record.custom_offers_pending %}
    <span class="label label-primary">Offer: {{ offer.liveproject.name }} ({{ offer.liveproject.owner.user.last_name }})</span>
{% endfor %}
{% for offer in record.custom_offers_declined %}
    <span class="label label-danger">Declined: {{ offer.liveproject.name }} ({{ offer.liveproject.owner.user.last_name }})</span>
{% endfor %}
"""


_project_offers = \
"""
{% for offer in record.custom_offers_accepted %}
    <span class="label label-success">Accepted: {{ offer.selector.student.user.name }}</span>
{% endfor %}
{% for offer in record.custom_offers_pending %}
    <span class="label label-primary">Offer: {{ offer.selector.student.user.name }}</span>
{% endfor %}
{% for offer in record.custom_offers_declined %}
    <span class="label label-danger">Declined: {{ offer.selector.student.user.name }}</span>
{% endfor %}
"""


_sel_actions = \
"""
<div class="pull-right">
    <a href="{{ url_for('convenor.create_new_offer', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.selector_custom_offers', sel_id=sel.id)) }}"
       class="btn btn-sm btn-default">
       Make offer
    </a>
</div>
"""


_proj_actions = \
"""
<div class="pull-right">
    <a href="{{ url_for('convenor.create_new_offer', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.project_custom_offers', proj_id=project.id)) }}"
       class="btn btn-sm btn-default">
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
