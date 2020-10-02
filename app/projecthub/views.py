#
# Created by David Seery on 02/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from . import projecthub

from flask import render_template, redirect, url_for, flash, request
from flask_security import current_user, roles_accepted, roles_required

from ..models import SubmissionRecord

from .utils import validate_project_hub
from ..shared.utils import redirect_url


@projecthub.route('/hub/<int:subid>')
@roles_accepted('admin', 'root', 'faculty', 'supervisor', 'student', 'office', 'moderator', 'external_examiner', 'exam_board')
def hub(subid):
    # subid labels a SubmissionRecord
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(subid)

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())