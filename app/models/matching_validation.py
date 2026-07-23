#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Consolidated validation logic for MatchingAttempt/MatchingRecord/MatchingRole complexes.

This module imports most of the model layer at module level, so it must NOT be imported at
module level from any model module in its own import closure (matching.py, faculty.py,
live_projects.py, project_class.py, users.py, and anything they import) — doing so would
create a circular import. Instead, those modules import the validators lazily inside the
function bodies that need them (is_valid properties and cache-invalidation helpers).
Non-model code may import this module normally.
"""

from typing import List, Set

from flask import current_app
from sqlalchemy import and_

from ..cache import cache
from ..database import db
from ..shared.sqlalchemy import get_count
from .faculty import EnrollmentRecord, FacultyData
from .live_projects import LiveProject, SelectingStudent
from .matching import MatchingAttempt, MatchingRecord, MatchingRole
from .project_class import (
    ProjectClass,
    ProjectClassConfig,
    SubmissionPeriodDefinition,
    SubmissionPeriodRecord,
)
from .users import User


@cache.memoize()
def _MatchingRecord_is_valid(id):
    obj: MatchingRecord = db.session.query(MatchingRecord).filter_by(id=id).one()
    attempt: MatchingAttempt = obj.matching_attempt
    project: LiveProject = obj.project
    sel: SelectingStudent = obj.selector

    pclass: ProjectClass = project.config.project_class
    config: ProjectClassConfig = project.config

    errors = {}
    warnings = {}

    # 0. SUBMISSION PERIOD SHOULD IDENTIFY A VALID PERIOD FOR THIS PROJECT CLASS
    if obj.submission_period is None or obj.submission_period < 1:
        errors[("period", 0)] = "Invalid submission period ({n})".format(n=obj.submission_period)
        return False, errors, warnings

    if config.select_in_previous_cycle:
        pd: SubmissionPeriodDefinition = pclass.get_period(obj.submission_period)
        if pd is None:
            errors[("period", 0)] = "Missing record for submission period {n} (expected a period in range 1-{max})".format(
                n=obj.submission_period, max=pclass.number_submissions
            )
            return False, errors, warnings

        uses_supervisor = pclass.uses_supervisor
        uses_marker = pclass.uses_marker
        markers_needed = pd.number_markers

    else:
        pd: SubmissionPeriodRecord = config.get_period(obj.submission_period)
        if pd is None:
            errors[("period", 0)] = "Missing record for submission period {n} (expected a period in range 1-{max})".format(
                n=obj.submission_period, max=config.number_submissions
            )
            return False, errors, warnings

        uses_supervisor = config.uses_supervisor
        uses_marker = config.uses_marker
        markers_needed = pd.number_markers

    # supervisor_roles includes both ROLE_RESPONSIBLE_SUPERVISOR and plain ROLE_SUPERVISOR
    supervisor_roles: List[User] = obj.supervisor_roles
    marker_roles: List[User] = obj.marker_roles

    supervisor_ids: Set[int] = set(u.id for u in supervisor_roles)
    marker_ids: Set[int] = set(u.id for u in marker_roles)

    responsible_supervisor_ids: Set[int] = obj.responsible_supervisor_role_ids
    plain_supervisor_ids: Set[int] = obj.supervisor_only_role_ids

    # 1. ONLY SUPERVISION AND MARKING ROLES ARE MEANINGFUL IN A MATCHING
    valid_role_types = {
        MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
        MatchingRole.ROLE_SUPERVISOR,
        MatchingRole.ROLE_MARKER,
    }
    for r in obj.roles:
        if r.role not in valid_role_types:
            errors[("roles", r.id)] = 'Role "{role}" assigned to "{name}" is not valid in a matching'.format(
                role=r.role_as_str, name=r.user.name if r.user is not None else "<unknown>"
            )

    # 1A. SUPERVISOR AND MARKER ROLES SHOULD BE DISTINCT
    a = supervisor_ids.intersection(marker_ids)
    if len(a) > 0:
        errors[("basic", 0)] = "Some supervisor and marker roles coincide"

    supervisor_counts = {}
    marker_counts = {}

    supervisor_dict = {}
    marker_dict = {}

    for u in supervisor_roles:
        supervisor_dict[u.id] = u

        if u.id not in supervisor_counts:
            supervisor_counts[u.id] = 1
        else:
            supervisor_counts[u.id] += 1

    for u in marker_roles:
        marker_dict[u.id] = u

        if u.id not in marker_counts:
            marker_counts[u.id] = 1
        else:
            marker_counts[u.id] += 1

    if uses_supervisor:
        # 1B. AT LEAST ONE RESPONSIBLE SUPERVISOR SHOULD BE ASSIGNED
        if len(responsible_supervisor_ids) == 0:
            errors[("supervisors", 0)] = "No responsible supervisor is assigned for this project"

        # 1C. USUALLY THERE SHOULD BE JUST ONE RESPONSIBLE SUPERVISOR
        # (plain supervisor roles are optional extras and attract no warning)
        if len(responsible_supervisor_ids) > 1:
            warnings[("supervisors", 0)] = "There are {n} responsible supervisors assigned for this project".format(n=len(responsible_supervisor_ids))

        # 1D. NO-ONE SHOULD HOLD MORE THAN ONE SUPERVISION ROLE: this catches duplicate
        # assignments within either role type, and assignment as both responsible supervisor
        # and plain supervisor
        for u_id in supervisor_counts:
            count = supervisor_counts[u_id]
            if count > 1:
                user: User = supervisor_dict[u_id]

                if u_id in responsible_supervisor_ids and u_id in plain_supervisor_ids:
                    errors[("supervisors", ("duplicate", u_id))] = (
                        '"{name}" is assigned as both responsible supervisor and supervisor for this selector'.format(name=user.name)
                    )
                else:
                    errors[("supervisors", ("duplicate", u_id))] = 'Supervisor "{name}" is assigned {n} times for this selector'.format(
                        name=user.name, n=count
                    )
    else:
        # 1E. IF SUPERVISORS ARE NOT USED, THERE SHOULD BE NO SUPERVISION ROLES
        if len(supervisor_roles) > 0:
            warnings[("supervisors", "unused")] = "Supervision roles are assigned, but this project class does not use supervisor roles"

    if uses_marker:
        # 1F. THERE SHOULD BE THE RIGHT NUMBER OF ASSIGNED MARKERS
        if len(marker_ids) < markers_needed:
            errors[("markers", 0)] = "Fewer marker roles are assigned than expected for this project (assigned={assgn}, expected={exp})".format(
                assgn=len(marker_ids), exp=markers_needed
            )

        # 1G. WARN IF MORE MARKERS THAN EXPECTED ASSIGNED
        if len(marker_ids) > markers_needed:
            warnings[("markers", 0)] = "More marker roles are assigned than expected for this project (assigned={assgn}, expected={exp})".format(
                assgn=len(marker_ids), exp=markers_needed
            )

        # 1H. MARKERS SHOULD NOT BE MULTIPLY ASSIGNED TO THE SAME ROLE
        for u_id in marker_counts:
            count = marker_counts[u_id]
            if count > 1:
                user: User = marker_dict[u_id]

                errors[("markers", ("duplicate", u_id))] = 'Marker "{name}" is assigned {n} times for this selector'.format(name=user.name, n=count)
    else:
        # 1I. IF MARKERS ARE NOT USED, THERE SHOULD BE NO MARKER ROLES
        if len(marker_roles) > 0:
            warnings[("markers", "unused")] = "Marker roles are assigned, but this project class does not use marker roles"

    # 2. IF THERE IS A SUBMISSION LIST, WARN IF ASSIGNED PROJECT IS NOT ON THIS LIST, UNLESS IT IS AN ALTERNATIVE FOR ONE
    # OF THE SELECTED PROJECTED
    if sel.has_submission_list:
        if sel.project_rank(obj.project_id) is None:
            alt_data = sel.alternative_priority(obj.project_id)
            if alt_data is None:
                errors[("assignment", 0)] = "Assigned project did not appear in this selector's choices"
            else:
                alt_lp: LiveProject = alt_data["project"]
                alt_priority: int = alt_data["priority"]
                warnings[("assignment", 0)] = f'Assigned project is an alternative for "{alt_lp.name}" with priority={alt_priority}'

    # 3. IF THERE WAS AN ACCEPTED CUSTOM OFFER, WARN IF ASSIGNED SUPERVISOR IS NOT THE ONE IN THE OFFER
    if obj.selector.has_accepted_offers():
        # if there was an accepted offer for this period, it should agree with the one we have
        this_period = obj.period
        accepted_offers = obj.selector.accepted_offers(this_period).all()
        if len(accepted_offers) > 0:
            offer = accepted_offers[0]
            offer_project: LiveProject = offer.liveproject

            if offer_project is not None:
                if project.id != offer_project.id:
                    errors[("custom", 0)] = (
                        f'This selector accepted a custom offer for project "{offer_project.name}" in period "{this_period.display_name(config.year + 1)}", but their assigned project is different'
                    )

        # if there is only one submission period, and there is an accepted offer, it should match
        if get_count(pclass.periods) == 1:
            accepted_offers = obj.selector.accepted_offers().all()
            if len(accepted_offers) > 0:
                offer = accepted_offers[0]
                offer_project: LiveProject = offer.liveproject

                if offer_project is not None:
                    if project.id != offer_project.id:
                        errors[("custom", 0)] = (
                            f'This selector accepted a custom offer for project "{offer_project.name}", but their assigned project is different'
                        )

    # 4. ASSIGNED PROJECT MUST BE PART OF THE PROJECT CLASS
    if project.config_id != obj.selector.config_id:
        errors[("pclass", 0)] = "Assigned project does not belong to the correct class for this selector"

    # 5. STAFF WITH SUPERVISOR ROLES SHOULD BE ENROLLED FOR THIS PROJECT CLASS
    for u in supervisor_roles:
        if u.faculty_data is not None:
            enrolment: EnrollmentRecord = u.faculty_data.get_enrollment_record(pclass)
            if enrolment is None or enrolment.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
                errors[("enrolment", ("supervisor", u.id))] = (
                    '"{name}" has been assigned a supervision role, but is not currently enrolled for this project class'.format(name=u.name)
                )
        else:
            warnings[("enrolment", ("supervisor", u.id))] = '"{name}" has been assigned a supervision role, but is not a faculty member'.format(
                name=u.name
            )

    # 6. STAFF WITH MARKER ROLES SHOULD BE ENROLLED FOR THIS PROJECT CLASS
    for u in marker_roles:
        if u.faculty_data is not None:
            enrolment: EnrollmentRecord = u.faculty_data.get_enrollment_record(pclass)
            if enrolment is None or enrolment.marker_state != EnrollmentRecord.MARKER_ENROLLED:
                errors[("enrolment", ("marker", u.id))] = (
                    '"{name}" has been assigned a marking role, but is not currently enrolled for this project class'.format(name=u.name)
                )
        else:
            warnings[("enrolment", ("marker", u.id))] = '"{name}" has been assigned a marking role, but is not a faculty member'.format(name=u.name)

    # 7. PROJECT SHOULD NOT BE MULTIPLY ASSIGNED TO SAME SELECTOR BUT A DIFFERENT SUBMISSION PERIOD
    count = get_count(attempt.records.filter_by(selector_id=obj.selector_id, project_id=obj.project_id))

    if count != 1:
        # only refuse to validate if we are the first member of the multiplet;
        # this prevents errors being reported multiple times
        lo_rec = (
            attempt.records.filter_by(selector_id=obj.selector_id, project_id=obj.project_id).order_by(MatchingRecord.submission_period.asc()).first()
        )

        if lo_rec is not None and lo_rec.submission_period == obj.submission_period:
            errors[("assignment", 2)] = 'Project "{name}" is duplicated in multiple submission periods'.format(name=project.name)

    # 9. ASSIGNED MARKERS SHOULD USUALLY BE IN THE ASSESSOR POOL FOR THE ASSIGNED PROJECT
    # (unambiguous to use config here since #4 checks config agrees with obj.selector.config)
    # exceptions are allowed, so this is a warning rather than an error
    if uses_marker:
        for u in marker_roles:
            count = get_count(project.assessor_list_query.filter(FacultyData.id == u.id))

            if count != 1:
                warnings[("markers", ("pool", u.id))] = 'Assigned marker "{name}" is not in the assessor pool for the assigned project'.format(
                    name=u.name
                )

    if uses_supervisor:
        if not project.use_supervisor_pool:
            # 10. FOR ORDINARY PROJECTS, THE PROJECT OWNER SHOULD USUALLY BE THE RESPONSIBLE SUPERVISOR
            # exceptions are allowed, so this is a warning rather than an error
            if project.owner is not None and project.owner_id not in responsible_supervisor_ids:
                warnings[("supervisors", 2)] = 'Project owner "{name}" is not assigned as responsible supervisor'.format(name=project.owner.user.name)

        else:
            pool_ids: Set[int] = set(fd.id for fd in project.supervisors)

            # 11. FOR GENERIC PROJECTS, THE RESPONSIBLE SUPERVISOR SHOULD USUALLY BE IN THE SUPERVISION POOL
            # exceptions are allowed, so this is a warning rather than an error; plain supervisor
            # roles are unrestricted
            for u_id in responsible_supervisor_ids:
                if u_id not in pool_ids:
                    user: User = supervisor_dict[u_id]
                    warnings[("supervisors", ("pool", u_id))] = (
                        'Assigned responsible supervisor "{name}" is not in the supervision pool for the assigned project'.format(name=user.name)
                    )

            # 11A. FOR GENERIC PROJECTS, ASSIGNING THE PROJECT OWNER IS USUALLY A MISTAKE
            # (the owner is normally an administrator rather than a supervisor), but it is
            # allowed if needed, so this is a warning rather than an error
            if project.owner is not None and project.owner_id in supervisor_ids:
                warnings[("supervisors", "owner")] = (
                    'Project owner "{name}" has been assigned a supervision role; for projects using a supervision pool, '
                    "the owner is usually an administrator, so please check this assignment is intended".format(name=project.owner.user.name)
                )

    # 12. SELECTOR SHOULD BE MARKED FOR CONVERSION
    if not obj.selector.convert_to_submitter:
        # only refuse to validate if we are the first member of the multiplet
        lo_rec = attempt.records.filter_by(selector_id=obj.selector_id).order_by(MatchingRecord.submission_period.asc()).first()

        if lo_rec is not None and lo_rec.id == obj.id:
            warnings[("conversion", 1)] = 'Selector "{name}" is not marked for conversion to submitter, but is present in this matching'.format(
                name=obj.selector.student.user.name
            )

    # 13. THE PROJECT SHOULD NOT BE OVERASSIGNED
    if project.enforce_capacity and project.capacity is not None:
        for supv in supervisor_roles:
            count = get_count(
                attempt.records.filter(
                    MatchingRecord.project_id == project.id,
                    MatchingRecord.roles.any(
                        and_(
                            MatchingRole.role.in_(
                                [
                                    MatchingRole.ROLE_SUPERVISOR,
                                    MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                                ]
                            ),
                            MatchingRole.user_id == supv.id,
                        )
                    ),
                )
            )

            if count > project.capacity:
                # only refuse to validate if we are the first member of the multiplet
                lo_rec = (
                    attempt.records.filter(
                        MatchingRecord.project_id == project.id,
                        MatchingRecord.roles.any(
                            and_(
                                MatchingRole.role.in_(
                                    [
                                        MatchingRole.ROLE_SUPERVISOR,
                                        MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                                    ]
                                ),
                                MatchingRole.user_id == supv.id,
                            )
                        ),
                    )
                    .order_by(MatchingRecord.selector_id.asc())
                    .first()
                )

                if lo_rec is not None and lo_rec.id == obj.id:
                    errors[("overassigned", supv.id)] = (
                        'Project "{name}" has maximum capacity {max} but has been assigned to supervisor "{supv_name}" with {num} selectors'.format(
                            name=project.name,
                            max=project.capacity,
                            supv_name=supv.name,
                            num=count,
                        )
                    )

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


@cache.memoize()
def _MatchingAttempt_is_valid(id):
    obj: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).one()

    # there are several steps:
    #   1. Validate that each MatchingRecord is valid (marker is not supervisor,
    #      LiveProject is attached to right class, project capacity constraints
    #      are not violated). Record-level errors are fatal; record-level warnings
    #      are collected but do not invalidate the match.
    #   2. Validate that each selector has exactly one assignment per submission period.
    #      Gaps or duplicates are fatal errors.
    #   3. Validate that faculty CATS limits are respected.
    #      These are warnings, not errors (sometimes supervisors have to take more
    #      students than we would like, but they do all have to be supervised somehow).
    #      Enrolment violations detected during the same sweep are errors.
    errors = {}
    warnings = {}
    student_issues = False
    faculty_issues = False

    # IF MATCHING CALCULATION IS NOT FINISHED, NOTHING TO VALIDATE
    if not obj.finished:
        return True, student_issues, faculty_issues, errors, warnings

    # 1. EACH MATCHING RECORD SHOULD VALIDATE INDEPENDENTLY ACCORDING TO ITS OWN CRITERIA
    # harvest both errors and warnings, whether or not the record is valid overall: a record
    # that validates with warnings should still surface those warnings at attempt level
    for record in obj.records:
        record_is_valid = record.is_valid
        record_errors = record.filter_errors()
        record_warnings = record.filter_warnings()

        if record_is_valid is False and len(record_errors) == 0:
            current_app.logger.info(
                "** Internal inconsistency in response from _MatchingRecord_is_valid: record is invalid, but no errors reported "
                "(record_warnings = {y})".format(y=record_warnings)
            )

        for n, msg in enumerate(record_errors):
            errors[("basic", (record.id, n))] = "{name}/{abbv}: {msg}".format(
                msg=msg,
                name=record.selector.student.user.name,
                abbv=record.selector.config.project_class.abbreviation,
            )

        for n, msg in enumerate(record_warnings):
            warnings[("basic", (record.id, n))] = "{name}/{abbv}: {msg}".format(
                msg=msg,
                name=record.selector.student.user.name,
                abbv=record.selector.config.project_class.abbreviation,
            )

        if len(record_errors) > 0:
            student_issues = True

    # 2. EACH SELECTOR SHOULD HAVE EXACTLY ONE ASSIGNMENT PER SUBMISSION PERIOD
    for sel in obj.selector_list_query().all():
        sel_config: ProjectClassConfig = sel.config

        if sel_config.select_in_previous_cycle:
            expected_periods = sel_config.project_class.number_submissions
        else:
            expected_periods = sel_config.number_submissions

        periods = [rec.submission_period for rec in obj.records.filter_by(selector_id=sel.id)]

        missing = sorted(set(range(1, expected_periods + 1)) - set(periods))
        if len(missing) > 0:
            errors[("coverage", sel.id)] = "{name}/{abbv}: No assignment for submission period{plural} {missing}".format(
                name=sel.student.user.name,
                abbv=sel_config.project_class.abbreviation,
                plural="s" if len(missing) > 1 else "",
                missing=", ".join(str(p) for p in missing),
            )
            student_issues = True

        duplicated = sorted(set(p for p in periods if periods.count(p) > 1))
        if len(duplicated) > 0:
            errors[("coverage_dup", sel.id)] = "{name}/{abbv}: Multiple assignments for submission period{plural} {dup}".format(
                name=sel.student.user.name,
                abbv=sel_config.project_class.abbreviation,
                plural="s" if len(duplicated) > 1 else "",
                dup=", ".join(str(p) for p in duplicated),
            )
            student_issues = True

    # 3. EACH PARTICIPATING FACULTY MEMBER SHOULD NOT BE OVERASSIGNED, EITHER AS MARKER OR SUPERVISOR
    # CATS-limit violations are warnings; enrolment violations are errors
    query = obj.faculty_list_query()
    for fac in query.all():
        data = obj.is_supervisor_overassigned(fac, include_matches=True)
        for n, msg in enumerate(data["errors"]):
            errors[("supervising", (fac.id, n))] = msg
            faculty_issues = True
        for n, msg in enumerate(data["warnings"]):
            warnings[("supervising", (fac.id, n))] = msg

        data = obj.is_marker_overassigned(fac, include_matches=True)
        for n, msg in enumerate(data["errors"]):
            errors[("marking", (fac.id, n))] = msg
            faculty_issues = True
        for n, msg in enumerate(data["warnings"]):
            warnings[("marking", (fac.id, n))] = msg

        # 4. FOR EACH INCLUDED PROJECT CLASS, FACULTY ASSIGNMENTS SHOULD RESPECT ANY CUSTOM CATS LIMITS
        # these are also CATS-limit violations, so are warnings rather than errors
        for config in obj.config_members:
            config: ProjectClassConfig
            rec: EnrollmentRecord = fac.get_enrollment_record(config.pclass_id)

            if rec is not None:
                sup, mark = obj.get_faculty_CATS(fac, pclass_id=config.pclass_id)

                if rec.CATS_supervision is not None and sup > rec.CATS_supervision:
                    warnings[("custom_sup", fac.id)] = "{pclass} assignment to {name} violates their custom supervising CATS limit = {n}".format(
                        pclass=config.name,
                        name=fac.user.name,
                        n=rec.CATS_supervision,
                    )

                if rec.CATS_marking is not None and mark > rec.CATS_marking:
                    warnings[("custom_mark", fac.id)] = "{pclass} assignment to {name} violates their custom marking CATS limit = {n}".format(
                        pclass=config.name, name=fac.user.name, n=rec.CATS_marking
                    )

                # UPDATE MODERATE CATS

    is_valid = (not student_issues) and (not faculty_issues)

    if not is_valid and len(errors) == 0:
        current_app.logger.info("** Internal inconsistency in _MatchingAttempt_is_valid: not valid, but len(errors) == 0")

    return is_valid, student_issues, faculty_issues, errors, warnings
