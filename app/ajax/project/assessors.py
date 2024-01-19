#
# Created by David Seery on 10/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Environment, Template

from ...cache import cache

# language=jinja2
_affiliations = """
{% for group in f.affiliations %}
    {{ simple_label(group.make_label()) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
"""

# language=jinja2
_status = """
{% if proj.is_assessor(f.id) %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Attached</span>
{% else %}
    <span class="badge bg-secondary"><i class-"fas fa-times"></i> Not attached</span>
{% endif %}
"""

# language=jinja2
_enrolments = """
{% set ns = namespace(count=0) %}
{% for e in f.enrollments %}
    {% if e.pclass.publish and (e.pclass.uses_marker or e.pclass.uses_presentations) %}
        {% set ns.count = ns.count + 1 %}
        {% if e.marker_state == e.MARKER_ENROLLED or e.presentations_state == e.PRESENTATIONS_ENROLLED %}
            {{ simple_label(e.pclass.make_label(e.pclass.abbreviation), prefix='<i class="fas fa-check"></i>') }}
        {% elif e.marker_state == e.MARKER_SABBATICAL and e.presentations_state == e.PRESENTATIONS_SABBATICAL %}
            <{% if not disabled %}a{% else %}span{% endif%} class="badge bg-secondary" {% if not disabled %}href="{{ url_for('manage_users.edit_enrollment', id=e.id, url=url) }}"{% endif %}><i class="fas fa-times"></i> {{ e.pclass.abbreviation }} (sabbat)<{% if not disabled %}/a{% else %}/span{% endif %}>
        {% elif (e.marker_state == e.MARKER_EXEMPT and e.presentations_state == e.PRESENTATIONS_SABBATICAL) or
                (e.marker_state == e.MARKER_SABBATICAL and e.presentations_state == e.PRESENTATIONS_EXEMPT) or
                (e.marker_state == e.MARKER_EXEMPT and e.presentations_state == e.PRESENTATIONS_EXEMPT)
        %}
            <{% if not disabled %}a{% else %}span{% endif%} class="badge bg-secondary" {% if not disabled %}href="{{ url_for('manage_users.edit_enrollment', id=e.id, url=url) }}"{% endif %}><i class="fas fa-times"></i> {{ e.pclass.abbreviation }} (exempt)<{% if not disabled %}/a{% else %}/span{% endif %}>
        {% else %}
            <{% if not disabled %}a{% else %}span{% endif%} class="badge bg-danger" {% if not disabled %}href="{{ url_for('manage_users.edit_enrollment', id=e.id, url=url) }}"{% endif %}><i class="fas fa-exclamation-triangle"></i> {{ e.pclass.abbreviation }} (unknown)<{% if not disabled %}/a{% else %}/span{% endif %}>
        {% endif %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


# language=jinja2
_attached = """
<span class="badge bg-secondary">{{ f.number_assessor }}</span>
"""


@cache.memoize()
def build_attached_template() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_attached)


@cache.memoize()
def build_affiliations_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_affiliations)


@cache.memoize()
def build_status_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_status)


@cache.memoize()
def build_enrolments_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_enrolments)



def build_assessor_data(faculty, proj, menu, pclass_id=None, url=None, disable_enrollment_links=False):
    simple_label = get_template_attribute("labels.html", "simple_label")

    # pre-compile template string
    attached_templ: Template = build_attached_template()
    affiliations_templ: Template = build_affiliations_templ()
    status_templ: Template = build_status_templ()
    enrolments_templ: Template = build_enrolments_templ()

    env: Environment = current_app.jinja_env
    menu_templ: Template = env.from_string(menu)

    data = [
        {
            "name": {"display": f.user.name, "sortstring": f.user.last_name + f.user.first_name},
            "attached": render_template(attached_templ, f=f),
            "groups": render_template(affiliations_templ, f=f, simple_label=simple_label),
            "status": render_template(status_templ, f=f, proj=proj),
            "enrolments": render_template(enrolments_templ, f=f, url=url, disabled=disable_enrollment_links, simple_label=simple_label),
            "menu": render_template(menu_templ, f=f, proj=proj, pclass_id=pclass_id),
        }
        for f in faculty
    ]

    return jsonify(data)
