 #
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_security import roles_accepted, current_user

from celery import chain

from ..database import db
from ..models import User, FacultyData, StudentData, TransferableSkill, ProjectClass, ProjectClassConfig, \
    LiveProject, SelectingStudent, Project, EnrollmentRecord, ResearchGroup, SkillGroup, \
    PopularityRecord, FilterRecord, DegreeProgramme, ProjectDescription, SelectionRecord, SubmittingStudent, \
    SubmissionRecord, PresentationFeedback, Module, FHEQ_Level, DegreeType

from ..shared.utils import get_current_year, home_dashboard, get_convenor_dashboard_data, get_capacity_data, \
    filter_projects, get_convenor_filter_record, filter_assessors, build_enroll_selector_candidates, \
    build_enroll_submitter_candidates, build_submitters_data
from ..shared.validators import validate_is_convenor, validate_is_administrator, validate_edit_project, \
    validate_project_open, validate_not_attending
from ..shared.actions import do_confirm, do_cancel_confirm, do_deconfirm, do_deconfirm_to_pending
from ..shared.convenor import add_selector, add_liveproject, add_blank_submitter
from ..shared.conversions import is_integer

from ..task_queue import register_task

import app.ajax as ajax

from . import convenor

from ..admin.forms import LevelSelectorForm
from ..faculty.forms import AddProjectFormFactory, EditProjectFormFactory, SkillSelectorForm, \
    AddDescriptionFormFactory, EditDescriptionFormFactory, PresentationFeedbackForm
from .forms import GoLiveForm, IssueFacultyConfirmRequestForm, OpenFeedbackForm, AssignMarkerFormFactory, \
    AssignPresentationFeedbackFormFactory

from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from datetime import date, datetime, timedelta


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
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-pencil"></i> Descriptions...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-cogs"></i> Assessors...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-cogs"></i> Transferable skills...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-cogs"></i> Degree programmes...
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-wrench"></i> Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


_unattached_project_menu = \
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
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Descriptions...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Assessors...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Transferable skills...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Degree programmes...
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-wrench"></i> Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


_marker_menu = \
"""
{% if proj.is_assessor(f) %}
    <a href="{{ url_for('convenor.remove_assessor', proj_id=proj.id, pclass_id=pclass_id, mid=f.id) }}"
       class="btn btn-sm btn-default">
        <i class="fa fa-trash"></i> Remove
    </a>
{% elif proj.can_enroll_assessor(f) %}
    <a href="{{ url_for('convenor.add_assessor', proj_id=proj.id, pclass_id=pclass_id, mid=f.id) }}"
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
<a href="{{ url_for('convenor.edit_description', did=d.id, pclass_id=pclass_id) }}">{{ d.label }}</a>
{% if not d.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
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
                <a href="{{ url_for('convenor.edit_description', did=d.id, pclass_id=pclass_id, create=create) }}">
                    <i class="fa fa-pencil"></i> Edit description...
                </a>
            </li>
            <li>
                <a href="{{ url_for('convenor.description_modules', did=d.id, pclass_id=pclass_id, create=create) }}">
                    <i class="fa fa-cogs"></i> Module pre-requisites...
                </a>
            </li>
            <li>
                <a href="{{ url_for('convenor.delete_description', did=d.id, pclass_id=pclass_id) }}">
                    <i class="fa fa-trash"></i> Delete
                </a>
            </li>
    
            <li role="separator" class="divider"></li>
    
            <li>
                <a href="{{ url_for('convenor.duplicate_description', did=d.id, pclass_id=pclass_id) }}">
                    <i class="fa fa-clone"></i> Duplicate
                </a>
            </li>
            <li>
                {% if d.default is none %}
                    <a href="{{ url_for('convenor.make_default_description', pid=d.parent_id, pclass_id=pclass_id, did=d.id) }}">
                        <i class="fa fa-wrench"></i> Make default
                    </a>
                {% else %}
                    <a href="{{ url_for('convenor.make_default_description', pid=d.parent_id, pclass_id=pclass_id) }}">
                        <i class="fa fa-wrench"></i> Remove default
                    </a>
                {% endif %}
            </li>
        </ul>
    </div>
 """


