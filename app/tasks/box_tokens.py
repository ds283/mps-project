#
# Created by David Seery on 06/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import and_, or_

from ..database import db
from ..models import User
from ..shared.box_api import _do_token_refresh

PROACTIVE_REFRESH_THRESHOLD = timedelta(days=45)
ACTIVE_WITHIN = timedelta(days=7)
LAPSE_THRESHOLD = timedelta(days=55)


def register_box_tokens_tasks(celery):

    @celery.task(bind=True, name="app.tasks.box_tokens.maintain_box_tokens")
    def maintain_box_tokens(self):
        now = datetime.now()

        # Query 1: proactive refresh for active users with stale tokens
        proactive_users = (
            db.session.query(User)
            .filter(
                User.box_token_valid.is_(True),
                User.box_updated_at < now - PROACTIVE_REFRESH_THRESHOLD,
                User.last_active > now - ACTIVE_WITHIN,
            )
            .all()
        )

        n_ok = 0
        n_err = 0
        for user in proactive_users:
            try:
                _do_token_refresh(user)
                n_ok += 1
            except Exception as exc:
                current_app.logger.error("Box token proactive refresh failed for user id=%s: %s", user.id, exc)
                n_err += 1

        current_app.logger.info("Box token proactive refresh: %d refreshed, %d errors", n_ok, n_err)

        # Query 2: lapse warning for inactive users near expiry
        lapse_users = (
            db.session.query(User)
            .filter(
                User.box_token_valid.is_(True),
                User.box_updated_at < now - LAPSE_THRESHOLD,
                or_(
                    User.last_active.is_(None),
                    User.last_active < now - ACTIVE_WITHIN,
                ),
            )
            .all()
        )

        for user in lapse_users:
            user.post_message(
                "Your Box connection will expire soon. Please visit your account settings to re-authenticate.",
                "warning",
                autocommit=True,
            )

    return (maintain_box_tokens,)
