#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Convenor per-class "Tickets" dashboard pane (design screen 3a). Rendered inside the shared
per-class dashboard chrome (pclass_base.html / nav.html) so the tab strip persists, this shows the
needs-triage panel and the class-scoped ticket ledger. The ledger data itself comes from the shared
tickets.ledger_ajax feed (mode=convenor, class_id=<this class>), which is permission-scoped.

A convenor's *personal* inbox (assigned/watched, cross-class) is a separate surface reached via the
faculty "My tickets" menu item — never through this class-scoped view.
"""

from datetime import datetime

from flask import flash, redirect, request
from flask_security import roles_accepted

from app.convenor import convenor

from ..models import Label, ProjectClass, Ticket
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor


def _triage_meta(ticket):
    return {
        "scope_names": [pclass.name for pclass in ticket.scope_classes],
        "overdue": ticket.due_date is not None and ticket.status in Ticket.OPEN_STATES and ticket.due_date < datetime.now(),
    }


@convenor.route("/tickets_tab/<int:id>")
@roles_accepted("faculty", "admin", "root")
def tickets_tab(id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # needs-triage: unassigned tickets in this class's scope that span more than one class
    triage = [
        ticket
        for ticket in Ticket.query.filter(
            Ticket.assignee_id.is_(None),
            Ticket.scope_classes.any(ProjectClass.id == pclass.id),
        )
        .order_by(Ticket.last_edit_timestamp.desc())
        .all()
        if ticket.scope_classes.count() > 1
    ]

    labels = []
    if pclass.tenant_id is not None:
        labels = Label.query.filter_by(tenant_id=pclass.tenant_id).order_by(Label.name.asc()).all()

    return render_template_context(
        "convenor/dashboard/tickets.html",
        pane="tickets",
        pclass=pclass,
        config=config,
        convenor_data=get_convenor_dashboard_data(pclass, config),
        needs_triage=triage,
        needs_triage_meta=[_triage_meta(ticket) for ticket in triage],
        labels=labels,
        all_statuses=[(value, label) for value, label in Ticket._labels.items()],
        selected_status=request.args.get("status", type=int),
        selected_label=request.args.get("label_id", type=int),
        action_form=ConfirmActionForm(),
    )
