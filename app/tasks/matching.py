#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import base64
import itertools
from datetime import datetime, timedelta
from io import BytesIO
from os import path
from pathlib import Path
from typing import List

import pulp
import pulp.apis as pulp_apis
from celery import group, chain
from celery.exceptions import Ignore
from flask import current_app, render_template, render_template_string
from flask_mailman import EmailMultiAlternatives
from pandas import DataFrame
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    MatchingAttempt,
    TaskRecord,
    LiveProject,
    SelectingStudent,
    User,
    EnrollmentRecord,
    MatchingRecord,
    SelectionRecord,
    ProjectClass,
    GeneratedAsset,
    MatchingEnumeration,
    TemporaryAsset,
    FacultyData,
    ProjectClassConfig,
    SubmissionRecord,
    SubmissionPeriodRecord,
    MatchingRole,
    SubmissionPeriodDefinition,
    SubmittingStudent,
    SubmissionRole,
    validate_nonce,
    CustomOffer,
    Project,
    LiveProjectAlternative,
    StudentData,
    DegreeProgramme,
)
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.scratch import ScratchFileManager
from ..shared.sqlalchemy import get_count
from ..shared.timer import Timer
from ..shared.utils import get_current_year
from ..task_queue import progress_update, register_task

FALLBACK_DEFAULT_SUPERVISOR_CATS = 35
FALLBACK_DEFAULT_MARKER_CATS = 3
FALLBACK_DEFAULT_MODERATOR_CATS = 3

# should be a large enough number that capacity for a project is effectively unbounded
UNBOUNDED_SUPERVISING_CAPACITY = 100
UNBOUNDED_MARKING_CAPACITY = 100


_match_success = """
<div><strong>Matching task {{ name }} has completed successfully.</strong></div>
<div class="mt-2">This page does not auto-update.
Please click <a href="{{ url_for('admin.manage_matching') }}" onclick="setTimeout(location.reload.bind(location), 1)">here</a> to refresh or view the matching list.</div>
"""


_match_failure = """
<div><strong>Matching task {{ name }} did not complete successfully.</strong></div>
<div class="mt-2">This page does not auto-update.
Please click <a href="{{ url_for('admin.manage_matching') }}" onclick="setTimeout(location.reload.bind(location), 1)">here</a> to refresh or view the matching list.</div>
"""


_match_offline_ready = """
<div><strong>The files necessary to perform offline matching for task {{ name }} have now been generated.</strong></div>
<div class="mt-2">These files have been emailed to you, but you can also download them from the matching list.</div>
<div class="mt-2">This page does not auto-update.
Please click <a href="{{ url_for('admin.manage_matching') }}" onclick="setTimeout(location.reload.bind(location), 1)">here</a> to refresh or view the matching list.</div>
"""


def _find_mean_project_CATS(configs):
    CATS_total = 0
    number = 0

    for config in configs:
        if config.uses_supervisor and config.CATS_supervision is not None:
            CATS_total += config.CATS_supervision
            number += 1

    return float(CATS_total) / number


def _min(a, b):
    if a is None and b is None:
        return None

    if a is None:
        return b

    if b is None:
        return a

    return a if a <= b else b


def _pulp_dicts(
    name,
    indices=None,  # required param. enforced within function for backwards compatibility
    lowBound=None,
    upBound=None,
    cat=pulp.const.LpContinuous,
    indexStart=[],
    indexs=None,
):
    """
    Re-implementation of pulp.LpVariable.dicts to use list comprehension rather than a for-loop, which
    is absurdly slow for large index sets

    :param name: The prefix to the name of each LP variable created
    :param indices: A list of strings of the keys to the dictionary of LP
        variables, and the main part of the variable name itself
    :param lowBound: The lower bound on these variables' range. Default is
        negative infinity
    :param upBound: The upper bound on these variables' range. Default is
        positive infinity
    :param cat: The category these variables are in, Integer or
        Continuous(default)
    :param indexs: (deprecated) Replaced with `indices` parameter

    :return: A dictionary of :py:class:`LpVariable`
    """

    # Backwards compatiblity with deprecation Warning for indexs
    if indices is not None and indexs is not None:
        raise TypeError("Both 'indices' and 'indexs' provided to LpVariable.dicts.  Use one only, preferably 'indices'.")
    elif indices is not None:
        pass
    elif indexs is not None:
        indices = indexs
    else:
        raise TypeError("LpVariable.dicts missing both 'indices' and deprecated 'indexs' arguments.")

    if not isinstance(indices, tuple):
        indices = (indices,)
    if "%" not in name:
        name += "_%s" * len(indices)

    index = indices[0]
    indices = indices[1:]

    if len(indices) == 0:
        d = {i: pulp.LpVariable(name % tuple(indexStart + [str(i)]), lowBound, upBound, cat) for i in index}
    else:
        d = {i: _pulp_dicts(name, indices, lowBound, upBound, cat, indexStart + [i]) for i in index}

    return d


