#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime
from functools import partial

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user
from flask_security import roles_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from .. import ajax
from ..admin.forms import EditEmailTemplateForm
from ..admin.views_utilities import create_new_email_template_labels
from ..database import db
from ..models import EmailTemplate, Tenant
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..tools import ServerSideSQLHandler
from ..tools.ServerSideProcessing import FakeQuery, ServerSideInMemoryHandler
from . import tenants
from .forms import AddTenantForm, EditTenantForm


@tenants.route("/edit_tenants")
@roles_required("root")
def edit_tenants():
    return render_template_context("tenants/edit_tenants.html")


@tenants.route("/tenants_ajax", methods=["POST"])
@roles_required("root")
def tenants_ajax():
    base_query = db.session.query(Tenant)

    name = {"search": Tenant.name, "order": Tenant.name}

    columns = {"name": name}

    return_url = url_for("tenants.edit_tenants")
    return_text = "tenants view"

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.tenants.tenants_data, return_url, return_text)
        )


@tenants.route("/add_tenant", methods=["GET", "POST"])
@roles_required("root")
def add_tenant():
    form = AddTenantForm(request.form)

    if form.validate_on_submit():
        tenant = Tenant(
            name=form.name.data,
            colour=form.colour.data,
            in_2026_ATAS_campaign=form.in_2026_ATAS_campaign.data,
        )

        try:
            db.session.add(tenant)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new tenant because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("tenants.edit_tenants"))

    return render_template_context(
        "tenants/edit_tenant.html", tenant_form=form, title="Add new tenant"
    )


@tenants.route("/edit_tenant/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_tenant(id):
    tenant = db.session.query(Tenant).get_or_404(id)

    form = EditTenantForm(obj=tenant)
    form.tenant = tenant

    if form.validate_on_submit():
        tenant.name = form.name.data
        tenant.colour = form.colour.data
        tenant.in_2026_ATAS_campaign = form.in_2026_ATAS_campaign.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not rename tenant because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("tenants.edit_tenants"))

    return render_template_context(
        "tenants/edit_tenant.html", tenant_form=form, title="Edit tenant"
    )


# Tenant-level email template views
# ======================================================================================================================


