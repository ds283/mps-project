#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

from app import create_app

# get current configuration, or default to production for safety
config_name = os.environ.get('FLASK_CONFIG') or 'production'
app, payload = create_app(config_name)

# pass control to application entry point if we are the controlling script
if __name__ == '__main__':
    app.run()
