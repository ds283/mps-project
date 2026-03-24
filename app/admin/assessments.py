#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date, datetime, timedelta
from typing import List

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    stream_with_context,
    url_for,
)
from flask_security import (
    current_user,
    roles_accepted,
    roles_required,
)
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import Headers
from werkzeug.wrappers import Response

import app.ajax as ajax

from ..database import db
from ..models import (
    AssessorAttendanceData,
    FacultyData,
    PresentationAssessment,
    PresentationSession,
    SubmissionRecord,
    SubmitterAttendanceData,
)
from ..shared.context.global_context import render_template_context
from ..shared.conversions import is_integer
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    get_current_year,
    redirect_url,
)
from ..shared.validators import (
    validate_assessment,
    validate_using_assessment,
)
from ..task_queue import register_task
from . import admin
from .actions import availability_CSV_generator
from .forms import (
    AddPresentationAssessmentFormFactory,
    AddSessionForm,
    AssignmentLimitForm,
    AvailabilityFormFactory,
    EditPresentationAssessmentFormFactory,
    EditSessionForm,
)


@admin.route("/manage_assessments")
@roles_required("root")
def manage_assessments():
    """
    Create the 'manage assessments' view
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    return render_template_context("admin/presentations/manage.html")


@admin.route("/presentation_assessments_ajax")
@roles_required("root")
def presentation_assessments_ajax():
    """
    AJAX endpoint to generate data for populating the 'manage assessments' view
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    current_year = get_current_year()
    assessments = (
        db.session.query(PresentationAssessment).filter_by(year=current_year).all()
    )

    return ajax.admin.presentation_assessments_data(assessments)


@admin.route("/add_assessment", methods=["GET", "POST"])
@roles_required("root")
def add_assessment():
    """
    Add a new named assessment event
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    current_year = get_current_year()
    AddPresentationAssessmentForm = AddPresentationAssessmentFormFactory(current_year)
    form = AddPresentationAssessmentForm(request.form)

    if not hasattr(form, "submission_periods"):
        flash(
            "An internal error occurred. Please contact a system administrator", "error"
        )
        return redirect(redirect_url())

    if form.validate_on_submit():
        data = PresentationAssessment(
            name=form.name.data,
            year=current_year,
            submission_periods=form.submission_periods.data,
            requested_availability=False,
            availability_closed=False,
            availability_deadline=None,
            skip_availability=False,
            availability_skipped_id=None,
            availability_skipped_timestamp=None,
            feedback_open=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        db.session.add(data)
        db.session.commit()

        return redirect(url_for("admin.manage_assessments"))

    return render_template_context(
        "admin/presentations/edit_assessment.html",
        form=form,
        title="Add new presentation assessment event",
    )


@admin.route("/edit_assessment/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_assessment(id):
    """
    Edit an existing named assessment event
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if assessment.requested_availability:
        flash(
            "It is no longer possible to change settings for an assessment once availability requests have been issued.",
            "info",
        )
        return redirect(redirect_url())

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    EditPresentationAssessmentForm = EditPresentationAssessmentFormFactory(
        current_year, assessment
    )
    form = EditPresentationAssessmentForm(obj=assessment)
    form.assessment = assessment

    if form.validate_on_submit():
        assessment.name = form.name.data

        if hasattr(form, "submission_periods"):
            assessment.submission_periods = form.submission_periods.data

        assessment.last_edit_id = current_user.id
        assessment.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for("admin.manage_assessments"))

    return render_template_context(
        "admin/presentations/edit_assessment.html",
        form=form,
        assessment=assessment,
        title="Edit existing presentation assessment event",
    )


@admin.route("/delete_assessment/<int:id>")
@roles_required("root")
def delete_assessment(id):
    """
    Delete an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule and cannot be deleted.'.format(
                name=assessment.name
            ),
            "info",
        )
        return redirect(redirect_url())

    title = "Delete presentation assessment"
    panel_title = "Delete presentation assessment <strong>{name}</strong>".format(
        name=assessment.name
    )

    action_url = url_for("admin.perform_delete_assessment", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to delete the assessment "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=assessment.name)
    )
    submit_label = "Delete assessment"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_delete_assessment/<int:id>")
@roles_required("root")
def perform_delete_assessment(id):
    """
    Delete an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule and cannot be deleted.'.format(
                name=assessment.name
            ),
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", url_for("admin.manage_assessments"))

    try:
        db.session.delete(assessment)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not delete assessment "{assessment.name}" due to a database error. Please contact a system administrator',
            "error",
        )

    return redirect(url)


