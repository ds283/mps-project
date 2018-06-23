#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, render_template_string, redirect, url_for, flash, request, jsonify
from flask_security import roles_required, roles_accepted, current_user

from ..models import db, DegreeProgramme, FacultyData, ResearchGroup, \
    TransferableSkill, ProjectClassConfig, LiveProject, SelectingStudent, Project, MessageOfTheDay, \
    EnrollmentRecord, SkillGroup

import app.ajax as ajax

from . import faculty

from .forms import AddProjectForm, EditProjectForm, SkillSelectorForm

from ..shared.utils import home_dashboard
from ..shared.validators import validate_user, validate_open
from ..shared.actions import render_live_project, do_confirm, do_deconfirm

from datetime import datetime


@faculty.route('/affiliations')
@roles_required('faculty')
def affiliations():
    """
    Allow a faculty member to adjust their own affiliations without admin privileges
    :return:
    """

    data = FacultyData.query.get_or_404(current_user.id)
    research_groups = ResearchGroup.query.all()

    return render_template('faculty/affiliations.html', user=current_user, data=data, research_groups=research_groups)


@faculty.route('/add_affiliation/<int:groupid>')
@roles_required('faculty')
def add_affiliation(groupid):

    data = FacultyData.query.get_or_404(current_user.id)
    group = ResearchGroup.query.get_or_404(groupid)

    if group not in data.affiliations:
        data.add_affiliation(group, autocommit=True)

    return redirect(request.referrer)


@faculty.route('/remove_affiliation/<int:groupid>')
@roles_required('faculty')
def remove_affiliation(groupid):

    data = FacultyData.query.get_or_404(current_user.id)
    group = ResearchGroup.query.get_or_404(groupid)

    if group in data.affiliations:
        data.remove_affiliation(group, autocommit=True)

    return redirect(request.referrer)


@faculty.route('/edit_projects')
@roles_accepted('faculty', 'admin', 'root')
def edit_projects():

    groups = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()

    return render_template('faculty/edit_projects.html', groups=groups)


_project_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('faculty.edit_project', id=project.id) }}">
                <i class="fa fa-pencil"></i> Edit project
            </a>
        </li>
        <li>
            <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
                Preview web page
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_skills', id=project.id) }}">
                <i class="fa fa-pencil"></i> Transferable skills
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_programmes', id=project.id) }}">
                <i class="fa fa-pencil"></i> Degree programmes
            </a>
        </li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('faculty.deactivate_project', id=project.id) }}">
                Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('faculty.activate_project', id=project.id) }}">
                Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


