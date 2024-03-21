#
# Created by David Seery on 12/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.live_project', pid=project.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
            View web page
        </a>
    </div>
</div>
"""

# language=jinja2
_pclass = """
{% set style = config.project_class.make_CSS_style() %}
<a class="badge text-decoration-none text-nohover-dark bg-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ config.convenor_email }}">
    {{ config.project_class.abbreviation }} ({{ config.convenor_name }})
</a>
"""


# language=jinja2
_name = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=p.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
    {{ p.name }}
</a>
"""


# language=jinja2
_affiliation = """
{% set ns = namespace(affiliation=false) %}
{% if project.group %}
    {{ simple_label(project.group.make_label()) }}
    {% set ns.affiliation = true %}
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ simple_label(tag.make_label(truncate(tag.name))) }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""


# language=jinja2
_metadata = """
<div>
    {{ project_selection_data(p) }}
</div>
<div class="mt-1">
    {{ project_metadata(p) }}
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_pclass_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_pclass)


def _build_affiliation_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_affiliation)


def _build_metadata_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_metadata)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def pastproject_data(projects):
    simple_label = get_template_attribute("labels.html", "simple_label")
    truncate = get_template_attribute("macros.html", "truncate")

    project_metadata = get_template_attribute("faculty/macros.html", "project_metadata")
    project_selection_data = get_template_attribute("faculty/macros.html", "project_selection_data")

    name_templ: Template = _build_name_templ()
    pclass_templ: Template = _build_pclass_templ()
    affiliation_templ: Template = _build_affiliation_templ()
    metadata_templ: Template = _build_metadata_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "year": "{c}".format(c=p.config.year),
            "name": render_template(name_templ, p=p),
            "pclass": render_template(pclass_templ, config=p.config),
            "group": render_template(affiliation_templ, project=p, simple_label=simple_label, truncate=truncate),
            "metadata": render_template(metadata_templ, p=p, project_selection_data=project_selection_data, project_metadata=project_metadata),
            "students": '<i class="fas fa-ban"></i> Not yet implemented',
            "menu": render_template(menu_templ, project=p),
        }
        for p in projects
    ]

    return jsonify(data)
