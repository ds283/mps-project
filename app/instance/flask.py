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

# needed for Celery tasks to build URLs outside a resource context
SERVER_NAME = os.environ.get('SERVER_NAME') or None

# set maximum upload size to be 96Mb
MAX_CONTENT_LENGTH = 96 * 1024 * 1024

# Flask secret key (used to encrypt client-side cookies)
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
