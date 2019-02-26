#
# Created by David Seery on 2019-02-24.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, jsonify, session
from flask_security import current_user, roles_required, roles_accepted

from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from . import project_approver

from ..database import db
from ..models import ProjectDescription

from ..shared.utils import get_current_year, build_project_approval_queues
from ..shared.conversions import is_integer

import app.ajax as ajax

from datetime import datetime


@project_approver.route('/validate')
@roles_required('project_approver')
def validate():
    """
    Validate project descriptions
    :return:
    """
    url = request.args.get('url', None)
    text = request.args.get('text', None)

    if url is None or text is None:
        url = request.referrer
        text = 'approvals dashboard'

    return render_template('project_approver/validate.html', url=url, text=text)


@project_approver.route('/validate_ajax')
@roles_required('project_approver')
def validate_ajax():
    url = request.args.get('url', None)
    text = request.args.get('text', None)

    queues = build_project_approval_queues()
    queued = queues['queued']

    return ajax.project_approver.validate_data(queued, url=url, text=text)


@project_approver.route('/approve/<int:id>')
@roles_required('project_approver')
def approve(id):
    record = ProjectDescription.query.get_or_404(id)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_VALIDATED
    record.validator_id = current_user.id
    record.validated_timestamp = datetime.now()
    db.session.commit()

    return redirect(url_for('project_approver.validate', url=url, text=text))


@project_approver.route('/reject/<int:id>')
@roles_required('project_approver')
def reject(id):
    record = ProjectDescription.query.get_or_404(id)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_REJECTED
    record.validator_id = current_user.id
    record.validated_timestamp = datetime.now()
    db.session.commit()

    return redirect(url_for('project_approver.validate', url=url, text=text))