@tenants.route("/email_templates/<int:tenant_id>")
@roles_required("root")
def email_templates(tenant_id):
    """
    List all email template overrides for a given tenant.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = redirect_url()

    AJAX_endpoint = url_for(
        "tenants.email_templates_ajax", tenant_id=tenant_id, url=url, text=text
    )

    return render_template_context(
        "admin/email_templates/list.html",
        AJAX_endpoint=AJAX_endpoint,
        title=f"Email templates for {tenant.name}",
        card_title=f"Email templates for <strong>{tenant.name}</strong>",
        inspector_type="tenant",
        url=url,
        text=text,
    )


@tenants.route("/email_templates_ajax/<int:tenant_id>", methods=["POST"])
@roles_required("root")
def email_templates_ajax(tenant_id):
    """
    AJAX endpoint for tenant email templates list.
    """
    from ..models.emails import TENANT_SPECIALIZABLE_TEMPLATES

    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    # Build list of (template_type, template_or_none) tuples for all specializable templates
    template_list = []
    for template_type in TENANT_SPECIALIZABLE_TEMPLATES:
        templates = (
            db.session.query(EmailTemplate)
            .filter(
                EmailTemplate.type == template_type,
                EmailTemplate.tenant_id == tenant_id,
                EmailTemplate.pclass_id.is_(None),
            )
            .order_by(EmailTemplate.version.desc())
            .all()
        )
        if len(templates) > 0:
            template_list.extend([(template_type, t) for t in templates])
        else:
            template_list.append((template_type, None))

    fake_query = FakeQuery(template_list)

    def _type_value(row):
        type_id, _ = row
        return type_id

    def _subject(row):
        _, template = row
        if template is None:
            return ""
        return template.subject

    def _version(row):
        _, template = row
        if template is None:
            return 0
        return template.version

    def _active(row):
        _, template = row
        if template is None:
            return False
        return template.active

    def _comment(row):
        _, template = row
        if template is None:
            return ""
        return template.comment

    type_col = {"order": _type_value}
    subject_col = {"search": _subject, "order": _subject}
    version_col = {"order": _version}
    status_col = {"order": _active}
    comment_col = {"search": _comment, "order": _comment}

    columns = {
        "type": type_col,
        "subject": subject_col,
        "version": version_col,
        "status": status_col,
        "comment": comment_col,
    }

    with ServerSideInMemoryHandler(request, fake_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.email_templates.template_data_tenant_override, tenant)
        )


@tenants.route("/create_email_template/<int:tenant_id>/<int:template_type>")
@roles_required("root")
def create_email_template(tenant_id, template_type):
    """
    Create a new email template override for a tenant.
    """
    from ..models.emails import TENANT_SPECIALIZABLE_TEMPLATES

    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    if template_type not in TENANT_SPECIALIZABLE_TEMPLATES:
        flash(
            f"Template type {template_type} cannot be specialized for tenants.",
            "error",
        )
        return redirect(redirect_url())

    # Find the active global fallback to use as a basis
    fallback_template = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template_type,
            EmailTemplate.tenant_id.is_(None),
            EmailTemplate.pclass_id.is_(None),
            EmailTemplate.active.is_(True),
        )
        .order_by(EmailTemplate.version.desc())
        .first()
    )

    if fallback_template is None:
        flash(
            f"Could not find a global fallback template for type {template_type}. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    now = datetime.now()
    new_template = EmailTemplate(
        active=True,
        tenant_id=tenant_id,
        pclass_id=None,
        type=template_type,
        subject=fallback_template.subject,
        html_body=fallback_template.html_body,
        comment=f"Created from default template (version {fallback_template.version})",
        version=1,
        creator_id=current_user.id,
        creation_timestamp=now,
        last_edit_timestamp=None,
        last_edit_id=None,
    )

    try:
        db.session.add(new_template)
        db.session.commit()
        flash("Successfully created new tenant email template override.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not create email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("tenants.email_templates", tenant_id=tenant_id))


@tenants.route(
    "/edit_email_template/<int:tenant_id>/<int:template_id>",
    methods=["GET", "POST"],
)
@roles_required("root")
def edit_email_template(tenant_id, template_id):
    """
    Edit a tenant-level email template override.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)
    form: EditEmailTemplateForm = EditEmailTemplateForm(obj=template)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("tenants.email_templates", tenant_id=tenant_id)

    if template.tenant_id != tenant_id:
        flash(
            "You cannot edit this template because it does not belong to the specified tenant.",
            "error",
        )
        return redirect(redirect_url())

    if form.validate_on_submit():
        label_list = create_new_email_template_labels(form)

        template.subject = form.subject.data
        template.html_body = form.html_body.data
        template.labels = label_list
        template.comment = form.comment.data

        template.last_edit_id = current_user.id
        template.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    action_url = url_for(
        "tenants.edit_email_template",
        tenant_id=tenant_id,
        template_id=template_id,
        url=url,
    )

    return render_template_context(
        "admin/email_templates/edit.html",
        form=form,
        email_template=template,
        title="Edit tenant email template",
        action_url=action_url,
    )


