#
# Created by David Seery on 08/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Set

from flask import request, session
from flask_security import roles_accepted, current_user
from sqlalchemy.sql import func

import app.ajax as ajax
from . import archive
from ..database import db
from ..models import (
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    DegreeProgramme,
    SubmittingStudent,
    User,
    Tenant, SubmissionRecord,
    ResearchGroup,
    LiveProject,
)
from ..shared.context.global_context import render_template_context
from ..shared.conversions import is_integer
from ..tools import ServerSideSQLHandler


@archive.route('/reports')
@roles_accepted('root', 'admin', 'archive_reports')
def reports():
    allowed_tenant_ids: List[int] = [t.id for t in current_user.tenants]

    # --- pclass filter ---
    pclass_filter = request.args.get('pclass_filter')

    if pclass_filter is None and session.get('archive_reports_pclass_filter'):
        pclass_filter = session['archive_reports_pclass_filter']

    if pclass_filter is not None and pclass_filter != 'all':
        flag, value = is_integer(pclass_filter)
        if flag:
            pclass: ProjectClass = db.session.query(ProjectClass).filter_by(id=value).first()
            if pclass is None:
                pclass_filter = 'all'
            elif not current_user.has_role('root') and pclass.tenant_id not in allowed_tenant_ids:
                pclass_filter = 'all'
        else:
            pclass_filter = 'all'

    if pclass_filter is not None:
        session['archive_reports_pclass_filter'] = pclass_filter

    # --- year filter ---
    year_filter = request.args.get('year_filter')

    if year_filter is None and session.get('archive_reports_year_filter'):
        year_filter = session['archive_reports_year_filter']

    if year_filter is not None and year_filter != 'all':
        flag, _ = is_integer(year_filter)
        if not flag:
            year_filter = 'all'

    if year_filter is not None:
        session['archive_reports_year_filter'] = year_filter

    # --- group filter ---
    group_filter = request.args.get('group_filter')

    if group_filter is None and session.get('archive_reports_group_filter'):
        group_filter = session['archive_reports_group_filter']

    if group_filter is not None and group_filter != 'all':
        flag, value = is_integer(group_filter)
        if flag:
            group: ResearchGroup = db.session.query(ResearchGroup).filter_by(id=value).first()
            if group is None:
                group_filter = 'all'
            elif not current_user.has_role('root'):
                # check that this group belongs to at least one of the user's tenants
                group_tenant_ids = {t.id for t in group.tenants}
                if not group_tenant_ids.intersection(allowed_tenant_ids):
                    group_filter = 'all'
        else:
            group_filter = 'all'

    if group_filter is not None:
        session['archive_reports_group_filter'] = group_filter

    # --- build list of available project classes (tenant-scoped) ---
    if current_user.has_role('root'):
        pclasses: List[ProjectClass] = (
            db.session.query(ProjectClass)
            .filter(
                ProjectClass.active == True,
                ProjectClass.publish == True,
                ProjectClass.uses_submission == True
            )
            .order_by(ProjectClass.name.asc())
            .all()
        )
    else:
        pclasses: List[ProjectClass] = (
            db.session.query(ProjectClass)
            .filter(
                ProjectClass.active == True,
                ProjectClass.publish == True,
                ProjectClass.uses_submission == True,
                ProjectClass.tenant_id.in_(allowed_tenant_ids),
            )
            .order_by(ProjectClass.name.asc())
            .all()
        )

    # --- build list of available years ---
    if current_user.has_role('root'):
        year_data = (
            db.session.query(ProjectClassConfig.year)
            .join(SubmittingStudent, SubmittingStudent.config_id == ProjectClassConfig.id)
            .filter(SubmittingStudent.retired == True)
            .distinct()
            .order_by(ProjectClassConfig.year.desc())
            .all()
        )
    else:
        year_data = (
            db.session.query(ProjectClassConfig.year)
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
            .join(SubmittingStudent, SubmittingStudent.config_id == ProjectClassConfig.id)
            .filter(
                SubmittingStudent.retired == True,
                ProjectClass.tenant_id.in_(allowed_tenant_ids),
            )
            .distinct()
            .order_by(ProjectClassConfig.year.desc())
            .all()
        )

    years: List[int] = [row[0] for row in year_data]

    # --- build list of available research groups (tenant-scoped) ---
    if current_user.has_role('root'):
        groups: List[ResearchGroup] = (
            db.session.query(ResearchGroup)
            .filter(ResearchGroup.active == True)
            .order_by(ResearchGroup.name.asc())
            .all()
        )
    else:
        # collect all research groups associated with the user's tenants
        group_ids: Set[int] = set()
        for tenant in current_user.tenants:
            for g in tenant.research_groups:
                group_ids.add(g.id)

        groups: List[ResearchGroup] = (
            db.session.query(ResearchGroup)
            .filter(
                ResearchGroup.active == True,
                ResearchGroup.id.in_(group_ids),
            )
            .order_by(ResearchGroup.name.asc())
            .all()
        )

    return render_template_context(
        'archive/reports.html',
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        years=years,
        year_filter=year_filter,
        groups=groups,
        group_filter=group_filter,
    )


