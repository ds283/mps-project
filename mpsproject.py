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
from app.models import db, TaskRecord

app, celery = create_app()

# drop all transient task records
with app.app_context():
    TaskRecord.query.delete()
    db.session.commit()

# pass control to application entry point if we are the controlling script
if __name__ == '__main__':
    app.run()
