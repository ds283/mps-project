#
# Created by David Seery on 15/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, jsonify, url_for
from sqlalchemy.exc import SQLAlchemyError

from .. import render_template_context
from ..database import db
from ..models import (
    StudentData,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    SupervisionEvent,
    User,
)
from . import api


@api.route(
    "/set_event_attendance/<int:event_id>/<int:owner_id>/<int:record_id>/<int:submitter_id>/<int:value>"
)
def set_event_attendance(event_id, owner_id, record_id, submitter_id, value):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)
    record: SubmissionRecord = event.sub_record
    owner: SubmissionRole = event.owner
    submitter: SubmittingStudent = record.owner
    sd: StudentData = submitter.student
    suser: User = sd.user

    homepage_url = url_for("home.homepage")
    project_page_url = url_for("projecthub.hub", subid=record.id)
    event_page_url = url_for(
        "projecthub.event_details",
        event_id=event_id,
        url=project_page_url,
        text=f"project page for {suser.name}",
    )

    # check that the other supplied values are valid
    # TODO: would prefer to secure this endpoint with an API key and possibly a
    #  security token, but for now we will accept just checking that this combination
    #  is valid
    if record.id != record_id:
        return render_template_context(
            "api/attendance/error.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    if owner.id != owner_id:
        return render_template_context(
            "api/attendance/error.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    if submitter.id != submitter_id:
        return render_template_context(
            "api/attendance/error.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    if not SupervisionEvent.attendance_valid(value):
        return render_template_context(
            "api/attendance/error.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    try:
        event.attendance = value
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return render_template_context(
            "api/attendance/error.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    return render_template_context(
        "api/attendance/thankyou.html",
        homepage_url=homepage_url,
        project_page_url=project_page_url,
        event_page_url=event_page_url,
    )


@api.route("/mute_event/<int:event_id>/<int:owner_id>/<int:record_id>")
def mute_event(event_id, owner_id, record_id):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)
    record: SubmissionRecord = event.sub_record
    owner: SubmissionRole = event.owner
    submitter: SubmittingStudent = record.owner
    sd: StudentData = submitter.student
    suser: User = sd.user

    homepage_url = url_for("home.homepage")
    project_page_url = url_for("projecthub.hub", subid=record.id)
    event_page_url = url_for(
        "projecthub.event_details",
        event_id=event_id,
        url=project_page_url,
        text=f"project page for {suser.name}",
    )

    # check that the other supplied values are valid
    # TODO: would prefer to secure this endpoint with an API key and possibly a
    #  security token, but for now we will accept just checking that this combination
    #  is valid
    if record.id != record_id:
        return render_template_context(
            "api/mute/error_event.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    if owner.id != owner_id:
        return render_template_context(
            "api/mute/error_event.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    try:
        event.mute = True
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return render_template_context(
            "api/mute/error_event.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
            event_page_url=event_page_url,
        )

    return render_template_context(
        "api/mute/thankyou_event.html",
        homepage_url=homepage_url,
        project_page_url=project_page_url,
        event_page_url=event_page_url,
    )


@api.route("/mute_role/<int:role_id>/<int:record_id>")
def mute_role(role_id, record_id):
    role: SubmissionRole = SubmissionRole.query.get_or_404(role_id)
    record: SubmissionRecord = role.submission
    submitter: SubmittingStudent = record.owner
    sd: StudentData = submitter.student

    homepage_url = url_for("home.homepage")
    project_page_url = url_for("projecthub.hub", subid=record.id)

    # check that the other supplied values are valid
    # TODO: would prefer to secure this endpoint with an API key and possibly a
    #  security token, but for now we will accept just checking that this combination
    #  is valid
    if record.id != record_id:
        return render_template_context(
            "api/mute/error_role.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
        )

    try:
        role.mute = True
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return render_template_context(
            "api/mute/error_role.html",
            homepage_url=homepage_url,
            project_page_url=project_page_url,
        )

    return render_template_context(
        "api/mute/thankyou_role.html",
        homepage_url=homepage_url,
        project_page_url=project_page_url,
    )
