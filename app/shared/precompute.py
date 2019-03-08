#
# Created by David Seery on 2019-02-03.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from ..database import db
from ..shared.internal_redis import get_redis

from celery import group

from datetime import datetime


def precompute_at_login(user):
    celery = current_app.extensions['celery']

    if user.has_role('student'):
        # students need to cache the list of available LiveProjects
        lp = celery.tasks['app.tasks.precompute.student_liveprojects']
        lp.apply_async(args=(user.id,))

    if user.has_role('admin') or user.has_role('root'):
        # admin or root users are able to manage users, so we need to cache
        user_accounts = celery.tasks['app.tasks.precompute.user_account_data']
        faculty_accounts = celery.tasks['app.tasks.precompute.user_faculty_data']
        student_accounts = celery.tasks['app.tasks.precompute.user_student_data']

        # these users can also have edits made to user accounts bounced back to them
        user_corrections = celery.tasks['app.tasks.precompute.user_corrections']

        task = group(user_accounts.si(user.id), faculty_accounts.si(user.id), student_accounts.si(user.id),
                     user_corrections.si(user.id))
        task.apply_async()

    if user.has_role('faculty'):
        # Faculty need to precompute the list of projects for which they are in the assessor pool.
        # These can be tagged with 'New comments' labels on a user-by-user basis.
        # However, the 'new comments' labels are injected by substitution *after* caching,
        # so we don't need to run these precompute jobs on a per-user basis
        # TODO: compute faculty project libraries? they tend to be quite small ...
        precompute_faculty_projects()

    if user.has_role('project_approver'):
        # users on the project approvals team need to generate table lines for projects in the
        # approvals queue, and projects in the rejected set.
        # Both of these can be tagged with 'New comments' labels on a user-by-user basis.
        # However, the 'new comments' labels are injected by substitution *after* caching,
        # so we don't need to run these precompute jobs on a per-user basis
        precompute_for_project_approver()

    if user.has_role('reports'):
        # 'reports' roles can access workload reports, which do not depend on who is viewing them.
        # we don't cache these on a per-user basis, but rather globally for everyone
        precompute_for_reports()

    if user.has_role('user_approver'):
        # likewise, 'user_approver' roles need tables for all the students to approve, but these are
        # shared between everyone on the user approvals team. So we cache them globally for everyone
        precompute_for_user_approver()

    # reset last precompute time for this user
    user.last_precompute = datetime.now()
    db.session.commit()


def _check_if_compute(db, key):
    # check if key giving last precompute time exists
    if not db.exists(key):
        return True

    # if no key exists, compute = True
    # if a key exists, compute = False and we should check when last event occurred
    last_timestamp = db.get(key)

    # values returned from Redis are often byte strings
    if not isinstance(last_timestamp, float):
        last_timestamp = float(last_timestamp)

    last_dt = datetime.fromtimestamp(last_timestamp)

    delta = datetime.now() - last_dt

    delay = current_app.config.get('PRECOMPUTE_DELAY')
    if delay is None:
        delay = 600

    return delta.seconds > delay


def precompute_for_reports():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_REPORTS'):
        return

    celery = current_app.extensions['celery']

    exc = celery.tasks['app.tasks.precompute.reporting']
    exc.apply_async()

    db.set('PRECOMPUTE_LAST_REPORTS', datetime.now().timestamp())


def precompute_for_user_approver():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_USER_APPROVER'):
        return

    celery = current_app.extensions['celery']

    ua = celery.tasks['app.tasks.precompute.user_approvals']
    ua.apply_async()

    db.set('PRECOMPUTE_LAST_USER_APPROVER', datetime.now().timestamp())


def precompute_faculty_projects():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_FACULTY_PROJECTS'):
        return

    celery = current_app.extensions['celery']

    # only precompute assessor data if we haven't recently computed the same data for reporting purposes
    if _check_if_compute(db, 'PRECOMPUTE_LAST_REPORTS'):
        fac = celery.tasks['app.tasks.precompute.assessor_data']
        fac.apply_async(args=(None,))

    db.set('PRECOMPUTE_LAST_FACULTY_PROJECTS', datetime.now().timestamp())


def precompute_for_project_approver():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_PROJECT_APPROVER'):
        return

    celery = current_app.extensions['celery']

    approvals = celery.tasks['app.tasks.precompute.project_approval']
    rejections = celery.tasks['app.tasks.precompute.project_rejected']

    task = group(approvals.si(None), rejections.si(None))
    task.apply_async()

    db.set('PRECOMPUTE_LAST_PROJECT_APPROVER', datetime.now().timestamp())
