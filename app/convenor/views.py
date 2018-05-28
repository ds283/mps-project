#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app, render_template, redirect, url_for, flash, request
from flask_security import login_required, roles_required, roles_accepted, current_user

from ..models import db, MainConfig, User, FacultyData, StudentData, ResearchGroup, DegreeType, DegreeProgramme, \
    TransferableSkill, ProjectClass, ProjectClassConfig, LiveProject, SelectingStudent, SubmittingStudent, \
    Supervisor, Project

from ..utils import get_current_year

from . import convenor

from ..faculty.forms import AddProjectForm, EditProjectForm, RolloverForm, GoLiveForm, CloseStudentSelectionsForm, \
    IssueFacultyConfirmRequestForm, ConfirmAllRequestsForm
from ..faculty.views import _confirm, _cancel_confirm, _deconfirm, _deconfirm_to_pending, _validate_open

import re
from datetime import date, datetime, timedelta


_ConvenorDashboardSettingsTab=1
_ConvenorDashboardProjectsTab=2
_ConvenorDashboardFacultyTab=3


def _validate_administrator():
    """
    Ensure that user in an administrator
    :return:
    """

    if not current_user.has_role('admin') and not current_user.has_role('root'):

        flash('Only administrative users can view unattached projects.')
        return False

    return True


def _validate_convenor(pclass):
    """
    Validate that the logged-in user is privileged to view a convenor dashboard
    :param pclass: Project class model instance
    :return: True/False
    """

    # if logged in user is convenor for this class, or is an admin user, then all is OK
    if pclass.convenor_id != current_user.id \
        and not current_user.has_role('admin') \
        and not current_user.has_role('root'):

        flash('Convenor actions are available only to project convenors and administrative users.')
        return False

    return True


@convenor.route('/dashboard/<int:id>/<int:tabid>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def dashboard(id, tabid):

    if id == 0:

        return _render_unattached()

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build forms
    golive_form = GoLiveForm(request.form)
    issue_form = IssueFacultyConfirmRequestForm(request.form)

    if config.requests_issued:

        issue_form.requests_issued.label.text = 'Save changes'

    if request.method == 'GET':

        if config.request_deadline is not None:
            issue_form.request_deadline.data = config.request_deadline
        else:
            issue_form.request_deadline.data = date.today() + timedelta(weeks=6)

        if config.live_deadline is not None:
            golive_form.live_deadline.data = config.live_deadline
        else:
            golive_form.live_deadline.data = date.today() + timedelta(weeks=6)

    # build list of all active faculty, together with their FacultyData records
    faculty = db.session.query(User, FacultyData).filter(User.active).join(FacultyData, FacultyData.id==User.id)

    # restrict to number of faculty with zero available projects
    faculty_enrolled = faculty.filter(FacultyData.enrollments.any(id=pclass.id))

    # count number of faculty enrolled on this project
    fac_count = faculty_enrolled.count()

    fac_nooffer = 0
    for item in faculty_enrolled.all():
        if item.FacultyData.projects_offered(pclass) == 0:
            fac_nooffer += 1

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False)

    # build a list of live students submitting work for evaluation in this project class
    submitters = config.submitting_students.filter_by(retired=False)

    return render_template('convenor/dashboard.html',
                           golive_form=golive_form, issue_form=issue_form,
                           pclass=pclass, config=config, current_year=current_year, tabid=tabid,
                           projects=pclass.projects, faculty=faculty, fac_count=fac_count, fac_nooffer=fac_nooffer,
                           selectors=selectors, submitters=submitters)


