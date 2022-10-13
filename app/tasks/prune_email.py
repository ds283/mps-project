#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app

from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import EmailLog

from datetime import datetime, timedelta


def register_prune_email(celery):

    @celery.task(bind=True)
    def prune_email_log(self, duration=52, interval='weeks'):
        self.update_state(state='STARTED')

        # get current date
        now = datetime.now()

        # construct a timedelta object corresponding to the specified duration
        delta = timedelta(**{interval: duration})

        # find the cutoff date; emails older than this should be pruned
        limit = now - delta

        try:
            db.session.query(EmailLog).filter(EmailLog.send_date < limit).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception in prune_email_log()", exc_info=e)
            raise self.retry()

        self.update_state(state='FINISHED')


    @celery.task(bind=True)
    def delete_all_email(self):
        self.update_state(state='STARTED')

        try:
            db.session.query(EmailLog).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception in delete_all_email()", exc_info=e)
            raise self.retry()

        self.update_state(state='FINISHED')
