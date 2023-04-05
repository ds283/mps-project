#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import itertools
from datetime import datetime
from os import path
from shutil import copyfile

import pulp
import pulp.apis as pulp_apis
from celery import group, chain
from celery.exceptions import Ignore
from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import MatchingAttempt, TaskRecord, LiveProject, SelectingStudent, \
    User, EnrollmentRecord, MatchingRecord, SelectionRecord, ProjectClass, GeneratedAsset, MatchingEnumeration, \
    TemporaryAsset, FacultyData, ProjectClassConfig, SubmissionRecord, SubmissionPeriodRecord, MatchingRole, \
    SubmissionPeriodDefinition
from ..shared.asset_tools import make_generated_asset_filename, canonical_temporary_asset_filename, \
    canonical_generated_asset_filename
from ..shared.sqlalchemy import get_count
from ..shared.timer import Timer
from ..task_queue import progress_update, register_task


FALLBACK_DEFAULT_SUPERVISOR_CATS = 35
FALLBACK_DEFAULT_MARKER_CATS = 3
FALLBACK_DEFAULT_MODERATOR_CATS = 3

# should be a large enough number that capacity for a project is effectively unbounded
UNBOUNDED_SUPERVISING_CAPACITY = 100
UNBOUNDED_MARKING_CAPACITY = 100


def _find_mean_project_CATS(configs):
    CATS_total = 0
    number = 0

    for config in configs:
        if config.uses_supervisor and config.CATS_supervision is not None:
            CATS_total += config.CATS_supervision
            number += 1

    return float(CATS_total)/number


def _min(a, b):
    if a is None and b is None:
        return None

    if a is None:
        return b

    if b is None:
        return a

    return a if a <= b else b


def _enumerate_selectors(record, configs, read_serialized=False):
    """
    Build a list of SelectingStudents who belong to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute assignment multiplicity for each selector, ie. how many projects they should be
    assigned (eg. FYP = 1 but MPP = 2 since projects only last one term)
    :param record:
    :param configs:
    :return:
    """
    if read_serialized:
        return _enumerate_selectors_serialized(record)

    return _enumerate_selectors_primary(configs, include_only_submitted=record.include_only_submitted)


def _enumerate_selectors_serialized(record):
    sel_to_number = {}
    number_to_sel = {}

    multiplicity = {}

    selector_dict = {}

    record_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.SELECTOR, matching_id=record.id).subquery()
    records = db.session.query(record_data.c.enumeration, SelectingStudent) \
        .select_from(SelectingStudent) \
        .join(record_data, record_data.c.key == SelectingStudent.id) \
        .order_by(record_data.c.enumeration.asc()).all()

    for n, sel in records:
        n: int
        sel: SelectingStudent

        sel_to_number[sel.id] = n
        number_to_sel[n] = sel.id

        submissions = sel.config.submissions
        multiplicity[n] = submissions if submissions >= 1 else 1

        selector_dict[n] = sel

    return n+1, sel_to_number, number_to_sel, multiplicity, selector_dict


def _enumerate_selectors_primary(configs, include_only_submitted=False):
    number = 0
    sel_to_number = {}
    number_to_sel = {}

    multiplicity = {}

    selector_dict = {}

    for config in configs:
        config: ProjectClassConfig
        # get SelectingStudent instances that are not retired and belong to this config instance

        # however, we need to remember that for projects marked 'selection_open_to_all',
        # we should interpret failure to submit choices as an indication that the selector
        # doesn't wish to participate.
        # So, in this case, we shouldn't forward the selector for matching

        # also, if the project automatically rolls over supervisor assignments,
        # then failure to submit choices indicates that the selector is happy with their
        # existing assignment.
        # So in this case too, we shouldn't forward the selector for matching

        opt_in_type = config.selection_open_to_all
        enroll_previous_year = config.auto_enroll_years == ProjectClass.AUTO_ENROLL_FIRST_YEAR
        enroll_any_year = config.auto_enroll_years == ProjectClass.AUTO_ENROLL_ALL_YEARS
        carryover = config.supervisor_carryover

        selectors = db.session.query(SelectingStudent) \
            .filter_by(retired=False, config_id=config.id, convert_to_submitter=True).all()

        print(' :: length of raw selectors list for "{name}" '
              '(config_id={y}) = {n}'.format(name=config.project_class.name, y=config.id, n=len(selectors)))

        for sel in selectors:
            sel: SelectingStudent

            # decide what to do with this selector
            attach = False

            if sel.has_submitted:
                # always count selectors who have submitted choices or accepted custom offers
                attach = True

            else:
                if include_only_submitted:
                    attach = False

                else:
                    if sel.academic_year is not None and not sel.has_graduated:
                        if opt_in_type and \
                                ((enroll_previous_year and sel.academic_year == config.start_year - (1 if config.select_in_previous_cycle else 0)) or
                                 (enroll_any_year and config.start_year <= sel.academic_year < config.start_year + config.extent)):
                            # interpret failure to submit as lack of interest; no need to generate a match
                            attach = False

                        elif carryover and config.start_year <= sel.academic_year < config.start_year + config.extent:
                            # interpret failure to submit as evidence student is happy with existing allocation

                            # TODO: in reality there is some overlap with the previous case, if both carryover and
                            #  opt_in_type are set. In such a case, if a student has a previous SubmittingStudent instance
                            #  and they don't respond, they probably mean to carryover. If they don't have a SubmittingStudent
                            #  instance then they probably mean to indicate that they don't want to participate.
                            #  I can't see any way to tell the difference using only data available in this method, but also
                            #  it doesn't seem to be critical
                            attach = False

                        else:
                            # otherwise, assume a match should be generated
                            attach = True

            if attach:
                sel_to_number[sel.id] = number
                number_to_sel[number] = sel.id

                # multiplicity determines how many project assignments we need to generate for this selector,
                # which is usually one per submission period
                # TODO: account for submission periods with different numbers of markers, and submission
                #  periods where no project needs to be assigned, e.g. the Data Science MSc with the project
                #  proposal submission period
                submissions = config.submissions
                multiplicity[number] = submissions if submissions >= 1 else 1

                selector_dict[number] = sel

                number += 1

    return number, sel_to_number, number_to_sel, multiplicity, selector_dict


def _enumerate_liveprojects(record, configs, read_serialized=False):
    """
    Build a list of LiveProjects belonging to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute CATS values for supervising and marking each project
    :param record:
    :param configs:
    :return:
    """
    if read_serialized:
        return _enumerate_liveprojects_serialized(record)

    return _enumerate_liveprojects_primary(configs)


def _enumerate_liveprojects_serialized(record):
    lp_to_number = {}
    number_to_lp = {}

    CATS_supervisor = {}
    CATS_marker = {}

    capacity = {}

    project_dict = {}           # mapping from enumerated number to LiveProject instance
    project_group_dict = {}     # mapping from config.id to list of LiveProject.ids associated with it

    record_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.LIVEPROJECT, matching_id=record.id).subquery()
    records = db.session.query(record_data.c.enumeration, LiveProject) \
        .select_from(LiveProject) \
        .join(record_data, record_data.c.key == LiveProject.id) \
        .order_by(record_data.c.enumeration.asc()).all()

    for n, lp in records:
        n: int
        lp: LiveProject

        lp_to_number[lp.id] = n
        number_to_lp[n] = lp.id

        # differences between ordinary/generic projects (if any) are handled internally
        # to LiveProject, so we need only use the LiveProject.CATS_supervision and
        # LiveProject.CATS_marking properties
        sup = lp.CATS_supervision
        mk = lp.CATS_marking

        CATS_supervisor[n] = sup if sup is not None else FALLBACK_DEFAULT_SUPERVISOR_CATS
        CATS_marker[n] = mk if mk is not None else FALLBACK_DEFAULT_MARKER_CATS

        capacity[n] = lp.capacity if (lp.enforce_capacity and
                                      lp.capacity is not None and lp.capacity > 0) else UNBOUNDED_SUPERVISING_CAPACITY

        project_dict[n] = lp

        # UPDATE MODERATE CATS

    group_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.LIVEPROJECT_GROUP, matching_id=record.id).all()

    for record in group_data:
        record: MatchingEnumeration

        if record.key not in project_group_dict:
            project_group_dict[record.key] = []

        project_group_dict[record.key].append(record.enumeration)

    return n+1, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, project_dict, project_group_dict


def _enumerate_liveprojects_primary(configs):
    number = 0
    lp_to_number = {}
    number_to_lp = {}

    CATS_supervisor = {}
    CATS_marker = {}

    capacity = {}

    project_dict = {}           # mapping from enumerated number to LiveProject instance
    project_group_dict = {}     # mapping from config.id to list of LiveProject.ids associated with it

    for config in configs:
        # get LiveProject instances that belong to this config instance and are associated with
        # a supervisor who is still enrolled
        # (eg. enrolment status may have changed since the projects went live)
        projects = db.session.query(LiveProject).filter_by(config_id=config.id) \
            .join(ProjectClassConfig, ProjectClassConfig.id == LiveProject.config_id) \
            .join(User, User.id == LiveProject.owner_id, isouter=True) \
            .join(FacultyData, FacultyData.id == LiveProject.owner_id, isouter=True) \
            .join(EnrollmentRecord, EnrollmentRecord.owner_id == LiveProject.owner_id, isouter=True) \
            .filter(or_(LiveProject.generic == True,
                        and_(LiveProject.generic == False,
                             User.active == True,
                             FacultyData.id != None,
                             EnrollmentRecord.pclass_id == ProjectClassConfig.pclass_id,
                             EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED))).all()

        project_group_dict[config.id] = []

        for item in projects:
            item: LiveProject

            lp_to_number[item.id] = number
            number_to_lp[number] = item.id

            sup = item.CATS_supervision
            mk = item.CATS_marking
            CATS_supervisor[number] = sup if sup is not None else FALLBACK_DEFAULT_SUPERVISOR_CATS
            CATS_marker[number] = mk if mk is not None else FALLBACK_DEFAULT_MARKER_CATS

            capacity[number] = item.capacity if (item.enforce_capacity and
                                                 item.capacity is not None and item.capacity > 0) else UNBOUNDED_SUPERVISING_CAPACITY

            project_dict[number] = item
            project_group_dict[config.id].append(number)

            number += 1

    return number, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, project_dict, project_group_dict


def _enumerate_supervising_faculty(record, configs, read_serialized=False):
    """
    Build a list of active, enrolled supervising faculty belonging to projects that
    participate in automatic matching, and assign them to consecutive numbers beginning at zero
    :param record:
    :param configs:
    :return:
    """
    if read_serialized:
        return _enumerate_supervising_faculty_serialized(record)

    return _enumerate_supervising_faculty_primary(configs)


def _enumerate_supervising_faculty_serialized(record):
    fac_to_number = {}
    number_to_fac = {}

    limit = {}                  # map from faculty number to global supervision CATS limit
    config_limits = {}          # map from config.id to (map from faculty number to local supervision CATS limit)

    fac_dict = {}

    # stored ids and primary keys refer to FacultyData instances, not EnrollmentRecord instances
    record_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.SUPERVISOR, matching_id=record.id).subquery()
    records = db.session.query(record_data.c.enumeration, FacultyData) \
        .select_from(FacultyData) \
        .join(record_data, record_data.c.key == FacultyData.id) \
        .order_by(record_data.c.enumeration.asc()).all()

    for n, fac in records:
        n: int
        fac: FacultyData

        fac_to_number[fac.id] = n
        number_to_fac[n] = fac.id

        lim = fac.CATS_supervision
        limit[n] = lim if lim is not None and lim > 0 else 0

        fac_dict[n] = fac

    limit_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.SUPERVISOR_LIMITS, matching_id=record.id).all()

    for record in limit_data:
        record: MatchingEnumeration

        config_id = record.key
        fac_number = record.enumeration
        limit = record.key2

        if config_id not in config_limits:
            config_limits[config_id] = {}

        config_limits[config_id][fac_number] = limit

    return n+1, fac_to_number, number_to_fac, limit, fac_dict, config_limits