@convenor.route('/add_project/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_project(pclass_id):

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not _validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not _validate_convenor(pclass):
            return redirect(request.referrer)

    # set up form
    form = AddProjectForm(request.form, convenor_editing=True)

    if form.validate_on_submit():

        data = Project(name=form.name.data,
                       keywords=form.keywords.data,
                       active=True,
                       owner=form.owner.data,
                       group=form.group.data,
                       project_classes=form.project_classes.data,
                       skills=[],
                       programmes=[],
                       meeting_reqd=form.meeting.data,
                       capacity=form.capacity.data,
                       enforce_capacity=form.enforce_capacity.data,
                       team=form.team.data,
                       description=form.description.data,
                       reading=form.reading.data,
                       creator_id=current_user.id,
                       creation_timestamp=datetime.now())

        # ensure that list of preferred degree programmes is consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        owner = data.owner.faculty_data
        for pclass in data.project_classes:

            if owner not in pclass.enrolled_faculty.all():

                owner.enrollments.append(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.build_name(), pclass=pclass.name))

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('convenor.dashboard', id=pclass_id, tabid=_ConvenorDashboardProjectsTab))

    return render_template('faculty/edit_project.html', project_form=form, pclass_id=pclass_id, title='Add new project')


@convenor.route('/edit_project/<int:id>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_project(id, pclass_id):

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not _validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not _validate_convenor(pclass):
            return redirect(request.referrer)

    # set up form
    data = Project.query.get_or_404(id)

    form = EditProjectForm(obj=data, convenor_editing=True)
    form.project = data

    if form.validate_on_submit():

        data.name = form.name.data
        data.owner = form.owner.data
        data.keywords = form.keywords.data
        data.group = form.group.data
        data.project_classes = form.project_classes.data
        data.meeting_reqd = form.meeting.data
        data.capacity = form.capacity.data
        data.enforce_capacity = form.enforce_capacity.data
        data.team = form.team.data
        data.description = form.description.data
        data.reading = form.reading.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        # ensure that list of preferred degree programmes is now consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        owner = data.owner.faculty_data
        for pclass in data.project_classes:

            if owner not in pclass.enrolled_faculty.all():

                owner.enrollments.append(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.build_name(), pclass=pclass.name))

        db.session.commit()

        return redirect(url_for('convenor.dashboard', id=pclass_id, tabid=_ConvenorDashboardProjectsTab))

    return render_template('faculty/edit_project.html', project_form=form, project=data, pclass_id=pclass_id, title='Edit project details')


@convenor.route('/make_project_active/<int:id>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def make_project_active(id, pclassid):

    # get project details
    data = Project.query.get_or_404(id)

    # get project class details
    pclass = ProjectClass.query.get_or_404(pclassid)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data.enable()
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclassid, tabid=2))


@convenor.route('/make_project_inactive/<int:id>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def make_project_inactive(id, pclassid):

    # get project details
    data = Project.query.get_or_404(id)

    # get project class details
    pclass = ProjectClass.query.get_or_404(pclassid)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data.disable()
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclassid, tabid=2))


@convenor.route('/attach_skills/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_skills(id, pclass_id):

    # get project details
    data = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not _validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not _validate_convenor(pclass):
            return redirect(request.referrer)

    # get list of active skills
    skills = TransferableSkill.query.filter_by(active=True).order_by(TransferableSkill.name)

    return render_template('convenor/attach_skills.html', data=data, skills=skills, pclass_id=pclass_id)


@convenor.route('/attach_programmes/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_programmes(id, pclass_id):

    # get project details
    data = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not _validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not _validate_convenor(pclass):
            return redirect(request.referrer)

    q = data.available_degree_programmes

    return render_template('convenor/attach_programmes.html', data=data, programmes=q.all(), pclass_id=pclass_id)


@convenor.route('/issue_confirm_requests/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def issue_confirm_requests(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    issue_form = IssueFacultyConfirmRequestForm(request.form)

    if issue_form.is_submitted() and issue_form.requests_issued.data is True:

        # set request deadline and issue requests if needed

        # only generate requests if they haven't been issued; subsequent clicks might be changes to deadline
        if not config.requests_issued:

            config.generate_golive_requests()
            requests = config.golive_required.count()
            plural = 's'
            if requests == 0:
                plural = ''

            flash('{n} confirmation request{plural} have been issued'.format(n=requests, plural=plural))

        config.requests_issued = True
        config.request_deadline = issue_form.request_deadline.data

        db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=1))


def _render_unattached():

    # special-case of unattached projects; reject user if not administrator
    if not _validate_administrator():
        return redirect(request.referrer)

    projects = [proj for proj in Project.query.all() if not proj.offerable]

    return render_template('convenor/unattached_dashboard.html', projects=projects)


@convenor.route('/force_confirm_all/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def force_confirm_all(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    for item in config.golive_required.all():

        config.golive_required.remove(item)

    db.session.commit()

    flash('All outstanding confirmation requests have been removed.', 'success')

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=1))