def _enumerate_selectors(record, configs, read_serialized=False):
    """
    Build a list of SelectingStudents who belong to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute assignment multiplicity for each selector, i.e. how many projects they should be
    assigned (e.g. FYP = 1 but MPP = 2 since projects only last one term)
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

    record_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.SELECTOR, matching_id=record.id).subquery()
    records = (
        db.session.query(record_data.c.enumeration, SelectingStudent)
        .select_from(SelectingStudent)
        .join(record_data, record_data.c.key == SelectingStudent.id)
        .order_by(record_data.c.enumeration.asc())
        .all()
    )

    for n, sel in records:
        n: int
        sel: SelectingStudent

        sel_to_number[sel.id] = n
        number_to_sel[n] = sel.id

        number_submissions = sel.config.number_submissions
        multiplicity[n] = number_submissions if number_submissions >= 1 else 1

        selector_dict[n] = sel

    return n + 1, sel_to_number, number_to_sel, multiplicity, selector_dict


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

        selectors = db.session.query(SelectingStudent).filter_by(retired=False, config_id=config.id, convert_to_submitter=True).all()

        print(
            ' :: length of raw selectors list for "{name}" '
            "(config_id={y}) = {n}".format(name=config.project_class.name, y=config.id, n=len(selectors))
        )

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
                        if opt_in_type and (
                            (enroll_previous_year and sel.academic_year == config.start_year - (1 if config.select_in_previous_cycle else 0))
                            or (enroll_any_year and config.start_year <= sel.academic_year < config.start_year + config.extent)
                        ):
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
                number_submissions = config.number_submissions
                multiplicity[number] = number_submissions if number_submissions >= 1 else 1

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

    project_dict = {}  # mapping from enumerated number to LiveProject instance
    project_group_dict = {}  # mapping from config.id to list of LiveProject.ids associated with it

    record_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.LIVEPROJECT, matching_id=record.id).subquery()
    records = (
        db.session.query(record_data.c.enumeration, LiveProject)
        .select_from(LiveProject)
        .join(record_data, record_data.c.key == LiveProject.id)
        .order_by(record_data.c.enumeration.asc())
        .all()
    )

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

        capacity[n] = lp.capacity if (lp.enforce_capacity and lp.capacity is not None and lp.capacity > 0) else UNBOUNDED_SUPERVISING_CAPACITY

        project_dict[n] = lp

        # UPDATE MODERATE CATS

    group_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.LIVEPROJECT_GROUP, matching_id=record.id).all()

    for record in group_data:
        record: MatchingEnumeration

        if record.key not in project_group_dict:
            project_group_dict[record.key] = []

        project_group_dict[record.key].append(record.enumeration)

    return n + 1, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, project_dict, project_group_dict


def _enumerate_liveprojects_primary(configs):
    number = 0
    lp_to_number = {}
    number_to_lp = {}

    CATS_supervisor = {}
    CATS_marker = {}

    capacity = {}

    project_dict = {}  # mapping from enumerated number to LiveProject instance
    project_group_dict = {}  # mapping from config.id to list of LiveProject.ids associated with it

    for config in configs:
        # get LiveProject instances that belong to this config instance and are associated with
        # a supervisor who is still enrolled
        # (e.g. enrolment status may have changed since the projects went live)
        projects = (
            db.session.query(LiveProject)
            .filter(LiveProject.config_id == config.id)
            .join(ProjectClassConfig, ProjectClassConfig.id == LiveProject.config_id)
            .join(User, User.id == LiveProject.owner_id, isouter=True)
            .join(FacultyData, FacultyData.id == LiveProject.owner_id, isouter=True)
            .join(
                EnrollmentRecord,
                and_(EnrollmentRecord.owner_id == LiveProject.owner_id, EnrollmentRecord.pclass_id == ProjectClassConfig.pclass_id),
                isouter=True,
            )
            .filter(
                or_(
                    LiveProject.generic == True,
                    and_(
                        LiveProject.generic == False,
                        User.active == True,
                        FacultyData.id != None,
                        EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    ),
                )
            )
            .distinct()
            .all()
        )

        project_group_dict[config.id] = []

        for item in projects:
            item: LiveProject

            if item.id not in lp_to_number:
                lp_to_number[item.id] = number
                number_to_lp[number] = item.id

                sup = item.CATS_supervision
                mk = item.CATS_marking
                CATS_supervisor[number] = sup if sup is not None else FALLBACK_DEFAULT_SUPERVISOR_CATS
                CATS_marker[number] = mk if mk is not None else FALLBACK_DEFAULT_MARKER_CATS

                capacity[number] = (
                    item.capacity if (item.enforce_capacity and item.capacity is not None and item.capacity > 0) else UNBOUNDED_SUPERVISING_CAPACITY
                )

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

    limit = {}  # map from faculty number to global supervision CATS limit
    config_limits = {}  # map from config.id to (map from faculty number to local supervision CATS limit)

    fac_dict = {}

    # stored ids and primary keys refer to FacultyData instances, not EnrollmentRecord instances
    record_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.SUPERVISOR, matching_id=record.id).subquery()
    records = (
        db.session.query(record_data.c.enumeration, FacultyData)
        .select_from(FacultyData)
        .join(record_data, record_data.c.key == FacultyData.id)
        .order_by(record_data.c.enumeration.asc())
        .all()
    )

    for n, fac in records:
        n: int
        fac: FacultyData

        fac_to_number[fac.id] = n
        number_to_fac[n] = fac.id

        lim = fac.CATS_supervision
        limit[n] = lim if lim is not None and lim > 0 else 0

        fac_dict[n] = fac

    limit_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.SUPERVISOR_LIMITS, matching_id=record.id).all()

    for record in limit_data:
        record: MatchingEnumeration

        config_id = record.key
        fac_number = record.enumeration
        limit = record.key2

        if config_id not in config_limits:
            config_limits[config_id] = {}

        config_limits[config_id][fac_number] = limit

    return n + 1, fac_to_number, number_to_fac, limit, fac_dict, config_limits


def _enumerate_supervising_faculty_primary(configs):
    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}  # map from faculty number to global supervision CATS limit
    config_limits = {}  # map from config.id to (map from faculty number to local supervision CATS limit)

    fac_dict = {}

    for config in configs:
        # get EnrollmentRecord instances for this project class
        records = (
            db.session.query(EnrollmentRecord)
            .filter_by(pclass_id=config.pclass_id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED)
            .join(User, User.id == EnrollmentRecord.owner_id)
            .filter(User.active)
            .distinct()
            .all()
        )

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

    limit = {}  # map from faculty number to global marking CATS limit
    config_limits = {}  # map from config.id to (map from faculty number to local marking CATS limit)

    fac_dict = {}

    # stored ids and primary keys refer to FacultyData instances, not EnrollmentRecord instances
    record_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.MARKER, matching_id=record.id).subquery()
    records = (
        db.session.query(record_data.c.enumeration, FacultyData)
        .select_from(FacultyData)
        .join(record_data, record_data.c.key == FacultyData.id)
        .order_by(record_data.c.enumeration.asc())
        .all()
    )

    for n, fac in records:
        n: int
        fac: FacultyData

        fac_to_number[fac.id] = n
        number_to_fac[n] = fac.id

        lim = fac.CATS_marking
        limit[n] = lim if lim is not None and lim > 0 else 0

        fac_dict[n] = fac

    limit_data = db.session.query(MatchingEnumeration).filter_by(category=MatchingEnumeration.MARKER_LIMITS, matching_id=record.id).all()

    for record in limit_data:
        record: MatchingEnumeration

        config_id = record.key
        fac_number = record.enumeration
        limit = record.key2

        if config_id not in config_limits:
            config_limits[config_id] = {}

        config_limits[config_id][fac_number] = limit

    return n + 1, fac_to_number, number_to_fac, limit, fac_dict, config_limits


def _enumerate_marking_faculty_primary(configs):
    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}  # map from faculty number to global marking CATS limit
    config_limits = {}  # map from config.id to (map from faculty number to local marking CATS limit)

    fac_dict = {}

    for config in configs:
        # get EnrollmentRecord instances for this project class
        records = (
            db.session.query(EnrollmentRecord)
            .filter_by(pclass_id=config.pclass_id, marker_state=EnrollmentRecord.MARKER_ENROLLED)
            .join(User, User.id == EnrollmentRecord.owner_id)
            .filter(User.active)
            .distinct()
            .all()
        )

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

    R = {}  # R is ranking matrix. Accounts for Forbid hints.
    W = {}  # W is weights matrix. Accounts for encourage & discourage hints, programme bias and bookmark bias

    cstr = set()  # cstr is a set of (student, project) pairs that will be converted into Require hints

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

    base_alternative_rank = 1
    for config in record.config_members:
        config: ProjectClassConfig
        largest_rank = max(config.initial_choices, config.switch_choices if config.allow_switching else 0)
        if largest_rank > base_alternative_rank:
            base_alternative_rank = largest_rank

    for i in range(0, number_sel):
        sel: SelectingStudent = sel_dict[i]

        ranks = {}
        weights = {}
        alternatives = {}
        require = set()

        # if this selector has accepted an offer, we want to force assignment to that offer
        # so we include only the accepted offer in the ranking matrix
        if sel.has_accepted_offers():
            offers: List[CustomOffer] = sel.accepted_offers()
            for offer in offers:
                project: Project = offer.liveproject

                if project.id in lp_to_number:
                    ranks[project.id] = 1
                    require.add(project.id)
                else:
                    raise RuntimeError(
                        'Could not assign custom offer to selector "{name}" because target LiveProject '
                        "does not exist".format(name=sel.student.user.name)
                    )

        # otherwise, we want to work through the student's entire submission list, keeping track of the ranks
        elif sel.has_submission_list:
            valid_projects = 0

            for item in sel.ordered_selections:
                item: SelectionRecord
                if item.liveproject_id in lp_to_number:
                    valid_projects += 1

                    hint = item.hint

                    if not use_hints or forbid_to_discourage or hint != SelectionRecord.SELECTION_HINT_FORBID:
                        ranks[item.liveproject_id] = item.rank

                    # determine weight for this allocation
                    w = 1.0
                    if item.converted_from_bookmark:
                        w *= bookmark_bias
                    if use_hints:
                        if hint == SelectionRecord.SELECTION_HINT_ENCOURAGE:
                            w *= encourage_bias
                        elif hint == SelectionRecord.SELECTION_HINT_DISCOURAGE:
                            w *= discourage_bias
                        elif hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG or (
                            require_to_encourage and hint == SelectionRecord.SELECTION_HINT_REQUIRE
                        ):
                            w *= strong_encourage_bias
                        elif hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG or (
                            forbid_to_discourage and hint == SelectionRecord.SELECTION_HINT_FORBID
                        ):
                            w *= strong_discourage_bias

                    weights[item.liveproject_id] = w

                    if use_hints and not require_to_encourage and hint == SelectionRecord.SELECTION_HINT_REQUIRE:
                        require.add(item.liveproject_id)

                    # record alternatives, provided this selection has not been forbidden
                    if item.liveproject is not None and (not use_hints or hint != SelectionRecord.SELECTION_HINT_FORBID):
                        for alt in item.liveproject.alternatives:
                            alt: LiveProjectAlternative

                            if alt.alternative_id in lp_to_number:
                                # don't overwrite priority if a higher-priority record already exists
                                new_priority = max(alt.priority, alternatives.get(alt.alternative_id, 0))
                                alternatives[alt.alternative_id] = new_priority

            if valid_projects == 0:
                raise RuntimeError(
                    'Could not build rank matrix for selector "{name}" because no LiveProjects '
                    "on their preference list exist".format(name=sel.student.user.name)
                )

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
            elif proj.id in alternatives:
                # alternatives should count has higher-order rankings
                R[idx] = base_alternative_rank + alternatives[proj.id]
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
                    errmsg = (
                        "Inconsistent number of second markers in match to LiveProject: "
                        "fac={fname}, proj={pname}, matches={c}, "
                        "LiveProject.id={lpid}, "
                        "FacultyData.id={fid}".format(fname=fac.user.name, pname=proj.name, c=count, lpid=proj.id, fid=fac.id)
                    )

                    print("!! {msg}".format(msg=errmsg))
                    print("!! LiveProject Assessor List")
                    for f in proj.assessor_list:
                        f: FacultyData
                        print("!! - {name} id={fid}".format(name=f.user.name, fid=f.id))

                    raise RuntimeError(errmsg)

            else:
                M[idx] = 0

    # how many markers do we actually have to assign for a project of type j? This depends on how many
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
                    errmsg = (
                        "Inconsistent number of possible supervisors for group project in match to LiveProject: "
                        "fac={fname}, proj={pname}, matches={c}, "
                        "LiveProject.id={lpid}, "
                        "FacultyData.id={fid}".format(fname=fac.user.name, pname=proj.name, c=count, lpid=proj.id, fid=fac.id)
                    )

                    print("!! {msg}".format(msg=errmsg))
                    print("!! LiveProject Assessor List")
                    for f in proj.assessor_list:
                        f: FacultyData
                        print("!! - {name} id={fid}".format(name=f.user.name, fid=f.id))

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

    progress_update(task_id, TaskRecord.RUNNING, 10, "Enumerating submission records with missing records...", autocommit=True)

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
                progress_update(
                    task_id,
                    TaskRecord.FAILURE,
                    100,
                    'Failed because LiveProject "{name}" has no ' "active assessors".format(name=sub.project.name),
                    autocommit=True,
                )
                user.post_message(
                    'Failed to populate markers because LiveProject "{name}" has no active ' "assessors.".format(name=sub.project.name),
                    "error",
                    autocommit=True,
                )
                self.update_state("FAILURE", meta={"msg": "LiveProject did not have active assessors"})
                raise Ignore()

            for marker in assessors:
                marker: FacultyData

                if marker not in inverse_mark_dict:
                    mark_dict[number_markers] = marker
                    inverse_mark_dict[marker] = number_markers
                    mark_CATS_dict[number_markers] = sum(marker.CATS_assignment(config))
                    number_markers += 1

    return mark_dict, inverse_mark_dict, submit_dict, inverse_submit_dict, mark_CATS_dict


def _floatify(item):
    if item is None:
        return None

    if isinstance(item, float):
        return item

    return float(item)


def _create_PuLP_problem(
    R,
    M,
    marker_valence,
    W,
    P,
    cstr,
    base_X,
    base_Y,
    base_S,
    has_base_match,
    force_base,
    CATS_supervisor,
    CATS_marker,
    capacity,
    sup_limits,
    sup_pclass_limits,
    mark_limits,
    mark_pclass_limits,
    multiplicity,
    number_lp,
    number_mark,
    number_sel,
    number_sup,
    record,
    sel_dict,
    sup_dict,
    mark_dict,
    lp_dict,
    lp_group_dict,
    sup_only_numbers,
    mark_only_numbers,
    sup_and_mark_numbers,
    mean_CATS_per_project,
):
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

    # SELECTOR DECISION VARIABLES

    progress_update(record.celery_id, TaskRecord.RUNNING, 22, "Creating decision variables...", autocommit=True)

    with Timer() as variable_timer:
        # generate decision variables for project assignment matrix
        # the indices are (selector, project) and the entries of the matrix are either 0 or 1,
        # 0 = selector not assigned to project
        # 1 = selector assigned to project

        with Timer() as X_timer:
            X = _pulp_dicts("X", itertools.product(range(number_sel), range(number_lp)), cat=pulp.LpBinary)
        print(" ** created X[i,j] matrix ({num} elements) in time {t}".format(t=X_timer.interval, num=len(X)))

        # SUPERVISOR DECISION VARIABLES

        # generate decision variables for supervisor assignment matrix
        # the indices are (supervisor, project) and the entries of the matrix are integers representing
        # the number of times a supervisor has been assigned to a project (depending on the number of students
        # who are assigned)
        # value = number of times assigned to this project. Can't be negative.
        with Timer() as S_timer:
            S = _pulp_dicts("S", itertools.product(range(number_sup), range(number_lp)), cat=pulp.LpInteger, lowBound=0)
        print(" ** created S[k,j] ({num} elements) matrix in time {t}".format(t=S_timer.interval, num=len(S)))

        # SUMMARY DECISION VARIABLES FOR SUPERVISORS

        # boolean version of S indicating whether a supervisor has any assignments to a particular project
        with Timer() as ss_timer:
            ss = _pulp_dicts("ss", itertools.product(range(number_sup), range(number_lp)), cat=pulp.LpBinary)
        print(" ** created ss[k,j] ({num} elements) matrix in time {t}".format(t=ss_timer.interval, num=len(ss)))

        # generate auxiliary variables that track whether a given supervisor has any projects assigned or not
        # 0 = none assigned
        # 1 = at least one assigned (obtained by biasing the optimizer to produce this from the objective function)
        with Timer() as Z_timer:
            Z = _pulp_dicts("Z", range(number_sup), cat=pulp.LpBinary)
        print(" ** created Z[k] ({num} elements) matrix in time {t}".format(t=Z_timer.interval, num=len(Z)))

        # MARKER DECISION VARIABLES

        # generate decision variables for marker assignment matrix
        # the indices are (marker, project, selector) and the entries are boolean variables.
        # We need this level of granularity to ensure that each selector has an appropriate number of
        # different markers assigned to their project.
        # Notice that the same marker can be assigned to mark more than one instance of a particular project
        # (e.g. different students submitting reports for the same project). The maximum multiplicity is
        # controlled by the marking matrix M
        # 0 = marker not assigned to this selector/project pair
        # 1 = marker assigned to this selector/project pair
        with Timer() as Y_timer:
            Y = _pulp_dicts("Y", itertools.product(range(number_mark), range(number_lp), range(number_sel)), cat=pulp.LpBinary)
        print(" ** created Y[i,j,l] ({num} elements) matrix in time {t}".format(t=Y_timer.interval, num=len(Y)))

        # SUMMARY DECISION VARIABLES FOR MARKERS

        # On its own, Y[i,j,l] turns the LP problem into something cubic, because we are going to need three
        # nested loops to explore its index space. This makes setting up the LP problem in PuLP too expensive
        # when the optimization becomes large (as it now does for e.g. the Data Science MSc).
        # Instead, we need some auxiliary variables to let us write expressions more economically.
        # First, Ysel[i, j] slices Y[i,j,l] by summing over selectors l at fixed i,j
        with Timer() as Ysel_timer:
            Ysel = _pulp_dicts("Ysel", itertools.product(range(number_mark), range(number_lp)), cat=pulp.LpInteger, lowBound=0)
        print(" ** created Ysel[i,j] ({num} elements) matrix in time {t}".format(t=Ysel_timer.interval, num=len(Ysel)))

        # Then, Ymark[l, j] slices Y[i,j,l] by summing over markers i at fixed j, l
        with Timer() as Ymark_timer:
            Ymark = _pulp_dicts("Ymark", itertools.product(range(number_sel), range(number_lp)), cat=pulp.LpInteger, lowBound=0)
        print(" ** created Ymark[l,j] ({num} elements) matrix in time {t}".format(t=Ymark_timer.interval, num=len(Ymark)))

        # boolean version of Y indicating whether a marker has any assignments to a particular project
        with Timer() as yy_timer:
            yy = _pulp_dicts("yy", itertools.product(range(number_mark), range(number_lp)), cat=pulp.LpBinary)
        print(" ** created yy[i,j] ({num} elements) matrix in time {t}".format(t=yy_timer.interval, num=len(yy)))

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
        sup_elastic_CATS = _pulp_dicts("A", range(number_sup), cat=pulp.LpContinuous, lowBound=0)
        mark_elastic_CATS = _pulp_dicts("B", range(number_mark), cat=pulp.LpContinuous, lowBound=0)

    print(" -- created decision variables in time {t}".format(t=variable_timer.interval))

    # OBJECTIVE FUNCTION

    progress_update(record.celery_id, TaskRecord.RUNNING, 23, "Building objective function for optimization...", autocommit=True)

    with Timer() as obj_timer:
        # tension top and bottom workloads in each group against each other
        group_levelling = (supMax - supMin) + (markMax - markMin) + (supMarkMax - supMarkMin)
        global_levelling = globalMax - globalMin

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
        elastic_CATS_penalty = abs(CATS_violation_penalty) * (
            sum(sup_elastic_CATS[i] for i in range(number_sup)) + sum(mark_elastic_CATS[i] for i in range(number_mark))
        )

        # we also impose a penalty for every supervisor who does not have any project assignments
        no_assignment_penalty = 2.0 * abs(no_assignment_penalty) * sum(1 - Z[i] for i in range(number_sup))

        prob += (
            _build_score_function(R, W, X, Y, S, number_lp, number_sel, number_sup, number_mark, base_X, base_Y, base_S, has_base_match, base_bias)
            - group_levelling_term
            - global_levelling_term
            - marking_bias
            - no_assignment_penalty
            - supervising_bias
            - elastic_CATS_penalty,
            "objective",
        )

    print(" -- created objective function in time {t}".format(t=obj_timer.interval))

    # STUDENT RANKING

    progress_update(record.celery_id, TaskRecord.RUNNING, 26, "Setting up student ranking constraints...", autocommit=True)

    with Timer() as sel_timer:
        # selectors can only be assigned to projects that they have ranked
        # (unless no ranking data was available, in which case all elements of R were set to 1)
        for l in range(number_sel):
            sel: SelectingStudent = sel_dict[l]
            user: User = sel.student.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                if proj.generic or proj.owner is None:
                    tag = "generic"
                else:
                    user_owner: User = proj.owner.user
                    tag = "{first}{last}".format(first=user_owner.first_name, last=user_owner.last_name)

                prob += X[(l, j)] <= R[(l, j)], "_C{first}{last}_rank_SC{scfg}_C{cfg}_{tag}_P{num}".format(
                    first=user.first_name, last=user.last_name, scfg=sel.config_id, cfg=proj.config_id, num=proj.number, tag=tag
                )

        # Enforce desired multiplicity (= total number of projects to be assigned) for each selector
        # typically this is one project per submission period
        for l in range(number_sel):
            sel: SelectingStudent = sel_dict[l]
            user: User = sel.student.user

            prob += sum(X[(l, j)] for j in range(number_lp)) == multiplicity[l], "_C{first}{last}_SC{scfg}_assign".format(
                first=user.first_name, last=user.last_name, scfg=sel.config_id
            )

        # Add constraints for any matches marked 'require' by a convenor
        for idx in cstr:
            l = idx[0]
            j = idx[1]
            sel: SelectingStudent = sel_dict[l]
            proj: LiveProject = lp_dict[j]
            user: User = sel.student.user

            # impose 'force' constraints, where we require a student to be allocated a particular project
            prob += X[idx] == 1, "_C{first}{last}_SC{scfg}_force_C{cfg}_P{num}".format(
                first=user.first_name, last=user.last_name, scfg=sel.config_id, cfg=proj.config_id, num=proj.number
            )

        # Implement any "force" constraints from base match
        if force_base:
            for idx in base_X:
                l = idx[0]
                j = idx[1]

                sel: SelectingStudent = sel_dict[l]
                proj: LiveProject = lp_dict[j]
                user: User = sel.student.user

                prob += X[idx] == 1, "_C{first}{last}_SC{scfg}_base_proj_C{cfg}_P{num}".format(
                    first=user.first_name, last=user.last_name, scfg=sel.config_id, cfg=proj.config_id, num=proj.number
                )

    print(" -- created selector ranking constraints in time {t}".format(t=sel_timer.interval))

    # SUPERVISOR ASSIGNMENTS

    progress_update(record.celery_id, TaskRecord.RUNNING, 35, "Setting up supervisor assignment constraints...", autocommit=True)

    with Timer() as sup_timer:
        # Supervisors can only be assigned to projects that they supervise, or to group/generic projects
        # for which they are in the supervisor pool
        for k in range(number_sup):
            sup: FacultyData = sup_dict[k]
            user: User = sup.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                # enforce maximum capacity for each project; each supervisor should have no more assignments than
                # the specified project capacity
                # print(f"Supervisor: {user.first_name} {user.last_name}, config_id = {proj.config_id}, project number = {proj.number}")
                prob += S[(k, j)] <= capacity[j] * P[(k, j)], "_CS{first}{last}_C{cfg}_P{num}_supv_capacity".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

        # ss[k,j] should be zero if supervisor k has no assignments to project j, and otherwise 1
        for k in range(number_sup):
            sup: FacultyData = sup_dict[k]
            user: User = sup.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                # force ss[k,j] to be zero if S[k,j] is zero
                prob += ss[(k, j)] <= S[(k, j)], "_Css{first}{last}_C{cfg}_P{num}_supv_assigned_upperb".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

                # force ss[k,j] to be 1 if S[k,j] is not zero. There doesn't seem to be a really elegant, clean
                # way to do this in mixed integer linear programming. We assume that S[k,j] never gets as large as
                # UNBOUNDED_SUPERVISING_CAPACITY, and then S[k,j]/UNBOUNDED_SUPERVISING_CAPACITY will be less than unity but greater than
                # zero whenver S[k,j] is not zero
                prob += UNBOUNDED_SUPERVISING_CAPACITY * ss[(k, j)] >= S[(k, j)], "_Css{first}{last}_C{cfg}_P{num}_supv_assigned_lowerb".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

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
                prob += sum(S[(k, j)] * P[(k, j)] for k in range(number_sup)) == sum(
                    X[(i, j)] for i in range(number_sel)
                ), "_CS_C{cfg}_P{num}_supv_parity".format(cfg=proj.config_id, num=proj.number)

            else:
                # enforce no supervisors assigned to this project
                prob += sum(S[(k, j)] for k in range(number_sup)) == 0, "_CS_C{cfg}_P{num}_nosupv".format(cfg=proj.config_id, num=proj.number)

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

                all_projects += ss[(k, j)]
                if proj.generic:
                    group_projects += ss[(k, j)]

            group_limit = record.max_different_group_projects
            if group_limit is not None and group_limit > 0:
                prob += group_projects <= group_limit, "_C{first}{last}_group_limit".format(first=user.first_name, last=user.last_name)

            all_limit = record.max_different_all_projects
            if all_limit is not None and all_limit > 0:
                if group_limit is not None and group_limit > all_limit:
                    all_limit = group_limit

                prob += all_projects <= all_limit, "_C{first}{last}_all_limit".format(first=user.first_name, last=user.last_name)

        # Z[k] should be constrained to be 0 if supervisor k is not assigned to any projects
        for k in range(number_sup):
            sup: FacultyData = sup_dict[k]
            user: User = sup.user

            # force Z[k] to be zero if no projects are assigned to supervisor k
            prob += Z[k] <= sum(S[(k, j)] for j in range(number_lp)), "_CZ{first}{last}_upperb".format(first=user.first_name, last=user.last_name)

            # force Z[k] to be 1 if any project is assigned to supervisor k
            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                prob += Z[k] >= ss[(k, j)], "_CZ{first}{last}_C{cfg}_P{num}_lowerb".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

    print(" -- created supervisor constraints in time {t}".format(t=sup_timer.interval))

    ## MARKER ASSIGNMENTS

    progress_update(record.celery_id, TaskRecord.RUNNING, 40, "Setting up marker assignment constraints...", autocommit=True)

    with Timer() as mark_timer:
        # Markers can only be assigned projects for which they are in the assessor pool
        for i in range(number_mark):
            mark: FacultyData = mark_dict[i]
            user: User = mark.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                # recall M[(i,j)] is the allowed multiplicity (i.e. maximum number of times marker i can be assigned
                # to mark a report from project j)
                prob += sum(Y[(i, j, l)] for l in range(number_sel)) <= M[(i, j)], "_CM{first}{last}_C{cfg}_P{num}_mark_capacity".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

        # Ysel[i,j] should slice Y[i,j,l] by summing over selectors l at fixed i and j
        for i in range(number_mark):
            mark: FacultyData = mark_dict[i]
            user: User = mark.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                prob += Ysel[(i, j)] == sum(Y[(i, j, l)] for l in range(number_sel)), "_CYsel{first}{last}_C{cfg}_P{num}".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

        # Ymark[l,j] should slice Y[i,j,l] by summing over markers i at fixed j and l
        for l in range(number_sel):
            sel: SelectingStudent = sel_dict[l]
            user: User = sel.student.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                prob += Ymark[(l, j)] == sum(Y[(i, j, l)] for i in range(number_mark)), "_CYmark_sel{sel}_C{cfg}_P{num}".format(
                    sel=user.id, cfg=proj.config_id, num=proj.number
                )

        # yy[i,j] should be zero if marker i has no assignments to project j, and otherwise 1
        for i in range(number_mark):
            mark: FacultyData = mark_dict[i]
            user: User = mark.user

            for j in range(number_lp):
                proj: LiveProject = lp_dict[j]

                # force yy[i,j] to be zero if Y[i,j,l] is zero for all selector l
                prob += yy[(i, j)] <= Ysel[(i, j)], "_Cyy{first}{last}_C{cfg}_P{num}_mark_assigned_upperb".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

                # force yy[i,j] to be 1 if Y[i,j,l] is not zero for any selector l
                # as above, there is no clean way to enforce this, so we use the UNBOUNDED_MARKING_CAPACITY
                # dodge with UNBOUNDED_MARKING_CAPACITY set to a suitable large value
                prob += UNBOUNDED_MARKING_CAPACITY * yy[(i, j)] >= Ysel[(i, j)], "_Cyy{first}{last}_C{cfg}_P{num}_mark_assigned_lowerb".format(
                    first=user.first_name, last=user.last_name, cfg=proj.config_id, num=proj.number
                )

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
                # for each selector, the total number of assigned markers should equal the intended valence for project j
                for l in range(number_sel):
                    sel: SelectingStudent = sel_dict[l]
                    sel_user: User = sel.student.user

                    prob += marker_valence[j] * X[(l, j)] == Ymark[(l, j)], "_CY_sel{sel}_C{cfg}_P{num}_mark_parity".format(
                        sel=sel_user.id, cfg=proj.config_id, num=proj.number
                    )

            else:
                # enforce no markers assigned to this project
                prob += sum(Ysel[(i, j)] for i in range(number_mark)) == 0, "_CY_C{cfg}_P{num}_nomark".format(cfg=proj.config_id, num=proj.number)

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

                        prob += ss[(k, j)] + yy[(i, j)] <= 1, "_C{first}{last}_C{cfg}_P{num}_supv_mark_disjoint".format(
                            first=sup_user.first_name, last=sup_user.last_name, cfg=proj.config_id, num=proj.number
                        )

        # Implement any "force" constraints from base match, if one is in use
        if force_base:
            for idx in base_Y.keys():
                i = idx[0]
                j = idx[1]
                l = idx[2]

                mark: FacultyData = mark_dict[i]
                proj: LiveProject = lp_dict[j]
                sel: SelectingStudent = sel_dict[l]

                mark_user: User = mark.user
                sel_user: User = sel.student.user

                prob += Y[idx] == base_Y[idx], "_C{first}{last}_sel{sel}_SC{scfg}_base_mark_C{cfg}_P{num}".format(
                    first=mark_user.first_name, last=mark_user.last_name, sel=sel_user.id, scfg=sel.config_id, cfg=proj.config_id, num=proj.number
                )

            # REMOVE? We don't want to force supervisior multiplicities to match the base configuration, because
            # that prevents any extra assignments for all supervisors. So this seems misguided.
            # for idx in base_S.keys():
            #     k = idx[0]
            #     j = idx[1]
            #
            #     supv: FacultyData = sup_dict[k]
            #     proj: LiveProject = lp_dict[j]
            #     user: User = supv.user
            #
            #     prob += S[idx] == base_S[idx], "_C{first}{last}_SC{scfg}_base_supv_C{cfg}_P{num}".format(
            #         first=user.first_name, last=user.last_name, scfg=sel.config_id, cfg=proj.config_id, num=proj.number
            #     )

    print(" -- created marker constraints in time {t}".format(t=mark_timer.interval))

    # WORKLOAD LIMITS

    progress_update(record.celery_id, TaskRecord.RUNNING, 45, "Setting up per-faculty workload constraints...", autocommit=True)

    with Timer() as fac_work_timer:
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
                raise RuntimeError(
                    "Inconsistent matching problem: existing supervisory CATS load {n} for faculty "
                    '"{name}" exceeds specified CATS limit'.format(n=existing_CATS, name=user.name)
                )

            prob += existing_CATS + sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) <= lim + sup_elastic_CATS[
                k
            ], "_C{first}{last}_supv_CATS".format(first=user.first_name, last=user.last_name)

            # enforce ad-hoc per-project-class supervisor limits
            for config_id in sup_pclass_limits:
                fac_limits = sup_pclass_limits[config_id]
                projects = lp_group_dict.get(config_id, None)

                if k in fac_limits and projects is not None:
                    prob += sum(S[(k, j)] * CATS_supervisor[j] for j in projects) <= fac_limits[k], "_C{first}{last}_supv_CATS_config_{cfg}".format(
                        first=user.first_name, last=user.last_name, cfg=config_id
                    )

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
                raise RuntimeError(
                    "Inconsistent matching problem: existing marking CATS load {n} for faculty "
                    '"{name}" exceeds specified CATS limit'.format(n=existing_CATS, name=mark.user.name)
                )

            prob += existing_CATS + sum(CATS_marker[j] * Ysel[(i, j)] for j in range(number_lp)) <= lim + mark_elastic_CATS[
                i
            ], "_C{first}{last}_mark_CATS".format(first=user.first_name, last=user.last_name)

            # enforce ad-hoc per-project-class marking limits
            for config_id in mark_pclass_limits:
                fac_limits = mark_pclass_limits[config_id]
                projects = lp_group_dict.get(config_id, None)

                if i in fac_limits and projects is not None:
                    prob += sum(CATS_marker[j] * Ysel[(i, j)] for j in projects) <= fac_limits[i], "_C{first}{last}_mark_CATS_config_C{cfg}".format(
                        first=user.first_name, last=user.last_name, cfg=config_id
                    )

    print(" -- created faculty workload constraints in time {t}".format(t=fac_work_timer.interval))

    # WORKLOAD LEVELLING

    progress_update(record.celery_id, TaskRecord.RUNNING, 48, "Setting up global workload levelling objectives...", autocommit=True)

    with Timer() as level_timer:
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
                prob += sum(Ysel[(i, j)] * CATS_marker[j] for j in range(number_lp)) <= markMax
                prob += sum(Ysel[(i, j)] * CATS_marker[j] for j in range(number_lp)) >= markMin

            prob += globalMin <= markMin
            prob += globalMax >= markMax

            global_trivial = False
        else:
            prob += markMax == 0
            prob += markMin == 0

        # supMarkMin and supMarkMAx should bracket the CATS workload of faculty who both supervise and mark
        if len(sup_and_mark_numbers) > 0:
            for k, i in sup_and_mark_numbers:
                prob += (
                    sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) + sum(Ysel[(i, j)] * CATS_marker[j] for j in range(number_lp))
                    <= supMarkMax
                )
                prob += (
                    sum(S[(k, j)] * CATS_supervisor[j] for j in range(number_lp)) + sum(Ysel[(i, j)] * CATS_marker[j] for j in range(number_lp))
                    >= supMarkMin
                )

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
                prob += sum(Ysel[(i, j)] for j in range(number_lp)) <= maxMarking
        else:
            prob += maxMarking == 0

    print(" -- created workload levelling objectives in time {t}".format(t=level_timer.interval))

    return prob, X, Y, S


def _build_score_function(R, W, X, Y, S, number_lp, number_sel, number_sup, number_mark, base_X, base_Y, base_S, has_base_match, base_bias):
    # generate score function, used as a component of the maximization objective
    objective = 0

    fbase_bias = None

    if len(base_X) > 0 or len(base_Y) > 0 or len(base_S) > 0:
        if base_bias is None:
            raise RuntimeError("base_bias = None in _build_score_function")
        else:
            fbase_bias = float(base_bias)
            print("-- using base bias of {f}".format(f=fbase_bias))

    # reward the solution for assigning students to highly ranked projects:
    for i in range(number_sel):
        base_match_exists = i in has_base_match
        if base_match_exists:
            print("-- using base match data for selector {n}".format(n=i))

        for j in range(number_lp):
            idx = (i, j)

            if base_match_exists:
                # an assignment for selector i was present in the base, but we don't know whether it was for
                # this project.

                if idx in base_X:
                    # an assignment to this project *was* already in the base, so bias it to be present here
                    objective += fbase_bias * X[idx]
                else:
                    # an assignment to this project was *not* already in the base, so bias it to be absent here
                    objective += fbase_bias * (1 - X[idx])
            else:
                # no assignment for selector i was present in the base

                if R[idx] > 0:
                    # score is 1/rank of assigned project, weighted
                    objective += X[idx] * W[idx] / R[idx]

    # bias towards any marking choices from base match
    if len(base_Y) > 0:
        for i in range(number_mark):
            for j in range(number_lp):
                for l in range(number_sel):
                    idx = (i, j, l)

                    if idx in base_Y:
                        # bias Y assignment towards the multiplicity found in the base
                        m = base_Y[idx]
                        objective += fbase_bias * (Y[idx] - int(m))
                    else:
                        # bias Y assignment towards Y = 0
                        objective += fbase_bias * (1 - Y[idx])

    # bias towards any supervising choices from base match
    if len(base_S) > 0:
        for k in range(number_sup):
            for j in range(number_lp):
                idx = (k, j)

                if idx in base_S:
                    # bias S assignment towards the multiplicity found in the base
                    m = base_S[idx]
                    objective += fbase_bias * (S[idx] - int(m))
                else:
                    # bias Y assignment towards S=0
                    objective += fbase_bias * (1 - S[idx])

    return objective


def _store_PuLP_solution(
    X,
    Y,
    S,
    record: MatchingAttempt,
    number_sel,
    number_to_sel,
    number_lp,
    number_to_lp,
    number_sup,
    number_to_sup,
    number_mark,
    number_to_mark,
    multiplicity,
    sel_dict,
    sup_dict,
    mark_dict,
    lp_dict,
    mean_CATS_per_project,
):
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
    with Timer() as config_timer:
        for item in sup_dict.values():
            if item not in record.supervisors:
                record.supervisors.append(item)

        for item in mark_dict.values():
            if item not in record.markers:
                record.markers.append(item)

        for item in lp_dict.values():
            if item not in record.projects:
                record.projects.append(item)

    print(" ** updated MatchingAttempt configuration data in time {t}".format(t=config_timer.interval))

    record.mean_CATS_per_project = mean_CATS_per_project

    # generate dictionary of supervisor assignments: we map each project id to a list of supervisors
    with Timer() as sup_timer:
        supervisors = {}
        for j in range(number_lp):
            proj_id = number_to_lp[j]
            if proj_id in supervisors:
                raise RuntimeError("PuLP solution has inconsistent supervisor assignment")

            assigned = {}

            for k in range(number_sup):
                S[(k, j)].round()
                # get multiplicity m with which supervisor k is assigned to project j
                m = pulp.value(S[(k, j)])
                if m > 0:
                    assigned.update({number_to_sup[k]: m})

            supervisors[proj_id] = assigned

    print(" ** parsed supervisor decision variables in time {t}".format(t=sup_timer.interval))

    # generate dictionary of marker assignments; we map each project id to a list of available markers
    markers = {}

    with Timer() as mark_timer:
        for j in range(number_lp):
            proj_id = number_to_lp[j]
            if proj_id in markers:
                raise RuntimeError("Marker entry already exists when storing PuLP marker assignment")

            assigned = {}

            for l in range(number_sel):
                sel_id = number_to_sel[l]
                if sel_id in assigned:
                    raise RuntimeError("Selector entry already exists when storing PuLP marker assignment")

                sel_marker = set()

                for i in range(number_mark):
                    Y[(i, j, l)].round()
                    m = pulp.value(Y[(i, j, l)])

                    if m > 0:
                        sel_marker.add(number_to_mark[i])

                assigned[sel_id] = sel_marker

            markers[proj_id] = assigned

    print(" ** parsed marker decision variables in time {t}".format(t=mark_timer.interval))

    # loop through all selectors that participated in the matching, generating matching records for each one
    for i in range(number_sel):
        if i not in sel_dict:
            raise RuntimeError("PuLP solution references unexpected SelectingStudent instance")

        sel_id: int = number_to_sel[i]

        sel: SelectingStudent = sel_dict[i]
        if sel.id != sel_id:
            raise RuntimeError("Inconsistent selector lookup when storing PuLP solution")

        # find the submission periods and marker valences that are needed for this selector
        config: ProjectClassConfig = sel.config
        pclass: ProjectClass = config.project_class

        # generate list of project assignments for this selector
        assigned = []

        for j in range(number_lp):
            X[(i, j)].round()
            if pulp.value(X[(i, j)]) == 1:
                assigned.append(j)

        if len(assigned) != multiplicity[i]:
            raise RuntimeError("Number of selector assignments in PuLP solution does not match expected selector multiplicity")

        print(f">> Storing assigned values for selector = {sel.student.user.name}")
        print(f">>   Assigned projects = {assigned}")

        custom_offers_per_period = {}
        markers_per_period = {}

        has_custom_offers = sel.has_accepted_offers()

        # if selection occurs in previous cycle, uses period definitions from parent ProjectClass
        if config.select_in_previous_cycle:
            uses_supervisor = pclass.uses_supervisor
            uses_marker = pclass.uses_marker

            for pd in pclass.periods:
                pd: SubmissionPeriodDefinition
                markers_per_period[pd.period] = pd.number_markers

                if has_custom_offers:
                    offers: List[CustomOffer] = sel.accepted_offers(pd).all()
                    num_offers = len(offers)

                    if num_offers > 0:
                        custom_offers_per_period[pd.period] = offers
                        print(f">>   -- Found {num_offers} custom offers for period #{pd.period}")
                    else:
                        print(f">>   -- Found no custom offers for period #{pd.period}")

        # otherwise, use current definitions from ProjectClassConfig
        else:
            uses_supervisor = config.uses_supervisor
            uses_marker = config.uses_marker

            for pd in config.periods:
                pd: SubmissionPeriodRecord
                markers_per_period[pd.submission_period] = pd.number_markers

                if has_custom_offers:
                    offers: List[CustomOffer] = sel.accepted_offers(pd.submission_period).all()
                    num_offers = len(offers)

                    if num_offers > 0:
                        custom_offers_per_period[pd.submission_period] = offers
                        print(f">>   -- Found {num_offers} custom offers for period #{pd.submission_period}")
                    else:
                        print(f">>   -- Found no custom offers for period #{pd.submission_period}")

        if len(markers_per_period) != multiplicity[i]:
            raise RuntimeError("Number of submission periods does not match expected selector multiplicity")

        print(f">>   Markers per period = {markers_per_period.items()}")
        print(f">>   Custom offers per period = {custom_offers_per_period.items()}")

        while len(assigned) > 0:
            # pop a project assignment from the back of the stack
            proj_number: int = assigned.pop()

            if proj_number not in lp_dict:
                raise RuntimeError("PuLP solution references unexpected LiveProject instance")

            proj_id: int = number_to_lp[proj_number]
            project: LiveProject = lp_dict[proj_number]
            if proj_id != project.id:
                raise RuntimeError("Inconsistent project lookup when storing PuLP solution")

            print(f">>   Processing assigned project id = #{proj_id}, number = #{proj_number}, '{project.name}'")

            # calculate selector's rank of the assigned project
            # (this lets us work out the quality of the fit from the student's perspective)
            rk = sel.project_rank(proj_id)
            alt_data = None
            if sel.has_submitted and rk is None:
                alt_data = sel.alternative_priority(proj_id)

                if alt_data is None:
                    raise RuntimeError("PuLP solution assigns unranked project to selector")

            # DECIDE WHICH SUBMISSION PERIOD TO ASSIGN THIS PROJECT TO
            if len(markers_per_period) == 0:
                raise RuntimeError("Period list is unexpectedly empty when storing PuLP solution")

            period_list = sorted(list(markers_per_period.keys()))
            this_period = None
            print(f">>   Assigning from remaining periods = {period_list}")

            # test whether there was a custom offer specifically for this period
            for pd, offers in custom_offers_per_period.items():
                for offer in offers:
                    if offer.liveproject_id == proj_id:

                        print(f">>   Matched custom offer id = #{offer.id} and assigned to period #{pd}")
                        if pd in period_list:
                            this_period = pd
                            break
                        else:
                            raise RuntimeError("PuLP solution should assign project to a custom offer, but the required period is missing")

                if this_period is not None:
                    break

            # if there were no custom offers, or none matched, then assign to first available period in order
            # avoid assigning to periods for which there is a custom offer, because that will create
            # a conflict
            if this_period is None:
                allowed_periods = [n for n in period_list if n not in custom_offers_per_period]
                this_period = allowed_periods[0]
                print(f">>   Assigned to vacant period #{this_period}")

            markers_needed = markers_per_period.pop(this_period)
            custom_offers_per_period.pop(this_period, None)

            data = MatchingRecord(
                matching_id=record.id,
                selector_id=number_to_sel[i],
                project_id=proj_id,
                original_project_id=proj_id,
                submission_period=this_period,
                rank=rk,
                alternative=False if alt_data is None else True,
                parent_id=None if alt_data is None else alt_data["project"].id,
                priority=None if alt_data is None else alt_data["priority"],
            )
            db.session.add(data)
            db.session.flush()

            # ASSIGN ROLES (IF USED)

            # find supervisor, if used
            if uses_supervisor:
                # get supervisor assignment for this project
                if proj_id not in supervisors:
                    raise RuntimeError("PuLP solution error: supervisor stack unexpectedly empty or missing")

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
                        raise RuntimeError(
                            "PuLP solution error: supervisor count has decreased to zero, but supervisor has not been removed from queue"
                        )

                if supervisor is None:
                    raise RuntimeError("PuLP solution error: supervisor stack unexpectedly empty or missing")

                # generate supervisor role record
                role_supv = MatchingRole(user_id=supervisor, role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR)
                data.roles.append(role_supv)

                # generate original supervisor role record (cached so we can revert later if required)
                orig_role_supv = MatchingRole(user_id=supervisor, role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR)
                data.original_roles.append(orig_role_supv)

            # find marker
            if uses_marker:
                # get a set of marker assignments for this project
                if proj_id not in markers:
                    raise RuntimeError("PuLP solution error: marker stack unexpectedly empty or missing")

                selector_list = markers[proj_id]
                marker_set = selector_list[sel_id]

                if len(marker_set) < markers_needed:
                    raise RuntimeError("Number of marker assignments in PuLP solution does not match expected marker valence")

                while markers_needed > 0 and len(marker_set) > 0:
                    marker = marker_set.pop()

                    if marker is None:
                        raise RuntimeError("PuLP solution error: marker stack unexpected empty or missing")

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
    Y = _pulp_dicts("Y", itertools.product(range(number_markers), range(number_submitters)), cat=pulp.LpBinary)

    # to implement workload balancing we use pairs of continuous variables that relax
    # to the maximum and minimum workload
    max_CATS = pulp.LpVariable("max_CATS", lowBound=0, cat=pulp.LpContinuous)
    min_CATS = pulp.LpVariable("min_CATS", lowBound=0, cat=pulp.LpContinuous)

    # track maximum number of marking assignments for any individual faculty member
    max_assigned = pulp.LpVariable("max_assigned", lowBound=0, cat=pulp.LpContinuous)

    # OBJECTIVE FUNCTION

    # maximization problem is to assign everyone while keeping difference between max and min CATS
    # small, and keeping max_assigned small
    prob += 10.0 * (max_CATS - min_CATS) + 5.0 * max_assigned

    for i in range(number_markers):
        # max_CATS and min_CATS should bracket the CATS workload of all faculty
        prob += mark_CATS_dict[i] + CATS_per_assignment * sum(Y[(i, j)] for j in range(number_submitters)) <= max_CATS
        prob += mark_CATS_dict[i] + CATS_per_assignment * sum(Y[(i, j)] for j in range(number_submitters)) >= min_CATS

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
        print(" -- {n} ProjectClassConfig instances participate in this matching".format(n=len(configs)))

        progress_update(record.celery_id, TaskRecord.RUNNING, 6, "Enumerating selector records...", autocommit=True)

        # get lists of selectors and liveprojects, together with auxiliary data such as
        # multiplicities (for selectors) and CATS assignments (for projects)
        with Timer() as sel_timer:
            number_sel, sel_to_number, number_to_sel, multiplicity, sel_dict = _enumerate_selectors(record, configs, read_serialized=read_serialized)
        print(" -- enumerated {n} selectors in time {s}".format(n=number_sel, s=sel_timer.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 8, "Enumerating LiveProject records...", autocommit=True)

        with Timer() as lp_timer:
            number_lp, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, lp_dict, lp_group_dict = _enumerate_liveprojects(
                record, configs, read_serialized=read_serialized
            )
        print(" -- enumerated {n} LiveProjects in time {s}".format(n=number_lp, s=lp_timer.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 10, "Enumerating supervising faculty...", autocommit=True)

        # get supervising faculty and marking faculty lists
        with Timer() as sup_timer:
            number_sup, sup_to_number, number_to_sup, sup_limits, sup_dict, sup_pclass_limits = _enumerate_supervising_faculty(record, configs)
        print(" -- enumerated {n} supervising faculty in time {s}".format(n=number_sup, s=sup_timer.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 12, "Enumerating marking faculty...", autocommit=True)

        with Timer() as mark_timer:
            number_mark, mark_to_number, number_to_mark, mark_limits, mark_dict, mark_pclass_limits = _enumerate_marking_faculty(record, configs)
        print(" -- enumerated {n} marking faculty in time {s}".format(n=number_mark, s=mark_timer.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 14, "Partioning faculty roles...", autocommit=True)

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
        print(" -- partitioned faculty in time {s}".format(s=partition_timer.interval))
        print("    :: {n} faculty are supervising only".format(n=len(sup_only_numbers)))
        print("    :: {n} faculty are marking only".format(n=len(mark_only_numbers)))
        print("    :: {n} faculty are supervising and marking".format(n=len(sup_and_mark_numbers)))

        progress_update(record.celery_id, TaskRecord.RUNNING, 16, "Building student ranking matrix...", autocommit=True)

        # build student ranking matrix
        with Timer() as rank_timer:
            R, W, cstr = _build_ranking_matrix(number_sel, sel_dict, number_lp, lp_to_number, lp_dict, record)
        print(" -- built student ranking matrix in time {s}".format(s=rank_timer.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 18, "Building marker compatibility matrix...", autocommit=True)

        # build marker compatibility matrix
        with Timer() as mark_matrix_timer:
            mm = record.max_marking_multiplicity
            M, marker_valence = _build_marking_matrix(number_mark, mark_dict, number_lp, lp_dict, mm if mm >= 1 else 1)
        print(" -- built marking compatibility matrix in time {s}".format(s=mark_matrix_timer.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 19, "Building project-to-supervisor mapping matrix...", autocommit=True)

        with Timer() as sup_mapping_timer:
            # build project-to-supervisor mapping
            P = _build_project_supervisor_matrix(number_lp, lp_dict, number_sup, sup_dict)
        print(" -- built project-to-supervisor mapping matrix in time {s}".format(s=sup_mapping_timer.interval))

    except SQLAlchemyError as e:
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    return (
        number_sel,
        number_lp,
        number_sup,
        number_mark,
        sel_to_number,
        lp_to_number,
        sup_to_number,
        mark_to_number,
        number_to_sel,
        number_to_lp,
        number_to_sup,
        number_to_mark,
        sel_dict,
        lp_dict,
        lp_group_dict,
        sup_dict,
        mark_dict,
        sup_only_numbers,
        mark_only_numbers,
        sup_and_mark_numbers,
        sup_limits,
        sup_pclass_limits,
        mark_limits,
        mark_pclass_limits,
        multiplicity,
        capacity,
        mean_CATS_per_project,
        CATS_supervisor,
        CATS_marker,
        R,
        W,
        cstr,
        M,
        marker_valence,
        P,
    )


def _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number, mark_to_number):
    base_X = set()
    base_Y = {}
    base_S = {}
    has_base_match = set()

    base: MatchingAttempt = record.base

    if record.base is None:
        print(f"-- no base in use for this match (record.base_id = {record.base_id})")
        return base_X, base_Y, base_S, has_base_match

    for record in base.records:
        record: MatchingRecord

        if record.selector_id not in sel_to_number:
            # this does not have to be an error; we just take it to indicate that no base match exists
            print(f"Missing SelectingStudent when reconstructing X map (SelectingStudent.id = {record.selector_id})")
            continue

        # get our selector number for the allocated selector
        sel_number = sel_to_number[record.selector_id]

        selector: SelectingStudent = record.selector
        sel_user: User = selector.student.user

        if record.project_id not in lp_to_number:
            # this does not have to be an error; we just take it to indicate that no base match exists
            # (e.g. this can happen if a supervisor has been marked as on sabbatical since the original match
            # was done; then their LiveProject instances don't get enumerated)
            print(f"Missing LiveProject when reconstructing X map (LiveProject.id = {record.project_id})")
            continue

        # get our project number for the allocated project
        proj_number = lp_to_number[record.project_id]

        base_X.add((sel_number, proj_number))
        print(
            ">> registered base match between selector {sel_n} (={sel_name}) and project {proj_n} "
            "(={proj_name})".format(sel_n=sel_number, proj_n=proj_number, sel_name=sel_user.name, proj_name=record.project.name)
        )
        has_base_match.add(sel_number)

        for role in record.roles:
            role: MatchingRole

            if role.role in [MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR]:
                if role.user_id not in sup_to_number:
                    print(f"Missing supervisor when reconstructing S map (User.id = {role.user_id})")
                    continue

                supv_number = sup_to_number[role.user_id]

                key = (supv_number, proj_number)
                if key in base_S:
                    base_S[key] += 1
                else:
                    base_S[key] = 1

                print(
                    ">> registered base match between supervisor {sup_n} (={sup_name}) and project {proj_n} "
                    "(={proj_name})".format(sup_n=supv_number, proj_n=proj_number, sup_name=role.user.name, proj_name=record.project.name)
                )

            elif role.role == MatchingRole.ROLE_MARKER:
                if role.user_id not in mark_to_number:
                    print(f"Missing marker when reconstructing Y map (User.id = {role.user_id})")
                    continue

                mark_number = mark_to_number[role.user_id]

                key = (mark_number, proj_number, sel_number)
                if key in base_Y:
                    raise RuntimeError("Duplicate value of boolean Y[marker,project,selector]")
                else:
                    base_Y[key] = 1

                print(
                    ">> registered base match between marker {mark_n} (={mark_name}), selector {sel_n} (={sel_name}) "
                    "and project {proj_n} "
                    "(={proj_name})".format(
                        mark_n=mark_number,
                        proj_n=proj_number,
                        sel_name=sel_user.name,
                        sel_n=sel_number,
                        mark_name=role.user.name,
                        proj_name=record.project.name,
                    )
                )

    return base_X, base_Y, base_S, has_base_match


def _execute_live(
    self,
    record,
    prob,
    X,
    Y,
    S,
    W,
    R,
    create_time,
    number_sel,
    number_to_sel,
    number_lp,
    number_to_lp,
    number_sup,
    number_to_sup,
    number_mark,
    number_to_mark,
    sel_dict,
    lp_dict,
    sup_dict,
    mark_dict,
    multiplicity,
    mean_CATS_per_project,
):
    print("Solving PuLP problem for project matching")

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...", autocommit=True)

    with Timer() as solve_time:
        record.awaiting_upload = False

        if record.solver == MatchingAttempt.SOLVER_CBC_PACKAGED:
            status = prob.solve(pulp_apis.PULP_CBC_CMD(msg=True, timeLimit=3600, gapRel=0.25))
        elif record.solver == MatchingAttempt.SOLVER_CBC_CMD:
            status = prob.solve(pulp_apis.COIN_CMD(msg=True, timeLimit=3600, gapRel=0.25))
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

    return _process_PuLP_solution(
        self,
        record,
        status,
        solve_time,
        X,
        Y,
        S,
        W,
        R,
        create_time,
        number_sel,
        number_to_sel,
        number_lp,
        number_to_lp,
        number_sup,
        number_to_sup,
        number_mark,
        number_to_mark,
        multiplicity,
        sel_dict,
        sup_dict,
        mark_dict,
        lp_dict,
        mean_CATS_per_project,
    )


def _execute_from_solution(
    self,
    file,
    record,
    prob,
    X,
    Y,
    S,
    W,
    R,
    create_time,
    number_sel,
    number_to_sel,
    number_lp,
    number_to_lp,
    number_sup,
    number_to_sup,
    number_mark,
    number_to_mark,
    sel_dict,
    lp_dict,
    sup_dict,
    mark_dict,
    multiplicity,
    mean_CATS_per_project,
):
    print('Processing PuLP solution from "{name}"'.format(name=file))

    if not path.exists(file):
        progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Could not locate uploaded solution file", autocommit=True)
        raise Ignore

    progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Processing uploaded solution file...", autocommit=True)

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
            progress_update(record.celery_id, TaskRecord.FAILURE, 100, "Unknown solver", autocommit=True)
            raise Ignore()

        if status != pulp.LpStatusInfeasible:
            prob.assignVarsVals(values)
            prob.assignVarsDj(reducedCosts)
            prob.assignConsPi(shadowPrices)
            prob.assignConsSlack(slacks)
        prob.status = status

        prob.restoreObjective(wasNone, dummyVar)
        prob.solver = solver

    return _process_PuLP_solution(
        self,
        record,
        status,
        solve_time,
        X,
        Y,
        S,
        W,
        R,
        create_time,
        number_sel,
        number_to_sel,
        number_lp,
        number_to_lp,
        number_sup,
        number_to_sup,
        number_mark,
        number_to_mark,
        multiplicity,
        sel_dict,
        sup_dict,
        mark_dict,
        lp_dict,
        mean_CATS_per_project,
    )


def _execute_marker_problem(task_id, prob, Y, mark_dict, submit_dict, user: User):
    print("Solving PuLP problem to populate markers")

    progress_update(task_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...", autocommit=True)

    with Timer() as solve_time:
        status = prob.solve(pulp_apis.PULP_CBC_CMD(msg=True, timeLimit=3600, gapRel=0.25))

    print("-- solved PuLP problem in time {t}".format(t=solve_time.interval))

    progress_update(task_id, TaskRecord.RUNNING, 70, "Processing PuLP solution...", autocommit=True)

    state = pulp.LpStatus[status]

    if state == "Optimal":
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
            user.post_message("Populated {num} missing marker assignments".format(num=number_populated), "success", autocommit=True)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            user.post_message(
                "Could not populate markers because, although the optimization task succeeded there was a failure while storing the solution.",
                "error",
                autocommit=True,
            )

    else:
        user.post_message("Could not populate markers because the optimization task failed", "error", autocommit=True)

    progress_update(task_id, TaskRecord.SUCCESS, 100, "Matching task complete", autocommit=True)


def _process_PuLP_solution(
    self,
    record,
    output,
    solve_time,
    X,
    Y,
    S,
    W,
    R,
    create_time,
    number_sel,
    number_to_sel,
    number_lp,
    number_to_lp,
    number_sup,
    number_to_sup,
    number_mark,
    number_to_mark,
    multiplicity,
    sel_dict,
    sup_dict,
    mark_dict,
    lp_dict,
    mean_CATS_per_project,
):
    state = pulp.LpStatus[output]

    if state == "Optimal":
        record.outcome = MatchingAttempt.OUTCOME_OPTIMAL

        # we don't just read the objective function out directly, because we don't want to include
        # contributions from the levelling and slack terms.
        # We don't account for biasing terms coming from a base match.
        score = _build_score_function(R, W, X, Y, S, number_lp, number_sel, number_sup, number_mark, set(), {}, set(), set(), 1.0)
        record.score = pulp.value(score)

        record.construct_time = create_time.interval
        record.compute_time = solve_time.interval

        progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing PuLP solution...", autocommit=True)

        try:
            # note _store_PuLP_solution does not do a commit by itself
            _store_PuLP_solution(
                X,
                Y,
                S,
                record,
                number_sel,
                number_to_sel,
                number_lp,
                number_to_lp,
                number_sup,
                number_to_sup,
                number_mark,
                number_to_mark,
                multiplicity,
                sel_dict,
                sup_dict,
                mark_dict,
                lp_dict,
                mean_CATS_per_project,
            )
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    elif state == "Not Solved":
        record.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED
    elif state == "Infeasible":
        record.outcome = MatchingAttempt.OUTCOME_INFEASIBLE
    elif state == "Unbounded":
        record.outcome = MatchingAttempt.OUTCOME_UNBOUNDED
    elif state == "Undefined":
        record.outcome = MatchingAttempt.OUTCOME_UNDEFINED
    else:
        raise RuntimeError("Unknown PuLP outcome")

    try:
        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, "Matching task complete", autocommit=False)

        record.finished = True
        record.celery_finished = True
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    return record.score


def _send_offline_email(celery, record: MatchingAttempt, user: User, lp_asset: GeneratedAsset):
    send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

    msg = EmailMultiAlternatives(
        subject="Files for offline matching of {name} are now ready".format(name=record.name),
        from_email=current_app.config["MAIL_DEFAULT_SENDER"],
        reply_to=[current_app.config["MAIL_REPLY_TO"]],
        to=[user.email],
    )

    msg.body = render_template("email/matching/generated.txt", name=record.name, user=user)

    # TODO: will be problems when generated LP/MPS files are too large; should instead send a download link
    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
    lp_storage: AssetCloudAdapter = AssetCloudAdapter(lp_asset, object_store, audit_data="matching._send_offline_email #1")

    msg.attach(filename=str("schedule.lp"), mimetype=lp_asset.mimetype, content=lp_storage.get())

    # register a new task in the database
    task_id = register_task(msg.subject, description="Email to {r}".format(r=", ".join(msg.to)))
    send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


def _write_LP_MPS_files(record: MatchingAttempt, prob, user):
    now = datetime.now()
    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

    def make_asset(source_path: Path, target_name: str):
        # AssetUploadManager will populate most fields later
        asset = GeneratedAsset(timestamp=now, expiry=None, target_name=target_name, parent_asset_id=None, license_id=None)

        size = source_path.stat().st_size

        with open(source_path, "rb") as f:
            with AssetUploadManager(
                asset,
                data=BytesIO(f.read()),
                storage=object_store,
                audit_data=f"matching._write_LP_MPS_files (matching attempt #{record.id})",
                length=size,
                mimetype="text/plain",
                validate_nonce=validate_nonce,
            ) as upload_mgr:
                pass

        asset.grant_user(user)
        db.session.add(asset)

        return asset

    with ScratchFileManager(suffix=".lp") as mgr:
        lp_path: Path = mgr.path
        prob.writeLP(lp_path)
        lp_asset = make_asset(lp_path, "matching.lp")

    # write new assets to database, so they get a valid primary key
    db.session.flush()

    # add asset details to MatchingAttempt record
    record.lp_file = lp_asset

    # allow exceptions to propagate up to calling function
    record.celery_finished = True
    db.session.commit()

    return lp_asset


def _store_enumeration_details(
    record, number_to_sel, number_to_lp, number_to_sup, number_to_mark, lp_group_dict, sup_pclass_limits, mark_pclass_limits
):
    def write_out(label, block):
        for number in block:
            data = MatchingEnumeration(matching_id=record.id, enumeration=number, key=block[number], category=label)
            db.session.add(data)

    write_out(MatchingEnumeration.SELECTOR, number_to_sel)
    write_out(MatchingEnumeration.LIVEPROJECT, number_to_lp)
    write_out(MatchingEnumeration.SUPERVISOR, number_to_sup)
    write_out(MatchingEnumeration.MARKER, number_to_mark)

    for config_id in lp_group_dict:
        lps = lp_group_dict[config_id]

        for lp_id in lps:
            data = MatchingEnumeration(matching_id=record.id, enumeration=lp_id, key=config_id, category=MatchingEnumeration.LIVEPROJECT_GROUP)
            db.session.add(data)

    def write_limits(label, limit_dict):
        for config_id in limit_dict:
            limits = limit_dict[config_id]

            for fac_number in limits:
                data = MatchingEnumeration(matching_id=record.id, enumeration=fac_number, key=config_id, key2=limits[fac_number], category=label)
                db.session.add(data)

    write_limits(MatchingEnumeration.SUPERVISOR_LIMITS, sup_pclass_limits)
    write_limits(MatchingEnumeration.MARKER_LIMITS, mark_pclass_limits)

    # allow exception to propgate up to calling function
    db.session.commit()


def register_matching_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def create_match(self, id):
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingAttempt record for id={id}".format(id=id)})

        try:
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore()

        with Timer() as create_time:
            (
                number_sel,
                number_lp,
                number_sup,
                number_mark,
                sel_to_number,
                lp_to_number,
                sup_to_number,
                mark_to_number,
                number_to_sel,
                number_to_lp,
                number_to_sup,
                number_to_mark,
                sel_dict,
                lp_dict,
                lp_group_dict,
                sup_dict,
                mark_dict,
                sup_only_numbers,
                mark_only_numbers,
                sup_and_mark_numbers,
                sup_limits,
                sup_pclass_limits,
                mark_limits,
                mark_pclass_limits,
                multiplicity,
                capacity,
                mean_CATS_per_project,
                CATS_supervisor,
                CATS_marker,
                R,
                W,
                cstr,
                M,
                marker_valence,
                P,
            ) = _initialize(self, record)

            base_X, base_Y, base_S, has_base_match = _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number, mark_to_number)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

            prob, X, Y, S = _create_PuLP_problem(
                R,
                M,
                marker_valence,
                W,
                P,
                cstr,
                base_X,
                base_Y,
                base_S,
                has_base_match,
                record.force_base,
                CATS_supervisor,
                CATS_marker,
                capacity,
                sup_limits,
                sup_pclass_limits,
                mark_limits,
                mark_pclass_limits,
                multiplicity,
                number_lp,
                number_mark,
                number_sel,
                number_sup,
                record,
                sel_dict,
                sup_dict,
                mark_dict,
                lp_dict,
                lp_group_dict,
                sup_only_numbers,
                mark_only_numbers,
                sup_and_mark_numbers,
                mean_CATS_per_project,
            )

        print(" -- creation complete in time {t}".format(t=create_time.interval))

        score = _execute_live(
            self,
            record,
            prob,
            X,
            Y,
            S,
            W,
            R,
            create_time,
            number_sel,
            number_to_sel,
            number_lp,
            number_to_lp,
            number_sup,
            number_to_sup,
            number_mark,
            number_to_mark,
            sel_dict,
            lp_dict,
            sup_dict,
            mark_dict,
            multiplicity,
            mean_CATS_per_project,
        )

        if record.created_by is not None:
            if record.is_valid:
                msg = render_template_string(_match_success, name=record.name)
                record.created_by.post_message(msg, "success", autocommit=True)
            else:
                msg = render_template_string(_match_failure, name=record.name)
                record.created_by.post_message(msg, "error", autocommit=True)

        return score

    @celery.task(bind=True, default_retry_delay=30)
    def offline_match(self, matching_id, user_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingAttempt record for id={id}".format(id=matching_id)})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=matching_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore()

        with Timer() as create_time:
            (
                number_sel,
                number_lp,
                number_sup,
                number_mark,
                sel_to_number,
                lp_to_number,
                sup_to_number,
                mark_to_number,
                number_to_sel,
                number_to_lp,
                number_to_sup,
                number_to_mark,
                sel_dict,
                lp_dict,
                lp_group_dict,
                sup_dict,
                mark_dict,
                sup_only_numbers,
                mark_only_numbers,
                sup_and_mark_numbers,
                sup_limits,
                sup_pclass_limits,
                mark_limits,
                mark_pclass_limits,
                multiplicity,
                capacity,
                mean_CATS_per_project,
                CATS_supervisor,
                CATS_marker,
                R,
                W,
                cstr,
                M,
                marker_valence,
                P,
            ) = _initialize(self, record)

            base_X, base_Y, base_S, has_base_match = _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number, mark_to_number)

            progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

            prob, X, Y, S = _create_PuLP_problem(
                R,
                M,
                marker_valence,
                W,
                P,
                cstr,
                base_X,
                base_Y,
                base_S,
                has_base_match,
                record.force_base,
                CATS_supervisor,
                CATS_marker,
                capacity,
                sup_limits,
                sup_pclass_limits,
                mark_limits,
                mark_pclass_limits,
                multiplicity,
                number_lp,
                number_mark,
                number_sel,
                number_sup,
                record,
                sel_dict,
                sup_dict,
                mark_dict,
                lp_dict,
                lp_group_dict,
                sup_only_numbers,
                mark_only_numbers,
                sup_and_mark_numbers,
                mean_CATS_per_project,
            )

        print(" -- creation complete in time {t}".format(t=create_time.interval))

        progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Writing .LP file...", autocommit=True)

        try:
            lp_asset = _write_LP_MPS_files(record, prob, user)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        _send_offline_email(celery, record, user, lp_asset)

        progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing matching details for later processing...", autocommit=True)

        try:
            _store_enumeration_details(
                record, number_to_sel, number_to_lp, number_to_sup, number_to_mark, lp_group_dict, sup_pclass_limits, mark_pclass_limits
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, "File generation for offline project matching now complete", autocommit=True)

        msg = render_template_string(_match_offline_ready, name=record.name)
        user.post_message(msg, "info", autocommit=True)

    @celery.task(bind=True, default_retry_delay=30)
    def process_offline_solution(self, matching_id, asset_id, user_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up TemporaryAsset record for id={id}".format(id=asset_id)})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            asset: TemporaryAsset = db.session.query(TemporaryAsset).filter_by(id=asset_id).first()
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=matching_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if asset is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load TemporaryAsset record"})
            raise Ignore()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore()

        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        storage = AssetCloudAdapter(asset, object_store, audit_data=f"matching.process_offline_solution(matching id #{matching_id})")

        with storage.download_to_scratch() as scratch_path:
            with Timer() as create_time:
                (
                    number_sel,
                    number_lp,
                    number_sup,
                    number_mark,
                    sel_to_number,
                    lp_to_number,
                    sup_to_number,
                    mark_to_number,
                    number_to_sel,
                    number_to_lp,
                    number_to_sup,
                    number_to_mark,
                    sel_dict,
                    lp_dict,
                    lp_group_dict,
                    sup_dict,
                    mark_dict,
                    sup_only_numbers,
                    mark_only_numbers,
                    sup_and_mark_numbers,
                    sup_limits,
                    sup_pclass_limits,
                    mark_limits,
                    mark_pclass_limits,
                    multiplicity,
                    capacity,
                    mean_CATS_per_project,
                    CATS_supervisor,
                    CATS_marker,
                    R,
                    W,
                    cstr,
                    M,
                    marker_valence,
                    P,
                ) = _initialize(self, record, read_serialized=True)

                base_X, base_Y, base_S, has_base_match = _build_base_XYS(record, sel_to_number, lp_to_number, sup_to_number, mark_to_number)

                progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

                prob, X, Y, S = _create_PuLP_problem(
                    R,
                    M,
                    marker_valence,
                    W,
                    P,
                    cstr,
                    base_X,
                    base_Y,
                    base_S,
                    has_base_match,
                    record.force_base,
                    CATS_supervisor,
                    CATS_marker,
                    capacity,
                    sup_limits,
                    sup_pclass_limits,
                    mark_limits,
                    mark_pclass_limits,
                    multiplicity,
                    number_lp,
                    number_mark,
                    number_sel,
                    number_sup,
                    record,
                    sel_dict,
                    sup_dict,
                    mark_dict,
                    lp_dict,
                    lp_group_dict,
                    sup_only_numbers,
                    mark_only_numbers,
                    sup_and_mark_numbers,
                    mean_CATS_per_project,
                )

            print(" -- creation complete in time {t}".format(t=create_time.interval))

            soln = _execute_from_solution(
                self,
                scratch_path.path,
                record,
                prob,
                X,
                Y,
                S,
                W,
                R,
                create_time,
                number_sel,
                number_to_sel,
                number_lp,
                number_to_lp,
                number_sup,
                number_to_sup,
                number_mark,
                number_to_mark,
                sel_dict,
                lp_dict,
                sup_dict,
                mark_dict,
                multiplicity,
                mean_CATS_per_project,
            )

            if record.created_by is not None:
                if record.is_valid:
                    msg = render_template_string(_match_success, name=record.name)
                    record.created_by.post_message(msg, "success", autocommit=True)
                else:
                    msg = render_template_string(_match_failure, name=record.name)
                    record.created_by.post_message(msg, "error", autocommit=True)

            return soln

    @celery.task(bind=True, default_retry_delay=30)
    def populate_markers(self, config_id, user_id, task_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ProjectClassConfig record for id={id}".format(id=config_id)})

        try:
            config = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load ProjectClassConfig record from database"})
            raise Ignore()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load User record from database"})
            raise Ignore()

        with Timer() as create_time:
            mark_dict, inverse_mark_dict, submit_dict, inverse_submit_dict, mark_CATS_dict = _enumerate_missing_markers(self, config, task_id, user)

            progress_update(task_id, TaskRecord.RUNNING, 20, "Building PuLP linear programming problem...", autocommit=True)

            prob, Y = _create_marker_PuLP_problem(mark_dict, submit_dict, mark_CATS_dict, config)

        print(" -- creation complete in time {t}".format(t=create_time.interval))

        return _execute_marker_problem(task_id, prob, Y, mark_dict, submit_dict, user)

    @celery.task(bind=True, default_retry_delay=30)
    def remove_markers(self, config_id, user_id, task_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up ProjectClassConfig record for id={id}".format(id=config_id)})

        try:
            config = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load ProjectClassConfig record from database"})
            raise Ignore()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load User record from database"})
            raise Ignore()

        progress_update(task_id, TaskRecord.RUNNING, 20, "Sorting SubmittingStudent records...", autocommit=True)
        payload = {}

        payload_data = []
        for period in config.periods:
            period: SubmissionPeriodRecord

            period_data = {"name": period.display_name}

            # ignore periods that are retired, closed, or have open feedback; the markers for these
            # cannot be changed
            if period.retired or period.closed or period.feedback_open:
                period_data.update({"action": "ignore"})
                payload.update(period_data)
                continue

            submissions_data = []
            for rec in period.submissions:
                rec: SubmissionRecord
                sub: SubmittingStudent = rec.owner
                student: StudentData = sub.student
                owner: User = student.user

                removed_markers = []
                for role in rec.roles:
                    role: SubmissionRole

                    if role.role == SubmissionRole.ROLE_MARKER:
                        user: User = role.user
                        if user is not None:
                            removed_markers.append(
                                {"id": user.id, "last_name": user.last_name, "first_name": user.first_name, "full_name": user.name}
                            )

                        db.session.delete(role)

                record_data = {"id": rec.id, "last_name": owner.last_name, "first_name": owner.first_name, "full_name": owner.name}
                if rec.project is not None:
                    record_data.update({"project_id": rec.project_id, "project_name": rec.project.name})
                record_data.update({"removed_markers": removed_markers})
                submissions_data.append(record_data)

            period_data.update({"action": "process", "submission_records": submissions_data})
            payload_data.append(period_data)

        try:
            progress_update(task_id, TaskRecord.SUCCESS, 100, "Finishing remove markers task...", autocommit=False)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return payload_data

    @celery.task(bind=True, default_retry_delay=30)
    def revert_record(self, id):
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingRecord record for id={id}".format(id=id)})

        try:
            record = db.session.query(MatchingRecord).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingRecord record from database"})
            raise Ignore()

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
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingAttempt record for id={id}".format(id=id)})

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
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
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingAttempt record for id={id}".format(id=id)})

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore

        wg = group(revert_record.si(r.id) for r in record.records.all())
        seq = chain(wg, revert_finalize.si(id))

        seq.apply_async()

    @celery.task(bind=True, default_retry_delay=30)
    def duplicate(self, id, new_name, current_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingAttempt record for id={id}".format(id=id)})

        try:
            old_attempt: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if old_attempt is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore

        # encapsulate the whole duplication process in a single transaction, so the process is as close to
        # atomic as we can make it

        try:
            # generate a new MatchingAttempt record
            new_attempt = MatchingAttempt(
                year=old_attempt.year,
                base_id=old_attempt.base_id,
                base_bias=old_attempt.base_bias,
                force_base=old_attempt.force_base,
                name=new_name,
                config_members=old_attempt.config_members,
                published=False,
                selected=False,
                celery_id=None,
                finished=old_attempt.finished,
                celery_finished=True,
                awaiting_upload=old_attempt.awaiting_upload,
                outcome=old_attempt.outcome,
                solver=old_attempt.solver,
                construct_time=old_attempt.construct_time,
                compute_time=old_attempt.compute_time,
                include_only_submitted=old_attempt.include_only_submitted,
                ignore_per_faculty_limits=old_attempt.ignore_per_faculty_limits,
                ignore_programme_prefs=old_attempt.ignore_programme_prefs,
                years_memory=old_attempt.years_memory,
                supervising_limit=old_attempt.supervising_limit,
                marking_limit=old_attempt.marking_limit,
                max_marking_multiplicity=old_attempt.max_marking_multiplicity,
                max_different_group_projects=old_attempt.max_different_group_projects,
                max_different_all_projects=old_attempt.max_different_all_projects,
                use_hints=old_attempt.use_hints,
                require_to_encourage=old_attempt.require_to_encourage,
                forbid_to_discourage=old_attempt.forbid_to_discourage,
                encourage_bias=old_attempt.encourage_bias,
                discourage_bias=old_attempt.discourage_bias,
                strong_encourage_bias=old_attempt.strong_encourage_bias,
                strong_discourage_bias=old_attempt.strong_discourage_bias,
                bookmark_bias=old_attempt.bookmark_bias,
                levelling_bias=old_attempt.levelling_bias,
                supervising_pressure=old_attempt.supervising_pressure,
                marking_pressure=old_attempt.marking_pressure,
                CATS_violation_penalty=old_attempt.CATS_violation_penalty,
                no_assignment_penalty=old_attempt.no_assignment_penalty,
                intra_group_tension=old_attempt.intra_group_tension,
                programme_bias=old_attempt.programme_bias,
                include_matches=old_attempt.include_matches,
                score=old_attempt.current_score,
                # note that current score becomes original score
                supervisors=old_attempt.supervisors,
                markers=old_attempt.markers,
                projects=old_attempt.projects,
                mean_CATS_per_project=old_attempt.mean_CATS_per_project,
                creator_id=current_id,
                creation_timestamp=datetime.now(),
                last_edit_id=None,
                last_edit_timestamp=None,
                lp_file_id=None,
            )

            db.session.add(new_attempt)
            db.session.flush()

            # duplicate all matching records, and corresponding matching roles
            for old_record in old_attempt.records:
                old_record: MatchingRecord
                new_record = MatchingRecord(
                    matching_id=new_attempt.id,
                    selector_id=old_record.selector_id,
                    submission_period=old_record.submission_period,
                    project_id=old_record.project_id,
                    original_project_id=old_record.project_id,
                    rank=old_record.rank,
                    alternative=old_record.alternative,
                    parent_id=old_record.parent_id,
                    priority=old_record.priority,
                    # TODO: remove marker_id and original_marker_id fields from MatchingRecord (they have now been replaced by MatchingRole instances)
                    marker_id=old_record.marker_id,
                    original_marker_id=old_record.marker_id,
                )
                db.session.add(new_record)

                # duplicate any roles stored with this MatchingRecord instance
                for old_role in old_record.roles:
                    old_role: MatchingRole
                    new_role = MatchingRole(
                        user_id=old_role.user_id,
                        role=old_role.role
                    )
                    new_record.roles.append(new_role)

                # duplicate any "original" roles stored with this MatchingRecord instance
                for old_role in old_record.original_roles:
                    old_role: MatchingRole
                    new_role = MatchingRole(
                        user_id=old_role.user_id,
                        role=old_role.role
                    )
                    new_record.original_roles.append(new_role)

            # if this MatchingAttempt is awaiting upload of an offline-generated match, duplicate enumerations
            # and any necessary assets that we hold
            if new_attempt.awaiting_upload:
                for old_enum in old_attempt.enumerations:
                    new_enum = MatchingEnumeration(
                        category=old_enum.category, enumeration=old_enum.enumeration, key=old_enum.key, key2=old_enum.key2, matching_id=new_attempt.id
                    )
                    db.session.add(new_enum)

                # duplicate LP asset file
                now = datetime.now()
                object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

                def copy_asset(old_asset):
                    old_storage = AssetCloudAdapter(old_asset, object_store, audit_data=f"matching.duplicate.copy_asset (matching id #{id})")
                    new_key, put_result = old_storage.duplicate(validate_nonce=validate_nonce)

                    new_base64_nonce = None
                    if "nonce" in put_result:
                        new_base64_nonce = base64.urlsafe_b64encode(put_result["nonce"]).decode("ascii")

                    # must duplicate all fields, including those usually managed by AssetUploadManager
                    new_asset = GeneratedAsset(
                        timestamp=now,
                        expiry=None,
                        unique_name=new_key,
                        filesize=old_asset.filesize,
                        mimetype=old_asset.mimetype,
                        target_name=old_asset.target_name,
                        parent_asset_id=old_asset.parent_asset_id,
                        license_id=old_asset.license_id,
                        lost=False,
                        unattached=False,
                        bucket=old_asset.bucket,
                        comment=old_asset.comment,
                        encryption=object_store.encrypted,
                        encrypted_size=put_result.get("encrypted_size", None),
                        nonce=new_base64_nonce,
                        compressed=object_store.compressed,
                        compressed_size=put_result.get("compressed_size", None),
                    )

                    # TODO: find a way to perform a deep copy without exposing implementation details
                    new_asset.access_control_list = old_asset.access_control_list
                    new_asset.access_control_roles = old_asset.access_control_roles
                    db.session.add(new_asset)

                    return new_asset

                if old_attempt.lp_file is not None:
                    new_attempt.lp_file = copy_asset(old_attempt.lp_file)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def populate_submitters(self, match_id, config_id, user_id, task_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up database configuration records"})

        progress_update(task_id, TaskRecord.RUNNING, 5, "Loading database records...", autocommit=True)

        try:
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if config is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load ProjectClassConfig record"})
            user.post_message(
                "Populate selectors task failed due to a database error. Please contact a system administrator.", "error", autocommit=True
            )
            raise Ignore()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            user.post_message(
                "Populate selectors task failed due to a database error. Please contact a system administrator.", "error", autocommit=True
            )
            raise Ignore()

        progress_update(task_id, TaskRecord.RUNNING, 10, "Inspecting match configuration...", autocommit=True)

        year = get_current_year()

        if record.year != year:
            self.update_state(state="FAILURE", meta={"msg": "MatchingAttempt is not for current year"})
            progress_update(task_id, TaskRecord.FAILURE, 100, "Match is not for the current year", autocommit=False)
            user.post_message(
                "Submitters could not be populated because the selected matching is not for the "
                "current academic year (current year={cyr}, "
                "match year={myr}".format(cyr=year, myr=record.year),
                "error",
                autocommit=True,
            )
            raise Ignore()

        if config.year != record.year:
            self.update_state(state="FAILURE", meta={"msg": "ProjectClassConfig does not belong to same year as MatchingAttempt"})
            progress_update(task_id, TaskRecord.FAILURE, 100, "Project configuration and matching were for different years", autocommit=False)
            user.post_message(
                "Submitters could not be populated because the selected matching does not belong "
                "to the same academic year as the current project configuration (selected matching "
                "year={myr}, current configuration "
                "year={cyr}".format(myr=record.year, cyr=config.year),
                "error",
                autocommit=True,
            )
            raise Ignore()

        if config.select_in_previous_cycle:
            self.update_state(state="FAILURE", Meta="ProjectClassConfig does not have select_in_previous_cycle")
            progress_update(task_id, TaskRecord.FAILURE, 100, "ProjectClassConfig does not have select_in_previous_cycle", autocommit=False)
            user.post_message(
                "Submitters could not be populated because this project type is not configured to use selection in the same cycle as submission",
                "error",
                autocommit=True,
            )
            raise Ignore()

        if not record.finished:
            if record.awaiting_upload:
                self.update_state(state="FAILURE", meta={"msg": "MatchingAttempt still awaiting manual upload"})
                progress_update(task_id, TaskRecord.FAILURE, 100, "Match is still awaiting manual upload", autocommit=False)
                user.post_message(
                    "Submitters could not be populated because the selecting matching is still awaiting manual upload of a solution.",
                    "error",
                    autocommit=True,
                )
            else:
                self.update_state(state="FAILURE", meta={"msg": "Matching optimization has not yet terminated"})
                progress_update(task_id, TaskRecord.FAILURE, 100, "Matching optimization has not yet terminated", autocommit=False)
                user.post_message(
                    "Submitters could not be populated because the matching optimization has not yet terminated.", "error", autocommit=True
                )
            raise Ignore()

        if not record.solution_usable:
            self.update_state(state="FAILURE", meta={"msg": "MatchingAttempt solution is not usable"})
            progress_update(task_id, TaskRecord.FAILURE, 100, "Matching solution is not usable", autocommit=False)
            user.post_message("Submitters could not be populated because the selecting matching solution is not usable.", "error", autocommit=True)
            raise Ignore()

        if not record.published:
            self.update_state(state="FAILURE", meta={"msg": "MatchingAttempt has not been published"})
            progress_update(task_id, TaskRecord.FAILURE, 100, "Matching has not yet been published to convenors", autocommit=True)
            user.post_message(
                "Submitters could not be populated because the selecting matching has not yet "
                "been published to convenors. Please publish the match before attempting "
                "to generate selectors.",
                "error",
                autocommit=True,
            )
            raise Ignore()

        # pull out MatchingRecord instances that belong to this MatchingAttempt, and which correspond to
        # the specified ProjectClass(Config)
        match_records = (
            record.records.join(SelectingStudent, SelectingStudent.id == MatchingRecord.selector_id)
            .filter(SelectingStudent.config_id == config_id)
            .all()
        )

        populate_tasks = group(convert_record_to_submitter.s(match_id, config_id, user_id, r.id) for r in match_records)

        if len(populate_tasks) > 0:
            work = populate_initial_msg.si(task_id) | populate_tasks | populate_final_msg.s(task_id)
            return self.replace(work)

        progress_update(task_id, TaskRecord.SUCCESS, 100, "Completed with no work to perform", autocommit=False)
        user.post_message(
            "The populate task completed successfully, but no matching records "
            "corresponded to this project class configuration, and therefore "
            "no submitter records have been populated.",
            "info",
            autocommit=True,
        )

    @celery.task(bind=True)
    def populate_initial_msg(self, task_id):
        progress_update(task_id, TaskRecord.RUNNING, 20, "Inspecting matching records to populate submitters...", autocommit=True)

    @celery.task(bind=True)
    def populate_final_msg(self, _result_data, task_id):
        new_submitters = 0
        new_submissions = 0
        projects_set = 0

        for payload in _result_data:
            if payload is not None and "actions" in payload:
                actions = payload["actions"]

                if "insert_submitter" in actions:
                    new_submitters += 1

                if "insert_submission" in actions:
                    new_submissions += 1

                if "set_project" in actions:
                    projects_set += 1

        def pluralize(n):
            if n != 1:
                return "s"

            return " " ""

        progress_update(
            task_id,
            TaskRecord.SUCCESS,
            100,
            f"Import submitter data now complete: {new_submitters} submitter record{pluralize(new_submitters)} created, "
            f"{new_submissions} submission record{pluralize(new_submissions)} generated, "
            f"{projects_set} project assignment{pluralize(projects_set)} set",
            autocommit=True,
        )

    @celery.task(bind=True)
    def convert_record_to_submitter(self, _result_data, match_id, config_id, user_id, data_id):
        # read database records
        self.update_state(state="STARTED", meta={"msg": "Looking up database configuration records"})

        try:
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
            user: User = db.session.query(User).filter_by(id=user_id).first()
            data: MatchingRecord = db.session.query(MatchingRecord).filter_by(id=data_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if config is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load ProjectClassConfig record"})
            raise Ignore()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore()

        if data is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load MatchingRecord record from database"})
            raise Ignore()

        needs_commit = False

        self.update_state(state="STARTED", meta={"msg": "Populating SubmittingStudent record..."})

        # first, determine whether there is an existing SubmittingStudent instance associated with this student
        sel: SelectingStudent = data.selector
        sub: SubmittingStudent = config.submitting_students.filter(SubmittingStudent.student_id == sel.student_id).first()

        # data payload returned from this task
        payload = {}

        # records actions taken; returned as part of the payload from this task
        actions = []

        # if no record, insert one, but otherwise do nothing; this is designed to produce idempotent behaviour on
        # multiple application
        if sub is None:
            try:
                new_sub = SubmittingStudent(config_id=config_id, student_id=sel.student_id, selector_id=sel.id, published=False, retired=False)
                db.session.add(new_sub)
                actions.append("insert_submitter")
                needs_commit = True

                db.session.flush()
                payload.update({"new_submitter_id": new_sub.id})
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()
            else:
                sub = new_sub

        # second, determine whether there is an existing SubmissionRecord instance associated with this
        # submission period

        sr: SubmissionRecord = sub.get_assignment(period=data.submission_period)
        period: SubmissionPeriodRecord = sr.period

        now = datetime.now()

        def set_roles(sr: SubmissionRecord):
            new_ids = []
            for role in data.roles:
                role: MatchingRole
                weight = 1.0
                if role.role in [SubmissionRole.ROLE_MARKER]:
                    weight = 1.0 / float(period.number_markers)
                new_role = SubmissionRole(
                    submission_id=sr.id,
                    user_id=role.user_id,
                    role=role.role,
                    marking_distributed=False,
                    external_marking_url=None,
                    grade=None,
                    weight=weight,
                    justification=None,
                    signed_off=None,
                    positive_feedback=None,
                    improvements_feedback=None,
                    submitted_feedback=False,
                    feedback_timestamp=None,
                    acknowledge_student=False,
                    submitted_response=False,
                    response_timestamp=None,
                    feedback_sent=False,
                    feedback_push_id=None,
                    feedback_push_timestamp=None,
                    creator_id=user.id,
                    creation_timestamp=now,
                    last_edit_id=None,
                    last_edit_timestamp=None,
                )

                db.session.add(new_role)
                db.session.flush()
                new_ids.append(new_role.id)

            return new_ids

        # if no record, insert one, but otherwise do nothing
        if sr is None:
            try:
                pd: SubmissionPeriodRecord = config.get_period(data.submission_period)
                new_sr = SubmissionRecord(
                    period_id=pd.id,
                    retired=False,
                    owner_id=sub.id,
                    project_id=data.project_id,
                    selection_config_id=config.id,
                    matching_record_id=data.id,
                    student_engage=False,
                    use_project_hub=None,
                    report_id=None,
                    processed_report_id=None,
                    celery_started=False,
                    celery_finished=False,
                    timestamp=False,
                    report_exemplar=False,
                    report_embargo=False,
                    report_secret=False,
                    exemplar_comment=None,
                    supervision_grade=None,
                    report_grade=None,
                    grade_generated_id=None,
                    grade_generated_timestamp=None,
                    canvas_submission_available=False,
                    turnitin_outcome=None,
                    turnitin_score=None,
                    turnitin_web_overlap=None,
                    turnitin_publication_overlap=None,
                    turnitin_student_overlap=None,
                    feedback_generated=False,
                    feedback_sent=False,
                    feedback_push_id=None,
                    feedback_push_timestamp=None,
                    student_feedback=None,
                    student_feedback_submitted=None,
                    student_feedback_timestamp=None,
                )

                db.session.add(new_sr)
                actions.extend(["insert_submission", "set_project"])
                payload.update({"project_id": new_sr.project_id})
                db.session.flush()

                new_ids = set_roles(new_sr)
                actions.append("set_roles")
                payload.update({"new_role_ids": new_ids})

                needs_commit = True

            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()
        else:
            # do nothing is a project has already been specified for this student
            if sr.project is None:
                # empty existing submission roles
                sr.roles = []
                db.session.flush()

                sr.project_id = data.project_id
                sr.selection_config_id = config.id
                sr.matching_record_id = data.id
                payload.update({"project_id": sr.project_id})

                new_ids = set_roles(sr)
                actions.extend(["set_project", "set_roles"])
                payload.update({"new_role_ids": new_ids})

                needs_commit = True

        if needs_commit:
            try:
                db.session.commit()
                actions.append("commit")
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()

        payload.update({"actions": actions})
        return payload

    @celery.task(bind=True, default_retry_delay=30)
    def send_excel_report_by_email(self, matching_id, user_id, task_id):
        self.update_state(state="STARTED", meta={"msg": "Looking up MatchingAttempt record for id={id}".format(id=matching_id)})
        progress_update(task_id, TaskRecord.RUNNING, 10, "Looking up database records...", autocommit=True)

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=matching_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore()

        self.update_state("STARTED", meta={"msg": "Writing .xlsx report"})
        progress_update(task_id, TaskRecord.RUNNING, 50, "Writing .xlsx report...", autocommit=True)

        try:
            xlsx_asset: GeneratedAsset = _export_matching_as_excel(record, user)
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state("STARTED", meta={"msg": "Sending .xlsx report by email"})

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        now = datetime.now()

        msg = EmailMultiAlternatives(
            subject=f"Excel report for matching attempt {record.name} at {now.strftime('%Y-%m-%d %H:%M:%S')}",
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=[user.email],
        )

        msg.body = render_template("email/matching/notify_excel_report.txt", name=record.name, user=user)

        # TODO: will be problems when generated LP/MPS files are too large; should instead send a download link
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        xlsx_storage: AssetCloudAdapter = AssetCloudAdapter(xlsx_asset, object_store, audit_data="matching._send_excel_report_by_email #1")

        msg.attach(filename=xlsx_asset.target_name, mimetype=xlsx_asset.mimetype, content=xlsx_storage.get())

        # register a new task in the database
        send_task_id = register_task(msg.subject, description="Email to {r}".format(r=", ".join(msg.to)))

        self.update_state("STARTED", meta={"msg": "Handoff to email dispatch task"})

        send_tasks = chain(
            send_log_email.s(send_task_id, msg),
            notify_excel_file_sent.s(matching_id, user_id, send_task_id),
        )

        self.update_state("SUCCESS", meta={"msg": ".xlsx report generation complete"})
        progress_update(task_id, TaskRecord.SUCCESS, 100, ".xlsx report generation complete", autocommit=True)

        return self.replace(send_tasks)

    @celery.task(bind=True, default_retry_delay=5)
    def notify_excel_file_sent(self, result_data, matching_id, user_id, task_id):
        # result_data not currently used
        self.update_state("STARTED", meta={"msg": "Notify user that Excel report has been generated"})
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Excel report sent by email", autocommit=False)

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=matching_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load owning User record"})
            raise Ignore()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load MatchingAttempt record from database"})
            raise Ignore()

        self.update_state("STARTED", meta={"msg": "Post message to user"})
        user.post_message(f'An Excel report for matching "{record.name}" has been sent by email to {user.email}', "success", autocommit=False)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state("SUCCESS", meta={"msg": "Task complete"})

    def _export_matching_as_excel(record: MatchingAttempt, user: User):
        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        def make_asset(source_path: Path, target_name: str):
            # AssetUploadManager will populate most fields later
            asset = GeneratedAsset(timestamp=now, expiry=expiry, target_name=target_name, parent_asset_id=None, license_id=None)

            size = source_path.stat().st_size

            with open(source_path, "rb") as f:
                with AssetUploadManager(
                    asset,
                    data=BytesIO(f.read()),
                    storage=object_store,
                    audit_data=f"matching._export_matching_as_excel (matching attempt #{record.id})",
                    length=size,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    validate_nonce=validate_nonce,
                ) as upload_mgr:
                    pass

            asset.grant_user(user)
            db.session.add(asset)

            return asset

        with ScratchFileManager(suffix=".xlsx") as mgr:
            records = []

            for item in record.records:
                item: MatchingRecord
                sel: SelectingStudent = item.selector
                sd: StudentData = sel.student
                su: User = sd.user
                programme: DegreeProgramme = sd.programme
                proj: LiveProject = item.project
                config: ProjectClassConfig = sel.config
                ofd: FacultyData = proj.owner
                ou: User = None if ofd is None else ofd.user

                data = {
                    "selector_last": su.last_name,
                    "selector_first": su.first_name,
                    "selector_full_name": su.name,
                    "selector_email": su.email,
                    "programme": programme.short_name,
                    "project_class": config.abbreviation,
                    "submission_period": item.submission_period,
                    "cohort": sd.cohort,
                    "academic_year": sd.academic_year,
                    "intermitting": sd.intermitting,
                    "bookmarks": sel.number_bookmarks,
                    "selections": sel.number_selections,
                    "custom_offers": sel.number_custom_offers(),
                    "custom_offers_accepted": sel.number_offers_accepted(),
                    "custom_offers_declined": sel.number_offers_declined(),
                    "custom_offers_pending": sel.number_offers_pending(),
                    "is_optional": sel.is_optional,
                    "is_valid_selection": sel.is_valid_selection[0],
                    "allocated_project": proj.name,
                    "generic": proj.generic or proj.owner is None,
                    "owner_last": None if ou is None else ou.last_name,
                    "owner_first": None if ou is None else ou.first_name,
                    "owner_full_name": None if ou is None else ou.name,
                    "owner_email": None if ou is None else ou.email,
                    "rank": item.rank,
                    "is_alternative": item.alternative,
                    "priority": None if not item.alternative else item.priority,
                }

                label_numbers = {}
                for role in item.roles.order_by(MatchingRole.role):
                    role: MatchingRole
                    ud: User = role.user

                    label = MatchingRole._role_labels[role.role]
                    if label not in label_numbers:
                        label_numbers[label] = 0

                    label_numbers[label] += 1
                    num = label_numbers[label]

                    data.update(
                        {
                            f"{label}_{num}_last": ud.last_name,
                            f"{label}_{num}_first": ud.first_name,
                            f"{label}_{num}_full_name": ud.name,
                            f"{label}_{num}_email": ud.email,
                        }
                    )

                records.append(data)

            df = DataFrame.from_records(records)

            output_path = mgr.path
            df.to_excel(output_path, sheet_name=f'Matching "{record.name}"', index=False)
            xlsx_asset = make_asset(output_path, f"Matching_{record.name}-{now.strftime("%Y-%m-%d_%H:%M:%S")}")

        db.session.commit()
        return xlsx_asset
