#
# Created by Junie on 25/02/2026.
#

from typing import List

from flask import render_template_string, get_template_attribute

from ...database import db
from ...models import FacultyBatchItem

# language=jinja2
_name = """
<div class="d-flex flex-column justify-content-start align-items-left gap-1">
    <div>{{ item.first_name }} {{ item.last_name }}</div>
    {% if item.CATS_supervision is not none or item.CATS_marking is not none or item.CATS_moderation is not none or item.CATS_presentation is not none %}
        <div>
            <div class="small fw-semibold">CATS limits</div>
            <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 mt-1 small">
                {% if item.CATS_supervision is not none %}
                    <span class="text-primary">S: {{ item.CATS_supervision }} CATS</span>
                {% endif %}
                {% if item.CATS_marking is not none %}
                    <span class="text-primary">Mk: {{ item.CATS_marking }} CATS</span>
                {% endif %}
                {% if item.CATS_moderation is not none %}
                    <span class="text-primary">Mo: {{ item.CATS_moderation }} CATS</span>
                {% endif %}
                {% if item.CATS_presentation is not none %}
                    <span class="text-primary">P: {{ item.CATS_presentation }} CATS</span>
                {% endif %}
            </div>
        </div>
    {% endif %}
    {% if item.existing_record is not none %}
        <span class="text-success small"><i class="fas fa-check-circle"></i> Matches {{ item.existing_record.user.name }}</span>
    {% endif %}
    {% if item.dont_convert %}
        <span class="text-danger small"><i class="fas fa-times"></i> Import disabled</span>
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
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_faculty_batch_item', item_id=item.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>

        {% if item.dont_convert %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.mark_faculty_batch_item_convert', item_id=item.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Allow import
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.mark_faculty_batch_item_dont_convert', item_id=item.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Disallow import
            </a>
        {% endif %}
    </div>
</div>
"""


def _element(item_id):
    item = db.session.query(FacultyBatchItem).filter_by(id=item_id).one()

    simple_label = get_template_attribute("labels.html", "simple_label")

    # compute which tenants from the parent batch are new for this user
    batch_tenants = list(item.parent.tenants)
    if item.existing_record is not None:
        existing_tenants = set(item.existing_record.user.tenants)
        new_tenants = [t for t in batch_tenants if t not in existing_tenants]
    else:
        new_tenants = batch_tenants

    return {
        "name": render_template_string(_name, item=item, new_tenants=new_tenants, simple_label=simple_label),
        "user": item.user_id,
        "email": item.email,
        "menu": render_template_string(_menu, item=item),
    }


def build_view_faculty_batch_data(items: List[FacultyBatchItem]):
    data = [_element(item.id) for item in items]

    return data
