#
# Created by David Seery on 16/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_security import login_required, current_user, logout_user, roles_required, roles_accepted

from . import student

from ..models import db, ProjectClass, ProjectClassConfig, SelectingStudent, SubmittingStudent, LiveProject, \
    Bookmark

import re
import datetime
import parse


def _verify_selector(sel):
    """
    Validate that the logged in user is allowed to perform operations on a particular SelectingStudent
    :param sel:
    :return:
    """

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if sel.user_id != current_user.id and not current_user.has_role('admin') and not current_user.has_role('root'):

        flash('You do not have permission to perform operations for this user. '
              'If you believe this is incorrect, contract the system administrator.', 'error')
        return False

    return True


def _verify_view_project(sel, project):
    """
    Validate that a particular SelectingStudent is allowed to perform operations on a given LiveProject
    :param sel:
    :param project:
    :return:
    """

    if not project in sel.config.live_projects:

        flash('You are not able to view or bookmark this project because it is not attached to your student '
              'record for this type of project. Return to the dashboard and try to access the project from there. '
              'If problems persist, contact the system administrator.', 'error')

        return False

    return True


def _verify_open(config):
    """
    Validate that a particular ProjectClassConfig is open for student selections
    :param config:
    :return:
    """

    if not config.open:

        flash('Project "{name}" is not open for student selections'.config(name=config.project_class.name), 'error')

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

        enrollments.append((config, sel, sub))

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


@student.route('/view_project/<int:sid>/<int:pid>')
@roles_accepted('student', 'admin', 'root')
def view_project(sid, pid):
    """
    View a specific project
    :param sid:
    :param pid:
    :return:
    """

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not _verify_selector(sel):
        return redirect(url_for('student.dashboard'))

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify student is allowed to view this live project
    if not _verify_view_project(sel, project):
        return redirect(url_for('student.dashboard'))

    # update page views
    if project.page_views is None:
        project.page_views = 1
    else:
        project.page_views += 1

    now = datetime.datetime.today()
    project.last_view = now
    db.session.commit()

    # build list of keywords
    keywords = [ kw.strip() for kw in re.split(";.", project.keywords) ]

    return render_template('student/show_project.html', title=project.name, sel=sel, project=project, keywords=keywords)


@student.route('/add_bookmark/<int:sid>/<int:pid>')
@roles_accepted('student', 'admin', 'root')
def add_bookmark(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not _verify_selector(sel):
        return redirect(request.referrer)

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify project is open
    if not _verify_open(project.config):
        return redirect(request.referrer)

    # verify student is allowed to view this live project
    if not _verify_view_project(sel, project):
        return redirect(request.referrer)

    # add bookmark
    if not sel.bookmarks.filter_by(liveproject_id=pid).first():

        bm = Bookmark(user_id=sid, liveproject_id=pid, rank=sel.bookmarks.count()+1)
        db.session.add(bm)
        db.session.commit()

    return redirect(request.referrer)


@student.route('/remove_bookmark/<int:sid>/<int:pid>')
@roles_accepted('student', 'admin', 'root')
def remove_bookmark(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not _verify_selector(sel):
        return redirect(request.referrer)

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify project is open
    if not _verify_open(project.config):
        return redirect(request.referrer)

    # verify student is allowed to view this live project
    if not _verify_view_project(sel, project):
        return redirect(request.referrer)

    # remove bookmark
    bm = sel.bookmarks.filter_by(liveproject_id=pid).first()

    if bm:
        sel.bookmarks.remove(bm)
        db.session.commit()

    return redirect(request.referrer)


@student.route('/request_confirm/<int:sid>/<int:pid>')
@roles_accepted('student', 'admin', 'root')
def request_confirmation(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not _verify_selector(sel):
        return redirect(request.referrer)

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify project is open
    if not _verify_open(project.config):
        return redirect(request.referrer)

    # verify student is allowed to view this live project
    if not _verify_view_project(sel, project):
        return redirect(request.referrer)

    # check if confirmation has already been issued
    if sel in project.confirmed_students:

        flash('Confirmation has already been issued for project "{n}"'.format(n=project.name), 'info')
        return redirect(request.referrer)

    # check if confirmation is already pending
    if sel in project.confirm_waiting:

        flash('Confirmation is already pending for project "{n}"'.format(n=project.name), 'info')
        return redirect(request.referrer)

    # add confirm request
    project.confirm_waiting.append(sel)
    db.session.commit()

    return redirect(request.referrer)


@student.route('/cancel_confirm/<int:sid>/<int:pid>')
@roles_accepted('student', 'admin', 'root')
def cancel_confirmation(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not _verify_selector(sel):
        return redirect(request.referrer)

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify project is open
    if not _verify_open(project.config):
        return redirect(request.referrer)

    # verify student is allowed to view this live project
    if not _verify_view_project(sel, project):
        return redirect(request.referrer)

    # check if confirmation has already been issued
    if sel in project.confirmed_students:

        flash('Confirmation has already been issued for project "{n}"'.format(n=project.name), 'info')
        return redirect(request.referrer)

    # remove confirm request if one exists
    if sel in project.confirm_waiting:
        project.confirm_waiting.remove(sel)
        db.session.commit()

    return redirect(request.referrer)


def _demap_project(item_id):

    result = parse.parse('P{configid}-{pid}', item_id)

    return int(result['pid'])


@student.route('update_ranking', methods=['GET', 'POST'])
@roles_accepted('student', 'admin', 'root')
def update_ranking():

    data = request.get_json()

    # discard if request is ill-formed
    if 'ranking' not in data or 'configid' not in data or 'sid' not in data:

        return jsonify({'status': 'ill_formed'})

    config_id = data['configid']
    sid = data['sid']
    ranking = data['ranking']

    config = ProjectClassConfig.query.filter_by(id=config_id).first()
    sel = SelectingStudent.query.filter_by(id=sid).first()

    if config is None or sel is None:

        return jsonify({'status': 'data_missing'})

    # check logged-in user is eligible to modify ranking data
    if current_user.id != sel.user.id:

        return jsonify({'status': 'insufficient_privileges'})

    projects = map(_demap_project, ranking)

    rmap = {}
    index = 1
    for p in projects:
        rmap[p] = index
        index += 1

    # update ranking
    for bookmark in sel.bookmarks:
        bookmark.rank = rmap[bookmark.liveproject.id]
    db.session.commit()

    # work out which HTML elements to make visible and which to hide, based on validity of this selection
    if sel.is_valid_selection:
        hide_elt = 'P{config}-invalid-message'.format(config=config.id)
        reveal_elt = 'P{config}-valid-message'.format(config=config.id)
    else:
        hide_elt = 'P{config}-valid-message'.format(config=config.id)
        reveal_elt = 'P{config}-invalid-message'.format(config=config.id)

    return jsonify({'status': 'success', 'hide': hide_elt, 'reveal': reveal_elt})
