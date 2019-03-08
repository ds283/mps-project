#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, redirect, url_for, flash, request, session, jsonify, current_app
from flask_security import roles_required, roles_accepted, current_user
from werkzeug.local import LocalProxy

from ..database import db
from ..models import DegreeProgramme, FacultyData, ResearchGroup, \
    TransferableSkill, ProjectClassConfig, LiveProject, SelectingStudent, Project, MessageOfTheDay, \
    EnrollmentRecord, SkillGroup, ProjectClass, ProjectDescription, SubmissionRecord, PresentationAssessment, \
    PresentationSession, ScheduleSlot, User, PresentationFeedback, Module, FHEQ_Level, DescriptionComment

import app.ajax as ajax

from . import faculty

from .forms import AddProjectFormFactory, EditProjectFormFactory, SkillSelectorForm, \
    AddDescriptionFormFactory, EditDescriptionFormFactory, MoveDescriptionFormFactory, \
    FacultyPreviewFormFactory, SupervisorFeedbackForm, MarkerFeedbackForm, PresentationFeedbackForm, \
    SupervisorResponseForm, FacultySettingsFormFactory, AvailabilityFormFactory
from ..admin.forms import LevelSelectorForm

from ..shared.utils import home_dashboard, home_dashboard_url, get_root_dashboard_data, filter_assessors, \
    get_current_year, get_count, get_approvals_data, allow_approvals
from ..shared.validators import validate_edit_project, validate_project_open, validate_is_project_owner, \
    validate_submission_supervisor, validate_submission_marker, validate_submission_viewable, \
    validate_assessment, validate_using_assessment, validate_presentation_assessor
from ..shared.actions import render_project, do_confirm, do_deconfirm, do_cancel_confirm, do_deconfirm_to_pending
from ..shared.conversions import is_integer

from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime, date


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


_marker_menu = \
"""
{% if proj.is_assessor(f.id) %}
    <a href="{{ url_for('faculty.remove_assessor', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm btn-block btn-default">
        <i class="fa fa-trash"></i> Remove
    </a>
{% elif proj.can_enroll_assessor(f) %}
    <a href="{{ url_for('faculty.add_assessor', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm btn-block btn-default">
        <i class="fa fa-plus"></i> Attach
    </a>
{% else %}
    <a class="btn btn-default btn-block btn-sm disabled">
        <i class="fa fa-ban"></i> Can't attach
    </a>
{% endif %}
"""


