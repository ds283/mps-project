#
# Created by David Seery on 2019-03-26.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from ..database import db
from ..models import ConfirmRequest, LiveProject

from sqlalchemy.exc import SQLAlchemyError


def register_selecting_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def remove_new(self, config_id, faculty_id):
        if isinstance(config_id, str):
            config_id = int(config_id)

        try:
            lps = db.session.query(LiveProject) \
                .filter(LiveProject.config_id == config_id,
                        LiveProject.owner_id == faculty_id).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        for lp in lps:
            unseen_confirmations = lp.confirmation_requests \
                .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED,
                        ConfirmRequest.viewed != True).all()

            for confirm in unseen_confirmations:
                confirm.viewed = True

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
