#
# Created by David Seery on 24/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json

from flask import flash, redirect, render_template_string, request, url_for
from flask_security import current_user, roles_accepted
from html2text import HTML2Text
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax

from ..database import db
from ..models import EmailWorkflow, EmailWorkflowItem
from ..models.emails import EmailTemplate
from ..shared.context.global_context import render_template_context
from ..tasks.email_workflow import decode_email_payload
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from . import emailworkflow
from .forms import EditWorkflowForm

_ROLES = ("root", "admin", "email")


# ---------------------------------------------------------------------------
# Task 2 – workflow list
# ---------------------------------------------------------------------------


@emailworkflow.route("/email_workflows")
@roles_accepted(*_ROLES)
def email_workflows():
    return render_template_context(
        "emailworkflow/email_workflows.html",
        url=url_for("emailworkflow.email_workflows"),
        text="Email workflows",
    )


@emailworkflow.route("/email_workflows_ajax", methods=["POST"])
@roles_accepted(*_ROLES)
def email_workflows_ajax():
    # honour filter query parameters passed as POST data inside the DataTables
    # "args" envelope, but fall back to accepting them as separate form fields too.
    args_str = request.form.get("args")
    if args_str:
        try:
            dt_args = json.loads(args_str)
        except (ValueError, TypeError):
            dt_args = {}
    else:
        dt_args = {}

    show_complete = dt_args.get("show_complete", "1") not in ("0", "false", "False")
    show_incomplete = dt_args.get("show_incomplete", "1") not in ("0", "false", "False")
    show_paused = dt_args.get("show_paused", "1") not in ("0", "false", "False")
    show_not_paused = dt_args.get("show_not_paused", "1") not in ("0", "false", "False")

    base_query = db.session.query(EmailWorkflow)

    # apply completion filter
    if show_complete and not show_incomplete:
        base_query = base_query.filter(EmailWorkflow.completed.is_(True))
    elif show_incomplete and not show_complete:
        base_query = base_query.filter(EmailWorkflow.completed.is_(False))

    # apply paused filter
    if show_paused and not show_not_paused:
        base_query = base_query.filter(EmailWorkflow.paused.is_(True))
    elif show_not_paused and not show_paused:
        base_query = base_query.filter(EmailWorkflow.paused.is_(False))

    columns = {
        "name": {"order": EmailWorkflow.name, "search": EmailWorkflow.name},
        "send_time": {"order": EmailWorkflow.send_time},
        "created": {"order": EmailWorkflow.creation_timestamp},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.email_workflow_data)


# ---------------------------------------------------------------------------
# Workflow actions – pause / unpause / edit
# ---------------------------------------------------------------------------


@emailworkflow.route("/pause_workflow/<int:id>")
@roles_accepted(*_ROLES)
def pause_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    if workflow.paused:
        flash("This workflow is already paused.", "info")
        return redirect(url_for("emailworkflow.email_workflows"))

    try:
        workflow.paused = True
        db.session.commit()
        flash(f'Workflow "{workflow.name}" has been paused.', "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not pause workflow due to a database error.", "error")

    return redirect(url_for("emailworkflow.email_workflows"))


@emailworkflow.route("/unpause_workflow/<int:id>")
@roles_accepted(*_ROLES)
def unpause_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    if not workflow.paused:
        flash("This workflow is not paused.", "info")
        return redirect(url_for("emailworkflow.email_workflows"))

    try:
        workflow.paused = False
        db.session.commit()
        flash(f'Workflow "{workflow.name}" has been unpaused.', "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not unpause workflow due to a database error.", "error")

    return redirect(url_for("emailworkflow.email_workflows"))


@emailworkflow.route("/edit_workflow/<int:id>", methods=["GET", "POST"])
@roles_accepted(*_ROLES)
def edit_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)
    form = EditWorkflowForm(obj=workflow)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))
    text = request.args.get("text", "Email workflows")

    if form.validate_on_submit():
        try:
            workflow.send_time = form.send_time.data
            workflow.max_attachment_size = form.max_attachment_size.data
            workflow.last_edit_id = current_user.id
            from datetime import datetime

            workflow.last_edit_timestamp = datetime.now()
            db.session.commit()
            flash(f'Workflow "{workflow.name}" has been updated.', "success")
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not update workflow due to a database error.", "error")

        return redirect(url)

    return render_template_context(
        "emailworkflow/edit_workflow.html",
        workflow=workflow,
        form=form,
        url=url,
        text=text,
    )


# ---------------------------------------------------------------------------
# Task 3 – workflow items
# ---------------------------------------------------------------------------


@emailworkflow.route("/workflow_items/<int:id>")
@roles_accepted(*_ROLES)
def workflow_items(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))
    text = request.args.get("text", "Email workflows")

    return render_template_context(
        "emailworkflow/workflow_items.html",
        workflow=workflow,
        url=url,
        text=text,
    )


