#
# Created by David Seery on 28/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import redirect, url_for, flash
from flask_security import current_user

from app import db
from app.models import db, MainConfig, ProjectClass, ProjectClassConfig, User, FacultyData, Project, \
    EnrollmentRecord, ResearchGroup, SelectingStudent, SubmittingStudent, LiveProject, FilterRecord, StudentData, \
    MatchingAttempt, MatchingRecord

from .conversions import is_integer

from sqlalchemy import func


def get_main_config():

    return db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()


def get_current_year():

    return get_main_config().year


def home_dashboard():

    if current_user.has_role('faculty'):

        return redirect(url_for('faculty.dashboard'))

    elif current_user.has_role('student'):

        return redirect(url_for('student.dashboard'))

    elif current_user.has_role('office'):

        return redirect(url_for('office.dashboard'))

    else:

        flash('Your role could not be identified. Please contact the system administrator.')
        return redirect(url_for('auth.logged_out'))


def get_root_dashboard_data():

    current_year = get_current_year()

    pcs = db.session.query(ProjectClass).filter_by(active=True).all()

    config_list = []

    matching_ready = True
    rollover_ready = True

    # loop through all active project classes
    for pclass in pcs:

        # get current configuration record for this project class
        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=pclass.id) \
            .order_by(ProjectClassConfig.year.desc()).first()

        if config is not None:

            # compute capacity data for this project class
            group_data, total_projects, total_faculty, total_capacity, total_capacity_bounded = \
                get_capacity_data(pclass)

            config_list.append((config, total_capacity, total_capacity_bounded))

            if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
                matching_ready = False

            if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER:
                rollover_ready = False

    return config_list, current_year, rollover_ready, matching_ready


def get_convenor_dashboard_data(pclass, config):
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

    # number of is_offerable projects
    project_count = 0

    # total capacity of projects
    # the flag 'capacity_bounded' is used to track whether any projects have quota enforcement turned off,
    # and therefore the computed capacity is a lower bound
    capacity = 0
    capacity_bounded = True

    for project in projects:

        if project.is_offerable:

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


def get_capacity_data(pclass):

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


def get_matching_dashboard_data():

    year = get_current_year()

    matches = db.session.query(func.count(MatchingAttempt.id)).filter_by(year=year).scalar()

    return matches


def filter_projects(plist, groups, skills, getter=None):

    projects = []

    for item in plist:

        if getter is not None:
            proj = getter(item)
        else:
            proj = item

        append = True

        if len(groups) > 0:

            # check if any of the items in the filter list matches this project's group affiliation
            match = False

            for group in groups:
                if proj.group_id == group.id:
                    match = True
                    break

            # nothing matched, kill append
            if not match:
                append = False

        if append and len(skills) > 0:

            # check if any of the items in the skill list matches one of this project's transferable skills
            match = False

            for skill in skills:
                inner_match = False

                for sk in proj.skills:
                    if sk.group_id == skill.id:
                        inner_match = True
                        break

                if inner_match:
                    match = True
                    break

            if not match:
                append = False

        if append:
            projects.append(item)

    return projects


def build_second_marker_query(proj, state_filter, pclass_filter, group_filter):
    """
    Build a query for FacultyData records suitable to populate the 2nd marker view
    :param proj:
    :param state_filter:
    :param pclass_filter:
    :param group_filter:
    :return:
    """

    # build base query -- either all users, or attached users, or not attached faculty
    if state_filter == 'attached':
        # build list of all active faculty users who are attached
        query = proj.second_markers \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active == True, User.id != proj.owner_id)

    elif state_filter == 'not-attached':
        # build list of all active faculty users who are not attached
        attached_query = proj.second_markers.subquery()

        query = db.session.query(FacultyData) \
            .join(User, User.id == FacultyData.id) \
            .join(attached_query, attached_query.c.id == FacultyData.id, isouter=True) \
            .filter(attached_query.c.id == None,
                    User.active == True, User.id != proj.owner_id)

    else:
        # build list of all active faculty
        query = db.session.query(FacultyData) \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active == True, User.id != proj.owner_id)

    # add filters for research group, if a filter is applied
    flag, value = is_integer(group_filter)

    if flag:
        query = query.filter(FacultyData.affiliations.any(ResearchGroup.id == value))

    # add filters for enrollment in a particular project class
    flag, value = is_integer(pclass_filter)

    if flag:
        query = query.filter(FacultyData.enrollments.any(EnrollmentRecord.pclass_id == value))

    query = query.order_by(User.last_name, User.first_name)

    return query


def filter_second_markers(proj, state_filter, pclass_filter, group_filter):
    """
    Build a list of FacultyData records suitable for the 2nd marker table
    :param pclass_filter:
    :param proj:
    :param state_filter:
    :param group_filter:
    :return:
    """

    query = build_second_marker_query(proj, state_filter, pclass_filter, group_filter)

    return query.all()


def get_convenor_filter_record(config):

    # extract FilterRecord for the logged-in user, if one exists
    record = config.filters.filter_by(user_id=current_user.id).first()

    if record is None:
        record = FilterRecord(user_id=current_user.id,
                              config_id=config.id)
        db.session.add(record)
        db.session.commit()

    return record


def build_enroll_selector_candidates(config):
    """
    Build a query that returns possible candidates for manual enrollment as selectors
    :param config:
    :return:
    """

    # which year does the project run in, and for how long?
    year = config.project_class.year
    extent = config.project_class.extent

    # earliest year: academic year in which students can be selectors
    first_selector_year = year - 1

    # latest year: last academic year in which students can be a selector
    last_selector_year = year + (extent - 1) - 1

    # build a list of eligible students who are not already attached as selectors
    candidates = db.session.query(StudentData) \
        .filter(StudentData.cohort >= config.year - first_selector_year + 1,
                StudentData.cohort <= config.year - last_selector_year + 1) \
        .join(User, StudentData.id == User.id).filter(User.active == True)

    # build a list of existing selecting students
    selectors = db.session.query(SelectingStudent.student_id) \
        .filter(SelectingStudent.config_id == config.id,
                ~SelectingStudent.retired).subquery()

    # find students in candidates who are not also in selectors
    missing = candidates.join(selectors, selectors.c.student_id == StudentData.id, isouter=True) \
        .filter(selectors.c.student_id == None)

    return missing


def get_automatch_pclasses():
    """
    Build a list of pclasses that participate in automatic matching
    :return:
    """

    pclasses = db.session.query(ProjectClass).filter_by(active=True, do_matching=True).all()

    return pclasses
