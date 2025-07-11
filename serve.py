#
# Created by David Seery on 2018-09-19.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from importlib import import_module

import flask_monitoringdashboard as dashboard
import gunicorn.app.base
from flask_security import current_user
from sqlalchemy import text, inspect

import gunicorn_config
from app import create_app
from app.database import db
from initdb import initial_populate_database, populate_CATS_limits, import_supervisor_data, import_examiner_data


def has_table(inspector, table_name):
    # if table does not exist, then fail
    if not inspector.has_table(table_name):
        return False

    # if table exists, but has no entries, then we should also fail
    out = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name};")).first()
    count = out[0]

    if count == 0:
        return False

    return True


def get_user_id():
    if current_user is not None:
        return current_user.id

    return None


app = create_app()
dashboard.config.init_from(envvar="DASHBOARD_CONFIG_FILE")
dashboard.config.group_by = get_user_id
dashboard.bind(app)

with app.app_context():
    engine = db.engine
    inspector = inspect(engine)

    # first inspect the main table; if this does not exist or is empty
    # then we assume that the database should be repopulated
    # (in general, the table will exist but may be empty, because Flask-Migrate will already have been run
    # by the boot script)
    if not has_table(inspector, "main_config"):
        # commit session to release any table locks; otherwise, if we are restoring from a mysqldump
        # dump file which issues DROP TABLE statements, these will block against the table lock
        db.session.commit()
        initial_populate_database(app, inspector)

    # import initdb configuration files
    initdb_module = import_module("app.initdb.initdb")

    # if specified, use an uploaded CATS limit file to overwrite existing limits
    if hasattr(initdb_module, "INITDB_CATS_LIMITS_FILE") and initdb_module.INITDB_CATS_LIMITS_FILE is not None:
        db.session.commit()
        populate_CATS_limits(app, initdb_module)

    # if specified, import supervisor and examiner data (usually from Qualtrics)
    if hasattr(initdb_module, "INITDB_SUPERVISOR_IMPORT") and initdb_module.INITDB_SUPERVISOR_IMPORT is not None:
        db.session.commit()
        import_supervisor_data(app, initdb_module)

    if hasattr(initdb_module, "INITDB_EXAMINER_IMPORT") and initdb_module.INITDB_EXAMINER_IMPORT is not None:
        db.session.commit()
        import_examiner_data(app, initdb_module)


class StandaloneApplication(gunicorn.app.base.BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items() if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


if __name__ == "__main__":
    StandaloneApplication(app, gunicorn_config.__dict__).run()
