#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, date
from typing import List, Dict
from uuid import uuid4

from flask import render_template, redirect, url_for, flash, request, session, jsonify, current_app
from flask_security import roles_required, roles_accepted, current_user
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.local import LocalProxy

import app.ajax as ajax
from . import faculty
from .forms import AddProjectFormFactory, EditProjectFormFactory, SkillSelectorForm, \
    AddDescriptionFormFactory, EditDescriptionSettingsFormFactory, MoveDescriptionFormFactory, \
    FacultyPreviewFormFactory, SupervisorFeedbackForm, MarkerFeedbackForm, PresentationFeedbackForm, \
    SupervisorResponseForm, FacultySettingsFormFactory, AvailabilityFormFactory, EditDescriptionContentForm
from ..admin.forms import LevelSelectorForm
from ..database import db
from ..models import DegreeProgramme, FacultyData, ResearchGroup, \
    TransferableSkill, ProjectClassConfig, LiveProject, SelectingStudent, Project, MessageOfTheDay, \
    EnrollmentRecord, SkillGroup, ProjectClass, ProjectDescription, SubmissionRecord, PresentationAssessment, \
    PresentationSession, ScheduleSlot, User, PresentationFeedback, Module, FHEQ_Level, DescriptionComment, \
    WorkflowMixin, ProjectDescriptionWorkflowHistory, StudentData, SubmittingStudent
from ..shared.actions import render_project, do_confirm, do_deconfirm, do_cancel_confirm, do_deconfirm_to_pending
from ..shared.conversions import is_integer
from ..shared.utils import home_dashboard, get_root_dashboard_data, filter_assessors, \
    get_current_year, get_count, get_approvals_data, allow_approvals, redirect_url
from ..shared.validators import validate_edit_project, validate_project_open, validate_is_project_owner, \
    validate_submission_supervisor, validate_submission_marker, validate_submission_viewable, \
    validate_assessment, validate_using_assessment, validate_presentation_assessor, \
    validate_is_convenor, validate_edit_description

_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


# language=jinja2
_marker_menu = \
"""
{% if proj.is_assessor(f.id) %}
    <a href="{{ url_for('faculty.remove_assessor', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm full-width-button btn-secondary">
        <i class="fas fa-trash"></i> Remove
    </a>
{% elif proj.can_enroll_assessor(f) %}
    <a href="{{ url_for('faculty.add_assessor', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm full-width-button btn-secondary">
        <i class="fas fa-plus"></i> Attach
    </a>
{% else %}
    <a class="btn btn-secondary full-width-button btn-sm disabled">
        <i class="fas fa-ban"></i> Can't attach
    </a>
{% endif %}
"""


