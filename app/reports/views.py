#
# Created by David Seery on 2018-11-01.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, redirect, url_for, flash, request, session
from flask_security import login_required, roles_required, roles_accepted, current_user

from ..database import db
from ..models import User, FacultyData, ResearchGroup, SkillGroup, ProjectClass, Project, WorkflowMixin

from ..shared.conversions import is_integer
from ..shared.sqlalchemy import get_count

import app.ajax as ajax

from . import reports


@reports.route('/workload')
@roles_required('reports')
def workload():
    """
    Basic workload report
    :return:
    """
    group_filter = request.args.get('group_filter')
    detail = request.args.get('detail')

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get('reports_workload_group_filter'):
        group_filter = session['reports_workload_group_filter']

    # write group filter into session if it is not empty
    if group_filter is not None:
        session['reports_workload_group_filter'] = group_filter

    # if no detail level supplied, check if one is stored in session
    if detail is None and session.get('reports_workload_detail'):
        detail = session['reports_workload_detail']

    # write detail level into session if it is not empty
    if detail is not None:
        session['reports_workload_detail'] = detail

    groups = db.session.query(ResearchGroup).filter_by(active=True).all()

    return render_template('reports/workload.html', groups=groups, group_filter=group_filter, detail=detail)


@reports.route('/workload_ajax')
@roles_required('reports')
def workload_ajax():
    """
    AJAX data point for workload report
    :return:
    """
    group_filter = request.args.get('group_filter')
    detail = request.args.get('detail')

    fac_query = db.session.query(FacultyData.id) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active)

    flag, group_value = is_integer(group_filter)
    if flag:
        fac_query = fac_query.filter(FacultyData.affiliations.any(id=group_value))

    faculty_ids = [f[0] for f in fac_query.all()]

    return ajax.reports.workload_data(faculty_ids, detail == 'simple')


@reports.route('/all_projects')
@roles_required('reports')
def all_projects():
    pclass_filter = request.args.get('pclass_filter')

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('reports_projects_pclass_filter'):
        pclass_filter = session['reports_projects_pclass_filter']

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session['reports_projects_pclass_filter'] = pclass_filter

    valid_filter = request.args.get('valid_filter')

    if valid_filter is None and session.get('reports_projects_valid_filter'):
        valid_filter = session['reports_projects_valid_filter']

    if valid_filter is not None:
        session['reports_projects_valid_filter'] = valid_filter

    state_filter = request.args.get('state_filter')

    if state_filter is None and session.get('reports_projects_state_filter'):
        state_filter = session['reports_projects_state_filter']

    if state_filter is not None:
        session['reports_projects_state_filter'] = state_filter

    active_filter = request.args.get('active_filter')

    if active_filter is None and session.get('reports_projects_active_filter'):
        active_filter = session['reports_projects_active_filter']

    if active_filter is not None:
        session['reports_projects_active_filter'] = active_filter

    groups = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()
    pclasses = ProjectClass.query.order_by(ProjectClass.name.asc()).all()

    return render_template('reports/all_projects.html', groups=groups, pclasses=pclasses, pclass_filter=pclass_filter,
                           valid_filter=valid_filter, state_filter=state_filter, active_filter=active_filter)


@reports.route('/all_projects_ajax', methods=['GET', 'POST'])
@roles_required('reports')
def all_projects_ajax():
    """
    Ajax data point for All Projects report
    :return:
    """
    pclass_filter = request.args.get('pclass_filter')
    valid_filter = request.args.get('valid_filter')
    state_filter = request.args.get('state_filter')
    active_filter = request.args.get('active_filter')

    flag, pclass_value = is_integer(pclass_filter)

    pq = db.session.query(Project) \
        .join(FacultyData, FacultyData.id == Project.owner_id) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active == True)
    if flag:
        pq = pq.filter(Project.project_classes.any(id=pclass_value))

    if state_filter == 'active':
        pq = pq.filter(Project.project_classes.any(active=True))
    elif state_filter == 'inactive':
        pq = pq.filter(~Project.project_classes.any(active=True))
    elif state_filter == 'published':
        pq = pq.filter(Project.project_classes.any(active=True, publish=True))
    elif state_filter == 'unpublished':
        pq = pq.filter(~Project.project_classes.any(active=True, publish=True))

    if active_filter == 'active':
        pq = pq.filter(Project.active == True)
    elif active_filter == 'inactive':
        pq = pq.filter(Project.active == False)

    data = pq.all()

    if valid_filter == 'valid':
        data = [(x.id, None) for x in data if x.approval_state == Project.DESCRIPTIONS_APPROVED]
    elif valid_filter == 'not-valid':
        data = [(x.id, None) for x in data if x.approval_state == Project.SOME_DESCRIPTIONS_QUEUED]
    elif valid_filter == 'reject':
        data = [(x.id, None) for x in data if x.approval_state == Project.SOME_DESCRIPTIONS_REJECTED]
    elif valid_filter == 'pending':
        data = [(x.id, None) for x in data if x.approval_state == Project.SOME_DESCRIPTIONS_UNCONFIRMED]
    else:
        data = [(x.id, None) for x in data]

    return ajax.project.build_data(data, current_user.id)