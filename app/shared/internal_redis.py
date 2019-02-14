#
# Created by David Seery on 2019-02-14.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import g, current_app
import redis

def get_redis():
    if 'db' not in g:
        g.db = redis.Redis.from_url(url=current_app.config['CACHE_REDIS_URL'])
    return g.db
