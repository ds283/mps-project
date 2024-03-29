#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

DEBUG = False

# Flask-Limiter
# RATELIMIT_STORAGE_URI is set in instance/ratelimit.py
RATELIMIT_DEFAULT = "5000/hour;300/minute"

# get SQLAlchemy to record metadata about query performance, so we can identify very slow queries
SQLALCHEMY_RECORD_QUERIES = True

# slow database query threshold (in seconds)
# queries that take longer than this are logged
DATABASE_QUERY_TIMEOUT = 0.5
