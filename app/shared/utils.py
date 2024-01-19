#
# Created by David Seery on 28/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from collections.abc import Iterable
from typing import List

from flask import redirect, url_for, flash, request
from flask_security import current_user
from sqlalchemy import and_, or_
from sqlalchemy.event import listens_for

from .conversions import is_integer
from .sqlalchemy import get_count
from ..cache import cache
from ..database import db
from ..models import (
    MainConfig,
    ProjectClass,
    ProjectClassConfig,
    User,
    FacultyData,
    Project,
    EnrollmentRecord,
    ResearchGroup,
    SelectingStudent,
    SubmittingStudent,
    FilterRecord,
    StudentData,
    ProjectDescription,
    DegreeProgramme,
    DegreeType,
)
from ..models import project_assessors


def get_main_config():
    return db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()


def get_current_year():
    return get_main_config().year


def home_dashboard_url():
    if current_user.has_role("faculty"):
        return url_for("faculty.dashboard")

    elif current_user.has_role("student"):
        return url_for("student.dashboard")

    elif current_user.has_role("office"):
        return url_for("office.dashboard")

    else:
        return "#"


def home_dashboard():
    url = home_dashboard_url()

    if url is not None:
        return redirect(url)

    flash("Your role could not be identified. Please contact the system administrator.")
    return redirect(url_for("auth.logged_out"))


def redirect_url(default=None):
    return (
        request.args.get("next")
        or (request.referrer if (request.referrer is not None and "/login" not in request.referrer) else None)
        or (url_for(default) if default is not None else None)
        or home_dashboard()
    )


def get_approval_queue_data():
    total = 0
    data = {}

    if current_user.has_role("user_approver") or current_user.has_role("root") or current_user.has_role("manage_users"):
        user_data = _get_user_approvals_data()
        data.update(user_data)

        if current_user.has_role("user_approver"):
            total += user_data["approval_user_queued"]

        if current_user.has_role("root") or current_user.has_role("manage_users"):
            total += user_data["approval_user_rejected"]

    if current_user.has_role("project_approver") or current_user.has_role("root"):
        project_data = _get_project_approvals_data()
        data.update(project_data)

        for v in project_data.values():
            total += v

    data["total"] = total

    return data


def _get_user_approvals_data():
    to_approve = get_count(
        db.session.query(StudentData).filter(
            StudentData.workflow_state == StudentData.WORKFLOW_APPROVAL_QUEUED,
            or_(
                and_(StudentData.last_edit_id == None, StudentData.creator_id != current_user.id),
                and_(StudentData.last_edit_id != None, StudentData.last_edit_id != current_user.id),
            ),
        )
    )

    to_correct = get_count(
        db.session.query(StudentData).filter(
            StudentData.workflow_state == StudentData.WORKFLOW_APPROVAL_REJECTED,
            or_(
                and_(StudentData.last_edit_id == None, StudentData.creator_id == current_user.id),
                and_(StudentData.last_edit_id != None, StudentData.last_edit_id == current_user.id),
            ),
        )
    )

    return {"approval_user_queued": to_approve, "approval_user_rejected": to_correct}


def _get_project_approvals_data():
    data = build_project_approval_queues()

    queued = data.get("queued")
    rejected = data.get("rejected")

    return {
        "approval_project_queued": len(queued) if isinstance(queued, list) else 0,
        "approval_project_rejected": len(rejected) if isinstance(rejected, list) else 0,
    }


def build_project_approval_queues():
    # want to count number of ProjectDescriptions that are associated with project classes that are in the
    # confirmation phase.
    # We ignore descriptions that have already been validated, or which belong to inactive projects
    descriptions = (
        db.session.query(ProjectDescription)
        .join(Project, Project.id == ProjectDescription.parent_id)
        .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
        .join(User, User.id == FacultyData.id, isouter=True)
        .filter(
            ProjectDescription.confirmed,
            ProjectDescription.workflow_state != ProjectDescription.WORKFLOW_APPROVAL_VALIDATED,
            Project.active == True,
            or_(Project.generic == True, and_(Project.generic == False, FacultyData.id != None, User.active == True)),
        )
        .all()
    )

    queued = []
    rejected = []

    for desc in descriptions:
        if allow_approval_for_project(desc.id):
            if desc.workflow_state == ProjectDescription.WORKFLOW_APPROVAL_QUEUED:
                queued.append(desc.id)
            elif desc.workflow_state == ProjectDescription.WORKFLOW_APPROVAL_REJECTED:
                rejected.append(desc.id)

    return {"queued": queued, "rejected": rejected}


