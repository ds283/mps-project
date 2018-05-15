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

    if data.owner_id != current_user.id:
        flash('This project belongs to another user and you do not have permission to edit it.')
        return redirect(request.referrer)

    form = EditProjectForm(obj=data)
    form.project = data

    if form.validate_on_submit():

        data.name = form.name.data
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

    # set up form
    data = Project.query.get_or_404(id)

    if data.owner_id != current_user.id:
        flash('This project belongs to another user and you do not have permission to edit it.')
        return redirect(request.referrer)

    data.active = True
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/make_project_inactive/<int:id>')
@roles_required('faculty')
def make_project_inactive(id):
    # set up form
    data = Project.query.get_or_404(id)

    if data.owner_id != current_user.id:
        flash('This project belongs to another user and you do not have permission to edit it.')
        return redirect(request.referrer)

    data.active = False
    db.session.commit()

    return redirect(request.referrer)
