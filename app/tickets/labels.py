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
Tenant-scoped label management (design screens 4b / 5a): create, rename/recolour, and delete
labels. Labels belong to a tenant and are shared across that tenant's classes. Gated to convenors
and admin/root (watchers and other users see labels read-only); the acting user must also belong to
the tenant (admin/root may manage any).
"""

from flask import abort, current_app, flash, redirect, request, url_for
from flask_security import current_user, roles_accepted
from sqlalchemy.exc import SQLAlchemyError

from app.tickets import tickets

from ..database import db
from ..models import Label, Tenant
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.tickets import can_manage_labels
from ..shared.workflow_logging import log_db_commit
from .forms import LabelForm

# the fixed 9-colour label palette (design 4b/5a). These are label data, not UI theme colours.
LABEL_PALETTE = [
    "#0a58ca",
    "#b60205",
    "#997404",
    "#0f5132",
    "#59359a",
    "#087990",
    "#b5480b",
    "#d63384",
    "#41464b",
]


def _manageable_tenants(user):
    if user.has_role("admin") or user.has_role("root"):
        return Tenant.query.order_by(Tenant.name.asc()).all()
    return list(user.tenants)


def _resolve_tenant(user, tenant_id):
    """Return a tenant the user may manage labels for, or abort."""
    manageable = {tenant.id: tenant for tenant in _manageable_tenants(user)}
    if not manageable:
        abort(403)
    if tenant_id is None:
        return sorted(manageable.values(), key=lambda t: t.id)[0]
    tenant = manageable.get(tenant_id)
    if tenant is None:
        abort(403)
    return tenant


def _next_unused_colour(tenant_id):
    used = {label.colour for label in Label.query.filter_by(tenant_id=tenant_id).all()}
    for colour in LABEL_PALETTE:
        if colour not in used:
            return colour
    return LABEL_PALETTE[0]


def _clamp_colour(requested, tenant_id):
    if requested in LABEL_PALETTE:
        return requested
    return _next_unused_colour(tenant_id)


@tickets.route("/labels")
@roles_accepted("faculty", "admin", "root")
def labels_manage():
    if not can_manage_labels(current_user):
        abort(403)

    tenant = _resolve_tenant(current_user, request.args.get("tenant_id", type=int))
    labels = Label.query.filter_by(tenant_id=tenant.id).order_by(Label.name.asc()).all()

    return render_template_context(
        "tickets/labels.html",
        tenant=tenant,
        tenants=_manageable_tenants(current_user),
        labels=labels,
        palette=LABEL_PALETTE,
        form=LabelForm(),
        action_form=ConfirmActionForm(),
    )


def _back(tenant_id):
    return redirect(url_for("tickets.labels_manage", tenant_id=tenant_id))


@tickets.route("/labels/create", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def label_create():
    if not can_manage_labels(current_user):
        abort(403)

    tenant = _resolve_tenant(current_user, request.form.get("tenant_id", type=int))
    form = LabelForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if Label.query.filter_by(tenant_id=tenant.id, name=name).first() is not None:
            flash(f"A label named '{name}' already exists in this tenant.", "error")
            return _back(tenant.id)

        colour = form.colour.data if form.colour.data in LABEL_PALETTE else _next_unused_colour(tenant.id)
        label = Label(tenant_id=tenant.id, name=name, colour=colour)
        db.session.add(label)
        _commit_or_flash(f"Created ticket label '{name}'", "Could not create the label due to a database error.")
    else:
        flash("The label could not be created — a name is required.", "error")

    return _back(tenant.id)


@tickets.route("/labels/<int:label_id>/edit", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def label_edit(label_id):
    if not can_manage_labels(current_user):
        abort(403)

    label = Label.query.get(label_id)
    if label is None:
        abort(404)
    tenant = _resolve_tenant(current_user, label.tenant_id)

    form = LabelForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        clash = Label.query.filter(Label.tenant_id == tenant.id, Label.name == name, Label.id != label.id).first()
        if clash is not None:
            flash(f"A label named '{name}' already exists in this tenant.", "error")
            return _back(tenant.id)

        label.name = name
        label.colour = _clamp_colour(form.colour.data, tenant.id)
        _commit_or_flash(f"Updated ticket label '{name}'", "Could not update the label due to a database error.")
    else:
        flash("The label could not be updated — a name is required.", "error")

    return _back(tenant.id)


@tickets.route("/labels/<int:label_id>/delete", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def label_delete(label_id):
    if not can_manage_labels(current_user):
        abort(403)

    label = Label.query.get(label_id)
    if label is None:
        abort(404)
    tenant = _resolve_tenant(current_user, label.tenant_id)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        name = label.name
        db.session.delete(label)
        _commit_or_flash(f"Deleted ticket label '{name}'", "Could not delete the label due to a database error.")

    return _back(tenant.id)


def _commit_or_flash(summary, failure_message):
    try:
        log_db_commit(summary, user=current_user)
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)
        flash(failure_message, "error")
