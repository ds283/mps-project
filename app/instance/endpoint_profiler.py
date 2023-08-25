#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os
from random import random

FLASK_PROFILER = {
    "enabled": True,
    "storage": {
        "engine": "mongodb",
        "MONGO_URL": os.environ.get('PROFILER_MONGO_URL'),
        "DATABASE": os.environ.get('PROFILER_MONGO_DATABASE') or 'flask_profiler',
        "COLLECTION": os.environ.get('PROFILER_MONGO_COLLECTION') or 'measurements'
    },
    "ignore": [
        "^/static/.*"
    ],
    "basicAuth": {
        "enabled": True,
        "username": os.environ.get('PROFILER_USERNAME'),
        "password": os.environ.get('PROFILER_PASSWORD')
    },
    "sampling_function": lambda: True if random() < 0.2 else False
}
