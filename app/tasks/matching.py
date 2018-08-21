#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..models import db, MatchingAttempt, TaskRecord, ProjectClass, ProjectClassConfig, LiveProject, SelectingStudent, \
    User, EnrollmentRecord, DegreeProgramme, FacultyData

from ..shared.utils import get_current_year
from ..task_queue import progress_update

from celery import chain, group

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

import pulp
import itertools


def find_pclasses():
    """
    Build a list of pclasses that participate in automatic matching
    :return:
    """

    pclasses = db.session.query(ProjectClass).filter_by(active=True, do_matching=True).all()

    return pclasses


def get_current_pclass_config(pclass):

    current_year = get_current_year()

    # get ProjectClassConfig for the current year
    config = db.session.query(ProjectClassConfig) \
        .filter_by(pclass_id=pclass.id, year=current_year) \
        .order_by(ProjectClassConfig.year.desc()).first()

    if config is None:
        raise RuntimeError(
            'Configuration record for "{name}" and year={yr} is missing'.format(name=pclass.name, yr=current_year))

    return config


def enumerate_selectors(pclasses):
    """
    Build a list of SelectingStudents who belong to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute assignment multiplicity for each selector, ie. how many projects they should be
    assigned (eg. FYP = 1 but MPP = 2 since projects only last one term)
    :param pclasses:
    :return:
    """

    number = 0
    sel_to_number = {}
    number_to_sel = {}

    multiplicity = {}

    selector_dict = {}

    for pclass in pclasses:
        config = get_current_pclass_config(pclass)

        # get SelectingStudent instances that are not retired and belong to this config instance
        selectors = db.session.query(SelectingStudent) \
            .filter_by(retired=False, config_id=config.id).all()

        for item in selectors:
            sel_to_number[item.id] = number
            number_to_sel[number] = item.id

            multiplicity[number] = pclass.submissions if pclass.submissions >= 1 else 1

            selector_dict[number] = item

            number += 1

    return number, sel_to_number, number_to_sel, multiplicity, selector_dict


def enumerate_liveprojects(pclasses):
    """
    Build a list of LiveProjects belonging to projects that participate in automatic
    matching, and assign them to consecutive numbers beginning at 0.
    Also compute CATS values for supervising and marking each project
    :param pclasses: 
    :return: 
    """

    number = 0
    lp_to_number = {}
    number_to_lp = {}

    CATS_supervisor = {}
    CATS_marker = {}

    capacity = {}

    project_dict = {}

    for pclass in pclasses:
        config = get_current_pclass_config(pclass)

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

            capacity[number] = item.capacity if (item.enforce_capacity and item.capacity > 0) else 0

            project_dict[number] = item

            number += 1

    return number, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, project_dict


def enumerate_supervising_faculty(pclasses):
    """
    Build a list of active, enrolled supervising faculty belonging to projects that
    participate in automatic matching, and assign them to consecutive numbers beginning at zero
    :param pclasses:
    :return:
    """

    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}

    fac_dict = {}

    for pclass in pclasses:

        # get EnrollmentRecord instances for this project class
        faculty = db.session.query(EnrollmentRecord) \
            .filter_by(pclass_id=pclass.id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED) \
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


def enumerate_marking_faculty(pclasses):
    """
    Build a list of active, enrolled 2nd-marking faculty belonging to projects that
    participate in automatic matching, and assign them to consecutive numbers beginning at zero
    :param pclasses:
    :return:
    """

    number = 0
    fac_to_number = {}
    number_to_fac = {}

    limit = {}

    fac_dict = {}

    for pclass in pclasses:

        # get EnrollmentRecord instances for this project class
        faculty = db.session.query(EnrollmentRecord) \
            .filter_by(pclass_id=pclass.id, marker_state=EnrollmentRecord.MARKER_ENROLLED) \
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


def build_ranking_matrix(number_students, student_dict, number_projects, project_dict, ignore_programme_prefs=False):
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

    R = {}
    W = {}

    for i in range(0, number_students):

        sel = student_dict[i]

        ranks = {}

        if sel.has_submitted:
            for item in sel.selections.all():
                ranks[item.liveproject_id] = item.rank
        elif sel.has_bookmarks:
            for item in sel.bookmarks.all():
                ranks[item.liveproject_id] = item.rank

        for j in range(0, number_projects):

            idx = (i, j)
            proj = project_dict[j]

            if proj.id in ranks:
                R[idx] = ranks[proj.id]
            else:
                R[idx] = 0

            # compute weight for this (student, project) combination
            w = 1.0

            # check whether this project has a preference for the degree programme associated with the current selector
            if not ignore_programme_prefs:
                prog_query = proj.programmes.subquery()
                count = db.session.query(func.count(prog_query.c.id)) \
                    .filter(prog_query.c.id == sel.student.programme_id) \
                    .scalar()

                if count == 1:
                    # TODO: reward for matching preferred programme might need tuning
                    w *= 2.0
                elif count > 1:
                    raise RuntimeError('Inconsistent number of degree preferences match to SelectingStudent')

            W[idx] = w

    return R, W


