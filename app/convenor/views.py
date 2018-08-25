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

from app.shared.utils import build_enroll_selector_candidates
from ..models import db, User, FacultyData, StudentData, TransferableSkill, ProjectClass, ProjectClassConfig, \
    LiveProject, SelectingStudent, Project, EnrollmentRecord, ResearchGroup, SkillGroup, \
    PopularityRecord, FilterRecord, DegreeProgramme

from ..shared.utils import get_current_year, home_dashboard, get_convenor_dashboard_data, get_capacity_data, \
    filter_projects, get_convenor_filter_record, filter_second_markers
from ..shared.validators import validate_is_convenor, validate_is_administrator, validate_edit_project, validate_project_open
from ..shared.actions import do_confirm, do_cancel_confirm, do_deconfirm, do_deconfirm_to_pending
from ..shared.convenor import add_selector, add_liveproject
from ..shared.conversions import is_integer

from ..task_queue import register_task

import app.ajax as ajax

from . import convenor

from ..faculty.forms import AddProjectForm, EditProjectForm, GoLiveForm, IssueFacultyConfirmRequestForm, \
    SkillSelectorForm

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
            <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
                Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Editing</li>

        <li>
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-pencil"></i> Edit project
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_markers', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-pencil"></i> 2nd markers
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-pencil"></i> Transferable skills
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=config.pclass_id) }}">
                <i class="fa fa-pencil"></i> Degree programmes
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=config.pclass_id) }}">
                Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=config.pclass_id) }}">
                Make active
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
            <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
                Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Editing</li>

        <li>
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Edit project
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_markers', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> 2nd markers
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Transferable skills
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Degree programmes
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=0) }}">
                Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=0) }}">
                Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


_marker_menu = \
"""
{% if proj.is_second_marker(f) %}
    <a href="{{ url_for('convenor.remove_marker', proj_id=proj.id, pclass_id=pclass_id, mid=f.id) }}"
       class="btn btn-sm btn-default">
        <i class="fa fa-trash"></i> Remove
    </a>
{% elif proj.can_enroll_marker(f) %}
    <a href="{{ url_for('convenor.add_marker', proj_id=proj.id, pclass_id=pclass_id, mid=f.id) }}"
       class="btn btn-sm btn-default">
        <i class="fa fa-plus"></i> Attach
    </a>
{% else %}
    <a class="btn btn-default btn-sm disabled">
        <i class="fa fa-plus"></i> Can't attach
    </a>
{% endif %}
"""


@convenor.route('/overview/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def overview(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build forms
    golive_form = GoLiveForm(request.form)
    issue_form = IssueFacultyConfirmRequestForm(request.form)

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

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)
    capacity_data = get_capacity_data(pclass)

    return render_template('convenor/dashboard/overview.html', pane='overview',
                           golive_form=golive_form, issue_form=issue_form,
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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build list of projects attached to this project class
    pq = db.session.query(Project.id, Project.owner_id).filter(Project.project_classes.any(id=id)).subquery()

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
                               filter_record.skill_filters.all(), lambda x: x[0])

    return ajax.project.build_data(projects, _project_menu, config=config)


@convenor.route('/faculty/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def faculty(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
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

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/faculty.html', pane='faculty',
                           pclass=pclass, config=config, current_year=current_year,
                           faculty=faculty, fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count,
                           enroll_filter=enroll_filter, state_filter=state_filter)


@convenor.route('faculty_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def faculty_ajax(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    enroll_filter = request.args.get('enroll_filter')
    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    if enroll_filter == 'enrolled':

        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id).subquery()

        # get User, FacultyData pairs for this list
        faculty = db.session.query(User, FacultyData) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids, User.id == faculty_ids.c.owner_id)

    elif enroll_filter == 'not-enrolled':

        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id) \
            .filter(EnrollmentRecord.pclass_id == id).subquery()

        # join to main User and FacultyData records and select pairs that have no counterpart in faculty_ids
        faculty = db.session.query(User, FacultyData) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids, faculty_ids.c.owner_id == User.id, isouter=True) \
            .filter(faculty_ids.c.owner_id == None)

    elif enroll_filter == 'supv-active' or enroll_filter == 'supv-sabbatical' or enroll_filter == 'supv-exempt' \
            or enroll_filter == 'mark-active' or enroll_filter == 'mark-sabbatical' or enroll_filter == 'mark-exempt':

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

        faculty_ids_q = faculty_ids.subquery()

        # get User, FacultyData pairs for this list
        faculty = db.session.query(User, FacultyData) \
            .join(FacultyData, FacultyData.id == User.id) \
            .join(faculty_ids_q, User.id == faculty_ids_q.c.owner_id)

    else:

        # build list of all active faculty, together with their FacultyData records
        faculty = db.session.query(User, FacultyData).filter(User.active).join(FacultyData, FacultyData.id==User.id)

    # results from the 'faculty' query are (User, FacultyData) pairs, so the FacultyData record is rec[1]
    if state_filter == 'no-projects':
        data = [ rec for rec in faculty.all() if rec[1].projects_offered(pclass) == 0 ]
    elif state_filter == 'no-marker':
        data = [ rec for rec in faculty.all() if rec[1].number_marker == 0 ]
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

    # reject user if not entitled to view this dashboard
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

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)
        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = DegreeProgramme.query.filter_by(active=True).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/selectors.html', pane='selectors', subpane='list',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=cohorts, progs=progs,
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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')
    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
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

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    if config.selection_closed:
        flash('Manual enrollment of selectors is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    candidates = build_enroll_selector_candidates(config)

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    for student in candidates:
        cohorts.add(student.cohort)
        programmes.add(student.programme_id)

    # build list of available programmes
    all_progs = DegreeProgramme.query.filter_by(active=True).all()
    progs = [ rec for rec in all_progs if rec.id in programmes ]

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/enroll_selectors.html', pane='selectors', subpane='enroll',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count, cohorts=cohorts, progs=progs,
                           cohort_filter=cohort_filter, prog_filter=prog_filter)