def _enumerate_supervising_faculty_primary(configs):
    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}                  # map from faculty number to global supervision CATS limit
    config_limits = {}          # map from config.id to (map from faculty number to local supervision CATS limit)

    fac_dict = {}

    for config in configs:
        # get EnrollmentRecord instances for this project class
        records = db.session.query(EnrollmentRecord) \
            .filter_by(pclass_id=config.pclass_id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED) \
            .join(User, User.id == EnrollmentRecord.owner_id) \
            .filter(User.active).all()

        config_limits[config.id] = {}

        # what gets written into our tables are links to the corresponding FacultyData instances
        for rec in records:
            rec: EnrollmentRecord
            fac: FacultyData = rec.owner

            if fac.id not in fac_to_number:
                fac_to_number[fac.id] = number
                number_to_fac[number] = fac.id

                lim = fac.CATS_supervision
                limit[number] = lim if lim is not None and lim > 0 else 0

                fac_dict[number] = fac

                number += 1

            if rec.CATS_supervision is not None:
                config_limits[config.id][fac_to_number[fac.id]] = rec.CATS_supervision

    return number, fac_to_number, number_to_fac, limit, fac_dict, config_limits


def _enumerate_marking_faculty(record, configs, read_serialized=False):
    """
    Build a list of active, enrolled 2nd-marking faculty belonging to projects that
    participate in automatic matching, and assign them to consecutive numbers beginning at zero
    :param record:
    :param configs:
    :return:
    """
    if read_serialized:
        return _enumerate_marking_faculty_serialized(record)

    return _enumerate_marking_faculty_primary(configs)


def _enumerate_marking_faculty_serialized(record):
    fac_to_number = {}
    number_to_fac = {}

    limit = {}                  # map from faculty number to global marking CATS limit
    config_limits = {}          # map from config.id to (map from faculty number to local marking CATS limit)

    fac_dict = {}

    # stored ids and primary keys refer to FacultyData instances, not EnrollmentRecord instances
    record_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.MARKER, matching_id=record.id).subquery()
    records = db.session.query(record_data.c.enumeration, FacultyData) \
        .select_from(FacultyData) \
        .join(record_data, record_data.c.key == FacultyData.id) \
        .order_by(record_data.c.enumeration.asc()).all()

    for n, fac in records:
        n: int
        fac: FacultyData

        fac_to_number[fac.id] = n
        number_to_fac[n] = fac.id

        lim = fac.CATS_marking
        limit[n] = lim if lim is not None and lim > 0 else 0

        fac_dict[n] = fac

    limit_data = db.session.query(MatchingEnumeration) \
        .filter_by(category=MatchingEnumeration.MARKER_LIMITS, matching_id=record.id).all()

    for record in limit_data:
        record: MatchingEnumeration

        config_id = record.key
        fac_number = record.enumeration
        limit = record.key2

        if config_id not in config_limits:
            config_limits[config_id] = {}

        config_limits[config_id][fac_number] = limit

    return n+1, fac_to_number, number_to_fac, limit, fac_dict, config_limits


def _enumerate_marking_faculty_primary(configs):
    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}                  # map from faculty number to global marking CATS limit
    config_limits = {}          # map from config.id to (map from faculty number to local marking CATS limit)

    fac_dict = {}

    for config in configs:
        # get EnrollmentRecord instances for this project class
        records = db.session.query(EnrollmentRecord) \
            .filter_by(pclass_id=config.pclass_id, marker_state=EnrollmentRecord.MARKER_ENROLLED) \
            .join(User, User.id == EnrollmentRecord.owner_id) \
            .filter(User.active).all()

        config_limits[config.id] = {}

        # what gets written into our tables are links to the corresponding FacultyData instances
        for rec in records:
            rec: EnrollmentRecord
            fac: FacultyData = rec.owner

            if fac.id not in fac_to_number:
                fac_to_number[fac.id] = number
                number_to_fac[number] = fac.id

                lim = fac.CATS_marking
                limit[number] = lim if lim is not None and lim > 0 else 0

                fac_dict[number] = fac

                number += 1

            if rec.CATS_marking is not None:
                config_limits[config.id][fac_to_number[fac.id]] = rec.CATS_marking

    return number, fac_to_number, number_to_fac, limit, fac_dict, config_limits


def _build_ranking_matrix(number_sel, sel_dict, number_lp, lp_to_number, lp_dict, record: MatchingAttempt):
    """
    Construct a dictionary mapping from (student, project) pairs to the rank assigned
    to that project by the student.
    Also build a weighting matrix that accounts for other factors we wish to weight
    in the assignment, such as degree programme or convenor-provided hints
    :param lp_to_number:
    :param number_sel:
    :param sel_dict:
    :param number_lp:
    :param lp_dict:
    :return:
    """

    R = {}          # R is ranking matrix. Accounts for Forbid hints.
    W = {}          # W is weights matrix. Accounts for encourage & discourage hints, programme bias and bookmark bias
    cstr = set()    # cstr is a set of (student, project) pairs that will be converted into Require hints

    ignore_programme_prefs = record.ignore_programme_prefs
    programme_bias = float(record.programme_bias) if record.programme_bias is not None else 1.0
    bookmark_bias = float(record.bookmark_bias) if record.bookmark_bias is not None else 1.0

    use_hints = record.use_hints
    require_to_encourage = record.require_to_encourage
    forbid_to_discourage = record.forbid_to_discourage

    encourage_bias = float(record.encourage_bias)
    discourage_bias = float(record.discourage_bias)
    strong_encourage_bias = float(record.strong_encourage_bias)
    strong_discourage_bias = float(record.strong_discourage_bias)

    for i in range(0, number_sel):
        sel = sel_dict[i]

        ranks = {}
        weights = {}
        require = set()

        if sel.has_accepted_offer:
            offer = sel.accepted_offer
            project = offer.liveproject

            if project.id in lp_to_number:
                ranks[project.id] = 1
                require.add(project.id)
            else:
                raise RuntimeError('Could not assign custom offer to selector "{name}" because target LiveProject '
                                   'does not exist'.format(name=sel.student.user.name))

        elif sel.has_submission_list:
            valid_projects = 0

            for item in sel.ordered_selections:
                if item.liveproject_id in lp_to_number:
                    valid_projects += 1

                    hint = item.hint

                    if not use_hints or forbid_to_discourage or hint != SelectionRecord.SELECTION_HINT_FORBID:
                        ranks[item.liveproject_id] = item.rank

                    w = 1.0
                    if item.converted_from_bookmark:
                        w *= bookmark_bias
                    if use_hints:
                        if hint == SelectionRecord.SELECTION_HINT_ENCOURAGE:
                            w *= encourage_bias
                        elif hint == SelectionRecord.SELECTION_HINT_DISCOURAGE:
                            w *= discourage_bias
                        elif hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG \
                                or (require_to_encourage and hint == SelectionRecord.SELECTION_HINT_REQUIRE):
                            w *= strong_encourage_bias
                        elif hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG \
                                or (forbid_to_discourage and hint == SelectionRecord.SELECTION_HINT_FORBID):
                            w *= strong_discourage_bias

                    weights[item.liveproject_id] = w

                    if use_hints and not require_to_encourage and hint == SelectionRecord.SELECTION_HINT_REQUIRE:
                        require.add(item.liveproject_id)

            if valid_projects == 0:
                raise RuntimeError('Could not build rank matrix for selector "{name}" because no LiveProjects '
                                   'on their preference list exist'.format(name=sel.student.user.name))

        else:
            # no ranking data, so rank all LiveProjects in the right project class equal to 1
            for k in lp_dict:
                proj = lp_dict[k]

                if sel.config_id == proj.config_id:
                    ranks[proj.id] = 1

        for j in range(0, number_lp):
            idx = (i, j)
            proj = lp_dict[j]

            val = True

            if proj.id in ranks:
                R[idx] = ranks[proj.id]
            else:
                # if not ranked, prevent solver from making this choice
                R[idx] = 0
                val = False

            # compute weight for this (student, project) combination
            if proj.id in weights:
                w = weights[proj.id]
            else:
                w = 0 if val is False else 1.0

            # check whether this project has a preference for the degree programme associated with the current selector
            if not ignore_programme_prefs and proj.satisfies_preferences(sel):
                w *= programme_bias

            W[idx] = w

            if proj.id in require:
                cstr.add(idx)

    return R, W, cstr


def _build_marking_matrix(number_mark, mark_dict, number_projects, project_dict, max_multiplicity):
    """
    Construct a dictionary mapping from (marking_faculty, project) pairs to the maximum multiplicity
    allowed for each marking assignment
    :param number_faculty:
    :param faculty_dict:
    :param number_project:
    :param project_dict:
    :param max_multiplicity:
    :return:
    """
    M = {}

    # scan through faculty who are available for marking
    for i in range(0, number_mark):
        fac: FacultyData = mark_dict[i]

        # scan through available projects
        for j in range(0, number_projects):
            idx = (i, j)
            proj: LiveProject = project_dict[j]

            # does the project class for this project use markers?
            if proj.config.uses_marker:
                # check whether marker i is in the assessor list for project j
                count = get_count(proj.assessor_list_query.filter(FacultyData.id == fac.id))

                if count == 1:
                    M[idx] = max_multiplicity
                elif count == 0:
                    M[idx] = 0
                else:
                    errmsg = 'Inconsistent number of second markers in match to LiveProject: ' \
                             'fac={fname}, proj={pname}, matches={c}, ' \
                             'LiveProject.id={lpid}, ' \
                             'FacultyData.id={fid}'.format(fname=fac.user.name, pname=proj.name, c=count,
                                                           lpid=proj.id, fid=fac.id)

                    print('!! {msg}'.format(msg=errmsg))
                    print('!! LiveProject Assessor List')
                    for f in proj.assessor_list:
                        f: FacultyData
                        print('!! - {name} id={fid}'.format(name=f.user.name, fid=f.id))

                    raise RuntimeError(errmsg)

            else:
                M[idx] = 0

    # how many markers do we actually have to assign for a project of type j? This depends how many
    # markers are used in the different submission periods associated with the project class that owns j.
    # We don't know which submission period the project will be assigned to, so have to allocate enough markers
    # for the largest possible
    marker_valence = {}

    for j in range(0, number_projects):
        proj: LiveProject = project_dict[j]
        config: ProjectClassConfig = proj.config
        pclass: ProjectClass = config.project_class

        markers_needed = 0

        # if selection in previous cycle, use period definitions from the main class
        if config.select_in_previous_cycle:
            for pd in pclass.periods:
                pd: SubmissionPeriodDefinition
                if pd.number_markers > markers_needed:
                    markers_needed = pd.number_markers

        # otherwise, use period records from the currently running ProjectClassConfig
        else:
            for pd in config.periods:
                pd: SubmissionPeriodRecord
                if pd.number_markers > markers_needed:
                    markers_needed = pd.number_markers

        marker_valence[j] = markers_needed


    return M, marker_valence


def _build_project_supervisor_matrix(number_proj, proj_dict, number_sup, sup_dict):
    """
    Construct a dictionary mapping from (supervising_faculty, project) pairs to:
      0 if this supervisor does not supervise the given project
      1 if this supervisor does supervise the given project
    :param number_proj:
    :param proj_dict:
    :param number_sup:
    :param sup_dict:
    :return:
    """
    P = {}

    for i in range(number_proj):
        proj: LiveProject = proj_dict[i]

        for j in range(number_sup):
            idx = (j, i)

            fac: FacultyData = sup_dict[j]

            # if project is of generic/group type, then any member of the assessor pool is an allowed
            # supervisor
            if proj.generic or proj.owner is None:
                count = get_count(proj.supervisor_list_query.filter(FacultyData.id == fac.id))
                if count == 1:
                    P[idx] = 1
                elif count == 0:
                    P[idx] = 0
                else:
                    errmsg = 'Inconsistent number of possible supervisors for group project in match to LiveProject: ' \
                             'fac={fname}, proj={pname}, matches={c}, ' \
                             'LiveProject.id={lpid}, ' \
                             'FacultyData.id={fid}'.format(fname=fac.user.name, pname=proj.name, c=count,
                                                           lpid=proj.id, fid=fac.id)

                    print('!! {msg}'.format(msg=errmsg))
                    print('!! LiveProject Assessor List')
                    for f in proj.assessor_list:
                        f: FacultyData
                        print('!! - {name} id={fid}'.format(name=f.user.name, fid=f.id))

                    raise RuntimeError(errmsg)

            # otherwise, only the project supervisor is an allowed supervisor
            # TODO: in future, possibly allow more general supervisory arrangements
            else:
                if proj.owner_id == fac.id:
                    P[idx] = 1
                else:
                    P[idx] = 0

    return P


