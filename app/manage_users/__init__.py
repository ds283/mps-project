#
# Created by David Seery on 2019-04-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import Blueprint

manage_users = Blueprint("manage_users", __name__)

from . import views
