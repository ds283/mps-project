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
    pass

def readiness():
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        raise HealthError("Can't connect to the SQL database: {what}".format(what=e))
