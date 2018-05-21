#
# Created by David Seery on 15/05/2018.
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

from . import faculty

from .forms import AddProjectForm, EditProjectForm, RolloverForm, GoLiveForm, CloseStudentSelectionsForm, \
    IssueFacultyConfirmRequestForm, ConfirmAllRequestsForm

import re
from datetime import date, timedelta


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


def _validate_user(project):
    """
    Validate that the logged-in user is privileged to edit a project
    :param project: Project model instance
    :return: True/False
    """

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if project.owner_id != current_user.id \
            and not current_user.has_role('admin') \
            and not current_user.has_role('root') \
            and not any[project.project_classes.convenor.id == current_user.id]:

        flash('This project belongs to another user. To edit it, you must be a suitable convenor or an administrator.')
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


@faculty.route('/edit_my_projects')
@roles_accepted('faculty', 'admin', 'root')
def edit_my_projects():

    # filter list of projects for current user
    projects = Project.query.filter_by(owner_id=current_user.id).all()

    return render_template('faculty/edit_my_projects.html', projects=projects)


@faculty.route('/add_project', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_project():

    # set up form
    form = AddProjectForm(request.form)

    # only convenors/administrators can reassign ownership
    del form.owner

    if form.validate_on_submit():

        data = Project(name=form.name.data,
                       keywords=form.keywords.data,
                       active=True,
                       owner=current_user,
                       group=form.group.data,
                       project_classes=form.project_classes.data,
                       skills=[],
                       programmes=[],
                       meeting_reqd=form.meeting.data,
                       team=form.team.data,
                       description=form.description.data,
                       reading=form.reading.data)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('faculty.edit_my_projects'))

    return render_template('faculty/edit_project.html', project_form=form, title='Add new project')


@faculty.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_project(id):

    # set up form
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    form = EditProjectForm(obj=data)
    form.project = data

    # only convenors/administrators can reassign ownership
    del form.owner

    if form.validate_on_submit():

        data.name = form.name.data
        data.keywords = form.keywords.data
        data.group = form.group.data
        data.project_classes = form.project_classes.data
        data.meeting_reqd = form.meeting.data
        data.team = form.team.data
        data.description = form.description.data
        data.reading = form.reading.data

        data.validate_programmes()

        db.session.commit()

        return redirect(url_for('faculty.edit_my_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=data, title='Edit project details')


@faculty.route('/convenor_add_project/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def convenor_add_project(pclass_id):

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
                       team=form.team.data,
                       description=form.description.data,
                       reading=form.reading.data)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('faculty.convenor_dashboard', id=pclass_id, tabid=_ConvenorDashboardProjectsTab))

    return render_template('faculty/edit_project.html', project_form=form, pclass_id=pclass_id, title='Add new project')


@faculty.route('/convenor_edit_project/<int:id>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def convenor_edit_project(id, pclass_id):

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
        data.team = form.team.data
        data.description = form.description.data
        data.reading = form.reading.data

        # ensure that list of preferred degree programmes is now consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        owner = data.owner.faculty_data
        for pclass in data.project_classes:

            if owner not in pclass.enrolled_faculty.all():

                owner.enrollments.append(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.build_name(), pclass=pclass.name))

        db.session.commit()

        return redirect(url_for('faculty.convenor_dashboard', id=pclass_id, tabid=_ConvenorDashboardProjectsTab))

    return render_template('faculty/edit_project.html', project_form=form, project=data, pclass_id=pclass_id, title='Edit project details')


@faculty.route('/make_project_active/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def make_project_active(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/make_project_inactive/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def make_project_inactive(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/convenor_make_project_active/<int:id>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def convenor_make_project_active(id, pclassid):

    # get project details
    data = Project.query.get_or_404(id)

    # get project class details
    pclass = ProjectClass.query.get_or_404(pclassid)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data.enable()
    db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=pclassid, tabid=2))


@faculty.route('/convenor_make_project_inactive/<int:id>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def convenor_make_project_inactive(id, pclassid):

    # get project details
    data = Project.query.get_or_404(id)

    # get project class details
    pclass = ProjectClass.query.get_or_404(pclassid)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data.disable()
    db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=pclassid, tabid=2))


