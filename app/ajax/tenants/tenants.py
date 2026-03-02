#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, get_template_attribute

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.edit_tenant', id=t.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
    </div>
</div>
"""

# language=jinja2
_colour = """
{% if t.colour %}
    {{ simple_label(t.make_label(t.colour)) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

def _build_row(t, simple_label):
    menu_html = render_template_string(_menu, t=t)
    colour_html = render_template_string(_colour, t=t, simple_label=simple_label)

    return {
        "name": t.name,
        "colour": colour_html,
        "menu": menu_html,
    }

def tenants_data(tenants):
    """
    Build the JSON payload for the tenants DataTable.
    """
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = []
    for t in tenants:
        data.append(_build_row(t, simple_label))

    return data