@convenor.route('/go_live/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'route')
def go_live(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    form = GoLiveForm(request.form)

    if form.is_submitted():

        # ensure there are no outstanding confirm requests
        if config.golive_required.first() is not None:

            flash('Cannot yet go live for {name} {yeara}-{yearb}'
                  ' because some confirmation requests are outstanding. '
                  'If needed, force all confirmations and try again.'.format(
                    name=pclass.name, yeara=config.year, yearb=config.year+1),
                  'error')

            return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=1))

        # going live consists of copying all tables for this project to the live project table,
        # in alphabetical order
        projects = pclass.projects.filter(Project.active).join(User).order_by(User.last_name, User.first_name)

        if projects.count() == 0:

            flash('Cannot yet go live for {name} {yeara}-{yearb} '
                  'because there are no available projects.'.format(
                    name=pclass.name, yeara=config.year, yearb=config.year+1),
                  'error')

            return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=1))

        number = 1
        for item in projects.all():

            # notice that this generates a LiveProject record ONLY FOR THIS PROJECT CLASS;
            # all project classes need their own LiveProject record
            live_item = LiveProject(config_id=config.id,
                                    creator_id=current_user.id,
                                    timestamp=datetime.now(),
                                    number=number,
                                    name=item.name,
                                    keywords=item.keywords,
                                    owner_id=item.owner_id,
                                    group_id=item.group_id,
                                    skills=item.skills,
                                    capacity=item.capacity,
                                    enforce_capacity=item.enforce_capacity,
                                    meeting_reqd=item.meeting_reqd,
                                    team=item.team,
                                    description=item.description,
                                    reading=item.reading,
                                    page_views=0,
                                    last_view=None)
            db.session.add(live_item)
            number += 1

        config.live = True
        config.live_deadline = form.live_deadline.data
        config.golive_id = current_user.id
        config.golive_timestamp = datetime.now()

        db.session.commit()

        flash('{name} {yeara}-{yearb} is now live'.format(name=pclass.name, yeara=config.year, yearb=config.year+1), 'success')

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=1))


@convenor.route('/close_selections/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'route')
def close_selections(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    config.closed = True
    config.closed_id = current_user.id
    config.closed_timestamp = datetime.now()

    db.session.commit()

    flash('Student selections for{name} {yeara}-{yearb} have now been closed'.format(name=pclass.name, yeara=config.year, yearb=config.year+1), 'success')

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=1))


@convenor.route('/enroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def enroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.add_enrollment(pclass)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclassid, tabid=_ConvenorDashboardFacultyTab))


@convenor.route('/unenroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def unenroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.remove_enrollment(pclass)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclassid, tabid=_ConvenorDashboardFacultyTab))


@convenor.route('/confirm/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def confirm(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))

    if _confirm(sel, project):
        db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))


@convenor.route('/deconfirm/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def deconfirm(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))

    if _deconfirm(sel, project):
        db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))


@convenor.route('/deconfirm_to_pending/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def deconfirm_to_pending(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))

    if _deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))


@convenor.route('/cancel_confirm/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def cancel_confirm(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))

    if _cancel_confirm(sel, project):
        db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=tabid))


@convenor.route('/project_confirm_all/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_confirm_all(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not _validate_convenor(pclass):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(project.config):
        return redirect(url_for('convenor.dashboard', id=project.config.id, tabid=6))

    for item in project.confirm_waiting:
        if item not in project.confirmed_students:
            project.confirmed_students.append(item)
        project.confirm_waiting.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=6))


