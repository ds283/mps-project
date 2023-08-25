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

MAIL_SERVER = os.environ.get('MAIL_SERVER')
MAIL_PORT = os.environ.get('MAIL_PORT')
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS')
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
MAIL_DEFAULT_SENDER = 'Project Management Portal <mps-projects@sussex.ac.uk>'
MAIL_REPLY_TO = 'do-not-reply@sussex.ac.uk'
SECURITY_EMAIL_SENDER = 'Project Management Portal <mps-projects@sussex.ac.uk>'

ADMIN_EMAIL = [os.environ.get('MAIL_ADMIN_EMAIL')]
