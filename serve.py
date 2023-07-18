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


def execute_query(query):
    try:
        result = db.session.execute(text(query))
    except SQLAlchemyError as e:
        print('** Encountered exception while emplacing SQL line')
        print(f'     {query}')
        print(e)


def get_current_datetime_str():
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    return now_str


def execute_scripts(scripts, now_str):
    for script in scripts:
        with open(script, 'r') as file:
            while line := file.readline():
                line_replace = line.replace('$$TIMESTAMP', now_str)
                execute_query(line_replace)


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

    now_str = get_current_datetime_str()

    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
    execute_scripts(scripts, now_str)
    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))

    db.session.commit()

    print('== FINISHED POPULATE_DATABASE()')


app = create_app()

populate = os.getenv("MPSPROJECT_POPULATE_DATABASE")
if populate is not None and populate == "1":
    with app.app_context():
        populate_database()


serve(app, port=5000)
