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

from flask import abort, flash, jsonify, redirect, request
from flask_security import roles_accepted

from app.convenor import convenor
from ..models import Label, ProjectClass, ProjectClassConfig, SelectingStudent, StudentData, SubmittingStudent, Ticket, TicketSubject, User
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.tickets import SEARCH_LIMIT as _SEARCH_LIMIT
from ..shared.tickets import name_filter as _name_filter
from ..shared.tickets import resolve_token as _resolve_token
from ..shared.tickets import student_name as _student_name
from ..shared.tickets import token_for as _token
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor


def _class_scope_candidates(pclass, query_term):
    """Select2 remote data for the ledger's scope-filter picker (screen 3a): any
    submitter/selector/whole-class option within this one class, across all years — unlike
    tickets.compose_people, which is scoped to the *acting* user's own supervisees and is the
    wrong candidate set for "filter this class's ledger by any student in it"."""

    def _results(model, kind, label):
        q = (
            model.query.join(ProjectClassConfig, model.config_id == ProjectClassConfig.id)
            .join(StudentData, model.student_id == StudentData.id)
            .join(User, StudentData.id == User.id)
            .filter(ProjectClassConfig.pclass_id == pclass.id)
        )
        if query_term:
            q = q.filter(_name_filter(query_term))
        rows = [{"id": _token(kind, student.id), "text": _student_name(student)} for student in q.limit(_SEARCH_LIMIT).all()]
        return {"text": label, "children": rows} if rows else None

    groups = []
    for section in (
        _results(SubmittingStudent, TicketSubject.SUBMITTING_STUDENT, "Submitting students"),
        _results(SelectingStudent, TicketSubject.SELECTING_STUDENT, "Selecting students"),
    ):
        if section is not None:
            groups.append(section)

    if not query_term or query_term.lower() in pclass.name.lower():
        groups.append({"text": "Project class", "children": [{"id": _token(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name}"}]})

    return groups


def _subject_label(token):
    """Human-readable label for an already-selected scope-filter token, so the select2 picker can
    re-render its current selection without an extra round-trip."""
    if not token:
        return None
    resolved = _resolve_token(token)
    if resolved is None:
        return None
    kind, target = resolved
    if kind == TicketSubject.PROJECT_CLASS:
        return f"{target.name}"
    return _student_name(target)


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
        selected_subject_kind=request.args.get("subject_kind"),
        selected_subject=request.args.get("subject"),
        selected_subject_label=_subject_label(request.args.get("subject")),
        action_form=ConfirmActionForm(),
    )


@convenor.route("/tickets_tab/<int:id>/scope_candidates")
@roles_accepted("faculty", "admin", "root")
def tickets_scope_candidates(id):
    """select2 remote data: submitter/selector/whole-class candidates for the ledger's scope
    filter, scoped to this one class (see _class_scope_candidates)."""
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)
    if not validate_is_convenor(pclass, message=False):
        abort(403)

    query_term = (request.args.get("q") or "").strip()
    return jsonify({"results": _class_scope_candidates(pclass, query_term)})
