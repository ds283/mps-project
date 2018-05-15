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
from flask_security import login_required, roles_required, current_user
from flask_security.utils import config_value, get_url, find_redirect, validate_redirect_url, get_message, do_flash, send_mail
from flask_security.confirmable import generate_confirmation_link
from flask_security.signals import user_registered

from ..models import db, MainConfig, User, FacultyData, StudentData, ResearchGroup, DegreeType, DegreeProgramme, \
    TransferableSkill, ProjectClass, Supervisor, Project

from . import faculty

from .forms import AddProjectForm, EditProjectForm


def _validate_user(data):
    """
    Validate that the logged-in user is privileged to edit a project
    :param data: Project model instance
    :return: True/False
    """

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if data.owner_id != current_user.id \
            and not current_user.has_role('admin') \
            and not any[ data.project_classes.convenor.id == current_user.id ] :

        flash('This project belongs to another user. To edit it, you must be a suitable convenor or an administrator.')
        return False

    return True


@faculty.route('/edit_my_projects')
@roles_required('faculty')
def edit_my_projects():

    # filter list of projects for current user
    projects = Project.query.filter_by(owner_id=current_user.id).all()

    return render_template('faculty/edit_my_projects.html', projects=projects)


@faculty.route('/add_project', methods=['GET', 'POST'])
@roles_required('faculty')
def add_project():

    # set up form
    form = AddProjectForm(request.form)

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
@roles_required('faculty')
def edit_project(id):

    # set up form
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    form = EditProjectForm(obj=data)
    form.project = data

    if form.validate_on_submit():

        data.name = form.name.data
        data.keywords = form.keywords.data
        data.group = form.group.data
        data.project_classes = form.project_classes.data
        data.meeting_reqd = form.meeting.data
        data.team = form.team.data
        data.description = form.description.data
        data.reading = form.reading.data

        db.session.commit()

        return redirect(url_for('faculty.edit_my_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=data, title='Edit project details')


@faculty.route('/make_project_active/<int:id>')
@roles_required('faculty')
def make_project_active(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    data.active = True
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/make_project_inactive/<int:id>')
@roles_required('faculty')
def make_project_inactive(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    data.active = False
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/attach_skills/<int:id>')
@roles_required('faculty')
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
@roles_required('faculty')
def add_skill(projectid, skillid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in data.skills:
        data.skills.append(skill)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/remove_skill/<int:projectid>/<int:skillid>')
@roles_required('faculty')
def remove_skill(projectid, skillid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in data.skills:
        data.skills.remove(skill)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/attach_programmes/<int:id>')
@roles_required('faculty')
def attach_programmes(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    # get list of active degree programmes relevant for our degree classes
    programmes = DegreeProgramme.query.filter_by(active=True)

    return render_template('faculty/attach_programmes.html', data=data, programmes=programmes)


@faculty.route('/add_programme/<int:projectid>/<int:progid>')
@roles_required('faculty')
def add_programme(projectid, progid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(progid)

    if programme not in data.programmes:
        data.programmes.append(programme)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/remove_programme/<int:projectid>/<int:progid>')
@roles_required('faculty')
def remove_programme(projectid, progid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not _validate_user(data):
        return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(progid)

    if programme in data.programmes:
        data.programmes.remove(programme)
        db.session.commit()

    return redirect(request.referrer)