@cache.memoize()
def allow_approval_for_project(desc_id):
    desc: ProjectDescription = db.session.query(ProjectDescription).filter_by(id=desc_id).first()

    if desc is None:
        return False

    parent: Project = desc.parent
    if parent.generic:
        return False

    owner: FacultyData = desc.parent.owner

    if owner:
        # no-one should approve their own projects
        if owner.id == current_user.id:
            return False

        # don't include inactive faculty
        if not owner.user.active:
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
        pcl: ProjectClass

        # ensure pcl is also in list of project classes for parent project
        if pcl in desc.parent.project_classes:
            # check user is root or in approvals team for this project class
            in_team = current_user.has_role("root") or get_count(pcl.approvals_team.filter_by(id=current_user.id)) > 0
            if not in_team:
                continue

            config: ProjectClassConfig = pcl.most_recent_config

            if config is not None and pcl.active and pcl.publish:
                # don't include projects for project classes that have already gone live
                if config.live:
                    continue

                # don't include projects if user is not enrolled normally as a supervisor
                record: EnrollmentRecord = owner.get_enrollment_record(pcl.id)
                if record is None or record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
                    continue

                # for project classes that require project confirmations:
                if config.require_confirm:
                    # don't include projects if confirmation is required and requests haven't been issued.
                    if not config.requests_issued:
                        continue

                    # don't include descriptions that have not been confirmed by their owner
                    if not desc.confirmed:
                        continue

                return True

    return False


def _approvals_ProjectDescription_delete_cache(desc):
    cache.delete_memoized(allow_approval_for_project, desc.id)


@listens_for(ProjectDescription, "before_insert")
def _approvals_ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription, "before_update")
def _approvals_ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription, "before_delete")
def _approvals_ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription.project_classes, "append")
def _approvals_ProjectDescription_project_classes_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


@listens_for(ProjectDescription.project_classes, "remove")
def _approvals_ProjectDescription_project_classes_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_ProjectDescription_delete_cache(target)


def _approvals_delete_ProjectClass_cache(project):
    for d in project.descriptions:
        cache.delete_memoized(allow_approval_for_project, d.id)


@listens_for(ProjectClass, "before_insert")
def _approvals_ProjectClass_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target)


@listens_for(ProjectClass, "before_update")
def _approvals_ProjectClass_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target)


@listens_for(ProjectClass, "before_delete")
def _approvals_ProjectClass_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target)


@listens_for(ProjectClassConfig, "before_insert")
def _approvals_ProjectClassConfig_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        if target.project_class is not None:
            _approvals_delete_ProjectClass_cache(target.project_class)
        elif target.pclass_id is not None:
            pclass = db.session.query(ProjectClass).filter_by(id=target.pclass_id).first()
            if pclass is not None:
                _approvals_delete_ProjectClass_cache(pclass)


@listens_for(ProjectClassConfig, "before_update")
def _approvals_ProjectClassConfig_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig, "before_delete")
def _approvals_ProjectClassConfig_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig.confirmation_required, "append")
def _approvals_ProjectClassConfig_confirmation_required_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


@listens_for(ProjectClassConfig.confirmation_required, "remove")
def _approvals_ProjectClassConfig_confirmation_required_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _approvals_delete_ProjectClass_cache(target.project_class)