@admin.route("/close_assessment/<int:id>")
@roles_required("root")
def close_assessment(id):
    """
    Close an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_closed:
        return redirect(redirect_url())

    if not assessment.is_closable:
        flash(
            'Cannot close assessment "{name}" because one or more closing criteria have not been met. Check '
            "that all scheduled sessions are in the past.".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    title = "Close assessment"
    panel_title = "Close assessment <strong>{name}</strong>".format(
        name=assessment.name
    )

    action_url = url_for("admin.perform_close_assessment", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to close the assessment "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=assessment.name)
    )
    submit_label = "Close assessment"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_close_assessment/<int:id>")
@roles_required("root")
def perform_close_assessment(id):
    """
    Close an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_closed:
        return redirect(redirect_url())

    if not assessment.is_closable:
        flash(
            'Cannot close assessment "{name}" because one or more closing criteria have not been met. Check that all scheduled sessions are in the past.'.format(
                name=assessment.name
            ),
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", url_for("admin.manage_assessments"))

    try:
        assessment.closed = False
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not close assessment "{assessment.name}" due to a database error. Please contact a system administrator',
            "error",
        )

    return redirect(url)


@admin.route("/initialize_assessment/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def initialize_assessment(id):
    """
    Initialize an assessment by requesting availability information from faculty, or optionally skip that
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if (
        not assessment.is_valid
        and assessment.availability_lifecycle
        < PresentationAssessment.AVAILABILITY_REQUESTED
    ):
        flash(
            "Cannot request availability for an invalid assessment. Correct any validation errors before attempting to proceed.",
            "info",
        )
        return redirect(redirect_url())

    return_url = url_for("admin.manage_assessments")

    AvailabilityForm = AvailabilityFormFactory(assessment)
    form: AvailabilityForm = AvailabilityForm(obj=assessment)

    if form.is_submitted():
        if hasattr(form, "issue_requests") and form.issue_requests.data:
            if assessment.skip_availability:
                flash(
                    "Cannot issue availability requests because they have been skipped for this assessment",
                    "info",
                )
                return redirect(return_url)

            if not assessment.requested_availability:
                if get_count(assessment.submission_periods) == 0:
                    flash(
                        "Availability requests not issued since this assessment is not attached to any submission periods",
                        "info",
                    )
                    return redirect(return_url)

                if get_count(assessment.sessions) == 0:
                    flash(
                        "Availability requests not issued since this assessment does not contain any sessions",
                        "info",
                    )
                    return redirect(return_url)

                _do_initialize_assessment(
                    'Issue availability requests for "{name}"'.format(
                        name=assessment.name
                    ),
                    "Issue availability requests to faculty assessors",
                    assessment.id,
                    form.availability_deadline.data,
                    False,
                )

            return redirect(return_url)

    else:
        if request.method == "GET":
            if form.availability_deadline.data is None:
                form.availability_deadline.data = date.today() + timedelta(weeks=2)

    if (
        PresentationAssessment.AVAILABILITY_NOT_REQUESTED
        < assessment.availability_lifecycle
        < PresentationAssessment.AVAILABILITY_SKIPPED
    ):
        if hasattr(form, "issue_requests"):
            form.issue_requests.label.text = "Save changes"

    return render_template_context(
        "admin/presentations/availability.html", form=form, assessment=assessment
    )


def _do_initialize_assessment(
    title: str,
    description: str,
    assessment_id: int,
    deadline: datetime,
    skip_availability: bool,
):
    uuid = register_task(title, owner=current_user, description=description)
    celery = current_app.extensions["celery"]
    availability_task = celery.tasks["app.tasks.availability.initialize"]
    availability_task.apply_async(
        args=(assessment_id, current_user.id, uuid, deadline, skip_availability),
        task_id=uuid,
    )


@admin.route("/skip_availability/<int:id>")
@roles_required("root")
def skip_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    return_url = url_for("admin.manage_assessments")

    current_year = get_current_year()

    if not validate_assessment(assessment, current_year=current_year):
        return redirect(return_url)

    if assessment.requested_availability:
        flash(
            "Cannot skip availability collection for this assessment because it has already been opened",
            "info",
        )
        return redirect(return_url)

    if not assessment.skip_availability:
        _do_initialize_assessment(
            'Attach assessor and submitter records for "{name}"'.format(
                name=assessment.name
            ),
            "Attach assessor and submitter records",
            assessment.id,
            None,
            True,
        )

    return redirect(return_url)


@admin.route("/close_availability/<int:id>")
@roles_required("root")
def close_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot close availability collection for this assessment because it has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash(
            "Cannot close availability collection for this assessment because it has been skipped",
            "info",
        )
        return redirect(redirect_url())

    assessment.availability_closed = True
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/availability_reminder/<int:id>")
@roles_required("root")
def availability_reminder(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot issue reminder emails for this assessment because availability collection has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash(
            "Cannot issue reminder emails for this assessment because availabilty collection has been skipped",
            "info",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.availability.reminder_email"]

    email_task.apply_async((id, current_user.id))

    return redirect(redirect_url())


@admin.route("/availability_reminder_individual/<int:id>")
@roles_required("root")
def availability_reminder_individual(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    record: AssessorAttendanceData = AssessorAttendanceData.query.get_or_404(id)
    assessment: PresentationAssessment = record.assessment

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot send a reminder email for this assessment because availability collection has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash(
            "Cannot issue a reminder email for this assessment because availability collection has been skipped",
            "info",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.availability.send_reminder_email"]
    notify_task = celery.tasks["app.tasks.utilities.email_notification"]

    tk = email_task.si(record.id) | notify_task.s(
        current_user.id, "Reminder email has been sent", "info"
    )
    tk.apply_async()

    return redirect(redirect_url())


@admin.route("/reopen_availability/<int:id>")
@roles_required("root")
def reopen_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash(
            "Cannot reopen availability collection for this assessment because it has been skipped",
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot reopen availability collection for this assessment because it has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if not assessment.availability_closed:
        flash(
            "Cannot reopen availability collection for this assessment because it has not yet been closed",
            "info",
        )
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            "Cannot reopen availability collection for this assessment because it has a deployed schedule",
            "info",
        )
        return redirect(redirect_url())

    assessment.availability_closed = False
    if assessment.availability_deadline < date.today():
        assessment.availability_deadline = date.today() + timedelta(weeks=1)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/outstanding_availability/<int:id>")
@roles_required("root")
def outstanding_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot show outstanding availability responses for this assessment because it has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    return render_template_context(
        "admin/presentations/availability/outstanding.html", assessment=assessment
    )


@admin.route("/outstanding_availability_ajax/<int:id>")
@roles_required("root")
def outstanding_availability_ajax(id):
    if not validate_using_assessment():
        return jsonify({})

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return jsonify({})

    if not assessment.requested_availability:
        flash(
            "Cannot show outstanding availability responses for this assessment because it has not yet been opened",
            "info",
        )
        return jsonify({})

    return ajax.admin.outstanding_availability_data(
        assessment.outstanding_assessors.all(), assessment
    )


@admin.route("/force_confirm_availability/<int:assessment_id>/<int:faculty_id>")
@roles_required("root")
def force_confirm_availability(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(
        assessment_id
    )

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot force confirm an availability response for this assessment because it has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            "Cannot force confirm availability for this assessment because it is currently deployed",
            "info",
        )
        return redirect(redirect_url())

    faculty: FacultyData = FacultyData.query.get_or_404(faculty_id)

    if not assessment.includes_faculty(faculty_id):
        flash(
            "Cannot force confirm availability response for {name} because this faculty member is not attached "
            "to this assessment".format(name=faculty.user.name),
            "error",
        )
        return redirect(redirect_url())

    record = assessment.assessor_list.filter_by(
        faculty_id=faculty_id, confirmed=False
    ).first()

    if record is not None:
        record.confirmed = True
        record.confirmed_timestamp = datetime.now()
        db.session.commit()

    return redirect(redirect_url())


@admin.route(
    "/set_assignment_limit/<int:assessment_id>/<int:faculty_id>",
    methods=["GET", "POST"],
)
@roles_required("root")
def schedule_set_limit(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(
        assessment_id
    )

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None:
        url = url_for("admin.assessment_manage_assessors", id=assessment_id)
        text = "assessment assessor list"

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(url)

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot adjust limits from this assessment because availability collection has not yet been opened",
            "info",
        )
        return redirect(url)

    if assessment.is_deployed:
        flash(
            "Cannot adjust limits for this assessment because it is currently deployed",
            "info",
        )
        return redirect(url)

    faculty: FacultyData = FacultyData.query.get_or_404(faculty_id)

    if not assessment.includes_faculty(faculty_id):
        flash(
            'Cannot remove assessor "{name}" from "{assess_name}" because this faculty member is not attached '
            "to this assessment".format(
                name=faculty.user.name, assess_name=assessment.name
            ),
            "error",
        )
        return redirect(url)

    record = assessment.assessor_list.filter_by(faculty_id=faculty_id).first()

    if record is None:
        return redirect(url)

    form = AssignmentLimitForm(obj=record)

    if form.validate_on_submit():
        record.assigned_limit = form.assigned_limit.data
        db.session.commit()

        return redirect(url)

    return render_template_context(
        "admin/presentations/edit_assigned_limit.html",
        form=form,
        fac=faculty,
        rec=record,
        a=assessment,
        url=url,
        text=text,
    )


@admin.route("/remove_assessor/<int:assessment_id>/<int:faculty_id>")
@roles_required("root")
def remove_assessor(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(
        assessment_id
    )

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot remove assessors from this assessment because it has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            "Cannot remove assessors from this assessment because it is currently deployed",
            "info",
        )
        return redirect(redirect_url())

    faculty: FacultyData = FacultyData.query.get_or_404(faculty_id)

    if not assessment.includes_faculty(faculty_id):
        flash(
            'Cannot remove assessor "{name}" from "{assess_name}" because this faculty member is not attached '
            "to this assessment".format(
                name=faculty.user.name, assess_name=assessment.name
            ),
            "error",
        )
        return redirect(redirect_url())

    record = assessment.assessor_list.filter_by(faculty_id=faculty_id).first()

    if record is not None:
        db.session.delete(record)
        db.session.commit()

    return redirect(redirect_url())


@admin.route("/availability_as_csv/<int:id>")
@roles_required("root")
def availability_as_csv(id):
    """
    Convert availability data to CSV and serve
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot generate availability data for this assessment because it has not yet been collected.",
            "info",
        )
        return redirect(redirect_url())

    # add a filename
    headers = Headers()
    headers.set("Content-Disposition", "attachment", filename="availability.csv")

    # stream the response as the data is generated
    return Response(
        stream_with_context(availability_CSV_generator(assessment)),
        mimetype="text/csv",
        headers=headers,
    )


