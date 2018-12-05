#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..database import db
from ..models import MatchingAttempt, TaskRecord, LiveProject, SelectingStudent, \
    User, EnrollmentRecord, MatchingRecord, SelectionRecord

from ..shared.sqlalchemy import get_count
from ..task_queue import progress_update

from sqlalchemy.exc import SQLAlchemyError

from celery import group, chain

import pulp
import pulp.solvers as solvers
import itertools
from datetime import datetime

from ..shared.timer import Timer


def _find_mean_project_CATS(configs):

    CATS_total = 0
    number = 0

    for config in configs:
        if config.CATS_supervision is not None:
            CATS_total += config.CATS_supervision
            number += 1

    return float(CATS_total)/number


def _enumerate_selectors(configs):
    """
    Build a list of SelectingStudents who belong to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute assignment multiplicity for each selector, ie. how many projects they should be
    assigned (eg. FYP = 1 but MPP = 2 since projects only last one term)
    :param configs:
    :return:
    """

    number = 0
    sel_to_number = {}
    number_to_sel = {}

    multiplicity = {}

    selector_dict = {}

    for config in configs:
        # get SelectingStudent instances that are not retired and belong to this config instance

        # however, we need to remember that for projects marked 'selection_open_to_all',
        # we should interpret failure to submit choices as an indication that the selector
        # doesn't wish to participate.
        # So, in this case, we shouldn't forward the selector for matching

        # also, if the project automatically rolls over supervisor assignments,
        # then failure to submit choices indicates that the selector is happy with their
        # existing assignment.
        # So in this case too, we shouldn't forward the selector for matching

        open_to_all = config.selection_open_to_all
        carryover = config.supervisor_carryover

        selectors = db.session.query(SelectingStudent) \
            .filter_by(retired=False, config_id=config.id).all()

        for item in selectors:

            attach = False
            if item.has_submitted:
                # always count selectors who have submitted choices
                attach = True
            else:
                if open_to_all and item.academic_year == config.start_year - 1:
                    # interpret failure to submit as lack of interest
                    pass
                elif carryover and config.start_year <= item.academic_year < config.start_year + config.extent:
                    # interpret failure to submit as evidence student is happy with existing allocation
                    pass
                else:
                    # otherwise, assume a match should be generated
                    attach = True

            if attach:
                sel_to_number[item.id] = number
                number_to_sel[number] = item.id

                submissions = config.submissions
                multiplicity[number] = submissions if submissions >= 1 else 1

                selector_dict[number] = item

                number += 1

    return number, sel_to_number, number_to_sel, multiplicity, selector_dict


def _enumerate_liveprojects(configs):
    """
    Build a list of LiveProjects belonging to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute CATS values for supervising and marking each project
    :param configs:
    :return: 
    """

    number = 0
    lp_to_number = {}
    number_to_lp = {}

    CATS_supervisor = {}
    CATS_marker = {}

    capacity = {}

    project_dict = {}

    for config in configs:
        # get LiveProject instances that belong to this config instance
        projects = db.session.query(LiveProject) \
            .filter_by(config_id=config.id).all()

        for item in projects:
            lp_to_number[item.id] = number
            number_to_lp[number] = item.id

            sup = config.CATS_supervision
            mk = config.CATS_marking
            CATS_supervisor[number] = sup if sup is not None else 30
            CATS_marker[number] = mk if mk is not None else 3

            capacity[number] = item.capacity if (item.enforce_capacity and
                                                 item.capacity is not None and
                                                 item.capacity > 0) else 0

            project_dict[number] = item

            number += 1

    return number, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, project_dict


def _enumerate_supervising_faculty(configs):
    """
    Build a list of active, enrolled supervising faculty belonging to projects that
    participate in automatic matching, and assign them to consecutive numbers beginning at zero
    :param configs:
    :return:
    """

    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}

    fac_dict = {}

    for config in configs:
        # get EnrollmentRecord instances for this project class
        faculty = db.session.query(EnrollmentRecord) \
            .filter_by(pclass_id=config.pclass_id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED) \
            .join(User, User.id==EnrollmentRecord.owner_id) \
            .filter(User.active).all()

        for item in faculty:
            if item.owner_id not in fac_to_number:
                fac_to_number[item.owner_id] = number
                number_to_fac[number] = item.owner_id

                lim = item.owner.CATS_supervision
                limit[number] = lim if lim is not None and lim > 0 else 0

                fac_dict[number] = item.owner

                number += 1

    return number, fac_to_number, number_to_fac, limit, fac_dict


