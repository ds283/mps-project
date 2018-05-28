#
# Created by David Seery on 28/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from .models import MainConfig


def get_main_config():

    return MainConfig.query.order_by(MainConfig.year.desc()).first()


def get_current_year():

    return get_main_config().year
