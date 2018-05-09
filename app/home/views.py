#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, redirect, url_for, flash
from flask_security import login_required, current_user, logout_user

from . import home

@home.route('/')
def homepage():
    """
    By default the homepage redirects to the dashboard, which will force a login if the user
    isn't authenticated
    :return: HTML string
    """

    # after logging in, simply redirect to the dashboard
    return redirect(url_for('home.dashboard'))


@home.route('/dashboard')
@login_required
def dashboard():
    """
    Render the dashboard template
    :return: HTML string
    """

    return render_template('home/dashboard.html', title="Dashboard")