def _compute_existing_sup_CATS(record, fac_data):
    CATS = 0

    for match in record.include_matches:
        sup, mark, mod = match.get_faculty_CATS(fac_data.id)
        CATS += sup

    return CATS


def _compute_existing_mark_CATS(record, fac_data):
    CATS = 0

    for match in record.include_matches:
        sup, mark, mod = match.get_faculty_CATS(fac_data.id)
        CATS += mark

    return CATS


def _enumerate_missing_markers(self, config, task_id, user: User):
    mark_dict = {}
    mark_CATS_dict = {}
    submit_dict = {}

    inverse_mark_dict = {}
    inverse_submit_dict = {}

    number_markers = 0
    number_submitters = 0

    progress_update(task_id, TaskRecord.RUNNING, 10, "Enumerating submission records with missing records...",
                    autocommit=True)

    # loop through all submissions in all periods to capture all those with missing markers
    for period in config.periods:
        period: SubmissionRecord

        for sub in period.submissions:
            sub: SubmissionRecord

            # do nothing if project not assigned (no assessor pool)
            if sub.project is None:
                continue

            # do nothing if marker already assigned
            if sub.marker is not None:
                continue

            # store this submission record in the submitter dictionary
            if sub in inverse_submit_dict:
                raise RuntimeError("Non-unique submitter when enumerating missing markers")

            submit_dict[number_submitters] = sub
            inverse_submit_dict[sub] = number_submitters
            number_submitters += 1

            # loop through markers in the assessor pool for this project
            # note - LiveProject.assessor_list will only return a list of assessors who are
            # currently enrolled as active markers
            assessors = sub.project.assessor_list
            if len(assessors) == 0:
                progress_update(task_id, TaskRecord.FAILURE, 100, 'Failed because LiveProject "{name}" has no '
                                                                  'active assessors'.format(name=sub.project.name),
                                autocommit=True)
                user.post_message('Failed to populate markers because LiveProject "{name}" has no acive '
                                  'assessors.'.format(name=sub.project.name), 'error', autocommit=True)
                self.update_state('FAILURE', meta='LiveProject did not have active assessors')
                raise Ignore()

            for marker in assessors:
                marker: FacultyData

                if marker not in inverse_mark_dict:
                    mark_dict[number_markers] = marker
                    inverse_mark_dict[marker] = number_markers
                    mark_CATS_dict[number_markers] = marker.CATS_assignment(config)
                    number_markers += 1

    return mark_dict, inverse_mark_dict, submit_dict, inverse_submit_dict, mark_CATS_dict


def _floatify(item):
    if item is None:
        return None

    if isinstance(item, float):
        return item

    return float(item)


