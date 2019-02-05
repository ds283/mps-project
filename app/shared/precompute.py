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

from datetime import datetime


def precompute_at_login(user):
    precompute_for_user(user)

    if user.has_role('faculty'):
        precompute_for_faculty()

    if user.has_role('exec'):
        precompute_for_exec()


def precompute_for_user(user):
    celery = current_app.extensions['celery']

    if user.has_role('student'):
        lp = celery.tasks['app.tasks.precompute.student_liveprojects']
        lp.apply_async(args=(user.id,))

    if user.has_role('user_approve'):
        ua = celery.tasks['app.tasks.precompute.user_approvals']
        ua.apply_async(args=(user.id,))

    if user.has_role('admin'):
        users = celery.tasks['app.tasks.precompute.administrator']
        users.apply_async(args=(user.id,))

    # don't run eg. 'faculty' or 'exec' role precomputes here, because they are independent of the user
    # if we run them for each user we are doing pointless work

    uc = celery.tasks['app.tasks.precompute.user_corrections']
    uc.apply_async(args=(user.id,))

    user.last_precompute = datetime.now()
    db.session.commit()


def precompute_for_faculty():
    celery = current_app.extensions['celery']

    fac = celery.tasks['app.tasks.precompute.faculty']
    fac.apply_async()


def precompute_for_exec():
    celery = current_app.extensions['celery']

    exc = celery.tasks['app.tasks.precompute.executive']
    exc.apply_async()
