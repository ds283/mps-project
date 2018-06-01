#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from ..models import db, User, EmailLog

from datetime import datetime


def register_send_log_email(celery, mail):

    # set up deferred email sender for Flask-Email; note that Flask-Email's Message object is not
    # JSON-serializable so we have to pickle instead
    @celery.task(serializer='pickle')
    def send_log_mail(msg):

        mail.send(msg)
        log = None

        # store message in email log
        if len(msg.recipients) == 1:
            user = User.query.filter_by(email=msg.recipients[0]).first()
            if user is not None:

                log = EmailLog(user_id=user.id,
                               recipient=None,
                               send_date=datetime.now(),
                               subject=msg.subject,
                               body=msg.body,
                               html=msg.html)

        if log is None:

            log = EmailLog(user_id=None,
                           recipient=', '.join(msg.recipients),
                           send_date=datetime.now(),
                           subject=msg.subject,
                           body=msg.body,
                           html=msg.html)

        db.session.add(log)
        db.session.commit()

    return send_log_mail
