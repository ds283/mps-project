#
# Created by David Seery on 06/04/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_project = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.selector_choices', id=sel.id), text='selector bookmarks') }}">
    {{ proj.name }}
</a>
"""


# language=jinja2
_owner = """
{% if not project.generic and project.owner is not none %}
    <a class="text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
    {% if project.group %}{{ simple_label(project.group.make_label()) }}{% endif %}
{% else %}
    <span class="badge bg-info">Generic</span>
{% endif %}
"""


# language=jinja2
_actions = """
<div class="float-end">
    <a href="{{ url_for('convenor.create_student_ranking', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.selector_choices', id=sel.id)) }}"
       class="btn btn-sm btn-secondary">
       Add ranking
    </a>
</div>
"""


def add_student_ranking(projects, sel):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "project": render_template_string(_project, sel=sel, proj=project),
            "owner": {
                "display": render_template_string(_owner, project=project, simple_label=simple_label),
                "sortvalue": project.owner.user.last_name + project.owner.user.first_name,
            },
            "actions": render_template_string(_actions, sel=sel, project=project),
        }
        for project in projects
    ]

    return jsonify(data)
