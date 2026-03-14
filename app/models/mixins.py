#
# Created by David Seery on 09/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


class WeekdaysMixin:
    # our numbering convention for weekdays is datetime.isoweekday(), with Monday=1, Sunday=7
    WEEKDAY_MONDAY = 1
    WEEKDAY_TUESDAY = 2
    WEEKDAY_WEDNESDAY = 3
    WEEKDAY_THURSDAY = 4
    WEEKDAY_FRIDAY = 5
    WEEKDAY_SATURDAY = 6
    WEEKDAY_SUNDAY = 7

    working_days_choices = [
        (WEEKDAY_MONDAY, "Monday"),
        (WEEKDAY_TUESDAY, "Tuesday"),
        (WEEKDAY_WEDNESDAY, "Wednesday"),
        (WEEKDAY_THURSDAY, "Thursday"),
        (WEEKDAY_FRIDAY, "Friday"),
    ]

    weekdays_choices = working_days_choices + [
        (WEEKDAY_SATURDAY, "Saturday"),
        (WEEKDAY_SUNDAY, "Sunday"),
    ]

    _weekdays_string = {
        WEEKDAY_MONDAY: "Monday",
        WEEKDAY_TUESDAY: "Tuesday",
        WEEKDAY_WEDNESDAY: "Wednesday",
        WEEKDAY_THURSDAY: "Thursday",
        WEEKDAY_FRIDAY: "Friday",
        WEEKDAY_SATURDAY: "Saturday",
        WEEKDAY_SUNDAY: "Sunday",
    }