_desc_label = \
"""
<a href="{{ url_for('faculty.edit_description', did=d.id) }}">{{ d.label }}</a>
{% if not d.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
{% set state = d.workflow_state %}
<div>
    {% if state == d.WORKFLOW_APPROVAL_VALIDATED %}
        <span class="label label-success"><i class="fa fa-check"></i> Approved</span>
    {% elif state == d.WORKFLOW_APPROVAL_QUEUED %}
        <span class="label label-warning">Approval: Queued</span>
    {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
        <span class="label label-info">Approval: In progress</span>
    {% else %}
        <span class="label label-danger">Unknown approval state</span>
    {% endif %}
    {% if current_user.has_role('project_approver') and d.validated_by %}
        <div>
            <span class="label label-info">Signed-off by {{ d.validated_by.name }}</span>
            {% if d.validated_timestamp %}
                <span class="label label-info">Signed-off at {{ d.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
            {% endif %}
        </div>
    {% endif %}
    {% if d.has_new_comments(current_user) %}
        <div>
            <span class="label label-warning">New comments</span>
        </div>
    {% endif %}
</div>
{% if not d.is_valid %}
    <p></p>
    {% set errors = d.errors %}
    {% set warnings = d.warnings %}
    {% if errors|length == 1 %}
        <span class="label label-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="label label-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="label label-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="label label-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="label label-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="label label-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="has-error">
            {% for item in errors %}
                {% if loop.index <= 5 %}
                    <p class="help-block">{{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="has-error">
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <p class="help-block">Warning: {{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
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
                <i class="fa fa-pencil"></i> Edit description...
            </a>
        </li>
            <li>
                <a href="{{ url_for('faculty.description_modules', did=d.id, create=create) }}">
                    <i class="fa fa-cogs"></i> Recommended modules...
                </a>
            </li>
        <li>
            <a href="{{ url_for('faculty.duplicate_description', did=d.id) }}">
                <i class="fa fa-clone"></i> Duplicate
            </a>
        </li>
        <li>
            <a href="{{ url_for('faculty.move_description', did=d.id, create=create) }}">
                <i class="fa fa-arrows"></i> Move project...
            </a>
        </li>
        <li>
            <a href="{{ url_for('faculty.delete_description', did=d.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
        
        <li role="separator" class="divider"></li>
        
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

    pq = db.session.query(Project.id).filter_by(owner_id=current_user.id).all()
    data = [(p[0], None) for p in pq]

    return ajax.project.build_data(data, current_user.id, 'faculty', text='projects list',
                                   url=url_for('faculty.edit_projects'))


@faculty.route('/assessor_for')
@roles_required('faculty')
def assessor_for():
    pclass_filter = request.args.get('pclass_filter')

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('view_marker_pclass_filter'):
        pclass_filter = session['view_marker_pclass_filter']

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session['view_marker_pclass_filter'] = pclass_filter

    groups = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()
    pclasses = ProjectClass.query.filter_by(active=True, publish=True).order_by(ProjectClass.name.asc()).all()

    return render_template('faculty/assessor_for.html', groups=groups, pclasses=pclasses, pclass_filter=pclass_filter)


@faculty.route('/marking_ajax')
@roles_required('faculty')
def marking_ajax():
    """
    Ajax data point for Assessor pool view
    :return:
    """
    pclass_filter = request.args.get('pclass_filter')
    flag, pclass_value = is_integer(pclass_filter)

    pq = current_user.faculty_data.assessor_for
    if flag:
        pq = pq.filter(Project.project_classes.any(id=pclass_value))

    data = [(p.id, None) for p in pq.all()]

    return ajax.project.build_data(data, current_user.id, show_approvals=False)


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
    AddProjectForm = AddProjectFormFactory(convenor_editing=False)
    form = AddProjectForm(request.form)

    if form.validate_on_submit():
        data = Project(name=form.name.data,
                       keywords=form.keywords.data,
                       active=True,
                       owner_id=current_user.faculty_data.id,
                       group=form.group.data,
                       project_classes=form.project_classes.data,
                       skills=[],
                       programmes=[],
                       meeting_reqd=form.meeting_reqd.data,
                       enforce_capacity=form.enforce_capacity.data,
                       show_popularity=form.show_popularity.data,
                       show_bookmarks=form.show_bookmarks.data,
                       show_selections=form.show_selections.data,
                       dont_clash_presentations=form.dont_clash_presentations.data,
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
            form.dont_clash_presentations.data = owner.dont_clash_presentations

    return render_template('faculty/edit_project.html', project_form=form, title='Add new project')


@faculty.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def edit_project(id):
    # set up form
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    EditProjectForm = EditProjectFormFactory(convenor_editing=False)
    form = EditProjectForm(obj=proj)
    form.project = proj

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
        proj.dont_clash_presentations = form.dont_clash_presentations.data
        proj.last_edit_id = current_user.id
        proj.last_edit_timestamp = datetime.now()

        proj.validate_programmes()

        db.session.commit()

        if form.save_and_preview.data:
            return redirect(url_for('faculty.project_preview', id=id,
                                    text='project list', url=url_for('faculty.edit_projects')))
        else:
            return redirect(url_for('faculty.edit_projects'))

    return render_template('faculty/edit_project.html', project_form=form, project=proj, title='Edit project settings')


@faculty.route('/remove_project_pclass/<int:proj_id>/<int:pclass_id>')
@roles_required('faculty')
def remove_project_pclass(proj_id, pclass_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    proj.remove_project_class(pclass)
    db.session.commit()

    return redirect(request.referrer)


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

    AddDescriptionForm = AddDescriptionFormFactory(pid)
    form = AddDescriptionForm(request.form)
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

    EditDescriptionForm = EditDescriptionFormFactory(desc.parent_id, did)
    form = EditDescriptionForm(obj=desc)
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

        desc.validate_modules()

        db.session.commit()

        return redirect(url_for('faculty.edit_descriptions', id=desc.parent_id, create=create))

    return render_template('faculty/edit_description.html', project=desc.parent, desc=desc, form=form,
                           title='Edit description', create=create)


@faculty.route('/description_modules/<int:did>/<int:level_id>', methods=['GET', 'POST'])
@faculty.route('/description_modules/<int:did>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def description_modules(did, level_id=None):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    form = LevelSelectorForm(request.form)

    if not form.validate_on_submit() and request.method == 'GET':
        if level_id is None:
            form.selector.data = FHEQ_Level.query \
                .filter(FHEQ_Level.active == True) \
                .order_by(FHEQ_Level.academic_year.asc()).first()
        else:
            form.selector.data = FHEQ_Level.query \
                .filter(FHEQ_Level.active == True, FHEQ_Level.id == level_id).first()

    # get list of modules for the current level_id
    if form.selector.data is not None:
        modules = desc.get_available_modules(level_id=form.selector.data.id)
    else:
        modules = []

    level_id = form.selector.data.id if form.selector.data is not None else None
    levels = FHEQ_Level.query.filter_by(active=True).order_by(FHEQ_Level.academic_year.asc()).all()

    return render_template('faculty/description_modules.html', project=desc.parent, desc=desc, form=form,
                           title='Attach recommended modules', levels=levels, create=create,
                           modules=modules, level_id=level_id)


@faculty.route('/description_attach_module/<int:did>/<int:mod_id>/<int:level_id>')
@roles_accepted('faculty', 'admin', 'root')
def description_attach_module(did, mod_id, level_id):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)
    module = Module.query.get_or_404(mod_id)

    if desc.module_available(module.id):
        if module not in desc.modules:
            desc.modules.append(module)
            db.session.commit()

    return redirect(url_for('faculty.description_modules', did=did, level_id=level_id, create=create))


@faculty.route('/description_detach_module/<int:did>/<int:mod_id>/<int:level_id>')
@roles_accepted('faculty', 'admin', 'root')
def description_detach_module(did, mod_id, level_id):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)
    module = Module.query.get_or_404(mod_id)

    if desc.module_available(module.id):
        if module in desc.modules:
            desc.modules.remove(module)
            db.session.commit()

    return redirect(url_for('faculty.description_modules', did=did, level_id=level_id, create=create))


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
                              modules=[],
                              capacity=desc.capacity,
                              description=desc.description,
                              reading=desc.reading,
                              team=desc.team)

    db.session.add(data)
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/move_description/<int:did>', methods=['GET', 'POST'])
@roles_required('faculty')
def move_description(did):
    desc = ProjectDescription.query.get_or_404(did)
    old_project = desc.parent

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    MoveDescriptionForm = MoveDescriptionFormFactory(old_project.owner_id, old_project.id)
    form = MoveDescriptionForm(request.form)

    if form.validate_on_submit():
        new_project = form.destination.data

        if new_project is not None:
            # relabel project if needed
            labels = get_count(new_project.descriptions.filter_by(label=desc.label))
            if labels > 0:
                desc.label = '{old} #{n}'.format(old=desc.label, n=labels+1)

            # remove subscription to any project classes that are already subscribed
            remove = set()

            for pclass in desc.project_classes:
                if get_count(new_project.project_classes.filter_by(id=pclass.id)) == 0:
                    remove.add(pclass)

                elif get_count(new_project.descriptions \
                                     .filter(ProjectDescription.project_classes.any(id=pclass.id))) > 0:
                    remove.add(pclass)

            for pclass in remove:
                desc.project_classes.remove(pclass)

            if old_project.default_id is not None and old_project.default_id == desc.id:
                old_project.default_id = None

            desc.parent_id = new_project.id

            try:
                db.session.commit()
                flash('Description "{name}" successfully moved to project '
                      '"{pname}"'.format(name=desc.label, pname=new_project.name), 'info')
            except SQLAlchemyError:
                db.rollback()
                flash('Description "{name}" could not be moved due to a database error'.format(name=desc.label),
                      'error')
        else:
            flash('Description "{name}" could not be moved because its parent project is '
                  'missing'.format(name=desc.label), 'error')

        if create:
            return redirect(url_for('faculty.edit_descriptions', id=old_project.id, create=True))
        else:
            return redirect(url_for('faculty.edit_descriptions', id=new_project.id))

    return render_template('faculty/move_description.html', form=form, desc=desc, create=create,
                           title='Move "{name}" to a new project'.format(name=desc.label))


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


@faculty.route('/attach_assessors/<int:id>')
@roles_required('faculty')
def attach_assessors(id):
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
    pclasses = proj.project_classes.filter(and_(ProjectClass.active == True,
                                                or_(ProjectClass.uses_marker == True,
                                                    ProjectClass.uses_presentations == True))).all()

    return render_template('faculty/attach_assessors.html', data=proj, groups=groups, pclasses=pclasses,
                           state_filter=state_filter, pclass_filter=pclass_filter, group_filter=group_filter,
                           create=create)


@faculty.route('/attach_assessors_ajax/<int:id>')
@roles_required('faculty')
def attach_assessors_ajax(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, return empty json
    if not validate_is_project_owner(proj):
        return jsonify({})

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    faculty = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    return ajax.project.build_marker_data(faculty, proj, _marker_menu, disable_enrollment_links=True,
                                          url=url_for('faculty.attach_assessors', id=id))


@faculty.route('/add_assessor/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def add_assessor(proj_id, mid):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    assessor = FacultyData.query.get_or_404(mid)

    proj.add_assessor(assessor)

    return redirect(request.referrer)


@faculty.route('/remove_assessor/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def remove_assessor(proj_id, mid):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    assessor = FacultyData.query.get_or_404(mid)

    proj.remove_assessor(assessor)

    return redirect(request.referrer)


@faculty.route('/attach_all_assessors/<int:proj_id>')
@roles_required('faculty')
def attach_all_assessors(proj_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    assssors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assssors:
        proj.add_assessor(assessor)

    return redirect(request.referrer)


@faculty.route('/remove_all_assessors/<int:proj_id>')
@roles_required('faculty')
def remove_all_assessors(proj_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    assessors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessors:
        proj.remove_assessor(assessor)

    return redirect(request.referrer)


@faculty.route('/preview/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root', 'project_approver')
def project_preview(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(data, 'project_approver'):
        return redirect(request.referrer)

    show_selector = bool(int(request.args.get('show_selector', True)))
    all_comments = bool(int(request.args.get('all_comments', False)))

    FacultyPreviewForm = FacultyPreviewFormFactory(id, show_selector)
    form = FacultyPreviewForm(request.form)

    current_year = get_current_year()

    pclass_id = request.args.get('pclass', None)

    text = request.args.get('text', None)
    url = request.args.get('url', None)

    if hasattr(form, 'selector'):
        if form.selector.data is None:
            # check whether pclass was passed in as an argument
            if pclass_id is None:
                # attach first available project class
                form.selector.data = data.project_classes.first()

            else:
                if pclass_id is not None:
                    pclass = data.project_classes.filter_by(id=pclass_id).first()
                    if pclass is not None:
                        form.selector.data = pclass
                    else:
                        form.selector.data = data.project_classes.first()
                else:
                    form.selector.data = None

        desc = data.get_description(form.selector.data)

    else:
        if pclass_id is not None:
            pclass = data.project_classes.filter_by(id=pclass_id).first()
            desc = data.get_description(pclass)
        else:
            desc = data.get_description(data.project_classes.first())

    if form.post_comment.data and form.validate():
        vis = DescriptionComment.VISIBILITY_EVERYONE
        if current_user.has_role('project_approver'):
            if form.limit_visibility.data:
                vis = DescriptionComment.VISIBILITY_APPROVALS_TEAM

        comment = DescriptionComment(year=current_year,
                                     owner_id=current_user.id,
                                     parent_id=desc.id,
                                     comment=form.comment.data,
                                     visibility=vis,
                                     deleted=False,
                                     creation_timestamp=datetime.now())
        db.session.add(comment)
        db.session.commit()

        form.comment.data = None

    # defaults for comments pane
    form.limit_visibility.data = True if current_user.has_role('project_approver') else False

    allow_approval = current_user.has_role('project_approver') and allow_approvals(desc)

    if desc is not None:
        if all_comments:
            comments = desc.comments.order_by(DescriptionComment.creation_timestamp.asc()).all()
        else:
            comments = desc.comments.filter_by(year=current_year) \
                .order_by(DescriptionComment.creation_timestamp.asc()).all()
    else:
        comments = []

    data.update_last_viewed_time(current_user, commit=True)

    return render_project(data, desc, form=form, text=text, url=url,
                          show_selector=show_selector, allow_approval=allow_approval,
                          show_comments=True, comments=comments, all_comments=all_comments, pclass_id=pclass_id)


@faculty.route('/dashboard')
@roles_required('faculty')
def dashboard():
    """
    Render the dashboard for a faculty user
    :return:
    """
    # check for unofferable projects and warn if any are present
    unofferable = current_user.faculty_data.projects_unofferable
    if unofferable > 0:
        plural = '' if unofferable == 1 else 's'
        isare = '' if unofferable == 1 else 'are'

        flash('You have {n} project{plural} that {isare} active but cannot be offered to students. '
              'Please check your project list.'.format(n=unofferable, plural=plural, isare=isare),
              'error')

    # build list of current configuration records for all enrolled project classes
    enrollments = []
    valid_panes = []
    for record in current_user.faculty_data.ordered_enrollments:
        pclass = record.pclass
        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=pclass.id) \
            .order_by(ProjectClassConfig.year.desc()).first()

        if pclass.active and pclass.publish and config is not None:
            include = False

            if (pclass.uses_supervisor and record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED) \
                    or (pclass.uses_marker and record.marker_state == EnrollmentRecord.MARKER_ENROLLED) \
                    or (pclass.uses_presentations and record.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED):
                include = True

            else:
                for n in range(config.submissions):
                    period = config.get_period(n+1)

                    supv_records = period.get_supervisor_records(current_user.id)
                    mark_records = period.get_marker_records(current_user.id)
                    pres_slots = period.get_faculty_presentation_slots(current_user.id) \
                        if (period.has_presentation and period.has_deployed_schedule) else []

                    if (pclass.uses_supervisor and len(supv_records) > 0) \
                            or (pclass.uses_marker and len(mark_records) > 0) \
                            or (pclass.uses_presentations and len(pres_slots) > 0):
                        include = True
                        break

            if include:
                # get live projects belonging to both this config item and the active user
                live_projects = config.live_projects.filter_by(owner_id=current_user.id)

                enrollments.append({'config': config, 'projects': live_projects, 'record': record})
                valid_panes.append(str(config.id))

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

    pane = request.args.get('pane', None)
    if pane is None and session.get('faculty_dashboard_pane'):
        pane = session['faculty_dashboard_pane']

    if pane is None:
        if current_user.has_role('root'):
            pane = 'system'
        elif len(enrollments) > 0:
            c = enrollments[0]['config']
            pane = c.id

    if pane == 'system':
        if not current_user.has_role('root'):
            if len(valid_panes) > 0:
                pane = valid_panes[0]
            else:
                pane = None
    elif pane == 'approve':
        if not (current_user.has_role('user_approver')
                or current_user.has_role('admin') or current_user.has_role('root')):
            if len(valid_panes) > 0:
                pane = valid_panes[0]
            else:
                pane = None
    else:
        if not pane in valid_panes:
            if len(valid_panes) > 0:
                pane = valid_panes[0]
            else:
                pane = None

    if pane is not None:
        session['faculty_dashboard_pane'] = pane

    if current_user.has_role('root'):
        root_dash_data = get_root_dashboard_data()
    else:
        root_dash_data = None

    approvals_data = get_approvals_data()

    return render_template('faculty/dashboard/dashboard.html', enrollments=enrollments, messages=messages,
                           root_dash_data=root_dash_data, approvals_data=approvals_data, pane=pane,
                           today=date.today())


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

    if current_user.faculty_data in config.confirmation_required:
        config.confirmation_required.remove(current_user.faculty_data)
        db.session.commit()

        flash('Thank you. You confirmation has been recorded.')
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


@faculty.route('/presentation_edit_feedback/<int:slot_id>/<int:talk_id>', methods=['GET', 'POST'])
@roles_required('faculty')
def presentation_edit_feedback(slot_id, talk_id):
    # slot_id labels a ScheduleSlot
    # talk_id labels a SubmissionRecord
    slot = ScheduleSlot.query.get_or_404(slot_id)
    talk = SubmissionRecord.query.get_or_404(talk_id)

    if get_count(slot.talks.filter_by(id=talk.id)) != 1:
        flash('This talk/slot combination does not form a scheduled pair', 'error')
        return redirect(request.referrer)

    if not validate_presentation_assessor(slot):
        return redirect(request.referrer)

    if not validate_assessment(slot.owner.owner):
        return redirect(request.referrer)

    if not slot.owner.deployed:
        flash('Can not edit feedback because the schedule containing this slot has not been deployed.', 'error')
        return redirect(request.referrer)

    if not slot.owner.owner.feedback_open and talk.presentation_assessor_submitted(current_user.id):
        flash('It is not possible to edit feedback after an assessment event has been closed.', 'error')
        return redirect(request.referrer)

    feedback = talk.presentation_feedback.filter_by(assessor_id=current_user.id).first()
    if feedback is None:
        feedback = PresentationFeedback(owner_id=talk.id,
                                        assessor_id=current_user.id,
                                        positive=None,
                                        negative=None,
                                        submitted=False,
                                        timestamp=None)
        db.session.add(feedback)
        db.session.commit()

    form = PresentationFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        feedback.positive = form.positive.data
        feedback.negative = form.negative.data

        if feedback.submitted:
            feedback.timestamp = datetime.now()

        db.session.commit()

        return redirect(url)

    else:

        if request.method == 'GET':
            form.positive.data = feedback.positive
            form.negative.data = feedback.negative

    return render_template('faculty/dashboard/edit_feedback.html', form=form,
                           title='Edit presentation feedback',
                           formtitle='Edit presentation feedback for <strong>{num}</strong>'.format(num=talk.owner.student.user.name),
                           submit_url=url_for('faculty.presentation_edit_feedback', slot_id=slot_id, talk_id=talk_id, url=url),
                           assessment=slot.owner.owner)


@faculty.route('/presentation_submit_feedback/<int:slot_id>/<int:talk_id>')
@roles_required('faculty')
def presentation_submit_feedback(slot_id, talk_id):
    # slot_id labels a ScheduleSlot
    # talk_id labels a SubmissionRecord
    slot = ScheduleSlot.query.get_or_404(slot_id)
    talk = SubmissionRecord.query.get_or_404(talk_id)

    if get_count(slot.talks.filter_by(id=talk.id)) != 1:
        flash('This talk/slot combination does not form a scheduled pair', 'error')
        return redirect(request.referrer)

    if not validate_presentation_assessor(slot):
        return redirect(request.referrer)

    if not validate_assessment(slot.owner.owner):
        return redirect(request.referrer)

    if not slot.owner.deployed:
        flash('Can not submit feedback because the schedule containing this slot has not been deployed.', 'error')
        return redirect(request.referrer)

    if not talk.is_presentation_assessor_valid(current_user.id):
        flash('Cannot submit feedback because it is still incomplete.', 'error')
        return redirect(request.referrer)

    feedback = talk.presentation_feedback.filter_by(assessor_id=current_user.id).one()

    feedback.submitted = True
    feedback.timestamp = datetime.now()
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/presentation_unsubmit_feedback/<int:slot_id>/<int:talk_id>')
@roles_required('faculty')
def presentation_unsubmit_feedback(slot_id, talk_id):
    # slot_id labels a ScheduleSlot
    # talk_id labels a SubmissionRecord
    slot = ScheduleSlot.query.get_or_404(slot_id)
    talk = SubmissionRecord.query.get_or_404(talk_id)

    if get_count(slot.talks.filter_by(id=talk.id)) != 1:
        flash('This talk/slot combination does not form a scheduled pair', 'error')
        return redirect(request.referrer)

    if not validate_presentation_assessor(slot):
        return redirect(request.referrer)

    if not validate_assessment(slot.owner.owner):
        return redirect(request.referrer)

    if not slot.owner.deployed:
        flash('Can not submit feedback because the schedule containing this slot has not been deployed.', 'error')
        return redirect(request.referrer)

    if not slot.owner.owner.feedback_open:
        flash('Cannot unsubmit feedback after an assessment has closed.', 'error')
        return redirect(request.referrer)

    feedback = talk.presentation_feedback.filter_by(assessor_id=current_user.id).one()

    feedback.submitted = False
    feedback.timestamp = None
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
    text = request.args.get('text', None)
    if url is None:
        url = request.referrer

    preview = request.args.get('preview', None)

    return render_template('faculty/dashboard/view_feedback.html', record=record, text=text,
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

        return redirect(url)

    else:

        if request.method == 'GET':
            form.feedback.data = record.faculty_response

    return render_template('faculty/dashboard/edit_response.html', form=form, record=record,
                           submit_url = url_for('faculty.edit_response', id=id, url=url), url=url)


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


@faculty.route('/mark_started/<int:id>')
@roles_accepted('faculty')
def mark_started(id):
    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    if not validate_submission_supervisor(rec):
        return redirect(request.referrer)

    if rec.owner.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to mark a submission period as started', 'error')
        return redirect(request.referrer)

    if rec.submission_period > rec.owner.config.submission_period:
        flash('Cannot mark this submission period as started because it is not yet open', 'error')
        return redirect(request.referrer)

    if not rec.owner.published:
        flash('Cannot mark this submission period as started because it is not published to the submitter', 'error')
        return redirect(request.referrer)

    rec.student_engaged = True
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/set_availability/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty')
def set_availability(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot set availability for this assessment because it has not yet been opened', 'info')
        return redirect(request.referrer)

    if data.availability_closed:
        flash('Cannot set availability for this assessment because it has been closed', 'info')
        return redirect(request.referrer)

    include_confirm = data.is_faculty_outstanding(current_user.id)
    AvailabilityForm = AvailabilityFormFactory(include_confirm)
    form = AvailabilityForm(request.form)

    if form.validate_on_submit():
        comment = form.comment.data
        if len(comment) == 0:
            comment = None

        data.faculty_set_comment(current_user.faculty_data, comment)

        if hasattr(form, 'confirm') and form.confirm:
            record = data.assessor_list.filter_by(faculty_id=current_user.id, confirmed=False).first()
            if record is not None:
                record.confirmed = True
                record.confirmed_timestamp = datetime.now()

            flash('Your availability details have been recorded. Thank you for responding.', 'info')

        elif hasattr(form, 'update') and form.update:
            flash('Thank you: your availability details have been updated', 'info')

        else:
            raise RuntimeError('Unknown submit button in faculty.set_availability')

        db.session.commit()
        return home_dashboard()

    else:
        if request.method == 'GET':
            form.comment.data = data.faculty_get_comment(current_user.faculty_data)

    return render_template('faculty/set_availability.html', form=form, assessment=data, url=url, text=text)


@faculty.route('/session_available/<int:id>')
@roles_accepted('faculty')
def session_available(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationSession.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(request.referrer)

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    if data.owner.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(request.referrer)

    data.faculty_make_available(current_user.faculty_data)
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/session_ifneeded/<int:id>')
@roles_accepted('faculty')
def session_ifneeded(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationSession.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(request.referrer)

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    if data.owner.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(request.referrer)

    data.faculty_make_ifneeded(current_user.faculty_data)
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/session_unavailable/<int:id>')
@roles_accepted('faculty')
def session_unavailable(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationSession.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(request.referrer)

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    if data.owner.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(request.referrer)

    data.faculty_make_unavailable(current_user.faculty_data)
    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/session_all_available/<int:id>')
@roles_accepted('faculty')
def session_all_available(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    if data.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(request.referrer)

    for session in data.sessions:
        session.faculty_make_available(current_user.faculty_data)

    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/session_all_unavailable/<int:id>')
@roles_accepted('faculty')
def session_all_unavailable(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    if data.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(request.referrer)

    for session in data.sessions:
        session.faculty_make_unavailable(current_user.faculty_data)

    db.session.commit()

    return redirect(request.referrer)


@faculty.route('/change_availability')
@roles_accepted('faculty')
def change_availability():
    if not validate_using_assessment():
        return redirect(request.referrer)

    return render_template('faculty/change_availability.html')


@faculty.route('/show_enrollments')
@roles_required('faculty')
def show_enrollments():
    data = FacultyData.query.get_or_404(current_user.id)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

        # avoid circular references
        if url is not None and 'show_enrollments' in url:
            url = None

    pclasses = ProjectClass.query.filter_by(active=True)
    return render_template('faculty/show_enrollments.html', data=data, url=url,
                           project_classes=pclasses)


@faculty.route('/show_workload')
@roles_required('faculty')
def show_workload():
    data = FacultyData.query.get_or_404(current_user.id)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

        # avoid circular references
        if 'show_workload' in url:
            url = None

    return render_template('faculty/show_workload.html', data=data, url=url)


@faculty.route('/settings', methods=['GET', 'POST'])
@roles_required('faculty')
def settings():
    """
    Edit settings for a faculty member
    :return:
    """
    user = User.query.get_or_404(current_user.id)
    data = FacultyData.query.get_or_404(current_user.id)

    FacultySettingsForm = FacultySettingsFormFactory(current_user)
    form = FacultySettingsForm(obj=data)
    form.user = user

    if form.validate_on_submit():
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.username = form.username.data
        user.theme = form.theme.data

        user.group_summaries = form.group_summaries.data
        user.summary_frequency = form.summary_frequency.data

        if hasattr(form, 'mask_roles'):
            user.mask_roles = form.mask_roles.data

            root = _datastore.find_role('root')
            admin = _datastore.find_role('admin')

            if admin in user.mask_roles and root not in user.mask_roles:
                user.mask_roles.append(root)
        else:
            user.mask_roles = []

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.project_capacity = form.project_capacity.data
        data.enforce_capacity = form.enforce_capacity.data
        data.show_popularity = form.show_popularity.data
        data.dont_clash_presentations = form.dont_clash_presentations.data
        data.office = form.office.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        flash('All changes saved', 'success')
        db.session.commit()

        return home_dashboard()

    else:
        # fill in fields that need data from 'User' and won't have been initialized from obj=data
        if request.method == 'GET':
            form.first_name.data = user.first_name
            form.last_name.data = user.last_name
            form.username.data = user.username
            form.theme.data = user.theme

            form.group_summaries.data = user.group_summaries
            form.summary_frequency.data = user.summary_frequency

            if hasattr(form, 'mask_roles'):
                form.mask_roles.data = user.mask_roles

    return render_template('faculty/settings.html', settings_form=form, data=data)
