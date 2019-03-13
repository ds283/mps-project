#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from app import create_app
from scout_apm.api import Config
from scout_apm.celery import install

app, celery = create_app()
app.app_context().push()

Config.set(key=app.config['SCOUT_KEY'],
           name=app.config['SCOUT_NAME'],
           monitor=app.config['SCOUT_MONITOR'])
install()
