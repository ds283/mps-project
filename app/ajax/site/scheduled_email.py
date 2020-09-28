#
# Created by David Seery on 28/09/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string
from typing import List

from ...models import EmailNotification


_name = \
"""
<a href="{{ user.email }}">{{ user.name }}</a>
"""


def scheduled_email(notifications: List[EmailNotification]):
    data = [{'recipient': render_template_string(_name, user=e.owner),
             'timestamp': e.timestamp.strftime("%a %d %b %Y %H:%M:%S"),
             'type': e.event_label,
             'details': str(e),
             'menu': None} for e in notifications]

    return data
