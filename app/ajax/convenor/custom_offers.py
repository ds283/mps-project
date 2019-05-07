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
<a href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.student_custom_offers', sel_id=sel.id), text='selector custom offers') }}">
    {{ proj.name }}
</a>
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
                    <i class="fa fa-check"></i> Decline
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


def project_offer_data(items):
    data = [{'student': render_template_string(_student, sel=item.selector),
             'timestamp': {
                 'display': item.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': item.creation_timestamp.timestamp()
             },
             'status': {
                 'display': render_template_string(_status, offer=item),
                 'sortvalue': '{x}_{y}'.format(x=item.status,
                                               y=item.last_edit_time.timestamp() if item.last_edit_time is not None else 0)
             },
             'menu': render_template_string(_menu, offer=item)} for item in items]

    return jsonify(data)


def student_offer_data(items):
    data = [{'project': render_template_string(_project, sel=item.selector, proj=item.liveproject),
             'timestamp': {
                 'display': item.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': item.creation_timestamp.timestamp()
             },
             'status': {
                 'display': render_template_string(_status, offer=item),
                 'sortvalue': '{x}_{y}'.format(x=item.status,
                                               y=item.last_edit_time.timestamp() if item.last_edit_time is not None else 0)
             },
             'menu': render_template_string(_menu, offer=item)} for item in items]

    return jsonify(data)
