#
# Created by David Seery on 2018-12-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User


def register_utility_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def email_notification(self, sent_data, user_id, message, priority):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not load User record from database')
            raise Ignore

        if not isinstance(sent_data, list):
            sent_data = [sent_data]

        num_sent = sum([n for n in sent_data if n is not None])
        plural = 's'
        if num_sent == 1:
            plural = ''

        user.post_message(message.format(n=num_sent, pl=plural), priority, autocommit=True)
