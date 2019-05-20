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

from sqlalchemy import and_, or_
from sqlalchemy.event import listens_for

from ..database import db
from ..models import MainConfig, ProjectClass, ProjectClassConfig, User, FacultyData, Project, \
    EnrollmentRecord, ResearchGroup, SelectingStudent, SubmittingStudent, LiveProject, FilterRecord, StudentData, \
    MatchingAttempt, MatchingRecord, ProjectDescription, WorkflowMixin
from ..models import project_assessors
from ..cache import cache

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

                if schedule.owner.feedback_open:
                    if schedule.owner.has_errors:
                        if schedule.event_name not in error_events:
                            messages.append(('error', 'Event "{event}" and deployed schedule "{name}" for project class '
                                             '"{pclass}" contain validation errors. Please attend to these as soon '
                                             'as possible.'.format(name=schedule.name, event=schedule.event_name,
                                                                   pclass=config.project_class.name)))
                            error_events.add(schedule.event_name)

                    elif schedule.has_errors:
                        if schedule.name not in error_schedules:
                            messages.append(('error', 'Deployed schedule "{name}" for event "{event}" and project class "{pclass}" '
                                             'contains validation errors. Please attend to these as soon as '
                                             'possible.'.format(name=schedule.name, event=schedule.event_name,
                                                                pclass=config.project_class.name)))
                            error_schedules.add(schedule.name)

                    elif schedule.has_warnings:
                        if schedule.name not in error_schedules:
                            messages.append(('warning', 'Deployed schedule "{name}" for event "{event}" and project class '
                                             '"{pclass}" contains validation'
                                             ' warnings.'.format(name=schedule.name, event=schedule.event_name,
                                                                 pclass=config.project_class.name)))
                            error_schedules.add(schedule.name)

    return {'messages': messages}


def get_matching_data(configs=None):
    if configs is None:
        configs = _get_pclass_config_list()

    matching_ready = False

    # loop through all active project classes
    for config in configs:
        if config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
            matching_ready = True

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


def get_global_context_data():
    pcs = _get_pclass_list()
    configs = _get_pclass_config_list(pcs)

    assessment = get_assessment_data(pcs)
    matching = get_matching_data(configs)

    assessment.update(matching)
    return assessment


def get_pclass_config_data(configs=None):
    if configs is None:
        configs = _get_pclass_config_list()

    config_list = []
    config_warning = False

    # loop through all active project classes
    for config in configs:
        # compute capacity data for this project class
        data = get_capacity_data(config.project_class)

        capacity = data['capacity']
        capacity_bounded = data['capacity_bounded']

        if capacity < 1.15*config.number_selectors:
            config_warning = True

        config_list.append({'config': config,
                            'capacity': capacity,
                            'is_bounded': capacity_bounded})

    return {'config_list': config_list,
            'config_warning': config_warning}


def get_approvals_data():
    data = {}

    if current_user.has_role('user_approver'):
        data.update(_get_user_approvals_data())

    if current_user.has_role('project_approver'):
        data.update(_get_project_approvals_data())

    total = 0
    for v in data.values():
        total += v

    data['total'] = total

    return data


def _get_user_approvals_data():
    to_approve = get_count(db.session.query(StudentData). \
                           filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
                                  or_(and_(StudentData.last_edit_id == None, StudentData.creator_id != current_user.id),
                                      and_(StudentData.last_edit_id != None, StudentData.last_edit_id != current_user.id))))

    to_correct = get_count(db.session.query(StudentData). \
                           filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED,
                                  or_(and_(StudentData.last_edit_id == None, StudentData.creator_id == current_user.id),
                                      and_(StudentData.last_edit_id != None, StudentData.last_edit_id == current_user.id))))

    return {'approval_user_outstanding': to_approve,
            'approval_user_rejected': to_correct}


