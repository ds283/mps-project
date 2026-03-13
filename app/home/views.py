#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import request
from flask_login import current_user
from flask_security import login_required

from . import home

from ..ajax.home import download_centre_data
from ..database import db
from ..models import DownloadCentreItem
from ..shared.context.global_context import render_template_context
from ..shared.utils import home_dashboard
from ..tools import ServerSideSQLHandler


@home.route("/")
@login_required
def homepage():
    """
    By default the homepage redirects to the dashboard, which will force a login if the user
    isn't authenticated
    :return: HTML string
    """

    # after logging in, simply redirect to the appropriate dashboard
    return home_dashboard()


@home.route("/download_centre")
@login_required
def download_centre():
    """
    Display the download centre for the current user, listing all DownloadCentreItem instances
    that belong to them.
    """
    return render_template_context("home/download_centre.html")


@home.route("/download_centre_ajax", methods=["POST"])
@login_required
def download_centre_ajax():
    """
    AJAX endpoint that supplies DataTables data for the download centre table.
    """
    base_query = db.session.query(DownloadCentreItem).filter(
        DownloadCentreItem.user_id == current_user.id
    )

    # None of the columns are searchable (no text-based search columns available on DownloadCentreItem),
    # so we only specify ordering keys.
    columns = {
        "name": {"order": DownloadCentreItem.generated_at},
        "generated": {"order": DownloadCentreItem.generated_at},
        "expiry": {"order": DownloadCentreItem.expire_at},
        "downloads": {"order": DownloadCentreItem.number_downloads},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(download_centre_data)