@archive.route('/reports_ajax', methods=['POST'])
@roles_accepted('root', 'admin', 'archive_reports')
def reports_ajax():
    allowed_tenant_ids: List[int] = [t.id for t in current_user.tenants]

    pclass_filter = request.args.get('pclass_filter')
    year_filter = request.args.get('year_filter')
    group_filter = request.args.get('group_filter')

    # Validate pclass filter
    if pclass_filter is not None and pclass_filter != 'all':
        flag, value = is_integer(pclass_filter)
        if flag:
            pclass: ProjectClass = db.session.query(ProjectClass).filter_by(id=value).first()
            if pclass is None:
                pclass_filter = 'all'
            elif not current_user.has_role('root') and pclass.tenant_id not in allowed_tenant_ids:
                pclass_filter = 'all'
        else:
            pclass_filter = 'all'

    # Validate year filter
    if year_filter is not None and year_filter != 'all':
        flag, _ = is_integer(year_filter)
        if not flag:
            year_filter = 'all'

    # Validate group filter
    if group_filter is not None and group_filter != 'all':
        flag, value = is_integer(group_filter)
        if flag:
            group: ResearchGroup = db.session.query(ResearchGroup).filter_by(id=value).first()
            if group is None:
                group_filter = 'all'
            elif not current_user.has_role('root'):
                group_tenant_ids = {t.id for t in group.tenants}
                if not group_tenant_ids.intersection(allowed_tenant_ids):
                    group_filter = 'all'
        else:
            group_filter = 'all'

    # Build base query
    base_query = (
        db.session.query(SubmittingStudent)
        .join(ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id)
        .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
        .join(StudentData, StudentData.id == SubmittingStudent.student_id)
        .join(User, User.id == StudentData.id)
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id, isouter=True)
        .filter(
            ProjectClass.uses_submission == True,
            ProjectClass.active == True,
            ProjectClass.publish == True,
            SubmittingStudent.retired == True,
        )
    )

    # Apply tenant restriction for non-root users
    if not current_user.has_role('root'):
        base_query = base_query.filter(ProjectClass.tenant_id.in_(allowed_tenant_ids))

    # Apply pclass filter
    if pclass_filter is not None and pclass_filter != 'all':
        flag, value = is_integer(pclass_filter)
        if flag:
            base_query = base_query.filter(ProjectClass.id == value)

    # Apply year filter
    if year_filter is not None and year_filter != 'all':
        flag, value = is_integer(year_filter)
        if flag:
            base_query = base_query.filter(ProjectClassConfig.year == value)

    # Apply group filter: join through SubmissionRecord and LiveProject to ResearchGroup
    if group_filter is not None and group_filter != 'all':
        flag, value = is_integer(group_filter)
        if flag:
            base_query = (
                base_query
                .join(SubmissionRecord, SubmissionRecord.owner_id == SubmittingStudent.id)
                .join(LiveProject, LiveProject.id == SubmissionRecord.project_id)
                .filter(LiveProject.group_id == value)
                .distinct()
            )

    # Define columns for ServerSideSQLHandler
    name_col = {
        'search': func.concat(User.first_name, ' ', User.last_name),
        'order': [User.last_name, User.first_name],
        'search_collation': 'utf8_general_ci',
    }
    year_col = {
        'search': ProjectClassConfig.year,
        'order': ProjectClassConfig.year,
    }

    columns = {
        'name': name_col,
        'year': year_col,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.archive.retired_reports)
