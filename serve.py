#
# Created by David Seery on 2018-09-19.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from waitress import serve

from app import create_app, db


def populate_database():
    print('!! EXECUTING POPULATE_DATABASE()')

    scripts = ['basic_database/asset_licenses.sql',
               'basic_database/celery_crontabs.sql',
               'basic_database/celery_intervals.sql',
               'basic_database/celery_schedules.sql',
               'basic_database/main_config.sql',
               'basic_database/roles.sql',
               'basic_database/users.sql',
               'basic_database/faculty_data.sql',
               'basic_database/roles_users.sql']

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))

    for script in scripts:
        with open(script, 'r') as file:
            while line := file.readline():
                line_replace = line.replace('$$TIMESTAMP', now_str)
                try:
                    result = db.session.execute(text(line_replace))
                except SQLAlchemyError as e:
                    print('** Encountered exception while emplacing SQL line')
                    print('     {line}'.format(line=line_replace))
                    print(e)

    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))

    db.session.commit()

    print('== FINISHED POPULATE_DATABASE()')


app = create_app()

populate = os.getenv("MPSPROJECT_POPULATE_DATABASE")
if populate is not None and populate == "1":
    with app.app_context():
        populate_database()


serve(app, port=5000)