def _enumerate_marking_faculty(configs):
    """
    Build a list of active, enrolled 2nd-marking faculty belonging to projects that
    participate in automatic matching, and assign them to consecutive numbers beginning at zero
    :param configs:
    :return:
    """

    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}

    fac_dict = {}

    for config in configs:
        # get EnrollmentRecord instances for this project class
        faculty = db.session.query(EnrollmentRecord) \
            .filter_by(pclass_id=config.pclass_id, marker_state=EnrollmentRecord.MARKER_ENROLLED) \
            .join(User, User.id == EnrollmentRecord.owner_id) \
            .filter(User.active).all()

        for item in faculty:
            if item.owner_id not in fac_to_number:
                fac_to_number[item.owner_id] = number
                number_to_fac[number] = item.owner_id

                lim = item.owner.CATS_marking
                limit[number] = lim if lim is not None and lim > 0 else 0

                fac_dict[number] = item.owner

                number += 1

    return number, fac_to_number, number_to_fac, limit, fac_dict


def _build_ranking_matrix(number_students, student_dict, number_projects, project_dict, record):
    """
    Construct a dictionary mapping from (student, project) pairs to the rank assigned
    to that project by the student.
    Also build a weighting matrix that accounts for other factors we wish to weight
    in the assignment, such as degree programme
    :param number_students:
    :param student_dict:
    :param number_projects:
    :param project_dict:
    :return:
    """

    R = {}          # R is ranking matrix. Accounts for Forbid hints.
    W = {}          # W is weights matrix. Accounts for encourage & discourage hints, programme bias and bookmark bias
    cstr = set()    # cstr is a set of (student, project) pairs that will be converted into Require hints

    ignore_programme_prefs = record.ignore_programme_prefs
    programme_bias = float(record.programme_bias) if record.programme_bias is not None else 1.0
    bookmark_bias = float(record.bookmark_bias) if record.bookmark_bias is not None else 1.0

    use_hints = record.use_hints
    encourage_bias = float(record.encourage_bias)
    discourage_bias = float(record.discourage_bias)
    strong_encourage_bias = float(record.strong_encourage_bias)
    strong_discourage_bias = float(record.strong_discourage_bias)

    for i in range(0, number_students):

        sel = student_dict[i]

        ranks = {}
        weights = {}
        require = set()

        if sel.has_submitted:
            for item in sel.selections.all():
                if item.hint != SelectionRecord.SELECTION_HINT_FORBID or not use_hints:
                    ranks[item.liveproject_id] = item.rank

                w = 1.0
                if item.converted_from_bookmark:
                    w *= bookmark_bias
                if use_hints:
                    if item.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE:
                        w *= encourage_bias
                    elif item.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE:
                        w *= discourage_bias
                    elif item.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG:
                        w *= strong_encourage_bias
                    elif item.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG:
                        w *= strong_discourage_bias

                weights[item.liveproject_id] = w

                if use_hints and item.hint == SelectionRecord.SELECTION_HINT_REQUIRE:
                    require.add(item.liveproject_id)

        else:
            # no ranking data, so rank all LiveProjects in the right project class equal to 1
            for k in project_dict:
                proj = project_dict[k]

                if sel.config_id == proj.config_id:
                    ranks[proj.id] = 1

        for j in range(0, number_projects):

            idx = (i, j)
            proj = project_dict[j]

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
            if not ignore_programme_prefs:
                if proj.satisfies_preferences(sel):
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

    for i in range(0, number_mark):
        fac = mark_dict[i]

        for j in range(0, number_projects):
            idx = (i, j)
            proj = project_dict[j]

            if proj.config.uses_marker:
                count = get_count(proj.assessor_list_query.filter_by(id=fac.id))

                if count == 1:
                    M[idx] = max_multiplicity
                elif count == 0:
                    M[idx] = 0
                else:
                    raise RuntimeError('Inconsistent number of second markers match to LiveProject: '
                                       'fac={fname}, proj={pname}, '
                                       'matches={c}'.format(fname=fac.user.name, pname=proj.name, c=count))

            else:
                M[idx] = 0

    return M