def _approvals_delete_EnrollmentRecord_cache(record):
    descriptions = (
        db.session.query(ProjectDescription)
        .join(Project, Project.id == ProjectDescription.parent_id)
        .filter(Project.owner_id == record.owner_id, ProjectDescription.project_classes.any(id=record.pclass_id))
        .all()
    )

    for d in descriptions:
        cache.delete_memoized(allow_approval_for_project, d.id)


@listens_for(EnrollmentRecord, "before_insert")
def _approvals_EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, "before_update")
def _approvals_EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, "before_delete")
def _approvals_EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _approvals_delete_EnrollmentRecord_cache(target)


def build_assessor_query(proj, state_filter, pclass_filter, group_filter):
    """
    Build a query for FacultyData records suitable to populate the marker view
    :param proj:
    :param state_filter:
    :param pclass_filter:
    :param group_filter:
    :return:
    """

    # build base query -- either all users, or attached users, or not attached faculty
    if state_filter == "attached":
        # build list of all active faculty users who are attached
        sq = db.session.query(project_assessors.c.faculty_id).filter(project_assessors.c.project_id == proj.id).subquery()

        query = (
            db.session.query(FacultyData)
            .join(sq, sq.c.faculty_id == FacultyData.id)
            .join(User, User.id == FacultyData.id)
            .filter(User.active == True, User.id != proj.owner_id)
        )

    elif state_filter == "not-attached":
        # build list of all active faculty users who are not attached
        attached_query = proj.assessors.subquery()

        query = (
            db.session.query(FacultyData)
            .join(User, User.id == FacultyData.id)
            .join(attached_query, attached_query.c.id == FacultyData.id, isouter=True)
            .filter(attached_query.c.id == None, User.active == True, User.id != proj.owner_id)
        )

    else:
        # build list of all active faculty
        query = db.session.query(FacultyData).join(User, User.id == FacultyData.id).filter(User.active == True, User.id != proj.owner_id)

    # add filters for research group, if a filter is applied
    flag, value = is_integer(group_filter)

    if flag:
        query = query.filter(FacultyData.affiliations.any(ResearchGroup.id == value))

    # add filters for enrolment in a particular project class
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


def get_convenor_filter_record(config) -> FilterRecord:
    # extract FilterRecord for the logged-in user, if one exists
    record = config.filters.filter_by(user_id=current_user.id).first()

    if record is None:
        record = FilterRecord(user_id=current_user.id, config_id=config.id)
        db.session.add(record)
        db.session.commit()

    return record


def detuple(x):
    while isinstance(x, Iterable):
        x = x[0]

    return x


def build_enrol_selector_candidates(config: ProjectClassConfig, disable_programme_filter: bool = False):
    """
    Build a query that returns possible candidates for manual enrolment as selectors
    :param disable_programme_filter:
    :param config:
    :return:
    """
    year_offset = -1 if config.select_in_previous_cycle else 0
    return _build_generic_enroll_candidate(config, year_offset, SelectingStudent, disable_programme_filter=disable_programme_filter)


def build_enrol_submitter_candidates(config: ProjectClassConfig, disable_programme_filter: bool = False):
    """
    Build a query that returns possible candidate for manual enrolment as submitters
    :param config:
    :return:
    """
    return _build_generic_enroll_candidate(config, 0, SubmittingStudent, disable_programme_filter=disable_programme_filter)


