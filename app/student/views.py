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
    Bookmark, MessageOfTheDay, ResearchGroup, SkillGroup

import app.ajax as ajax

import re
from datetime import date, datetime
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

        flash('Project "{name}" is not open for student selections'.format(name=config.project_class.name), 'error')

        return False

    return True


@student.route('/dashboard')
@roles_accepted('student', 'admin', 'root')
def dashboard():
    """
    Render dashboard for a student user
    :return:
    """

    # build list of all project classes for which this student has roles
    pcs = []

    for item in current_user.selecting.filter_by(retired=False).all():

        pclass = item.config.project_class
        if pclass.active and pclass not in pcs:
            pcs.append(pclass)

    for item in current_user.submitting.filter_by(retired=False).all():

        pclass = item.config.project_class
        if pclass.active and pclass not in pcs:
            pcs.append(pclass)

    # map list of project classes into ProjectClassConfig instance, and selector/submitter cards
    enrollments = []
    for item in pcs:

        # extract live configuration for this project class
        config = item.configs.order_by(ProjectClassConfig.year.desc()).first()

        # determine whether this student has a selector role for this project class
        select_q = config.selecting_students.filter_by(retired=False, user_id=current_user.id)

        # TODO: consider performance impact of count() here. Is there a better alternative?
        if select_q.count() > 1:
            flash('Multiple live "selector" records exist for "{pclass}" on your account. Please contact '
                  'the system administrator'.format(pclass=item.name), 'error')

        sel = select_q.first()

        # determine whether this student has a submitter role for this project class
        submit_q = config.submitting_students.filter_by(retired=False, user_id=current_user.id)

        # TODO: consider performance impact of count() here. Is there a better alternative?
        if submit_q.count() > 1:
            flash('Multiple live "submitter" records exist for "{pclass}" on your account. Please contact '
                  'the system administrator'.format(pclass=item.name), 'error')

        sub = submit_q.first()

        enrollments.append((config, sel, sub))

    # list of all project classes used to generate a simple informational dashboard in the event
    # that this student doesn't have any live selector or submitter roles
    pclasses = ProjectClass.query.filter_by(active=True)

    # build list of system messages to consider displaying
    messages = []
    for message in MessageOfTheDay.query.filter(MessageOfTheDay.show_students,
                                                ~MessageOfTheDay.dismissed_by.any(id=current_user.id)).all():

        include = message.project_classes.first() is None
        if not include:
            for pcl in message.project_classes:
                if pcl in pcs:
                    include = True
                    break

        if include:
            messages.append(message)

    return render_template('student/dashboard.html', enrolled_classes=pcs, enrollments=enrollments, pclasses=pclasses,
                           messages=messages)


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

    groups = ResearchGroup.query.order_by(ResearchGroup.name.asc())
    skills = SkillGroup.query.order_by(SkillGroup.name.asc())

    return render_template('student/browse_projects.html', sel=sel, config=sel.config,
                           groups=groups, skills=skills)


@student.route('/projects_ajax/<int:id>')
@roles_accepted('student', 'admin', 'root')
def projects_ajax(id):
    """
    Ajax data point for live projects table
    :param id:
    :return:
    """

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # verify the logged-in user is allowed to view this SelectingStudent
    if not _verify_selector(sel):
        return jsonify({})

    projects = []

    for item in sel.config.live_projects:

        append = True

        if sel.group_filters is not None and sel.group_filters.first() is not None:

            # check if any of the items in the filter list matches this project's group affiliation
            match = False

            for group in sel.group_filters:
                if item.group_id == group.id:
                    match = True
                    break

            # nothing matched, kill append
            if not match:
                append = False

        if append and sel.skill_filters is not None and sel.skill_filters.first() is not None:

            # check if any of the items in the skill list matches one of this project's transferable skills
            match = False

            for skill in sel.skill_filters:
                inner_match = False

                for sk in item.skills:
                    if sk.group_id == skill.id:
                        inner_match = True
                        break

                if inner_match:
                    match = True
                    break

            if not match:
                append = False

        if append:
            projects.append(item)


    return ajax.student.liveprojects_data(sel, projects)


@student.route('/add_group_filter/<int:sel_id>/<int:id>')
@roles_accepted('student')
def add_group_filter(sel_id, id):

    group = ResearchGroup.query.get_or_404(id)
    sel = SelectingStudent.query.get_or_404(sel_id)

    if group not in sel.group_filters:
        sel.group_filters.append(group)
        db.session.commit()

    return redirect(request.referrer)


@student.route('/remove_group_filter/<int:sel_id>/<int:id>')
@roles_accepted('student')
def remove_group_filter(sel_id, id):

    group = ResearchGroup.query.get_or_404(id)
    sel = SelectingStudent.query.get_or_404(sel_id)

    if group in sel.group_filters:
        sel.group_filters.remove(group)
        db.session.commit()

    return redirect(request.referrer)


@student.route('/add_skill_filter/<int:sel_id>/<int:id>')
@roles_accepted('student')
def add_skill_filter(sel_id, id):

    skilll = SkillGroup.query.get_or_404(id)
    sel = SelectingStudent.query.get_or_404(sel_id)

    if skilll not in sel.skill_filters:
        sel.skill_filters.append(skilll)
        db.session.commit()

    return redirect(request.referrer)


@student.route('/remove_skill_filter/<int:sel_id>/<int:id>')
@roles_accepted('student')
def remove_skill_filter(sel_id, id):

    skill = SkillGroup.query.get_or_404(id)
    sel = SelectingStudent.query.get_or_404(sel_id)

    if skill in sel.skill_filters:
        sel.skill_filters.remove(skill)
        db.session.commit()

    return redirect(request.referrer)


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

    project.last_view = datetime.today()
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
