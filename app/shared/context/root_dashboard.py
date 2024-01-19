#
# Created by David Seery on 19/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from flask import current_app

from .assessments import get_schedule_message_data
from .convenor_dashboard import get_capacity_data
from .rollover import get_rollover_data
from .utils import get_pclass_list, get_pclass_config_list
from ..utils import get_current_year


def get_root_dashboard_data():
    current_year = get_current_year()

    pcs = get_pclass_list()
    configs = get_pclass_config_list(pcs=pcs)

    # don't need get_assessment_data since these keys are made available in the global context
    # don't need get_matching_data since these keys are made available in the global context
    rollover_data = get_rollover_data(configs=configs, current_year=current_year)
    message_data = get_schedule_message_data(configs=configs)
    config_data = _get_config_capacity_data(configs=configs)

    session_collection = current_app.session_interface.store
    sessions = session_collection.count_documents({})

    data = {"warning": (config_data["config_warning"] or rollover_data["rollover_ready"]), "current_year": current_year, "number_sessions": sessions}

    data.update(rollover_data)
    data.update(message_data)
    data.update(config_data)

    return data


def _get_config_capacity_data(configs=None):
    if configs is None:
        configs = get_pclass_config_list()

    config_list = []
    config_warning = False

    # loop through all active project classes
    for config in configs:
        # compute capacity data for this project class
        data = get_capacity_data(config.project_class)

        capacity = data["capacity"]
        capacity_bounded = data["capacity_bounded"]

        if capacity < 1.15 * config.number_selectors:
            config_warning = True

        config_list.append({"config": config, "capacity": capacity, "is_bounded": capacity_bounded})

    return {"config_list": config_list, "config_warning": config_warning}
