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
from flask_security import login_required, current_user, logout_user, roles_required, roles_accepted

from . import student

from ..models import db, ProjectClass, ProjectClassConfig, SelectingStudent, SubmittingStudent, LiveProject


def _verify_selector(sel):

    # verify the logged-in user is allowed to view this SelectingStudent
    if sel.user_id != current_user.id and not current_user.has_role('admin') and not current_user.has_role('root'):

        flash('You do not have permission to open the browse view for this user.', 'error')
        return False

    return True


@student.route('/dashboard')
@roles_accepted('student', 'admin', 'root')
def dashboard():
    """
    Render dashboard for a student user
    :return:
    """

    pcs = []

    for item in current_user.selecting.filter_by(retired=False).all():

        pclass = item.config.project_class
        if pclass not in pcs:
            pcs.append(pclass)

    for item in current_user.submitting.filter_by(retired=False).all():

        pclass = item.config.project_class
        if pclass not in pcs:
            pcs.append(pclass)

    enrollments = []
    for item in pcs:

        config = item.configs.order_by(ProjectClassConfig.year.desc()).first()

        select_q = config.selecting_students.filter_by(retired=False, user_id=current_user.id)

        if select_q.count() > 1:
            flash('Multiple live "select" records exist for your account. Please contact '
                  'the system administrator', 'error')

        sel = select_q.first()

        submit_q = config.submitting_students.filter_by(retired=False, user_id=current_user.id)

        if submit_q.count() > 1:
            flash('Multiple live "submit" records exist for your account. Please contact '
                  'the system administrator', 'error')

        sub = submit_q.first()

        enrollments.append((config,sel,sub))

    pclasses = ProjectClass.query.filter_by(active=True)

    return render_template('student/dashboard.html', enrollments=enrollments, pclasses=pclasses)


@student.route('/browse_projects/<int:id>')
@roles_accepted('student', 'admin', 'root')
def browse_projects(id):
    """
    Browse the live project table for a particular ProjectClassConfig
    :param id:
    :return:
    """

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # verify the logged-in user is allowed to view this SelectingStudent
    if not _verify_selector(sel):
        return redirect(url_for('student.dashboard'))

    return render_template('student/browse_projects.html', sel=sel, config=sel.config,
                           projects=sel.config.live_projects)


@student.route('/view_project/<int:selid>/<int:projid>')
@roles_accepted('student', 'admin', 'root')
def view_project(selid, projid):
    """
    View a specific project
    :param selid:
    :param projid:
    :return:
    """

    # selid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(selid)

    # verify the logged-in user is allowed to view this SelectingStudent
    if not _verify_selector(sel):
        return redirect(url_for('student.dashboard'))

    # projid is the id for a LiveProject
    live_project = LiveProject.query.get_or_404(projid)

    # update page views
    if live_project.page_views is None:
        live_project.page_views = 1
    else:
        live_project.page_views += 1
    db.session.commit()

    return render_template('student/show_project.html', sel=sel, project=live_project)
