#
# Created by David Seery on 06/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, current_app, jsonify

from celery.result import AsyncResult

_state = \
"""
{% if state == 0 %}
    <span class="label label-info">PENDING</span>
{% elif state == 1 %}
    <span class="label label-info">RUNNING</span>
{% elif state == 2 %}
    <span class="label label-success">SUCCESS</span>
{% else %}
    <span class="label label-danger">FAILED</span>
{% endif %}
"""


def background_task_data(tasks):

    data = []

    for task in tasks:
        data.append({ 'id': task.id,
                      'owner': '<a href="mailto:{em}">{nm}</a>'.format(nm=task.owner.build_name(),
                                                                       em=task.owner.email) if task.owner is not None
                            else '<span class="label label-default">Nobody</span>',
                      'name': task.name,
                      'description': task.description,
                      'start_at': task.start_date.strftime("%a %d %b %Y %H:%M:%S"),
                      'status': render_template_string(_state, state=task.status),
                      'progress': '{c}%'.format(c=task.progress),
                      'message': task.message,
                      'shown': 'Yes' if task.shown else 'No',
                      'dismissed': 'Yes' if task.dismissed else 'No'
                    })

    return jsonify(data)
