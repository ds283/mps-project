#
# Created by David Seery on 28/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import redirect, url_for, flash, current_app
from flask_security import current_user
from sqlalchemy import and_

from ..database import db
from ..models import MainConfig, ProjectClass, ProjectClassConfig, User, FacultyData, Project, \
    EnrollmentRecord, ResearchGroup, SelectingStudent, SubmittingStudent, LiveProject, FilterRecord, StudentData, \
    MatchingAttempt, MatchingRecord
from ..models import project_assessors

from .conversions import is_integer
from .sqlalchemy import get_count

from os import path, makedirs
from uuid import uuid4


def get_main_config():
    return db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()


def get_current_year():
    return get_main_config().year


def home_dashboard_url():
    if current_user.has_role('faculty'):
        return url_for('faculty.dashboard')

    elif current_user.has_role('student'):
        return url_for('student.dashboard')

    elif current_user.has_role('office'):
        return url_for('office.dashboard')

    else:
        return '#'


def home_dashboard():
    url = home_dashboard_url()

    if url is not None:
        return redirect(url)

    flash('Your role could not be identified. Please contact the system administrator.')
    return redirect(url_for('auth.logged_out'))


def get_rollover_data(configs=None, current_year=None):
    if configs is None:
        configs = _get_pclass_config_list()

    if current_year is None:
        current_year = get_current_year()

    rollover_ready = True
    rollover_in_progress = False

    # loop through all active project classes
    for config in configs:
        # if MainConfig year has already been advanced, then we shouldn't offer
        # matching or rollover options on the dashboard
        if config.year < current_year:
            rollover_in_progress = True

        if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER:
            rollover_ready = False

        if config.submitter_lifecycle < ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
            rollover_ready = False

    return {'rollover_ready': rollover_ready,
            'rollover_in_progress': rollover_in_progress}


def get_schedule_message_data(configs=None):
    if configs is None:
        configs = _get_pclass_config_list()

    messages = []
    error_events = set()
    error_schedules = set()

    # loop through all active project classes
    for config in configs:
        for period in config.periods:
            if period.has_deployed_schedule:
                schedule = period.deployed_schedule

                if not schedule.owner.is_valid:
                    if schedule.event_name not in error_events:
                        messages.append(('error', 'Event "{event}" and deployed schedule "{name}" for project class '
                                         '"{pclass}" contain validation errors. Please attend to these as soon '
                                         'as possible.'.format(name=schedule.name, event=schedule.event_name,
                                                               pclass=pclass.name)))
                        error_events.add(schedule.event_name)

                elif not schedule.is_valid:
                    if schedule.name not in error_schedules:
                        messages.append(('error', 'Deployed schedule "{name}" for event "{event}" and project class "{pclass}") '
                                         'contains validation errors. Please attend to these as soon as '
                                         'possible.'.format(name=schedule.name, event=schedule.event_name,
                                                            pclass=pclass.name)))
                        error_schedules.add(schedule.name)

    return {'messages': messages}


def get_matching_data(configs=None):
    if configs is None:
        configs = _get_pclass_config_list()

    matching_ready = True

    # loop through all active project classes
    for config in configs:
        if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
            matching_ready = False

    return {'matching_ready': matching_ready}


def get_assessment_data(pcs=None):
    if pcs is None:
        pcs = _get_pclass_list()

    presentation_assessments = False

    # loop through all active project classes
    for pclass in pcs:
        if pclass.uses_presentations:
            presentation_assessments = True

    return {'has_assessments': presentation_assessments}


def get_pclass_config_data(configs=None):
    if configs is None:
        configs = _get_pclass_config_list()

    config_list = []
    config_warning = False

    # loop through all active project classes
    for config in configs:
        # compute capacity data for this project class
        group_data, total_projects, total_faculty, total_capacity, total_capacity_bounded = \
            get_capacity_data(config.project_class)

        if total_capacity < 1.15*config.number_selectors:
            config_warning = True

        config_list.append((config, total_capacity, total_capacity_bounded))

    return {'config_list': config_list,
            'config_warning': config_warning}