def build_project_approval_queues():
    # want to count number of ProjectDescriptions that are associated with project classes that are in the
    # confirmation phase, for faculty that have signed-off on their projects
    descriptions = db.session.query(ProjectDescription).all()

    queued = []
    rejected = []

    for desc in descriptions:
        if allow_approvals(desc.id):
            if desc.workflow_state == ProjectDescription.WORKFLOW_APPROVAL_QUEUED:
                queued.append(desc.id)
            elif desc.workflow_state == ProjectDescription.WORKFLOW_APPROVAL_REJECTED:
                rejected.append(desc.id)

    return {'queued': queued,
            'rejected': rejected}


@cache.memoize()
def allow_approvals(desc_id):
    desc = db.session.query(ProjectDescription).filter_by(id=desc_id).first()

    if desc is None:
        return False

    faculty = desc.parent.owner

    # no-one should approve their own projects
    if faculty.id == current_user.id:
        return False

    # don't include inactive faculty
    if not faculty.user.active:
        return False

    # don't include inactive projects
    if not desc.parent.active:
        return False

    # don't include descriptions or projects that have validation errors
    # no need to check descriptions separately since they are validated as part
    # of the parent project
    if not desc.parent.is_offerable:
        return False

    for pcl in desc.project_classes:

        # ensure pcl is also in list of project classes for parent project
        if pcl in desc.parent.project_classes:
            config = db.session.query(ProjectClassConfig) \
                .filter_by(pclass_id=pcl.id) \
                .order_by(ProjectClassConfig.year.desc()).first()

            if config is not None and pcl.active and pcl.publish:
                # don't include projects for project classes that have already gone live
                if config.live:
                    continue

                # don't include projects if user is not enrolled normally as a supervisor
                record = faculty.get_enrollment_record(pcl.id)
                if record is None or record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
                    continue

                # don't include projects if confirmation is required and requests haven't been issued.
                # don't include projects if requests have been issued, but project owner hasn't yet confirmed
                if config.require_confirm:
                    if not config.requests_issued:
                        continue

                    if not desc.confirmed:
                        continue

                    if get_count(config.confirmation_required.filter_by(id=faculty.id)) > 0:
                        continue

                return True

    return False



def _approvals_ProjectDescription_delete_cache(desc):
    cache.delete_memoized(allow_approvals, desc.id)


@listens_for(ProjectDescription, 'before_insert')
def _approvals_ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription, 'before_update')
def _approvals_ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription, 'before_update')
def _approvals_ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription.project_classes, 'append')
def _approvals_ProjectDescription_project_classes_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription.project_classes, 'remove')
def _approvals_ProjectDescription_project_classes_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


def _approvals_delete_ProjectClass_cache(project):
    for d in project.descriptions:
        cache.delete_memoized(allow_approvals, d.id)


@listens_for(ProjectClass, 'before_insert')
def _approvals_ProjectClass_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target)


@listens_for(ProjectClass, 'before_update')
def _approvals_ProjectClass_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target)


@listens_for(ProjectClass, 'before_delete')
def _approvals_ProjectClass_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target)


@listens_for(ProjectClassConfig, 'before_insert')
def _approvals_ProjectClassConfig_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig, 'before_update')
def _approvals_ProjectClassConfig_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig, 'before_delete')
def _approvals_ProjectClassConfig_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig.confirmation_required, 'append')
def _approvals_ProjectClassConfig_confirmation_required_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig.confirmation_required, 'remove')
def _approvals_ProjectClassConfig_confirmation_required_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


def _approvals_delete_EnrollmentRecord_cache(record):
    descriptions = db.session.query(ProjectDescription) \
        .join(Project, Project.id == ProjectDescription.parent_id) \
        .filter(Project.owner_id == record.owner_id,
                ProjectDescription.project_classes.any(id=record.pclass_id)).all()

    for d in descriptions:
        cache.delete_memoized(allow_approvals, d.id)


@listens_for(EnrollmentRecord, 'before_insert')
def _approvals_EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, 'before_update')
def _approvals_EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, 'before_delete')
def _approvals_EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_EnrollmentRecord_cache(target)


def _get_project_approvals_data():
    data = build_project_approval_queues()

    queued = data.get('queued')
    rejected = data.get('rejected')

    return {'approval_project_queued': len(queued) if isinstance(queued, list) else 0,
            'approval_project_rejected': len(rejected) if isinstance(rejected, list) else 0}


