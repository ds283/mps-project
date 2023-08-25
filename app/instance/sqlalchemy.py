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

# read database URI from DATABASE_URL environment variable
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

SQLACHEMY_AES_KEY = os.environ.get('SQLALCHEMY_AES_KEY')

SQLALCHEMY_TRACK_MODIFICATIONS = False  # suppress notifications on database changes
