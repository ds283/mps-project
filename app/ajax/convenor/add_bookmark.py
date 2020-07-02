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


_project = \
"""
<a href="{{ url_for('faculty.live_project', pid=proj.id, url=url_for('convenor.selector_bookmarks', id=sel.id), text='selector bookmarks') }}">
    {{ proj.name }}
</a>
"""


_owner = \
"""
<a href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
{{ project.group.make_label()|safe }}
"""


_actions = \
"""
<div class="float-right">
    <a href="{{ url_for('convenor.create_student_bookmark', proj_id=project.id, sel_id=sel.id, url=url_for('convenor.selector_bookmarks', id=sel.id)) }}"
       class="btn btn-sm btn-secondary">
       Add bookmark
    </a>
</div>
"""


def add_student_bookmark(projects, sel):
    data = [{'project': render_template_string(_project, sel=sel, proj=project),
             'owner': {
                 'display': render_template_string(_owner, project=project),
                 'sortvalue': project.owner.user.last_name + project.owner.user.first_name
             },
             'actions': render_template_string(_actions, sel=sel, project=project)} for project in projects]

    return jsonify(data)
