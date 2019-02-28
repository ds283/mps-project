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

from datetime import datetime


def precompute_at_login(user):
    celery = current_app.extensions['celery']

    if user.has_role('student'):
        lp = celery.tasks['app.tasks.precompute.student_liveprojects']
        lp.apply_async(args=(user.id,))

    if user.has_role('admin'):
        users = celery.tasks['app.tasks.precompute.administrator']
        users.apply_async(args=(user.id,))

    if user.has_role('faculty'):
        precompute_for_faculty()

    if user.has_role('exec'):
        precompute_for_exec()

    if user.has_role('project_approver'):
        precompute_for_project_approver()

    if user.has_role('user_approver'):
        precompute_for_user_approver()

    if user.has_role('admin') or user.has_role('root'):
        precompute_user_corrections()

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


def precompute_for_faculty():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_FACULTY'):
        return

    celery = current_app.extensions['celery']

    fac = celery.tasks['app.tasks.precompute.faculty']
    fac.apply_async()

    db.set('PRECOMPUTE_LAST_FACULTY', datetime.now().timestamp())


def precompute_for_exec():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_EXEC'):
        return

    celery = current_app.extensions['celery']

    exc = celery.tasks['app.tasks.precompute.executive']
    exc.apply_async()

    db.set('PRECOMPUTE_LAST_EXEC', datetime.now().timestamp())


def precompute_for_project_approver():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_PROJECT_APPROVER'):
        return

    celery = current_app.extensions['celery']

    pa = celery.tasks['app.tasks.precompute.project_approval']
    pc = celery.tasks['app.tasks.precompute.project_rejected']
    pa.apply_async()
    pc.apply_async()

    db.set('PRECOMPUTE_LAST_PROJECT_APPROVER', datetime.now().timestamp())


def precompute_for_user_approver():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_USER_APPROVER'):
        return

    celery = current_app.extensions['celery']

    ua = celery.tasks['app.tasks.precompute.user_approvals']
    ua.apply_async()

    db.set('PRECOMPUTE_LAST_USER_APPROVER', datetime.now().timestamp())


def precompute_user_corrections():
    db = get_redis()

    if not _check_if_compute(db, 'PRECOMPUTE_LAST_USER_CORRECTIONS'):
        return

    celery = current_app.extensions['celery']

    uc = celery.tasks['app.tasks.precompute.user_corrections']
    uc.apply_async()

    db.set('PRECOMPUTE_LAST_USER_CORRECTIONS', datetime.now().timestamp())