@convenor.route('/project_clear_requests/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_clear_requests(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not _validate_convenor(pclass):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(project.config):
        return redirect(url_for('convenor.dashboard', id=project.config.id, tabid=6))

    for item in project.confirm_waiting:
        project.confirm_waiting.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=6))


@convenor.route('/project_remove_confirms/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_remove_confirms(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not _validate_convenor(pclass):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(project.config):
        return redirect(url_for('convenor.dashboard', id=project.config.id, tabid=6))

    for item in project.confirmed_students:
        project.confirmed_students.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=6))


@convenor.route('/project_make_all_confirms_pending/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_make_all_confirms_pending(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not _validate_convenor(pclass):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(project.config):
        return redirect(url_for('convenor.dashboard', id=project.config.id, tabid=6))

    for item in project.confirmed_students:
        if item not in project.confirm_waiting:
            project.confirm_waiting.append(item)
        project.confirmed_students.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=pclass.id, tabid=6))


@convenor.route('/student_confirm_all/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_confirm_all(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))

    for item in sel.confirm_requests:
        if item not in sel.confirmed:
            sel.confirmed.append(item)
        sel.confirm_requests.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))


@convenor.route('/student_remove_confirms/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_remove_confirms(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))

    for item in sel.confirmed:
        sel.confirmed.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))


@convenor.route('/student_clear_requests/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_clear_requests(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))

    for item in sel.confirm_requests:
        sel.confirm_requests.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))


@convenor.route('/student_make_all_confirms_pending/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_make_all_confirms_pending(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))

    for item in sel.confirmed:
        if item not in sel.confirm_requests:
            sel.confirm_requests.append(item)
        sel.confirmed.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))


@convenor.route('/student_clear_bookmarks/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_clear_bookmarks(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.dashboard'))

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))

    for item in sel.bookmarks:
        db.session.remove(item)
    db.session.commit()

    return redirect(url_for('convenor.dashboard', id=sel.config.id, tabid=4))


@convenor.route('/rollover/<int:pid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'route')
def rollover(pid, configid):

    # pid is a ProjectClass
    pclass = ProjectClass.query.get_or_404(pid)

    if not pclass.active:
        flash('{name} is not an active project class'.format(name=pclass.name), 'error')
        return redirect(url_for('faculty.dashboard'))

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not _validate_convenor(pclass):
        return redirect(url_for('faculty.dashboard'))

    # get current config record and retire all IDs
    current_config = ProjectClassConfig.query.get_or_404(configid)

    for item in current_config.selecting_students:

        item.retired = True

    for item in current_config.submitting_students:

        item.retired = True


    # get new, rolled-over academic year
    current_year = get_current_year()

    # generate a new ProjectClassConfig for this year
    new_config = ProjectClassConfig(year=current_year,
                                    pclass_id=pid,
                                    creator_id=current_user.id,
                                    timestamp=datetime.now(),
                                    requests_issued=False,
                                    request_deadline=None,
                                    live=False,
                                    live_deadline=None,
                                    closed=False,
                                    submission_period=1)
    db.session.add(new_config)

    # generate SubmittingStudent records for each student who will be in the correct submitting year
    for student in StudentData.query.all():

        academic_year = current_year - student.cohort + 1

        if pclass.year - 1 <= academic_year < pclass.year + pclass.extent - 1 \
                and (pclass.selection_open_to_all or student.programme in pclass.programmes):

            # will be a selecting student
            selector = SelectingStudent(config_id=new_config.id,
                                        user_id=student.user.id,
                                        retired=False)
            db.session.add(selector)

        if pclass.year <= academic_year < pclass.year + pclass.extent \
                and student.programme in pclass.programmes:

            # will be a submitting student
            submittor = SubmittingStudent(config_id=new_config.id,
                                          user_id=student.user.id,
                                          retired=False)
            db.session.add(submittor)

    db.session.commit()

    flash('{name} has been rolled over to {yeara}-{yearb}'.format(
        name=pclass.name, yeara=current_year, yearb=current_year+1), 'success')

    return redirect(url_for('convenor.dashboard', id=pid, tabid=1))
