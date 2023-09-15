#
# Created by David Seery on 2018-09-19.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError
from waitress import serve

from app import create_app, db


def execute_query(app, query):
    try:
        result = db.session.execute(text(query))
    except SQLAlchemyError as e:
        app.logger.info('** encountered exception while emplacing SQL line')
        app.logger.info(f'     {query}')
        app.logger.exception("SQLAlchemyError exception", exc_info=e)


def get_current_datetime_str():
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    return now_str


def execute_scripts(app, script, now_str):
    with open(script, 'r') as file:
        while line := file.readline():
            line_replace = line.replace('$$TIMESTAMP', now_str)
            execute_query(app, line_replace)


def populate_table(app, script):
    now_str = get_current_datetime_str()

    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
    execute_scripts(app, script, now_str)
    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))

    db.session.commit()


def check_table(app, inspector, table_data):
    name = table_data['table']
    if not inspector.has_table(name):
        app.logger.error(f'!! FATAL: database is missing the "{name}" table and is not ready. '
                         f'Check that the Alembic migration script has run correctly.')
        exit()

    out = db.session.execute(text(f'SELECT COUNT(*) FROM {name};')).first()
    count = out[0]

    if count == 0:
        app.logger.info(f'** table "{name}" is empty, beginning to auto-populate')
        populate_table(app, table['script'])


app = create_app()

with app.app_context():
    engine = db.engine
    inspector = inspect(engine)

    tables = [
        {'table': 'asset_licenses',
         'script': 'basic_database/asset_licenses.sql'},
        {'table': 'celery_crontabs',
         'script': 'basic_database/celery_crontabs.sql'},
        {'table': 'celery_intervals',
         'script': 'basic_database/celery_intervals.sql'},
        {'table': 'celery_schedules',
         'script': 'basic_database/celery_schedules.sql'},
        {'table': 'main_config',
         'script': 'basic_database/main_config.sql'},
        {'table': 'roles',
         'script': 'basic_database/roles.sql'},
        {'table': 'users',
         'script': 'basic_database/users.sql'},
        {'table': 'faculty_data',
         'script': 'basic_database/faculty_data.sql'},
        {'table': 'roles_users',
         'script': 'basic_database/roles_users.sql'}
    ]

    for table in tables:
        check_table(app, inspector, table)


serve(app, port=5000)
