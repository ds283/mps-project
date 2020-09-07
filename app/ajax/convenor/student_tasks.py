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

from flask import render_template_string
from ...models import ConvenorStudentTask


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
        <a class="dropdown-item" href="{{ url_for('convenor.edit_student_task', tid=tk.id, url=return_url) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        {% set complete_action='complete' if not tk.complete else 'active' %}
        {% set complete_label='Complete' if not tk.complete else 'Not complete' %}
        {% set drop_action='drop' if not tk.dropped else 'undrop' %}
        {% set drop_label='Drop' if not tk.dropped else 'Restore' %}
        <a class="dropdown-item" href="{{ url_for('convenor.student_task_complete', tid=tk.id, action=complete_action) }}">
            <i class="fas fa-check fa-fw"></i> {{ complete_label }}
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.student_task_drop', tid=tk.id, action=drop_action) }}">
            <i class="fas fa-ban fa-fw"></i> {{ drop_label }}
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.delete_student_task', tid=tk.id, url=return_url) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def student_task_data(type, sid, return_url, tasks: List[ConvenorStudentTask]):
    data = [{'task': render_template_string(_task, tk=t),
             'due_date': t.due_date.strftime("%a %d %b %Y %H:%M") if t.due_date is not None else '<span class="badge badge-secondary">None</span>',
             'defer_date': t.defer_date.strftime("%a %d %b %Y %H:%M") if t.defer_date is not None else '<span class="badge badge-secondary">None</span>',
             'status': render_template_string(_status, available=t.is_available, overdue=t.is_overdue, tk=t),
             'menu': render_template_string(_menu, tk=t, type=type, sid=sid,
                                            return_url=return_url)} for t in tasks]

    return data
