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

from ..models import db, DegreeProgramme, FacultyData, ResearchGroup, \
    TransferableSkill, ProjectClassConfig, LiveProject, SelectingStudent, Project, MessageOfTheDay, \
    EnrollmentRecord, SkillGroup, ProjectClass, ProjectDescription, SubmissionRecord, SubmittingStudent

import app.ajax as ajax

from . import faculty

from .forms import AddProjectForm, EditProjectForm, SkillSelectorForm, AddDescriptionForm, EditDescriptionForm, \
    DescriptionSelectorForm, SupervisorFeedbackForm, MarkerFeedbackForm, SupervisorResponseForm

from ..shared.utils import home_dashboard, get_root_dashboard_data, filter_second_markers
from ..shared.validators import validate_edit_project, validate_project_open, validate_is_project_owner, \
    validate_submission_supervisor, validate_submission_marker, validate_submission_viewable
from ..shared.actions import render_project, do_confirm, do_deconfirm, do_cancel_confirm, do_deconfirm_to_pending
from ..shared.conversions import is_integer

from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime


_project_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
                <i class="fa fa-search"></i> Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Edit project</li>

        <li>
            <a href="{{ url_for('faculty.edit_project', id=project.id) }}">
                <i class="fa fa-pencil"></i> Project settings
            </a>
        </li>
        
        <li>
            <a href="{{ url_for('faculty.edit_descriptions', id=project.id) }}">
                <i class="fa fa-pencil"></i> Descriptions
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_markers', id=project.id) }}">
                <i class="fa fa-wrench"></i> 2nd markers
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_skills', id=project.id) }}">
                <i class="fa fa-wrench"></i> Transferable skills
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_programmes', id=project.id) }}">
                <i class="fa fa-wrench"></i> Degree programmes
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
            {% if project.active %}
                <a href="{{ url_for('faculty.deactivate_project', id=project.id) }}">
                    <i class="fa fa-wrench"></i> Make inactive
                </a>
            {% else %}
                <a href="{{ url_for('faculty.activate_project', id=project.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a>
            {% endif %}
        </li>
        {% if project.is_deletable %}
            <li>
                <a href="{{ url_for('faculty.delete_project', id=project.id) }}">
                    <i class="fa fa-trash"></i> Delete
                </a>
            </li>
        {% else %}
            <li class="disabled"><a>
                <i class="fa fa-trash"></i> Delete disabled
            </a></li>
        {% endif %}
    </ul>
</div>
"""


_marker_menu = \
"""
{% if proj.is_second_marker(f) %}
    <a href="{{ url_for('faculty.remove_marker', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm btn-default">
        <i class="fa fa-trash"></i> Remove
    </a>
{% elif proj.can_enroll_marker(f) %}
    <a href="{{ url_for('faculty.add_marker', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm btn-default">
        <i class="fa fa-plus"></i> Attach
    </a>
{% else %}
    <a class="btn btn-default btn-sm disabled">
        <i class="fa fa-ban"></i> Can't attach
    </a>
{% endif %}
"""


_desc_label = \
"""
<a href="{{ url_for('faculty.edit_description', did=d.id) }}">{{ d.label }}</a>
"""


_desc_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.edit_description', did=d.id, create=create) }}">
                <i class="fa fa-pencil"></i> Edit description
            </a>
        </li>
        <li>
            <a href="{{ url_for('faculty.delete_description', did=d.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
        
        <li role="separator" class="divider"></li>
        
        <li>
            <a href="{{ url_for('faculty.duplicate_description', did=d.id) }}">
                <i class="fa fa-clone"></i> Duplicate
            </a>
        </li>
        <li>
            {% if d.default is none %}
                <a href="{{ url_for('faculty.make_default_description', pid=d.parent_id, did=d.id) }}">
                    <i class="fa fa-wrench"></i> Make default
                </a>
            {% else %}
                <a href="{{ url_for('faculty.make_default_description', pid=d.parent_id) }}">
                    <i class="fa fa-wrench"></i> Remove default
                </a>
            {% endif %}
        </li>
    </ul>
</div>
"""


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