def _create_PuLP_problem(R, M, marker_valence, W, P, cstr, base_X, base_Y, base_S, has_base_match, force_base,
                         CATS_supervisor, CATS_marker, capacity, sup_limits, sup_pclass_limits, mark_limits,
                         mark_pclass_limits, multiplicity, number_lp, number_mark, number_sel, number_sup, record,
                         sel_dict, sup_dict, mark_dict, lp_dict, lp_group_dict, sup_only_numbers, mark_only_numbers,
                         sup_and_mark_numbers, mean_CATS_per_project):
    """
    Generate a PuLP problem to find an optimal assignment of projects+markers to students
    :param marker_valence:
    :param force_base:
    :param old_S:
    """

    levelling_bias = _floatify(record.levelling_bias)
    intra_group_tension = _floatify(record.intra_group_tension)
    supervising_pressure = _floatify(record.supervising_pressure)
    marking_pressure = _floatify(record.marking_pressure)
    CATS_violation_penalty = _floatify(record.CATS_violation_penalty)
    no_assignment_penalty = _floatify(record.no_assignment_penalty)
    base_bias = _floatify(record.base_bias)

    mean_CATS_per_project = _floatify(mean_CATS_per_project)

    # generate PuLP problem
    prob: pulp.LpProblem = pulp.LpProblem(record.name, pulp.LpMaximize)

    # generate decision variables for project assignment matrix
    # the indices are (selector, project) and the entries of the matrix are either 0 or 1,
    # 0 = selector not assigned to project
    # 1 = selector assigned to project
    X = pulp.LpVariable.dicts("X", itertools.product(range(number_sel), range(number_lp)), cat=pulp.LpBinary)

    # generate decision variables for supervisor assignment matrix
    # the indices are (supervisor, project) and the entries of the matrix are integers representing
    # the number of times a supervisor has been assigned to a project (depending on the number of students
    # who are assigned)
    # value = number of times assigned to this project. Can't be negative.
    S = pulp.LpVariable.dicts("S", itertools.product(range(number_sup), range(number_lp)),
                              cat=pulp.LpInteger, lowBound=0)

    # boolean version of S indicating whether a supervisor has any assignments to a particular project
    ss = pulp.LpVariable.dicts("ss", itertools.product(range(number_sup), range(number_lp)),
                               cat=pulp.LpBinary)

    # generate decision variables for marker assignment matrix
    # the indices are (marker, project) and the entries of the matrix are integers, because
    # the same marker can be assigned to mark more than one instance of a particular project (e.g. different
    # students submitting reports for the same project).
    # value = number of times assigned to this project. Can't be negative.
    Y = pulp.LpVariable.dicts("Y", itertools.product(range(number_mark), range(number_lp)),
                              cat=pulp.LpInteger, lowBound=0)

    ## boolean version of Y indicating whether a marker has any assignments to a particular project
    yy = pulp.LpVariable.dicts("yy", itertools.product(range(number_mark), range(number_lp)),
                               cat=pulp.LpBinary)

    # generate auxiliary variables that track whether a given supervisor has any projects assigned or not
    # 0 = none assigned
    # 1 = at least one assigned (obtained by biasing the optimizer to produce this from the objective function)
    Z = pulp.LpVariable.dicts("Z", range(number_sup), cat=pulp.LpBinary)

    # generate auxiliary variables that track whether a given project has any students assigned or not
    # 0 = none assigned
    # 1 = at least one assigned
    Q = pulp.LpVariable.dicts("Q", range(number_lp), cat=pulp.LpBinary)

    # to implement workload balancing we use pairs of continuous variables that relax
    # to the maximum and minimum workload for each faculty group:
    # supervisors+marks, supervisors only, markers only

    # the objective function contains a linear potential that tensions the top and
    # bottom workload in each band against each other, so the solution is rewarded for
    # balancing workloads within each group

    # we also tension the workload between groups, so that the workload of no one group
    # is pushed too far away from the others, subject to existing CATS caps
    supMax = pulp.LpVariable("sMax", lowBound=0, cat=pulp.LpContinuous)
    supMin = pulp.LpVariable("sMin", lowBound=0, cat=pulp.LpContinuous)

    markMax = pulp.LpVariable("mMax", lowBound=0, cat=pulp.LpContinuous)
    markMin = pulp.LpVariable("mMin", lowBound=0, cat=pulp.LpContinuous)

    supMarkMax = pulp.LpVariable("smMax", lowBound=0, cat=pulp.LpContinuous)
    supMarkMin = pulp.LpVariable("smMin", lowBound=0, cat=pulp.LpContinuous)

    globalMax = pulp.LpVariable("gMax", lowBound=0, cat=pulp.LpContinuous)
    globalMin = pulp.LpVariable("gMin", lowBound=0, cat=pulp.LpContinuous)

    # finally, to spread second-marking tasks fairly among a pool of faculty, where any
    # particular assignment won't significantly affect markMax/markMin or supMarkMax/supMarkMin,
    # we add a term to the objective function designed to keep down the maximum number of
    # projects assigned to any individual faculty member.
    maxProjects = pulp.LpVariable("maxProjects", lowBound=0, cat=pulp.LpContinuous)
    maxMarking = pulp.LpVariable("maxMarking", lowBound=0, cat=pulp.LpContinuous)

    # add variables designed to allow violation of maximum CATS if necessary to obtain a feasible
    # solution
    sup_elastic_CATS = pulp.LpVariable.dicts("A", range(number_sup), cat=pulp.LpContinuous, lowBound=0)
    mark_elastic_CATS = pulp.LpVariable.dicts("B", range(number_mark), cat=pulp.LpContinuous, lowBound=0)


    # OBJECTIVE FUNCTION

    # tension top and bottom workloads in each group against each other
    group_levelling = (supMax - supMin) + (markMax - markMin) + (supMarkMax - supMarkMin)
    global_levelling = (globalMax - globalMin)

    # apart from attempting to balance workloads, there is no need to add a reward for marker assignments;
    # these only need to satisfy the constraints, and any one solution is as good as another

    # dividing through by mean_CATS_per_project makes a workload discrepancy of 1 project between
    # upper and lower limits roughly equal to one ranking place in matching to students
    group_levelling_term = abs(levelling_bias) * group_levelling / mean_CATS_per_project
    global_levelling_term = abs(intra_group_tension) * global_levelling / mean_CATS_per_project

    # try to keep marking assignments under control by imposing a penalty for the highest number of marking assignments
    marking_bias = abs(marking_pressure) * maxMarking

    # likewise for supervising
    supervising_bias = abs(supervising_pressure) * maxProjects

    # we subtract off a penalty for all 'elastic' variables with a high coefficient, to discourage violation
    # of CATS limits except where really necessary; notice that these elastic variables are measured in
    # units of CATS, not projects, so the coefficents really are large
    elastic_CATS_penalty = abs(CATS_violation_penalty) * \
                           (sum(sup_elastic_CATS[i] for i in range(number_sup))
                            + sum(mark_elastic_CATS[i] for i in range(number_mark)))

    # we also impose a penalty for every supervisor who does not have any project assignments
    no_assignment_penalty = 2.0 * abs(no_assignment_penalty) * sum(1-Z[i] for i in range(number_sup))

    prob += _build_score_function(R, W, X, Y, S, number_lp, number_sel, number_sup, number_mark, base_X, base_Y, base_S,
                                  has_base_match, base_bias) \
            - group_levelling_term \
            - global_levelling_term \
            - marking_bias \
            - no_assignment_penalty \
            - supervising_bias \
            - elastic_CATS_penalty, \
            "objective"


    # STUDENT RANKING

    # selectors can only be assigned to projects that they have ranked
    # (unless no ranking data was available, in which case all elements of R were set to 1)
    for i in range(number_sel):
        sel: SelectingStudent = sel_dict[i]
        user: User = sel.student.user

        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (i, j)

            if proj.generic or proj.owner is None:
                tag = 'generic'
            else:
                user_owner: User = proj.owner.user
                tag = '{first}{last}'.format(first=user_owner.first_name, last=user_owner.last_name)

            prob += X[key] <= R[key], \
                    '_C{first}{last}_rank_SC{scfg}_C{cfg}_{tag}_P{num}' \
                        .format(first=user.first_name, last=user.last_name, scfg=sel.config_id,
                                cfg=proj.config_id, num=proj.number, tag=tag)


    # Q[j] should be constrained to be 1 if project j is assigned to any student, otherwise it should be zero
    for j in range(number_lp):
        proj: LiveProject = lp_dict[j]

        # force Q[j] to be zero if no students are assigned to project j
        prob += Q[j] <= sum(X[(i, j)] for i in range(number_sel)), \
                '_CQ_upperb_C{cfg}_P{num}'.format(cfg=proj.config_id, num=proj.number)

        # force Q[j] to be nonzero if any students are assigned to project j
        for i in range(number_sel):
            sel: SelectingStudent = sel_dict[i]
            user: User = sel.student.user

            prob += Q[j] >= X[(i, j)], \
                    '_CQ{first}{last}_lowerb_C{cfg}_P{num}'.format(first=user.first_name, last=user.last_name,
                                                                   cfg=proj.config_id, num=proj.number)


    # Enforce desired multiplicity (= total number of projects to be assigned) for each selector
    # typically this is one project per submission period
    for i in range(number_sel):
        sel: SelectingStudent = sel_dict[i]
        user: User = sel.student.user

        prob += sum(X[(i, j)] for j in range(number_lp)) == multiplicity[i], \
                '_C{first}{last}_SC{scfg}_assign'.format(first=user.first_name, last=user.last_name, scfg=sel.config_id)


    # Add constraints for any matches marked 'require' by a convenor
    for idx in cstr:
        i = idx[0]
        j = idx[1]
        sel: SelectingStudent = sel_dict[i]
        proj: LiveProject = lp_dict[j]
        user: User = sel.student.user

        # impose 'force' constraints, where we require a student to be allocated a particular project
        prob += X[idx] == 1, \
                '_C{first}{last}_SC{scfg}_force_C{cfg}_P{num}'.format(first=user.first_name, last=user.last_name,
                                                                      scfg=sel.config_id, cfg=proj.config_id,
                                                                      num=proj.number)


    # Implement any "force" constraints from base match
    if force_base:
        for idx in base_X:
            i = idx[0]
            j = idx[1]

            sel: SelectingStudent = sel_dict[i]
            proj: LiveProject = lp_dict[j]
            user: User = sel.student.user

            prob += X[idx] == 1, \
                    '_C{first}{last}_SC{scfg}_base_proj_C{cfg}_P{num}'.format(first=user.first_name, last=user.last_name,
                                                                              scfg=sel.config_id, cfg=proj.config_id,
                                                                              num=proj.number)


    # SUPERVISOR AND MARKER ASSIGNMENTS

    # Supervisors can only be assigned to projects that they supervise, or to group/generic projects
    # for which they are in the supervisor pool
    for k in range(number_sup):
        sup: FacultyData = sup_dict[k]
        user: User = sup.user

        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (k, j)

            # enforce maximum capacity for each project; each supervisor should have no more assignments than
            # the specified project capacity
            prob += S[key] <= capacity[j] * P[key], \
                    '_CS{first}{last}_C{cfg}_P{num}_supv_capacity'.format(first=user.first_name, last=user.last_name,
                                                                          cfg=proj.config_id, num=proj.number)


    # ss[k,j] should be zero if supervisor k has no assignments to project j, and otherwise 1
    for k in range(number_sup):
        sup: FacultyData = sup_dict[k]
        user: User = sup.user

        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (k, j)

            # force ss[k,j] to be zero if S[k,j] is zero
            prob += ss[key] <= S[key], \
                    '_Css{first}{last}_C{cfg}_P{num}_supv_assigned_upperb'.format(first=user.first_name, last=user.last_name,
                                                                                  cfg=proj.config_id, num=proj.number)

            # force ss[k,j] to be 1 if S[k,j] is not zero. There doesn't seem to be a really elegant, clean
            # way to do this in mixed integer linear programming. We assume that S[k,j] never gets as large as
            # UNBOUNDED_SUPERVISING_CAPACITY, and then S[k,j]/UNBOUNDED_SUPERVISING_CAPACITY will be less than unity but greater than
            # zero whenver S[k,j] is not zero
            prob += UNBOUNDED_SUPERVISING_CAPACITY * ss[key] >= S[key], \
                    '_Css{first}{last}_C{cfg}_P{num}_supv_assigned_lowerb'.format(first=user.first_name, last=user.last_name,
                                                                                  cfg=proj.config_id, num=proj.number)


    # Prevent supervisors from being assigned to more than a fixed number of projects.
    # There are separate constraints for group projects and projects of any type
    for k in range(number_sup):
        sup: FacultyData = sup_dict[k]
        user: User = sup.user

        # build sum of group projects assigned/not assigned flags for this supervisor
        group_projects = 0
        all_projects = 0
        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (k, j)

            all_projects += ss[key]
            if proj.generic:
                group_projects += ss[key]

        group_limit = record.max_different_group_projects
        if group_limit is not None and group_limit > 0:
            prob += group_projects <= group_limit, \
                    '_C{first}{last}_group_limit'.format(first=user.first_name, last=user.last_name)

        all_limit = record.max_different_all_projects
        if all_limit is not None and all_limit > 0:
            if group_limit is not None and group_limit > all_limit:
                all_limit = group_limit

            prob += all_projects <= all_limit, \
                    '_C{first}{last}_all_limit'.format(first=user.first_name, last=user.last_name)


    # Z[k] should be constrained to be 0 if supervisor k is not assigned to any projects
    for k in range(number_sup):
        sup: FacultyData = sup_dict[k]
        user: User = sup.user

        # force Z[k] to be zero if no projects are assigned to supervisor k
        prob += Z[k] <= sum(S[(k, j)] for j in range(number_lp)), \
                '_CZ{first}{last}_upperb'.format(first=user.first_name, last=user.last_name)

        # force Z[k] to be 1 if any project is assigned to supervisor k
        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (k, j)

            prob += Z[k] >= ss[key], \
                    '_CZ{first}{last}_C{cfg}_P{num}_lowerb'.format(first=user.first_name, last=user.last_name,
                                                                   cfg=proj.config_id, num=proj.number)


    # Markers can only be assigned projects to which they are in the assessor pool
    for i in range(number_mark):
        mark: FacultyData = mark_dict[i]
        user: User = mark.user

        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (i, j)

            # recall M[key] is the allowed multiplicity (i.e. maximum number of times marker i can be assigned
            # to mark a report from project j), not just a 0 or 1
            prob += Y[key] <= M[key], \
                    '_CM{first}{last}_C{cfg}_P{num}_mark_capacity'.format(first=user.first_name, last=user.last_name,
                                                                          cfg=proj.config_id, num=proj.number)


    # yy[i,j] should be zero if marker i has no assignments to project j, and otherwise 1
    for i in range(number_mark):
        mark: FacultyData = mark_dict[i]
        user: User = mark.user

        for j in range(number_lp):
            proj: LiveProject = lp_dict[j]
            key = (i, j)

            # force yy[i,j] to be zero if Y[i,j] is zero
            prob += yy[key] <= Y[key], \
                    '_Cyy{first}{last}_C{cfg}_P{num}_mark_assigned_upperb'.format(first=user.first_name, last=user.last_name,
                                                                                  cfg=proj.config_id, num=proj.number)

            # force yy[i,j] to be 1 if Y[i,j] is not zero
            prob += UNBOUNDED_MARKING_CAPACITY * yy[key] >= Y[key], \
                    '_Cyy{first}{last}_C{cfg}_P{num}_mark_assigned_lowerb'.format(first=user.first_name, last=user.last_name,
                                                                                  cfg=proj.config_id, num=proj.number)


    # If supervisors are being used, a supervisor should be assigned for each project that has been assigned
    for j in range(number_lp):
        proj: LiveProject = lp_dict[j]
        config: ProjectClassConfig = proj.config
        pclass: ProjectClass = config.project_class

        if config.select_in_previous_cycle:
            uses_supervisor = pclass.uses_supervisor
        else:
            uses_supervisor = config.uses_supervisor

        if uses_supervisor:

            # force that total number of assigned supervisors matches total number of assigned students;
            # (each S[k,j] can be > 1, meaning that the same supervisor is assigned to > 1 students)
            prob += sum(S[(k, j)] * P[(k, j)] for k in range(number_sup)) == \
                      sum(X[(i, j)] for i in range(number_sel)), \
                    '_CS_C{cfg}_P{num}_supv_parity'.format(cfg=proj.config_id, num=proj.number)

        else:
            # enforce no supervisors assigned to this project
            prob += sum(S[(k, j)] for k in range(number_sup)) == 0, \
                    '_CS_C{cfg}_P{num}_nosupv'.format(cfg=proj.config_id, num=proj.number)


    # If markers are being used, number of students assigned to each project must match the required
    # number of markers assigned to each project; otherwise, number of markers should be zero.
    # The required number of markers is determined by the value of marker_valence[j]
    for j in range(number_lp):
        proj: LiveProject = lp_dict[j]
        config: ProjectClassConfig = proj.config
        pclass: ProjectClass = config.project_class

        if config.select_in_previous_cycle:
            uses_marker = pclass.uses_marker
        else:
            uses_marker = config.uses_marker

        if uses_marker:
            # total number of assigned students should equal number of assigned markers, or zero if no markers used
            prob += marker_valence[j] * sum(X[(i, j)] for i in range(number_sel)) == \
                    sum(Y[(i, j)] for i in range(number_mark)), \
                    '_CY_C{cfg}_P{num}_mark_parity'.format(cfg=proj.config_id, num=proj.number)

            # also, for each project, we should have at least marker_valence[j] different markers assigned,
            # in order that we can generate the right number of *distinct* marking assignments
            prob += sum(yy[(i, j)] for i in range(number_mark)) >= marker_valence[j] * Q[j], \
                    '_CY_C{cfg}_P{num}_mark_distinct'.format(cfg=proj.config_id, num=proj.number)

        else:
            # enforce no markers assigned to this project
            prob += sum(Y[(i, j)] for i in range(number_mark)) == 0, \
                    '_CY_C{cfg}_P{num}_nomark'.format(cfg=proj.config_id, num=proj.number)


    # No supervisor should be assigned to mark their own project, and vice versa
    for i in range(number_mark):
        mark: FacultyData = mark_dict[i]
        mark_user: User = mark.user

        for k in range(number_sup):
            sup: FacultyData = sup_dict[k]
            sup_user: User = sup.user

            # if this supervisor and this marker are the same, they should not be assigned to the same project
            if mark_user.id == sup_user.id:
                for j in range(number_lp):
                    proj: LiveProject = lp_dict[j]

                    prob += ss[(k, j)] + yy[(i, j)] <= 1, \
                            '_C{first}{last}_C{cfg}_P{num}_supv_mark_disjoint'.format(first=sup_user.first_name, last=sup_user.last_name,
                                                                                      cfg=proj.config_id, num=proj.number)


    # Implement any "force" constraints from base match, if one is in use
    if force_base:
        for idx in base_Y.keys():
            i = idx[0]
            j = idx[1]

            mark: FacultyData = mark_dict[i]
            proj: LiveProject = lp_dict[j]
            user: User = mark.user

            prob += Y[idx] == base_Y[idx], \
                    '_C{first}{last}_SC{scfg}_base_mark_C{cfg}_P{num}'.format(first=user.first_name, last=user.last_name,
                                                                              scfg=sel.config_id, cfg=proj.config_id,
                                                                              num=proj.number)

        for idx in base_S.keys():
            k = idx[0]
            j = idx[1]

            supv: FacultyData = sup_dict[k]
            proj: LiveProject = lp_dict[j]
            user: User = supv.user

            prob += S[idx] == base_S[idx], \
                    '_C{first}{last}_SC{scfg}_base_supv_C{cfg}_P{num}'.format(first=user.first_name, last=user.last_name,
                                                                              scfg=sel.config_id, cfg=proj.config_id,
                                                                              num=proj.number)


    # WORKLOAD LIMITS

    # CATS assigned to each supervisor must be within bounds
    for k in range(number_sup):
        sup: FacultyData = sup_dict[k]
        user: User = sup.user

        # enforce global limit, either from optimization configuration or from user's global record
        lim = record.supervising_limit
        sup_limit = sup_limits[k]
        if not record.ignore_per_faculty_limits and sup_limit is not None and sup_limit > 0:
            if sup_limit < lim:
                lim = sup_limit

        existing_CATS = _compute_existing_sup_CATS(record, sup)
        if existing_CATS > lim:
            raise RuntimeError('Inconsistent matching problem: existing supervisory CATS load {n} for faculty '
                               '"{name}" exceeds specified CATS limit'.format(n=existing_CATS, name=user.name))

        prob += existing_CATS + sum(S[(k, j)] * CATS_supervisor[j]
                                    for j in range(number_lp)) <= lim + sup_elastic_CATS[k], \
                '_C{first}{last}_supv_CATS'.format(first=user.first_name, last=user.last_name)

        # enforce ad-hoc per-project-class supervisor limits
        for config_id in sup_pclass_limits:
            fac_limits = sup_pclass_limits[config_id]
            projects = lp_group_dict.get(config_id, None)

            if k in fac_limits and projects is not None:
                prob += sum(S[(k, j)] * CATS_supervisor[j] for j in projects) <= fac_limits[i], \
                        '_C{first}{last}_supv_CATS_config_{cfg}'.format(first=user.first_name, last=user.last_name,
                                                                        cfg=config_id)

    # CATS assigned to each marker must be within bounds
    for i in range(number_mark):
        mark: FacultyData = mark_dict[i]
        user: User = mark.user

        # enforce global limit
        lim = record.marking_limit
        mark_limit = mark_limits[i]
        if not record.ignore_per_faculty_limits and mark_limit is not None and mark_limit > 0:
            if mark_limit < lim:
                lim = mark_limit

        existing_CATS = _compute_existing_mark_CATS(record, mark)
        if existing_CATS > lim:
            raise RuntimeError('Inconsistent matching problem: existing marking CATS load {n} for faculty '
                               '"{name}" exceeds specified CATS limit'.format(n=existing_CATS, name=mark.user.name))

        prob += existing_CATS + sum(Y[(i, j)] * CATS_marker[j]
                                    for j in range(number_lp)) <= lim + mark_elastic_CATS[i], \
                '_C{first}{last}_mark_CATS'.format(first=user.first_name, last=user.last_name)

        # enforce ad-hoc per-project-class marking limits
        for config_id in mark_pclass_limits:
            fac_limits = mark_pclass_limits[config_id]
            projects = lp_group_dict.get(config_id, None)

            if i in fac_limits and projects is not None:
                prob += sum(Y[(i, j)] * CATS_marker[j] for j in projects) <= fac_limits[i], \
                        '_C{first}{last}_mark_CATS_config_C{cfg}'.format(first=user.first_name, last=user.last_name,
                                                                         cfg=config_id)


    # WORKLOAD LEVELLING

    global_trivial = True

    # supMin and supMax should bracket the CATS workload of faculty who supervise only
    if len(sup_only_numbers) > 0:
        for k in sup_only_numbers:
            prob += sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) <= supMax
            prob += sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) >= supMin

        prob += globalMin <= supMin
        prob += globalMax >= supMax

        global_trivial = False
    else:
        prob += supMax == 0
        prob += supMin == 0

    # markMin and markMax should bracket the CATS workload of faculty who mark only
    if len(mark_only_numbers) > 0:
        for i in mark_only_numbers:
            prob += sum(Y[(i, j)] * CATS_marker[j] for j in range(number_lp)) <= markMax
            prob += sum(Y[(i, j)] * CATS_marker[j] for j in range(number_lp)) >= markMin

        prob += globalMin <= markMin
        prob += globalMax >= markMax

        global_trivial = False
    else:
        prob += markMax == 0
        prob += markMin == 0

    # supMarkMin and supMarkMAx should bracket the CATS workload of faculty who both supervise and mark
    if len(sup_and_mark_numbers) > 0:
        for k, i in sup_and_mark_numbers:
            prob += sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) \
                    + sum(Y[(i, j)] * CATS_marker[j] for j in range(number_lp)) <= supMarkMax
            prob += sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) \
                    + sum(Y[(i, j)] * CATS_marker[j] for j in range(number_lp)) >= supMarkMin

        prob += globalMin <= supMarkMin
        prob += globalMax >= supMarkMax

        global_trivial = False
    else:
        prob += supMarkMax == 0
        prob += supMarkMin == 0

    # if no constraints have been emitted for the global variables, issue constraints to tie them to zero:
    if global_trivial:
        prob += globalMin == 0
        prob += globalMax == 0

    # maxProjects should be larger than the total number of projects assigned for supervising to any
    # individual faculty member
    if number_sup > 0:
        for i in range(number_sup):
            prob += sum(S[(k, j)] for j in range(number_lp)) <= maxProjects
    else:
        prob += maxProjects == 0

    # maxMarking should be larger than the total number of projects assigned for marking to
    # any individual faculty member
    if number_mark > 0:
        for i in range(number_mark):
            prob += sum(Y[(i, j)] for j in range(number_lp)) <= maxMarking
    else:
        prob += maxMarking == 0

    return prob, X, Y, S


