#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import Blueprint

convenor = Blueprint("convenor", __name__)

from . import (
    dashboard,
    documents,
    email_templates,
    journal,
    lifecycle,
    markingevent,
    marking_feedback,
    projects,
    resources,
    selector_details,
    selectors,
    student_tasks,
    submitters,
)
