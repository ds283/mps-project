#
# Created by David Seery on 16/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_security import current_user, roles_required, roles_accepted
from flask_mail import Message

from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from . import student

from .forms import StudentFeedbackForm, StudentSettingsForm

from ..database import db
from ..models import ProjectClass, ProjectClassConfig, SelectingStudent, LiveProject, \
    Bookmark, MessageOfTheDay, ResearchGroup, SkillGroup, SelectionRecord, SubmissionRecord, TransferableSkill, \
    User, EmailNotification, add_notification
from ..task_queue import register_task

from ..shared.utils import home_dashboard, home_dashboard_url, filter_projects, get_count

import app.ajax as ajax

import re
from datetime import datetime, date
import parse


def _verify_submitter(rec):

    if rec.owner.student_id != current_user.id:
        flash('You do not have permission to view feedback for this user. '
              'If you believe this is incorrect, contract the system administrator.', 'error')
        return False

    return True


def _verify_selector(sel):
    """
    Validate that the logged in user is allowed to perform operations on a particular SelectingStudent
    :param sel:
    :return:
    """

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if sel.student_id != current_user.id and not current_user.has_role('admin') and not current_user.has_role('root'):
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

    if config.selector_lifecycle != ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash('Project "{name}" is not open for student selections'.format(name=config.name), 'error')
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
    pcs = set()

    if current_user.student_data is not None:
        for item in current_user.student_data.selecting.filter_by(retired=False).all():
            pclass = item.config.project_class
            if pclass.active and pclass.publish:
                pcs.add(pclass)

        for item in current_user.student_data.submitting.filter_by(retired=False).all():
            pclass = item.config.project_class
            if pclass.active and pclass.publish:
                pcs.add(pclass)

    # map list of project classes into ProjectClassConfig instance, and selector/submitter cards
    enrollments = []
    for item in pcs:
        # extract live configuration for this project class
        config = item.configs.order_by(ProjectClassConfig.year.desc()).first()

        # determine whether this student has a selector role for this project class
        select_q = config.selecting_students.filter_by(retired=False, student_id=current_user.id)

        if get_count(select_q) > 1:
            flash('Multiple live "selector" records exist for "{pclass}" on your account. Please contact '
                  'the system administrator'.format(pclass=item.name), 'error')

        sel = select_q.first()

        # determine whether this student has a submitter role for this project class
        submit_q = config.submitting_students.filter_by(retired=False, student_id=current_user.id)

        if get_count(submit_q) > 1:
            flash('Multiple live "submitter" records exist for "{pclass}" on your account. Please contact '
                  'the system administrator'.format(pclass=item.name), 'error')

        sub = submit_q.first()

        enrollments.append((config, sel, sub))

    enrollments.sort(key=lambda x: x[0].project_class.name)

    # list of all (active, published) project classes used to generate a simple informational dashboard in the event
    # that this student doesn't have any live selector or submitter roles
    pclasses = ProjectClass.query.filter_by(active=True, publish=True)

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
                           messages=messages, today=date.today())


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

    # supply list of transferable skill groups and research groups that can be filtered against
    groups = db.session.query(ResearchGroup) \
        .filter_by(active=True).order_by(ResearchGroup.name.asc()).all()

    skills = db.session.query(TransferableSkill) \
        .join(SkillGroup, SkillGroup.id == TransferableSkill.group_id) \
        .filter(TransferableSkill.active == True, SkillGroup.active == True) \
        .order_by(SkillGroup.name.asc(), TransferableSkill.name.asc()).all()

    skill_list = {}
    for skill in skills:
        if skill_list.get(skill.group.name, None) is None:
            skill_list[skill.group.name] = []
        skill_list[skill.group.name].append(skill)

    return render_template('student/browse_projects.html', sel=sel, config=sel.config,
                           groups=groups, skill_groups=sorted(skill_list.keys()), skill_list=skill_list)


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

    projects = filter_projects(sel.config.live_projects.all(),
                               sel.group_filters.all(), sel.skill_filters.all(), setter=lambda x: x.id)

    return ajax.student.liveprojects_data(sel.id, projects)


@student.route('/add_group_filter/<id>/<gid>')
@roles_accepted('student')
def add_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)
    sel = SelectingStudent.query.get_or_404(id)

    if group not in sel.group_filters:
        try:
            sel.group_filters.append(group)
            db.session.commit()
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(request.referrer)


@student.route('/remove_group_filter/<id>/<gid>')
@roles_accepted('student')
def remove_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)
    sel = SelectingStudent.query.get_or_404(id)

    if group in sel.group_filters:
        try:
            sel.group_filters.remove(group)
            db.session.commit()
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(request.referrer)


@student.route('/clear_group_filters/<id>')
@roles_accepted('student')
def clear_group_filters(id):
    sel = SelectingStudent.query.get_or_404(id)

    try:
        sel.group_filters = []
        db.session.commit()
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(request.referrer)