def _build_score_function(R, W, X, Y, S, number_lp, number_sel, number_sup, number_mark, base_X, base_Y, base_S,
                          has_base_match, base_bias):
    # generate score function, used as a component of the maximization objective
    objective = 0

    fbase_bias = None

    if len(base_X) > 0 or len(base_Y) > 0 or len(base_S) > 0:
        if base_bias is None:
            raise RuntimeError('base_bias = None in _build_score_function')
        else:
            fbase_bias = float(base_bias)
            print('-- using base bias of {f}'.format(f=fbase_bias))

    # reward the solution for assigning students to highly ranked projects:
    for i in range(number_sel):
        base_match_exists = i in has_base_match
        if base_match_exists:
            print('-- using base match data for selector {n}'.format(n=i))

        for j in range(number_lp):
            idx = (i, j)

            if base_match_exists:
                # an assignment for selector i was present in the base, but we don't know whether it was for
                # this project.

                if idx in base_X:
                    # an assignment to this project *was* already in the base, so bias it to be present here
                    objective += fbase_bias*X[idx]
                else:
                    # an assignment to this project was *not* already in the base, so bias it to be absent here
                    objective += fbase_bias*(1-X[idx])
            else:
                # no assignment for selector i was present in the base

                if R[idx] > 0:
                    # score is 1/rank of assigned project, weighted
                    objective += X[idx] * W[idx] / R[idx]

    # bias towards any marking choices from base match
    if len(base_Y) > 0:
        for i in range(number_mark):
            for j in range(number_lp):
                idx = (i, j)

                if idx in base_Y:
                    # bias Y assignment towards the multiplicity found in the base
                    m = base_Y[idx]
                    objective += fbase_bias*(Y[idx] - int(m))
                else:
                    # bias Y assignment towards Y = 0
                    objective += fbase_bias*(1-Y[idx])

    # bias towards any supervising choices from base match
    if len(base_S) > 0:
        for k in range(number_sup):
            for j in range(number_lp):
                idx = (k, j)

                if idx in base_S:
                    # bias S assignment towards the multiplicity found in the base
                    m = base_S[idx]
                    objective += fbase_bias*(S[idx] - int(m))
                else:
                    # bias Y assignment towards S=0
                    objective += fbase_bias*(1-S[idx])

    return objective


def _store_PuLP_solution(X, Y, S, record: MatchingAttempt, number_sel, number_to_sel, number_lp, number_to_lp,
                         number_sup, number_to_sup, number_mark, number_to_mark, multiplicity, sel_dict, sup_dict,
                         mark_dict, lp_dict, mean_CATS_per_project):
    """
    Store a matching satisfying all the constraints of the pulp problem
    :param number_to_sup:
    :param S:
    :param number_sup:
    :param prob:
    :param record:
    :param number_sel:
    :param number_to_sel:
    :param number_lp:
    :param number_to_lp:
    :param number_mark:
    :param number_to_mark:
    :return:
    """
    # store configuration data
    for item in sup_dict.values():
        if item not in record.supervisors:
            record.supervisors.append(item)

    for item in mark_dict.values():
        if item not in record.markers:
            record.markers.append(item)

    for item in lp_dict.values():
        if item not in record.projects:
            record.projects.append(item)

    record.mean_CATS_per_project = mean_CATS_per_project

    # generate dictionary of supervisor assignments: we map each project id to a list of supervisors
    supervisors = {}
    for j in range(number_lp):
        proj_id = number_to_lp[j]
        if proj_id in supervisors:
            raise RuntimeError('PuLP solution has inconsistent supervisor assignment')

        assigned = {}

        for k in range(number_sup):
            S[(k, j)].round()
            # get multiplicity m with which supervisor k is assigned to project j
            m = pulp.value(S[(k, j)])
            if m > 0:
                assigned.update({number_to_sup[k]: m})

        supervisors[proj_id] = assigned

    # generate dictionary of marker assignments; we map each project id to a list of available markers
    markers = {}
    for j in range(number_lp):
        proj_id = number_to_lp[j]
        if proj_id in markers:
            raise RuntimeError('PuLP solution has inconsistent marker assignment')

        assigned = {}

        for i in range(number_mark):
            Y[(i, j)].round()
            # get multiplicity with which marker i is assigned to project j
            m = pulp.value(Y[(i, j)])
            if m > 0:
                assigned.update({number_to_mark[i]: m})

        markers[proj_id] = assigned

    # loop through all selectors that participated in the matching, generating matching records for each one
    for i in range(number_sel):
        if i not in sel_dict:
            raise RuntimeError('PuLP solution contains invalid selector id')

        sel: SelectingStudent = sel_dict[i]

        if sel.id != number_to_sel[i]:
            raise RuntimeError('Inconsistent selector ids when storing PuLP solution')

        # find the submission periods and marker valences that are needed for this selector
        config: ProjectClassConfig = sel.config
        pclass: ProjectClass = config.project_class

        periods = {}

        # if selection occurs in previous cycle, uses period definitions from parent ProjectClass
        if config.select_in_previous_cycle:
            uses_supervisor = pclass.uses_supervisor
            uses_marker = pclass.uses_marker

            for pd in pclass.periods:
                pd: SubmissionPeriodDefinition
                periods[pd.period] = pd.number_markers

        # otherwise, use current definitions from ProjectClassConfig
        else:
            uses_supervisor = config.uses_supervisor
            uses_marker = config.uses_marker

            for pd in config.periods:
                pd: SubmissionPeriodRecord
                periods[pd.period] = pd.number_markers

        if len(periods) != multiplicity[i]:
            raise RuntimeError('Number of submission periods does not match expected selector multiplicity')

        # generate list of project assignments for this selector
        assigned = []

        for j in range(number_lp):
            X[(i, j)].round()
            if pulp.value(X[(i, j)]) == 1:
                assigned.append(j)

        if len(assigned) != multiplicity[i]:
            raise RuntimeError('Number of assignments in PuLP solution does not match expected selector multiplicity')

        while len(assigned) > 0:
            # pop a project assignment from the back of the stack
            proj_number: int = assigned.pop()
            proj_id: int = number_to_lp[proj_number]

            if proj_number not in lp_dict:
                raise RuntimeError('PuLP solution references unexpected LiveProject instance')

            project: LiveProject = lp_dict[proj_number]
            if proj_id != project.id:
                raise RuntimeError('Inconsistent project lookup when storing PuLP solution')

            # calculate selector's rank of the assigned project
            # (this lets us work out the quality of the fit from the student's perspective)
            rk = sel.project_rank(proj_id)
            if sel.has_submitted and rk is None:
                raise RuntimeError('PuLP solution assigns unranked project to selector')

            # decide which submission period to assign this project to
            if len(periods) == 0:
                raise RuntimeError('Period list is unexpectedly empty when storing PuLP solution')
            period_list = sorted(list(periods))
            this_period = period_list[0]
            markers_needed = periods.pop(this_period)

            data = MatchingRecord(matching_id=record.id,
                                  selector_id=number_to_sel[i],
                                  project_id=proj_id,
                                  original_project_id=proj_id,
                                  submission_period=this_period,
                                  rank=rk)
            db.session.add(data)
            db.session.flush()


            # ASSIGN ROLES (IF USED)

            # find supervisor, if used
            if uses_supervisor:
                # get supervisor assignment for this project
                if proj_id not in supervisors:
                    raise RuntimeError('PuLP solution error: supervisor stack unexpectedly empty or missing')

                supervisor_list = supervisors[proj_id]
                supervisor = None

                while supervisor is None and len(supervisor_list) > 0:
                    key_list = sorted(list(supervisor_list))
                    key = key_list[0]
                    value = supervisor_list[key]

                    if value > 0:
                        supervisor = key
                        value -= 1

                        if value == 0:
                            supervisor_list.pop(key)
                        else:
                            supervisor_list[key] = value

                    else:
                        raise RuntimeError('PuLP solution error: supervisor count has decreased to zero, but '
                                           'supervisor has not been removed from queue')

                if supervisor is None:
                    raise RuntimeError('PuLP solution error: supervisor stack unexpectedly empty or missing')

                # generate supervisor role record
                role_supv = MatchingRole(user_id=supervisor, role=MatchingRole.ROLE_SUPERVISOR)
                data.roles.append(role_supv)

                # generate original supervisor role record (cached so we can revert later if required)
                orig_role_supv = MatchingRole(user_id=supervisor, role=MatchingRole.ROLE_SUPERVISOR)
                data.original_roles.append(orig_role_supv)

            # find marker
            if uses_marker:
                # get a set of marker assignments for this project
                if proj_id not in markers:
                    raise RuntimeError('PuLP solution error: marker stack unexpectedly empty or missing')

                marker_list = markers[proj_id]
                markers_used = set()

                while markers_needed > 0:
                    marker = None

                    while marker is None and len(marker_list) > 0:
                        key_list = sorted(list(marker_list))
                        key = None
                        while key is None and len(key_list) > 0:
                            key_candidate = key_list.pop()
                            if key_candidate not in markers_used:
                                key = key_candidate

                        if key is None:
                            raise RuntimeError('PuLP solution error: was not able to find candidate marker')

                        value = marker_list[key]

                        if value > 0:
                            marker = key
                            markers_used.add(marker)

                            value -= 1

                            if value == 0:
                                marker_list.pop(key)
                            else:
                                marker_list[key] = value

                        else:
                            raise RuntimeError('PuLP solution error: marker count has decreased to zero, but '
                                               'marker has not been removed from the queue')

                    if marker is None:
                        raise RuntimeError('PuLP solution error: marker stack unexpected empty or missing')

                    # generate marker role record
                    role_mark = MatchingRole(user_id=marker, role=MatchingRole.ROLE_MARKER)
                    data.roles.append(role_mark)

                    # generate original marker role record (cached so we can revert later if required)
                    orig_role_mark = MatchingRole(user_id=marker, role=MatchingRole.ROLE_MARKER)
                    data.original_roles.append(orig_role_mark)

                    markers_needed -= 1

            db.session.flush()


