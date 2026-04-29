#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, get_template_attribute, render_template

# language=jinja2
_marking_event_period = """
<div class="text-primary">{{ event.period.display_name }}</div>
<div class="small text-muted mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
    <div class="text-secondary">{{ event.config.year }}&ndash;{{ event.config.year+1 }}</div>
    {% if event.period.start_date %}
        <div class="text-secondary"><i class="fas fa-calendar"></i> Start: {{ event.period.start_date.strftime("%d/%m/%Y") }}</div>
    {% endif %}
    {% if event.period.hand_in_date %}
        <div class="text-secondary"><i class="fas fa-calendar"></i> Hand-in: {{ event.period.hand_in_date.strftime("%d/%m/%Y") }}</div>
    {% endif %}
</div>
"""

# language=jinja2
_marking_event_name = """
<div>{{ event.name }}</div>
{% set pclass = event.pclass %}
{% set swatch_colour = pclass.make_CSS_style() %}
<div class="d-flex flex-row justify-content-start align-items-center gap-2">
    {{ small_swatch(swatch_colour) }}
    <span class="small">{{ pclass.name }}</span>
</div>
"""

# language=jinja2
_marking_event_workflows = """
{% set workflows = event.workflows.all() %}
{% if workflows|length > 0 %}
    <div class="d-flex flex-column gap-1">
        {% for wf in workflows %}
            <div><i class="fas fa-clipboard-check me-1"></i> <span class="text-primary">{{ wf.name }}</span></div>
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_marking_event_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.event_marking_workflows_inspector', event_id=event.id, url=url_for('convenor.marking_events_inspector', pclass_id=pclass.id), text='Assessment archive') }}">
            <i class="fas fa-search fa-fw"></i> Inspect workflows&hellip;
        </a>
    </div>
</div>
"""


def marking_event_data(events):
    """Format a MarkingEvent row for DataTables (assessment archive view)"""

    env = current_app.jinja_env

    period_tmpl = env.from_string(_marking_event_period)
    name_tmpl = env.from_string(_marking_event_name)
    workflows_tmpl = env.from_string(_marking_event_workflows)
    menu_tmpl = env.from_string(_marking_event_menu)

    small_swatch = get_template_attribute("swatch.html", "small_swatch")

    return [
        {
            "period": render_template(period_tmpl, event=event),
            "name": render_template(name_tmpl, event=event, small_swatch=small_swatch),
            "workflows": render_template(workflows_tmpl, event=event),
            "menu": render_template(menu_tmpl, event=event, pclass=event.pclass),
        }
        for event in events
    ]
