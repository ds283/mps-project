#
# Created by David Seery on 12/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_project_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('faculty.live_project', pid=project.id) }}">
                View web page
            </a>
        </li>
    </ul>
</div>
"""


def pastproject_data(projects):

    data = [{'year': '{c}'.format(c=p.config.year),
             'name': '<a href="{url}"><strong>{name}</strong></a>'.format(name=p.name,
                                                                          url=url_for('faculty.live_project',
                                                                                      pid=p.id)),
             'pclass': '<span class="label label-default">{name}</span>'.format(name=p.config.project_class.name),
             'group': '<span class="label label-success">{name}</span>'.format(name=p.group.abbreviation),
             'pageviews': '{c}'.format(c=p.page_views),
             'bookmarks': '{c}'.format(c=p.bookmarks.count()),
             'students': 'Not yet implemented',
             'menu': render_template_string(_project_menu, project=p)} for p in projects]

    return jsonify(data)
