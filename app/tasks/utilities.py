#
# Created by David Seery on 2018-12-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User


def register_utility_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def email_notification(self, results, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not load User record from database')
            raise Ignore

        sent_emails = sum(results)

        user.post_message('{n} emails have been sent.'.format(n=sent_emails), 'info', autocommit=True)
