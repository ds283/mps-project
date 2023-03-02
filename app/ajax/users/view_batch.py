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
from ...models import StudentBatchItem, StudentBatch, User, StudentData
from ...cache import cache

from sqlalchemy.event import listens_for


# language=jinja2
_name = \
"""
<div>
    {{ item.first_name }} {{ item.last_name }}
    {% if item.registration_number is not none %}
        <span class="badge bg-info text-dark">Registration #{{ item.registration_number }}</span>
    {% endif %}
    {% set warnings = item.warnings %}
    {% set w_length = warnings|length %}
    {% if w_length == 1 %}
        <span class="badge bg-warning text-dark">1 warning</span>
    {% elif w_length > 1 %}
        <span class="badge bg-warning text-dark">{{ w_length }} warnings</span>
    {% else %}
        {% if item.existing_record is none %}
            <span class="badge bg-success"><i class="fas fa-plus-circle"></i> New</span>
        {% else %}
            <span class="badge bg-success"><i class="fas fa-check"></i> Safe to import</span>
        {% endif %}
    {% endif %}
</div>
<div class="mt-1">
    {% if item.existing_record is not none %}
        <span class="badge bg-success"><i class="fas fa-check"></i> Matches {{ item.existing_record.user.name }} {{ item.existing_record.cohort }}</span>
    {% endif %}
    {% if item.intermitting %}
        <span class="badge bg-danger">TWD</span>
    {% endif %}
    {% if item.dont_convert %}
        <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Import disabled</span>
    {% endif %}
</div>
{% if w_length > 0 %}
    <div class="error-block">
        {% for w in warnings %}
            <div class="error-message">{{ w }}</div>
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_programme = \
"""
{% if p is not none %}
    {{ p.make_label()|safe }}
{% else %}
    <span class="badge bg-danger">Unknown</span>
{% endif %}
"""


# language=jinja2
_cohort = \
"""
<div>
    {{ item.cohort }}
    {{ item.academic_year_label()|safe }}
</div>
{% if item.foundation_year %}
    <span class="badge bg-info text-dark">Foundation year</span>
{% endif %}
{% if item.repeated_years is not none and item.repeated_years > 0 %}
    {% set pl = 's' %}{% if item.repeated_years == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge bg-primary">{{ item.repeated_years }} repeated year{{ pl }}</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_batch_item', item_id=item.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>

        {% if item.dont_convert %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.mark_batch_item_convert', item_id=item.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Allow import
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.mark_batch_item_dont_convert', item_id=item.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Disallow import
            </a>
        {% endif %}
    </div>
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


@listens_for(StudentBatch, 'before_update')
def _StudentBatch_update_handler(mapping, connection, target):
    with db.session.no_autoflush:
        for rec in target.items:
            _delete_StudentBatchItem_cache(rec.id)


@listens_for(User, 'before_update')
def _User_update_handler(mapping, connection, target):
    with db.session.no_autoflush:
        if target.student_data is not None:
            for rec in target.student_data.counterparts:
                _delete_StudentBatchItem_cache(rec.id)


@listens_for(StudentData, 'before_update')
def _StudentData_update_handler(mapping, connection, target):
    with db.session.no_autoflush:
        for rec in target.counterparts:
            _delete_StudentBatchItem_cache(rec.id)


def build_view_batch_data(items):
    data = [_element(i) for i in items]

    return jsonify(data)
