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

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user
from flask_security import roles_required
from sqlalchemy.exc import SQLAlchemyError

from .. import ajax
from ..admin.forms import EditEmailTemplateForm
from ..admin.utilities import create_new_email_template_labels
from ..database import db
from ..models import EmailTemplate, ProjectClass, ProjectClassConfig, Tenant
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..tools import ServerSideSQLHandler
from ..tools.ServerSideProcessing import FakeQuery, ServerSideInMemoryHandler
from . import tenants
from .forms import AddAICalibrationFormFactory, AddTenantForm, DeleteForm, EditTenantForm, RecalculateAIConcernFormFactory
from ..shared.email_templates import clone_email_template
from ..shared.workflow_logging import log_db_commit


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
        return handler.build_payload(partial(ajax.tenants.tenants_data, return_url, return_text))


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
            log_db_commit("Added new tenant", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new tenant because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("tenants.edit_tenants"))

    return render_template_context("tenants/edit_tenant.html", tenant_form=form, title="Add new tenant")


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
            log_db_commit("Edited tenant settings", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not rename tenant because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("tenants.edit_tenants"))

    return render_template_context("tenants/edit_tenant.html", tenant_form=form, title="Edit tenant")


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

    AJAX_endpoint = url_for("tenants.email_templates_ajax", tenant_id=tenant_id, url=url, text=text)

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
    from ..models.emails import TENANT_SPECIALIZABLE_TEMPLATES, _TYPE_NAMES

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

    def _type_name(row):
        type_id, _ = row
        return _TYPE_NAMES.get(type_id, f"Unknown type ({type_id})")

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

    type_col = {"search": _type_name, "order": _type_value}
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
        return handler.build_payload(partial(ajax.email_templates.template_data_tenant_override, tenant))


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
        log_db_commit("Created new tenant email template override", user=current_user)
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
            log_db_commit("Edited tenant email template", user=current_user)
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

    new_template = clone_email_template(template, None, tenant_id, current_user)

    try:
        db.session.add(new_template)
        log_db_commit("Duplicated tenant email template", user=current_user)
        flash(
            f"Successfully duplicated email template. New version is {new_template.version}.",
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
        log_db_commit("Activated tenant email template", user=current_user)
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
        log_db_commit("Deactivated tenant email template", user=current_user)
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
        log_db_commit("Deleted tenant email template", user=current_user)
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

    type_name = _TYPE_NAMES.get(template_type, f"Unknown email template type ({template_type})")

    return render_template_context(
        "admin/email_templates/view_default.html",
        tenant=tenant,
        email_template=default_template,
        type_name=type_name,
        url=url,
        title="View default email template",
    )


# AI concern calibration
# ======================================================================================================================


def _get_available_years(tenant_id: int) -> list[int]:
    """Return sorted list of distinct ProjectClassConfig.year values for a tenant."""
    rows = (
        db.session.query(ProjectClassConfig.year)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .filter(ProjectClass.tenant_id == tenant_id)
        .distinct()
        .order_by(ProjectClassConfig.year)
        .all()
    )
    return [r[0] for r in rows if r[0] is not None]


def _get_llm_configs_from_data(tenant_id: int) -> list[tuple]:
    """Return sorted distinct (llm_model_name, llm_context_size) pairs from completed submissions."""
    from ..models import SubmissionPeriodRecord, SubmissionRecord

    rows = (
        db.session.query(SubmissionRecord.llm_model_name, SubmissionRecord.llm_context_size)
        .join(SubmissionPeriodRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
        .join(ProjectClassConfig, SubmissionPeriodRecord.config_id == ProjectClassConfig.id)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .filter(
            ProjectClass.tenant_id == tenant_id,
            SubmissionRecord.llm_model_name.isnot(None),
            SubmissionRecord.llm_context_size.isnot(None),
        )
        .distinct()
        .order_by(SubmissionRecord.llm_model_name, SubmissionRecord.llm_context_size)
        .all()
    )
    return [(r[0], r[1]) for r in rows]


def _uncovered_pclasses(tenant: Tenant) -> list:
    """Return ProjectClass objects with uses_submission set that have no TenantAICalibration."""
    covered_ids: set[int] = set()
    for cal in tenant.ai_calibrations:
        covered_ids.update(cal.included_pclass_ids_data)

    return [p for p in ProjectClass.query.filter_by(tenant_id=tenant.id).all() if p.uses_submission and p.id not in covered_ids]


@tenants.route("/ai_calibrations/<int:tenant_id>")
@roles_required("root")
def ai_calibrations(tenant_id):
    """Show all TenantAICalibration objects for a tenant and surface coverage warnings."""
    from ..shared.ai_calibration import CALIBRATION_MIN_SAMPLES

    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    pclass_by_id = {p.id: p for p in ProjectClass.query.filter_by(tenant_id=tenant_id).all()}

    bonferroni_k = len(tenant.ai_calibrations)
    alpha_medium = 0.05 / bonferroni_k if bonferroni_k else None
    alpha_high = 0.01 / bonferroni_k if bonferroni_k else None

    uncovered = _uncovered_pclasses(tenant)
    delete_form = DeleteForm()

    return render_template_context(
        "tenants/ai_calibrations.html",
        tenant=tenant,
        calibrations=tenant.ai_calibrations,
        pclass_by_id=pclass_by_id,
        bonferroni_k=bonferroni_k,
        alpha_medium=alpha_medium,
        alpha_high=alpha_high,
        uncovered=uncovered,
        min_samples=CALIBRATION_MIN_SAMPLES,
        delete_form=delete_form,
        url=url_for("tenants.edit_tenants"),
        text="Tenant list",
    )


@tenants.route("/add_ai_calibration/<int:tenant_id>", methods=["GET", "POST"])
@roles_required("root")
def add_ai_calibration(tenant_id):
    """Add a new TenantAICalibration for a tenant."""
    import json as _json
    from datetime import datetime as _dt

    from ..models.ai_calibration import TenantAICalibration
    from ..shared.ai_calibration import CALIBRATION_MIN_SAMPLES, compute_calibration

    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    available_years = _get_available_years(tenant_id)
    year_choices = [(y, str(y)) for y in available_years]
    llm_configs = _get_llm_configs_from_data(tenant_id)

    FormClass = AddAICalibrationFormFactory(tenant_id, llm_configs)
    form = FormClass(request.form)
    form.years.choices = year_choices

    if form.validate_on_submit():
        feature_set = form.feature_set.data
        llm_config_val = form.llm_config.data or ""
        pclass_ids = [p.id for p in form.project_classes.data] if form.project_classes.data else None
        years = [int(y) for y in form.years.data] if form.years.data else None

        llm_model_name = None
        llm_context_window = None
        if llm_config_val and "::" in llm_config_val:
            parts = llm_config_val.split("::", 1)
            llm_model_name = parts[0]
            try:
                llm_context_window = int(parts[1])
            except ValueError:
                llm_context_window = None

        if feature_set == "full" and (llm_model_name is None or llm_context_window is None):
            flash("A valid LLM configuration must be selected for full (4D) calibrations.", "error")
            return redirect(request.url)

        try:
            cal_data = compute_calibration(tenant_id, pclass_ids=pclass_ids, years=years, feature_set=feature_set)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(request.url)

        cal = TenantAICalibration(
            tenant_id=tenant_id,
            feature_set=feature_set,
            llm_model_name=llm_model_name,
            llm_context_window=llm_context_window,
            calibrated_at=_dt.fromisoformat(cal_data["calibrated_at"]),
            n_samples=cal_data["n_samples"],
            mu=_json.dumps(cal_data["mu"]),
            sigma_inv=_json.dumps(cal_data["sigma_inv"]),
            included_pclass_ids=_json.dumps(cal_data["included_pclass_ids"]),
            included_years=_json.dumps(cal_data["included_years"]),
        )

        conflicts = cal.validate_pclass_exclusivity(db.session)
        if conflicts:
            pcs = ProjectClass.query.filter(ProjectClass.id.in_(conflicts)).all()
            names = ", ".join(p.abbreviation or p.name for p in pcs)
            flash(
                f"Cannot save: the following project classes are already assigned to another "
                f"calibration with the same feature set and LLM configuration: {names}",
                "error",
            )
            return redirect(request.url)

        try:
            db.session.add(cal)
            log_db_commit(
                f"Added AI calibration ({feature_set}) for tenant {tenant.name}",
                user=current_user,
            )
            flash(
                f"Calibration saved successfully using {cal_data['n_samples']} samples.",
                "success",
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError saving AI calibration", exc_info=exc)
            flash(
                "A database error occurred while saving the calibration. Please contact an administrator.",
                "error",
            )

        return redirect(url_for("tenants.ai_calibrations", tenant_id=tenant_id))

    if request.method == "GET":
        all_pclasses = ProjectClass.query.filter_by(tenant_id=tenant_id).all()
        form.project_classes.data = all_pclasses
        form.years.data = [y for y in available_years if y <= 2022]

    return render_template_context(
        "tenants/add_ai_calibration.html",
        tenant=tenant,
        form=form,
        llm_configs=llm_configs,
        min_samples=CALIBRATION_MIN_SAMPLES,
        url=url_for("tenants.ai_calibrations", tenant_id=tenant_id),
        text="AI calibrations",
    )


@tenants.route("/delete_ai_calibration/<int:tenant_id>/<int:cal_id>", methods=["POST"])
@roles_required("root")
def delete_ai_calibration(tenant_id, cal_id):
    """Delete a TenantAICalibration."""
    from ..models.ai_calibration import TenantAICalibration

    form = DeleteForm(request.form)
    if not form.validate():
        flash("Request validation failed. Please try again.", "error")
        return redirect(url_for("tenants.ai_calibrations", tenant_id=tenant_id))

    tenant: Tenant = Tenant.query.get_or_404(tenant_id)
    cal: TenantAICalibration = TenantAICalibration.query.get_or_404(cal_id)

    if cal.tenant_id != tenant_id:
        flash("This calibration does not belong to the specified tenant.", "error")
        return redirect(url_for("tenants.ai_calibrations", tenant_id=tenant_id))

    try:
        db.session.delete(cal)
        log_db_commit(
            f"Deleted AI calibration ({cal.feature_set}) for tenant {tenant.name}",
            user=current_user,
        )
        flash("Calibration deleted successfully.", "success")
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError deleting AI calibration", exc_info=exc)
        flash(
            "A database error occurred while deleting the calibration. Please contact an administrator.",
            "error",
        )

    return redirect(url_for("tenants.ai_calibrations", tenant_id=tenant_id))


@tenants.route("/recalculate_ai_concern/<int:tenant_id>", methods=["GET", "POST"])
@roles_required("root")
def recalculate_ai_concern(tenant_id):
    """
    Launch a background Celery task that re-evaluates the Mahalanobis AI-concern
    flag on existing completed SubmissionRecords for a tenant.

    This is intentionally separate from calibration: calibration updates the
    centroid, recalculation propagates that centroid to stored results.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    if not tenant.ai_calibrations:
        flash(
            "This tenant has no calibration data yet. Please add a calibration first.",
            "warning",
        )
        return redirect(url_for("tenants.ai_calibrations", tenant_id=tenant_id))

    available_years = _get_available_years(tenant_id)
    year_choices = [(y, str(y)) for y in available_years]

    FormClass = RecalculateAIConcernFormFactory(tenant_id)
    form = FormClass(request.form)
    form.years.choices = year_choices

    calibrations = list(tenant.ai_calibrations)
    bonferroni_k = len(calibrations)
    alpha_medium = 0.05 / bonferroni_k if bonferroni_k else None
    alpha_high = 0.01 / bonferroni_k if bonferroni_k else None

    if form.validate_on_submit():
        from ..task_queue import register_task

        pclass_ids = [p.id for p in form.project_classes.data] if form.project_classes.data else None
        years = [int(y) for y in form.years.data] if form.years.data else None

        full_recalculate = form.full_recalculate.data
        task_description = (
            "Re-process cached extracted text and recompute all lexical metrics before reclassifying."
            if full_recalculate
            else "Re-evaluate Mahalanobis AI concern flags for existing submissions."
        )
        task_id = register_task(
            f"Recalculate AI concern — {tenant.name}",
            owner=current_user,
            description=task_description,
        )
        if task_id is not None:
            celery = current_app.extensions["celery"]
            t = celery.tasks["app.tasks.language_analysis.recalculate_ai_concern"]
            t.apply_async(args=[task_id, tenant_id, pclass_ids, years, full_recalculate], queue="default")
            flash(
                "Recalculation task has been launched. It will run in the background.",
                "success",
            )
        return redirect(url_for("tenants.ai_calibrations", tenant_id=tenant_id))

    if request.method == "GET":
        all_pclasses = ProjectClass.query.filter_by(tenant_id=tenant_id).all()
        form.project_classes.data = all_pclasses
        form.years.data = available_years

    return render_template_context(
        "tenants/recalculate_ai_concern.html",
        tenant=tenant,
        form=form,
        calibrations=calibrations,
        bonferroni_k=bonferroni_k,
        alpha_medium=alpha_medium,
        alpha_high=alpha_high,
        url=url_for("tenants.ai_calibrations", tenant_id=tenant_id),
        text="AI calibrations",
    )


@tenants.route("/export_marking_data/<int:tenant_id>")
@roles_required("root")
def export_marking_data(tenant_id):
    """
    Queue an anonymised analytical marking data export for the given tenant.
    The resulting Excel workbook is delivered to the requesting user's Download Centre.
    """
    tenant: Tenant = Tenant.query.get_or_404(tenant_id)

    from ..task_queue import register_task

    task_id = register_task(
        f"Analytical marking data export — {tenant.name}",
        owner=current_user,
        description=f"Export anonymised marking data for tenant ‘{tenant.name}’",
    )
    if task_id is not None:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.data_export.export_tenant_marking_data_xlsx"]
        task.apply_async(args=[task_id, tenant_id, current_user.id], task_id=task_id, queue="default")
        flash(
            "Export queued. You will be notified in your Download Centre when it is ready.",
            "success",
        )
    else:
        flash("Could not register export task. Please try again.", "error")

    return redirect(url_for("tenants.edit_tenants"))
