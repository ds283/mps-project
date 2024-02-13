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

# Flask-Caching

CACHE_TYPE = 'RedisCache'
CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL')

# default timeout = 86400 seconds = 24 hours
CACHE_DEFAULT_TIMEOUT = 86400