def _create_marker_PuLP_problem(mark_dict, submit_dict, mark_CATS_dict, config):
    # capture number of CATS assigned per marking task
    CATS_per_assignment = _floatify(config.CATS_marking)

    # generate PuLP problem
    prob: pulp.LpProblem = pulp.LpProblem("populate_marker", pulp.LpMinimize)

    # generate decision variables for marker assignment
    number_markers = len(mark_dict)
    number_submitters = len(submit_dict)
    Y = pulp.LpVariable.dicts("Y", itertools.product(range(number_markers), range(number_submitters)),
                              cat=pulp.LpBinary)

    # to implement workload balancing we use pairs of continuous variables that relax
    # to the maximum and minimum workload
    max_CATS = pulp.LpVariable("max_CATS", lowBound=0, cat=pulp.LpContinuous)
    min_CATS = pulp.LpVariable("min_CATS", lowBound=0, cat=pulp.LpContinuous)

    # track maximum number of marking assignments for any individual faculty member
    max_assigned = pulp.LpVariable("max_assigned", lowBound=0, cat=pulp.LpContinuous)


    # OBJECTIVE FUNCTION

    # maximization problem is to assign everyone while keeping difference between max and min CATS
    # small, and keeping max_assigned small
    prob += 10.0*(max_CATS - min_CATS) + 5.0*max_assigned

    for i in range(number_markers):
        # max_CATS and min_CATS should bracket the CATS workload of all faculty
        prob += mark_CATS_dict[i] \
                + CATS_per_assignment * sum(Y[(i, j)] for j in range(number_submitters)) <= max_CATS
        prob += mark_CATS_dict[i] \
                + CATS_per_assignment * sum(Y[(i, j)] for j in range(number_submitters)) >= min_CATS

        # max_assigned should relax to total assigned
        prob += sum(Y[(i, j)] for j in range(number_submitters)) <= max_assigned


    # CONSTRAINT: EXACTLY ONE MARKER ASSIGNED PER SUBMITTER

    for j in range(number_submitters):
        prob += sum(Y[(i, j)] for i in range(number_markers)) == 1


    # CONSTRAINT: MARKERS CAN ONLY BE ASSIGNED TO PROJECTS FOR WHICH THEY ARE IN THE ASSESSOR POOL

    for j in range(number_submitters):
        sub: SubmissionRecord = submit_dict[j]

        for i in range(number_markers):
            marker: FacultyData = mark_dict[i]

            if sub.is_in_assessor_pool(marker.id):
                prob += Y[(i, j)] <= 1
            else:
                prob += Y[(i, j)] == 0

    return prob, Y


def _initialize(self, record, read_serialized=False):
    progress_update(record.celery_id, TaskRecord.RUNNING, 5, "Collecting information...", autocommit=True)

    try:
        # get list of project classes participating in automatic assignment
        configs = record.config_members.all()
        mean_CATS_per_project = _find_mean_project_CATS(configs)
        print(' -- {n} ProjectClassConfig instances participate in this matching'.format(n=len(configs)))

        # get lists of selectors and liveprojects, together with auxiliary data such as
        # multiplicities (for selectors) and CATS assignments (for projects)
        with Timer() as sel_timer:
            number_sel, sel_to_number, number_to_sel, multiplicity, \
                sel_dict = _enumerate_selectors(record, configs, read_serialized=read_serialized)
        print(' -- enumerated {n} selectors in time {s}'.format(n=number_sel, s=sel_timer.interval))

        with Timer() as lp_timer:
            number_lp, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, \
                lp_dict, lp_group_dict = _enumerate_liveprojects(record, configs, read_serialized=read_serialized)
        print(' -- enumerated {n} LiveProjects in time {s}'.format(n=number_lp, s=lp_timer.interval))

        # get supervising faculty and marking faculty lists
        with Timer() as sup_timer:
            number_sup, sup_to_number, number_to_sup, sup_limits, sup_dict, sup_pclass_limits = \
                _enumerate_supervising_faculty(record, configs)
        print(' -- enumerated {n} supervising faculty in time {s}'.format(n=number_sup, s=sup_timer.interval))

        with Timer() as mark_timer:
            number_mark, mark_to_number, number_to_mark, mark_limits, mark_dict, mark_pclass_limits = \
                _enumerate_marking_faculty(record, configs)
        print(' -- enumerated {n} marking faculty in time {s}'.format(n=number_mark, s=mark_timer.interval))

        with Timer() as partition_timer:
            # partition faculty into supervisors, markers and supervisors+markers
            supervisors = sup_to_number.keys()
            markers = mark_to_number.keys()

            # we can apply set operations to the key views that are returned
            sup_only = supervisors - markers
            mark_only = markers - supervisors
            sup_and_mark = supervisors & markers

            sup_only_numbers = {sup_to_number[x] for x in sup_only}
            mark_only_numbers = {mark_to_number[x] for x in mark_only}
            sup_and_mark_numbers = {(sup_to_number[x], mark_to_number[x]) for x in sup_and_mark}
        print(' -- partitioned faculty in time {s}'.format(s=partition_timer.interval))
        print('    :: {n} faculty are supervising only'.format(n=len(sup_only_numbers)))
        print('    :: {n} faculty are marking only'.format(n=len(mark_only_numbers)))
        print('    :: {n} faculty are supervising and marking'.format(n=len(sup_and_mark_numbers)))

        # build student ranking matrix
        with Timer() as rank_timer:
            R, W, cstr = _build_ranking_matrix(number_sel, sel_dict, number_lp, lp_to_number, lp_dict, record)
        print(' -- built student ranking matrix in time {s}'.format(s=rank_timer.interval))

        # build marker compatibility matrix
        with Timer() as mark_matrix_timer:
            mm = record.max_marking_multiplicity
            M, marker_valence = _build_marking_matrix(number_mark, mark_dict, number_lp, lp_dict, mm if mm >= 1 else 1)
        print(' -- built marking compatibility matrix in time {s}'.format(s=mark_matrix_timer.interval))

        with Timer() as sup_mapping_timer:
            # build project-to-supervisor mapping
            P = _build_project_supervisor_matrix(number_lp, lp_dict, number_sup, sup_dict)
        print(' -- built project-to-supervisor mapping matrix in time {s}'.format(s=sup_mapping_timer.interval))

    except SQLAlchemyError as e:
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    return number_sel, number_lp, number_sup, number_mark, \
           sel_to_number, lp_to_number, sup_to_number, mark_to_number, \
           number_to_sel, number_to_lp, number_to_sup, number_to_mark, \
           sel_dict, lp_dict, lp_group_dict, sup_dict, mark_dict, \
           sup_only_numbers, mark_only_numbers, sup_and_mark_numbers, \
           sup_limits, sup_pclass_limits, mark_limits, mark_pclass_limits,\
           multiplicity, capacity, \
           mean_CATS_per_project, CATS_supervisor, CATS_marker, \
           R, W, cstr, M, marker_valence, P


def _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number, mark_to_number):
    base_X = set()
    base_Y = {}
    base_S = {}
    has_base_match = set()

    base: MatchingAttempt = record.base

    if record.base is None:
        print('-- no base in use for this match (record.base_id={base_id})'.format(base_id=record.base_id))
        return base_X, base_Y, base_S, has_base_match

    for record in base.records:
        record: MatchingRecord

        if record.selector_id not in sel_to_number:
            raise RuntimeError('Missing SelectingStudent when reconstructing X map')

        # get our selector number for the allocated selector
        sel_number = sel_to_number[record.selector_id]

        if record.project_id not in lp_to_number:
            raise RuntimeError('Missing LiveProject when reconstructing X map')

        # get our project number for the allocated project
        proj_number = lp_to_number[record.project_id]

        base_X.add((sel_number, proj_number))
        print('>> registered base match between selector {sel_n} (={sel_name}) and project {proj_n} '
              '(={proj_name})'.format(sel_n=sel_number, proj_n=proj_number,
                                      sel_name=record.selector.student.user.name, proj_name=record.project.name))
        has_base_match.add(sel_number)

        for role in record.roles:
            role: MatchingRole

            if role.role == MatchingRole.ROLE_SUPERVISOR:
                if role.user_id not in sup_to_number:
                    raise RuntimeError('Missing supervisor when reconstructing S map')
                supv_number = sup_to_number[role.user_id]

                key = (supv_number, proj_number)
                if key in base_S:
                    base_S[key] += 1
                else:
                    base_S[key] = 1

                print('>> registered base match between supervisor {sup_n} (={sup_name}) and project {proj_n} '
                      '(={proj_name})'.format(sup_n=supv_number, proj_n=proj_number,
                                              sup_name=role.user.name, proj_name=record.project.name))

            elif role.role == MatchingRole.ROLE_MARKER:
                if role.user_id not in mark_to_number:
                    raise RuntimeError('Missing marker when reconstructing Y map')
                mark_number = mark_to_number[role.user_id]

                key = (mark_number, proj_number)
                if key in base_Y:
                    base_Y[key] += 1
                else:
                    base_Y[key] = 1

                print('>> registered base match between marker {mark_n} (={mark_name}) and project {proj_n} '
                      '(={proj_name})'.format(mark_n=mark_number, proj_n=proj_number,
                                              mark_name=role.user.name, proj_name=record.project.name))

    return base_X, base_Y, base_S, has_base_match