def _build_project_supervisor_matrix(number_proj, proj_dict, number_sup, sup_dict):
    """
    Construct a dictionary mapping from (project, supervisor) pairs to:
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

        proj = proj_dict[i]

        for j in range(number_sup):

            idx = (i,j)

            fac = sup_dict[j]

            if proj.owner_id == fac.id:
                P[idx] = 1
            else:
                P[idx] = 0

    return P


def _create_PuLP_problem(R, M, W, P, cstr, CATS_supervisor, CATS_marker, capacity, sup_limits, mark_limits,
                         multiplicity, number_lp, number_mark, number_sel, number_sup, record, lp_dict,
                         sup_only_numbers, mark_only_numbers, sup_and_mark_numbers,
                         levelling_bias, intra_group_tension, mean_CATS_per_project):
    """
    Generate a PuLP problem to find an optimal assignment of projects+2nd markers to students
    :param R:
    :param M:
    :param W:
    :param P:
    :param CATS_supervisor:
    :param CATS_marker:
    :param capacity:
    :param sup_limits:
    :param mark_limits:
    :param multiplicity:
    :param number_lp:
    :param number_mark:
    :param number_sel:
    :param number_sup:
    :param record:
    :return:
    """

    if not isinstance(levelling_bias, float):
        levelling_bias = float(levelling_bias)

    if not isinstance(intra_group_tension, float):
        intra_group_tension = float(intra_group_tension)

    if not isinstance(mean_CATS_per_project, float):
        mean_CATS_per_project = float(mean_CATS_per_project)

    # generate PuLP problem
    prob = pulp.LpProblem(record.name, pulp.LpMaximize)

    # generate decision variables for project assignment matrix
    # the entries of this matrix are either 0 or 1
    X = pulp.LpVariable.dicts("x", itertools.product(range(number_sel), range(number_lp)), cat=pulp.LpBinary)

    # generate decision variables for marker assignment matrix
    # the entries of this matrix are integers, indicating multiplicity of assignment if > 1
    Y = pulp.LpVariable.dicts("y", itertools.product(range(number_mark), range(number_lp)),
                              cat=pulp.LpInteger, lowBound=0)

    # to implement workload balancing we use pairs of continuous variables that relax
    # to the maximum and minimum workload for each faculty group:
    # supervisors+marks, supervisors only, markers only

    # the objective function contains a linear potential that tensions the top and
    # bottom workload in each band against each other, so the solution is rewarded for
    # balancing workloads within each group

    # we also tension the workload between groups, so that the workload of no one group
    # is pushed too far away from the others, subject to existing CATS caps
    supMax = pulp.LpVariable("supMax", lowBound=0, cat=pulp.LpContinuous)
    supMin = pulp.LpVariable("supMin", lowBound=0, cat=pulp.LpContinuous)

    markMax = pulp.LpVariable("markMax", lowBound=0, cat=pulp.LpContinuous)
    markMin = pulp.LpVariable("markMin", lowBound=0, cat=pulp.LpContinuous)

    supMarkMax = pulp.LpVariable("supMarkMax", lowBound=0, cat=pulp.LpContinuous)
    supMarkMin = pulp.LpVariable("supMarkMin", lowBound=0, cat=pulp.LpContinuous)

    globalMax = pulp.LpVariable("globalMax", lowBound=0, cat=pulp.LpContinuous)
    globalMin = pulp.LpVariable("globalMin", lowBound=0, cat=pulp.LpContinuous)

    # finally, to spread second-marking tasks fairly among a pool of faculty, where any
    # particular assignment won't significantly affect markMax/markMin or supMarkMax/supMarkMin,
    # we add a term to the objective function designed to keep down the maximum number of
    # projects assigned to any individual faculty member.
    maxMarking = pulp.LpVariable("maxMarking", lowBound=0, cat=pulp.LpContinuous)


    # OBJECTIVE FUNCTION

    # generate objective function
    objective = 0

    # reward the solution for assigning students to highly ranked projects:
    for i in range(number_sel):
        for j in range(number_lp):
            idx = (i, j)
            if R[idx] > 0:
                # score is 1/rank of assigned project, weighted
                objective += X[idx] * W[idx] / R[idx]

    # tension top and bottom workloads in each group against each other
    levelling = (supMax - supMin) \
                + (markMax - markMin) \
                + (supMarkMax - supMarkMin) \
                + abs(intra_group_tension)*(globalMax - globalMin)

    # apart from attempting to balance workloads, there is no need to add a reward for marker assignments;
    # these only need to satisfy the constraints, and any one solution is as good as another

    # dividing through by mean_CATS_per_project makes a workload discrepancy of 1 project between
    # upper and lower limits roughly equal to one ranking place in matching to students
    prob += objective \
            - abs(levelling_bias) * levelling / mean_CATS_per_project \
            - abs(levelling_bias) * maxMarking, "objective function"


    # STUDENT RANKING, WORKLOAD LIMITS, PROJECT CAPACITY LIMITS

    # selectors can only be assigned to projects that they have ranked
    # (unless no ranking data was available, in which case all elements of R were set to 1)
    for key in X:
        prob += X[key] <= R[key]

    # markers can only be assigned projects to which they are attached
    for key in Y:
        prob += Y[key] <= M[key]

    # enforce desired multiplicity for each selector
    # (usually requires that each selector is assigned just one project, but can be 2 for eg. MPP)
    for i in range(number_sel):
        prob += sum(X[(i, j)] for j in range(number_lp)) == multiplicity[i]

    # enforce maximum capacity for each project
    # note capacity[j] will be zero if this project is not enforcing an upper limit on capacity
    for j in range(number_lp):
        if capacity[j] != 0:
            prob += sum(X[(i, j)] for i in range(number_sel)) <= capacity[j]

    # number of students assigned to each project must match number of markers assigned to each project,
    # if markers are being used; otherwise, number of markers should be zero
    for j in range(number_lp):
        if j not in lp_dict:
            raise RuntimeError('lp_dict does not contain all projects when constructing PuLP problem')

        proj = lp_dict[j]

        if proj.config.uses_marker:
            prob += sum(X[(i, j)] for i in range(number_sel)) - \
                    sum(Y[(i, j)] for i in range(number_mark)) == 0

        else:
            for j in range(number_mark):
                prob += Y[(i, j)] == 0      # enforce no markers assigned to this project

    # CATS assigned to each supervisor must be within bounds
    for i in range(number_sup):

        lim = record.supervising_limit
        if not record.ignore_per_faculty_limits and sup_limits[i] > 0:
            lim = sup_limits[i]

        prob += sum(X[(k, j)] * CATS_supervisor[j] * P[(j, i)] for j in range(number_lp)
                    for k in range(number_sel)) <= lim

    # CATS assigned to each marker must be within bounds
    for i in range(number_mark):

        lim = record.marking_limit
        if not record.ignore_per_faculty_limits and mark_limits[i] > 0:
            lim = mark_limits[i]

        prob += sum(Y[(i, j)] * CATS_marker[j] for j in range(number_lp)) <= lim

    # add constraints for any matches marked 'require' by a convenor
    for idx in cstr:
        prob += X[idx] == 1


    # WORKLOAD LEVELLING

    global_trivial = True

    # supMin and supMax should bracket the CATS workload of faculty who supervise only
    if len(sup_only_numbers) > 0:
        for i in sup_only_numbers:
            prob += sum(X[(k, j)] * CATS_supervisor[j] * P[(j, i)] for j in range(number_lp)
                        for k in range(number_sel)) <= supMax
            prob += sum(X[(k, j)] * CATS_supervisor[j] * P[(j, i)] for j in range(number_lp)
                        for k in range(number_sel)) >= supMin

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
        for i1, i2 in sup_and_mark_numbers:
            prob += sum(X[(k, j)] * CATS_supervisor[j] * P[(j, i1)] for j in range(number_lp)
                        for k in range(number_sel)) \
                    + sum(Y[(i2, j)] * CATS_marker[j] for j in range(number_lp)) <= supMarkMax
            prob += sum(X[(k, j)] * float(CATS_supervisor[j]) * P[(j, i1)] for j in range(number_lp)
                        for k in range(number_sel)) \
                    + sum(Y[(i2, j)] * CATS_marker[j] for j in range(number_lp)) >= supMarkMin

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

    # maxMarking should be larger than the total number of projects assigned for 2nd marking to
    # any individual faculty member
    if number_mark > 0:
        for i in range(number_mark):
            prob += sum(Y[(i, j)] for j in range(number_lp)) <= maxMarking
    else:
        prob += maxMarking == 0

    return prob, X, Y


def _store_PuLP_solution(X, Y, record, number_sel, number_to_sel, number_lp, number_to_lp, number_mark, number_to_mark,
                         multiplicity, sel_dict, sup_dict, mark_dict, lp_dict, mean_CATS_per_project):
    """
    Store a matching satisfying all the constraints of the pulp problem
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
    for k in sup_dict:
        record.supervisors.append(sup_dict[k])

    for k in mark_dict:
        record.markers.append(mark_dict[k])

    for k in lp_dict:
        record.projects.append(lp_dict[k])

    record.mean_CATS_per_project = mean_CATS_per_project

    # generate dictionary of marker assignments; we map each project id to a list of available markers
    markers = {}
    for j in range(number_lp):

        proj_id = number_to_lp[j]
        if proj_id in markers:
            raise RuntimeError('PuLP solution has inconsistent marker assignment')

        assigned = []

        for i in range(number_mark):
            Y[(i,j)].round()
            m = pulp.value(Y[(i,j)])
            if m > 0:
                for k in range(m):
                    assigned.append(number_to_mark[i])

        markers[proj_id] = assigned

    # loop through all selectors that participated in the matching, generating matching records for each one
    for i in range(number_sel):

        if i not in sel_dict:
            raise RuntimeError('PuLP solution contains invalid selector id')

        sel = sel_dict[i]

        if sel.id != number_to_sel[i]:
            raise RuntimeError('Inconsistent selector ids when storing PuLP solution')

        # generate list of project assignments for this selector
        assigned = []

        for j in range(number_lp):
            X[(i,j)].round()
            if pulp.value(X[(i,j)]) == 1:
                assigned.append(j)

        if len(assigned) != multiplicity[i]:
            raise RuntimeError('PuLP solution has unexpected multiplicity')

        for m in range(multiplicity[i]):

            # pop a project assignment from the back of the stack
            proj_number = assigned.pop()
            proj_id = number_to_lp[proj_number]

            if proj_number not in lp_dict:
                raise RuntimeError('PuLP solution references unexpected LiveProject instance')
            project = lp_dict[proj_number]

            if proj_id != project.id:
                raise RuntimeError('Inconsistent project lookup when storing PuLP solution')

            # assign a marker if one is used
            if project.config.uses_marker:
                # pop a 2nd marker from the back of the stack associated with this project
                if proj_id not in markers:
                    raise RuntimeError('PuLP solution error: marker stack unexpectedly empty or missing')

                marker = markers[proj_id].pop()
                if marker is None:
                    raise RuntimeError('PuLP solution assigns too few markers to project')

            else:
                marker = None

            rk = sel.project_rank(proj_id)
            if sel.has_submitted and rk is None:
                raise RuntimeError('PuLP solution assigns unranked project to selector')

            data = MatchingRecord(matching_id=record.id,
                                  selector_id=number_to_sel[i],
                                  project_id=proj_id,
                                  original_project_id=proj_id,
                                  marker_id=marker,
                                  original_marker_id=marker,
                                  submission_period=m+1,
                                  rank=rk)
            db.session.add(data)


