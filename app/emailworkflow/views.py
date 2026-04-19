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
from datetime import datetime

from celery import chain
from flask import current_app, flash, redirect, render_template_string, request, url_for
from flask_security import current_user, roles_accepted
from html2text import HTML2Text
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax

from ..database import db
from ..models import EmailWorkflow, EmailWorkflowItem, User
from ..models.emails import EmailTemplate
from ..shared.context.global_context import render_template_context
from ..shared.email_templates import clone_email_template
from ..shared.workflow_logging import log_db_commit
from ..task_queue import register_task
from ..tasks.email_workflow import decode_email_payload
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from . import emailworkflow
from .forms import EditWorkflowForm

_ROLES = ("root", "admin", "office", "email")


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

    base_query = db.session.query(EmailWorkflow).outerjoin(
        User, EmailWorkflow.creator_id == User.id
    )

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
        "name": {
            "order": EmailWorkflow.name,
            "search": EmailWorkflow.name,
            "search_collation": "utf8_general_ci",
        },
        "creator_first_name": {
            "search": User.first_name,
            "search_collation": "utf8_general_ci",
        },
        "creator_last_name": {
            "search": User.last_name,
            "search_collation": "utf8_general_ci",
        },
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

    if workflow.completed:
        flash("Cannot pause a completed workflow.", "error")
        return redirect(url_for("emailworkflow.email_workflows"))

    if workflow.paused:
        flash("This workflow is already paused.", "info")
        return redirect(url_for("emailworkflow.email_workflows"))

    try:
        workflow.paused = True
        log_db_commit(f'Paused email workflow "{workflow.name}"', user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not pause workflow due to a database error.", "error")

    return redirect(url_for("emailworkflow.email_workflows"))


@emailworkflow.route("/unpause_workflow/<int:id>")
@roles_accepted(*_ROLES)
def unpause_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    if workflow.completed:
        flash("Cannot unpause a completed workflow.", "error")
        return redirect(url_for("emailworkflow.email_workflows"))

    if not workflow.paused:
        flash("This workflow is not paused.", "info")
        return redirect(url_for("emailworkflow.email_workflows"))

    try:
        workflow.paused = False
        log_db_commit(f'Unpaused email workflow "{workflow.name}"', user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not unpause workflow due to a database error.", "error")

    return redirect(url_for("emailworkflow.email_workflows"))


@emailworkflow.route("/confirm_delete_workflow/<int:id>")
@roles_accepted(*_ROLES)
def confirm_delete_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))

    item_count = workflow.items.count()

    title = f'Delete workflow "{workflow.name}"'
    message = (
        f"<p>You are about to permanently delete workflow <strong>{workflow.name}</strong>, "
        f"which contains <strong>{item_count}</strong> item(s).</p>"
        f"<p>This action <strong>cannot be undone</strong>. "
        f"All pending items will be removed and their emails will never be delivered. "
        f"Any in-progress sends will be cancelled.</p>"
    )

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=url_for("emailworkflow.delete_workflow", id=id, url=url),
        message=message,
        submit_label="Delete workflow",
    )


@emailworkflow.route("/delete_workflow/<int:id>")
@roles_accepted(*_ROLES)
def delete_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))
    workflow_name = workflow.name

    tk_name = f'Delete email workflow "{workflow_name}"'
    task_id = register_task(tk_name, owner=current_user, description=tk_name)

    celery = current_app.extensions["celery"]
    tk = celery.tasks["app.tasks.email_workflow.delete_email_workflow"]
    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        tk.si(id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))

    seq.apply_async(task_id=task_id)

    flash(
        f'Workflow "{workflow_name}" is being deleted in the background.',
        "info",
    )
    return redirect(url)