@emailworkflow.route("/workflow_items_ajax/<int:id>", methods=["POST"])
@roles_accepted(*_ROLES)
def workflow_items_ajax(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    base_query = db.session.query(EmailWorkflowItem).filter(
        EmailWorkflowItem.workflow_id == id
    )

    columns = {
        "name": {"order": EmailWorkflowItem.id},
        "sent": {"order": EmailWorkflowItem.sent_timestamp},
        "created": {"order": EmailWorkflowItem.creation_timestamp},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.email_workflow_item_data)


# ---------------------------------------------------------------------------
# Item actions – pause / unpause
# ---------------------------------------------------------------------------


@emailworkflow.route("/pause_item/<int:id>")
@roles_accepted(*_ROLES)
def pause_item(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )

    if item.paused:
        flash("This item is already paused.", "info")
        return redirect(url)

    try:
        item.paused = True
        db.session.commit()
        flash("Email workflow item has been paused.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not pause item due to a database error.", "error")

    return redirect(url)


@emailworkflow.route("/unpause_item/<int:id>")
@roles_accepted(*_ROLES)
def unpause_item(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )

    if not item.paused:
        flash("This item is not paused.", "info")
        return redirect(url)

    try:
        item.paused = False
        db.session.commit()
        flash("Email workflow item has been unpaused.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not unpause item due to a database error.", "error")

    return redirect(url)


# ---------------------------------------------------------------------------
# Item payload inspection
# ---------------------------------------------------------------------------

_PAYLOAD_KIND_LABELS = {
    "subject_payload": "Subject payload",
    "body_payload": "Body payload",
    "subject_override": "Subject override",
    "body_override": "Body override",
}


@emailworkflow.route("/item_payload/<int:id>/<string:kind>")
@roles_accepted(*_ROLES)
def item_payload(id, kind):
    if kind not in _PAYLOAD_KIND_LABELS:
        flash(f'Unknown payload kind "{kind}".', "error")
        return redirect(url_for("emailworkflow.email_workflows"))

    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )
    text = request.args.get("text", "Workflow items")

    raw = getattr(item, kind)
    label = _PAYLOAD_KIND_LABELS[kind]

    # pretty-print JSON payloads; plain text for override fields
    if kind in ("subject_payload", "body_payload"):
        try:
            parsed = json.loads(raw) if raw else None
            content = (
                json.dumps(parsed, indent=2, default=str)
                if parsed is not None
                else "(empty)"
            )
        except (ValueError, TypeError):
            content = raw or "(empty)"
        content_type = "json"
    else:
        content = raw or "(not set)"
        content_type = "text"

    return render_template_context(
        "emailworkflow/payload_view.html",
        item=item,
        label=label,
        content=content,
        content_type=content_type,
        url=url,
        text=text,
    )


# ---------------------------------------------------------------------------
# Task 4 – item preview
# ---------------------------------------------------------------------------


@emailworkflow.route("/preview_item/<int:id>")
@roles_accepted(*_ROLES)
def preview_item(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)
    workflow: EmailWorkflow = item.workflow
    template: EmailTemplate = workflow.template

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=workflow.id)
    )
    text = request.args.get("text", "Workflow items")

    # Decode payloads
    try:
        subject_kwargs = decode_email_payload(item.subject_payload_dict) or {}
        body_kwargs = decode_email_payload(item.body_payload_dict) or {}
    except (LookupError, Exception) as e:
        flash(f"Could not decode email payload: {e}", "error")
        return redirect(url)

    # Resolve subject: use override if set, otherwise render from template
    if item.subject_override:
        subject_str = item.subject_override
    else:
        try:
            subject_str, _ = EmailTemplate.render_content_(
                template, subject_kwargs, None
            )
        except Exception as e:
            subject_str = f"[Rendering error: {e}]"

    # Resolve HTML body: use override if set, otherwise render from template
    if item.body_override:
        html_str = item.body_override
    else:
        try:
            _, html_str = EmailTemplate.render_content_(template, None, body_kwargs)
        except Exception as e:
            html_str = f"<p>[Rendering error: {e}]</p>"

    # Convert HTML to plain text
    plain_str = HTML2Text().handle(html_str)

    # Collect recipient/sender information
    recipients = item.recipient_addresses
    from_email_addr = item.from_email
    reply_to_list = item.reply_to_list

    # Collect attachments
    attachment_list = list(item.attachments.all())

    # Build asset info list for display
    attachment_infos = []
    for att in attachment_list:
        if att.generated_asset is not None:
            asset = att.generated_asset
            asset_type = "GeneratedAsset"
            download_url = url_for("admin.download_generated_asset", asset_id=asset.id)
        elif att.submitted_asset is not None:
            asset = att.submitted_asset
            asset_type = "SubmittedAsset"
            download_url = url_for("admin.download_submitted_asset", asset_id=asset.id)
        elif att.temporary_asset is not None:
            asset = att.temporary_asset
            asset_type = "TemporaryAsset"
            download_url = None
        else:
            continue

        attachment_infos.append(
            {
                "attachment": att,
                "asset": asset,
                "asset_type": asset_type,
                "download_url": download_url,
            }
        )

    return render_template_context(
        "emailworkflow/preview_item.html",
        item=item,
        workflow=workflow,
        email_template=template,
        subject_str=subject_str,
        html_str=html_str,
        plain_str=plain_str,
        recipients=recipients,
        from_email_addr=from_email_addr,
        reply_to_list=reply_to_list,
        attachment_infos=attachment_infos,
        url=url,
        text=text,
    )
