#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import render_template_string, get_template_attribute

from ...database import db
from ...models import StudentBatchItem

# language=jinja2
_name = """
<div class="d-flex flex-column justify-content-start align-items-left gap-1">
    <div>{{ item.first_name }} {{ item.last_name }}</div>
    {% if item.registration_number is not none %}
        <span class="text-secondary small">Registration #{{ item.registration_number }}</span>
    {% endif %}
    {% if item.existing_record is not none %}
        <span class="text-success small"><i class="fas fa-check-circle"></i> Matches {{ item.existing_record.user.name }} {{ item.existing_record.cohort }}</span>
    {% endif %}
    {% if item.dont_convert %}
        <span class="text-danger small"><i class="fas fa-times"></i> Import disabled</span>
    {% endif %}
    {% if item.intermitting %}
        <div><span class="badge bg-danger">TWD</span></div>
    {% endif %}
    {% if new_tenants|length > 0 %}
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-1 mt-1">
            <span class="small text-muted">New tenants:</span>
            {% for t in new_tenants %}
                {{ simple_label(t.make_label()) }}
            {% endfor %}
        </div>
    {% endif %}
    {% set warnings = item.warnings %}
    {% set w_length = warnings|length %}
    {% if w_length == 1 %}
        <span class="text-warning small"><i class="fas fa-exclamation-circle"></i> 1 warning</span>
    {% elif w_length > 1 %}
        <span class="text-warning small"><i class="fas fa-exclamation-circle"></i> {{ w_length }} warnings</span>
    {% else %}
        {% if item.existing_record is none %}
            <div><span class="badge bg-success"><i class="fas fa-plus-circle"></i> New</span></div>
        {% else %}
            <span class="text-success small "><i class="fas fa-check-circle"></i> Safe to import</span>
        {% endif %}
    {% endif %}
</div>
{% if w_length > 0 %}
    <div class="mt-1 d-flex flex-column justify-content-start align-items-start">
        {% for w in warnings %}
            <span class="text-danger small">{{ w }}</span>
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_programme = """
{% if p is not none %}
    {{ simple_label(p.make_label()) }}
{% else %}
    <span class="badge bg-danger">Unknown</span>
{% endif %}
"""


# language=jinja2
_cohort = """
<div>
    {{ item.cohort }}
    {{ simple_label(item.academic_year_label()) }}
</div>
{% if item.foundation_year %}
    <span class="badge bg-info">Foundation year</span>
{% endif %}
{% if item.repeated_years is not none and item.repeated_years > 0 %}
    {% set pl = 's' %}{% if item.repeated_years == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge bg-primary">{{ item.repeated_years }} repeated year{{ pl }}</span>
{% endif %}
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_student_batch_item', item_id=item.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>

        {% if item.dont_convert %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.mark_student_batch_item_convert', item_id=item.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Allow import
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.mark_student_batch_item_dont_convert', item_id=item.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Disallow import
            </a>
        {% endif %}
    </div>
</div>
"""


def _element(item_id):
    item = db.session.query(StudentBatchItem).filter_by(id=item_id).one()

    simple_label = get_template_attribute("labels.html", "simple_label")

    # compute which tenants from the parent batch are new for this user
    batch_tenants = list(item.parent.tenants)
    if item.existing_record is not None:
        existing_tenants = set(item.existing_record.user.tenants)
        new_tenants = [t for t in batch_tenants if t not in existing_tenants]
    else:
        new_tenants = batch_tenants

    return {
        "name": render_template_string(
            _name, item=item, new_tenants=new_tenants, simple_label=simple_label
        ),
        "user": item.user_id,
        "email": item.email,
        "cohort": render_template_string(_cohort, item=item, simple_label=simple_label),
        "programme": render_template_string(
            _programme, p=item.programme, simple_label=simple_label
        ),
        "menu": render_template_string(_menu, item=item),
    }


def build_view_batch_data(items: List[StudentBatchItem]):
    data = [_element(item.id) for item in items]

    return data
