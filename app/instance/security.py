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

from bleach import clean
from flask_security import uia_email_mapper


def _uia_username_mapper(identity):
    # we allow pretty much anything - but we bleach it.
    return clean(identity, strip=True)

# Flask-Security(-Too) features

SECURITY_PASSWORD_SALT = os.environ.get('FLASK_SECURITY_PASSWORD_SALT')

SECURITY_CONFIRMABLE = True
SECURITY_RECOVERABLE = True
SECURITY_TRACKABLE = True
SECURITY_CHANGEABLE = True
SECURITY_REGISTERABLE = False

SECURITY_PASSWORD_LENGTH_MIN = 8
SECURITY_PASSWORD_COMPLEXITY_CHECKER = 'zxcvbn'
SECURITY_PASSWORD_CHECK_BREACHED = True
SECURITY_PASSWORD_BREACHED_COUNT = 1

# tokens expire after 3 * 60 * 60 = 10,800 seconds = 3 hours
SECURITY_TOKEN_MAX_AGE = 10800

# disable passwordless login
SECURITY_PASSWORDLESS = False

# disable HTML emails
SECURITY_EMAIL_HTML = False

SECURITY_USER_IDENTITY_ATTRIBUTES = [{"email": {"mapper": uia_email_mapper, "case_insensitive": True}},
                                     {"username'": {"mapper": _uia_username_mapper}}]

SECURITY_UNAUTHORIZED_VIEW = "home.homepage"