@convenor.route('/enroll_selectors_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def enroll_selectors_ajax(id):
    """
    Ajax data point for selectors view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get('cohort_filter')
    prog_filter = request.args.get('prog_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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

    if config.selection_closed:
        flash('Manual enrollment of selectors is only possible before student choices are closed', 'error')
        return redirect(request.referrer)

    add_selector(sid, configid, autocommit=True)

    return redirect(request.referrer)


@convenor.route('/submitters/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def submitters(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    fac_data, live_count, proj_count, sel_count, sub_count = get_convenor_dashboard_data(pclass, config)

    return render_template('convenor/dashboard/submitters.html', pane='submitters',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('/submitters_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def submitters_ajax(id):
    """
    Ajax data point for submitters view
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build a list of live students submitting work for evaluation in this project class
    submitters = config.submitting_students.filter_by(retired=False)

    return ajax.convenor.submitters_data(submitters, config)


@convenor.route('/liveprojects/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def liveprojects(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    state_filter = request.args.get('state_filter')

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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

    return ajax.project.build_data(zip(ps, es), _attach_liveproject_action, config=config)


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
              'please consult with an administrator.'.format(p=project.name, c=config.project_class.name), 'error')
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

    return ajax.project.build_data(zip(ps, es), _attach_liveproject_other_action, config=config)


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

        # ensure that list of preferred degree programmes is consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        owner = data.owner
        for pclass in data.project_classes:

            if not owner.is_enrolled(pclass):

                owner.add_enrollment(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.user.name, pclass=pclass.name))

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('convenor.attached', id=pclass_id))

    else:

        if request.method == 'GET':

            # can't use any individual user's preferences to set defaults, so pick a standard set
            form.show_popularity.data = True
            form.show_bookmarks.data = True
            form.show_selections.data = True

            form.capacity.data = current_app.config['DEFAULT_PROJECT_CAPACITY']
            form.enforce_capacity.data = True

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

    form = EditProjectForm(obj=data, convenor_editing=True)
    form.project = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.owner = form.owner.data
        data.keywords = form.keywords.data
        data.group = form.group.data
        data.project_classes = form.project_classes.data
        data.meeting_reqd = form.meeting_reqd.data
        data.capacity = form.capacity.data
        data.enforce_capacity = form.enforce_capacity.data
        data.team = form.team.data
        data.show_popularity = form.show_popularity.data
        data.show_bookmarks = form.show_bookmarks.data
        data.show_selections = form.show_selections.data
        data.description = form.description.data
        data.reading = form.reading.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        # ensure that list of preferred degree programmes is now consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        for pclass in data.project_classes:

            if not data.owner.is_enrolled(pclass):
                data.owner.add_enrollment(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.user.name, pclass=pclass.name))

        db.session.commit()

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

    return render_template('convenor/attach_skills.html', data=proj, skills=skills, pclass_id=pclass_id,
                           form=form, sel_id=form.selector.data.id)


