#
# Created by David Seery on 2019-03-24.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify

from ..limiter import limiter

from . import alb

@alb.route('/health_check')
@limiter.exempt
def health_check():
    response = jsonify(success=True)
    response.status_code = 200

    return response
