#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, redirect, url_for, flash, request, session, jsonify
from flask_security import roles_required, roles_accepted, current_user

from ..models import db, DegreeProgramme, User, FacultyData, ResearchGroup, \
    TransferableSkill, ProjectClassConfig, LiveProject, SelectingStudent, Project, MessageOfTheDay, \
    EnrollmentRecord, SkillGroup

import app.ajax as ajax

from . import faculty

from .forms import AddProjectForm, EditProjectForm, SkillSelectorForm

from ..shared.utils import home_dashboard, get_root_dashboard_data, filter_second_markers
from ..shared.validators import validate_edit_project, validate_project_open, validate_is_project_owner
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
    research_groups = ResearchGroup.query.filter_by(active=True).order_by(ResearchGroup.name).all()

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
@roles_required('faculty')
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
            <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
                Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Editing</li>

        <li>
            <a href="{{ url_for('faculty.edit_project', id=project.id) }}">
                <i class="fa fa-pencil"></i> Edit project
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_markers', id=project.id) }}">
                <i class="fa fa-pencil"></i> 2nd markers
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

        <li role="separator" class="divider"></li>

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
@roles_required('faculty')
def projects_ajax():
    """
    Ajax data point for Edit Projects view
    :return:
    """

    pq = Project.query.filter_by(owner_id=current_user.id)

    data = [(p, None) for p in pq.all()]

    return ajax.project.build_data(data, _project_menu)


@faculty.route('/add_project', methods=['GET', 'POST'])
@roles_required('faculty')
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
                       meeting_reqd=form.meeting_reqd.data,
                       capacity=form.capacity.data,
                       enforce_capacity=form.enforce_capacity.data,
                       team=form.team.data,
                       show_popularity=form.show_popularity.data,
                       show_bookmarks=form.show_bookmarks.data,
                       show_selections=form.show_selections.data,
                       description=form.description.data,
                       reading=form.reading.data,
                       creator_id=current_user.id,
                       creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('faculty.edit_projects'))

    else:

        if request.method == 'GET':

            owner = current_user.faculty_data

            if owner.show_popularity:
                form.show_popularity.data = True
                form.show_bookmarks.data = True
                form.show_selections.data = True
            else:
                form.show_popularity.data = False
                form.show_bookmarks.data = False
                form.show_selections.data = False

            form.capacity.data = owner.project_capacity
            form.enforce_capacity.data = owner.enforce_capacity

    return render_template('faculty/edit_project.html', project_form=form, title='Add new project')


