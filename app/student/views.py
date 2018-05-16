#
# Created by David Seery on 16/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash
from flask_security import login_required, current_user, logout_user, roles_required

from . import student


@student.route('/dashboard')
@roles_required('student')
def dashboard():
    """
    Render dashboard for a student user
    :return:
    """

    return render_template('student/dashboard.html')
