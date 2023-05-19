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
from ...models import ConvenorTask


# language=jinja2
_task = \
"""
{{ tk.description }}
{% if tk.blocking %}
    <span class="badge bg-warning text-dark"><i class="fas fa-hand-paper"></i> Blocking</span>
{% endif %}
{% if tk.notes and tk.notes|length > 0 %}
    <div class="text-muted">{{ tk.notes|truncate(150) }}</div>
{% endif %}
"""


# language=jinja2
_status = \
"""
{% if tk.dropped %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Dropped</span>
{% elif tk.complete %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Complete</span>
{% elif overdue %}
    <span class="badge bg-danger"><i class="fas fa-exclamation-triangle"></i> Overdue</span>
{% elif available %}
    <span class="badge bg-info"><i class="fas fa-thumbs-up"></i> Available</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-ban"></i> Not yet available</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_student_task', tid=tk.id, url=return_url) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        {% set complete_action='complete' if not tk.complete else 'active' %}
        {% set complete_label='Complete' if not tk.complete else 'Not complete' %}
        {% set drop_action='drop' if not tk.dropped else 'undrop' %}
        {% set drop_label='Drop' if not tk.dropped else 'Restore' %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.mark_task_complete', tid=tk.id, action=complete_action) }}">
            <i class="fas fa-check fa-fw"></i> {{ complete_label }}
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.mark_task_dropped', tid=tk.id, action=drop_action) }}">
            <i class="fas fa-ban fa-fw"></i> {{ drop_label }}
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_task', tid=tk.id, url=return_url) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def student_task_data(type, sid, return_url, tasks: List[ConvenorTask]):
    data = [{'task': render_template_string(_task, tk=t),
             'due_date': t.due_date.strftime("%a %d %b %Y %H:%M") if t.due_date is not None else '<span class="badge bg-secondary">None</span>',
             'defer_date': t.defer_date.strftime("%a %d %b %Y %H:%M") if t.defer_date is not None else '<span class="badge bg-secondary">None</span>',
             'status': render_template_string(_status, available=t.is_available, overdue=t.is_overdue, tk=t),
             'menu': render_template_string(_menu, tk=t, type=type, sid=sid,
                                            return_url=return_url)} for t in tasks]

    return data
