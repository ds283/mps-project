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
@login_required
def homepage():
    """
    By default the homepage redirects to the dashboard, which will force a login if the user
    isn't authenticated
    :return: HTML string
    """

    # after logging in, simply redirect to the appropriate dashboard
    if current_user.has_role('faculty'):

        return redirect(url_for('faculty.dashboard'))

    elif current_user.has_role('student'):

        return redirect(url_for('student.dashboard'))

    elif current_user.has_role('office'):

        return redirect(url_for('office.dashboard'))

    else:

        flash('Your role could not be identified. Please contact the system administrator.')
        return redirect(url_for('auth.logged_out'))
