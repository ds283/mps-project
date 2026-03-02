#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.rename_tenant', id=t.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Rename...
        </a>
    </div>
</div>
"""

def _build_row(t):
    menu_html = render_template_string(_menu, t=t)

    return {
        "name": t.name,
        "menu": menu_html,
    }

def tenants_data(tenants):
    """
    Build the JSON payload for the tenants DataTable.
    """
    data = []
    for t in tenants:
        data.append(_build_row(t))

    return data