@admin.route("/assessment_manage_sessions/<int:id>")
@roles_required("root")
def assessment_manage_sessions(id):
    """
    Manage dates for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    return render_template_context(
        "admin/presentations/manage_sessions.html", assessment=assessment
    )


@admin.route("/manage_sessions_ajax/<int:id>")
@roles_required("root")
def manage_sessions_ajax(id):
    if not validate_using_assessment():
        return jsonify({})

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return jsonify({})

    return ajax.admin.assessment_sessions_data(assessment.sessions)


@admin.route("/add_session/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def add_session(id):
    """
    Attach a new session to the specified assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if not assessment.is_closed:
        flash(
            'Event "{name}" has been closed and its sessions can no longer be edited'.format(
                name=assessment.name
            ),
            "info",
        )
        return redirect(redirect_url())

    form = AddSessionForm(request.form)

    if form.validate_on_submit():
        sess = PresentationSession(
            owner_id=assessment.id,
            name=form.name.data,
            date=form.date.data,
            session_type=form.session_type.data,
            rooms=form.rooms.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(sess)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not add new session due to a database error. Please contact a system administrator.",
                "error",
            )

        else:
            # add this session to all attendance data records attached for this assessment
            celery = current_app.extensions["celery"]
            adjust_task = celery.tasks["app.tasks.availability.session_added"]

            adjust_task.apply_async(args=(sess.id, assessment.id))

        return redirect(url_for("admin.assessment_manage_sessions", id=id))

    return render_template_context(
        "admin/presentations/edit_session.html", form=form, assessment=assessment
    )


