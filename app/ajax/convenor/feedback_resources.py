#
# Created by David Seery on 27/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, current_app, request
from jinja2 import Template, Environment

from ...database import db
from ...models import FeedbackAsset, FeedbackTemplate, FeedbackRecipe, ProjectClass
from ...tools.ServerSideProcessing import ServerSideSQLHandler


# language=jinja2
_asset_label = """
<div class="fw-semibold">{{ fa.label }}</div>
{% set submitted = fa.asset %}
{% if submitted is not none %}
    {% if submitted.small_thumbnail is not none and not submitted.small_thumbnail.lost %}
        <div class="mt-1">
            <img src="{{ url_for('documents.serve_thumbnail', asset_type='SubmittedAsset', asset_id=submitted.id, size='small') }}"
                 class="img-thumbnail" style="max-width:60px; max-height:60px;" alt="Preview">
        </div>
    {% else %}
        <div class="small text-muted mt-1"><i class="fas fa-image fa-fw"></i> No preview</div>
    {% endif %}
{% endif %}
"""

# language=jinja2
_asset_metadata = """
{% if fa.created_by is not none %}
    <div class="small text-muted">
        <i class="fas fa-user fa-fw me-1"></i>Created by {{ fa.created_by.name }}
        {% if fa.creation_timestamp is not none %}
            &mdash; {{ fa.creation_timestamp.strftime('%d %b %Y %H:%M') }}
        {% endif %}
    </div>
{% endif %}
{% if fa.last_edited_by is not none %}
    <div class="small text-muted mt-1">
        <i class="fas fa-edit fa-fw me-1"></i>Last edited by {{ fa.last_edited_by.name }}
        {% if fa.last_edit_timestamp is not none %}
            &mdash; {{ fa.last_edit_timestamp.strftime('%d %b %Y %H:%M') }}
        {% endif %}
    </div>
{% elif fa.created_by is not none %}
    <div class="small text-muted mt-1"><i class="fas fa-edit fa-fw me-1"></i>Not yet edited</div>
{% endif %}
"""

# language=jinja2
_asset_description = """
{% if fa.description %}
    <span class="small">{{ fa.description }}</span>
{% else %}
    <span class="small text-muted">No description</span>
{% endif %}
"""

# language=jinja2
_asset_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        <a class="dropdown-item" href="{{ url_for('convenor.edit_feedback_asset', asset_id=fa.id, url=return_url, text=return_text) }}">
            <i class="fas fa-edit fa-fw"></i> Edit
        </a>
        <a class="dropdown-item text-danger" href="{{ url_for('convenor.delete_feedback_asset', asset_id=fa.id, url=return_url, text=return_text) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""

# language=jinja2
_template_label = """
<div class="fw-semibold">{{ ft.label }}</div>
"""

# language=jinja2
_template_metadata = """
{% if ft.created_by is not none %}
    <div class="small text-muted">
        <i class="fas fa-user fa-fw me-1"></i>Created by {{ ft.created_by.name }}
        {% if ft.creation_timestamp is not none %}
            &mdash; {{ ft.creation_timestamp.strftime('%d %b %Y %H:%M') }}
        {% endif %}
    </div>
{% endif %}
{% if ft.last_edited_by is not none %}
    <div class="small text-muted mt-1">
        <i class="fas fa-edit fa-fw me-1"></i>Last edited by {{ ft.last_edited_by.name }}
        {% if ft.last_edit_timestamp is not none %}
            &mdash; {{ ft.last_edit_timestamp.strftime('%d %b %Y %H:%M') }}
        {% endif %}
    </div>
{% elif ft.created_by is not none %}
    <div class="small text-muted mt-1"><i class="fas fa-edit fa-fw me-1"></i>Not yet edited</div>
{% endif %}
"""

# language=jinja2
_template_description_tags = """
{% if ft.description %}
    <div class="small mb-1">{{ ft.description }}</div>
{% endif %}
{% set tag_list = ft.tags.all() %}
{% if tag_list %}
    <div class="d-flex flex-row flex-wrap gap-1">
        {% for tag in tag_list %}
            {{ tag.make_label()|safe }}
        {% endfor %}
    </div>
{% else %}
    <span class="small text-muted">No tags</span>
{% endif %}
"""

# language=jinja2
_template_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        <a class="dropdown-item" href="{{ url_for('convenor.edit_feedback_template', template_id=ft.id, url=return_url, text=return_text) }}">
            <i class="fas fa-edit fa-fw"></i> Edit
        </a>
        <a class="dropdown-item text-danger" href="{{ url_for('convenor.delete_feedback_template', template_id=ft.id, url=return_url, text=return_text) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""

# language=jinja2
_recipe_label = """
<div class="fw-semibold">{{ fr.label }}</div>
"""

# language=jinja2
_recipe_metadata = """
{% if fr.created_by is not none %}
    <div class="small text-muted">
        <i class="fas fa-user fa-fw me-1"></i>Created by {{ fr.created_by.name }}
        {% if fr.creation_timestamp is not none %}
            &mdash; {{ fr.creation_timestamp.strftime('%d %b %Y %H:%M') }}
        {% endif %}
    </div>
{% endif %}
{% if fr.last_edited_by is not none %}
    <div class="small text-muted mt-1">
        <i class="fas fa-edit fa-fw me-1"></i>Last edited by {{ fr.last_edited_by.name }}
        {% if fr.last_edit_timestamp is not none %}
            &mdash; {{ fr.last_edit_timestamp.strftime('%d %b %Y %H:%M') }}
        {% endif %}
    </div>
{% elif fr.created_by is not none %}
    <div class="small text-muted mt-1"><i class="fas fa-edit fa-fw me-1"></i>Not yet edited</div>
{% endif %}
"""

