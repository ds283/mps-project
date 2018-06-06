#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from sqlalchemy.exc import SQLAlchemyError

from ..models import db, EmailLog

from datetime import datetime, timedelta


def register_prune_email(celery):

    @celery.task()
    def prune_email_log(duration=52, interval='weeks'):

        emails = db.session.query(EmailLog).all()

        for item in emails:
            prune_email.apply_async(args=(duration, interval, item.id))


    @celery.task(bind=True)
    def prune_email(self, interval, duration, id):

        now = datetime.now()
        delta = timedelta(**{interval: duration})

        try:
            record = EmailLog.query.filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is not None:

            age = now - record.send_date

            if age > delta:
                db.session.delete(record)
                db.commit()
