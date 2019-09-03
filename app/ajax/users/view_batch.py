#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

from ...database import db
from ...models import StudentBatchItem
from ...cache import cache

from sqlalchemy.event import listens_for


_name = \
"""
<div>
    {{ item.first_name }} {{ item.last_name }}
    {% if item.exam_number is not none %}
        <span class="label label-primary">{{ item.exam_number }}</span>
    {% endif %}
    {% set warnings = item.warnings %}
    {% set w_length = warnings|length %}
    {% if w_length == 1 %}
        <span class="label label-warning">1 warning</span>
    {% elif w_length > 1 %}
        <span class="label label-warning">{{ w_length }} warnings</span>
    {% else %}
        {% if item.existing_record is none %}
            <span class="label label-success"><i class="fa fa-plus-circle"></i> New</span>
        {% else %}
            <span class="label label-success"><i class="fa fa-check"></i> Safe to import</span>
        {% endif %}
    {% endif %}
</div>
<div>
    {% if item.existing_record is not none %}
        <span class="label label-success"><i class="fa fa-check"></i> Matches {{ item.existing_record.user.name }} {{ item.existing_record.cohort }}</span>
    {% endif %}
    {% if item.intermitting %}
        <span class="label label-danger">INTERMITTING</span>
    {% endif %}
    {% if item.dont_convert %}
        <span class="label label-warning"><i class="fa fa-times"></i> Import disabled</span>
    {% endif %}
</div>
{% if w_length > 0 %}
    <div class="has-error">
        {% for w in warnings %}
            <p class="help-block">{{ w }}</p>
        {% endfor %}
    </div>
{% endif %}
"""


_programme = \
"""
{% if p is not none %}
    {{ p.make_label()|safe }}
{% else %}
    <span class="label label-danger">Unknown</span>
{% endif %}
"""


_cohort = \
"""
{{ item.cohort }}
{% if item.foundation_year %}
    <span class="label label-info">Foundation year</span>
{% endif %}
{% if item.repeated_years is not none and item.repeated_years > 0 %}
    {% set pl = 's' %}{% if item.repeated_years == 1 %}{% set pl = '' %}{% endif %}
    <span class="label label-primary">{{ item.repeated_years }} repeated year{{ pl }}</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('manage_users.edit_batch_item', item_id=item.id) }}">
                <i class="fa fa-pencil"></i> Edit...
            </a>
        </li>
        
        <li role="separator" class="divider"></li>

        {% if item.dont_convert %}
            <li>
                <a href="{{ url_for('manage_users.mark_batch_item_convert', item_id=item.id) }}">
                    <i class="fa fa-wrench"></i> Allow import
                </a>
            </li>
        {% else %}
            <li>
                <a href="{{ url_for('manage_users.mark_batch_item_dont_convert', item_id=item.id) }}">
                    <i class="fa fa-wrench"></i> Disallow import
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""


@cache.memoize()
def _element(item_id):
    item = db.session.query(StudentBatchItem).filter_by(id=item_id).one()

    return {'name': {'display': render_template_string(_name, item=item),
                     'sortvalue': item.last_name + item.first_name},
             'user': item.user_id,
             'email': item.email,
             'cohort': render_template_string(_cohort, item=item),
             'programme': render_template_string(_programme, p=item.programme),
             'menu': render_template_string(_menu, item=item)}


def _delete_StudentBatchItem_cache(item_id):
    cache.delete_memoized(_element, item_id)


@listens_for(StudentBatchItem, 'before_insert')
def _StudentBatchItem_insert_handler(mapping, connection, target):
    with db.session.no_autoflush:
        _delete_StudentBatchItem_cache(target.id)


@listens_for(StudentBatchItem, 'before_update')
def _StudentBatchItem_update_handler(mapping, connection, target):
    with db.session.no_autoflush:
        _delete_StudentBatchItem_cache(target.id)


@listens_for(StudentBatchItem, 'before_delete')
def _StudentBatchItem_delete_handler(mapping, connection, target):
    with db.session.no_autoflush:
        _delete_StudentBatchItem_cache(target.id)


def build_view_batch_data(items):
    data = [_element(i) for i in items]

    return jsonify(data)