def _get_pclass_list():
    return db.session.query(ProjectClass) \
        .filter_by(active=True) \
        .order_by(ProjectClass.name.asc()).all()


def _get_pclass_config_list(pcs=None):
    if pcs is None:
        pcs = _get_pclass_list()

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

    rollover_data.update(matching_data)

    return rollover_data


def get_root_dashboard_data():
    current_year = get_current_year()

    pcs = _get_pclass_list()
    configs = _get_pclass_config_list(pcs=pcs)

    # don't need get_assessment_data since these keys are made available in the global context
    # don't need get_matching_data since these keys are made available in the global context
    rollover_data = get_rollover_data(configs=configs, current_year=current_year)
    message_data = get_schedule_message_data(configs=configs)
    config_data = get_pclass_config_data(configs=configs)

    data = {'warning': (config_data['config_warning']
                        or rollover_data['rollover_ready']),
            'current_year': current_year}

    data.update(rollover_data)
    data.update(message_data)
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
        .filter(Project.active == True,
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

    return {'faculty': fac_count,
            'total_faculty': fac_total,
            'live_projects': live_count,
            'attached_projects': proj_count,
            'selectors': sel_count,
            'submitters': sub_count}


@cache.memoize()
def _compute_group_capacity_data(pclass_id, group_id):
    # filter all 'attached' projects that are tagged with this research group, belonging to active faculty
    # who are normally enrolled
    ps = db.session.query(Project) \
        .filter(Project.active == True,
                Project.project_classes.any(id=pclass_id),
                Project.group_id == group_id) \
        .join(User, User.id == Project.owner_id) \
        .join(FacultyData, FacultyData.id == Project.owner_id) \
        .join(EnrollmentRecord,
              and_(EnrollmentRecord.pclass_id == pclass_id, EnrollmentRecord.owner_id == Project.owner_id)) \
        .filter(User.active) \
        .filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED)

    # set of faculty members offering projects
    faculty_offering = set()

    # number of offerable projects
    projects = 0
    pending = 0
    approved = 0
    rejected = 0
    queued = 0

    # total capacity of projects
    # the flag 'capacity_bounded' is used to track whether any projects have quota enforcement turned off,
    # and therefore the computed capacity is a lower bound
    capacity = 0
    capacity_bounded = True

    for p in ps:
        if p.is_offerable:
            projects += 1

            # add owner to list of faculty offering projects
            faculty_offering.add(p.owner.id)

            desc = p.get_description(pclass_id)
            if desc is not None:
                cap = desc.capacity
                if cap is not None and cap > 0:
                    capacity += cap

                if not p.enforce_capacity:
                    capacity_bounded = False

                if not desc.confirmed:
                    pending += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED:
                    queued += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED:
                    rejected += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED:
                    approved += 1

    # get number of enrolled faculty belonging to this research group
    faculty_enrolled = get_count(db.session.query(EnrollmentRecord.id) \
                                 .filter(EnrollmentRecord.pclass_id == pclass_id) \
                                 .join(FacultyData, FacultyData.id == EnrollmentRecord.owner_id) \
                                 .join(User, User.id == EnrollmentRecord.owner_id) \
                                 .filter(FacultyData.affiliations.any(id=group_id),
                                         User.active == True))

    # get total number of faculty belonging to this research group
    faculty_in_group = get_count(db.session.query(FacultyData.id) \
                                 .join(User, User.id == FacultyData.id) \
                                 .filter(FacultyData.affiliations.any(id=group_id),
                                         User.active == True))

    return {'projects': projects,
            'pending': pending,
            'queued': queued,
            'rejected': rejected,
            'approved': approved,
            'faculty_offering': len(faculty_offering),
            'faculty_enrolled': faculty_enrolled,
            'faculty_in_group': faculty_in_group,
            'capacity': capacity,
            'capacity_bounded': capacity_bounded}