def register_matching_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_match(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            return

        progress_update(record.celery_id, TaskRecord.RUNNING, 5, "Collecting information...", autocommit=True)

        try:
            # get list of project classes participating in automatic assignment
            configs = record.config_members
            mean_CATS_per_project = _find_mean_project_CATS(configs)

            # get lists of selectors and liveprojects, together with auxiliary data such as
            # multiplicities (for selectors) and CATS assignments (for projects)
            number_sel, sel_to_number, number_to_sel, multiplicity, sel_dict = _enumerate_selectors(configs)
            number_lp, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, \
                lp_dict = _enumerate_liveprojects(configs)

            # get supervising faculty and marking faculty lists
            number_sup, sup_to_number, number_to_sup, sup_limits, sup_dict = _enumerate_supervising_faculty(configs)
            number_mark, mark_to_number, number_to_mark, mark_limits, mark_dict = _enumerate_marking_faculty(configs)

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

            # build student ranking matrix
            R, W, cstr = _build_ranking_matrix(number_sel, sel_dict, number_lp, lp_dict, record)

            # build marker compatibility matrix
            mm = record.max_marking_multiplicity
            M = _build_marking_matrix(number_mark, mark_dict, number_lp, lp_dict, mm if mm >= 1 else 1)

            # build project-to-supervisor mapping
            P = _build_project_supervisor_matrix(number_lp, lp_dict, number_sup, sup_dict)

        except SQLAlchemyError:
            raise self.retry()

        progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...", autocommit=True)

        with Timer() as create_time:
            prob, X, Y = _create_PuLP_problem(R, M, W, P, cstr, CATS_supervisor, CATS_marker, capacity, sup_limits, mark_limits,
                                              multiplicity, number_lp, number_mark, number_sel, number_sup, record, lp_dict,
                                              sup_only_numbers, mark_only_numbers, sup_and_mark_numbers,
                                              record.levelling_bias, record.intra_group_tension, mean_CATS_per_project)

        progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...", autocommit=True)

        with Timer() as solve_time:
            record.awaiting_upload = False

            if record.solver == MatchingAttempt.SOLVER_CBC_PACKAGED:
                output = prob.solve(solvers.PULP_CBC_CMD(msg=1, maxSeconds=600, fracGap=0.01))
            elif record.solver == MatchingAttempt.SOLVER_CBC_CMD:
                output = prob.solve(solvers.COIN_CMD(msg=1, maxSeconds=600, fracGap=0.01))
            elif record.solver == MatchingAttempt.SOLVER_GLPK_CMD:
                output = prob.solve(solvers.GLPK_CMD())
            else:
                output = prob.solve()

        state = pulp.LpStatus[output]

        if state == 'Optimal':
            record.outcome = MatchingAttempt.OUTCOME_OPTIMAL
            record.score = pulp.value(prob.objective)

            record.construct_time = create_time.interval
            record.compute_time = solve_time.interval

            progress_update(record.celery_id, TaskRecord.RUNNING, 80, "Storing PuLP solution...", autocommit=True)

            try:
                _store_PuLP_solution(X, Y, record, number_sel, number_to_sel, number_lp, number_to_lp, number_mark,
                                     number_to_mark, multiplicity, sel_dict, sup_dict, mark_dict, lp_dict,
                                     mean_CATS_per_project)
                db.session.commit()

            except SQLAlchemyError:
                db.session.rollback()
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
            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        return record.score


    @celery.task(bind=True, default_retry_delay=30)
    def revert_record(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingRecord record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingRecord).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingRecord record from database')
            return

        try:
            record.project_id = record.original_project_id
            record.marker_id = record.original_marker_id
            record.rank = record.selector.project_rank(record.original_project_id)
            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        return None


    @celery.task(bind=True, default_retry_delay=30)
    def revert_finalize(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingRecord record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            return

        try:
            record.last_edit_id = None
            record.last_edit_timestamp = None
            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        return None


    @celery.task(bind=True, default_retry_delay=30)
    def revert(self, id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingRecord record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            return

        wg = group(revert_record.si(r.id) for r in record.records.all())
        seq = chain(wg, revert_finalize.si(id))

        seq.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def duplicate(self, id, new_name, current_id):
        self.update_state(state='STARTED',
                          meta='Looking up MatchingRecord record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load MatchingAttempt record from database')
            return

        # encapsulate the whole duplication process in a single transaction, so the process is as close to
        # atomic as we can make it

        try:
            # generate a new MatchingRecord
            data = MatchingAttempt(year=record.year,
                                   name=new_name,
                                   config_members=record.config_members,
                                   published=record.published,
                                   selected=False,
                                   celery_id=None,
                                   finished=record.finished,
                                   awaiting_upload=record.awaiting_upload,
                                   outcome=record.outcome,
                                   solver=record.solver,
                                   construct_time=record.construct_time,
                                   compute_time=record.compute_time,
                                   ignore_per_faculty_limits=record.ignore_per_faculty_limits,
                                   ignore_programme_prefs=record.ignore_programme_prefs,
                                   years_memory=record.years_memory,
                                   supervising_limit=record.supervising_limit,
                                   marking_limit=record.marking_limit,
                                   max_marking_multiplicity=record.max_marking_multiplicity,
                                   use_hints=record.use_hints,
                                   encourage_bias=record.encourage_bias,
                                   discourage_bias=record.discourage_bias,
                                   strong_encourage_bias=record.strong_encourage_bias,
                                   strong_discourage_bias=record.strong_discourage_bias,
                                   bookmark_bias=record.bookmark_bias,
                                   levelling_bias=record.levelling_bias,
                                   intra_group_tension=record.intra_group_tension,
                                   programme_bias=record.programme_bias,
                                   include_matches=record.include_matches,
                                   score=record.current_score,                                      # note that current score becomes original score
                                   supervisors=record.supervisors,
                                   markers=record.markers,
                                   projects=record.projects,
                                   mean_CATS_per_project=record.mean_CATS_per_project,
                                   creator_id=current_id,
                                   creation_timestamp=datetime.now(),
                                   last_edit_id=None,
                                   last_edit_timestamp=None)

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

            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        return None