def _get_pclass_list():
    return db.session.query(ProjectClass) \
        .filter_by(active=True) \
        .order_by(ProjectClass.name.asc()).all()


def _get_pclass_config_list(pcs=None):
    if pcs is None:
        pcs = _get_pclass_config_list()

    cs = [db.session.query(ProjectClassConfig). \
              filter_by(pclass_id=pclass.id). \
              order_by(ProjectClassConfig.year.desc()).first() for pclass in pcs]

    # strip out 'None' entries before returning
    return [x for x in cs if x is not None]


def get_ready_to_match_data():
    pcs = _get_pclass_list()
    configs = _get_pclass_config_list(pcs=pcs)

    rollover_data = get_rollover_data(configs=configs)
    matching_data = get_matching_data(configs=configs)

    return rollover_data.update(matching_data)


def get_root_dashboard_data():
    current_year = get_current_year()

    pcs = _get_pclass_list()
    configs = _get_pclass_config_list(pcs=pcs)

    rollover_data = get_rollover_data(configs=configs, current_year=current_year)
    message_data = get_schedule_message_data(configs=configs)
    matching_data = get_matching_data(configs=configs)
    assessment_data = get_assessment_data(pcs=pcs)
    config_data = get_pclass_config_data(configs=configs)

    data = {'warning': (config_data['config_warning']
                        or matching_data['matching_ready']
                        or rollover_data['rollover_ready']),
            'current_year': current_year}

    data.update(rollover_data)
    data.update(message_data)
    data.update(matching_data)
    data.update(assessment_data)
    data.update(config_data)

    return data


def get_convenor_dashboard_data(pclass, config):
    """
    Efficiently retrieve statistics needed to render the convenor dashboard
    :param pclass:
    :param config:
    :return:
    """
    fac_query = db.session.query(User) \
        .filter_by(active=True) \
        .join(FacultyData, FacultyData.id == User.id)

    fac_total = get_count(fac_query)
    fac_count = get_count(fac_query.filter(FacultyData.enrollments.any(pclass_id=pclass.id)))

    attached_projects = db.session.query(Project) \
        .filter(Project.active,
                Project.project_classes.any(id=pclass.id)) \
        .join(User, User.id == Project.owner_id) \
        .join(FacultyData, FacultyData.id == Project.owner_id) \
        .join(EnrollmentRecord,
              and_(EnrollmentRecord.pclass_id == pclass.id, EnrollmentRecord.owner_id == Project.owner_id)) \
        .filter(User.active) \
        .filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED) \
        .order_by(User.last_name, User.first_name)
    proj_count = get_count(attached_projects)

    sel_count = get_count(config.selecting_students.filter_by(retired=False))
    sub_count = get_count(config.submitting_students.filter_by(retired=False))
    live_count = get_count(config.live_projects)

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

            cap = project.get_capacity(pclass)
            if cap is not None and cap > 0:
                capacity += cap
            if not project.enforce_capacity:
                capacity_bounded = False

    # get number of enrolled faculty belonging to this research group
    enrolled = get_count(db.session.query(EnrollmentRecord.id) \
                         .filter(EnrollmentRecord.pclass_id == pclass.id) \
                         .join(FacultyData, FacultyData.id == EnrollmentRecord.owner_id) \
                         .join(User, User.id == EnrollmentRecord.owner_id) \
                         .filter(FacultyData.affiliations.any(id=group.id),
                                 User.active == True))

    # get total number of faculty belonging to this research group
    total = get_count(db.session.query(FacultyData.id) \
                      .join(User, User.id == FacultyData.id) \
                      .filter(FacultyData.affiliations.any(id=group.id),
                              User.active == True))

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
    matches = get_count(db.session.query(MatchingAttempt).filter_by(year=year))

    return matches


