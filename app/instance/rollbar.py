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

# rollbar configuration
ROLLBAR_TOKEN = os.environ.get('ROLLBAR_TOKEN')
ROLLBAR_ENV = os.environ.get('ROLLBAR_ENV')
