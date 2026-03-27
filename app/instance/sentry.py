#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

SENTRY_ENDPOINT = os.environ.get("SENTRY_ENDPOINT")
SENTRY_ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT")
SENTRY_TRACE = os.environ.get("SENTRY_TRACE")
