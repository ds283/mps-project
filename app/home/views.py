#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security import login_required

from . import home

from ..shared.utils import home_dashboard


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