# language=jinja2
_recipe_assets = """
{% if fr.template is not none %}
    <div class="small mb-1"><i class="fas fa-file-code fa-fw me-1"></i><strong>Template:</strong> {{ fr.template.label }}</div>
{% else %}
    <div class="small mb-1 text-muted"><i class="fas fa-file-code fa-fw me-1"></i>No template selected</div>
{% endif %}
{% set asset_count = fr.asset_list.count() %}
{% if asset_count > 0 %}
    <div class="small"><i class="fas fa-images fa-fw me-1"></i>{{ asset_count }} asset{{ 's' if asset_count != 1 }}</div>
{% else %}
    <div class="small text-muted"><i class="fas fa-images fa-fw me-1"></i>No assets</div>
{% endif %}
"""

# language=jinja2
_recipe_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        <a class="dropdown-item" href="{{ url_for('convenor.edit_feedback_recipe', recipe_id=fr.id, url=return_url, text=return_text) }}">
            <i class="fas fa-edit fa-fw"></i> Edit
        </a>
        <a class="dropdown-item text-danger" href="{{ url_for('convenor.delete_feedback_recipe', recipe_id=fr.id, url=return_url, text=return_text) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def _build_templ(src: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(src)


def feedback_assets_data(pclass: ProjectClass):
    base_query = db.session.query(FeedbackAsset).filter(FeedbackAsset.pclass_id == pclass.id)

    label_col = {
        "search": FeedbackAsset.label,
        "order": FeedbackAsset.label,
        "search_collation": "utf8_general_ci",
    }
    metadata_col = {}
    description_col = {
        "search": FeedbackAsset.description,
        "order": FeedbackAsset.description,
        "search_collation": "utf8_general_ci",
    }
    menu_col = {}

    columns = {
        "label": label_col,
        "metadata": metadata_col,
        "description": description_col,
        "menu": menu_col,
    }

    from flask import url_for

    return_url = url_for("convenor.feedback_resources", pclass_id=pclass.id)
    return_text = "Feedback resources"

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        label_templ = _build_templ(_asset_label)
        metadata_templ = _build_templ(_asset_metadata)
        description_templ = _build_templ(_asset_description)
        menu_templ = _build_templ(_asset_menu)

        def row_formatter(rows):
            return [
                {
                    "label": render_template(label_templ, fa=fa),
                    "metadata": render_template(metadata_templ, fa=fa),
                    "description": render_template(description_templ, fa=fa),
                    "menu": render_template(menu_templ, fa=fa, return_url=return_url, return_text=return_text),
                }
                for fa in rows
            ]

        return handler.build_payload(row_formatter)


def feedback_templates_data(pclass: ProjectClass):
    base_query = db.session.query(FeedbackTemplate).filter(FeedbackTemplate.pclass_id == pclass.id)

    label_col = {
        "search": FeedbackTemplate.label,
        "order": FeedbackTemplate.label,
        "search_collation": "utf8_general_ci",
    }
    metadata_col = {}
    description_tags_col = {
        "search": FeedbackTemplate.description,
        "order": FeedbackTemplate.description,
        "search_collation": "utf8_general_ci",
    }
    menu_col = {}

    columns = {
        "label": label_col,
        "metadata": metadata_col,
        "description_tags": description_tags_col,
        "menu": menu_col,
    }

    from flask import url_for

    return_url = url_for("convenor.feedback_resources", pclass_id=pclass.id)
    return_text = "Feedback resources"

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        label_templ = _build_templ(_template_label)
        metadata_templ = _build_templ(_template_metadata)
        desc_tags_templ = _build_templ(_template_description_tags)
        menu_templ = _build_templ(_template_menu)

        def row_formatter(rows):
            return [
                {
                    "label": render_template(label_templ, ft=ft),
                    "metadata": render_template(metadata_templ, ft=ft),
                    "description_tags": render_template(desc_tags_templ, ft=ft),
                    "menu": render_template(menu_templ, ft=ft, return_url=return_url, return_text=return_text),
                }
                for ft in rows
            ]

        return handler.build_payload(row_formatter)


def feedback_recipes_data(pclass: ProjectClass):
    base_query = db.session.query(FeedbackRecipe).filter(FeedbackRecipe.pclass_id == pclass.id)

    label_col = {
        "search": FeedbackRecipe.label,
        "order": FeedbackRecipe.label,
        "search_collation": "utf8_general_ci",
    }
    metadata_col = {}
    assets_col = {}
    menu_col = {}

    columns = {
        "label": label_col,
        "metadata": metadata_col,
        "assets": assets_col,
        "menu": menu_col,
    }

    from flask import url_for

    return_url = url_for("convenor.feedback_resources", pclass_id=pclass.id)
    return_text = "Feedback resources"

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        label_templ = _build_templ(_recipe_label)
        metadata_templ = _build_templ(_recipe_metadata)
        assets_templ = _build_templ(_recipe_assets)
        menu_templ = _build_templ(_recipe_menu)

        def row_formatter(rows):
            return [
                {
                    "label": render_template(label_templ, fr=fr),
                    "metadata": render_template(metadata_templ, fr=fr),
                    "assets": render_template(assets_templ, fr=fr),
                    "menu": render_template(menu_templ, fr=fr, return_url=return_url, return_text=return_text),
                }
                for fr in rows
            ]

        return handler.build_payload(row_formatter)
