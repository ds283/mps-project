#
# Created by David Seery on 28/08/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import render_template_string, jsonify
from ...models import ConvenorStudentTask

from datetime import datetime


_task = \
"""
{{ tk.description }}
{% if tk.blocking %}
    <span class="badge badge-warning"><i class="fas fa-hand-paper"></i> Blocking</span>
{% endif %}
"""


_status = \
"""
{% if tk.dropped %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Dropped</span>
{% elif tk.complete %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Complete</span>
{% elif overdue %}
    <span class="badge badge-danger"><i class="fas fa-exclamation-triangle"></i> Overdue</span>
{% elif available %}
    <span class="badge badge-info"><i class="fas fa-thumbs-up"></i> Available</span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-ban"></i> Not yet available</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('convenor.edit_student_task', tid=tk.id, type=type, sid=sid, url=url_for('convenor.student_tasks', type=type, sid=sid)) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit task...
        </a>
    </div>
</div>
"""


def student_task_data(type, sid, tasks: List[ConvenorStudentTask]):
    now = datetime.now()

    data = [{'task': render_template_string(_task, tk=t),
             'due_date': t.due_date.strftime("%a %d %b %Y %H:%M") if t.due_date is not None else 'None',
             'defer_date': t.defer_date.strftime("%a %d %b %Y %H:%M") if t.defer_date is not None else 'None',
             'status': render_template_string(_status,
                                              available=t.defer_date < now if t.defer_date is not None else True,
                                              overdue=t.due_date < now if t.due_date is not None else True,
                                              tk=t),
             'menu': render_template_string(_menu, tk=t, type=type, sid=sid)} for t in tasks]

    return data
