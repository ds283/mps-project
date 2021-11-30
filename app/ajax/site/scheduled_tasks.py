#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_scheduled_menu_template = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-o border-0 dropdown-menu-end">
            <a class="dropdown-item d-flex gap-2" href="{% if task.interval_id %}{{ url_for('admin.edit_interval_task', id=task.id) }}{% elif task.crontab_id %}{{ url_for('admin.edit_crontab_task', id=task.id) }}{% else %}#{% endif %}">
                <i class="fas fa-cogs fa-fw"></i> Edit task
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.delete_scheduled_task', id=task.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
            {% if task.enabled %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_scheduled_task', id=task.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_scheduled_task', id=task.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% endif %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.launch_scheduled_task', id=task.id) }}">
                <i class="fas fa-running fa-fw"></i> Run now...
            </a>
    </div>
</div>
"""


# language=jinja2
_active = \
"""
{% if t.enabled %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_name = \
"""
{{ t.name }}
<div>
    {% if t.queue == 'priority' %}
        <span class="badge bg-danger">PRIORITY</span>
    {% else %}
        <span class="badge bg-secondary">{{ t.queue|upper }}</span>
    {% endif %}
</div>
"""


def _format_schedule(task):

    if task.interval is not None:
        data = task.interval
        return '{d} {i}'.format(d=data.every,
                                i=data.period[:-1] if data.every == 1 else data.period)

    elif task.crontab is not None:
        data = task.crontab
        return 'm({m}) h({h}) wd({wd}) mo({mo}) mon({mon})'.format(
            m=data.minute, h=data.hour, wd=data.day_of_week,
            mo=data.day_of_month, mon=data.month_of_year)

    return '<span class="badge bg-danger">Invalid</a>'


def scheduled_task_data(tasks):
    data = [{'name': render_template_string(_name, t=t),
             'schedule': _format_schedule(t),
             'owner': '<a class="text-decoration-none" href="mailto:{e}">{name}</a>'.format(e=t.owner.email,
                                                               name=t.owner.name) if t.owner is not None
                else '<span class="badge bg-secondary">Nobody</span>',
             'active': render_template_string(_active, t=t),
             'last_run': {
                 'display': t.last_run_at.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': t.last_run_at.timestamp()
             },
             'total_runs': t.total_run_count,
             'last_change': {
                 'display': t.date_changed.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': t.date_changed.timestamp()
             },
             'expires': {
                 'display': t.expires.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestamp': t.expires.timestamp()
             } if t.expires is not None else {
                 'display': '<span class="badge bg-secondary">No expiry</span>',
                 'timestamp': None
             },
             'menu': render_template_string(_scheduled_menu_template, task=t)} for t in tasks]

    return jsonify(data)
