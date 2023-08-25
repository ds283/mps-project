#
# Created by David Seery on 24/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os
from datetime import timedelta

# Flask-Sessionstore

SESSION_MONGO_URL = os.environ.get('SESSION_MONGO_URL')

SESSION_TYPE = 'mongodb'
SESSION_PERMANENT = True
PERMANENT_SESSION_LIFETIME = timedelta(days=7)

SESSION_MONGODB_DB = 'flask_sessionstore'
SESSION_MONGODB_COLLECT = 'sessions'
SESSION_KEY_PREFIX = 'session:'