@convenor.route('/add_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def add_skill(projectid, skillid, pclass_id, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(proj):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in proj.skills:
        proj.add_skill(skill)
        db.session.commit()

    return redirect(url_for('convenor.attach_skills', id=projectid, pclass_id=pclass_id, sel_id=sel_id))


@convenor.route('/remove_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>')
@roles_accepted('faculty', 'admin', 'root')
def remove_skill(projectid, skillid, pclass_id, sel_id):

    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(proj):
        return redirect(request.referrer)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in proj.skills:
        proj.remove_skill(skill)
        db.session.commit()

    return redirect(url_for('convenor.attach_skills', id=projectid, pclass_id=pclass_id, sel_id=sel_id))


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

    return render_template('convenor/attach_programmes.html', data=proj, programmes=q.all(), pclass_id=pclass_id)


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


@convenor.route('/attach_markers/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_markers(id, pclass_id):

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
    pclasses = proj.project_classes.filter_by(active=True, uses_marker=True).all()

    return render_template('convenor/attach_markers.html', data=proj, pclass_id=pclass_id, groups=groups, pclasses=pclasses,
                           state_filter=state_filter, pclass_filter=pclass_filter, group_filter=group_filter)


@convenor.route('/attach_markers_ajax/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_markers_ajax(id, pclass_id):

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

    faculty = filter_second_markers(proj, state_filter, pclass_filter, group_filter)

    return ajax.project.build_marker_data(faculty, proj, _marker_menu, pclass_id)


@convenor.route('/add_marker/<int:proj_id>/<int:pclass_id>/<int:mid>')
@roles_accepted('faculty', 'admin', 'root')
def add_marker(proj_id, pclass_id, mid):

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

    marker = FacultyData.query.get_or_404(mid)

    proj.add_marker(marker)

    return redirect(request.referrer)


@convenor.route('/remove_marker/<int:proj_id>/<int:pclass_id>/<int:mid>')
@roles_accepted('faculty', 'admin', 'root')
def remove_marker(proj_id, pclass_id, mid):

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

    marker = FacultyData.query.get_or_404(mid)

    proj.remove_marker(marker)

    return redirect(request.referrer)


@convenor.route('/attach_all_markers/<int:proj_id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_all_markers(proj_id, pclass_id):

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

    markers = filter_second_markers(proj, state_filter, pclass_filter, group_filter)

    for marker in markers:
        proj.add_marker(marker)

    return redirect(request.referrer)


@convenor.route('/remove_all_markers/<int:proj_id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def remove_all_markers(proj_id, pclass_id):

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

    markers = filter_second_markers(proj, state_filter, pclass_filter, group_filter)

    for marker in markers:
        proj.remove_marker(marker)

    return redirect(request.referrer)


@convenor.route('/issue_confirm_requests/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def issue_confirm_requests(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

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
        config.request_deadline = issue_form.request_deadline.data

        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/golive_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def golive_ajax(id):
    """
    Ajax data point for waiting-to-go-live faculty list on dashboard
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    return ajax.convenor.golive_data(config)


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

    projects = [(p, None) for p in db.session.query(Project).filter_by(active=True).all() if not p.offerable]

    return ajax.project.build_data(projects, _unattached_project_menu)



@convenor.route('/force_confirm_all/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def force_confirm_all(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    for item in config.golive_required.all():

        config.golive_required.remove(item)

    db.session.commit()

    flash('All outstanding confirmation requests have been removed.', 'success')

    return redirect(request.referrer)


@convenor.route('/go_live/<pid>/<int:configid>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def go_live(pid, configid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pid)

    # reject user if not entitled to perform dashboard functions
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).first()

    if config.id != configid or config.year != year:
        flash('A "Go Live" request was ignored. If you are attempting to go live with this project class, '
              'please contact a system administrator.', 'error')
        return redirect(url_for('convenor.overview', id=pid))

    form = GoLiveForm(request.form)

    if form.is_submitted():

        # get golive task instance
        celery = current_app.extensions['celery']
        golive = celery.tasks['app.tasks.go_live.pclass_golive']
        golive_fail = celery.tasks['app.tasks.go_live.golive_fail']

        # register Go Live as a new background task and push it to the celery scheduler
        task_id = register_task('Go Live for "{proj}" {yra}-{yrb}'.format(proj=pclass.name, yra=year, yrb=year+1),
                                owner=current_user,
                                description='Perform Go Live of "{proj}"'.format(proj=pclass.name))
        golive.apply_async(args=(task_id, pid, configid, current_user.id, form.live_deadline.data), task_id=task_id,
                           link_error=golive_fail.si(task_id, current_user.id))

    return redirect(request.referrer)


@convenor.route('/close_selections/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def close_selections(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    config.selection_closed = True
    config.closed_id = current_user.id
    config.closed_timestamp = datetime.now()

    db.session.commit()

    flash('Student selections for {name} {yeara}-{yearb} have now been closed'.format(name=pclass.name, yeara=config.year, yearb=config.year+1), 'success')

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
    data.add_enrollment(pclass, autocommit=True)

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
    data.remove_enrollment(pclass, autocommit=True)

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

    for item in project.confirm_waiting:
        if item not in project.confirmed_students:
            project.confirmed_students.append(item)
        project.confirm_waiting.remove(item)
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

    for item in project.confirm_waiting:
        project.confirm_waiting.remove(item)
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

    for item in project.confirmed_students:
        project.confirmed_students.remove(item)
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

    for item in project.confirmed_students:
        if item not in project.confirm_waiting:
            project.confirm_waiting.append(item)
        project.confirmed_students.remove(item)
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

    for item in sel.confirm_requests:
        if item not in sel.confirmed:
            sel.confirmed.append(item)
        sel.confirm_requests.remove(item)
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

    for item in sel.confirmed:
        sel.confirmed.remove(item)
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

    for item in sel.confirm_requests:
        sel.confirm_requests.remove(item)
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

    for item in sel.confirmed:
        if item not in sel.confirm_requests:
            sel.confirm_requests.append(item)
        sel.confirmed.remove(item)
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


@convenor.route('/confirm_rollover/<int:pid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'root')
def confirm_rollover(pid, configid):

    year = get_current_year()

    # do nothing if a rollover has already been performed (try to make action idempotent in case
    # accidentally invoked twice)
    config = ProjectClassConfig.query.filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).first()

    title = 'Rollover of "{proj}" to {yeara}&ndash;{yearb}'.format(proj=config.project_class.name,
                                                                   yeara=year, yearb=year + 1)
    action_url = url_for('convenor.rollover', pid=pid, configid=configid)
    message = 'Please confirm that you wish to rollover project class "{proj}" to ' \
              '{yeara}&ndash;{yearb}'.format(proj=config.project_class.name,
                                             yeara=year, yearb=year + 1)
    submit_label = 'Rollover to {yr}'.format(yr=year)

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@convenor.route('/rollover/<int:pid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'root')
def rollover(pid, configid):

    # pid is a ProjectClass
    pclass = ProjectClass.query.get_or_404(pid)

    if not pclass.active:
        flash('{name} is not an active project class'.format(name=pclass.name), 'error')
        return home_dashboard()

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(pclass):
        return home_dashboard()

    year = get_current_year()

    # do nothing if a rollover has already been performed (try to make action idempotent in case
    # accidentally invoked twice)
    config = ProjectClassConfig.query.filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).first()

    if config.id != configid or config.year == year:
        flash('A rollover request was ignored. If you are attempting to rollover the academic year and '
              'have not managed to do so, please contact a system administrator', 'error')
        return redirect(url_for('convenor.overview', id=pid))

    # get rollover task instance
    celery = current_app.extensions['celery']
    rollover = celery.tasks['app.tasks.rollover.pclass_rollover']
    rollover_fail = celery.tasks['app.tasks.rollover.rollover_fail']

    # register rollover as a new background task and push it to the celery scheduler
    task_id = register_task('Rollover "{proj}" to {yra}-{yrb}'.format(proj=pclass.name, yra=year, yrb=year+1),
                            owner=current_user,
                            description='Perform rollover of "{proj}" to new academic year'.format(proj=pclass.name))
    rollover.apply_async(args=(task_id, pid, configid, current_user.id), task_id=task_id,
                         link_error=rollover_fail.si(task_id, current_user.id))

    return redirect(url_for('convenor.overview', id=pid))


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
        .format(name=config.project_class.name, yra=config.year+1, yrb=config.year+2)

    action_url = url_for('convenor.perform_reset_popularity_data', id=id)
    message = '<p>Please confirm that you wish to delete all popularity data for ' \
              '<strong>{name} {yra}&ndash;{yrb}</strong>. ' \
              'This action cannot be undone.</p>' \
              '<p>Afterwards, it will not be possible to analyse ' \
              'historical popularity trends for individual projects offered in this cycle.</p>' \
        .format(name=config.project_class.name, yra=config.year+1, yrb=config.year+2)
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

    return redirect(url_for('convenor.liveprojects', id=config.project_class.id))


@convenor.route('/selector_bookmarks/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_bookmarks(id):

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/student_bookmarks.html', sel=sel)


@convenor.route('/project_bookmarks/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_bookmarks(id):

    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(proj.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/project_bookmarks.html', project=proj)


@convenor.route('/selector_choices/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_choices(id):

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/student_choices.html', sel=sel)


@convenor.route('/project_choices/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_choices(id):

    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(proj.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/project_choices.html', project=proj)


@convenor.route('/selector_confirmations/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selector_confirmations(id):

    # id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_is_convenor(sel.config.project_class):
        return redirect(request.referrer)

    return render_template('convenor/selector/student_confirmations.html', sel=sel)


@convenor.route('/project_confirmations/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def project_confirmations(id):

    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
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