def _execute_live(self, record, prob, X, Y, S, W, R, create_time, number_sel, number_to_sel, number_lp, number_to_lp,
                  number_sup, number_to_sup, number_mark, number_to_mark, sel_dict, lp_dict, sup_dict, mark_dict,
                  multiplicity, mean_CATS_per_project):
    print('Solving PuLP problem for project matching')

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...",
                    autocommit=True)

    with Timer() as solve_time:
        record.awaiting_upload = False

        if record.solver == MatchingAttempt.SOLVER_CBC_PACKAGED:
            status = prob.solve(pulp_apis.PULP_CBC_CMD(msg=1, maxSeconds=3600, fracGap=0.25))
        elif record.solver == MatchingAttempt.SOLVER_CBC_CMD:
            status = prob.solve(pulp_apis.COIN_CMD(msg=1, maxSeconds=3600, fracGap=0.25))
        elif record.solver == MatchingAttempt.SOLVER_GLPK_CMD:
            status = prob.solve(pulp_apis.GLPK_CMD())
        elif record.solver == MatchingAttempt.SOLVER_CPLEX_CMD:
            status = prob.solve(pulp_apis.CPLEX_CMD())
        elif record.solver == MatchingAttempt.SOLVER_GUROBI_CMD:
            status = prob.solve(pulp_apis.GUROBI_CMD())
        elif record.solver == MatchingAttempt.SOLVER_SCIP_CMD:
            status = prob.solve(pulp_apis.SCIP_CMD())
        else:
            status = prob.solve()

    return _process_PuLP_solution(self, record, status, solve_time, X, Y, S, W, R, create_time, number_sel,
                                  number_to_sel, number_lp, number_to_lp, number_sup, number_to_sup, number_mark,
                                  number_to_mark, multiplicity, sel_dict, sup_dict, mark_dict, lp_dict,
                                  mean_CATS_per_project)


def _execute_from_solution(self, file, record, prob, X, Y, S, W, R, create_time, number_sel, number_to_sel, number_lp,
                           number_to_lp, number_sup, number_to_sup, number_mark, number_to_mark, sel_dict, lp_dict,
                           sup_dict, mark_dict, multiplicity, mean_CATS_per_project):
    print('Processing PuLP solution from "{name}"'.format(name=file))

    if not path.exists(file):
        progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Could not locate uploaded solution file",
                        autocommit=True)
        raise Ignore

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Processing uploaded solution file...",
                    autocommit=True)

    # TODO: catch pulp.pulp_apis.PulpSolverError: Unknown status returned by CPLEX
    #  and handle it gracefully (or fix it on the fly)
    with Timer() as solve_time:
        record.awaiting_upload = False
        wasNone, dummyVar = prob.fixObjective()

        if record.solver == MatchingAttempt.SOLVER_CBC_PACKAGED:
            solver = pulp_apis.PULP_CBC_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol_LP(file, prob, prob.variables())
        elif record.solver == MatchingAttempt.SOLVER_CBC_CMD:
            solver = pulp_apis.COIN_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol_LP(file, prob, prob.variables())
        elif record.solver == MatchingAttempt.SOLVER_GLPK_CMD:
            solver = pulp_apis.GLPK_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol(file)
        elif record.solver == MatchingAttempt.SOLVER_CPLEX_CMD:
            solver = pulp_apis.CPLEX_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol(file)
        elif record.solver == MatchingAttempt.SOLVER_GUROBI_CMD:
            solver = pulp_apis.GUROBI_CMD()
            status, values, reducedCosts, shadowPrices, slacks = solver.readsol(file)
        elif record.solver == MatchingAttempt.SOLVER_SCIP_CMD:
            solver = pulp_apis.SCIP_CMD()
            status, values, reducedCosts, shadowPrices, slacks, solStatus = solver.readsol(file)
        else:
            progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Unknown solver",
                            autocommit=True)
            raise Ignore()

        if status != pulp.LpStatusInfeasible:
            prob.assignVarsVals(values)
            prob.assignVarsDj(reducedCosts)
            prob.assignConsPi(shadowPrices)
            prob.assignConsSlack(slacks)
        prob.status = status

        prob.restoreObjective(wasNone, dummyVar)
        prob.solver = solver

    return _process_PuLP_solution(self, record, status, solve_time, X, Y, S, W, R, create_time, number_sel,
                                  number_to_sel, number_lp, number_to_lp, number_sup, number_to_sup, number_mark,
                                  number_to_mark, multiplicity, sel_dict, sup_dict, mark_dict, lp_dict,
                                  mean_CATS_per_project)


def _execute_marker_problem(task_id, prob, Y, mark_dict, submit_dict, user: User):
    print('Solving PuLP problem to populate markers')

    progress_update(task_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...",
                    autocommit=True)

    with Timer() as solve_time:
        status = prob.solve(pulp_apis.PULP_CBC_CMD(msg=1, maxSeconds=3600, fracGap=0.25))

    print('-- solved PuLP problem in time {t}'.format(t=solve_time.interval))

    progress_update(task_id, TaskRecord.RUNNING, 70, "Processing PuLP solution...", autocommit=True)

    state = pulp.LpStatus[status]

    if state == 'Optimal':
        try:
            number_markers = len(mark_dict)
            number_submitters = len(submit_dict)

            number_populated = 0

            for j in range(number_submitters):
                sub: SubmissionRecord = submit_dict[j]

                for i in range(number_markers):
                    Y[(i, j)].round()
                    if pulp.value(Y[(i, j)]) == 1:
                        marker: FacultyData = mark_dict[i]

                        sub.marker_id = marker.id
                        number_populated += 1
                        break

            db.session.commit()
            user.post_message("Populated {num} missing marker assignments".format(num=number_populated), 'success',
                              autocommit=True)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            user.post_message("Could not populate markers because, although the optimization task succeeded "
                              "there was a failure while storing the solution.", 'error', autocommit=True)

    else:
        user.post_message("Could not populate markers because the optimization task failed",
                          'error', autocommit=True)

    progress_update(task_id, TaskRecord.SUCCESS, 100, 'Matching task complete', autocommit=True)


def _process_PuLP_solution(self, record, output, solve_time, X, Y, S, W, R, create_time, number_sel, number_to_sel,
                           number_lp, number_to_lp, number_sup, number_to_sup, number_mark, number_to_mark,
                           multiplicity, sel_dict, sup_dict, mark_dict, lp_dict, mean_CATS_per_project):
    state = pulp.LpStatus[output]

    if state == 'Optimal':
        record.outcome = MatchingAttempt.OUTCOME_OPTIMAL

        # we don't just read the objective function out directly, because we don't want to include
        # contributions from the levelling and slack terms.
        # We don't account for biasing terms coming from a base match.
        score = _build_score_function(R, W, X, Y, S, number_lp, number_sel, number_sup, number_mark,
                                      set(), {}, set(), set(), 1.0)
        record.score = pulp.value(score)

        record.construct_time = create_time.interval
        record.compute_time = solve_time.interval

        progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing PuLP solution...", autocommit=True)

        try:
            # note _store_PuLP_solution does not do a commit by itself
            _store_PuLP_solution(X, Y, S, record, number_sel, number_to_sel, number_lp, number_to_lp, number_sup,
                                 number_to_sup, number_mark, number_to_mark, multiplicity, sel_dict, sup_dict,
                                 mark_dict, lp_dict, mean_CATS_per_project)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    elif state == 'Not Solved':
        record.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED
    elif state == 'Infeasible':
        record.outcome = MatchingAttempt.OUTCOME_INFEASIBLE
    elif state == 'Unbounded':
        record.outcome = MatchingAttempt.OUTCOME_UNBOUNDED
    elif state == 'Undefined':
        record.outcome = MatchingAttempt.OUTCOME_UNDEFINED
    else:
        raise RuntimeError('Unknown PuLP outcome')

    try:
        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, 'Matching task complete', autocommit=False)

        record.finished = True
        record.celery_finished = True
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    return record.score


def _send_offline_email(celery, record: MatchingAttempt, user, lp_asset: GeneratedAsset, mps_asset: GeneratedAsset):
    send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']

    msg = EmailMultiAlternatives(subject='Files for offline matching of {name} are now ready'.format(name=record.name),
                                 from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                                 reply_to=[current_app.config['MAIL_REPLY_TO']],
                                 to=[user.email])

    msg.body = render_template('email/matching/generated.txt', name=record.name, user=user)

    lp_path = canonical_generated_asset_filename(lp_asset.filename)
    with open(lp_path, 'rb') as fd:
        msg.attach(filename=str('schedule.lp'), mimetype=lp_asset.mimetype, content=fd.read())

    mps_path = canonical_generated_asset_filename(mps_asset.filename)
    with open(mps_path, 'rb') as fd:
        msg.attach(filename=str('schedule.mps'), mimetype=mps_asset.mimetype, content=fd.read())

    # register a new task in the database
    task_id = register_task(msg.subject, description='Email to {r}'.format(r=', '.join(msg.to)))
    send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


def _write_LP_MPS_files(record: MatchingAttempt, prob, user):
    lp_name, lp_abs_path = make_generated_asset_filename(ext='lp')
    mps_name, mps_abs_path = make_generated_asset_filename(ext='mps')
    prob.writeLP(lp_abs_path)
    prob.writeMPS(mps_abs_path)

    now = datetime.now()

    def make_asset(name, target):
        asset = GeneratedAsset(timestamp=now,
                               expiry=None,
                               filename=str(name),
                               mimetype='text/plain',
                               target_name=target)
        asset.grant_user(user)
        db.session.add(asset)

        return asset

    lp_asset = make_asset(lp_name, 'matching.lp')
    mps_asset = make_asset(mps_name, 'matching.mps')

    # write new assets to database, so they get a valid primary key
    db.session.flush()

    # add asset details to MatchingAttempt record
    record.lp_file = lp_asset
    record.mps_file = mps_asset

    # allow exceptions to propagate up to calling function
    record.celery_finished = True
    db.session.commit()

    return lp_asset, mps_asset


def _store_enumeration_details(record, number_to_sel, number_to_lp, number_to_sup, number_to_mark, lp_group_dict,
                               sup_pclass_limits, mark_pclass_limits):
    def write_out(label, block):
        for number in block:
            data = MatchingEnumeration(matching_id=record.id,
                                       enumeration=number,
                                       key=block[number],
                                       category=label)
            db.session.add(data)

    write_out(MatchingEnumeration.SELECTOR, number_to_sel)
    write_out(MatchingEnumeration.LIVEPROJECT, number_to_lp)
    write_out(MatchingEnumeration.SUPERVISOR, number_to_sup)
    write_out(MatchingEnumeration.MARKER, number_to_mark)

    for config_id in lp_group_dict:
        lps = lp_group_dict[config_id]

        for lp_id in lps:
            data = MatchingEnumeration(matching_id=record.id,
                                       enumeration=lp_id,
                                       key=config_id,
                                       category=MatchingEnumeration.LIVEPROJECT_GROUP)
            db.session.add(data)

    def write_limits(label, limit_dict):
        for config_id in limit_dict:
            limits = limit_dict[config_id]

            for fac_number in limits:
                data = MatchingEnumeration(matching_id=record.id,
                                           enumeration=fac_number,
                                           key=config_id,
                                           key2=limits[fac_number],
                                           category=label)
                db.session.add(data)

    write_limits(MatchingEnumeration.SUPERVISOR_LIMITS, sup_pclass_limits)
    write_limits(MatchingEnumeration.MARKER_LIMITS, mark_pclass_limits)

    # allow exception to propgate up to calling function
    db.session.commit()