def _build_generic_enroll_candidate(config: ProjectClassConfig, year_offset: int, StudentRecordType, disable_programme_filter: bool = False):
    """
    Build a query that returns missing candidates for manual enrolment
    :param disable_programme_filter:
    :param config: ProjectClassConfig instance to which we wish to add manually enrolled students
    :param year_offset: offset in years to be applied to the year range. Should be -1 for selectors, if selection
     takes places in the previous cycle, or 0 for submitters.
    :param StudentRecordType: Student model. Usually SubmittingStudent for submitters and SelectingStudent for selectors.
    :return:
    """
    # which year does the project run in, and for how long?
    start_year = config.start_year
    extent = config.extent

    # earliest year: academic year in which students can be enrolled (either as selectors or submitters, depending on
    # year_offset)
    first_year = start_year + year_offset

    # latest year: last academic year in which students can be enrolled (either as selectors or submitters, depending on
    # year_offset)
    last_year = start_year + extent + year_offset

    if disable_programme_filter or config.selection_open_to_all:
        allowed_programmes = None
    else:
        allowed_programmes = config.project_class.programmes.with_entities(DegreeProgramme.id).distinct().all()
        allowed_programmes = set(detuple(x) for x in allowed_programmes)

    # build a list of eligible students who are not already attached as selectors
    candidate_students = _build_candidates(allowed_programmes, config.student_level, first_year, last_year)

    # build a list of existing selecting students associated with this ProjectClassConfig instance
    existing_students = db.session.query(StudentRecordType.student_id).filter(StudentRecordType.config_id == config.id, ~StudentRecordType.retired)

    existing_students = existing_students.subquery()

    # find students in candidates who are not also in selectors
    # StudentData model in this expression references the query candidate_students, which selects a list of
    # StudentData instances
    missing_students = candidate_students.join(existing_students, existing_students.c.student_id == StudentData.id, isouter=True).filter(
        existing_students.c.student_id == None
    )

    return missing_students


def _build_candidates(allowed_programmes, student_level: int, first_year: int, last_year: int):
    candidates = (
        db.session.query(StudentData)
        .join(User, StudentData.id == User.id)
        .filter(User.active == True)
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
    )

    # if allowed programmes are specified, filter the candidates according to this allowed set (which should all
    # be at a consistent level, e.g. UG, PGT, PGR)
    if allowed_programmes is not None and len(allowed_programmes) > 0:
        candidates = candidates.filter(StudentData.programme_id.in_(allowed_programmes))

    # otherwise, filter candidates by the level of the project class
    else:
        candidates = candidates.filter(DegreeType.level == student_level)

    # restrict to candidates who have not graduated, and who fall between the allowed years from enrolment
    candidates = candidates.filter(
        or_(
            StudentData.academic_year == None,
            StudentData.academic_year <= DegreeType.duration,
            and_(StudentData.academic_year >= first_year, StudentData.academic_year <= last_year),
        )
    )

    return candidates


def get_automatch_pclasses():
    """
    Build a list of pclasses that participate in automatic matching
    :return:
    """

    pclasses = db.session.query(ProjectClass).filter_by(active=True, do_matching=True).all()

    return pclasses


def build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter) -> List[SubmittingStudent]:
    # build a list of live students submitting work for evaluation in this project class
    submitters: List[SubmittingStudent] = config.submitting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag or prog_flag or state_filter == "twd":
        submitters = submitters.join(StudentData, StudentData.id == SubmittingStudent.student_id)

    if cohort_flag:
        submitters = submitters.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        submitters = submitters.filter(StudentData.programme_id == prog_value)

    if state_filter == "published":
        submitters = submitters.filter(SubmittingStudent.published == True)
        data = submitters.all()
    elif state_filter == "unpublished":
        submitters = submitters.filter(SubmittingStudent.published == False)
        data = submitters.all()
    elif state_filter == "late-feedback":
        data = [x for x in submitters.all() if x.has_late_feedback]
    elif state_filter == "no-late-feedback":
        data = [x for x in submitters.all() if not x.has_late_feedback]
    elif state_filter == "not-started":
        data = [x for x in submitters.all() if x.has_not_started_flags]
    elif state_filter == "report":
        data = [x for x in submitters.all() if x.has_report]
    elif state_filter == "no-report":
        data = [x for x in submitters.all() if not x.has_report]
    elif state_filter == "attachments":
        data = [x for x in submitters.all() if x.has_attachments]
    elif state_filter == "no-attachments":
        data = [x for x in submitters.all() if not x.has_attachments]
    elif state_filter == "twd":
        submitters = submitters.filter(StudentData.intermitting == True)
        data = submitters.all()
    else:
        data = submitters.all()

    if year_flag:
        data = [s for s in data if (s.academic_year is None or s.academic_year == year_value)]

    return data