@admin.route("/edit_session/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_session(id):
    """
    Edit an existing assessment event session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    if sess.owner.is_closed:
        flash(
            'Event "{name}" has been closed to feedback and its sessions can no longer be edited'.format(
                name=sess.owner.name
            ),
            "info",
        )
        return redirect(redirect_url())

    form = EditSessionForm(obj=sess)
    form.session = sess

    if form.validate_on_submit():
        sess.name = form.name.data
        sess.date = form.date.data
        sess.session_type = form.session_type.data
        sess.rooms = form.rooms.data

        sess.last_edit_id = current_user.id
        sess.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not save edited session data due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("admin.assessment_manage_sessions", id=sess.owner_id))

    return render_template_context(
        "admin/presentations/edit_session.html",
        form=form,
        assessment=sess.owner,
        sess=sess,
    )


@admin.route("/delete_session/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def delete_session(id):
    """
    Delete the specified session from an assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    if sess.owner.is_closed:
        flash(
            'Event "{name}" has been closed to feedback and its sessions can no longer be edited'.format(
                name=sess.owner.name
            ),
            "info",
        )
        return redirect(redirect_url())

    # deletion can't be done asynchronously, because we want the database to be updated
    # by the time the user's UI is refreshed

    for assessor in sess.owner.assessor_list:
        if sess in assessor.available:
            assessor.available.remove(sess)
        if sess in assessor.unavailable:
            assessor.unavailable.remove(sess)
        if sess in assessor.if_needed:
            assessor.if_needed.remove(sess)

    for submitter in sess.owner.submitter_list:
        if sess in submitter.available:
            submitter.available.remove(sess)
        if sess in submitter.unavailable:
            submitter.unavailable.remove(sess)

    db.session.delete(sess)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/manage_attendees_ajax/<int:id>")
@roles_required("root")
def manage_attendees_ajax(id):
    """
    AJAX data point for managing student attendees
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    attend_filter = request.args.get("attend_filter")

    talks: List[SubmitterAttendanceData] = data.submitter_list

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        talks = [t for t in talks if t.submitter.owner.config.pclass_id == pclass_value]

    if attend_filter == "attending":
        talks = [t for t in talks if t.attending]
    elif attend_filter == "not-attending":
        talks = [t for t in talks if not t.attending]

    return ajax.admin.presentation_attendees_data(
        data, talks, editable=not data.is_deployed
    )


@admin.route("/assessment_attending/<int:a_id>/<int:s_id>")
@roles_required("root")
def assessment_attending(a_id, s_id):
    """
    Mark a student/talk as able to attend the assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be '
            "altered".format(name=data.name),
            "info",
        )
        return redirect(redirect_url())

    talk: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if talk not in data.available_talks:
        flash(
            "Cannot mark the specified presenter as attending because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    data.submitter_attending(talk)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessment_not_attending/<int:a_id>/<int:s_id>")
