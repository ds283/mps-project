#
# Created by David Seery on 19/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from collections import defaultdict

from ...database import db
from ...models import ScheduleAttempt, ScheduleSlot, SubmissionRecord, SubmissionRole
from ..utils import get_current_year
from .utils import get_pclass_config_list


def get_schedule_message_data(configs=None):
    if configs is None:
        configs = get_pclass_config_list()

    current_year = get_current_year()

    messages = []
    error_events = set()
    error_schedules = set()

    # collect (config, period) pairs for current-year configs
    current_year_pairs = [
        (config, period)
        for config in configs
        if config.year == current_year
        for period in config.periods
    ]

    if current_year_pairs:
        period_ids = [period.id for _, period in current_year_pairs]

        # single query: find all distinct (period_id, ScheduleAttempt) pairs referenced by
        # ROLE_PRESENTATION_ASSESSOR SubmissionRoles belonging to these periods
        rows = (
            db.session.query(SubmissionRecord.period_id, ScheduleAttempt)
            .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
            .join(ScheduleSlot, ScheduleSlot.id == SubmissionRole.schedule_slot_id)
            .join(ScheduleAttempt, ScheduleAttempt.id == ScheduleSlot.owner_id)
            .filter(
                SubmissionRecord.period_id.in_(period_ids),
                SubmissionRecord.retired.is_(False),
                SubmissionRole.role == SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
            )
            .distinct()
            .all()
        )

        # build dict: period_id -> {schedule_id: ScheduleAttempt} (keyed by id to avoid duplicates)
        period_schedules: dict[int, dict[int, ScheduleAttempt]] = defaultdict(dict)
        for period_id, schedule in rows:
            period_schedules[period_id][schedule.id] = schedule

        # loop through all active project classes
        for config, period in current_year_pairs:
            for schedule in period_schedules.get(period.id, {}).values():
                if not schedule.owner.is_closed:
                    if schedule.owner.has_errors:
                        if schedule.event_name not in error_events:
                            messages.append(
                                (
                                    "error",
                                    'Event "{event}" and deployed schedule "{name}" for project class '
                                    '"{pclass}" contain validation errors. Please attend to these as soon '
                                    "as possible.".format(
                                        name=schedule.name,
                                        event=schedule.event_name,
                                        pclass=config.project_class.name,
                                    ),
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
                                    "possible.".format(
                                        name=schedule.name,
                                        event=schedule.event_name,
                                        pclass=config.project_class.name,
                                    ),
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
                                    " warnings.".format(
                                        name=schedule.name,
                                        event=schedule.event_name,
                                        pclass=config.project_class.name,
                                    ),
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