def _capacity_delete_ProjectDescription_cache(desc):
    for pcl in desc.project_classes:
        if desc.parent is not None:
            cache.delete_memoized(_compute_group_capacity_data, pcl.id, desc.parent.group_id)
        else:
            cache.delete_memoized(_compute_group_capacity_data)


@listens_for(ProjectDescription, 'before_insert')
def _capacity_ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_ProjectDescription_cache(target)


@listens_for(ProjectDescription, 'before_update')
def _capacity_ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_ProjectDescription_cache(target)


@listens_for(ProjectDescription, 'before_delete')
def _capacity_ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_ProjectDescription_cache(target)


def _capacity_delete_Project_cache(project):
    for pcl in project.project_classes:
        cache.delete_memoized(_compute_group_capacity_data, pcl.id, project.group_id)


@listens_for(Project, 'before_insert')
def _capacity_Project_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_Project_cache(target)


@listens_for(Project, 'before_update')
def _capacity_Project_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_Project_cache(target)


@listens_for(Project, 'before_delete')
def _capacity_Project_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_Project_cache(target)


def _capacity_delete_EnrollmentRecord_cache(record):
    if record.owner_id is None:
        return

    if record.owner is None:
        owner = db.session.query(FacultyData).filter_by(id=record.owner_id).one()
    else:
        owner = record.owner

    for gp in owner.affiliations.all():
        cache.delete_memoized(_compute_group_capacity_data, record.pclass_id, gp.id)


@listens_for(EnrollmentRecord, 'before_insert')
def _capacity_EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, 'before_update')
def _capacity_EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, 'before_delete')
def _capacity_EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_EnrollmentRecord_cache(target)


def _capacity_delete_FacultyData_affiliation_cache(target, value):
    # value is the group that has been added or removed to FacultyData.affiliations
    pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

    for pcl in pclasses:
        cache.delete_memoized(_compute_group_capacity_data, pcl.id, value.id)


@listens_for(FacultyData.affiliations, 'append')
def _capacity_FacultyData_affiliations_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_affiliation_cache(target, value)


@listens_for(FacultyData.affiliations, 'remove')
def _capacity_FacultyData_affiliations_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_affiliation_cache(target, value)


def _capacity_delete_FacultyData_cache(fac_data):
    pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

    for pcl in pclasses:
        for gp in fac_data.affiliations:
            cache.delete_memoized(_compute_group_capacity_data, pcl.id, gp.id)


@listens_for(FacultyData, 'before_insert')
def _capacity_FacultyData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_cache(target)


@listens_for(FacultyData, 'before_update')
def _capacity_FacultyData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_cache(target)


@listens_for(FacultyData, 'before_delete')
def _capacity_FacultyData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_cache(target)


def get_capacity_data(pclass):
    # get list of research groups
    groups = db.session.query(ResearchGroup) \
        .filter_by(active=True)\
        .order_by(ResearchGroup.name) \
        .all()

    data = []

    projects = 0
    pending = 0
    queued = 0
    rejected = 0
    approved = 0

    faculty_offering = 0
    capacity = 0
    capacity_bounded = True

    for group in groups:
        group_data = _compute_group_capacity_data(pclass.id, group.id)

        # update totals
        projects += group_data['projects']
        pending += group_data['pending']
        queued += group_data['queued']
        rejected += group_data['rejected']
        approved += group_data['approved']

        faculty_offering += group_data['faculty_offering']
        capacity += group_data['capacity']
        capacity_bounded = capacity_bounded and group_data['capacity_bounded']

        # store data for this research group
        data.append({'label': group.make_label(group.name), 'data': group_data})

    return {'data': data,
            'projects': projects,
            'pending': pending,
            'queued': queued,
            'rejected': rejected,
            'approved': approved,
            'faculty_offering': faculty_offering,
            'capacity': capacity,
            'capacity_bounded': capacity_bounded}


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
                    if sk.id == skill.id:
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


def build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter):
    # build a list of live students submitting work for evaluation in this project class
    submitters = config.submitting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

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

    if year_flag:
        data = [s for s in data if s.academic_year == year_value]

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
