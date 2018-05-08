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

from . import auth


@auth.route('/logout')
def logout():
    """
    Log out the current user
    """

    logout_user()
    flash("You have been logged out")
    return redirect(url_for('home.dashboard'))


@auth.route('/logged_out')
def logged_out():
    """
    Inform the user that an unrecoverable error has occurred, and they have been logged out.
    Assume any error message has already been posted via flash.
    :return: HTML string
    """

    logout_user()
    return render_template('auth/error_logout.html')
