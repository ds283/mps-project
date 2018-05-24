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
from datetime import date, datetime, timedelta


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


def _validate_open(config):
    """
    Validate that a particular ProjectClassConfig is open for student selections
    :param config:
    :return:
    """

    if not config.open:

        flash('Project "{name}" is not open for student selections'.format(name=config.project_class.name), 'error')

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
                       reading=form.reading.data,
                       creator_id=current_user.id,
                       creation_timestamp=datetime.now())
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
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        data.validate_programmes()

        db.session.commit()

        return redirect(url_for('faculty.edit_my_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=data, title='Edit project details')


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

    q = data.available_degree_programmes

    return render_template('faculty/attach_programmes.html', data=data, programmes=q.all())


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


@faculty.route('/preview/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_preview(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    # build list of keywords
    keywords = [ kw.strip() for kw in re.split(";.", data.keywords) ]

    return render_template('student/show_project.html', title=data.name, project=data, keywords=keywords)



@faculty.route('/live_project/<int:pid>/<int:classid>/<int:tabid>')
@roles_accepted('faculty', 'admin', 'root')
def view_live_project(pid, classid, tabid):
    """
    View a specific project on the live system
    :param tabid:
    :param classid:
    :param pid:
    :return:
    """

    # pid is the id for a LiveProject
    data = LiveProject.query.get_or_404(pid)

    # verify the logged-in user is allowed to view this live project
    if not _validate_user(data):

        if tabid == 0:
            return redirect(url_for('faculty.dashboard'))
        else:
            return redirect(url_for('convenor.dashboard', id=classid, tabid=tabid))

    # build list of keywords
    keywords = [ kw.strip() for kw in re.split(";.", data.keywords) ]

    # without the sel variable, won't render any of the student-specific items
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

        if item.active:

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

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for(request.referrer))

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

    # validate that project is open
    if not _validate_open(sel.config):
        return redirect(url_for(request.referrer))

    if _deconfirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


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
