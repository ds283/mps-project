#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime
from functools import partial

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_security import current_user, roles_accepted
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

import app.ajax as ajax
from app.convenor import convenor

from ..admin.forms import EditEmailTemplateForm
from ..admin.views import create_new_email_template_labels
from ..database import db
from ..models import (
    EmailTemplate,
    ProjectClass,
)
from ..shared.context.global_context import render_template_context
from ..shared.utils import (
    redirect_url,
)
from ..shared.validators import (
    validate_is_convenor,
)
from ..tools import ServerSideInMemoryHandler
from ..tools.ServerSideProcessing import FakeQuery


@convenor.route("/email_templates/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def email_templates(pclass_id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = redirect_url()

    AJAX_endpoint = url_for(
        "convenor.email_templates_ajax", pclass_id=pclass_id, url=url, text=text
    )

    return render_template_context(
        "admin/email_templates/list.html",
        AJAX_endpoint=AJAX_endpoint,
        title=f"Email templates for {pclass.name}",
        card_title=f"Email templates for <strong>{pclass.name}</strong>",
        inspector_type="pclass",
        url=url,
        text=text,
    )


@convenor.route("/email_templates_ajax/<int:pclass_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def email_templates_ajax(pclass_id):
    """
    AJAX endpoint for email templates list
    :param pclass_id: project class ID
    :return: JSON response for DataTables
    """
    from ..models.emails import PCLASS_SPECIALIZABLE_TEMPLATES

    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # Build list of (template_type, template_or_none) tuples for all specializable templates
    template_list = []
    for template_type in PCLASS_SPECIALIZABLE_TEMPLATES:
        # Find all templates for this specific type and project class
        templates = (
            db.session.query(EmailTemplate)
            .filter(
                EmailTemplate.type == template_type,
                EmailTemplate.pclass_id == pclass_id,
            )
            .order_by(EmailTemplate.version.desc())
            .all()
        )
        if len(templates) > 0:
            template_list.extend([(template_type, t) for t in templates])
        else:
            template_list.append((template_type, None))

    # Use in-memory handler since we're working with a simple list
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
            partial(ajax.email_templates.template_data_pclass_override, pclass)
        )


@convenor.route("/create_email_template/<int:pclass_id>/<int:template_type>")
@roles_accepted("faculty", "admin", "root")
def create_email_template(pclass_id, template_type):
    """
    Create a new email template override for a project class
    """
    from ..models.emails import PCLASS_SPECIALIZABLE_TEMPLATES

    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # verify template type is specializable
    if template_type not in PCLASS_SPECIALIZABLE_TEMPLATES:
        flash(
            f"Template type {template_type} cannot be specialized for project classes.",
            "error",
        )
        return redirect(redirect_url())

    # Find a fallback template to use as a basis, preferring a tenant specialization
    # if there is one
    fallback_template = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template_type,
            EmailTemplate.pclass_id.is_(None),
            or_(
                EmailTemplate.tenant_id.is_(None),
                EmailTemplate.tenant_id == pclass.tenant_id,
            ),
            EmailTemplate.active.is_(True),
        )
        .order_by(
            EmailTemplate.tenant_id.desc(),
            EmailTemplate.version.desc(),
        )
        .first()
    )

    if fallback_template is None:
        flash(
            f"Could not find fallback template for type {template_type}. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # Create new template based on fallback
    now = datetime.now()
    new_template = EmailTemplate(
        active=True,
        pclass_id=pclass_id,
        tenant_id=None,
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
        flash(f"Successfully created new email template override.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f"Could not create email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("convenor.email_templates", pclass_id=pclass_id))


@convenor.route(
    "/edit_email_template/<int:pclass_id>/<int:template_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root")
def edit_email_template(pclass_id, template_id):
    """
    Edit an email template
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get template
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)
    form: EditEmailTemplateForm = EditEmailTemplateForm(obj=template)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.email_templates", pclass_id=pclass_id)

    # verify template belongs to this project class
    if template.pclass_id != pclass_id:
        flash(
            "You cannto edit this template, because it does not belong to the specified project class.",
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
        "convenor.edit_email_template",
        pclass_id=pclass_id,
        template_id=template_id,
        url=url,
    )

    return render_template_context(
        "admin/email_templates/edit.html",
        form=form,
        email_template=template,
        title="Edit email template",
        action_url=action_url,
    )


@convenor.route("/duplicate_email_template/<int:pclass_id>/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def duplicate_email_template(pclass_id, template_id):
    """
    Duplicate an email template, incrementing the version number
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get template
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    # verify template belongs to this project class
    if template.pclass_id != pclass_id:
        flash("This template does not belong to the specified project class.", "error")
        return redirect(redirect_url())

    # Find the highest version number for this template type and project class
    max_version = (
        db.session.query(func.max(EmailTemplate.version))
        .filter(
            EmailTemplate.type == template.type,
            EmailTemplate.pclass_id == pclass_id,
        )
        .scalar()
    )
    new_version = (max_version or 0) + 1

    # Create duplicate
    now = datetime.now()
    new_template = EmailTemplate(
        active=False,  # duplicates start inactive
        pclass_id=pclass_id,
        tenant_id=None,
        type=template.type,
        subject=template.subject,
        html_body=template.html_body,
        comment=f"Duplicated from version {template.version}",
        version=new_version,
        creator_id=current_user.id,
        creation_timestamp=now,
        last_edit_timestamp=None,
        last_edit_id=None,
    )

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
            f"Could not duplicate email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("convenor.email_templates", pclass_id=pclass_id))


@convenor.route("/activate_email_template/<int:pclass_id>/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def activate_email_template(pclass_id, template_id):
    """
    Activate an email template
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get template
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    # verify template belongs to this project class
    if template.pclass_id != pclass_id:
        flash("This template does not belong to the specified project class.", "error")
        return redirect(redirect_url())

    try:
        template.active = True
        template.last_edit_timestamp = datetime.now()
        template.last_edited_id = current_user.id
        db.session.commit()
        flash("Successfully activated email template.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("convenor.email_templates", pclass_id=pclass_id))


@convenor.route("/deactivate_email_template/<int:pclass_id>/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def deactivate_email_template(pclass_id, template_id):
    """
    Deactivate an email template
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get template
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    # verify template belongs to this project class
    if template.pclass_id != pclass_id:
        flash("This template does not belong to the specified project class.", "error")
        return redirect(redirect_url())

    try:
        template.active = False
        template.last_edit_timestamp = datetime.now()
        template.last_edited_id = current_user.id
        db.session.commit()
        flash("Successfully deactivated email template.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deactivate email template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("convenor.email_templates", pclass_id=pclass_id))


@convenor.route("/delete_email_template/<int:pclass_id>/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def delete_email_template(pclass_id, template_id):
    """
    Delete an email template
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get template
    template: EmailTemplate = EmailTemplate.query.get_or_404(template_id)

    # verify template belongs to this project class
    if template.pclass_id != pclass_id:
        flash("This template does not belong to the specified project class.", "error")
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

    return redirect(url_for("convenor.email_templates", pclass_id=pclass_id))


@convenor.route("/view_default_template/<int:pclass_id>/<int:template_type>")
@roles_accepted("faculty", "admin", "root")
def view_default_template(pclass_id, template_type):
    """
    View the current default (tenant-level or global fallback) template for a given
    project class and template type. Read-only; no editing is permitted.
    """
    from ..models.emails import _TYPE_NAMES, PCLASS_SPECIALIZABLE_TEMPLATES

    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # verify template type is specializable at the project-class level
    if template_type not in PCLASS_SPECIALIZABLE_TEMPLATES:
        flash(
            f"Template type {template_type} cannot be specialized for project classes.",
            "error",
        )
        return redirect(redirect_url())

    # find the active default template (tenant-level preferred over global fallback)
    # excluding any pclass-level override
    default_template = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template_type,
            EmailTemplate.pclass_id.is_(None),
            or_(
                EmailTemplate.tenant_id.is_(None),
                EmailTemplate.tenant_id == pclass.tenant_id,
            ),
            EmailTemplate.active.is_(True),
        )
        .order_by(
            EmailTemplate.tenant_id.desc(),
            EmailTemplate.version.desc(),
        )
        .first()
    )

    if default_template is None:
        flash(
            f"Could not find a default template for this template type. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.email_templates", pclass_id=pclass_id)

    type_name = _TYPE_NAMES.get(
        template_type, f"Unknown email template type ({template_type})"
    )

    return render_template_context(
        "admin/email_templates/view_default.html",
        pclass=pclass,
        email_template=default_template,
        type_name=type_name,
        url=url,
        title="View default email template",
    )
