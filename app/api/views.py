#
# Created by David Seery on 15/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from flask import current_app, jsonify
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    SupervisionEvent,
)
from . import api


@api.route(
    "/set_event_attendance/<int:event_id>/<int:owner_id>/<int:record_id>/<int:submitter_id>/<int:value>"
)
def set_event_attendance(event_id, owner_id, record_id, submitter_id, value):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)

    # check that the other supplied values are valid
    # TODO: would prefer to secure this endpoint with an API key and possibly a
    #  security token, but for now we will accept
    record: SubmissionRecord = event.sub_record
    if record.id != record_id:
        return jsonify({})

    owner: SubmissionRole = event.owner
    if owner.id != owner_id:
        return jsonify({})

    submitter: SubmittingStudent = record.owner
    if submitter.id != submitter_id:
        return jsonify({})

    if not SupervisionEvent.attendance_valid(value):
        return jsonify({"state": "failure", "msg": "invalid attendance value"})

    try:
        event.attendance = value
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"state": "failure", "msg": "database error was detected"})

    return jsonify({"state": "success"})
