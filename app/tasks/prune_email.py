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

        now = datetime.now()
        delta = timedelta(**{interval: duration})
        limit = now - delta

        try:
            EmailLog.query.filter(EmailLog.send_date < limit).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True)
    def delete_all_email(self):

        try:
            EmailLog.query.delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
