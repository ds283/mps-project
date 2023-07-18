#
# Created by ds283 on 18/07/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_healthz import HealthError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..database import db


def liveness():
    """
    Check if the program is alive.
    Currently, does not perform a check, needs implementation.
    """
    pass

def readiness():
    """
    Check if the program can connect to a SQL database.
    If it can't, raise a HealthError.
    """
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        raise HealthError(f"Can't connect to the SQL database: {e}")
