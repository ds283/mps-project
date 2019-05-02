#
# Created by David Seery on 2018-09-17.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


# IP whitelist
@limiter.request_filter
def ip_whitelist():
    # whitelist internal Sussex IPs
    return request.remote_addr.startswith('139.184.')