@faculty.route('/projects_ajax', methods=['GET', 'POST'])
@roles_required('faculty')
def projects_ajax():
    """
    Ajax data point for Edit Projects view
    :return:
    """

    pq = Project.query.filter_by(owner_id=current_user.id)
    data = [(p, None) for p in pq.all()]

    return ajax.project.build_data(data, _project_menu,
                                   text='projects list',
                                   url=url_for('faculty.edit_projects'))


@faculty.route('/second_marker')
@roles_required('faculty')
def second_marker():

    pclass_filter = request.args.get('pclass_filter')

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('view_marker_pclass_filter'):
        pclass_filter = session['view_marker_pclass_filter']

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session['view_marker_pclass_filter'] = pclass_filter

    groups = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()
    pclasses = ProjectClass.query.filter_by(active=True).order_by(ProjectClass.name.asc()).all()

    return render_template('faculty/second_marker.html', groups=groups, pclasses=pclasses, pclass_filter=pclass_filter)


@faculty.route('/marking_ajax', methods=['GET', 'POST'])
@roles_required('faculty')
def marking_ajax():
    """
    Ajax data point for Marking pool view
    :return:
    """

    pclass_filter = request.args.get('pclass_filter')
    flag, pclass_value = is_integer(pclass_filter)

    pq = current_user.faculty_data.second_marker_for
    if flag:
        pq = pq.filter(Project.project_classes.any(id=pclass_value))

    data = [(p, None) for p in pq.all()]

    return ajax.project.build_data(data, "")


@faculty.route('/edit_descriptions/<int:id>')
@roles_required('faculty')
def edit_descriptions(id):

    project = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(project):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    return render_template('faculty/edit_descriptions.html', project=project, create=create)


@faculty.route('/descriptions_ajax/<int:id>')
@roles_required('faculty')
def descriptions_ajax(id):

    project = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(project):
        return jsonify({})

    descs = project.descriptions.all()

    create = request.args.get('create', default=None)

    return ajax.faculty.descriptions_data(descs, _desc_label, _desc_menu, create=create)