@emailworkflow.route("/edit_workflow/<int:id>", methods=["GET", "POST"])
@roles_accepted(*_ROLES)
def edit_workflow(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))
    text = request.args.get("text", "Email workflows")

    if workflow.completed:
        flash("Cannot edit properties of a completed workflow.", "error")
        return redirect(url)

    form = EditWorkflowForm(obj=workflow)

    # Restrict the template selector to the same type and scope as the current template
    current_template = workflow.template
    # allow the filter to find inactive templates
    form.template.query_factory = lambda: (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == current_template.type,
            EmailTemplate.pclass_id == current_template.pclass_id,
            EmailTemplate.tenant_id == current_template.tenant_id,
        )
        .order_by(EmailTemplate.version.desc())
    )

    if form.validate_on_submit():
        from datetime import datetime

        try:
            workflow.send_time = form.send_time.data
            workflow.max_attachment_size = form.max_attachment_size.data
            workflow.template = form.template.data
            workflow.last_edit_id = current_user.id
            workflow.last_edit_timestamp = datetime.now()
            log_db_commit(
                f'Updated settings for email workflow "{workflow.name}"',
                user=current_user,
            )
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


@emailworkflow.route("/clone_workflow_template/<int:id>")
@roles_accepted(*_ROLES)
def clone_workflow_template(id):
    workflow: EmailWorkflow = EmailWorkflow.query.get_or_404(id)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))
    text = request.args.get("text", "Email workflows")

    if workflow.completed:
        flash("Cannot clone the template of a completed workflow.", "error")
        return redirect(
            url_for("emailworkflow.edit_workflow", id=id, url=url, text=text)
        )

    # Build the back-URL so the template editor can return to this workflow's edit page
    edit_url = url_for("emailworkflow.edit_workflow", id=id, url=url, text=text)

    pclasses = list(workflow.pclasses.all())

    if len(pclasses) == 1:
        pclass_id = pclasses[0].id
        tenant_id = None
    elif len(pclasses) > 1:
        tenants = set([p.tenant_id for p in pclasses])
        if len(tenants) == 1:
            pclass_id = None
            tenant_id = tenants.pop()
        else:
            pclass_id = None
            tenant_id = None
    else:
        pclass_id = None
        tenant_id = None

    new_template = clone_email_template(
        workflow.template, pclass_id, tenant_id, current_user
    )

    try:
        db.session.add(new_template)
        workflow.template = new_template
        workflow.last_edit_id = current_user.id
        workflow.last_edit_timestamp = datetime.now()
        log_db_commit(
            f'Cloned email template for workflow "{workflow.name}" as version {new_template.version}',
            user=current_user,
        )
        flash(
            f"Template cloned as version {new_template.version}. You can now edit it below.",
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not clone the template due to a database error.", "error")
        return redirect(edit_url)

    # Redirect to the appropriate template editor with a back-link to this edit page
    if pclass_id is not None:
        return redirect(
            url_for(
                "convenor.edit_email_template",
                pclass_id=pclass_id,
                template_id=new_template.id,
                url=edit_url,
            )
        )
    elif tenant_id is not None:
        return redirect(
            url_for(
                "tenants.edit_email_template",
                tenant_id=tenant_id,
                template_id=new_template.id,
                url=edit_url,
            )
        )
    else:
        return redirect(
            url_for(
                "admin.edit_global_email_template", id=new_template.id, url=edit_url
            )
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
    url = request.args.get("url", url_for("emailworkflow.email_workflows"))
    text = request.args.get("text", "Email workflows")

    base_query = db.session.query(EmailWorkflowItem).filter(
        EmailWorkflowItem.workflow_id == id
    )

    columns = {
        "name": {"order": EmailWorkflowItem.id},
        "sent": {"order": EmailWorkflowItem.sent_timestamp},
        "created": {"order": EmailWorkflowItem.creation_timestamp},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            lambda items: ajax.site.email_workflow_item_data(items, url, text)
        )


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

    if item.sent_timestamp is not None:
        flash("Cannot pause an item that has already been sent.", "error")
        return redirect(url)

    if item.paused:
        flash("This item is already paused.", "info")
        return redirect(url)

    try:
        item.paused = True
        log_db_commit(
            f'Paused email workflow item "{item.workflow.name}"', user=current_user
        )
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

    if item.sent_timestamp is not None:
        flash("Cannot unpause an item that has already been sent.", "error")
        return redirect(url)

    if not item.paused:
        flash("This item is not paused.", "info")
        return redirect(url)

    try:
        item.paused = False
        log_db_commit(
            f'Unpaused email workflow item "{item.workflow.name}"', user=current_user
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not unpause item due to a database error.", "error")

    return redirect(url)


# ---------------------------------------------------------------------------
# Item payload inspection
# ---------------------------------------------------------------------------


def _pretty_json(raw):
    """Return a pretty-printed JSON string, or '(empty)' if raw is None/empty."""
    try:
        parsed = json.loads(raw) if raw else None
        return (
            json.dumps(parsed, indent=2, default=str)
            if parsed is not None
            else "(empty)"
        )
    except (ValueError, TypeError):
        return raw or "(empty)"


@emailworkflow.route("/item_payloads/<int:id>")
@roles_accepted(*_ROLES)
def item_payloads(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )
    text = request.args.get("text", "Workflow items")

    return render_template_context(
        "emailworkflow/item_payloads.html",
        item=item,
        subject_payload_content=_pretty_json(item.subject_payload),
        body_payload_content=_pretty_json(item.body_payload),
        callbacks_content=_pretty_json(item.callbacks),
        url=url,
        text=text,
    )


@emailworkflow.route("/item_overrides/<int:id>")
@roles_accepted(*_ROLES)
def item_overrides(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )
    text = request.args.get("text", "Workflow items")

    return render_template_context(
        "emailworkflow/item_overrides.html",
        item=item,
        url=url,
        text=text,
    )


@emailworkflow.route("/confirm_delete_item/<int:id>")
@roles_accepted(*_ROLES)
def confirm_delete_item(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )
    text = request.args.get("text", "Workflow items")

    if item.sent_timestamp is not None:
        flash("Cannot delete an item that has already been sent.", "error")
        return redirect(url)

    recipients = item.recipient_addresses
    recipient_str = ", ".join(recipients) if recipients else "(no recipients)"

    title = f"Delete workflow item #{item.id}"
    message = (
        f"<p>You are about to delete workflow item <strong>#{item.id}</strong> "
        f"(recipients: <em>{recipient_str}</em>) from workflow "
        f"<strong>{item.workflow.name}</strong>.</p>"
        f"<p>This action <strong>cannot be undone</strong>. "
        f"If the item has not yet been sent, the email will never be delivered.</p>"
    )

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=url_for("emailworkflow.delete_item", id=id, url=url, text=text),
        message=message,
        submit_label="Delete item",
    )


@emailworkflow.route("/delete_item/<int:id>")
@roles_accepted(*_ROLES)
def delete_item(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)

    url = request.args.get("url", url_for("emailworkflow.email_workflows"))

    if item.sent_timestamp is not None:
        flash("Cannot delete an item that has already been sent.", "error")
        return redirect(url)

    workflow_id = item.workflow_id
    workflow_name = item.workflow.name if item.workflow else f"#{workflow_id}"

    try:
        db.session.delete(item)
        log_db_commit(
            f'Deleted email workflow item #{id} from workflow "{workflow_name}"',
            user=current_user,
        )
        flash(f"Workflow item #{id} has been deleted.", "info")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not delete item due to a database error.", "error")

    return redirect(url)


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


# ---------------------------------------------------------------------------
# Task 5 – item error log
# ---------------------------------------------------------------------------


@emailworkflow.route("/item_error_log/<int:id>")
@roles_accepted(*_ROLES)
def item_error_log(id):
    item: EmailWorkflowItem = EmailWorkflowItem.query.get_or_404(id)
    workflow = item.workflow

    url = request.args.get(
        "url", url_for("emailworkflow.workflow_items", id=item.workflow_id)
    )
    text = request.args.get("text", "Workflow items")

    # Error entries in descending timestamp order.
    entries = list(reversed(item.error_log_list))

    return render_template_context(
        "emailworkflow/item_error_log.html",
        item=item,
        workflow=workflow,
        entries=entries,
        url=url,
        text=text,
    )
