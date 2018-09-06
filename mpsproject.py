#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from app import create_app
from app.models import db, TaskRecord, Notification, MatchingAttempt
from sqlalchemy.exc import SQLAlchemyError

app, celery = create_app()

with app.app_context():

    # drop all transient task records and notifications, which will no longer have any meaning
    TaskRecord.query.delete()
    Notification.query.delete()

    # any in-progress matching attempts will have been aborted when the app crashed or exited
    try:
        in_progress_matching = MatchingAttempt.query.filter_by(finished=False)
        for item in in_progress_matching:
            item.finished = True
            item.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED
    except SQLAlchemyError:
        pass

    db.session.commit()

# pass control to application entry point if we are the controlling script
if __name__ == '__main__':
    app.run()