def build_marking_matrix(number_mark, mark_dict, number_projects, project_dict, max_multiplicity):
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

            if proj.config.project_class.uses_marker:

                marker_query = proj.second_markers.subquery()
                count = db.session.query(func.count(marker_query.c.id)) \
                    .filter(marker_query.c.id == fac.id) \
                    .scalar()

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


def build_project_supervisor_matrix(number_proj, proj_dict, number_sup, sup_dict):
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
            pclasses = find_pclasses()

            # get lists of selectors and liveprojects, together with auxiliary data such as
            # multiplicities (for selectors) and CATS assignments (for projects)
            number_sel, sel_to_number, number_to_sel, multiplicity, sel_dict = enumerate_selectors(pclasses)
            number_lp, lp_to_number, number_to_lp, CATS_supervisor, CATS_marker, capacity, \
                lp_dict = enumerate_liveprojects(pclasses)

            # get supervising faculty and marking faculty lists
            number_sup, sup_to_number, number_to_sup, sup_limits, sup_dict = enumerate_supervising_faculty(pclasses)
            number_mark, mark_to_number, number_to_mark, mark_limits, mark_dict = enumerate_marking_faculty(pclasses)

            # build student ranking matrix
            R, W = build_ranking_matrix(number_sel, sel_dict, number_lp, lp_dict, record.ignore_programme_prefs)

            # build marker compatibility matrix
            mm = record.max_marking_multiplicity
            M = build_marking_matrix(number_mark, mark_dict, number_lp, lp_dict, mm if mm >= 1 else 1)

            # build project-to-supervisor mapping
            P = build_project_supervisor_matrix(number_lp, lp_dict, number_sup, sup_dict)

        except SQLAlchemyError:
            raise self.retry()

        progress_update(record.celery_id, TaskRecord.RUNNING, 20, "Generating PuLP linear programming problem...", autocommit=True)

        # generate PuLP problem
        prob = pulp.LpProblem(record.name, pulp.LpMaximize)

        # generate decision variables for project assignment matrix
        # the entries of this matrix are either 0 or 1
        X = pulp.LpVariable.dicts("x", itertools.product(range(number_sel), range(number_lp)), cat=pulp.LpBinary)

        # generate decision variables for marker assignment matrix
        # the entries of this matrix are integers, indicating multiplicity of assignment if > 1
        Y = pulp.LpVariable.dicts("y", itertools.product(range(number_mark), range(number_lp)), cat=pulp.LpInteger)

        # generate objective function
        objective = 0

        # reward the solution for assigning students to highly ranked projects:
        for i in range(number_sel):
            for j in range(number_lp):
                idx = (i,j)
                if R[idx] > 0:
                    objective += X[idx] * W[idx] / R[idx]

        # no need to add a reward for marker assignments; these only need to satisfy the constraints, and any
        # one solution is as good as another

        prob += objective, "objective function"

        # selectors can only be assigned to projects that they have ranked
        for key in X:
            prob += X[key] <= float(R[key])

        # markers can only be assigned projects to which they are attached
        for key in Y:
            prob += Y[key] <= float(M[key])

        # enforce desired multiplicity for each selector
        for i in range(number_sel):
            prob += sum(X[(i,j)] for j in range(number_lp)) == float(multiplicity[i])

        # enforce maximum capacity for each project
        for j in range(number_lp):
            if capacity[j] != 0:
                prob += sum(X[(i,j)] for i in range(number_sel)) <= float(capacity[j])

        # number of students assigned to each project must match number of markers assigned to each project
        for j in range(number_lp):
            prob += sum(X[(i,j)] for i in range(number_sel)) - \
                sum(Y[(i,j)] for i in range(number_mark)) == float(0)

        # CATS assigned to each supervisor must be within bounds
        for i in range(number_sup):

            lim = record.supervising_limit
            if not record.ignore_per_faculty_limits and sup_limits[i] > 0:
                lim = sup_limits[i]

            prob += sum(X[(k, j)] * float(CATS_supervisor[j]) * float(P[(j, i)]) for j in range(number_lp)
                        for k in range(number_sel)) <= float(lim)

        # CATS assigned to each marker must be within bounds
        for i in range(number_mark):

            lim = record.marking_limit
            if not record.ignore_per_faculty_limits and mark_limits[i] > 0:
                lim = mark_limits[i]

            prob += sum(Y[(i,j)]*float(CATS_marker[j]) for j in range(number_lp)) <= float(lim)

        progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Solving PuLP linear programming problem...", autocommit=True)

        output = prob.solve()
        state = pulp.LpStatus[output]

        if state == 'Optimal':
            record.outcome = MatchingAttempt.OUTCOME_OPTIMAL
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