@roles_required("root")
def assessment_not_attending(a_id, s_id):
    """
    Mark a student/talk as not able to attend the assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be '
            "altered".format(name=data.name),
            "info",
        )
        return redirect(redirect_url())

    talk = SubmissionRecord.query.get_or_404(s_id)

    if talk not in data.available_talks:
        flash(
            "Cannot mark the specified presenter as not attending because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    data.submitter_not_attending(talk)
    db.session.commit()

    # we leave availability information per-session intact, so that it is immediately available again
    # if this presenter is subsequently marked as attending

    return redirect(redirect_url())


@admin.route("/assessment_submitter_availability/<int:a_id>/<int:s_id>")
@roles_required("root")
def assessment_submitter_availability(a_id, s_id):
    """
    Allow submitter availabilities to be specified on a per-session basis
    :param a_id:
    :param s_id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if not data.includes_submitter(s_id):
        flash(
            "Cannot set availability for the specified presenter because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "admin/presentations/availability/submitter_availability.html",
        assessment=data,
        submitter=submitter,
        url=url,
        text=text,
    )


@admin.route("/assessment_assessor_availability/<int:a_id>/<int:f_id>")
@roles_required("root")
def assessment_assessor_availability(a_id, f_id):
    """
    Allow submitter availabilities to be specified on a per-session basis
    :param a_id:
    :param s_id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    assessor: FacultyData = FacultyData.query.get_or_404(f_id)

    if not data.includes_faculty(f_id):
        flash(
            "Cannot set availability for the specified assessor because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "admin/presentations/availability/assessor_availability.html",
        assessment=data,
        assessor=assessor,
        url=url,
        text=text,
    )


@admin.route("/submitter_session_availability/<int:id>")
@roles_required("root")
def submitter_session_availability(id):
    """
    Edit/inspect submitter availabilities per session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if sess.owner.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be'
            " altered".format(name=sess.owner.name),
            "info",
        )
        return redirect(redirect_url())

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter")

    if pclass_filter is None and session.get("attendees_session_pclass_filter"):
        pclass_filter = session["attendees_session_pclass_filter"]

    if pclass_filter is not None:
        session["attendees_session_pclass_filter"] = pclass_filter

    pclasses = sess.owner.available_pclasses

    return render_template_context(
        "admin/presentations/availability/submitter_session_availability.html",
        assessment=sess.owner,
        sess=sess,
        pclass_filter=pclass_filter,
        pclasses=pclasses,
    )