@student.route('/add_skill_filter/<id>/<skill_id>')
@roles_accepted('student')
def add_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)
    sel = SelectingStudent.query.get_or_404(id)

    if skill not in sel.skill_filters:
        try:
            sel.skill_filters.append(skill)
            db.session.commit()
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()


    return redirect(request.referrer)


@student.route('/remove_skill_filter/<id>/<skill_id>')
@roles_accepted('student')
def remove_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)
    sel = SelectingStudent.query.get_or_404(id)

    if skill in sel.skill_filters:
        try:
            sel.skill_filters.remove(skill)
            db.session.commit()
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(request.referrer)


@student.route('/clear_skill_filters/<id>')
@roles_accepted('student')
def clear_skill_filters(id):
    sel = SelectingStudent.query.get_or_404(id)

    try:
        sel.skill_filters = []
        db.session.commit()
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

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
    if isinstance(project.keywords, str):
        keywords = _extract_keywords(project.keywords)
    elif project.keywords is None:
        keywords = []
    else:
        try:
            keywords = _extract_keywords(project.keywords.decode('utf-8'))
        except AttributeError:
            keywords = []

    return render_template('student/show_project.html', title=project.name, sel=sel, project=project, desc=project,
                           keywords=keywords, text='project list',
                           url=url_for('student.browse_projects', id=sel.id))


def _extract_keywords(field):
    keywords = [kw.strip() for kw in re.split("[;,]", field)]
    keywords = [w for w in keywords if len(w) > 0]
    return keywords


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
    if not sel.is_project_bookmarked(project):
        bm = Bookmark(owner_id=sid, liveproject_id=pid, rank=sel.bookmarks.count()+1)
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
    if project.is_confirmed(sel):
        flash('Confirmation has already been issued for project "{n}"'.format(n=project.name), 'info')
        return redirect(request.referrer)

    # check if confirmation is already pending
    if project.is_waiting(sel):
        flash('Confirmation is already pending for project "{n}"'.format(n=project.name), 'info')
        return redirect(request.referrer)

    # add confirm request
    req = project.make_confirm_request(sel)
    db.session.add(req)
    add_notification(project.owner, EmailNotification.CONFIRMATION_REQUEST_CREATED, req, autocommit=False)

    # check if a bookmark already exists, and make one if not
    if not sel.is_project_bookmarked(project):
        bm = Bookmark(owner_id=sid, liveproject_id=pid, rank=sel.bookmarks.count()+1)
        db.session.add(bm)

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
    if project.is_confirmed(sel):
        flash('Confirmation has already been issued for project "{n}"'.format(n=project.name), 'info')
        return redirect(request.referrer)

    # remove confirm request if one exists
    if project.is_waiting(sel):
        req = project.get_confirm_request(sel)
        if req is not None:
            req.remove()
            db.session.delete(req)
            db.session.commit()

    return redirect(request.referrer)


def _demap_project(item_id):
    result = parse.parse('P{configid}-{pid}', item_id)

    return int(result['pid'])


@student.route('/update_ranking', methods=['GET', 'POST'])
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
    if current_user.id != sel.student.id:

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
        hide_elt = 'P{config}-invalid-button'.format(config=config.id)
        reveal_elt = 'P{config}-valid-button'.format(config=config.id)
    else:
        hide_elt = 'P{config}-valid-button'.format(config=config.id)
        reveal_elt = 'P{config}-invalid-button'.format(config=config.id)

    return jsonify({'status': 'success', 'hide': hide_elt, 'reveal': reveal_elt})


