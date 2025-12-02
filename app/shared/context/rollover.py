#
# Created by David Seery on 19/01/2024$.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from .utils import get_pclass_config_list
from ..utils import get_current_year


def get_rollover_data(configs=None, current_year=None):
    if configs is None:
        configs = get_pclass_config_list()

    if current_year is None:
        current_year = get_current_year()

    rollover_ready = False
    rollover_in_progress = False

    # are there any pclasses that have been published?
    # if not, we are always in a rollover state
    some_pclass_published = False

    # loop through all active project classes to test for rollover status
    for config in configs:
        if config.project_class.publish:
            # unpublished classes do not prevent rollover
            some_pclass_published = True

            # if MainConfig year has already been advanced, then we shouldn't offer
            # matching or rollover options on the dashboard
            if config.year < current_year:
                rollover_in_progress = True

            # we can initiate rollover if just one project class is ready
            # this doesn't affect the other types
            # so the logic we want here is rollover_ready = rollover_ready | status for this class
            if config.rollover_ready:
                rollover_ready = True

    # if no published classes at all, allow rollover
    if not rollover_ready and not some_pclass_published:
        rollover_ready = True

    return {"rollover_ready": rollover_ready, "rollover_in_progress": rollover_in_progress}