@admin.route("/submitter_session_availability_ajax/<int:id>")
@roles_required("root")
def submitter_session_availability_ajax(id):
    """
    AJAX endpoint for edit/inspect submitter availability per session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if sess.owner.is_deployed:
        return jsonify({})

    if not validate_assessment(sess.owner):
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")

    data = sess.owner
    talks = data.submitter_list.filter_by(
        attending=True
    )  # only include students who are marked as attending
    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        talks = [t for t in talks if t.submitter.owner.config.pclass_id == pclass_value]

    return ajax.admin.submitter_session_availability_data(
        data, sess, talks, editable=not sess.owner.is_deployed
    )


@admin.route("/submitter_available/<int:sess_id>/<int:s_id>")
@roles_accepted("root")
def submitter_available(sess_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess = PresentationSession.query.get_or_404(sess_id)
    data = sess.owner

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=data.name),
            "info",
        )
        return redirect(redirect_url())

    submitter = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in data.available_talks:
        flash(
            "Cannot specify availability for the specified presenter because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    sess.submitter_make_available(submitter)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/submitter_unavailable/<int:sess_id>/<int:s_id>")
@roles_accepted("root")
def submitter_unavailable(sess_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    data = sess.owner

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=data.name),
            "info",
        )
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in data.available_talks:
        flash(
            "Cannot specify availability for the specified presenter because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    sess.submitter_make_unavailable(submitter)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/submitter_available_all_sessions/<int:a_id>/<int:s_id>")
@roles_accepted("root")
def submitter_available_all_sessions(a_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in assessment.available_talks:
        flash(
            "Cannot specify availability for the specified presenter because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    for s in assessment.sessions:
        s.submitter_make_available(submitter)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/submitter_unavailable_all_sessions/<int:a_id>/<int:s_id>")
@roles_accepted("root")
def submitter_unavailable_all_sessions(a_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in assessment.available_talks:
        flash(
            "Cannot specify availability for the specified presenter because they are not included in this presentation assessment",
            "error",
        )
        return redirect(redirect_url())

    for s in assessment.sessions:
        s.submitter_make_unavailable(submitter)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_submitters_available/<int:sess_id>")
@roles_accepted("root")
def session_all_submitters_available(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    for s in assessment.submitter_list:
        s: SubmitterAttendanceData
        rec: SubmissionRecord = s.submitter

        sess.submitter_make_available(rec)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_submitters_unavailable/<int:sess_id>")
@roles_accepted("root")
def session_all_submitters_unavailable(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    for s in assessment.submitter_list:
        s: SubmitterAttendanceData
        rec: SubmissionRecord = s.submitter

        sess.submitter_make_unavailable(rec)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessment_manage_assessors/<int:id>")
@roles_required("root")
def assessment_manage_assessors(id):
    """
    Manage faculty assessors for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")

    if state_filter is None and session.get("assessors_state_filter"):
        state_filter = session["assessors_state_filter"]

    if state_filter is not None:
        session["assessors_state_filter"] = state_filter

    return render_template_context(
        "admin/presentations/manage_assessors.html",
        assessment=data,
        state_filter=state_filter,
    )