@faculty.route('/add_project', methods=['GET', 'POST'])
@roles_required('faculty')
def add_project():

    # set up form
    form = AddProjectForm(request.form)

    # only conveners/administrators can reassign ownership
    del form.owner

    if form.validate_on_submit():

        data = Project(name=form.name.data,
                       keywords=form.keywords.data,
                       active=True,
                       owner=current_user.faculty_data,
                       group=form.group.data,
                       project_classes=form.project_classes.data,
                       skills=[],
                       programmes=[],
                       meeting_reqd=form.meeting_reqd.data,
                       enforce_capacity=form.enforce_capacity.data,
                       show_popularity=form.show_popularity.data,
                       show_bookmarks=form.show_bookmarks.data,
                       show_selections=form.show_selections.data,
                       creator_id=current_user.id,
                       creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        if form.submit.data:
            return redirect(url_for('faculty.edit_descriptions', id=data.id, create=1))
        elif form.save_and_exit.data:
            return redirect(url_for('faculty.edit_projects'))
        elif form.save_and_preview:
            return redirect(url_for('faculty.project_preview', id=data.id,
                                    text='project list',
                                    url=url_for('faculty.edit_projects')))
        else:
            raise RuntimeError('Unknown submit button in faculty.add_project')

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
        proj.enforce_capacity = form.enforce_capacity.data
        proj.show_popularity = form.show_popularity.data
        proj.show_bookmarks = form.show_bookmarks.data
        proj.show_selections = form.show_selections.data
        proj.last_edit_id = current_user.id
        proj.last_edit_timestamp = datetime.now()

        proj.validate_programmes()

        db.session.commit()

        if form.save_and_preview.data:
            return redirect(url_for('faculty.project_preview', id=id,
                                    text='project list',
                                    url=url_for('faculty.edit_projects')))
        else:
            return redirect(url_for('faculty.edit_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=proj, title='Edit project settings')


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


@faculty.route('/delete_project/<int:id>')
@roles_required('faculty')
def delete_project(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(data):
        return redirect(request.referrer)

    title = 'Delete project'
    panel_title = 'Delete project <strong>{name}</strong>'.format(name=data.name)

    action_url = url_for('faculty.perform_delete_project', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to delete the project ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=data.name)
    submit_label = 'Delete project'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@faculty.route('/perform_delete_project/<int:id>')
@roles_required('faculty')
def perform_delete_project(id):

    # get project details
    data = Project.query.get_or_404(id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('faculty.edit_projects')

    # if project owner is not logged in user, object
    if not validate_is_project_owner(data):
        return redirect(url)

    try:
        for item in data.descriptions:
            db.session.delete(item)

        db.session.delete(data)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise

    return redirect(url)


@faculty.route('/add_description/<int:pid>', methods=['GET', 'POST'])
@roles_required('faculty')
def add_description(pid):

    # get parent project details
    proj = Project.query.get_or_404(pid)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    form = AddDescriptionForm(pid, request.form)
    form.project_id = pid

    if form.validate_on_submit():

        data = ProjectDescription(parent_id=pid,
                                  label=form.label.data,
                                  project_classes=form.project_classes.data,
                                  description=form.description.data,
                                  reading=form.reading.data,
                                  team=form.team.data,
                                  capacity=form.capacity.data,
                                  creator_id=current_user.id,
                                  creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('faculty.edit_descriptions', id=pid, create=create))

    else:
        if request.method == 'GET':
            form.capacity.data = proj.owner.project_capacity

    return render_template('faculty/edit_description.html', project=proj, form=form, title='Add new description',
                           create=create)


@faculty.route('/edit_description/<int:did>', methods=['GET', 'POST'])
@roles_required('faculty')
def edit_description(did):

    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    form = EditDescriptionForm(desc.parent_id, did, obj=desc)
    form.project_id = desc.parent_id
    form.desc = desc

    if form.validate_on_submit():

        desc.label = form.label.data
        desc.project_classes = form.project_classes.data
        desc.description = form.description.data
        desc.reading = form.reading.data
        desc.team = form.team.data
        desc.capacity = form.capacity.data
        desc.last_edit_id = current_user.id
        desc.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('faculty.edit_descriptions', id=desc.parent_id, create=create))

    return render_template('faculty/edit_description.html', project=desc.parent, desc=desc, form=form,
                           title='Edit description', create=create)


@faculty.route('/delete_description/<int:did>')
@roles_required('faculty')
def delete_description(did):

    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    db.session.delete(desc)
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/duplicate_description/<int:did>')
@roles_required('faculty')
def duplicate_description(did):

    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    suffix = 2
    while suffix < 100:
        new_label = '{label} #{suffix}'.format(label=desc.label, suffix=suffix)

        if ProjectDescription.query.filter_by(parent_id=desc.parent_id, label=new_label).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash('Could not duplicate description "{label}" because a new unique label could not '
              'be generated'.format(label=desc.label), 'error')
        return redirect(request.referrer)

    data = ProjectDescription(parent_id=desc.parent_id,
                              label=new_label,
                              project_classes=[],
                              capacity=desc.capacity,
                              description=desc.description,
                              reading=desc.reading,
                              team=desc.team)

    db.session.add(data)
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/make_default_description/<int:pid>/<int:did>')
@faculty.route('/make_default_description/<int:pid>')
@roles_required('faculty')
def make_default_description(pid, did=None):

    proj = Project.query.get_or_404(pid)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    if did is not None:
        desc = ProjectDescription.query.get_or_404(did)

        if desc.parent_id != pid:
            flash('Cannot set default description (id={did)) for project (id={pid}) because this description '
                  'does not belong to the project'.format(pid=pid, did=did), 'error')
            return redirect(request.referrer)

    proj.default_id = did
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

    create = request.args.get('create', default=None)

    return render_template('faculty/attach_skills.html', data=proj, skills=skills,
                           form=form, sel_id=form.selector.data.id, create=create)


@faculty.route('/add_skill/<int:projectid>/<int:skillid>/<int:sel_id>')
@roles_required('faculty')
def add_skill(projectid, skillid, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in proj.skills:
        proj.add_skill(skill)
        db.session.commit()

    return redirect(url_for('faculty.attach_skills', id=projectid, sel_id=sel_id, create=create))


@faculty.route('/remove_skill/<int:projectid>/<int:skillid>/<int:sel_id>')
@roles_required('faculty')
def remove_skill(projectid, skillid, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in proj.skills:
        proj.remove_skill(skill)
        db.session.commit()

    return redirect(url_for('faculty.attach_skills', id=projectid, sel_id=sel_id, create=create))


@faculty.route('/attach_programmes/<int:id>')
@roles_required('faculty')
def attach_programmes(id):

    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    q = proj.available_degree_programmes

    create = request.args.get('create', default=None)

    return render_template('faculty/attach_programmes.html', data=proj, programmes=q.all(), create=create)


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

    create = request.args.get('create', default=None)

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
    pclasses = proj.project_classes.filter_by(active=True, uses_marker=True).all()

    return render_template('faculty/attach_markers.html', data=proj, groups=groups, pclasses=pclasses,
                           state_filter=state_filter, pclass_filter=pclass_filter, group_filter=group_filter,
                           create=create)


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

    return ajax.project.build_marker_data(faculty, proj, _marker_menu)


@faculty.route('/add_marker/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def add_marker(proj_id, mid):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    marker = FacultyData.query.get_or_404(mid)

    proj.add_marker(marker)

    return redirect(request.referrer)


@faculty.route('/remove_marker/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def remove_marker(proj_id, mid):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    marker = FacultyData.query.get_or_404(mid)

    proj.remove_marker(marker)

    return redirect(request.referrer)


@faculty.route('/attach_all_markers/<int:proj_id>')
@roles_required('faculty')
def attach_all_markers(proj_id):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    markers = filter_second_markers(proj, state_filter, pclass_filter, group_filter)

    for marker in markers:
        proj.add_marker(marker)

    return redirect(request.referrer)


@faculty.route('/remove_all_markers/<int:proj_id>')
@roles_required('faculty')
def remove_all_markers(proj_id):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    markers = filter_second_markers(proj, state_filter, pclass_filter, group_filter)

    for marker in markers:
        proj.remove_marker(marker)

    return redirect(request.referrer)


@faculty.route('/preview/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def project_preview(id):

    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(data):
        return redirect(request.referrer)

    form = DescriptionSelectorForm(id, request.form)

    if form.validate_on_submit():
        pass

    else:
        if request.method == 'GET':

            # attach first available project class
            form.selector.data = data.project_classes.first()

    text = request.args.get('text', None)
    url = request.args.get('url', None)

    return render_project(data, data.get_description(form.selector.data), form=form, text=text, url=url)


@faculty.route('/dashboard')
@roles_required('faculty')
def dashboard():
    """
    Render the dashboard for a faculty user
    :return:
    """

    # check for unofferable projects and warn if any are prsent
    unofferable = current_user.faculty_data.projects_unofferable
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
            project=config.name, yeara=config.year, yearb=config.year+1))
        return home_dashboard()

    if current_user.faculty_data in config.golive_required:

        config.golive_required.remove(current_user.faculty_data)
        db.session.commit()

        flash('Thank-you. You confirmation has been recorded.')
        return home_dashboard()

    flash('You have no outstanding confirmation requests for {project} {yeara}-{yearb}'.format(
        project=config.name, yeara=config.year, yearb=config.year+1))

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


@faculty.route('/deconfirm_to_pending/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def deconfirm_to_pending(sid, pid):

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

    if do_deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@faculty.route('/cancel_confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def cancel_confirm(sid, pid):

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

    if do_cancel_confirm(sel, project):
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

    text = request.args.get('text', None)
    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    return render_project(data, data, text=text, url=url)


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


@faculty.route('/supervisor_edit_feedback/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def supervisor_edit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(request.referrer)

    period = record.period

    if not period.feedback_open:
        flash('Can not edit feedback for this submission because the convenor has not yet opened this submission '
              'period for feedback and marking.',
              'error')
        return redirect(request.referrer)

    if period.closed and record.supervisor_submitted:
        flash('It is not possible to edit feedback after the convenor has closed this submission period.',
              'error')
        return redirect(request.referrer)

    form = SupervisorFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        record.supervisor_positive = form.positive.data
        record.supervisor_negative = form.negative.data

        if record.supervisor_submitted:
            record.supervisor_timestamp = datetime.now()

        db.session.commit()

        return redirect(url)

    else:

        if request.method == 'GET':
            form.positive.data = record.supervisor_positive
            form.negative.data = record.supervisor_negative

    return render_template('faculty/dashboard/edit_feedback.html', form=form,
                           title='Edit supervisor feedback',
                           formtitle='Edit supervisor feedback for <i class="fa fa-user"></i> <strong>{name}</strong>'.format(name=record.owner.student.user.name),
                           submit_url=url_for('faculty.supervisor_edit_feedback', id=id, url=url),
                           period=period, record=record)


@faculty.route('/marker_edit_feedback/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def marker_edit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_marker(record):
        return redirect(request.referrer)

    period = record.period

    if not period.feedback_open:
        flash('Can not edit feedback for this submission because the convenor has not yet opened this submission '
              'period for feedback and marking.',
              'error')
        return redirect(request.referrer)

    if period.closed and record.marker_submitted:
        flash('It is not possible to edit feedback after the convenor has closed this submission period.',
              'error')
        return redirect(request.referrer)

    form = MarkerFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        record.marker_positive = form.positive.data
        record.marker_negative = form.negative.data

        if record.marker_submitted:
            record.marker_timestamp = datetime.now()

        db.session.commit()

        return redirect(url)

    else:

        if request.method == 'GET':
            form.positive.data = record.marker_positive
            form.negative.data = record.marker_negative

    return render_template('faculty/dashboard/edit_feedback.html', form=form,
                           title='Edit marker feedback',
                           formtitle='Edit marker feedback for <strong>{num}</strong>'.format(num=record.owner.student.exam_number),
                           submit_url=url_for('faculty.marker_edit_feedback', id=id, url=url),
                           period=period, record=record)


@faculty.route('/supervisor_submit_feedback/<int:id>')
@roles_required('faculty')
def supervisor_submit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(request.referrer)

    if record.supervisor_submitted:
        return redirect(request.referrer)

    period = record.period

    if not period.feedback_open:
        flash('It is not possible to submit before the feedback period has opened.', 'error')
        return redirect(request.referrer)

    if not record.is_supervisor_valid:
        flash('Cannot submit feedback because it is still incomplete.', 'error')
        return redirect(request.referrer)

    record.supervisor_submitted = True
    record.supervisor_timestamp = datetime.now()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/supervisor_unsubmit_feedback/<int:id>')
@roles_required('faculty')
def supervisor_unsubmit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(request.referrer)

    if not record.supervisor_submitted:
        return redirect(request.referrer)

    period = record.period

    if period.closed:
        flash('It is not possible to unsubmit after the feedback period has closed.', 'error')
        return redirect(request.referrer)

    record.supervisor_submitted = False
    record.supervisor_timestamp = None
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/marker_submit_feedback/<int:id>')
@roles_required('faculty')
def marker_submit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_marker(record):
        return redirect(request.referrer)

    if record.marker_submitted:
        return redirect(request.referrer)

    period = record.period

    if not period.feedback_open:
        flash('It is not possible to submit before the feedback period has opened.', 'error')
        return redirect(request.referrer)

    if not record.is_marker_valid:
        flash('Cannot submit feedback because it is still incomplete.', 'error')
        return redirect(request.referrer)

    record.marker_submitted = True
    record.marker_timestamp = datetime.now()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/marker_unsubmit_feedback/<int:id>')
@roles_required('faculty')
def marker_unsubmit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_marker(record):
        return redirect(request.referrer)

    if not record.marker_submitted:
        return redirect(request.referrer)

    period = record.period

    if period.closed:
        flash('It is not possible to unsubmit after the feedback period has closed.', 'error')
        return redirect(request.referrer)

    record.marker_submitted = False
    record.marker_timestamp = None
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/supervisor_acknowledge_feedback/<int:id>')
@roles_required('faculty')
def supervisor_acknowledge_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(request.referrer)

    if record.acknowledge_feedback:
        return redirect(request.referrer)

    period = record.period

    if not period.feedback_open:
        flash('It is not possible to submit before the feedback period has opened.', 'error')
        return redirect(request.referrer)

    if not record.student_feedback_submitted:
        flash('Cannot acknowledge student feedback because none has been submitted.', 'error')
        return redirect(request.referrer)

    record.acknowledge_feedback = True
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/view_feedback/<int:id>')
@roles_required('faculty')
def view_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_viewable(record):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    preview = request.args.get('preview', None)

    return render_template('faculty/dashboard/view_feedback.html', record=record, text='home dashboard',
                           url=url, preview=preview)


@faculty.route('/edit_response/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty')
def edit_response(id):

    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(request.referrer)

    period = record.period

    if not period.closed:
        flash('It is only possible to give respond to feedback from your student when '
              'their own marks and feedback are available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(request.referrer)

    if period.closed and record.faculty_response_submitted:
        flash('It is not possible to edit your response once it has been submitted', 'info')
        return redirect(request.referrer)

    if period.closed and not record.student_feedback_submitted:
        flash('It is not possible to write a response to feedback from your student before '
              'they have submitted it.', 'info')
        return redirect(request.referrer)

    form = SupervisorResponseForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        record.faculty_response = form.feedback.data
        db.session.commit()

        if form.save_preview.data:
            return redirect(url_for('faculty.view_feedback', id=id, url=url, preview=1))
        else:
            return redirect(url)

    else:

        if request.method == 'GET':
            form.feedback.data = record.faculty_response

    return render_template('faculty/dashboard/edit_response.html', form=form, record=record,
                           submit_url = url_for('faculty.edit_response', id=id, url=url),
                           text='home dashboard', url=request.referrer)


@faculty.route('/submit_response/<int:id>')
@roles_accepted('faculty')
def submit_response(id):

    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(request.referrer)

    period = record.period

    if record.faculty_response_submitted:
        return redirect(request.referrer)

    if not period.closed:
        flash('It is only possible to give respond to feedback from your student when '
              'their own marks and feedback are available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(request.referrer)

    if period.closed and record.faculty_response_submitted:
        flash('It is not possible to edit your response once it has been submitted', 'info')
        return redirect(request.referrer)

    if period.closed and not record.student_feedback_submitted:
        flash('It is not possible to write a response to feedback from your student before '
              'they have submitted it.', 'info')
        return redirect(request.referrer)

    if not record.is_response_valid:
        flash('Cannot submit your feedback because it is incomplete.', 'info')
        return redirect(request.referrer)

    record.faculty_response_submitted = True
    record.faculty_response_timestamp = datetime.now()
    db.session.commit()

    return redirect(request.referrer)
