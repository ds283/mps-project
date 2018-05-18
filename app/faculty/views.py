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
    TransferableSkill, ProjectClass, ProjectClassConfig, LiveProject, LiveStudent, Supervisor, Project

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

        flash('The convenor dashboard is available only to project convenors and administrative users.')
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

        data.validate_programmes()

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
    rollover_form = RolloverForm(request.form)
    golive_form = GoLiveForm(request.form)
    close_form = CloseStudentSelectionsForm(request.form)
    issue_form = IssueFacultyConfirmRequestForm(request.form)
    confirm_form = ConfirmAllRequestsForm(request.form)

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

    return render_template('faculty/convenor_dashboard.html',
                           rollover_form=rollover_form, golive_form=golive_form, close_form=close_form,
                           issue_form=issue_form, confirm_form=confirm_form, pclass=pclass, config=config,
                           current_year=current_year, tabid=tabid,
                           projects=pclass.projects, faculty=faculty, fac_count=fac_count)


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

    # check for unofferable projects
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

    # build list of enrolled projects
    pcs = []
    for item in current_user.faculty_data.enrollments:

        pcs.append(item.configs.order_by(ProjectClassConfig.year.desc()).first())

    return render_template('faculty/dashboard.html', enrollments=pcs)


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

        flash('Confirmation requests have not yet been issued for {project} {year}'.format(project=config.project_class.name), year=config.year)
        return redirect(url_for('faculty.dashboard'))

    if current_user.faculty_data in config.golive_required:

        config.golive_required.remove(current_user.faculty_data)
        db.session.commit()

        flash('Thank-you. You confirmation has been recorded.')
        return redirect(url_for('faculty.dashboard'))

    flash('You have no outstanding confirmation requests for {project} {year}'.format(project=config.project_class.name), year=config.year)
    return redirect(url_for('faculty.dashboard'))