@faculty.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def edit_project(id):

    # set up form
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    form = EditProjectForm(obj=proj)
    form.project = proj

    # only convenors/administrators can reassign ownership
    del form.owner

    if form.validate_on_submit():

        proj.name = form.name.data
        proj.keywords = form.keywords.data
        proj.group = form.group.data
        proj.project_classes = form.project_classes.data
        proj.meeting_reqd = form.meeting_reqd.data
        proj.capacity = form.capacity.data
        proj.enforce_capacity = form.enforce_capacity.data
        proj.team = form.team.data
        proj.show_popularity = form.show_popularity.data
        proj.show_bookmarks = form.show_bookmarks.data
        proj.show_selections = form.show_selections.data
        proj.description = form.description.data
        proj.reading = form.reading.data
        proj.last_edit_id = current_user.id
        proj.last_edit_timestamp = datetime.now()

        proj.validate_programmes()

        db.session.commit()

        return redirect(url_for('faculty.edit_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=proj, title='Edit project details')


@faculty.route('/activate_project/<int:id>')
@roles_required('faculty')
def activate_project(id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    proj.enable()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/deactivate_project/<int:id>')
@roles_required('faculty')
def deactivate_project(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(data):
        return redirect(request.referrer)

    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/attach_skills/<int:id>/<int:sel_id>')
@faculty.route('/attach_skills/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def attach_skills(id, sel_id=None):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    form = SkillSelectorForm(request.form)

    # retain memory of which skill group is selected
    # (otherwise the form annoyingly resets itself everytime the page reloads)
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

    return render_template('faculty/attach_skills.html', data=proj, skills=skills,
                           form=form, sel_id=form.selector.data.id)


@faculty.route('/add_skill/<int:projectid>/<int:skillid>/<int:sel_id>')
@roles_required('faculty')
def add_skill(projectid, skillid, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in proj.skills:
        proj.add_skill(skill)
        db.session.commit()

    return redirect(url_for('faculty.attach_skills', id=projectid, sel_id=sel_id))


@faculty.route('/remove_skill/<int:projectid>/<int:skillid>/<int:sel_id>')
@roles_required('faculty')
def remove_skill(projectid, skillid, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in proj.skills:
        proj.remove_skill(skill)
        db.session.commit()

    return redirect(url_for('faculty.attach_skills', id=projectid, sel_id=sel_id))


@faculty.route('/attach_programmes/<int:id>')
@roles_required('faculty')
def attach_programmes(id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    q = proj.available_degree_programmes

    return render_template('faculty/attach_programmes.html', data=proj, programmes=q.all())


@faculty.route('/add_programme/<int:id>/<int:prog_id>')
@roles_required('faculty')
def add_programme(id, prog_id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme not in proj.programmes:
        proj.add_programme(programme)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/remove_programme/<int:id>/<int:prog_id>')
@roles_required('faculty')
def remove_programme(id, prog_id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme in proj.programmes:
        proj.remove_programme(programme)
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/attach_markers/<int:id>')
@roles_required('faculty')
def attach_markers(id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    # if no state filter supplied, check if one is stored in session
    if state_filter is None and session.get('faculty_marker_state_filter'):
        state_filter = session['faculty_marker_state_filter']

    # write state filter into session if it is not empty
    if state_filter is not None:
        session['faculty_marker_state_filter'] = state_filter

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('faculty_marker_pclass_filter'):
        pclass_filter = session['faculty_marker_pclass_filter']

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session['faculty_marker_pclass_filter'] = pclass_filter

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get('faculty_marker_group_filter'):
        group_filter = session['faculty_marker_group_filter']

    # write group filter into session if it is not empty
    if group_filter is not None:
        session['faculty_marker_group_filter'] = group_filter

    # get list of available research groups
    groups = ResearchGroup.query.filter_by(active=True).all()

    # get list of project classes to which this project is attached, and which require assignment of
    # second markers
    pclasses = proj.project_classes.filter_by(uses_marker=True).all()

    return render_template('faculty/attach_markers.html', data=proj, groups=groups, pclasses=pclasses,
                           state_filter=state_filter, pclass_filter=pclass_filter, group_filter=group_filter)


@faculty.route('/attach_markers_ajax/<int:id>')
@roles_required('faculty')
def attach_markers_ajax(id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, return empty json
    if not validate_is_project_owner(proj):
        return jsonify({})

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    faculty = filter_second_markers(proj, state_filter, pclass_filter, group_filter)

    return ajax.project.build_marker_data(faculty, proj)


@faculty.route('/add_marker/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def add_marker(proj_id, mid):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, return empty json
    if not validate_is_project_owner(proj):
        return jsonify({})

    marker = FacultyData.query.get_or_404(mid)

    proj.add_marker(marker)

    return redirect(request.referrer)


@faculty.route('/remove_marker/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def remove_marker(proj_id, mid):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, return empty json
    if not validate_is_project_owner(proj):
        return jsonify({})

    marker = FacultyData.query.get_or_404(mid)

    proj.remove_marker(marker)

    return redirect(request.referrer)


@faculty.route('/preview/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_preview(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(data):
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

        if (record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
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

    root_dash_data = get_root_dashboard_data()

    return render_template('faculty/dashboard/dashboard.html',
                           enrolled_classes=current_user.faculty_data.enrollments,
                           enrollments=enrollments,
                           messages=messages,
                           root_dash_data=root_dash_data)


@faculty.route('/confirm_pclass/<int:id>')
@roles_required('faculty')
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
@roles_required('faculty')
def confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(request.referrer)

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_confirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/deconfirm/<int:sid>/<int:pid>')
@roles_required('faculty')
def deconfirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(request.referrer)

    # validate that project is open
    if not validate_project_open(sel.config):
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
    if not validate_edit_project(data):
        return redirect(request.referrer)

    return render_live_project(data)


@faculty.route('/past_projects')
@roles_required('faculty')
def past_projects():
    """
    Show list of previously offered projects, extracted from live table
    :return:
    """

    return render_template('faculty/past_projects.html')


@faculty.route('/past_projects_ajax')
@roles_required('faculty')
def past_projects_ajax():
    """
    Ajax data point for list of previously offered projects
    :return:
    """

    past_projects = LiveProject.query.filter_by(owner_id=current_user.id)

    return ajax.faculty.pastproject_data(past_projects)