# label for project description list
# language=jinja2
_desc_label = \
"""
{% set valid = not d.has_issues %}
{% if not valid %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
<a class="text-decoration-none" href="{{ url_for('faculty.project_preview', id=d.parent.id, pclass=desc_pclass_id,
                    url=url_for('faculty.edit_descriptions', id=d.parent.id, create=create),
                    text='description list view') }}">
    {{ d.label }}
</a>
<div>
    {% if d.review_only %}
        <span class="badge bg-info text-dark">Review project</span>
    {% endif %}
</div>
{% set state = d.workflow_state %}
<div>
    {% set not_confirmed = d.requires_confirmation and not d.confirmed %}
    {% if not_confirmed %}
        <span class="badge bg-secondary">Approval: Not confirmed</span>
    {% else %}
        {% if state == d.WORKFLOW_APPROVAL_VALIDATED %}
            <span class="badge bg-success"><i class="fas fa-check"></i> Approved</span>
        {% elif state == d.WORKFLOW_APPROVAL_QUEUED %}
            <span class="badge bg-warning text-dark">Approval: Queued</span>
        {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
            <span class="badge bg-info text-dark">Approval: In progress</span>
        {% else %}
            <span class="badge bg-danger">Unknown approval state</span>
        {% endif %}
        {% if current_user.has_role('project_approver') and d.validated_by %}
            <div>
                <span class="badge bg-info text-dark">Signed-off: {{ d.validated_by.name }}</span>
                {% if d.validated_timestamp %}
                    <span class="badge bg-info text-dark">{{ d.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
                {% endif %}
            </div>
        {% endif %}
    {% endif %}
    {% if d.has_new_comments(current_user) %}
        <div>
            <span class="badge bg-warning text-dark">New comments</span>
        </div>
    {% endif %}
</div>
{% if not valid %}
    <div class="mt-2">
        {% set errors = d.errors %}
        {% set warnings = d.warnings %}
        {% if errors|length == 1 %}
            <span class="badge bg-danger">1 error</span>
        {% elif errors|length > 1 %}
            <span class="badge bg-danger">{{ errors|length }} errors</span>
        {% else %}
            <span class="badge bg-success">0 errors</span>
        {% endif %}
        {% if warnings|length == 1 %}
            <span class="badge bg-warning text-dark">1 warning</span>
        {% elif warnings|length > 1 %}
            <span class="badge bg-warning text-dark">{{ warnings|length }} warnings</span>
        {% else %}
            <span class="badge bg-success">0 warnings</span>
        {% endif %}
        {% if errors|length > 0 %}
            <div class="error-block">
                {% for item in errors %}
                    {% if loop.index <= 5 %}
                        <div class="error-message">{{ item }}</div>
                    {% elif loop.index == 6 %}
                        <div class="error-message">Further errors suppressed...</div>
                    {% endif %}            
                {% endfor %}
            </div>
        {% endif %}
        {% if warnings|length > 0 %}
            <div class="error-block">
                {% for item in warnings %}
                    {% if loop.index <= 5 %}
                        <div class="error-message">Warning: {{ item }}</div>
                    {% elif loop.index == 6 %}
                        <div class="error-message">Further errors suppressed...</div>
                    {% endif %}
                {% endfor %}
            </div>
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_desc_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-o border-0 dropdown-menu-end">
        <a class="dropdown-item" href="{{ url_for('faculty.project_preview', id=d.parent.id, pclass=pclass_id,
           url=url_for('faculty.edit_descriptions', id=d.parent.id, create=create),
           text='description list view') }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit description</div>

        <a class="dropdown-item" href="{{ url_for('faculty.edit_description', did=d.id, create=create,
                                                  url=url_for('faculty.edit_descriptions', id=d.parent_id, create=create),
                                                  text='project variants list') }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.edit_description_content', did=d.id, create=create,
                                                  url=url_for('faculty.edit_descriptions', id=d.parent_id, create=create),
                                                  text='project variants list') }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit content...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.description_modules', did=d.id, create=create) }}">
            <i class="fas fa-cogs fa-fw"></i> Recommended modules...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.duplicate_description', did=d.id) }}">
            <i class="fas fa-clone fa-fw"></i> Duplicate
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.move_description', did=d.id, create=create) }}">
            <i class="fas fa-folder-open fa-fw"></i> Move to project...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.delete_description', did=d.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        
        {% if d.default is none %}
            <a class="dropdown-item" href="{{ url_for('faculty.make_default_description', pid=d.parent_id, did=d.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make default
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('faculty.make_default_description', pid=d.parent_id) }}">
                <i class="fas fa-wrench fa-fw"></i> Remove default
            </a>
        {% endif %}
    </div>
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

    return redirect(redirect_url())


@faculty.route('/remove_affiliation/<int:groupid>')
@roles_required('faculty')
def remove_affiliation(groupid):

    data = FacultyData.query.get_or_404(current_user.id)
    group = ResearchGroup.query.get_or_404(groupid)

    if group in data.affiliations:
        data.remove_affiliation(group, autocommit=True)

    return redirect(redirect_url())


@faculty.route('/edit_projects')
@roles_required('faculty')
def edit_projects():

    groups = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()

    return render_template('faculty/edit_projects.html', groups=groups)


@faculty.route('/projects_ajax')
@roles_required('faculty')
def projects_ajax():
    """
    Ajax data point for Edit Projects view
    :return:
    """

    pq = db.session.query(Project.id).filter_by(owner_id=current_user.id).all()
    data = [(p[0], None) for p in pq]

    return ajax.project.build_data(data, current_user_id=current_user.id, menu_template='faculty',
                                   text='projects list', url=url_for('faculty.edit_projects'))


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

    return ajax.project.build_data(data, current_user_id=current_user.id, show_approvals=False, show_errors=False)


@faculty.route('/edit_descriptions/<int:id>')
@roles_required('faculty')
def edit_descriptions(id):
    project = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    create = request.args.get('create', default=None)

    missing_aims = [x for x in project.descriptions if x.has_warning('aims')]

    return render_template('faculty/edit_descriptions.html', project=project, create=create,
                           missing_aims=missing_aims)


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
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)
    if url is None:
        url = url_for('faculty.edit_projects')
        text = 'project library'

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
            return redirect(url_for('faculty.project_preview', id=id, text=text, url=url))
        else:
            return redirect(url)

    return render_template('faculty/edit_project.html', project_form=form, project=proj, title='Edit project settings',
                           url=url, text=text)


@faculty.route('/remove_project_pclass/<int:proj_id>/<int:pclass_id>')
@roles_required('faculty')
def remove_project_pclass(proj_id, pclass_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    try:
        proj.remove_project_class(pclass)
        db.session.commit()
    except StaleDataError:
        # presumably caused by a race condition?
        db.session.rollback()

    return redirect(redirect_url())


@faculty.route('/activate_project/<int:id>')
@roles_required('faculty')
def activate_project(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    proj.enable()
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/deactivate_project/<int:id>')
@roles_required('faculty')
def deactivate_project(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(data):
        return redirect(redirect_url())

    data.disable()
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/delete_project/<int:id>')
@roles_required('faculty')
def delete_project(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(data):
        return redirect(redirect_url())

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
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not delete project due to a database error. Please contact a system administrator', 'error')

    return redirect(url)


@faculty.route('/add_description/<int:pid>', methods=['GET', 'POST'])
@roles_required('faculty')
def add_description(pid):
    # get parent project details
    proj = Project.query.get_or_404(pid)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    create = request.args.get('create', default=None)

    AddDescriptionForm = AddDescriptionFormFactory(pid)
    form = AddDescriptionForm(request.form)
    form.project_id = pid

    if form.validate_on_submit():

        data = ProjectDescription(parent_id=pid,
                                  label=form.label.data,
                                  project_classes=form.project_classes.data,
                                  description=None,
                                  reading=None,
                                  aims=form.aims.data,
                                  team=form.team.data,
                                  confirmed=False,
                                  workflow_state=WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
                                  validator_id=None,
                                  validated_timestamp=None,
                                  capacity=form.capacity.data,
                                  review_only=form.review_only.data,
                                  creator_id=current_user.id,
                                  creation_timestamp=datetime.now())

        try:
            db.session.add(data)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash('Could not add new description due to a database error. Please contact a system administrator',
                  'error')

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
    if not validate_edit_description(desc):
        return redirect(redirect_url())

    create = request.args.get('create', default=None)
    focus_aims = bool(int(request.args.get('focus_aims', 0)))
    url = request.args.get('url', None)
    text = request.args.get('text', None)
    if url is None:
        url = url_for('faculty.edit_descriptions', id=desc.parent_id, create=create)
        text = 'project variants list'

    EditDescriptionForm = EditDescriptionSettingsFormFactory(desc.parent_id, did)
    form = EditDescriptionForm(obj=desc)
    form.project_id = desc.parent_id
    form.desc = desc

    if focus_aims:
        if not hasattr(form.aims, 'errors') or form.aims.errors is None:
            form.aims.errors = tuple()

        form.aims.errors = (*form.aims.errors, 'Thank you for helping to improve our database. '
                                               'Please enter your statement of aims and save changes.')

    if form.validate_on_submit():
        desc.label = form.label.data
        desc.project_classes = form.project_classes.data
        desc.aims = form.aims.data
        desc.team = form.team.data
        desc.capacity = form.capacity.data
        desc.review_only = form.review_only.data
        desc.last_edit_id = current_user.id
        desc.last_edit_timestamp = datetime.now()

        desc.validate_modules()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash('Could not edit project description due to a database error. '
                  'Please contact a system administrator', 'error')

        return redirect(url)

    return render_template('faculty/edit_description.html', project=desc.parent, desc=desc, form=form,
                           title='Edit description', create=create, url=url, text=text)


@faculty.route('/edit_description_content/<int:did>', methods=['GET', 'POST'])
@roles_required('faculty')
def edit_description_content(did):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_edit_description(desc):
        return redirect(redirect_url())

    create = request.args.get('create', default=None)
    url = request.args.get('url', None)
    text = request.args.get('text', None)
    if url is None:
        url = url_for('faculty.edit_descriptions', id=desc.parent_id, create=create)
        text = 'project variants list'

    form = EditDescriptionContentForm(obj=desc)

    if form.validate_on_submit():
        desc.description = form.description.data
        desc.reading = form.reading.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash('Could not edit project description due to a database error. '
                  'Please contact a system administrator', 'error')

        return redirect(url)

    return render_template('faculty/edit_description_content.html', project=desc.parent, desc=desc, form=form,
                           title='Edit description', create=create, url=url, text=text)


@faculty.route('/description_modules/<int:did>/<int:level_id>', methods=['GET', 'POST'])
@faculty.route('/description_modules/<int:did>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def description_modules(did, level_id=None):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_edit_description(desc):
        return redirect(redirect_url())

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
    if not validate_edit_description(desc):
        return redirect(redirect_url())

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
    if not validate_edit_description(desc):
        return redirect(redirect_url())

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
    if not validate_edit_description(desc):
        return redirect(redirect_url())

    try:
        db.session.delete(desc)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not delete project description due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@faculty.route('/duplicate_description/<int:did>')
@roles_required('faculty')
def duplicate_description(did):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    suffix = 2
    while suffix < 100:
        new_label = '{label} #{suffix}'.format(label=desc.label, suffix=suffix)

        if ProjectDescription.query.filter_by(parent_id=desc.parent_id, label=new_label).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash('Could not duplicate variant "{label}" because a new unique label could not '
              'be generated'.format(label=desc.label), 'error')
        return redirect(redirect_url())

    data = ProjectDescription(parent_id=desc.parent_id,
                              label=new_label,
                              project_classes=[],
                              modules=[],
                              capacity=desc.capacity,
                              description=desc.description,
                              reading=desc.reading,
                              team=desc.team,
                              confirmed=False,
                              workflow_state=WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
                              validator_id=None,
                              validated_timestamp=None,
                              creator_id=current_user.id,
                              creation_timestamp=datetime.now())

    try:
        db.session.add(data)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not duplicate project description due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@faculty.route('/move_description/<int:did>', methods=['GET', 'POST'])
@roles_required('faculty')
def move_description(did):
    desc = ProjectDescription.query.get_or_404(did)
    old_project = desc.parent

    # if project owner is not logged-in user, object
    if not validate_edit_description(desc):
        return redirect(redirect_url())

    create = request.args.get('create', default=None)

    MoveDescriptionForm = MoveDescriptionFormFactory(old_project.owner_id, old_project.id)
    form = MoveDescriptionForm(request.form)

    if form.validate_on_submit():
        new_project = form.destination.data
        leave_copy = form.copy.data

        if new_project is not None:
            if leave_copy:
                copy_desc = ProjectDescription(parent_id=desc.parent.id,
                                               label=desc.label,
                                               description=desc.description,
                                               reading=desc.reading,
                                               team=desc.team,
                                               project_classes=desc.project_classes,
                                               modules=desc.modules,
                                               capacity=desc.capacity,
                                               confirmed=False,
                                               workflow_state=desc.workflow_state,
                                               validator_id=desc.validator_id,
                                               validated_timestamp=desc.validated_timestamp,
                                               creator_id=current_user.id,
                                               creation_timestamp=datetime.now())
            else:
                copy_desc = None

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
            if copy_desc is not None:
                db.session.add(copy_desc)

            try:
                db.session.commit()
                flash('Variant "{name}" successfully moved to project '
                      '"{pname}"'.format(name=desc.label, pname=new_project.name), 'info')
            except SQLAlchemyError as e:
                db.session.rollback()
                flash('Variant "{name}" could not be moved due to a database error'.format(name=desc.label),
                      'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        else:
            flash('Variant "{name}" could not be moved because its parent project is '
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
    if not validate_edit_project(proj):
        return redirect(redirect_url())

    if did is not None:
        desc = ProjectDescription.query.get_or_404(did)

        if desc.parent_id != pid:
            flash('Cannot set default description (id={did)) for project (id={pid}) because this description '
                  'does not belong to the project'.format(pid=pid, did=did), 'error')
            return redirect(redirect_url())

    proj.default_id = did
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/attach_skills/<int:id>/<int:sel_id>')
@faculty.route('/attach_skills/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def attach_skills(id, sel_id=None):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

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
        return redirect(redirect_url())

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
        return redirect(redirect_url())

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
        return redirect(redirect_url())

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
        return redirect(redirect_url())

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme not in proj.programmes:
        proj.add_programme(programme)
        db.session.commit()

    return redirect(redirect_url())


@faculty.route('/remove_programme/<int:id>/<int:prog_id>')
@roles_required('faculty')
def remove_programme(id, prog_id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme in proj.programmes:
        proj.remove_programme(programme)
        db.session.commit()

    return redirect(redirect_url())


@faculty.route('/attach_assessors/<int:id>')
@roles_required('faculty')
def attach_assessors(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

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
        return redirect(redirect_url())

    assessor = FacultyData.query.get_or_404(mid)

    proj.add_assessor(assessor, autocommit=True)

    return redirect(redirect_url())


@faculty.route('/remove_assessor/<int:proj_id>/<int:mid>')
@roles_required('faculty')
def remove_assessor(proj_id, mid):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    assessor = FacultyData.query.get_or_404(mid)

    proj.remove_assessor(assessor, autocommit=True)

    return redirect(redirect_url())


@faculty.route('/attach_all_assessors/<int:proj_id>')
@roles_required('faculty')
def attach_all_assessors(proj_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    assssors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assssors:
        proj.add_assessor(assessor, autocommit=False)

    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/remove_all_assessors/<int:proj_id>')
@roles_required('faculty')
def remove_all_assessors(proj_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    assessors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessors:
        proj.remove_assessor(assessor, autocommit=False)

    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/preview/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root', 'project_approver')
def project_preview(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(data, 'project_approver'):
        return redirect(redirect_url())

    show_selector = bool(int(request.args.get('show_selector', True)))
    all_comments = bool(int(request.args.get('all_comments', False)))
    all_workflow = bool(int(request.args.get('all_workflow', False)))

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

        # notify watchers on this thread that a new comment has been posted
        celery = current_app.extensions['celery']
        notify = celery.tasks['app.tasks.issue_confirm.notify_comment']
        notify.apply_async(args=(comment.id,))

        form.comment.data = None

    # defaults for comments pane
    form.limit_visibility.data = True if current_user.has_role('project_approver') else False

    allow_approval = current_user.has_role('project_approver') and desc is not None and allow_approvals(desc.id)

    if desc is not None:
        if all_workflow:
            workflow_history = desc.workflow_history \
                .order_by(ProjectDescriptionWorkflowHistory.timestamp.asc()).all()
        else:
            workflow_history = desc.workflow_history.filter_by(year=current_year) \
                .order_by(ProjectDescriptionWorkflowHistory.timestamp.asc()).all()

        if all_comments:
            comments = desc.comments.order_by(DescriptionComment.creation_timestamp.asc()).all()
        else:
            comments = desc.comments.filter_by(year=current_year) \
                .order_by(DescriptionComment.creation_timestamp.asc()).all()
    else:
        workflow_history = []
        comments = []

    data.update_last_viewed_time(current_user, commit=True)

    return render_project(data, desc, form=form, text=text, url=url,
                          show_selector=show_selector, allow_approval=allow_approval,
                          show_comments=True, comments=comments, all_comments=all_comments,
                          all_workflow=all_workflow, pclass_id=pclass_id, workflow_history=workflow_history)


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
        isare = 'is' if unofferable == 1 else 'are'

        flash('You have {n} project{plural} that {isare} active but cannot be offered to students. '
              'Please check your project list.'.format(n=unofferable, plural=plural, isare=isare),
              'error')

    # build list of current configuration records for all enrolled project classes
    enrollments = []
    valid_panes = []
    for record in current_user.faculty_data.ordered_enrollments:
        pclass = record.pclass
        config = pclass.most_recent_config

        if pclass.active and pclass.publish and config is not None:
            include = False

            if (pclass.uses_supervisor and record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED) \
                    or (config.uses_marker and config.display_marker
                        and record.marker_state == EnrollmentRecord.MARKER_ENROLLED) \
                    or (config.uses_presentations and config.display_presentations
                        and record.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED):
                include = True

            else:
                for n in range(config.submissions):
                    period = config.get_period(n+1)

                    supv_records = period.get_supervisor_records(current_user.id)
                    mark_records = period.get_marker_records(current_user.id)
                    pres_slots = period.get_faculty_presentation_slots(current_user.id) \
                        if (period.has_presentation and period.has_deployed_schedule) else []

                    if (pclass.uses_supervisor and len(supv_records) > 0) \
                            or (config.uses_marker and config.display_marker and len(mark_records) > 0) \
                            or (config.uses_presentations and config.display_presentations and len(pres_slots) > 0):
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
        if pane not in valid_panes:
            if len(valid_panes) > 0:
                pane = valid_panes[0]
            else:
                pane = None

        # mark any unviewed confirmation requests as viewed, but do it with a 15 sec delay so that the
        # NEW labels don't disappear immediately
        if pane is not None:
            celery = current_app.extensions['celery']
            remove_new = celery.tasks['app.tasks.selecting.remove_new']
            remove_new.apply_async(args=(int(pane), current_user.id), countdown=15)

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
    pclass: ProjectClass = db.session.query(ProjectClass).filter_by(id=id).first()
    config: ProjectClassConfig = pclass.most_recent_config

    if not config.requests_issued:
        flash('Confirmation requests have not yet been issued for {project} '
              '{yeara}-{yearb}'.format(project=config.name, yeara=config.year, yearb=config.year+1))
        return redirect(redirect_url())

    if config.live:
        flash('Confirmation is no longer required for {project} {yeara}-{yearb} because this project '
              'has already gone live'.format(project=config.name, yeara=config.year, yearb=config.year+1))
        return redirect(redirect_url())

    if not config.is_confirmation_required(current_user.faculty_data):
        flash('You have no outstanding confirmation requests for {project} {yeara}-{yearb}'.format(
            project=config.name, yeara=config.year, yearb=config.year+1))
        return redirect(redirect_url())

    config.mark_confirmed(current_user.faculty_data, message=True)
    db.session.commit()

    # kick off a background task to check whether any other project classes in which this user is enrolled
    # have been reduced to zero confirmations left.
    # If so, treat this 'Confirm' click as accounting for them also
    celery = current_app.extensions['celery']
    task = celery.tasks['app.tasks.issue_confirm.propagate_confirm']
    task.apply_async(args=(current_user.id, id))

    return redirect(redirect_url())


@faculty.route('/confirm_description/<int:did>/<int:pclass_id>')
@roles_required('faculty')
def confirm_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    # get current configuration record for this project class
    pcl: ProjectClass = db.session.query(ProjectClass).filter_by(id=pclass_id).first()
    config: ProjectClassConfig = pcl.most_recent_config

    if not config.requests_issued:
        flash('Confirmation requests have not yet been issued for {project} {yeara}-{yearb}'.format(
            project=config.name, yeara=config.year, yearb=config.year+1))
        return redirect(redirect_url())

    if config.live:
        flash('Confirmation is no longer required for {project} {yeara}-{yearb} because this project '
              'has already gone live'.format(project=config.name, yeara=config.year, yearb=config.year + 1))
        return redirect(redirect_url())

    # if project owner is not logged in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    desc.confirmed = True
    db.session.commit()

    # if no further confirmations outstanding, mark whole configuration as confirmed
    if not config.has_confirmations_outstanding(current_user.faculty_data):
        config.mark_confirmed(current_user.faculty_data, message=True)
        db.session.commit()

    # kick off a background task to check whether any other project classes in which this user is enrolled
    # have been reduced to zero confirmations left.
    # If so, treat this 'Confirm' click as accounting for them also
    celery = current_app.extensions['celery']
    task = celery.tasks['app.tasks.issue_confirm.propagate_confirm']
    task.apply_async(args=(current_user.id, pclass_id))

    return redirect(redirect_url())


@faculty.route('/confirm/<int:sid>/<int:pid>')
@roles_required('faculty')
def confirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_confirm(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@faculty.route('/deconfirm/<int:sid>/<int:pid>')
@roles_required('faculty')
def deconfirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_deconfirm(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@faculty.route('/deconfirm_to_pending/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def deconfirm_to_pending(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@faculty.route('/cancel_confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def cancel_confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_cancel_confirm(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@faculty.route('/live_project/<int:pid>')
@roles_accepted('student', 'faculty', 'admin', 'root')
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
        url = redirect_url()

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
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash('Feedback collection has been disabled for this submission period.', 'info')
        return redirect(redirect_url())

    period = record.period

    if not period.is_feedback_open:
        flash('Can not edit feedback for this submission because the convenor has not yet opened this submission '
              'period for feedback and marking.',
              'error')
        return redirect(redirect_url())

    if period.closed and record.supervisor_submitted:
        flash('It is not possible to edit feedback after the convenor has closed this submission period.',
              'error')
        return redirect(redirect_url())

    form = SupervisorFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = redirect_url()

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
                           title='Edit supervisor feedback', unique_id='supv-{id}'.format(id=id),
                           formtitle='Edit supervisor feedback for <i class="fas fa-user"></i> <strong>{name}</strong>'.format(name=record.student_identifier),
                           submit_url=url_for('faculty.supervisor_edit_feedback', id=id, url=url),
                           period=period, record=record)


@faculty.route('/marker_edit_feedback/<int:id>', methods=['GET', 'POST'])
@roles_required('faculty')
def marker_edit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_marker(record):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash('Feedback collection has been disabled for this submission period.', 'info')
        return redirect(redirect_url())

    period = record.period

    if not period.is_feedback_open:
        flash('Can not edit feedback for this submission because the convenor has not yet opened this submission '
              'period for feedback and marking.',
              'error')
        return redirect(redirect_url())

    if period.closed and record.marker_submitted:
        flash('It is not possible to edit feedback after the convenor has closed this submission period.',
              'error')
        return redirect(redirect_url())

    form = MarkerFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = redirect_url()

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
                           title='Edit marker feedback', unique_id='mark-{id}'.format(id=id),
                           formtitle='Edit marker feedback for <strong>{num}</strong>'.format(num=record.owner.student.exam_number),
                           submit_url=url_for('faculty.marker_edit_feedback', id=id, url=url),
                           period=period, record=record)


@faculty.route('/supervisor_submit_feedback/<int:id>')
@roles_required('faculty')
def supervisor_submit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash('Feedback collection has been disabled for this submission period.', 'info')
        return redirect(redirect_url())

    if record.supervisor_submitted:
        return redirect(redirect_url())

    period = record.period

    if not period.is_feedback_open:
        flash('It is not possible to submit before the feedback period has opened.', 'error')
        return redirect(redirect_url())

    if not record.is_supervisor_valid:
        flash('Cannot submit feedback because it is still incomplete.', 'error')
        return redirect(redirect_url())

    record.supervisor_submitted = True
    record.supervisor_timestamp = datetime.now()
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/supervisor_unsubmit_feedback/<int:id>')
@roles_required('faculty')
def supervisor_unsubmit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash('Feedback collection has been disabled for this submission period.', 'info')
        return redirect(redirect_url())

    if not record.supervisor_submitted:
        return redirect(redirect_url())

    period = record.period

    if period.closed:
        flash('It is not possible to unsubmit after the feedback period has closed.', 'error')
        return redirect(redirect_url())

    record.supervisor_submitted = False
    record.supervisor_timestamp = None
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/marker_submit_feedback/<int:id>')
@roles_required('faculty')
def marker_submit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_marker(record):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash('Feedback collection has been disabled for this submission period.', 'info')
        return redirect(redirect_url())

    if record.marker_submitted:
        return redirect(redirect_url())

    period = record.period

    if not period.is_feedback_open:
        flash('It is not possible to submit before the feedback period has opened.', 'error')
        return redirect(redirect_url())

    if not record.is_marker_valid:
        flash('Cannot submit feedback because it is still incomplete.', 'error')
        return redirect(redirect_url())

    record.marker_submitted = True
    record.marker_timestamp = datetime.now()
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/marker_unsubmit_feedback/<int:id>')
@roles_required('faculty')
def marker_unsubmit_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_marker(record):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash('Feedback collection has been disabled for this submission period.', 'info')
        return redirect(redirect_url())

    if not record.marker_submitted:
        return redirect(redirect_url())

    period = record.period

    if period.closed:
        flash('It is not possible to unsubmit after the feedback period has closed.', 'error')
        return redirect(redirect_url())

    record.marker_submitted = False
    record.marker_timestamp = None
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/supervisor_acknowledge_feedback/<int:id>')
@roles_required('faculty')
def supervisor_acknowledge_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(redirect_url())

    if record.acknowledge_feedback:
        return redirect(redirect_url())

    period = record.period

    if not period.is_feedback_open:
        flash('It is not possible to submit before the feedback period has opened.', 'error')
        return redirect(redirect_url())

    if not record.student_feedback_submitted:
        flash('Cannot acknowledge student feedback because none has been submitted.', 'error')
        return redirect(redirect_url())

    record.acknowledge_feedback = True
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/presentation_edit_feedback/<int:slot_id>/<int:talk_id>', methods=['GET', 'POST'])
@roles_required('faculty')
def presentation_edit_feedback(slot_id, talk_id):
    # slot_id labels a ScheduleSlot
    # talk_id labels a SubmissionRecord
    slot = ScheduleSlot.query.get_or_404(slot_id)
    talk = SubmissionRecord.query.get_or_404(talk_id)

    if get_count(slot.talks.filter_by(id=talk.id)) != 1:
        flash('This talk/slot combination does not form a scheduled pair', 'error')
        return redirect(redirect_url())

    if not validate_presentation_assessor(slot):
        return redirect(redirect_url())

    if not validate_assessment(slot.owner.owner):
        return redirect(redirect_url())

    if not slot.owner.deployed:
        flash('Can not edit feedback because the schedule containing this slot has not been deployed.', 'error')
        return redirect(redirect_url())

    if not slot.owner.owner.is_feedback_open and talk.presentation_assessor_submitted(current_user.id):
        flash('It is not possible to edit feedback after an assessment event has been closed.', 'error')
        return redirect(redirect_url())

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
        url = redirect_url()

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

    return render_template('faculty/dashboard/edit_feedback.html', form=form, unique_id='pres-{id}'.format(id=id),
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
        return redirect(redirect_url())

    if not validate_presentation_assessor(slot):
        return redirect(redirect_url())

    if not validate_assessment(slot.owner.owner):
        return redirect(redirect_url())

    if not slot.owner.deployed:
        flash('Can not submit feedback because the schedule containing this slot has not been deployed.', 'error')
        return redirect(redirect_url())

    if not talk.is_presentation_assessor_valid(current_user.id):
        flash('Cannot submit feedback because it is still incomplete.', 'error')
        return redirect(redirect_url())

    feedback = talk.presentation_feedback.filter_by(assessor_id=current_user.id).one()

    feedback.submitted = True
    feedback.timestamp = datetime.now()
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/presentation_unsubmit_feedback/<int:slot_id>/<int:talk_id>')
@roles_required('faculty')
def presentation_unsubmit_feedback(slot_id, talk_id):
    # slot_id labels a ScheduleSlot
    # talk_id labels a SubmissionRecord
    slot = ScheduleSlot.query.get_or_404(slot_id)
    talk = SubmissionRecord.query.get_or_404(talk_id)

    if get_count(slot.talks.filter_by(id=talk.id)) != 1:
        flash('This talk/slot combination does not form a scheduled pair', 'error')
        return redirect(redirect_url())

    if not validate_presentation_assessor(slot):
        return redirect(redirect_url())

    if not validate_assessment(slot.owner.owner):
        return redirect(redirect_url())

    if not slot.owner.deployed:
        flash('Can not submit feedback because the schedule containing this slot has not been deployed.', 'error')
        return redirect(redirect_url())

    if not slot.owner.owner.is_feedback_open:
        flash('Cannot unsubmit feedback after an assessment has closed.', 'error')
        return redirect(redirect_url())

    feedback = talk.presentation_feedback.filter_by(assessor_id=current_user.id).one()

    feedback.submitted = False
    feedback.timestamp = None
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/view_feedback/<int:id>')
@roles_required('faculty')
def view_feedback(id):
    # id is a SubmissionRecord instance
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_viewable(record):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)
    if url is None:
        url = redirect_url()

    preview = request.args.get('preview', None)

    return render_template('faculty/dashboard/view_feedback.html', record=record, text=text,
                           url=url, preview=preview)


@faculty.route('/edit_response/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty')
def edit_response(id):

    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_supervisor(record):
        return redirect(redirect_url())

    period = record.period

    if not period.closed:
        flash('It is only possible to give respond to feedback from your student when '
              'their own marks and feedback are available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(redirect_url())

    if period.closed and record.faculty_response_submitted:
        flash('It is not possible to edit your response once it has been submitted', 'info')
        return redirect(redirect_url())

    if period.closed and not record.student_feedback_submitted:
        flash('It is not possible to write a response to feedback from your student before '
              'they have submitted it.', 'info')
        return redirect(redirect_url())

    form = SupervisorResponseForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = redirect_url()

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
        return redirect(redirect_url())

    period = record.period

    if record.faculty_response_submitted:
        return redirect(redirect_url())

    if not period.closed:
        flash('It is only possible to give respond to feedback from your student when '
              'their own marks and feedback are available. '
              'Try again when this submission period is closed.', 'info')
        return redirect(redirect_url())

    if period.closed and record.faculty_response_submitted:
        flash('It is not possible to edit your response once it has been submitted', 'info')
        return redirect(redirect_url())

    if period.closed and not record.student_feedback_submitted:
        flash('It is not possible to write a response to feedback from your student before '
              'they have submitted it.', 'info')
        return redirect(redirect_url())

    if not record.is_response_valid:
        flash('Cannot submit your feedback because it is incomplete.', 'info')
        return redirect(redirect_url())

    record.faculty_response_submitted = True
    record.faculty_response_timestamp = datetime.now()
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/mark_started/<int:id>')
@roles_accepted('faculty')
def mark_started(id):
    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    if not validate_submission_supervisor(rec):
        return redirect(redirect_url())

    if rec.owner.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to mark a submission period as started', 'error')
        return redirect(redirect_url())

    if rec.submission_period > rec.owner.config.submission_period:
        flash('Cannot mark this submission period as started because it is not yet open', 'error')
        return redirect(redirect_url())

    if not rec.owner.published:
        flash('Cannot mark this submission period as started because it is not published to the submitter', 'error')
        return redirect(redirect_url())

    rec.student_engaged = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not mark student as "engaged" due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@faculty.route('/mark_waiting/<int:id>')
@roles_accepted('faculty')
def mark_waiting(id):
    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    if not validate_submission_supervisor(rec):
        return redirect(redirect_url())

    if rec.owner.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late change engagement status for this submission period', 'error')
        return redirect(redirect_url())

    if rec.submission_period > rec.owner.config.submission_period:
        flash('Cannot change engagement status for this submission period because it is not yet open', 'error')
        return redirect(redirect_url())

    if not rec.owner.published:
        flash('Cannot change engagement status for this submission period because it is not published '
              'to the submitter', 'error')
        return redirect(redirect_url())

    rec.student_engaged = False

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not mark student as "not engaged" due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@faculty.route('/set_availability/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty')
def set_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    data = PresentationAssessment.query.get_or_404(id)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(redirect_url())

    if not data.requested_availability:
        flash('Cannot set availability for this assessment because it has not yet been opened', 'info')
        return redirect(redirect_url())

    if data.availability_closed:
        flash('Cannot set availability for this assessment because it has been closed', 'info')
        return redirect(redirect_url())

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
        return redirect(redirect_url())

    data = PresentationSession.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(redirect_url())

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(redirect_url())

    if data.owner.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(redirect_url())

    data.faculty_make_available(current_user.faculty_data)
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/session_ifneeded/<int:id>')
@roles_accepted('faculty')
def session_ifneeded(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    data = PresentationSession.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(redirect_url())

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(redirect_url())

    if data.owner.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(redirect_url())

    data.faculty_make_ifneeded(current_user.faculty_data)
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/session_unavailable/<int:id>')
@roles_accepted('faculty')
def session_unavailable(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    data = PresentationSession.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(redirect_url())

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(redirect_url())

    if data.owner.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(redirect_url())

    data.faculty_make_unavailable(current_user.faculty_data)
    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/session_all_available/<int:id>')
@roles_accepted('faculty')
def session_all_available(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(redirect_url())

    if not data.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(redirect_url())

    if data.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(redirect_url())

    for session in data.sessions:
        session.faculty_make_available(current_user.faculty_data)

    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/session_all_unavailable/<int:id>')
@roles_accepted('faculty')
def session_all_unavailable(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(redirect_url())

    if not data.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(redirect_url())

    if data.availability_closed:
        flash('Cannot set availability for this session because its parent assessment has been closed', 'info')
        return redirect(redirect_url())

    for session in data.sessions:
        session.faculty_make_unavailable(current_user.faculty_data)

    db.session.commit()

    return redirect(redirect_url())


@faculty.route('/change_availability')
@roles_accepted('faculty')
def change_availability():
    if not validate_using_assessment():
        return redirect(redirect_url())

    return render_template('faculty/change_availability.html')


@faculty.route('/show_enrollments')
@roles_required('faculty')
def show_enrollments():
    data = FacultyData.query.get_or_404(current_user.id)

    url = request.args.get('url', None)
    if url is None:
        url = redirect_url()

        # avoid circular references
        if url is not None and 'show_enrollments' in url:
            url = None

    pclasses = db.session.query(ProjectClass).filter_by(active=True, publish=True).all()
    return render_template('faculty/show_enrollments.html', data=data, url=url,
                           project_classes=pclasses)


@faculty.route('/show_workload')
@roles_required('faculty')
def show_workload():
    data = FacultyData.query.get_or_404(current_user.id)

    url = request.args.get('url', None)
    if url is None:
        url = redirect_url()

        # avoid circular references
        if isinstance(url, str) and 'show_workload' in url:
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
        user.default_license = form.default_license.data

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
            form.default_license.data = user.default_license

            form.group_summaries.data = user.group_summaries
            form.summary_frequency.data = user.summary_frequency

            if hasattr(form, 'mask_roles'):
                form.mask_roles.data = user.mask_roles

    return render_template('faculty/settings.html', settings_form=form, data=data)


@faculty.route('/past_feedback/<int:student_id>')
@roles_accepted('faculty', 'admin', 'root')
def past_feedback(student_id):
    """
    Show past feedback associated with this student
    :param student_id:
    :return:
    """
    user: User = User.query.get_or_404(student_id)

    if not user.has_role('student'):
        flash('It is only possible to view past feedback for a student account.', 'info')
        return redirect(redirect_url())

    if user.student_data is None:
        flash('Cannot display past feedback for this student account because the corresponding '
              'StudentData record is missing.', 'error')
        return redirect(redirect_url())

    data: StudentData = user.student_data

    if not data.has_previous_submissions:
        flash('This student does not yet have any past feedback. Feedback will be available to view once '
              'the student has made one or more project submissions.', 'info')
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    # collate retired selector and submitter records for this student
    years: List[int]
    selector_records: Dict[List[SelectingStudent]]
    submitter_records: Dict[List[SubmittingStudent]]
    years, selector_records, submitter_records = data.collect_student_records()

    # check roles for logged-in user, to determine whether they are permitted to view the student's feedback
    roles = {}
    for year in submitter_records:
        submissions: List[SubmittingStudent] = submitter_records[year]

        for sub in submissions:
            sub: SubmittingStudent

            for record in sub.ordered_assignments:
                record: SubmissionRecord

                # convenor can always view feedback and documents
                if validate_is_convenor(sub.config.project_class, message=False):
                    roles[record.id] = 'convenor'

                # otherwise perform usual check
                elif validate_submission_viewable(record, message=False):
                    roles[record.id] = 'faculty'

    student_text = 'student feedback'
    generic_text = 'student feedback'
    return_url = url_for('faculty.past_feedback', student_id=data.id, text=text, url=url)

    return render_template('student/timeline.html', data=data, user=user, years=years,
                           selector_records={}, submitter_records=submitter_records,
                           roles=roles, text=text, url=url,
                           student_text=student_text, generic_text=generic_text, return_url=return_url)