def register_matching_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_match(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise Ignore()

        with Timer() as create_time:
            number_sel, number_lp, number_sup, number_mark, \
            sel_to_number, lp_to_number, sup_to_number, mark_to_number, \
            number_to_sel, number_to_lp, number_to_sup, number_to_mark, \
            sel_dict, lp_dict, lp_group_dict, sup_dict, mark_dict, \
            sup_only_numbers, mark_only_numbers, sup_and_mark_numbers, \
            sup_limits, sup_pclass_limits, mark_limits, mark_pclass_limits, \
            multiplicity, capacity, \
            mean_CATS_per_project, CATS_supervisor, CATS_marker, \
            R, W, cstr, M, marker_valence, P = _initialize(self, record)

            base_X, base_Y, base_S, has_base_match = _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number,
                                                                     mark_to_number)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                            autocommit=True)

            prob, X, Y, S = _create_PuLP_problem(R, M, marker_valence, W, P, cstr, base_X, base_Y, base_S,
                                                 has_base_match, record.force_base, CATS_supervisor, CATS_marker,
                                                 capacity, sup_limits, sup_pclass_limits, mark_limits,
                                                 mark_pclass_limits, multiplicity, number_lp, number_mark, number_sel,
                                                 number_sup, record, sel_dict, sup_dict, mark_dict, lp_dict,
                                                 lp_group_dict, sup_only_numbers, mark_only_numbers,
                                                 sup_and_mark_numbers, mean_CATS_per_project)

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        return _execute_live(self, record, prob, X, Y, S, W, R, create_time, number_sel, number_to_sel, number_lp,
                             number_to_lp, number_sup, number_to_sup, number_mark, number_to_mark, sel_dict, lp_dict,
                             sup_dict, mark_dict, multiplicity, mean_CATS_per_project)


    @celery.task(bind=True, default_retry_delay=30)
    def offline_match(self, matching_id, user_id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=matching_id))

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            record = db.session.query(MatchingAttempt).filter_by(id=matching_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load owning User record')
            raise Ignore()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise Ignore()

        with Timer() as create_time:
            number_sel, number_lp, number_sup, number_mark, \
            sel_to_number, lp_to_number, sup_to_number, mark_to_number, \
            number_to_sel, number_to_lp, number_to_sup, number_to_mark, \
            sel_dict, lp_dict, lp_group_dict, sup_dict, mark_dict, \
            sup_only_numbers, mark_only_numbers, sup_and_mark_numbers, \
            sup_limits, sup_pclass_limits, mark_limits, mark_pclass_limits, \
            multiplicity, capacity, \
            mean_CATS_per_project, CATS_supervisor, CATS_marker, \
            R, W, cstr, M, marker_valence, P = _initialize(self, record)

            base_X, base_Y, base_S, has_base_match = _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number,
                                                                     mark_to_number)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                            autocommit=True)

            prob, X, Y, S = _create_PuLP_problem(R, M, marker_valence, W, P, cstr, base_X, base_Y, base_S,
                                                 has_base_match, record.force_base, CATS_supervisor, CATS_marker,
                                                 capacity, sup_limits, sup_pclass_limits, mark_limits,
                                                 mark_pclass_limits, multiplicity, number_lp, number_mark, number_sel,
                                                 number_sup, record, sel_dict, sup_dict, mark_dict, lp_dict,
                                                 lp_group_dict, sup_only_numbers, mark_only_numbers,
                                                 sup_and_mark_numbers, mean_CATS_per_project)

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Writing .LP and .MPS files...", autocommit=True)

        try:
            lp_asset, mps_asset = _write_LP_MPS_files(record, prob, user)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        _send_offline_email(celery, record, user, lp_asset, mps_asset)

        progress_update(record.celery_id, TaskRecord.RUNNING, 80,
                        'Storing matching details for later processing...', autocommit=True)

        try:
            _store_enumeration_details(record, number_to_sel, number_to_lp, number_to_sup, number_to_mark,
                                       lp_group_dict, sup_pclass_limits, mark_pclass_limits)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        progress_update(record.celery_id, TaskRecord.SUCCESS, 100,
                        'File generation for offline project matching now complete', autocommit=True)
        user.post_message('The files necessary to perform offline matching have been emailed to you.',
                          'info', autocommit=True)


    @celery.task(bind=True, default_retry_delay=30)
    def process_offline_solution(self, matching_id, asset_id, user_id):
        self.update_state(state='STARTED',
                          meta='Looking up TemporaryAsset record for id={id}'.format(id=asset_id))

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
            asset = db.session.query(TemporaryAsset).filter_by(id=asset_id).first()
            record = db.session.query(MatchingAttempt).filter_by(id=matching_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load owning User record')
            raise Ignore()

        if asset is None:
            self.update_state(state='FAILURE', meta='Could not load TemporaryAsset record')
            raise Ignore()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            raise Ignore()

        with Timer() as create_time:
            number_sel, number_lp, number_sup, number_mark, \
            sel_to_number, lp_to_number, sup_to_number, mark_to_number, \
            number_to_sel, number_to_lp, number_to_sup, number_to_mark, \
            sel_dict, lp_dict, lp_group_dict, sup_dict, mark_dict, \
            sup_only_numbers, mark_only_numbers, sup_and_mark_numbers, \
            sup_limits, sup_pclass_limits, mark_limits, mark_pclass_limits, \
            multiplicity, capacity, \
            mean_CATS_per_project, CATS_supervisor, CATS_marker, \
            R, W, cstr, M, marker_valence, P = _initialize(self, record, read_serialized=True)

            base_X, base_Y, base_S, has_base_match = _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number,
                                                                     mark_to_number)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                            autocommit=True)

            prob, X, Y, S = _create_PuLP_problem(R, M, marker_valence, W, P, cstr, base_X, base_Y, base_S,
                                                 has_base_match, record.force_base, CATS_supervisor, CATS_marker,
                                                 capacity, sup_limits, sup_pclass_limits, mark_limits,
                                                 mark_pclass_limits, multiplicity, number_lp, number_mark, number_sel,
                                                 number_sup, record, sel_dict, sup_dict, mark_dict, lp_dict,
                                                 lp_group_dict, sup_only_numbers, mark_only_numbers,
                                                 sup_and_mark_numbers, mean_CATS_per_project)

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        return _execute_from_solution(self, canonical_temporary_asset_filename(asset.filename), record, prob, X, Y, S,
                                      W, R, create_time, number_sel, number_to_sel, number_lp, number_to_lp, number_sup,
                                      number_to_sup, number_mark, number_to_mark, sel_dict, lp_dict, sup_dict,
                                      mark_dict, multiplicity, mean_CATS_per_project)


    @celery.task(bind=True, default_retry_delay=30)
    def populate_markers(self, config_id, user_id, task_id):
        self.update_state(state='STARTED',
                          meta='Looking up ProjectClassConfig record for id={id}'.format(id=config_id))

        try:
            config = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(state='FAILURE', meta='Could not load ProjectClassConfig record from database')
            raise Ignore()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load User record from database')
            raise Ignore()

        with Timer() as create_time:
            mark_dict, inverse_mark_dict, submit_dict, inverse_submit_dict, mark_CATS_dict = \
                _enumerate_missing_markers(self, config, task_id, user)

            progress_update(task_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...",
                            autocommit=True)

            prob, Y = _create_marker_PuLP_problem(mark_dict, submit_dict, mark_CATS_dict, config)

        print(' -- creation complete in time {t}'.format(t=create_time.interval))

        return _execute_marker_problem(task_id, prob, Y, mark_dict, submit_dict, user)


    @celery.task(bind=True, default_retry_delay=30)
    def remove_markers(self, config_id, user_id, task_id):
        self.update_state(state='STARTED',
                          meta='Looking up ProjectClassConfig record for id={id}'.format(id=config_id))

        try:
            config = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(state='FAILURE', meta='Could not load ProjectClassConfig record from database')
            raise Ignore()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load User record from database')
            raise Ignore()

        progress_update(task_id, TaskRecord.RUNNING, 20, "Sorting SubmittingStudent records...",
                        autocommit=True)

        for period in config.periods:
            period: SubmissionPeriodRecord

            # ignore periods that are retired, closed, or have open feedback; the markers for these
            # cannot be changed
            if period.retired or period.closed or period.feedback_open:
                continue

            for sub in period.submissions:
                sub: SubmissionRecord
                sub.marker = None

        try:
            progress_update(task_id, TaskRecord.SUCCESS, 100, "Finishing remove markers task....",
                            autocommit=False)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None


    @celery.task(bind=True, default_retry_delay=30)
    def revert_record(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingRecord record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingRecord).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingRecord record from database')
            raise Ignore

        try:
            record.project_id = record.original_project_id
            record.marker_id = record.original_marker_id
            record.rank = record.selector.project_rank(record.original_project_id)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None


    @celery.task(bind=True, default_retry_delay=30)
    def revert_finalize(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            raise Ignore

        try:
            record.last_edit_id = None
            record.last_edit_timestamp = None
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None


    @celery.task(bind=True, default_retry_delay=30)
    def revert(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            raise Ignore

        wg = group(revert_record.si(r.id) for r in record.records.all())
        seq = chain(wg, revert_finalize.si(id))

        seq.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def duplicate(self, id, new_name, current_id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            raise Ignore

        # encapsulate the whole duplication process in a single transaction, so the process is as close to
        # atomic as we can make it

        try:
            # generate a new MatchingRecord
            data = MatchingAttempt(year=record.year,
                                   base_id=record.base_id,
                                   base_bias=record.base_bias,
                                   force_base=record.force_base,
                                   name=new_name,
                                   config_members=record.config_members,
                                   published=record.published,
                                   selected=False,
                                   celery_id=None,
                                   finished=record.finished,
                                   celery_finished=True,
                                   awaiting_upload=record.awaiting_upload,
                                   outcome=record.outcome,
                                   solver=record.solver,
                                   construct_time=record.construct_time,
                                   compute_time=record.compute_time,
                                   include_only_submitted=record.include_only_submitted,
                                   ignore_per_faculty_limits=record.ignore_per_faculty_limits,
                                   ignore_programme_prefs=record.ignore_programme_prefs,
                                   years_memory=record.years_memory,
                                   supervising_limit=record.supervising_limit,
                                   marking_limit=record.marking_limit,
                                   max_marking_multiplicity=record.max_marking_multiplicity,
                                   max_different_group_projects=record.max_different_group_projects,
                                   max_different_all_projects=record.max_different_all_projects,
                                   use_hints=record.use_hints,
                                   require_to_encourage=record.require_to_encourage,
                                   forbid_to_discourage=record.forbid_to_discourage,
                                   encourage_bias=record.encourage_bias,
                                   discourage_bias=record.discourage_bias,
                                   strong_encourage_bias=record.strong_encourage_bias,
                                   strong_discourage_bias=record.strong_discourage_bias,
                                   bookmark_bias=record.bookmark_bias,
                                   levelling_bias=record.levelling_bias,
                                   supervising_pressure=record.supervising_pressure,
                                   marking_pressure=record.marking_pressure,
                                   CATS_violation_penalty=record.CATS_violation_penalty,
                                   no_assignment_penalty=record.no_assignment_penalty,
                                   intra_group_tension=record.intra_group_tension,
                                   programme_bias=record.programme_bias,
                                   include_matches=record.include_matches,
                                   score=record.current_score,  # note that current score becomes original score
                                   supervisors=record.supervisors,
                                   markers=record.markers,
                                   projects=record.projects,
                                   mean_CATS_per_project=record.mean_CATS_per_project,
                                   creator_id=current_id,
                                   creation_timestamp=datetime.now(),
                                   last_edit_id=None,
                                   last_edit_timestamp=None,
                                   lp_file_id=None,
                                   mps_file_id=None)

            db.session.add(data)
            db.session.flush()

            # duplicate all matching records
            for item in record.records:
                rec = MatchingRecord(matching_id=data.id,
                                     selector_id=item.selector_id,
                                     submission_period=item.submission_period,
                                     project_id=item.project_id,
                                     original_project_id=item.project_id,
                                     rank=item.rank,
                                     marker_id=item.marker_id,
                                     original_marker_id=item.marker_id)
                db.session.add(rec)

            # duplicate all enumerations
            if data.awaiting_upload:
                for item in record.enumerations:
                    en = MatchingEnumeration(category=item.category,
                                             enumeration=item.enumeration,
                                             key=item.key,
                                             key2=item.key2,
                                             matching_id=data.id)
                    db.session.add(en)

                now = datetime.now()

                def copy_asset(old_asset, target, ext=None):
                    old_path = canonical_generated_asset_filename(old_asset.filename)
                    new_name, new_abs_path = make_generated_asset_filename(ext=ext)

                    copyfile(old_path, new_abs_path)

                    new_asset = GeneratedAsset(timestamp=now,
                                               expiry=None,
                                               filename=str(new_name),
                                               mimetype='text/plain',
                                               target_name=target)
                    # TODO: find a way to perform a deep copy without exposing implementation details
                    new_asset.access_control_list = old_asset.access_control_list
                    new_asset.access_control_roles = old_asset.access_control_roles
                    db.session.add(new_asset)

                    return new_asset

                if record.lp_file is not None:
                    data.lp_file = copy_asset(record.lp_file, 'matching.lp', ext='lp')

                if record.mps_file is not None:
                    data.mps_file = copy_asset(record.mps_file, 'matching.mps', ext='mps')

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None
