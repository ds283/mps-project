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

from sqlalchemy import text, inspect
from waitress import serve

from app import create_app
from app.database import db
from initdb import initial_populate_database, populate_CATS_limits


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


app = create_app()

with app.app_context():
    engine = db.engine
    inspector = inspect(engine)

    # first inspect the main table; if this does not exist or is empty
    # then we assume that they database should be repopulated
    # (in general the table will exist but may be empty, because Flask-Migrate will already have been run
    # by the boot script)
    if not has_table(inspector, "main_config"):
        # commit session to release any table locks; otherwise, if we are restoring from a mysqldump
        # dump file which issues DROP TABLE statements, these will block against the table lock
        db.session.commit()
        initial_populate_database(app, inspector)

    # import initdb configuration file
    initdb_module = import_module("app.initdb.initdb")
    if hasattr(initdb_module, "INITDB_CATS_LIMITS_FILE") and initdb_module.INITDB_CATS_LIMITS_FILE is not None:
        db.session.commit()
        populate_CATS_limits(app, inspector, initdb_module)

serve(app, port=5000)