def filter_projects(plist, groups, skills, getter=None, setter=None):
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
            if setter is not None:
                projects.append(setter(item))
            else:
                projects.append(item)

    return projects


def build_assessor_query(proj, state_filter, pclass_filter, group_filter):
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
        sq = db.session.query(project_assessors.c.faculty_id) \
            .filter(project_assessors.c.project_id == proj.id).subquery()

        query = db.session.query(FacultyData) \
            .join(sq, sq.c.faculty_id == FacultyData.id) \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active == True, User.id != proj.owner_id)

    elif state_filter == 'not-attached':
        # build list of all active faculty users who are not attached
        attached_query = proj.assessors.subquery()

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


def filter_assessors(proj, state_filter, pclass_filter, group_filter):
    """
    Build a list of FacultyData records suitable for the assessor table
    :param pclass_filter:
    :param proj:
    :param state_filter:
    :param group_filter:
    :return:
    """
    query = build_assessor_query(proj, state_filter, pclass_filter, group_filter)
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
    year = config.start_year
    extent = config.extent

    # earliest year: academic year in which students can be selectors
    first_selector_year = year - 1

    # latest year: last academic year in which students can be a selector
    last_selector_year = year + (extent - 1) - 1

    # build a list of eligible students who are not already attached as selectors
    candidates = db.session.query(StudentData) \
        .filter(StudentData.foundation_year == False,
                config.year - StudentData.cohort + 1 - StudentData.repeated_years >= first_selector_year,
                config.year - StudentData.cohort + 1 - StudentData.repeated_years <= last_selector_year) \
        .join(User, StudentData.id == User.id) \
        .filter(User.active == True)

    fyear_candidates = db.session.query(StudentData) \
        .filter(StudentData.foundation_year == True,
                config.year - StudentData.cohort - StudentData.repeated_years >= first_selector_year,
                config.year - StudentData.cohort - StudentData.repeated_years <= last_selector_year) \
        .join(User, StudentData.id == User.id) \
        .filter(User.active == True)

    candidates = candidates.union(fyear_candidates)

    # build a list of existing selecting students
    selectors = db.session.query(SelectingStudent.student_id) \
        .filter(SelectingStudent.config_id == config.id,
                ~SelectingStudent.retired).subquery()

    # find students in candidates who are not also in selectors
    missing = candidates.join(selectors, selectors.c.student_id == StudentData.id, isouter=True) \
        .filter(selectors.c.student_id == None)

    return missing


def build_enroll_submitter_candidates(config):
    """
    Build a query that returns possible candidate for manual enrollment as submitters
    :param config:
    :return:
    """

    # which year does the project run in, and for how long?
    year = config.start_year
    extent = config.extent

    # earliest year: academic year in which students can be submitter
    first_submitter_year = year

    # latest year: last academic year in which students can be a submitter
    last_submitter_year = year + (extent - 1)

    # build a list of eligible students who are not already attached as submitters
    candidates = db.session.query(StudentData) \
        .filter(StudentData.foundation_year == False,
                config.year - StudentData.cohort + 1 - StudentData.repeated_years >= first_submitter_year,
                config.year - StudentData.cohort + 1 - StudentData.repeated_years <= last_submitter_year) \
        .join(User, StudentData.id == User.id) \
        .filter(User.active == True)

    fyear_candidates = db.session.query(StudentData) \
        .filter(StudentData.foundation_year == True,
                config.year - StudentData.cohort - StudentData.repeated_years >= first_submitter_year,
                config.year - StudentData.cohort - StudentData.repeated_years <= last_submitter_year) \
        .join(User, StudentData.id == User.id) \
        .filter(User.active == True)

    candidates = candidates.union(fyear_candidates)

    # build a list of existing selecting students
    submitters = db.session.query(SubmittingStudent.student_id) \
        .filter(SubmittingStudent.config_id == config.id,
                ~SubmittingStudent.retired).subquery()

    # find students in candidates who are not also in selectors
    missing = candidates.join(submitters, submitters.c.student_id == StudentData.id, isouter=True) \
        .filter(submitters.c.student_id == None)

    return missing


