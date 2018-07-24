#
# Created by David Seery on 24/07/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..models import db, User, FacultyData, Project, EnrollmentRecord, ResearchGroup, SelectingStudent, \
    SubmittingStudent, LiveProject

from sqlalchemy import func


def dashboard_data(pclass, config):
    """
    Efficiently retrieve statistics needed to render the convenor dashboard
    :param pclass:
    :param config:
    :return:
    """

    fac_query = db.session.query(func.count(User.id)). \
        filter(User.active).join(FacultyData, FacultyData.id == User.id)

    fac_total = fac_query.scalar()
    fac_count = fac_query.filter(FacultyData.enrollments.any(pclass_id=pclass.id)).scalar()

    proj_count = db.session.query(func.count(Project.id)) \
        .filter(Project.project_classes.any(id=pclass.id)).scalar()

    sel_count = db.session.query(func.count(SelectingStudent.id)) \
        .filter(~SelectingStudent.retired, SelectingStudent.config_id == config.id).scalar()

    sub_count = db.session.query(func.count(SubmittingStudent.id)) \
        .filter(~SelectingStudent.retired, SelectingStudent.config_id == config.id).scalar()

    live_count = db.session.query(func.count(LiveProject.id)) \
        .filter(LiveProject.config_id == config.id).scalar()

    return (fac_count, fac_total), live_count, proj_count, sel_count, sub_count


def _compute_group_capacity_data(pclass, group):

    # filter all 'attached' projects that are tagged with this research group
    projects = db.session.query(Project) \
        .filter(Project.active == True, Project.project_classes.any(id=pclass.id),
                Project.group_id == group.id)

    # set of faculty members offering projects
    faculty = set()

    # number of offerable projects
    project_count = 0

    # total capacity of projects
    # the flag 'capacity_bounded' is used to track whether any projects have quota enforcement turned off,
    # and therefore the computed capacity is a lower bound
    capacity = 0
    capacity_bounded = True

    for project in projects:

        if project.offerable:

            project_count += 1

            # add owner to list of faculty offering projects
            if project.owner.id not in faculty:
                faculty.add(project.owner.id)

            if project.capacity is not None:
                capacity += project.capacity
            if not project.enforce_capacity:
                capacity_bounded = False

    # get number of enrolled faculty belonging to this research group
    enrolled = db.session.query(func.count(EnrollmentRecord.id)) \
        .filter(EnrollmentRecord.pclass_id == pclass.id) \
        .join(FacultyData, FacultyData.id == EnrollmentRecord.owner_id) \
        .join(User, User.id == EnrollmentRecord.owner_id) \
        .filter(FacultyData.affiliations.any(id=group.id),
                User.active == True).scalar()

    # get total number of faculty belonging to this research group
    total = db.session.query(func.count(FacultyData.id)) \
        .join(User, User.id == FacultyData.id) \
        .filter(FacultyData.affiliations.any(id=group.id),
                User.active == True).scalar()

    return project_count, len(faculty), enrolled, total, capacity, capacity_bounded


def compute_capacity_data(pclass):

    # get list of research groups
    groups = db.session.query(ResearchGroup) \
        .filter_by(active=True)\
        .order_by(ResearchGroup.name) \
        .all()

    data = []
    total_projects = 0
    total_faculty = 0
    total_capacity = 0
    total_capacity_bounded = True

    for group in groups:

        proj_count, fac_count, enrolled, total, capacity, capacity_bounded = \
            _compute_group_capacity_data(pclass, group)

        # update totals
        total_projects += proj_count
        total_faculty += fac_count
        total_capacity += capacity
        total_capacity_bounded = total_capacity_bounded and capacity_bounded

        # store data for this research group
        data.append( (group.make_label(group.name), proj_count, fac_count, enrolled, total, capacity, capacity_bounded) )

    return data, total_projects, total_faculty, total_capacity, total_capacity_bounded
