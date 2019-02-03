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

def do_precompute(user):
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

    uc = celery.tasks['app.tasks.precompute.user_corrections']
    uc.apply_async(args=(user.id,))

    user.last_precompute = datetime.now()
    db.session.commit()