@faculty.route('/attach_skills/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_skills(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    # get list of active skills
    skills = TransferableSkill.query.filter_by(active=True)

    return render_template('faculty/attach_skills.html', data=data, skills=skills)


@faculty.route('/convenor_attach_skills/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def convenor_attach_skills(id, pclass_id):

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
    skills = TransferableSkill.query.filter_by(active=True)

    return render_template('faculty/convenor_attach_skills.html', data=data, skills=skills, pclass_id=pclass_id)


@faculty.route('/add_skill/<int:projectid>/<int:skillid>')
@roles_accepted('faculty', 'admin', 'root')
def add_skill(projectid, skillid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in data.skills:
        data.add_skill(skill)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/remove_skill/<int:projectid>/<int:skillid>')
@roles_accepted('faculty', 'admin', 'root')
def remove_skill(projectid, skillid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in data.skills:
        data.remove_skill(skill)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/attach_programmes/<int:id>')
@roles_accepted('faculty', 'office')
def attach_programmes(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    q = data.available_degree_programmes()

    return render_template('faculty/attach_programmes.html', data=data, programmes=q.all())


@faculty.route('/convenor_attach_programmes/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'office')
def convenor_attach_programmes(id, pclass_id):

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

    q = data.available_degree_programmes()

    return render_template('faculty/convenor_attach_programmes.html', data=data, programmes=q.all(), pclass_id=pclass_id)


@faculty.route('/add_programme/<int:projectid>/<int:progid>')
@roles_accepted('faculty', 'admin', 'root')
def add_programme(projectid, progid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(progid)

    if data.programmes is not None and programme not in data.programmes:
        data.add_programme(programme)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/remove_programme/<int:projectid>/<int:progid>')
@roles_accepted('faculty', 'admin', 'root')
def remove_programme(projectid, progid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(progid)

    if data.programmes is not None and programme in data.programmes:
        data.remove_programme(programme)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/convenor_dashboard/<int:id>/<int:tabid>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def convenor_dashboard(id, tabid):

    if id == 0:

        return _render_unattached()

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = MainConfig.query.order_by(MainConfig.year.desc()).first().year

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
    faculty = db.session.query(User, FacultyData).filter(User.active).join(FacultyData)

    # count number of faculty enrolled on this project
    fac_count = db.session.query(User).filter(User.active).join(FacultyData).filter(
        FacultyData.enrollments.any(id=id)).count()

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False)

    # build a list of live students submitting work for evaluation in this project class
    submitters = config.submitting_students.filter_by(retired=False)

    return render_template('faculty/convenor_dashboard.html',
                           golive_form=golive_form, issue_form=issue_form,
                           pclass=pclass, config=config, current_year=current_year, tabid=tabid,
                           projects=pclass.projects, faculty=faculty, fac_count=fac_count,
                           selectors=selectors, submitters=submitters)


@faculty.route('/issue_confirm_requests/<int:id>', methods=['GET', 'POST'])
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

    return redirect(url_for('faculty.convenor_dashboard', id=pclass.id, tabid=1))


def _render_unattached():

    # special-case of unattached projects; reject user if not administrator
    if not _validate_administrator():
        return redirect(request.referrer)

    projects = [proj for proj in Project.query.all() if not proj.offerable]

    return render_template('faculty/unattached_dashboard.html', projects=projects)


@faculty.route('/force_confirm_all/<int:id>')
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

    return redirect(url_for('faculty.convenor_dashboard', id=pclass.id, tabid=1))


@faculty.route('/go_live/<int:id>', methods=['GET', 'POST'])
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
        if config.golive_required.count() > 0:

            flash('Cannot yet go live for {name} {yeara}-{yearb}'
                  ' because some confirmation requests are outstanding. '
                  'If needed, force all confirmations and try again.'.format(
                    name=pclass.name, yeara=config.year, yearb=config.year+1),
                  'error')

            return redirect(url_for('faculty.convenor_dashboard', id=pclass.id, tabid=1))

        # going live consists of copying all tables for this project to the live project table,
        # in alphabetical order
        projects = pclass.projects.filter(Project.active).join(User).order_by(User.last_name, User.first_name)

        if projects.count() == 0:

            flash('Cannot yet go live for {name} {yeara}-{yearb} '
                  'because there are no available projects.'.format(
                    name=pclass.name, yeara=config.year, yearb=config.year+1),
                  'error')

            return redirect(url_for('faculty.convenor_dashboard', id=pclass.id, tabid=1))

        number = 1
        for item in projects.all():

            live_item = LiveProject(config_id=pclass.id,
                                    number=number,
                                    name=item.name,
                                    keywords=item.keywords,
                                    owner_id=item.owner_id,
                                    group_id=item.group_id,
                                    project_classes=item.project_classes,
                                    skills=item.skills,
                                    programmes=item.programmes,
                                    meeting_reqd=item.meeting_reqd,
                                    team=item.team,
                                    description=item.description,
                                    reading=item.description,
                                    page_views=0)
            db.session.add(live_item)
            number += 1

        config.live = True
        config.live_deadline = form.live_deadline.data

        db.session.commit()

        flash('{name} {yeara}-{yearb} is now live'.format(name=pclass.name, yeara=config.year, yearb=config.year+1), 'success')

    return redirect(url_for('faculty.convenor_dashboard', id=pclass.id, tabid=1))


@faculty.route('/convenor_enroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def convenor_enroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.add_enrollment(pclass)
    db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=pclassid, tabid=_ConvenorDashboardFacultyTab))


@faculty.route('/convenor_unenroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def convenor_unenroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not _validate_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.remove_enrollment(pclass)
    db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=pclassid, tabid=_ConvenorDashboardFacultyTab))


@faculty.route('/preview/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_preview(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    keywords = [ kw.strip() for kw in re.split(";.", data.keywords) ]

    return render_template('student/show_project.html', title=data.name, project=data, keywords=keywords)


@faculty.route('/dashboard')
@roles_required('faculty')
def dashboard():
    """
    Render the dashboard for a faculty user
    :return:
    """

    # check for unofferable projects and warn if any are prsent
    unofferable = current_user.faculty_data.projects_unofferable()
    if unofferable > 0:
        plural='s'
        isare='are'

        if unofferable == 1:
            plural=''
            isare='is'

        flash('You have {n} project{plural} that {isare} active but cannot be offered to students. '
              'Please check your project list.'.format(n=unofferable, plural=plural, isare=isare),
              'error')

    # build list of current configuration records for all enrolled project classes
    enrollments = []
    for item in current_user.faculty_data.enrollments:

        config = item.configs.order_by(ProjectClassConfig.year.desc()).first()

        # get live projects belonging to both this config item and the active user
        live_projects = config.live_projects.filter_by(owner_id=current_user.id)

        enrollments.append((config, live_projects))

    return render_template('faculty/dashboard.html', enrollments=enrollments)


@faculty.route('/confirm_pclass/<int:id>')
@roles_accepted('faculty')
def confirm_pclass(id):
    """
    Issue confirmation for this project class and logged-in user
    :param id:
    :return:
    """

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    if not config.requests_issued:
        flash('Confirmation requests have not yet been issued for {project} {yeara}-{yearb}'.format(
            project=config.project_class.name, yeara=config.year, yearb=config.year+1))
        return redirect(url_for('faculty.dashboard'))

    if current_user.faculty_data in config.golive_required:

        config.golive_required.remove(current_user.faculty_data)
        db.session.commit()

        flash('Thank-you. You confirmation has been recorded.')
        return redirect(url_for('faculty.dashboard'))

    flash('You have no outstanding confirmation requests for {project} {yeara}-{yearb}'.format(
        project=config.project_class.name, yeara=config.year, yearb=config.year+1))

    return redirect(url_for('faculty.dashboard'))


@faculty.route('/confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty')
def confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if project.owner_id != current_user.id:

        flash('You do not have privileges to edit this project', 'error')
        return redirect(request.referrer)

    if _confirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/deconfirm/<int:sid>/<int:pid>')
@roles_accepted('faculty')
def deconfirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if project.owner_id != current_user.id:
        flash('You do not have privileges to edit this project', 'error')
        return redirect(request.referrer)

    if _deconfirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/convenor_confirm/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def convenor_confirm(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))

    if _confirm(sel, project):
        db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))


@faculty.route('/convenor_deconfirm/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def convenor_deconfirm(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))

    if _deconfirm(sel, project):
        db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))


@faculty.route('/convenor_deconfirm_to_pending/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def convenor_deconfirm_to_pending(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))

    if _deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))


@faculty.route('/convenor_cancel_confirm/<int:sid>/<int:pid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'route')
def convenor_cancel_confirm(sid, pid, tabid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not _validate_convenor(sel.config.project_class):
        return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))

    if _cancel_confirm(sel, project):
        db.session.commit()

    return redirect(url_for('faculty.convenor_dashboard', id=sel.config.id, tabid=tabid))


def _confirm(sel, project):

    if sel not in project.confirm_waiting:

        return False

    project.confirm_waiting.remove(sel)

    if sel not in project.confirmed_students:

        project.confirmed_students.append(sel)

    return True


def _deconfirm(sel, project):

    if sel in project.confirmed_students:

        project.confirmed_students.remove(sel)
        return True

    return False


def _deconfirm_to_pending(sel, project):

    if sel not in project.confirmed_students:

        return False

    project.confirmed_students.remove(sel)

    if sel not in project.confirm_waiting:

        project.confirm_waiting.append(sel)

    return True


def _cancel_confirm(sel, project):

    if sel not in project.confirm_waiting:

        return False

    project.confirm_waiting.remove(sel)
    return True