@convenor.route('/overview/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def overview(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    # get record for current submission period
    period = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash('Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    # build forms
    golive_form = GoLiveForm(request.form)
    issue_form = IssueFacultyConfirmRequestForm(request.form)
    feedback_form = OpenFeedbackForm(request.form)

    # change labels and text depending on current lifecycle state
    if config.requests_issued:
        issue_form.request_deadline.label.text = 'The current deadline for responses is'
        issue_form.requests_issued.label.text = 'Save changes'

    if period is not None and period.feedback_open:
        feedback_form.feedback_deadline.label.text = 'The current deadline for feedback is'
        feedback_form.open_feedback.label.text = 'Save changes'

    if request.method == 'GET':
        if config.request_deadline is not None:
            issue_form.request_deadline.data = config.request_deadline
        else:
            issue_form.request_deadline.data = date.today() + timedelta(weeks=6)

        if config.live_deadline is not None:
            golive_form.live_deadline.data = config.live_deadline
        else:
            golive_form.live_deadline.data = date.today() + timedelta(weeks=6)

        if period is not None and period.feedback_deadline is not None:
            feedback_form.feedback_deadline.data = period.feedback_deadline
        else:
            feedback_form.feedback_deadline.data = date.today() + timedelta(weeks=3)

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)
    capacity_data = get_capacity_data(pclass)

    return render_template('convenor/dashboard/overview.html', pane='overview',
                           golive_form=golive_form, issue_form=issue_form, feedback_form=feedback_form,
                           pclass=pclass, config=config, current_year=current_year,
                           fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, capacity_data=capacity_data)


@convenor.route('/attached/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def attached(id):

    if id == 0:
        return redirect(url_for('convenor.show_unofferable'))

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    # supply list of transferable skill groups and research groups that can be filtered against
    groups = ResearchGroup.query.filter_by(active=True).order_by(ResearchGroup.name.asc()).all()
    skills = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()

    # get filter record
    filter_record = get_convenor_filter_record(config)

    return render_template('convenor/dashboard/attached.html', pane='attached',
                           pclass=pclass, config=config, current_year=current_year,
                           fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, groups=groups, skills=skills,
                           filter_record=filter_record)


@convenor.route('/attached_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def attached_ajax(id):
    """
    Ajax data point for attached projects view
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    # build list of active projects attached to this project class
    pq = db.session.query(Project.id, Project.owner_id) \
        .filter(Project.project_classes.any(id=id)) \
        .join(User, User.id == Project.owner_id) \
        .filter(User.active == True).subquery()

    # build list of enrollments attached to this project class
    eq = db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id).filter_by(pclass_id=id).subquery()

    # pair up projects with the corresponding enrollment records
    jq = db.session.query(pq.c.id.label('pid'), eq.c.id.label('eid')).join(eq, eq.c.owner_id == pq.c.owner_id).subquery()

    # can't find a better way of getting the ORM to construct a tuple of mapped objects here.
    # in principle we want something like
    #
    # projects = db.session.query(Project, EnrollmentRecord). \
    #     join(jq, and_(Project.id == jq.c.pid, EnrollmentRecord.id == jq.c.eid))
    #
    # The ORM implements this as a CROSS JOIN constrained by an INNER JOIN which causes at least MariaDB
    # to fail

    # extract list of Project and Enrollment objects
    pq2 = db.session.query(jq.c.pid, Project).join(Project, Project.id == jq.c.pid)
    eq2 = db.session.query(jq.c.pid, EnrollmentRecord).join(EnrollmentRecord, EnrollmentRecord.id == jq.c.eid)

    ps = [x[1] for x in pq2.all()]
    es = [x[1] for x in eq2.all()]

    # get FilterRecord for currently logged-in user
    filter_record = get_convenor_filter_record(config)

    plist = zip(ps, es)
    projects = filter_projects(plist, filter_record.group_filters.all(),
                               filter_record.skill_filters.all(), getter=lambda x: x[0])

    return ajax.project.build_data(projects, _project_menu, config=config,
                                   name_labels=True, text='attached projects list',
                                   url=url_for('convenor.attached', id=id))


@convenor.route('/faculty/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def faculty(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    enroll_filter = request.args.get('enroll_filter')
    state_filter = request.args.get('state_filter')

    if state_filter == 'no-projects':
        enroll_filter = 'enrolled'

    if enroll_filter is None and session.get('convenor_faculty_enroll_filter'):
        enroll_filter = session['convenor_faculty_enroll_filter']

    if enroll_filter is not None:
        session['convenor_faculty_enroll_filter'] = enroll_filter

    if state_filter is None and session.get('convenor_faculty_state_filter'):
        state_filter = session['convenor_faculty_state_filter']

    if state_filter is not None:
        session['convenor_faculty_state_filter'] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/faculty.html', pane='faculty', subpane='list',
                           pclass=pclass, config=config, current_year=current_year,
                           faculty=faculty, fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count,
                           enroll_filter=enroll_filter, state_filter=state_filter)


@convenor.route('faculty_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def faculty_ajax(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    enroll_filter = request.args.get('enroll_filter')
    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    if enroll_filter == 'enrolled':

        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id).subquery()

        # get User, FacultyData pairs for this list
        faculty = db.session.query(User, FacultyData) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids, User.id == faculty_ids.c.owner_id)

    elif enroll_filter == 'not-enrolled':

        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id).subquery()

        # join to main User and FacultyData records and select pairs that have no counterpart in faculty_ids
        faculty = db.session.query(User, FacultyData) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids, faculty_ids.c.owner_id == User.id, isouter=True) \
            .filter(faculty_ids.c.owner_id == None)

    elif ((enroll_filter == 'supv-active' or enroll_filter == 'supv-sabbatical' or enroll_filter == 'supv-exempt') and pclass.uses_supervisor) \
            or ((enroll_filter == 'mark-active' or enroll_filter == 'mark-sabbatical' or enroll_filter == 'mark-exempt') and pclass.uses_marker) \
            or ((enroll_filter == 'pres-active' or enroll_filter == 'pres-sabbatical' or enroll_filter == 'pres-exempt') and pclass.uses_presentations):

        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id)

        if enroll_filter == 'supv-active':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED)
        elif enroll_filter == 'supv-sabbatical':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_SABBATICAL)
        elif enroll_filter == 'supv-exempt':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_EXEMPT)
        elif enroll_filter == 'mark-active':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED)
        elif enroll_filter == 'mark-sabbatical':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_SABBATICAL)
        elif enroll_filter == 'mark-exempt':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_EXEMPT)
        elif enroll_filter == 'pres-active':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED)
        elif enroll_filter == 'pres-sabbatical':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_SABBATICAL)
        elif enroll_filter == 'pres-exempt':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_EXEMPT)

        faculty_ids_q = faculty_ids.subquery()

        # get User, FacultyData pairs for this list
        faculty = db.session.query(User, FacultyData) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids_q, User.id == faculty_ids_q.c.owner_id)

    else:

        # build list of all active faculty, together with their FacultyData records
        faculty = db.session.query(User, FacultyData).filter(User.active).join(FacultyData, FacultyData.id==User.id)

    # results from the 'faculty' query are (User, FacultyData) pairs, so the FacultyData record is rec[1]
    if state_filter == 'no-projects' and pclass.uses_supervisor:
        data = [ rec for rec in faculty.all() if rec[1].projects_offered(pclass) == 0 ]
    elif state_filter == 'no-marker' and pclass.uses_supervisor:
        data = [ rec for rec in faculty.all() if rec[1].number_assessor == 0 ]
    elif state_filter == 'unofferable':
        data = [ rec for rec in faculty.all() if rec[1].projects_unofferable > 0 ]
    else:
        data = faculty.all()

    return ajax.convenor.faculty_data(data, pclass, config)


@convenor.route('/selectors/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selectors(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    if cohort_filter is None and session.get('convenor_selectors_cohort_filter'):
        cohort_filter = session['convenor_selectors_cohort_filter']

    if cohort_filter is not None:
        session['convenor_selectors_cohort_filter'] = cohort_filter

    if prog_filter is None and session.get('convenor_selectors_prog_filter'):
        prog_filter = session['convenor_selectors_prog_filter']

    if prog_filter is not None:
        session['convenor_selectors_prog_filter'] = prog_filter

    if state_filter is None and session.get('convenor_selectors_state_filter'):
        state_filter = session['convenor_selectors_state_filter']

    if state_filter is not None:
        session['convenor_selectors_state_filter'] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)
        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = db.session.query(DegreeProgramme) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/selectors.html', pane='selectors', subpane='list',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=sorted(cohorts), progs=progs,
                           cohort_filter=cohort_filter, prog_filter=prog_filter, state_filter=state_filter)


@convenor.route('/selectors_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def selectors_ajax(id):
    """
    Ajax data point for selectors view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get('c        ohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)

    if cohort_flag or prog_flag:
        selectors = selectors \
            .join(StudentData, StudentData.id == SelectingStudent.student_id)

    if cohort_flag:
        selectors = selectors.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        selectors = selectors.filter(StudentData.programme_id == prog_value)

    if state_filter == 'submitted':
        data = [ rec for rec in selectors.all() if rec.has_submitted ]
    elif state_filter == 'bookmarks':
        data = [ rec for rec in selectors.all() if not rec.has_submitted and rec.has_bookmarks ]
    elif state_filter == 'none':
        data = [ rec for rec in selectors.all() if not rec.has_submitted and not rec.has_bookmarks ]
    elif state_filter == 'confirmations':
        data = [ rec for rec in selectors.all() if rec.number_pending > 0 ]
    else:
        data = selectors.all()

    return ajax.convenor.selectors_data(data, config)


@convenor.route('/enroll_selectors/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def enroll_selectors(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    if config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash('Manual enrollment of selectors is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')

    if cohort_filter is None and session.get('convenor_sel_enroll_cohort_filter'):
        cohort_filter = session['convenor_sel_enroll_cohort_filter']

    if cohort_filter is not None:
        session['convenor_sel_enroll_cohort_filter'] = cohort_filter

    if prog_filter is None and session.get('convenor_sel_enroll_prog_filter'):
        prog_filter = session['convenor_sel_enroll_prog_filter']

    if prog_filter is not None:
        session['convenor_sel_enroll_prog_filter'] = prog_filter

    candidates = build_enroll_selector_candidates(config)

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for student in candidates:
        cohorts.add(student.cohort)
        programmes.add(student.programme_id)

    # build list of available programmes
    all_progs = db.session.query(DegreeProgramme) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/enroll_selectors.html', pane='selectors', subpane='enroll',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=sorted(cohorts), progs=progs,
                           cohort_filter=cohort_filter, prog_filter=prog_filter)


@convenor.route('/enroll_selectors_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def enroll_selectors_ajax(id):
    """
    Ajax data point for enroll selectors view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    if config.selection_closed:
        return jsonify({})

    candidates = build_enroll_selector_candidates(config)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    return ajax.convenor.enroll_selectors_data(candidates, config)


@convenor.route('/enroll_selector/<int:sid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'root')
def enroll_selector(sid, configid):
    """
    Manually enroll a student as a selector
    :param sid:
    :param configid:
    :return:
    """

    config = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash('Manual enrollment of selectors is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    add_selector(sid, configid, autocommit=True)

    return redirect(request.referrer)


@convenor.route('/delete_selector/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def delete_selector(sid):
    """
    Manually delete a selector
    :param sid:
    :return:
    """

    sel = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    if sel.config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash('Manual deletion of selectors is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    try:
        db.session.delete(sel)      # delete should cascade to Bookmark and SelectionRecord items
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not delete selector due to a database error. Please contact a system administrator.',
              'error')

    return redirect(request.referrer)


@convenor.route('/selector_grid/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_grid(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash('The selector grid view is availably only after student choices are closed', 'error')
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')

    if cohort_filter is None and session.get('convenor_sel_grid_cohort_filter'):
        cohort_filter = session['convenor_sel_grid_cohort_filter']

    if cohort_filter is not None:
        session['convenor_sel_grid_cohort_filter'] = cohort_filter

    if prog_filter is None and session.get('convenor_sel_grid_prog_filter'):
        prog_filter = session['convenor_sel_grid_prog_filter']

    if prog_filter is not None:
        session['convenor_sel_grid_prog_filter'] = prog_filter

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)
        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = db.session.query(DegreeProgramme) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]
    groups = db.session.query(ResearchGroup) \
        .filter_by(active=True) \
        .order_by(ResearchGroup.name.asc()).all()

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/selector_grid.html', pane='selectors', subpane='grid',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=sorted(cohorts), progs=progs,
                           cohort_filter=cohort_filter, prog_filter=prog_filter, groups=groups)


@convenor.route('/selector_grid_ajax/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_grid_ajax(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)

    if cohort_flag or prog_flag:
        selectors = selectors \
            .join(StudentData, StudentData.id == SelectingStudent.student_id)

    if cohort_flag:
        selectors = selectors.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        selectors = selectors.filter(StudentData.programme_id == prog_value)

    return ajax.convenor.selector_grid_data(selectors.all(), config)


@convenor.route('/submitters/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def submitters(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    if cohort_filter is None and session.get('convenor_submitters_cohort_filter'):
        cohort_filter = session['convenor_submitters_cohort_filter']

    if cohort_filter is not None:
        session['convenor_submitters_cohort_filter'] = cohort_filter

    if prog_filter is None and session.get('convenor_submitters_prog_filter'):
        prog_filter = session['convenor_submitters_prog_filter']

    if prog_filter is not None:
        session['convenor_submitters_prog_filter'] = prog_filter

    if state_filter is None and session.get('convenor_submitters_state_filter'):
        state_filter = session['convenor_submitters_state_filter']

    if state_filter is not None:
        session['convenor_submitters_state_filter'] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    submitters = config.submitting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for sub in submitters:
        cohorts.add(sub.student.cohort)
        programmes.add(sub.student.programme_id)

    # build list of available programmes
    all_progs = db.session.query(DegreeProgramme) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/submitters.html', pane='submitters', subpane='list',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=sorted(cohorts), progs=progs,
                           cohort_filter=cohort_filter, prog_filter=prog_filter, state_filter=state_filter)


@convenor.route('/submitters_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def submitters_ajax(id):
    """
    Ajax data point for submitters view
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter)

    return ajax.convenor.submitters_data(data, config)


@convenor.route('/enroll_submitters/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def enroll_submitters(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    if config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash('Manual enrollment of selectors is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')

    if cohort_filter is None and session.get('convenor_sub_enroll_cohort_filter'):
        cohort_filter = session['convenor_sub_enroll_cohort_filter']

    if cohort_filter is not None:
        session['convenor_sub_enroll_cohort_filter'] = cohort_filter

    if prog_filter is None and session.get('convenor_sub_enroll_prog_filter'):
        prog_filter = session['convenor_sub_enroll_prog_filter']

    if prog_filter is not None:
        session['convenor_sub_enroll_prog_filter'] = prog_filter

    candidates = build_enroll_submitter_candidates(config)

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for student in candidates:
        cohorts.add(student.cohort)
        programmes.add(student.programme_id)

    # build list of available programmes
    all_progs = db.session.query(DegreeProgramme) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/enroll_submitters.html', pane='submitters', subpane='enroll',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=sorted(cohorts), progs=progs,
                           cohort_filter=cohort_filter, prog_filter=prog_filter)


@convenor.route('/enroll_submitters_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def enroll_submitters_ajax(id):
    """
    Ajax data point for enroll submitters view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    if config.selection_closed:
        return jsonify({})

    candidates = build_enroll_submitter_candidates(config)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    return ajax.convenor.enroll_submitters_data(candidates, config)


@convenor.route('/enroll_submitter/<int:sid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'root')
def enroll_submitter(sid, configid):
    """
    Manually enroll a student as a submitter
    :param sid:
    :param configid:
    :return:
    """

    config = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash('Manual enrollment of submitters is only possible during normal project activity', 'error')
        return redirect(request.referrer)

    old_config = ProjectClassConfig.query.filter_by(pclass_id=config.pclass_id, year=config.year-1).first()

    add_blank_submitter(sid, old_config.id if old_config is not None else None, configid, autocommit=True)

    return redirect(request.referrer)


@convenor.route('/delete_submitter/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def delete_submitter(sid):
    """
    Manually delete a submitter
    :param sid:
    :return:
    """

    sub = SubmittingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sub.config.project_class):
        return redirect(request.referrer)

    if sub.config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash('Manual deletion of submitters is only possible during normal project activity', 'error')
        return redirect(request.referrer)

    try:
        db.session.delete(sub)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not delete submitter due to a database error. Please contact a system administrator.',
              'error')

    return redirect(request.referrer)


@convenor.route('/liveprojects/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def liveprojects(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    state_filter = request.args.get('state_filter')

    if state_filter is None and session.get('convenor_liveprojects_state_filter'):
        state_filter = session['convenor_liveprojects_state_filter']

    if state_filter is not None:
        session['convenor_liveprojects_state_filter'] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    # supply list of transferable skill groups and research groups that can be filtered against
    groups = ResearchGroup.query.filter_by(active=True).order_by(ResearchGroup.name.asc()).all()
    skills = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()

    # get filter record
    filter_record = get_convenor_filter_record(config)

    return render_template('convenor/dashboard/liveprojects.html', pane='live', subpane='list',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count,
                           groups=groups, skills=skills, filter_record=filter_record,
                           state_filter=state_filter)


@convenor.route('/liveprojects_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def liveprojects_ajax(id):
    """
    Ajax data point for liveprojects fiew
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    # get FilterRecord for currently logged-in user
    filter_record = get_convenor_filter_record(config)

    projects = filter_projects(config.live_projects.all(), filter_record.group_filters.all(),
                               filter_record.skill_filters.all())

    if state_filter == 'submitted':
        data = [ rec for rec in projects if rec.number_confirmed > 0 ]
    elif state_filter == 'bookmarks':
        data = [ rec for rec in projects if rec.number_confirmed == 0 and rec.number_bookmarks > 0 ]
    elif state_filter == 'none':
        data = [ rec for rec in projects if rec.number_confirmed == 0 and rec.number_bookmarks == 0 ]
    elif state_filter == 'confirmations':
        data = [ rec for rec in projects if rec.number_pending > 0 ]
    else:
        data = projects

    return ajax.convenor.liveprojects_data(config, data)


@convenor.route('/attach_liveproject/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_liveproject(id):
    """
    Allow manual attachment of projects
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    # reject if project class is not live
    if not config.live:
        flash('Manual attachment of projects is only possible after going live in this academic year', 'error')
        return redirect(request.referrer)

    if config.selection_closed:
        flash('Manual attachment of projects is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/attach_liveproject.html', pane='live', subpane='attach',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


_attach_liveproject_action = \
"""
<a href="{{ url_for('convenor.manual_attach_project', id=project.id, configid=config.id) }}" class="btn btn-warning btn-sm">
    <i class="fa fa-plus"></i> Manually attach
</a>
"""


@convenor.route('/attach_liveproject_ajax/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_liveproject_ajax(id):
    """
    Ajax datapoint for attach_liveproject view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    if not config.live or config.selection_closed:
        return jsonify({})

    # get existing liveprojects
    current_projects = config.live_projects.subquery()

    # get all projects attached to this class
    attached = pclass.projects.subquery()

    # compute all active attached projects that do not have a LiveProject equivalent
    pq = db.session.query(attached.c.id, attached.c.owner_id) \
        .filter(attached.c.active) \
        .join(current_projects, current_projects.c.parent_id == attached.c.id, isouter=True) \
        .filter(current_projects.c.id == None).subquery()

    eq = db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id).filter_by(pclass_id=id).subquery()
    jq = db.session.query(pq.c.id.label('pid'), eq.c.id.label('eid')).join(eq, eq.c.owner_id == pq.c.owner_id).subquery()

    # match original tables to these primary keys
    pq2 = db.session.query(jq.c.pid, Project).join(Project, Project.id == jq.c.pid)
    eq2 = db.session.query(jq.c.pid, EnrollmentRecord).join(EnrollmentRecord, EnrollmentRecord.id == jq.c.eid)

    ps = [ x[1] for x in pq2.all() ]
    es = [ x[1] for x in eq2.all() ]

    return ajax.project.build_data(zip(ps, es), _attach_liveproject_action, config=config,
                                   name_labels=True, text='attach view',
                                   url=url_for('convenor.attach_liveproject', id=id))


@convenor.route('/manual_attach_project/<int:id>/<int:configid>')
@roles_accepted('faculty', 'admin', 'root')
def manual_attach_project(id, configid):
    """
    Manually attach a project
    :param id:
    :param configid:
    :return:
    """

    config = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not entitled to act as convenor
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    # reject if project class is not live
    if not config.live:
        flash('Manual attachment of projects is only possible after going live in this academic year', 'error')
        return redirect(request.referrer)

    if config.selection_closed:
        flash('Manual attachment of projects is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    # reject if desired project is not attachable
    project = Project.query.get_or_404(id)

    if not config.project_class in project.project_classes:
        flash('Project "{p}" is not attached to "{c}". You do not have sufficient privileges to manually attached it; '
              'please consult with an administrator.'.format(p=project.name, c=config.name), 'error')
        return redirect(request.referrer)

    # get number for this project
    number = config.live_projects.count() + 1

    add_liveproject(number, project, configid, autocommit=True)

    return redirect(request.referrer)


_attach_liveproject_other_action = \
"""
<a href="{{ url_for('convenor.manual_attach_other_project', id=project.id, configid=config.id) }}" class="btn btn-warning btn-sm">
    <i class="fa fa-plus"></i> Manually attach
</a>
"""


@convenor.route('/attach_liveproject_other_ajax/<int:id>')
@roles_accepted('admin', 'root')
def attach_liveproject_other_ajax(id):
    """
    Ajax datapoint for attach_liveproject view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    if not config.live or config.selection_closed:
        return jsonify({})

    # find all projects that do not have a LiveProject equivalent

    # get existing liveprojects
    current_projects = config.live_projects.subquery()

    # this time the SQL is a bit harder
    # we want to find all active projects that do not have a LiveProject equivalent and are *not*
    # attached to this pclass

    # first compute all projects that *are* attached to this pclass
    attached = pclass.projects.subquery()

    # join this sublist back to the main Projects table to determine projects that *are not* attached to this pclass;
    # we keep only the project IDs since we will requery later to build complete Project records including all
    # relationship data
    active_not_attached = db.session.query(Project.id, Project.owner_id) \
        .join(attached, attached.c.id == Project.id, isouter=True) \
        .filter(Project.active, attached.c.id == None).subquery()

    # finally join against list of current projects to find those that do not have a LiveProject equivalent
    pq = db.session.query(active_not_attached) \
        .join(current_projects, current_projects.c.parent_id == active_not_attached.c.id, isouter=True) \
        .filter(current_projects.c.id == None).subquery()

    eq = db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id).filter_by(pclass_id=id).subquery()
    jq = db.session.query(pq.c.id.label('pid'), eq.c.id.label('eid')).join(eq, eq.c.owner_id == pq.c.owner_id).subquery()

    pq2 = db.session.query(jq.c.pid, Project).join(Project, Project.id == jq.c.pid)
    eq2 = db.session.query(jq.c.pid, EnrollmentRecord).join(EnrollmentRecord, EnrollmentRecord.id == jq.c.eid)

    ps = [ x[1] for x in pq2.all() ]
    es = [ x[1] for x in eq2.all() ]

    return ajax.project.build_data(zip(ps, es), _attach_liveproject_other_action, config=config,
                                   name_labels=True, text='attach view',
                                   url=url_for('convenor.attach_liveproject', id=id))


@convenor.route('/manual_attach_other_project/<int:id>/<int:configid>')
@roles_accepted('admin', 'root')
def manual_attach_other_project(id, configid):
    """
    Manually attach a project
    :param id:
    :param configid:
    :return:
    """

    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if project class is not live
    if not config.live:
        flash('Manual attachment of projects is only possible after going live in this academic year', 'error')
        return redirect(request.referrer)

    if config.selection_closed:
        flash('Manual attachment of projects is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    # get number for this project
    project = Project.query.get_or_404(id)
    number = config.live_projects.count() + 1

    add_liveproject(number, project, configid, autocommit=True)

    return redirect(request.referrer)


@convenor.route('/edit_descriptions/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def edit_descriptions(id, pclass_id):

    # get project details
    project = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    create = request.args.get('create', default=None)

    return render_template('convenor/edit_descriptions.html', project=project, pclass_id=pclass_id, create=create)


@convenor.route('/descriptions_ajax/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def descriptions_ajax(id, pclass_id):

    # get project details
    project = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    descs = project.descriptions.all()

    create = request.args.get('create', default=None)

    return ajax.faculty.descriptions_data(descs, _desc_label, _desc_menu, pclass_id=pclass_id, create=create)


@convenor.route('/add_project/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_project(pclass_id):

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    # set up form
    AddProjectForm = AddProjectFormFactory(convenor_editing=True)
    form = AddProjectForm(request.form)

    if form.validate_on_submit():

        data = Project(name=form.name.data,
                       keywords=form.keywords.data,
                       active=True,
                       owner=form.owner.data,
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

        if pclass_id != 0 and len(data.project_classes.all()) == 0 and not pclass.uses_supervisor:
            data.project_classes.append(pclass)

        # ensure that list of preferred degree programmes is consistent
        data.validate_programmes()

        db.session.add(data)
        db.session.commit()

        # auto-enroll if implied by current project class associations
        owner = data.owner
        for pclass in data.project_classes:
            if not owner.is_enrolled(pclass):
                owner.add_enrollment(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.user.name, pclass=pclass.name))

        if form.submit.data:
            return redirect(url_for('convenor.edit_descriptions', id=data.id, pclass_id=pclass_id, create=1))
        elif form.save_and_exit.data:
            return redirect(url_for('convenor.attached', id=pclass_id))
        elif form.save_and_preview:
            return redirect(url_for('faculty.project_preview', id=data.id,
                                    text='attached projects list',
                                    url=url_for('convenor.attached', id=pclass_id)))
        else:
            raise RuntimeError('Unknown submit button in faculty.add_project')

    else:
        if request.method == 'GET':
            # use convenor's defaults
            # This solution is arbitrary, but no less arbitrary than any other choice
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

    return render_template('faculty/edit_project.html', project_form=form, pclass_id=pclass_id, title='Add new project')


@convenor.route('/edit_project/<int:id>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_project(id, pclass_id):

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    # set up form
    data = Project.query.get_or_404(id)

    EditProjectForm = EditProjectFormFactory(convenor_editing=True)
    form = EditProjectForm(obj=data)
    form.project = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.owner = form.owner.data
        data.keywords = form.keywords.data
        data.group = form.group.data
        data.project_classes = form.project_classes.data
        data.meeting_reqd = form.meeting_reqd.data
        data.enforce_capacity = form.enforce_capacity.data
        data.show_popularity = form.show_popularity.data
        data.show_bookmarks = form.show_bookmarks.data
        data.show_selections = form.show_selections.data
        data.dont_clash_presentations = form.dont_clash_presentations.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        if pclass_id != 0 and len(data.project_classes.all()) == 0 and not pclass.uses_supervisor:
            data.project_classes.append(pclass)

        # ensure that list of preferred degree programmes is now consistent
        data.validate_programmes()

        db.session.commit()

        # auto-enroll if implied by current project class associations
        for pclass in data.project_classes:
            if not data.owner.is_enrolled(pclass):
                data.owner.add_enrollment(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.user.name, pclass=pclass.name))

        return redirect(url_for('convenor.attached', id=pclass_id))

    return render_template('faculty/edit_project.html', project_form=form, project=data, pclass_id=pclass_id, title='Edit project details')


@convenor.route('/activate_project/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def activate_project(id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    proj.enable()
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/deactivate_project/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def deactivate_project(id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    proj.disable()
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/add_description/<int:pid>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_description(pid, pclass_id):

    # get project details
    proj = Project.query.get_or_404(pid)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
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

        return redirect(url_for('convenor.edit_descriptions', id=pid, pclass_id=pclass_id, create=create))

    return render_template('faculty/edit_description.html', project=proj, form=form, pclass_id=pclass_id,
                           title='Add new description', create=create)


@convenor.route('/edit_description/<int:did>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
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

        db.session.commit()

        return redirect(url_for('convenor.edit_descriptions', id=desc.parent_id, pclass_id=pclass_id, create=create))

    return render_template('faculty/edit_description.html', project=desc.parent, desc=desc, form=form,
                           pclass_id=pclass_id, title='Edit description', create=create)


@convenor.route('/description_modules/<int:did>/<int:pclass_id>/<int:level_id>', methods=['GET', 'POST'])
@convenor.route('/description_modules/<int:did>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def description_modules(did, pclass_id, level_id=None):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
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

    return render_template('convenor/description_modules.html', project=desc.parent, desc=desc, form=form,
                           pclass_id=pclass_id, title='Attach pre-requisite modules', levels=levels, create=create,
                           modules=modules, level_id=level_id)


@convenor.route('/description_attach_module/<int:did>/<int:pclass_id>/<int:mod_id>/<int:level_id>')
@roles_accepted('faculty', 'admin', 'root')
def description_attach_module(did, pclass_id, mod_id, level_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    create = request.args.get('create', default=None)
    module = Module.query.get_or_404(mod_id)

    if desc.module_available(module.id):
        if not module in desc.modules:
            desc.modules.append(module)
            db.session.commit()

    return redirect(url_for('convenor.description_modules', did=did, pclass_id=pclass_id, level_id=level_id, create=create))


@convenor.route('/description_detach_module/<int:did>/<int:pclass_id>/<int:mod_id>/<int:level_id>')
@roles_accepted('faculty', 'admin', 'root')
def description_detach_module(did, pclass_id, mod_id, level_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    create = request.args.get('create', default=None)
    module = Module.query.get_or_404(mod_id)

    if desc.module_available(module.id):
        if module in desc.modules:
            desc.modules.remove(module)
            db.session.commit()

    return redirect(url_for('convenor.description_modules', did=did, pclass_id=pclass_id, level_id=level_id, create=create))


@convenor.route('/delete_description/<int:did>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def delete_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    db.session.delete(desc)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/duplicate_description/<int:did>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def duplicate_description(did, pclass_id):

    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
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


@convenor.route('/make_default_description/<int:pid>/<int:pclass_id>/<int:did>')
@convenor.route('/make_default_description/<int:pid>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def make_default_description(pid, pclass_id, did=None):

    proj = Project.query.get_or_404(pid)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
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


@convenor.route('/attach_skills/<int:id>/<int:pclass_id>/<int:sel_id>')
@convenor.route('/attach_skills/<int:id>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def attach_skills(id, pclass_id, sel_id=None):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
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

    create = request.args.get('create', default=None)

    return render_template('convenor/attach_skills.html', data=proj, skills=skills, pclass_id=pclass_id,
                           form=form, sel_id=form.selector.data.id, create=create)


@convenor.route('/add_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def add_skill(projectid, skillid, pclass_id, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(proj):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in proj.skills:
        proj.add_skill(skill)
        db.session.commit()

    return redirect(url_for('convenor.attach_skills', id=projectid, pclass_id=pclass_id, sel_id=sel_id, create=create))


@convenor.route('/remove_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def remove_skill(projectid, skillid, pclass_id, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(proj):
        return redirect(request.referrer)

    create = request.args.get('create', default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in proj.skills:
        proj.remove_skill(skill)
        db.session.commit()

    return redirect(url_for('convenor.attach_skills', id=projectid, pclass_id=pclass_id, sel_id=sel_id, create=create))


@convenor.route('/attach_programmes/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_programmes(id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    q = proj.available_degree_programmes

    create = request.args.get('create', default=None)

    return render_template('convenor/attach_programmes.html', data=proj, programmes=q.all(), pclass_id=pclass_id,
                           create=create)


@convenor.route('/add_programme/<int:id>/<int:pclass_id>/<int:prog_id>')
@roles_accepted('faculty', 'admin', 'root')
def add_programme(id, pclass_id, prog_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme not in proj.programmes:
        proj.add_programme(programme)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/remove_programme/<int:id>/<int:pclass_id>/<int:prog_id>')
@roles_accepted('faculty', 'admin', 'root')
def remove_programme(id, pclass_id, prog_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme in proj.programmes:
        proj.remove_programme(programme)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/attach_assessors/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_assessors(id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    create = request.args.get('create', default=None)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    # if no state filter supplied, check if one is stored in session
    if state_filter is None and session.get('convenor_marker_state_filter'):
        state_filter = session['convenor_marker_state_filter']

    # write state filter into session if it is not empty
    if state_filter is not None:
        session['convenor_marker_state_filter'] = state_filter

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('convenor_marker_pclass_filter'):
        pclass_filter = session['convenor_marker_pclass_filter']

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session['convenor_marker_pclass_filter'] = pclass_filter

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get('convenor_marker_group_filter'):
        group_filter = session['convenor_marker_group_filter']

    # write group filter into session if it is not empty
    if group_filter is not None:
        session['convenor_marker_group_filter'] = group_filter

    # get list of available research groups
    groups = ResearchGroup.query.filter_by(active=True).all()

    # get list of project classes to which this project is attached, and which require assignment of
    # second markers
    pclasses = proj.project_classes.filter(and_(ProjectClass.active == True,
                                                or_(ProjectClass.uses_marker == True,
                                                    ProjectClass.uses_presentations == True))).all()

    return render_template('convenor/attach_assessors.html', data=proj, pclass_id=pclass_id, groups=groups, pclasses=pclasses,
                           state_filter=state_filter, pclass_filter=pclass_filter, group_filter=group_filter,
                           create=create)


@convenor.route('/attach_assessors_ajax/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_assessors_ajax(id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return jsonify({})

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return jsonify({})

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    faculty = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    return ajax.project.build_marker_data(faculty, proj, _marker_menu, pclass_id)


@convenor.route('/add_assessor/<int:proj_id>/<int:pclass_id>/<int:mid>')
@roles_accepted('faculty', 'admin', 'root')
def add_assessor(proj_id, pclass_id, mid):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    assessor = FacultyData.query.get_or_404(mid)

    proj.add_assessor(assessor)

    return redirect(request.referrer)


@convenor.route('/remove_assessor/<int:proj_id>/<int:pclass_id>/<int:mid>')
@roles_accepted('faculty', 'admin', 'root')
def remove_assessor(proj_id, pclass_id, mid):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    assessor = FacultyData.query.get_or_404(mid)

    proj.remove_assessor(assessor)

    return redirect(request.referrer)


@convenor.route('/attach_all_assessors/<int:proj_id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_all_assessors(proj_id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    assessoes = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessoes:
        proj.add_assessor(assessor)

    return redirect(request.referrer)


@convenor.route('/remove_all_assessors/<int:proj_id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def remove_all_assessors(proj_id, pclass_id):

    # get project details
    proj = Project.query.get_or_404(proj_id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(request.referrer)

    state_filter = request.args.get('state_filter')
    pclass_filter = request.args.get('pclass_filter')
    group_filter = request.args.get('group_filter')

    assessors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessors:
        proj.remove_assessor(assessor)

    return redirect(request.referrer)


@convenor.route('/issue_confirm_requests/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def issue_confirm_requests(id):

    # get details for project class
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

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

        deadline = issue_form.request_deadline.data
        if deadline < date.today():
            deadline = date.today() + timedelta(weeks=2)
        config.request_deadline = deadline

        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/outstanding_confirm/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def outstanding_confirm(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/dashboard/outstanding_confirm.html', config=config, pclass=config.project_class)


@convenor.route('/outstanding_confirm_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def outstanding_confirm_ajax(id):
    """
    Ajax data point for waiting-to-go-live faculty list on dashboard
    :param id:
    :return:
    """

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    return ajax.convenor.outstanding_confirm_data(config)


@convenor.route('/show_unofferable')
@roles_accepted('faculty', 'admin', 'root')
def show_unofferable():

    # special-case of unattached projects; reject user if not administrator
    if not validate_is_administrator():
        return redirect(request.referrer)

    return render_template('convenor/unofferable.html')


@convenor.route('/unofferable_ajax')
@roles_accepted('faculty', 'admin', 'root')
def unofferable_ajax():
    """
    Ajax data point for show-unattached view
    :return:
    """

    if not validate_is_administrator():
        return jsonify({})

    projects = [(p, None) for p in db.session.query(Project).filter_by(active=True).all() if not p.is_offerable]

    return ajax.project.build_data(projects, _unattached_project_menu,
                                   name_labels=True, text='attached projects list',
                                   url=url_for('convenor.show_unofferable'))


@convenor.route('/force_confirm_all/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def force_confirm_all(id):

    # get details for project class
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    config.golive_required = []
    db.session.commit()

    flash('All outstanding confirmation requests have been removed.', 'success')

    return redirect(request.referrer)


@convenor.route('/force_confirm/<int:id>/<int:uid>')
@roles_accepted('faculty', 'admin', 'root')
def force_confirm(id, uid):

    # get details for project class
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    faculty = FacultyData.query.get_or_404(uid)

    if faculty in config.golive_required:
        config.golive_required.remove(faculty)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/go_live/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def go_live(id):

    # get details for current pclass configuration
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    year = get_current_year()
    form = GoLiveForm(request.form)

    if form.is_submitted():

        # get golive task instance
        celery = current_app.extensions['celery']
        golive = celery.tasks['app.tasks.go_live.pclass_golive']
        golive_fail = celery.tasks['app.tasks.go_live.golive_fail']
        golive_close = celery.tasks['app.tasks.go_live.golive_close']

        # register Go Live as a new background task and push it to the celery scheduler
        task_id = register_task('Go Live for "{proj}" {yra}-{yrb}'.format(proj=config.name,
                                                                          yra=year, yrb=year+1),
                                owner=current_user,
                                description='Perform Go Live of "{proj}"'.format(proj=config.name))

        if form.live.data:
            golive.apply_async(args=(task_id, id, current_user.id, form.live_deadline.data, False),
                               task_id=task_id,
                               link_error=golive_fail.si(task_id, current_user.id))

        elif form.live_and_close.data:
            seq = chain(golive.si(task_id, id, current_user.id, form.live_deadline.data, True),
                        golive_close.si(id, current_user.id)).on_error(golive_fail.si(task_id, current_user.id))
            seq.apply_async()

        else:
            raise RuntimeError('Unknown GoLive submission button')

    return redirect(request.referrer)


@convenor.route('/close_selections/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def close_selections(id):

    # get details for current pclass configuration
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    year = get_current_year()

    celery = current_app.extensions['celery']
    close = celery.tasks['app.tasks.close_selection.pclass_close']
    close_fail = celery.tasks['app.tasks.close_selection.close_fail']

    # register as new background task and push to celery scheduler
    task_id = register_task('Close selections for "{proj}" {yra}-{yrb}'.format(proj=config.name,
                                                                               yra=year, yrb=year+1),
                            owner=current_user,
                            description='Close selections for "{proj}"'.format(proj=config.name))

    close.apply_async(args=(task_id, config.id, current_user.id),
                      task_id=task_id,
                      link_error=close_fail.si(task_id, current_user.id))

    return redirect(request.referrer)


@convenor.route('/enroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def enroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.add_enrollment(pclass)

    return redirect(request.referrer)


@convenor.route('/unenroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def unenroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.remove_enrollment(pclass)

    return redirect(request.referrer)


@convenor.route('/confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    if do_confirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/deconfirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def deconfirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    if do_deconfirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/deconfirm_to_pending/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def deconfirm_to_pending(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    if do_deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/cancel_confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def cancel_confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    if do_cancel_confirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_confirm_all/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def project_confirm_all(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(request.referrer)

    for sel in project.confirm_waiting:
        if sel not in project.confirmed_students:
            project.confirmed_students.append(sel)
            sel.student.user.post_message('Your confirmation request for the project "{name}" has been '
                                          'approved.'.format(name=project.name), 'success')

    project.confirm_waiting = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_clear_requests/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def project_clear_requests(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(request.referrer)

    project.confirm_waiting = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_remove_confirms/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def project_remove_confirms(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(request.referrer)

    for sel in project.confirmed_students:
        sel.student.user.post_message('Your confirmation approval for the project "{name}" has been removed. '
                                      'If you were not expecting this event, please make an appointment to discuss '
                                      'with the supervisor.'.format(name=project.name), 'info')
    project.confirmed_students = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_make_all_confirms_pending/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def project_make_all_confirms_pending(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(request.referrer)

    for sel in project.confirmed_students:
        if sel not in project.confirm_waiting:
            project.confirm_waiting.append(sel)
            sel.student.user.post_message('Your confirmation approval for the project "{name}" has been reverted to "pending". '
                                          'If you were not expecting this event, please make an appointment to discuss '
                                          'with the supervisor.'.format(name=project.name), 'info')
    project.confirmed_students = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_confirm_all/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def student_confirm_all(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    for project in sel.confirm_requests:
        if project not in sel.confirmed:
            sel.confirmed.append(project)
            sel.student.user.post_message('Your confirmation request for the project "{name}" has been '
                                          'approved.'.format(name=project.name), 'success')
    sel.confirm_requests = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_remove_confirms/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def student_remove_confirms(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    for project in sel.confirmed:
        sel.student.user.post_message('Your confirmation approval for the project "{name}" has been removed. '
                                      'If you were not expecting this event, please make an appointment to discuss '
                                      'with the supervisor.'.format(name=project.name), 'info')
    sel.confirmed = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_clear_requests/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def student_clear_requests(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    sel.confirm_requests = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_make_all_confirms_pending/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def student_make_all_confirms_pending(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    for project in sel.confirmed:
        if project not in sel.confirm_requests:
            sel.confirm_requests.append(project)
            sel.student.user.post_message('Your confirmation approval for the project "{name}" has been reverted to "pending". '
                                          'If you were not expecting this event, please make an appointment to discuss '
                                          'with the supervisor.'.format(name=project.name), 'info')
    sel.confirmed = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_clear_bookmarks/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def student_clear_bookmarks(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(request.referrer)

    for item in sel.bookmarks:
        db.session.delete(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/confirm_rollover/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def confirm_rollover(id):

    # pid is a ProjectClass
    config = ProjectClassConfig.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    year = get_current_year()

    title = 'Rollover of "{proj}" to {yeara}&ndash;{yearb}'.format(proj=config.name, yeara=year, yearb=year + 1)
    action_url = url_for('convenor.rollover', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to rollover project class "{proj}" to ' \
              '{yeara}&ndash;{yearb}</p>' \
              '<p>This action cannot be undone.</p>'.format(proj=config.name, yeara=year, yearb=year + 1)
    submit_label = 'Rollover to {yr}'.format(yr=year)

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@convenor.route('/rollover/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def rollover(id):

    # pid is a ProjectClass
    config = ProjectClassConfig.query.get_or_404(id)

    url = request.args.get('url', None)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(url) if url is not None else home_dashboard()

    year = get_current_year()
    if config.year == year:
        flash('A rollover request was ignored. If you are attempting to rollover the academic year and '
              'have not managed to do so, please contact a system administrator', 'error')
        return redirect(url) if url is not None else home_dashboard()

    if not config.project_class.active:
        flash('{name} is not an active project class'.format(name=config.name), 'error')
        return redirect(url) if url is not None else home_dashboard()

    # get rollover task instance
    celery = current_app.extensions['celery']
    rollover = celery.tasks['app.tasks.rollover.pclass_rollover']
    rollover_fail = celery.tasks['app.tasks.rollover.rollover_fail']

    # register rollover as a new background task and push it to the celery scheduler
    task_id = register_task('Rollover "{proj}" to {yra}-{yrb}'.format(proj=config.name, yra=year, yrb=year+1),
                            owner=current_user,
                            description='Perform rollover of "{proj}" to new academic year'.format(proj=config.name))
    rollover.apply_async(args=(task_id, id, current_user.id), task_id=task_id,
                         link_error=rollover_fail.si(task_id, current_user.id))

    return redirect(url) if url is not None else home_dashboard()


@convenor.route('/reset_popularity_data/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def reset_popularity_data(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    title = 'Delete popularity data'
    panel_title = 'Delete selection popularity data for <strong>{name} {yra}&ndash;{yrb}</strong>'\
        .format(name=config.name, yra=config.year+1, yrb=config.year+2)

    action_url = url_for('convenor.perform_reset_popularity_data', id=id)
    message = '<p>Please confirm that you wish to delete all popularity data for ' \
              '<strong>{name} {yra}&ndash;{yrb}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
              '<p>Afterwards, it will not be possible to analyse ' \
              'historical popularity trends for individual projects offered in this cycle.</p>' \
        .format(name=config.name, yra=config.year+1, yrb=config.year+2)
    submit_label = 'Delete data'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@convenor.route('/perform_reset_popularity_data/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def perform_reset_popularity_data(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    db.session.query(PopularityRecord).filter_by(config_id=id).delete()
    db.session.commit()

    return redirect(url_for('convenor.liveprojects', id=config.pclass_id))


@convenor.route('/selector_bookmarks/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_bookmarks(id):

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/student_bookmarks.html', sel=sel)


@convenor.route('/project_bookmarks/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_bookmarks(id):

    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/project_bookmarks.html', project=proj)


@convenor.route('/selector_choices/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_choices(id):

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/student_choices.html', sel=sel)


@convenor.route('/project_choices/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_choices(id):

    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/project_choices.html', project=proj)


@convenor.route('/selector_confirmations/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_confirmations(id):

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/student_confirmations.html', sel=sel)


@convenor.route('/project_confirmations/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_confirmations(id):

    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return home_dashboard()

    return render_template('convenor/selector/project_confirmations.html', project=proj)


@convenor.route('/add_group_filter/<int:id>/<int:gid>')
@roles_accepted('faculty', 'admin', 'root')
def add_group_filter(id, gid):

    group = ResearchGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(request.referrer)

    if group not in record.group_filters:
        record.group_filters.append(group)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/remove_group_filter/<int:id>/<int:gid>')
@roles_accepted('faculty', 'admin', 'root')
def remove_group_filter(id, gid):

    group = ResearchGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(request.referrer)

    if group in record.group_filters:
        record.group_filters.remove(group)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/clear_group_filters/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def clear_group_filters(id):

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(request.referrer)

    record.group_filters = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/add_skill_filter/<int:id>/<int:gid>')
@roles_accepted('faculty', 'admin', 'root')
def add_skill_filter(id, gid):
    skill = SkillGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(request.referrer)

    if skill not in record.skill_filters:
        record.skill_filters.append(skill)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/remove_skill_filter/<int:id>/<int:gid>')
@roles_accepted('faculty', 'admin', 'root')
def remove_skill_filter(id, gid):
    skill = SkillGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(request.referrer)

    if skill in record.skill_filters:
        record.skill_filters.remove(skill)
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/clear_skill_filters/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def clear_skill_filters(id):
    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(request.referrer)

    record.skill_filters = []
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/set_hint/<int:id>/<int:hint>')
@roles_accepted('faculty', 'admin', 'root')
def set_hint(id, hint):
    rec = SelectionRecord.query.get_or_404(id)
    config = rec.owner.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash('Selection hints may only be set once student choices are closed and the project class '
              'is ready to match', 'error')
        return redirect(request.referrer)

    rec.set_hint(hint)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/hints_list/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def hints_list(id):
    # pid is a ProjectClass
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash('Selection hints may only be set once student choices are closed and the project class '
              'is ready to match', 'error')
        return redirect(request.referrer)

    hints = db.session.query(SelectionRecord) \
        .join(SelectingStudent, SelectingStudent.id == SelectionRecord.owner_id) \
        .filter(SelectingStudent.config_id == config.id) \
        .filter(SelectionRecord.hint != SelectionRecord.SELECTION_HINT_NEUTRAL).all()

    return render_template('convenor/dashboard/hints_list.html', pclass=pclass, hints=hints)


@convenor.route('/audit_matches/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def audit_matches(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    return render_template('convenor/matching/audit.html', pclass_id=pclass_id)


@convenor.route('/audit_matches_ajax/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def audit_matches_ajax(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=pclass_id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    matches = config.published_matches.all()

    return ajax.admin.matches_data(matches, text='matching audit dashboard',
                                   url=url_for('convenor.audit_matches', pclass_id=pclass_id))


@convenor.route('/audit_schedules/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def audit_schedules(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    return render_template('convenor/presentations/audit.html', pclass_id=pclass_id)


@convenor.route('/audit_schedules_ajax/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def audit_schedules_ajax(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=pclass_id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    matches = config.published_schedules.all()

    return ajax.admin.assessment_schedules_data(matches, text='schedule audit dashboard',
                                                url=url_for('convenor.audit_schedules', pclass_id=pclass_id))


@convenor.route('/open_feedback/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def open_feedback(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY and \
            state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash('Feedback cannot be opened at this stage in the project lifecycle.', 'info')
        return redirect(request.referrer)

    feedback_form = OpenFeedbackForm(request.form)

    if feedback_form.is_submitted() and feedback_form.open_feedback.data is True:
        # set feedback deadline and mark feedback open

        period = config.periods.filter_by(submission_period=config.submission_period).first()

        period.feedback_open = True
        period.feedback_deadline = feedback_form.feedback_deadline.data

        if period.feedback_id is None:
            period.feedback_id = current_user.id

        if period.feedback_timestamp is None:
            period.feedback_timestamp = datetime.now()

        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/close_feedback/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def close_feedback(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash('Feedback cannot be closed at this stage in the project lifecycle.', 'info')
        return redirect(request.referrer)

    if config.submission_period > config.submissions:
        flash('Feedback close request ignored because "{name}" is already in a rollover state.'.format(name=config.name),
              'info')
        return request.referrer

    period = config.periods.filter_by(submission_period=config.submission_period).first()

    period.closed = True
    period.closed_id = current_user.id
    period.closed_timestamp = datetime.now()

    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/publish_assignment/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def publish_assignment(id):

    # id is a SubmittingStudent
    sub = SubmittingStudent.query.get_or_404(id)

    # reject is logged-in user is not a convenor for this SubmittingStudent
    if not validate_is_convenor(sub.config.project_class):
        return redirect(request.referrer)

    if sub.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to publish an assignment to students', 'error')
        return redirect(request.referrer)

    sub.published = True
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/unpublish_assignment/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def unpublish_assignment(id):

    # id is a SubmittingStudent
    sub = SubmittingStudent.query.get_or_404(id)

    # reject is logged-in user is not a convenor for this SubmittingStudent
    if not validate_is_convenor(sub.config.project_class):
        return redirect(request.referrer)

    if sub.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to publish an assignment to students', 'error')
        return redirect(request.referrer)

    sub.published = False
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/publish_all_assignments/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def publish_all_assignments(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject is logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to publish an assignment to students', 'error')
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter)

    for sel in data:
        sel.published = True

    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/unpublish_all_assignments/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def unpublish_all_assignments(id):

    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject is logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to unpublish an assignment', 'error')
        return redirect(request.referrer)

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter)

    for sel in data:
        sel.published = False

    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/mark_started/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def mark_started(id):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject is logged-in user is not a convenor for the project class associated with this submission record
    if not validate_is_convenor(rec.owner.config.project_class):
        return redirect(request.referrer)

    if rec.owner.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to mark a submission period as started', 'error')
        return redirect(request.referrer)

    if rec.submission_period > rec.owner.config.submission_period:
        flash('Cannot mark this submission period as started because it is not yet open', 'error')
        return redirect(request.referrer)

    if not rec.owner.published:
        flash('Cannot mark this submission period as started because it is not published to the submitter', 'error')

    rec.student_engaged = True
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/view_feedback/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def view_feedback(id):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject is logged-in user is not a convenor for the project class associated with this submission record
    if not validate_is_convenor(rec.owner.config.project_class):
        return redirect(request.referrer)

    text = request.args.get('text', None)
    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    return render_template('faculty/dashboard/view_feedback.html', record=rec, text=text, url=url)


@convenor.route('/faculty_workload/<int:id>')
@roles_accepted('faculty', 'admin', 'route')
def faculty_workload(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    enroll_filter = request.args.get('enroll_filter')
    state_filter = request.args.get('state_filter')

    if state_filter == 'no-projects':
        enroll_filter = 'enrolled'

    if enroll_filter is None and session.get('convenor_faculty_enroll_filter'):
        enroll_filter = session['convenor_faculty_enroll_filter']

    if enroll_filter is not None:
        session['convenor_faculty_enroll_filter'] = enroll_filter

    if state_filter is None and session.get('convenor_faculty_state_filter'):
        state_filter = session['convenor_faculty_state_filter']

    if state_filter is not None:
        session['convenor_faculty_state_filter'] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return redirect(request.referrer)

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/workload.html', pane='faculty', subpane='workload',
                           pclass=pclass, config=config, current_year=current_year,
                           faculty=faculty, fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count,
                           enroll_filter=enroll_filter, state_filter=state_filter)


@convenor.route('faculty_workload_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def faculty_workload_ajax(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    enroll_filter = request.args.get('enroll_filter')
    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()
    if config is None:
        flash('Internal error: could not locate ProjectClassConfig. Please contact a system administrator.', 'error')
        return jsonify({})

    if enroll_filter == 'enrolled':

        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id).subquery()

        # get User, FacultyData pairs for this list
        faculty = db.session.query(User, FacultyData) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids, User.id == faculty_ids.c.owner_id)

    elif enroll_filter == 'not-enrolled':

        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id).subquery()

        # join to main User and FacultyData records and select pairs that have no counterpart in faculty_ids
        faculty = db.session.query(User, FacultyData) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids, faculty_ids.c.owner_id == User.id, isouter=True) \
            .filter(faculty_ids.c.owner_id == None)

    elif ((enroll_filter == 'supv-active' or enroll_filter == 'supv-sabbatical' or enroll_filter == 'supv-exempt') and pclass.uses_supervisor) \
            or ((enroll_filter == 'mark-active' or enroll_filter == 'mark-sabbatical' or enroll_filter == 'mark-exempt') and pclass.uses_marker) \
            or ((enroll_filter == 'pres-active' or enroll_filter == 'pres-sabbatical' or enroll_filter == 'pres-exempt') and pclass.uses_presentations):

        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id)

        if enroll_filter == 'supv-active':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED)
        elif enroll_filter == 'supv-sabbatical':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_SABBATICAL)
        elif enroll_filter == 'supv-exempt':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_EXEMPT)
        elif enroll_filter == 'mark-active':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED)
        elif enroll_filter == 'mark-sabbatical':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_SABBATICAL)
        elif enroll_filter == 'mark-exempt':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_EXEMPT)
        elif enroll_filter == 'pres-active':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED)
        elif enroll_filter == 'pres-sabbatical':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_SABBATICAL)
        elif enroll_filter == 'pres-exempt':
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_EXEMPT)

        faculty_ids_q = faculty_ids.subquery()

        # get User, FacultyData pairs for this list
        faculty = db.session.query(User, FacultyData) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids_q, User.id == faculty_ids_q.c.owner_id)

    else:

        # build list of all active faculty, together with their FacultyData records
        faculty = db.session.query(User, FacultyData).filter(User.active).join(FacultyData, FacultyData.id==User.id)

    # results from the 'faculty' query are (User, FacultyData) pairs, so the FacultyData record is rec[1]
    if state_filter == 'no-late-feedback':
        data = [rec for rec in faculty.all() if not rec[1].has_late_feedback(pclass.id, rec[1].id)]
    elif state_filter == 'late-feedback':
        data = [rec for rec in faculty.all() if rec[1].has_late_feedback(pclass.id, rec[1].id)]
    elif state_filter == 'not-started':
        data = [rec for rec in faculty.all() if rec[1].has_not_started_flags(pclass.id, rec[1].id)]
    else:
        data = faculty.all()

    return ajax.convenor.faculty_workload_data(data, config)


@convenor.route('/manual_assign/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def manual_assign(id):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # find the old ProjectClassConfig from which we will draw the list of available LiveProjects
    config = rec.previous_config
    if config is None:
        flash('Can not reassign because the list of available Live Projects could not be found', 'error')
        return redirect(request.referrer)

    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if rec.period.feedback_open:
        flash('Can not reassign for {name} '
              'because feedback is already open'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    if rec.student_engaged:
        flash('Can not reassign for {name} '
              'because the project is already marked as started'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    AssignMarkerForm = AssignMarkerFormFactory(rec.project, rec.pclass_id)
    form = AssignMarkerForm(request.form)

    if form.validate_on_submit():
        rec.marker = form.marker.data
        db.session.commit()

    else:
        if request.method == 'GET':
            form.marker.data = rec.marker

    text = request.args.get('text', None)
    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    return render_template('convenor/dashboard/manual_assign.html', rec=rec, config=config, url=url, text=text,
                           form=form)


@convenor.route('/manual_assign_ajax/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def manual_assign_ajax(id):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # find the old ProjectClassConfig from which we will draw the list of available LiveProjects
    config = rec.previous_config
    if config is None:
        flash('Can not reassign because the list of available Live Projects could not be found', 'error')
        return jsonify({})

    if not validate_is_convenor(config.project_class):
        return jsonify({})

    if rec.period.feedback_open:
        flash('Can not reassign for {name} '
              'because feedback is already open'.format(name=rec.period.display_name), 'error')
        return jsonify({})

    data = config.live_projects.all()

    return ajax.convenor.manual_assign_data(data, rec)


@convenor.route('/assign_revert/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def assign_revert(id):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # find the old ProjectClassConfig from which we will draw the list of available LiveProjects
    config = rec.previous_config
    if config is None:
        flash('Can not revert assignment because the list of available Live Projects could not be found', 'error')
        return redirect(request.referrer)

    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if rec.period.feedback_open:
        flash('Can not revert assignment for {name} '
              'because feedback is already open'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    if rec.matching_record is None:
        flash('Can not revert assignment for {name} '
              'because automatic data could not be found'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    rec.project_id = rec.matching_record.project_id
    rec.marker_id = rec.matching_record.marker_id

    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/assign_from_selection/<int:id>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def assign_from_selection(id, sel_id):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # find the old ProjectClassConfig from which we will draw the list of available LiveProjects
    config = rec.previous_config
    if config is None:
        flash('Can not reassign because the list of available Live Projects could not be found', 'error')
        return redirect(request.referrer)

    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if rec.period.feedback_open:
        flash('Can not reassign for {name} '
              'because feedback is already open'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    if rec.matching_record is None:
        flash('Can not revert assignment for {name} '
              'because automatic data could not be found'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    sel = SelectionRecord.query.get_or_404(sel_id)

    rec.project_id = sel.liveproject_id

    markers = sel.liveproject.assessor_list
    if rec.marker not in markers:
        sorted_markers = sorted(markers, key=lambda x: (x.CATS_assignment(config.project_class))[1])
        rec.marker_id = sorted_markers[0].id if len(sorted_markers) > 0 else None

    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/assign_liveproject/<int:id>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def assign_liveproject(id, pid):

    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # find the old ProjectClassConfig from which we will draw the list of available LiveProjects
    config = rec.previous_config
    if config is None:
        flash('Can not reassign because the list of available Live Projects could not be found', 'error')
        return redirect(request.referrer)

    if not validate_is_convenor(config.project_class):
        return redirect(request.referrer)

    if rec.period.feedback_open:
        flash('Can not reassign for {name} '
              'because feedback is already open'.format(name=rec.period.display_name), 'error')
        return redirect(request.referrer)

    lp = LiveProject.query.get_or_404(pid)

    if lp.config_id != config.id:
        flash('Can not assign LiveProject #{num} for {name} because '
              'their configuration data do not agree'.format(num=lp.number, name=rec.period.display_name),
              'error')
        return redirect(request.referrer)

    rec.project_id = lp.id

    markers = lp.assessor_list
    if rec.marker not in markers:
        sorted_markers = sorted(markers, key=lambda x: (x.CATS_assignment(config.project_class))[1])
        rec.marker_id = sorted_markers[0].id if len(sorted_markers) > 0 else None

    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/assign_presentation_feedback/<int:id>/', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def assign_presentation_feedback(id):
    # id labels a SubmissionRecord
    talk = SubmissionRecord.query.get_or_404(id)

    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(request.referrer)

    if not validate_not_attending(talk):
        return redirect(request.referrer)

    AssignPresentationFeedbackForm = AssignPresentationFeedbackFormFactory(talk.id)
    form = AssignPresentationFeedbackForm(request.form)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        feedback = PresentationFeedback(owner_id=talk.id,
                                        assessor=form.assessor.data,
                                        positive=form.positive.data,
                                        negative=form.negative.data,
                                        submitted=True,
                                        timestamp=datetime.now())

        db.session.add(feedback)
        db.session.commit()

        return redirect(url)

    return render_template('faculty/dashboard/edit_feedback.html', form=form,
                           title='Assign presentation feedback',
                           formtitle='Assign presentation feedback for <strong>{num}</strong>'.format(num=talk.owner.student.user.name),
                           submit_url=url_for('convenor.assign_presentation_feedback', id=talk.id, url=url))


@convenor.route('/edit_presentation_feedback/<int:id>/', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_presentation_feedback(id):
    # id labels PresentationFeedback record
    feedback = PresentationFeedback.query.get_or_404(id)

    talk = feedback.owner
    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(request.referrer)

    if not validate_not_attending(talk):
        return redirect(request.referrer)

    form = PresentationFeedbackForm(obj=feedback)

    url = request.args.get('url', None)
    if url is None:
        url = request.referrer

    if form.validate_on_submit():
        feedback.positive = form.positive.data
        feedback.negative = form.negative.data
        feedback.timestamp = datetime.now()

        db.session.commit()

        return redirect(url)

    return render_template('faculty/dashboard/edit_feedback.html', form=form,
                           title='Assign presentation feedback',
                           formtitle='Assign presentation feedback for <strong>{num}</strong>'.format(num=talk.owner.student.user.name),
                           submit_url=url_for('convenor.edit_presentation_feedback', id=feedback.id, url=url))


@convenor.route('/delete_presentation_feedback/<int:id>/', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def delete_presentation_feedback(id):
    # id labels PresentationFeedback record
    feedback = PresentationFeedback.query.get_or_404(id)

    talk = feedback.owner
    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(request.referrer)

    if not validate_not_attending(talk):
        return redirect(request.referrer)

    db.session.delete(feedback)
    db.session.commit()

    return redirect(request.referrer)
