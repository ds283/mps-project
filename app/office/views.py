#
# Created by David Seery on 16/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import request, flash, session
from flask_security import current_user, roles_required

from . import office
from .forms import OfficeSettingsForm
from ..database import db
from ..models import User
from ..shared.context.global_context import render_template_context
from ..shared.context.root_dashboard import get_root_dashboard_data
from ..shared.utils import home_dashboard, get_approval_queue_data


@office.route("/dashboard")
@roles_required("office")
def dashboard():
    """
    Render dashboard for an office user
    :return:
    """
    pane = request.args.get("pane", None)
    if pane is None and session.get("office_dashboard_pane"):
        pane = session["office_dashboard_pane"]

    if pane != "overview" and pane != "approve":
        pane = "overview"

    if pane is not None:
        session["office_dashboard_pane"] = pane

    root_data = get_root_dashboard_data()
    approvals_data = get_approval_queue_data()

    return render_template_context("office/dashboard.html", root_data=root_data, approvals_data=approvals_data, pane=pane)


@office.route("/settings", methods=["GET", "POST"])
@roles_required("office")
def settings():
    """
    Edit settings for an office user
    :return:
    """
    user = User.query.get_or_404(current_user.id)

    form = OfficeSettingsForm(obj=user)
    form.user = user

    if form.validate_on_submit():
        user.default_license = form.default_license.data

        user.group_summaries = form.group_summaries.data
        user.summary_frequency = form.summary_frequency.data

        flash("All changes saved", "success")
        db.session.commit()

        return home_dashboard()

    return render_template_context("office/settings.html", settings_form=form, user=user)
