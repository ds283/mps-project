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
{% if state == 'FAILURE' %}
    <span class="label label-danger">FAILURE</span>
{% elif state == 'PENDING' %}
    <span class="label label-info">PENDING</span>
{% elif state == 'SUCCESS' %}
    <span class="label label-success">SUCCESS</span>
{% else %}
    <span class="label label-default">{{ state }}</span>
{% endif %}
"""


def background_task_data(tasks):

    data = []
    celery = current_app.extensions['celery']

    for task in tasks:
        handle = AsyncResult(task.id, app=celery)
        data.append({ 'id': task.id,
                      'owner': '<a href="mailto:{em}">{nm}</a>'.format(nm=task.owner.build_name(),
                                                                       em=task.owner.email) if task.owner is not None
                            else '<span class="label label-default">Nobody</span>',
                      'name': task.name,
                      'description': task.description,
                      'start_at': task.start_date.strftime("%a %d %b %Y %H:%M:%S"),
                      'complete': '<span class="label label-success">Complete</a>' if task.complete
                            else '<span class="label label-info">Pending</a>',
                      'task': '<unknown>',
                      'backend': render_template_string(_state, state=handle.state)
                    })

    return jsonify(data)