@admin.route("/manage_assessors_ajax/<int:id>")
@roles_required("root")
def manage_assessors_ajax(id):
    """
    AJAX data point for managing faculty assessors
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    state_filter = request.args.get("state_filter")

    if state_filter == "confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed.is_(True))
            .all()
        )

    elif state_filter == "not-confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed.is_(False))
            .all()
        )

    else:
        assessors = data.assessor_list.all()

    return ajax.admin.presentation_assessors_data(
        data, assessors, editable=not data.is_deployed
    )


@admin.route("/assessor_session_availability/<int:id>")
@roles_required("root")
def assessor_session_availability(id):
    """
    Edit/inspect faculty availabilities for an assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if sess.owner.is_closed:
        flash(
            'Event "{name}" has been closed and its sessions can no longer be edited'.format(
                name=sess.owner.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")

    if state_filter is None and session.get("assessors_session_state_filter"):
        state_filter = session["assessors_session_state_filter"]

    if state_filter is not None:
        session["assessors_session_state_filter"] = state_filter

    return render_template_context(
        "admin/presentations/availability/assessor_session_availability.html",
        assessment=sess.owner,
        sess=sess,
        state_filter=state_filter,
    )


@admin.route("/assessor_session_availability_ajax/<int:id>")
@roles_required("root")
def assessor_session_availability_ajax(id):
    """
    AJAX data entrypoint for edit/inspect faculty availability viee
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return jsonify({})

    state_filter = request.args.get("state_filter")
    data = sess.owner

    if state_filter == "confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed.is_(True))
            .all()
        )

    elif state_filter == "not-confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed.is_(False))
            .all()
        )

    else:
        assessors = data.assessor_list.all()

    return ajax.admin.assessor_session_availability_data(
        data, sess, assessors, editable=not sess.owner.is_deployed
    )


@admin.route("/assessor_available/<int:sess_id>/<int:f_id>")
@roles_accepted("root")
def assessor_available(sess_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    current_year = get_current_year()
    if not validate_assessment(sess.owner, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)
    sess.faculty_make_available(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_ifneeded/<int:sess_id>/<int:f_id>")
@roles_accepted("root")
def assessor_ifneeded(sess_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    current_year = get_current_year()
    if not validate_assessment(sess.owner, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)
    sess.faculty_make_ifneeded(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_unavailable/<int:sess_id>/<int:f_id>")
@roles_accepted("root")
def assessor_unavailable(sess_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    current_year = get_current_year()
    if not validate_assessment(sess.owner, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)
    sess.faculty_make_unavailable(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_available_all_sessions/<int:a_id>/<int:f_id>")
@roles_accepted("root")
def assessor_available_all_sessions(a_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)

    for s in assessment.sessions:
        s.faculty_make_available(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_unavailable_all_sessions/<int:a_id>/<int:f_id>")
@roles_accepted("root")
def assessor_unavailable_all_sessions(a_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)

    for s in assessment.sessions:
        s.faculty_make_unavailable(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_assessors_available/<int:sess_id>")
@roles_accepted("root")
def session_all_assessors_available(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    for f in assessment.assessor_list:
        f: AssessorAttendanceData
        fac: FacultyData = f.faculty

        sess.faculty_make_available(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_assessors_unavailable/<int:sess_id>")
@roles_accepted("root")
def session_all_assessors_unavailable(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot change availability because collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    for f in assessment.assessor_list:
        f: AssessorAttendanceData
        fac: FacultyData = f.faculty

        sess.faculty_make_unavailable(fac)

    db.session.commit()

    return redirect(redirect_url())