@faculty.route('/projects_ajax', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def projects_ajax():
    """
    Ajax data point for Edit Projects view
    :return:
    """

    pq = Project.query.filter_by(owner_id=current_user.id)

    data = [(p, None) for p in pq.all()]

    return ajax.project.build_data(data, _project_menu)


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

        return redirect(url_for('faculty.edit_projects'))

    return render_template('faculty/edit_project.html', project_form=form, title='Add new project')


@faculty.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_project(id):

    # set up form
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
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

        return redirect(url_for('faculty.edit_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=data, title='Edit project details')


@faculty.route('/activate_project/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def activate_project(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
        return redirect(request.referrer)

    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/deactivate_project/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def deactivate_project(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
        return redirect(request.referrer)

    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/attach_skills/<int:id>/<int:sel_id>')
@faculty.route('/attach_skills/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def attach_skills(id, sel_id=None):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
        return redirect(request.referrer)

    form = SkillSelectorForm(request.form)

    if not form.validate_on_submit() and request.method == 'GET':
        if sel_id is None:
            form.selector.data = SkillGroup.query \
                .filter(SkillGroup.active == True) \
                .order_by(SkillGroup.name.asc()).first()
        else:
            form.selector.data = SkillGroup.query \
                .filter(SkillGroup.active == True, SkillGroup.id == sel_id).first()

    # get list of active skills matching selector
    if form.selector.data is not None:
        skills = TransferableSkill.query \
            .filter(TransferableSkill.active == True,
                    TransferableSkill.group_id == form.selector.data.id) \
            .order_by(TransferableSkill.name.asc())
    else:
        skills = TransferableSkill.query.filter_by(active=True).order_by(TransferableSkill.name.asc())

    return render_template('faculty/attach_skills.html', data=data, skills=skills,
                           form=form, sel_id=form.selector.data.id)


@faculty.route('/add_skill/<int:projectid>/<int:skillid>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def add_skill(projectid, skillid, sel_id):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in data.skills:
        data.add_skill(skill)
        db.session.commit()

    return redirect(url_for('faculty.attach_skills', id=projectid, sel_id=sel_id))


@faculty.route('/remove_skill/<int:projectid>/<int:skillid>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def remove_skill(projectid, skillid, sel_id):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in data.skills:
        data.remove_skill(skill)
        db.session.commit()

    return redirect(url_for('faculty.attach_skills', id=projectid, sel_id=sel_id))


@faculty.route('/attach_programmes/<int:id>')
@roles_accepted('faculty', 'office')
def attach_programmes(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
        return redirect(request.referrer)

    q = data.available_degree_programmes

    return render_template('faculty/attach_programmes.html', data=data, programmes=q.all())


@faculty.route('/add_programme/<int:projectid>/<int:progid>')
@roles_accepted('faculty', 'admin', 'root')
def add_programme(projectid, progid):

    # get project details
    data = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_user(data):
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
    if not validate_user(data):
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
    if not validate_user(data):
        return redirect(request.referrer)

    return render_live_project(data)


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
    for record in current_user.faculty_data.enrollments:

        if (record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED \
                or record.marker_state == EnrollmentRecord.MARKER_ENROLLED) and record.pclass.active:
            config = record.pclass.configs.order_by(ProjectClassConfig.year.desc()).first()

            # get live projects belonging to both this config item and the active user
            live_projects = config.live_projects.filter_by(owner_id=current_user.id)

            enrollments.append((config, live_projects))

    # build list of system messages to consider displaying
    messages = []
    for message in MessageOfTheDay.query.filter(MessageOfTheDay.show_faculty,
                                                ~MessageOfTheDay.dismissed_by.any(id=current_user.id)).all():

        include = message.project_classes.first() is None
        if not include:
            for pcl in message.project_classes:
                if current_user.faculty_data.is_enrolled(pcl):
                    include = True
                    break

        if include:
            messages.append(message)

    return render_template('faculty/dashboard.html',
                           enrolled_classes=current_user.faculty_data.enrollments,
                           enrollments=enrollments,
                           messages=messages)


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
        return home_dashboard()

    if current_user.faculty_data in config.golive_required:

        config.golive_required.remove(current_user.faculty_data)
        db.session.commit()

        flash('Thank-you. You confirmation has been recorded.')
        return home_dashboard()

    flash('You have no outstanding confirmation requests for {project} {yeara}-{yearb}'.format(
        project=config.project_class.name, yeara=config.year, yearb=config.year+1))

    return home_dashboard()


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
    if not validate_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_confirm(sel, project):
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
    if not validate_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_deconfirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/live_project/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def live_project(pid):
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
    if not validate_user(data):
        return redirect(request.referrer)

    return render_live_project(data)


@faculty.route('/past_projects')
@roles_accepted('faculty', 'admin', 'root')
def past_projects():
    """
    Show list of previously offered projects, extracted from live table
    :return:
    """

    return render_template('faculty/past_projects.html')


@faculty.route('/past_projects_ajax')
@roles_accepted('faculty', 'admin', 'root')
def past_projects_ajax():
    """
    Ajax data point for list of previously offered projects
    :return:
    """

    past_projects = LiveProject.query.filter_by(owner_id=current_user.id)

    return ajax.faculty.pastproject_data(past_projects)