def get_automatch_pclasses():
    """
    Build a list of pclasses that participate in automatic matching
    :return:
    """

    pclasses = db.session.query(ProjectClass).filter_by(active=True, do_matching=True).all()

    return pclasses


def build_submitters_data(config, cohort_filter, prog_filter, state_filter):
    # build a list of live students submitting work for evaluation in this project class
    submitters = config.submitting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)

    if cohort_flag or prog_flag:
        submitters = submitters \
            .join(StudentData, StudentData.id == SubmittingStudent.student_id)

    if cohort_flag:
        submitters = submitters.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        submitters = submitters.filter(StudentData.programme_id == prog_value)

    if state_filter == 'published':
        submitters = submitters.filter(SubmittingStudent.published == True)
        data = submitters.all()
    elif state_filter == 'unpublished':
        submitters = submitters.filter(SubmittingStudent.published == False)
        data = submitters.all()
    elif state_filter == 'late-feedback':
        data = [x for x in submitters.all() if x.has_late_feedback]
    elif state_filter == 'no-late-feedback':
        data = [x for x in submitters.all() if not x.has_late_feedback]
    elif state_filter == 'not-started':
        data = [x for x in submitters.all() if x.has_not_started_flags]
    else:
        data = submitters.all()

    return data


def make_generated_asset_filename(ext=None):
    """
    Generate a unique filename for a newly-generated asset
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    generated_subfolder = current_app.config.get('ASSETS_GENERATED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if generated_subfolder is None:
        raise RuntimeError('ASSETS_GENERATED_SUBFOLDER configuration variable is not set')

    if ext is not None:
        filename = '{leaf}.{ext}'.format(leaf=uuid4(), ext=ext)
    else:
        filename = '{leaf}'.format(leaf=uuid4())

    abs_generated_path = path.join(asset_folder, generated_subfolder)
    makedirs(abs_generated_path, exist_ok=True)

    return filename, path.join(abs_generated_path, filename)


def canonical_generated_asset_filename(filename):
    """
    Turn a unique filename for a generated asset into an absolute path
    :param filename:
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    generated_subfolder = current_app.config.get('ASSETS_GENERATED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if generated_subfolder is None:
        raise RuntimeError('ASSETS_GENERATED_SUBFOLDER configuration variable is not set')

    abs_generated_path = path.join(asset_folder, generated_subfolder)
    return path.join(abs_generated_path, filename)


def make_uploaded_asset_filename(ext=None):
    """
    Generate a unique filename for an uploaded asset
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    uploaded_subfolder = current_app.config.get('ASSETS_UPLOADED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if uploaded_subfolder is None:
        raise RuntimeError('ASSETS_UPLOADED_SUBFOLDER configuration variable is not set')

    if ext is not None:
        filename = '{leaf}.{ext}'.format(leaf=uuid4(), ext=ext)
    else:
        filename = '{leaf}'.format(leaf=uuid4())

    abs_generated_path = path.join(asset_folder, uploaded_subfolder)
    makedirs(abs_generated_path, exist_ok=True)

    return filename, path.join(abs_generated_path, filename)


def canonical_uploaded_asset_filename(filename):
    """
    Turn a unique filename for an uploaded asset into an absolute path
    :param filename:
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    uploaded_subfolder = current_app.config.get('ASSETS_UPLOADED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if uploaded_subfolder is None:
        raise RuntimeError('ASSETS_UPLOADED_SUBFOLDER configuration variable is not set')

    abs_generated_path = path.join(asset_folder, uploaded_subfolder)
    return path.join(abs_generated_path, filename)