@tenants.route("/duplicate_email_template/<int:tenant_id>/<int:template_id>")
@roles_required("root")
def duplicate_email_template(tenant_id, template_id):
    """
    Duplicate a tenant-level email template, incrementing the version number.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    if template.tenant_id != tenant_id:
        flash("This template does not belong to the specified tenant.", "error")
        return redirect(redirect_url())

    max_version = (
        db.session.query(func.max(EmailTemplate.version))
        .filter(
            EmailTemplate.type == template.type,
            EmailTemplate.tenant_id == tenant_id,
            EmailTemplate.pclass_id.is_(None),
        )
        .scalar()
    )
    new_version = (max_version or 0) + 1

    now = datetime.now()
    new_template = EmailTemplate(
        active=False,
        tenant_id=tenant_id,
        pclass_id=None,
        type=template.type,
        subject=template.subject,
        html_body=template.html_body,
        comment=f"Duplicated from version {template.version}",
        version=new_version,
        last_used=None,
        creator_id=current_user.id,
        creation_timestamp=now,
        last_edit_timestamp=None,
        last_edit_id=None,
    )
    new_template.labels = list(template.labels)

    try:
        db.session.add(new_template)
        db.session.commit()
        flash(
            f"Successfully duplicated email template. New version is {new_version}.",
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not duplicate email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("tenants.email_templates", tenant_id=tenant_id))


@tenants.route("/activate_email_template/<int:tenant_id>/<int:template_id>")
@roles_required("root")
def activate_email_template(tenant_id, template_id):
    """
    Activate a tenant-level email template.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    if template.tenant_id != tenant_id:
        flash("This template does not belong to the specified tenant.", "error")
        return redirect(redirect_url())

    try:
        template.active = True
        template.last_edit_timestamp = datetime.now()
        template.last_edit_id = current_user.id
        db.session.commit()
        flash("Successfully activated email template.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("tenants.email_templates", tenant_id=tenant_id))


@tenants.route("/deactivate_email_template/<int:tenant_id>/<int:template_id>")
@roles_required("root")
def deactivate_email_template(tenant_id, template_id):
    """
    Deactivate a tenant-level email template.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    if template.tenant_id != tenant_id:
        flash("This template does not belong to the specified tenant.", "error")
        return redirect(redirect_url())

    try:
        template.active = False
        template.last_edit_timestamp = datetime.now()
        template.last_edit_id = current_user.id
        db.session.commit()
        flash("Successfully deactivated email template.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deactivate email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("tenants.email_templates", tenant_id=tenant_id))


@tenants.route("/delete_email_template/<int:tenant_id>/<int:template_id>")
@roles_required("root")
def delete_email_template(tenant_id, template_id):
    """
    Delete a tenant-level email template override.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    if template.tenant_id != tenant_id:
        flash("This template does not belong to the specified tenant.", "error")
        return redirect(redirect_url())

    try:
        db.session.delete(template)
        db.session.commit()
        flash("Successfully deleted email template.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("tenants.email_templates", tenant_id=tenant_id))


@tenants.route("/view_default_template/<int:tenant_id>/<int:template_type>")
@roles_required("root")
def view_default_template(tenant_id, template_type):
    """
    View the global fallback template for a given template type (read-only).
    Used by admins inspecting what the default is before creating a tenant override.
    """
    from ..models.emails import _TYPE_NAMES, TENANT_SPECIALIZABLE_TEMPLATES

    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    if template_type not in TENANT_SPECIALIZABLE_TEMPLATES:
        flash(
            f"Template type {template_type} cannot be specialized for tenants.",
            "error",
        )
        return redirect(redirect_url())

    # Find the active global fallback (no tenant, no pclass)
    default_template = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template_type,
            EmailTemplate.tenant_id.is_(None),
            EmailTemplate.pclass_id.is_(None),
            EmailTemplate.active.is_(True),
        )
        .order_by(EmailTemplate.version.desc())
        .first()
    )

    if default_template is None:
        flash(
            "Could not find a global fallback template for this template type. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("tenants.email_templates", tenant_id=tenant_id)

    type_name = _TYPE_NAMES.get(
        template_type, f"Unknown email template type ({template_type})"
    )

    return render_template_context(
        "admin/email_templates/view_default.html",
        tenant=tenant,
        email_template=default_template,
        type_name=type_name,
        url=url,
        title="View default email template",
    )
