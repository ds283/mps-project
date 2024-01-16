#
# Created by David Seery on 2019-02-24.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, current_app
from flask_security import current_user, roles_required, roles_accepted, login_required

from . import project_approver

from .forms import EditCommentForm

from ..database import db
from ..models import ProjectDescription, DescriptionComment, EnrollmentRecord

from ..shared.utils import build_project_approval_queues, home_dashboard_url, redirect_url

import app.ajax as ajax

from datetime import datetime


@project_approver.route("/validate")
@roles_required("project_approver")
def validate():
    """
    Validate project descriptions
    :return:
    """
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None or text is None:
        url = redirect_url()
        text = "approvals dashboard"

    return render_template("project_approver/validate.html", url=url, text=text)


@project_approver.route("/validate_ajax")
@roles_required("project_approver")
def validate_ajax():
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    queues = build_project_approval_queues()
    queued = queues["queued"]

    return ajax.project_approver.validate_data(
        queued, current_user.id, url=url_for("project_approver.validate", url=url, text=text), text="project approval list"
    )


@project_approver.route("/approve/<int:id>")
@roles_required("project_approver")
def approve(id):
    record = ProjectDescription.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_VALIDATED
    # validator_id and validated_timestamp are set by validator for workflow_state
    db.session.commit()

    return redirect(url)


@project_approver.route("/reject/<int:id>")
@roles_required("project_approver")
def reject(id):
    record = ProjectDescription.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_REJECTED
    # validator_id and validated_timestamp are set by validator for workflow_state
    db.session.commit()

    return redirect(url)


@project_approver.route("/requeue/<int:id>")
@roles_required("project_approver")
def requeue(id):
    record = ProjectDescription.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_QUEUED
    # validator_id and validated_timestamp are set by validator for workflow_state
    db.session.commit()

    return redirect(url)


@project_approver.route("/return_to_owner/<int:id>")
@roles_required("project_approver")
def return_to_owner(id):
    record = ProjectDescription.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_QUEUED
    # validator_id and validated_timestamp are set by validator for workflow_state

    owner = record.parent.owner
    if owner is None:
        return redirect(url)

    names = set()

    # find project classes associated with this description
    for pcl in record.project_classes:
        config = pcl.most_recent_config

        if config is not None:
            if config.requests_issued and not config.live:
                enrollment = owner.get_enrollment_record(pcl.id)
                if enrollment is not None and enrollment.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED:
                    record.confirmed = False
                    names.add(pcl.name)

    db.session.commit()

    celery = current_app.extensions["celery"]
    revise_notify = celery.tasks["app.tasks.issue_confirm.revise_notify"]

    revise_notify.apply_async(args=(record.id, list(names), current_user.id))

    return redirect(url)


@project_approver.route("/publish_comment/<int:id>")
@roles_required("project_approver")
def publish_comment(id):
    # id is a DescriptionComment
    comment = DescriptionComment.query.get_or_404(id)

    comment.visibility = DescriptionComment.VISIBILITY_PUBLISHED_BY_APPROVALS
    db.session.commit()

    return redirect(redirect_url())


@project_approver.route("/edit_comment/<int:id>", methods=["GET", "POST"])
@login_required
def edit_comment(id):
    # id is a DescriptionComment
    comment = DescriptionComment.query.get_or_404(id)

    if current_user.id != comment.owner_id:
        flash("This comment belongs to another user. It is only possible to edit comments that you own.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    form = EditCommentForm(request.form)

    if form.validate_on_submit():
        comment.comment = form.comment.data

        vis = DescriptionComment.VISIBILITY_EVERYONE
        if current_user.has_role("project_approver"):
            if form.limit_visibility.data:
                vis = DescriptionComment.VISIBILITY_APPROVALS_TEAM
        comment.visibility = vis

        comment.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url)

    else:
        if request.method == "GET":
            form.comment.data = comment.comment
            form.limit_visibility.data = comment.visibility == DescriptionComment.VISIBILITY_APPROVALS_TEAM

    return render_template("project_approver/edit_comment.html", comment=comment, form=form, url=url)


@project_approver.route("/delete_comment/<int:id>")
@login_required
def delete_comment(id):
    # id is a DescriptionComment
    comment = DescriptionComment.query.get_or_404(id)

    if current_user.id != comment.owner_id:
        flash("This comment belongs to another user. It is only possible to edit comments that you own.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if comment.deleted:
        return redirect(url)

    title = "Delete comment"
    panel_title = "Delete comment"

    action_url = url_for("project_approver.perform_delete_comment", id=id, url=url)
    message = "<p>Are you sure that you wish to delete this comment?</p>" "<p>This action cannot be undone.</p>"
    submit_label = "Delete comment"

    return render_template(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@project_approver.route("/perform_delete_comment/<int:id>")
@login_required
def perform_delete_comment(id):
    # id is a DescriptionComment
    comment = DescriptionComment.query.get_or_404(id)

    if current_user.id != comment.owner_id:
        flash("This comment belongs to another user. It is only possible to edit comments that you own.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    if comment.deleted:
        return redirect(url)

    comment.comment = None
    comment.deleted = True
    comment.last_edit_timestamp = datetime.now()
    db.session.commit()

    return redirect(url)


@project_approver.route("/clean_comments/<int:id>")
@roles_accepted("admin", "root")
def clean_comments(id):
    # id is a ProjectDescription
    desc = ProjectDescription.query.get_or_404(id)

    desc.comments.filter_by(deleted=True).delete()
    db.session.commit()

    flash("All deleted comments have been removed from the thread.", "success")
    return redirect(redirect_url())


@project_approver.route("/rejected")
@roles_required("project_approver")
def rejected():
    """
    Review rejected project descriptions
    :return:
    """
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None or text is None:
        url = redirect_url()
        text = "approvals dashboard"

    return render_template("project_approver/review.html", url=url, text=text)


@project_approver.route("/rejected_ajax")
@roles_required("project_approver")
def rejected_ajax():
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    queues = build_project_approval_queues()
    queued = queues["rejected"]

    return ajax.project_approver.rejected_data(
        queued, current_user.id, url=url_for("project_approver.rejected", url=url, text=text), text="rejected projects review"
    )
