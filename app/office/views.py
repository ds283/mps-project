#
# Created by David Seery on 16/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, request, redirect, url_for, flash
from flask_security import current_user, roles_required

from . import office

from ..database import db
from ..models import User
from .forms import OfficeSettingsForm
from ..shared.utils import home_dashboard


@office.route('/dashboard')
@roles_required('office')
def dashboard():
    """
    Render dashboard for an office user
    :return:
    """

    return render_template('office/dashboard.html')


@office.route('/settings', methods=['GET', 'POST'])
@roles_required('office')
def settings():
    """
    Edit settings for an office user
    :return:
    """
    user = User.query.get_or_404(current_user.id)

    form = OfficeSettingsForm(obj=user)
    form.user = user

    if form.validate_on_submit():
        user.theme = form.theme.data

        flash('All changes saved', 'success')
        db.session.commit()

        return home_dashboard()

    else:
        # fill in fields that need data from 'User' and won't have been initialized from obj=data
        if request.method == 'GET':
            form.theme.data = user.theme

    return render_template('office/settings.html', settings_form=form, user=user)
