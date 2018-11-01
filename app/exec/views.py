#
# Created by David Seery on 2018-11-01.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, redirect, url_for, flash, request, session
from flask_security import login_required, roles_required, roles_accepted, current_user, login_user

from ..database import db
from ..models import User, FacultyData, ResearchGroup

from ..shared.conversions import is_integer
from ..shared.sqlalchemy import get_count

import app.ajax as ajax

from . import exec


@exec.route('/workload')
@roles_required('exec')
def workload():
    """
    Basic workload report
    :return:
    """
    group_filter = request.args.get('group_filter')

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get('exec_workload_group_filter'):
        group_filter = session['exec_workload_group_filter']

    # write group filter into session if it is not empty
    if group_filter is not None:
        session['exec_workload_group_filter'] = group_filter

    groups = db.session.query(ResearchGroup).filter_by(active=True).all()
    return render_template('exec/workload.html', groups=groups, group_filter=group_filter)


@exec.route('/workload_ajax')
@roles_required('exec')
def workload_ajax():
    """
    AJAX data point for workload report
    :return:
    """
    group_filter = request.args.get('group_filter')

    faculty = db.session.query(FacultyData) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active)

    flag, group_value = is_integer(group_filter)
    if flag:
        faculty = faculty.filter(FacultyData.affiliations.any(id=group_value))

    return ajax.exec.workload_data(faculty)
