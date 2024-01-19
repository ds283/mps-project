#
# Created by David Seery on 19/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from .utils import get_pclass_config_list
from ..utils import get_current_year


def get_schedule_message_data(configs=None):
    if configs is None:
        configs = get_pclass_config_list()

    current_year = get_current_year()

    messages = []
    error_events = set()
    error_schedules = set()

    # loop through all active project classes
    for config in configs:
        # ignore messages from schedules deployed in previous years that have just not yet rolled over
        if config.year == current_year:
            for period in config.periods:
                if period.has_deployed_schedule:
                    schedule = period.deployed_schedule

                    if schedule.owner.is_feedback_open:
                        if schedule.owner.has_errors:
                            if schedule.event_name not in error_events:
                                messages.append(
                                    (
                                        "error",
                                        'Event "{event}" and deployed schedule "{name}" for project class '
                                        '"{pclass}" contain validation errors. Please attend to these as soon '
                                        "as possible.".format(name=schedule.name, event=schedule.event_name, pclass=config.project_class.name),
                                    )
                                )
                                error_events.add(schedule.event_name)

                        elif schedule.has_errors:
                            if schedule.name not in error_schedules:
                                messages.append(
                                    (
                                        "error",
                                        'Deployed schedule "{name}" for event "{event}" and project class "{pclass}" '
                                        "contains validation errors. Please attend to these as soon as "
                                        "possible.".format(name=schedule.name, event=schedule.event_name, pclass=config.project_class.name),
                                    )
                                )
                                error_schedules.add(schedule.name)

                        elif schedule.has_warnings:
                            if schedule.name not in error_schedules:
                                messages.append(
                                    (
                                        "warning",
                                        'Deployed schedule "{name}" for event "{event}" and project class '
                                        '"{pclass}" contains validation'
                                        " warnings.".format(name=schedule.name, event=schedule.event_name, pclass=config.project_class.name),
                                    )
                                )
                                error_schedules.add(schedule.name)

    return {"messages": messages}


def get_assessment_data(configs=None):
    if configs is None:
        configs = get_pclass_config_list()

    presentation_assessments = False

    # loop through all active project classes
    for config in configs:
        if config.uses_presentations:
            presentation_assessments = True

    return {"has_assessments": presentation_assessments}