@student.route('/submit/<int:sid>')
@roles_required('student')
def submit(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash('You do not have permission to submit project preferences for this selector.', 'error')
        return redirect(request.referrer)

    if not sel.is_valid_selection:
        flash('The current bookmark list is not a valid set of project preferences. This is an internal error; '
              'please contact a system administrator.', 'error')
        return redirect(request.referrer)

    try:
        # delete any existing selections
        sel.selections = []

        # iterate through bookmarks, converting them to a selection set
        for bookmark in sel.bookmarks:
            # rank is based on 1
            if bookmark.rank <= sel.number_choices:
                rec = SelectionRecord(owner_id=sel.id,
                                      liveproject_id=bookmark.liveproject_id,
                                      rank=bookmark.rank,
                                      converted_from_bookmark=False,
                                      hint=SelectionRecord.SELECTION_HINT_NEUTRAL)
                sel.selections.append(rec)

        sel.submission_time = datetime.now()
        sel.submission_IP = current_user.current_login_ip

        db.session.commit()

        celery = current_app.extensions['celery']
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']

        msg = Message(subject='Your project choices have been received '
                              '({pcl})'.format(pcl=sel.config.project_class.name),
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[sel.student.user.email])

        msg.body = render_template('email/student_notifications/choices_received.txt', user=sel.student.user,
                                   pclass=sel.config.project_class, config=sel.config, sel=sel)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send project choices confirmation email '
                                                         'to {r}'.format(r=', '.join(msg.recipients)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        flash('Your project preferences were submitted successfully. '
              'A confirmation email has been sent to your registered email address.', 'info')

    except SQLAlchemyError:
        db.session.rollback()
        flash('A database error occurred during submission. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    return redirect(request.referrer)


@student.route('/clear_submission/<int:sid>')
@roles_required('student')
def clear_submission(sid):
    sel = SelectingStudent.query.get_or_404(sid)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:

        flash('You do not have permission to clear project preferences for this selector.', 'error')
        return redirect(request.referrer)

    title = 'Clear submitted preferences'
    panel_title = 'Clear submitted preferences for {name}'.format(name=sel.config.name)

    action_url = url_for('student.do_clear_submission', sid=sid)
    message = '<p>Please confirm that you wish to clear your submitted preferences for ' \
              '<strong>{name} {yeara}&ndash;{yearb}</strong>.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=sel.config.name,
                                                     yeara=sel.config.year, yearb=sel.config.year+1)
    submit_label = 'Clear submitted preferences'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@student.route('/do_clear_submission/<int:sid>')
@roles_required('student')
def do_clear_submission(sid):
    sel = SelectingStudent.query.get_or_404(sid)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash('You do not have permission to clear project preferences for this selector.', 'error')
        return home_dashboard()

    sel.selections = []
    sel.submission_time = None
    sel.submission_IP = None

    db.session.commit()
    flash('Your project preferences have been cleared successfully.', 'info')

    return home_dashboard()


@student.route('/view_selection/<int:sid>')
@roles_accepted('student', 'admin', 'root')
def view_selection(sid):

    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not _verify_selector(sel):
        return redirect(request.referrer)

    return render_template('student/choices.html', sel=sel)


@student.route('/view_feedback/<int:id>', methods=['GET', 'POST'])
@roles_accepted('student')
def view_feedback(id):
    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not _verify_submitter(record):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)
    if url is None:
        url = request.referrer

    if not record.has_feedback:
        flash('It is only possible to view feedback after the convenor has made it available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(url)

    config = record.owner.config
    period = config.get_period(record.submission_period)

    preview = request.args.get('preview', None)

    return render_template('student/dashboard/view_feedback.html', record=record, period=period,
                           text=text, url=url, preview=preview)


@student.route('/edit_feedback/<int:id>', methods=['GET', 'POST'])
@roles_accepted('student')
def edit_feedback(id):
    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not _verify_submitter(record):
        return redirect(request.referrer)

    config = record.owner.config
    period = config.get_period(record.submission_period)

    if not period.closed:
        flash('It is only possible to give feedback to your supervisor once your own marks and feedback are available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(request.referrer)

    if period.closed and record.student_feedback_submitted:
        flash('It is not possible to edit your feedback once it has been submitted', 'info')
        return redirect(request.referrer)

    form = StudentFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        record.student_feedback = form.feedback.data
        db.session.commit()

        return redirect(url)

    else:
        if request.method == 'GET':
            form.feedback.data = record.student_feedback

    return render_template('student/dashboard/edit_feedback.html', form=form,
                           submit_url=url_for('student.edit_feedback', id=id, url=url),
                           text='home dashboard', url=home_dashboard_url())


@student.route('/submit_feedback/<int:id>')
@roles_accepted('student')
def submit_feedback(id):

    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not _verify_submitter(record):
        return redirect(request.referrer)

    config = record.owner.config
    period = config.get_period(record.submission_period)

    if record.student_feedback_submitted:
        return redirect(request.referrer)

    if not period.closed:
        flash('It is only possible to give feedback to your supervisor once your own marks and feedback are available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(request.referrer)

    if not record.is_student_valid:
        flash('Cannot submit your feedback because it is incomplete.', 'info')
        return redirect(request.referrer)

    record.student_feedback_submitted = True
    record.student_feedback_timestamp = datetime.now()
    db.session.commit()

    return redirect(request.referrer)


@student.route('/settings', methods=['GET', 'POST'])
@roles_required('student')
def settings():
    """
    Edit settings for a student user
    :return:
    """
    user = User.query.get_or_404(current_user.id)

    form = StudentSettingsForm(obj=user)
    form.user = user

    if form.validate_on_submit():
        user.theme = form.theme.data

        user.group_summaries = form.group_summaries.data
        user.summary_frequency = form.summary_frequency.data

        flash('All changes saved', 'success')
        db.session.commit()

        return home_dashboard()

    else:
        # fill in fields that need data from 'User' and won't have been initialized from obj=data
        if request.method == 'GET':
            form.theme.data = user.theme

            form.group_summaries.data = user.group_summaries
            form.summary_frequency.data = user.summary_frequency

    return render_template('student/settings.html', settings_form=form, user=user)
