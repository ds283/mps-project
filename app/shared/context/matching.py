#
# Created by David Seery on 19/01/2024$.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from .rollover import get_rollover_data
from .utils import get_pclass_config_list, get_pclass_list
from ..sqlalchemy import get_count
from ...database import db
from ...models import ProjectClassConfig, MatchingAttempt


def get_matching_data(configs=None):
    if configs is None:
        configs = get_pclass_config_list()

    matching_ready = False

    # loop through all active project classes
    for config in configs:
        if not config.project_class.publish:
            continue

        if config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
            matching_ready = True

    return {"matching_ready": matching_ready}


def get_ready_to_match_data():
    pcs = get_pclass_list()
    configs = get_pclass_config_list(pcs=pcs)

    rollover_data = get_rollover_data(configs=configs)
    matching_data = get_matching_data(configs=configs)

    rollover_data.update(matching_data)

    return rollover_data


def get_matching_dashboard_data(year):
    matches = get_count(db.session.query(MatchingAttempt).filter_by(year=year))
    return matches
