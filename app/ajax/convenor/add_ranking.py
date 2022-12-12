#
# Created by David Seery on 06/04/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_project = \
"""
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.selector_choices', id=sel.id), text='selector bookmarks') }}">
    {{ proj.name }}
</a>
"""


# language=jinja2
_owner = \
"""
<a class="text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
{% if project.group %}{{ project.group.make_label()|safe }}{% endif %}
"""


# language=jinja2
_actions = \
"""
<div class="float-end">
    <a href="{{ url_for('convenor.create_student_ranking', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.selector_choices', id=sel.id)) }}"
       class="btn btn-sm btn-secondary">
       Add ranking
    </a>
</div>
"""


def add_student_ranking(projects, sel):
    data = [{'project': render_template_string(_project, sel=sel, proj=project),
             'owner': {
                 'display': render_template_string(_owner, project=project),
                 'sortvalue': project.owner.user.last_name + project.owner.user.first_name
             },
             'actions': render_template_string(_actions, sel=sel, project=project)} for project in projects]

    return jsonify(data)
