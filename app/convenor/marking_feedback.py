#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime
from functools import partial

from celery import chain
from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask_security import current_user, roles_accepted
from ordered_set import OrderedSet
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

import app.ajax as ajax
from app.convenor import convenor

from ..database import db
from ..faculty.forms import (
    SubmissionRoleFeedbackForm,
)
from ..models import (
    EnrollmentRecord,
    FacultyData,
    FeedbackRecipe,
    LiveProject,
    MarkingEvent,
    MarkingReport,
    MarkingWorkflow,
    MatchingRecord,
    MatchingRole,
    ProjectClass,
    ProjectClassConfig,
    SelectionRecord,
    SubmissionPeriodRecord,
    SubmissionPeriodUnit,
    SubmissionRecord,
    SubmissionRole,
    SubmissionRoleTypesMixin,
    SubmitterReport,
    SubmittingStudent,
    SupervisionEvent,
    SupervisionEventTemplate,
    User,
)
from ..shared.context.convenor_dashboard import (
    get_convenor_dashboard_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import SelectSubmissionRecordFormFactory
from ..shared.utils import (
    build_submitters_data,
    get_current_year,
    redirect_url,
)
from ..shared.validators import (
    validate_assign_feedback,
    validate_is_convenor,
    validate_project_class,
)
from ..shared.workflow_logging import log_db_commit
from ..task_queue import register_task
from ..tools import ServerSideInMemoryHandler, ServerSideSQLHandler
from .forms import (
    AddSubmissionPeriodUnitFormFactory,
    AddSupervisionEventTemplateFormFactory,
    EditPeriodRecordFormFactory,
    EditProjectConfigFormFactory,
    EditSubmissionPeriodRecordPresentationsForm,
    EditSubmissionPeriodUnitFormFactory,
    EditSupervisionEventTemplateFormFactory,
    ManualAssignFormFactory,
)


@convenor.route("/audit_matches/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_matches(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return render_template_context("convenor/matching/audit.html", pclass=pclass)


@convenor.route("/audit_matches_ajax/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_matches_ajax(pclass_id):
    # pclass_id labels a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    matches = config.published_matches.all()

    return ajax.admin.matches_data(
        matches,
        config=config,
        text="matching audit dashboard",
        url=url_for("convenor.audit_matches", pclass_id=pclass_id),
        is_root=current_user.has_role("root"),
    )


@convenor.route("/audit_schedules/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_schedules(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return render_template_context(
        "convenor/presentations/audit.html", pclass_id=pclass_id
    )


@convenor.route("/audit_schedules_ajax/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_schedules_ajax(pclass_id):
    # pclass_id labels a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    matches = config.published_schedules.all()

    return ajax.admin.assessment_schedules_data(
        matches,
        text="schedule audit dashboard",
        url=url_for("convenor.audit_schedules", pclass_id=pclass_id),
    )


@convenor.route("/close_period/<int:id>")
@roles_accepted("faculty", "admin", "root")
def close_period(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash(
            "The period cannot be closed while marking events are active.", "info"
        )
        return redirect(redirect_url())

    if config.submission_period > config.number_submissions:
        flash(
            'Period close request ignored because "{name}" '
            "is already in a rollover state.".format(name=config.name),
            "info",
        )
        return request.referrer

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = 'Close period "{name}"'.format(name=config.name)
    panel_title = "Close period <strong>{name}</strong>".format(name=config.name)

    action_url = url_for("convenor.do_close_period", id=id, url=url)
    message = (
        "<p>Are you sure that you wish to close this submission period for project class "
        "<strong>{name}</strong>?</p>"
        "<p>After closure, no immediate action is taken automatically by the platform, "
        "but no further edits can be made.</p>"
        "<p>This action cannot be undone.</p>".format(name=config.name)
    )
    submit_label = "Close period"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/do_close_period/<int:id>")
@roles_accepted("faculty", "admin", "root")
def do_close_period(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash(
            "The period cannot be closed while marking events are active.", "info"
        )
        return redirect(redirect_url())

    if config.submission_period > config.number_submissions:
        flash(
            'Period close request ignored because "{name}" '
            "is already in a rollover state.".format(name=config.name),
            "info",
        )
        return request.referrer

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    period: SubmissionPeriodRecord = config.periods.filter_by(
        submission_period=config.submission_period
    ).first()
    if period is None and config.number_submissions > 0:
        flash(
            "Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    period.closed = True
    period.closed_id = current_user.id
    period.closed_timestamp = datetime.now()

    try:
        log_db_commit(
            f'Closed period for "{config.name}" / "{period.display_name}"',
            user=current_user,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not close period due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/edit_project_config/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_project_config(pid):
    # pid is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(pid)

    # reject is user is not a convenor for the associated project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # check configuration is still current
    if config.project_class.most_recent_config.id != config.id:
        flash(
            "It is no longer possible to edit the project configuration for academic year {yra}&ndash;{yrb} "
            "because it has been rolled over.".format(
                yra=config.submit_year_a, yrb=config.submit_year_b
            ),
            "info",
        )
        return redirect(redirect_url())

    EditProjectConfigForm = EditProjectConfigFormFactory(config)
    form = EditProjectConfigForm(obj=config)

    if form.validate_on_submit():
        now = datetime.now()

        if form.skip_matching.data != config.skip_matching:
            config.skip_matching = form.skip_matching.data

        if form.requests_skipped.data != config.requests_skipped:
            config.requests_skipped = form.requests_skipped.data

            if config.requests_skipped:
                config.requests_skipped_id = current_user.id
                config.requests_skipped_timestamp = now
            else:
                config.requests_skipped_by = None
                config.requests_skipped_timestamp = None

        if form.full_CATS.data != config.full_CATS:
            config.full_CATS = form.full_CATS.data

        config.uses_supervisor = form.uses_supervisor.data
        config.uses_marker = form.uses_marker.data
        config.uses_moderator = form.uses_moderator.data
        config.uses_presentations = form.uses_presentations.data
        config.display_marker = form.display_marker.data
        config.display_presentations = form.display_presentations.data

        config.CATS_supervision = form.CATS_supervision.data
        config.CATS_marking = form.CATS_marking.data
        config.CATS_moderation = form.CATS_moderation.data
        config.CATS_presentation = form.CATS_presentation.data

        if hasattr(form, "canvas_module_id"):
            config.canvas_module_id = form.canvas_module_id.data
        if hasattr(form, "canvas_login"):
            config.canvas_login = form.canvas_login.data

        try:
            log_db_commit(
                f'Saved project configuration for "{config.name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save project configuration because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.status", id=config.project_class.id))

    return render_template_context(
        "convenor/dashboard/edit_project_config.html", form=form, config=config
    )


def _validate_submission_period(
    record: SubmissionPeriodRecord, config: ProjectClassConfig
):
    # reject is user is not a convenor for the associated project class
    if not validate_is_convenor(config.project_class):
        return False

    # check configuration is still current
    if config.project_class.most_recent_config.id != config.id:
        flash(
            "It is no longer possible to edit the project configuration for academic year {yra}&ndash;{yrb} "
            "because it has been rolled over.".format(
                yra=config.submit_year_a, yrb=config.submit_year_b
            ),
            "info",
        )
        return False

    # reject if project class is not published
    if not validate_project_class(config.project_class):
        return False

    # reject if this submission period is in the past
    if config.submission_period > record.submission_period:
        flash(
            "It is no longer possible to edit this submission period because it has been closed.",
            "info",
        )
        return False

    # reject if period is retired
    if record.retired:
        flash(
            "It is no longer possible to edit this submission period because it has been retired.",
            "info",
        )
        return False

    # reject if lifecycle stage is marking or later

    state = config.submitter_lifecycle
    if state >= ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash(
            "It is no longer possible to edit this submission period because it is being marked, or is ready to rollover.",
            "info",
        )
        return False

    return True


@convenor.route("/edit_period_record/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_period_record(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    if not _validate_submission_period(record, config):
        return redirect(redirect_url())

    FormClass = EditPeriodRecordFormFactory(config)
    edit_form = FormClass(obj=record)

    if edit_form.validate_on_submit():
        record.name = edit_form.name.data
        record.number_markers = edit_form.number_markers.data
        record.number_moderators = edit_form.number_moderators.data
        record.start_date = edit_form.start_date.data
        record.hand_in_date = edit_form.hand_in_date.data

        if hasattr(edit_form, "canvas_module_id"):
            record.canvas_module_id = edit_form.canvas_module_id.data
        if hasattr(edit_form, "canvas_assignment_id"):
            record.canvas_assignment_id = edit_form.canvas_assignment_id.data

        try:
            log_db_commit(
                f'Saved submission period configuration for "{record.display_name}" in "{config.name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save submission period configuration because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.periods", id=config.project_class.id))

    return render_template_context(
        "convenor/dashboard/edit_period_record.html",
        form=edit_form,
        record=record,
        config=config,
    )


@convenor.route("/edit_period_presentation/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_period_presentation(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    if not _validate_submission_period(record, config):
        return redirect(redirect_url())

    edit_form = EditSubmissionPeriodRecordPresentationsForm(obj=record)

    if edit_form.validate_on_submit():
        record.has_presentation = edit_form.has_presentation.data

        if record.has_presentation:
            record.lecture_capture = edit_form.lecture_capture.data
            record.number_assessors = edit_form.number_assessors.data
            record.max_group_size = edit_form.max_group_size.data
            record.morning_session = edit_form.morning_session.data
            record.afternoon_session = edit_form.afternoon_session.data
            record.talk_format = edit_form.talk_format.data

        try:
            log_db_commit(
                f'Saved presentation settings for submission period "{record.display_name}" in "{config.name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save submission period configuration because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.periods", id=config.project_class.id))

    return render_template_context(
        "convenor/dashboard/edit_period_presentation.html",
        form=edit_form,
        record=record,
    )


@convenor.route("/publish_assignment/<int:id>")
@roles_accepted("faculty", "admin", "root")
def publish_assignment(id):
    # id is a SubmittingStudent
    sub = SubmittingStudent.query.get_or_404(id)

    # reject if project class not published
    if not validate_project_class(sub.config.project_class):
        return redirect(redirect_url())

    # reject if logged-in user is not a convenor for this SubmittingStudent
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    if (
        sub.config.submitter_lifecycle
        >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER
    ):
        flash(
            "It is now too late to publish an assignment to students for this project class.",
            "error",
        )
        return redirect(redirect_url())

    sub.published = True

    try:
        log_db_commit(
            f'Published assignment for submitter "{sub.student.user.name}" in "{sub.config.name}"',
            user=current_user,
            project_classes=sub.config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not publish assignment because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/unpublish_assignment/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unpublish_assignment(id):
    # id is a SubmittingStudent
    sub = SubmittingStudent.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this SubmittingStudent
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(sub.config.project_class):
        return redirect(redirect_url())

    if (
        sub.config.submitter_lifecycle
        >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER
    ):
        flash(
            "It is now too late to unpublish an assignment for this project class.",
            "error",
        )
        return redirect(redirect_url())

    try:
        log_db_commit(
            f'Unpublished assignment for submitter "{sub.student.user.name}" in "{sub.config.name}"',
            user=current_user,
            project_classes=sub.config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not unpublish assignment because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/publish_all_assignments/<int:id>")
@roles_accepted("faculty", "admin", "root")
def publish_all_assignments(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if (
        config.submitter_lifecycle
        >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER
    ):
        flash(
            "It is now too late to publish assignments to students for this project class.",
            "error",
        )
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")

    data = build_submitters_data(
        config, cohort_filter, prog_filter, state_filter, year_filter
    )

    for sel in data:
        sel.published = True

    try:
        log_db_commit(
            f'Published all filtered assignments for "{config.name}"',
            user=current_user,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not publish assignments because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/unpublish_all_assignments/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unpublish_all_assignments(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if (
        config.submitter_lifecycle
        >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER
    ):
        flash(
            "It is now too late to unpublish assignments for this project class.",
            "error",
        )
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")

    data = build_submitters_data(
        config, cohort_filter, prog_filter, state_filter, year_filter
    )

    for sel in data:
        sel.published = False

    try:
        log_db_commit(
            f'Unpublished all filtered assignments for "{config.name}"',
            user=current_user,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not unpublish assignments because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/populate_markers/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def populate_markers(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    uuid = register_task(
        'Populate markers for "{proj}"'.format(proj=config.name),
        owner=current_user,
        description='Populate missing marker assignments for "{proj}"'.format(
            proj=config.name
        ),
    )

    celery = current_app.extensions["celery"]
    populate = celery.tasks["app.tasks.matching.populate_markers"]

    populate.apply_async(args=(config.id, current_user.id, uuid), task_id=uuid)

    return redirect(redirect_url())


@convenor.route("/remove_markers/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def remove_markers(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = "Remove all markers"
    panel_title = "Remove all markers"

    action_url = url_for("convenor.do_remove_markers", configid=configid, url=url)
    message = (
        "<p>Are you sure that you wish to remove all marker assignments?</p>"
        "<p>This action cannot be undone.</p>"
    )
    submit_label = "Remove markers"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/do_remove_markers/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def do_remove_markers(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    uuid = register_task(
        'Remove markers for "{proj}"'.format(proj=config.name),
        owner=current_user,
        description='Remove marker assignments for "{proj}"'.format(proj=config.name),
    )

    celery = current_app.extensions["celery"]
    populate = celery.tasks["app.tasks.matching.remove_markers"]

    populate.apply_async(args=(config.id, current_user.id, uuid), task_id=uuid)

    return redirect(url)


@convenor.route("/view_feedback/", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def view_feedback():
    sub_id = request.args.get("sub_id", None)
    sid = request.args.get("id", None)

    # reject request if neither sub_id nor sid is specified
    if sub_id is None and sid is None:
        abort(404)

    submitter: SubmittingStudent = (
        SubmittingStudent.query.get_or_404(sub_id) if sub_id is not None else None
    )
    rec: SubmissionRecord = (
        SubmissionRecord.query.get_or_404(sid) if sid is not None else None
    )

    if submitter is not None:
        config: ProjectClassConfig = submitter.config
    else:
        config: ProjectClassConfig = rec.period.config

    # construct selector form
    is_admin = validate_is_convenor(config.project_class, message=False)
    SelectSubmissionRecordForm = SelectSubmissionRecordFormFactory(config, is_admin)
    form: SelectSubmissionRecordForm = SelectSubmissionRecordForm(request.form)

    # if submitter and record are both specified, check that SubmissionRecord belongs to it.
    # otherwise, we select the SubmissionRecord corresponding to the current period
    if submitter is not None:
        if rec is not None:
            if rec.owner.id != submitter.id:
                flash(
                    "Cannot display submitter documents for this combination of student and submission record, "
                    "because the specified submission record does not belong to the student",
                    "info",
                )
                return redirect(redirect_url())

        else:
            if hasattr(form, "selector") and form.selector.data is not None:
                rec: SubmissionRecord = submitter.get_assignment(
                    period=form.selector.data
                )
            else:
                rec: SubmissionRecord = submitter.get_assignment()

    else:
        # submitter was not specified, so SubmissionRecord must have been.
        # we extract the SubmittingStudent from the record
        assert rec is not None
        submitter = rec.owner

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    pclass = config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(pclass):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # ensure form selector reflects the record that is actually being displayed
    if hasattr(form, "selector"):
        period: SubmissionPeriodRecord = rec.period
        form.selector.data = period

    # Build list of (event, submitter_report) for all MarkingEvents associated with this period
    all_events = MarkingEvent.query.filter_by(period_id=rec.period_id).all()
    event_data = []
    for event in all_events:
        sr = (
            rec.submitter_reports.join(
                MarkingWorkflow, SubmitterReport.workflow_id == MarkingWorkflow.id
            )
            .filter(MarkingWorkflow.event_id == event.id)
            .first()
        )
        if sr is not None:
            event_data.append((event, sr))

    return render_template_context(
        "convenor/dashboard/view_feedback.html",
        submitter=submitter,
        record=rec,
        form=form,
        event_data=event_data,
        ROLE_SUPERVISOR=SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
        ROLE_RESPONSIBLE_SUPERVISOR=SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        ROLE_PRESENTATION_ASSESSOR=SubmissionRoleTypesMixin.ROLE_PRESENTATION_ASSESSOR,
        ROLE_MARKER=SubmissionRoleTypesMixin.ROLE_MARKER,
        ROLE_MODERATOR=SubmissionRoleTypesMixin.ROLE_MODERATOR,
        text=text,
        url=url,
    )


@convenor.route("/faculty_workload/<int:id>")
@roles_accepted("faculty", "admin", "root")
def faculty_workload(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    enroll_filter = request.args.get("enroll_filter")

    if enroll_filter is None and session.get("convenor_faculty_enroll_filter"):
        enroll_filter = session["convenor_faculty_enroll_filter"]

    if enroll_filter not in [
        "all",
        "supv-active",
        "supv-sabbatical",
        "supv-exempt",
        "mark-active",
        "mark-sabbatical",
        "mark-exempt",
        "pres-active",
        "pres-sabbatical",
        "pres-exempt",
    ]:
        enroll_filter = "all"

    if enroll_filter is not None:
        session["convenor_faculty_enroll_filter"] = enroll_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/workload.html",
        pane="faculty",
        subpane="workload",
        pclass=pclass,
        config=config,
        current_year=current_year,
        convenor_data=data,
        enroll_filter=enroll_filter,
    )


@convenor.route("faculty_workload_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def faculty_workload_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    enroll_filter = request.args.get("enroll_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    # build a list of only enrolled faculty, together with their FacultyData records
    faculty_ids = db.session.query(EnrollmentRecord.owner_id).filter(
        EnrollmentRecord.pclass_id == id
    )

    if enroll_filter == "supv-active":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
        )
    elif enroll_filter == "supv-sabbatical":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_SABBATICAL
        )
    elif enroll_filter == "supv-exempt":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_EXEMPT
        )
    elif enroll_filter == "mark-active":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED
        )
    elif enroll_filter == "mark-sabbatical":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_SABBATICAL
        )
    elif enroll_filter == "mark-exempt":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_EXEMPT
        )
    elif enroll_filter == "pres-active":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.presentations_state
            == EnrollmentRecord.PRESENTATIONS_ENROLLED
        )
    elif enroll_filter == "pres-sabbatical":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.presentations_state
            == EnrollmentRecord.PRESENTATIONS_SABBATICAL
        )
    elif enroll_filter == "pres-exempt":
        faculty_ids = faculty_ids.filter(
            EnrollmentRecord.presentations_state
            == EnrollmentRecord.PRESENTATIONS_EXEMPT
        )

    faculty_ids = faculty_ids.subquery()

    # get User, FacultyData pairs for this list
    base_query = (
        db.session.query(User, FacultyData)
        .filter(User.active)
        .join(FacultyData, FacultyData.id == User.id)
        .join(faculty_ids, User.id == faculty_ids.c.owner_id)
    )

    def search_name(row):
        u: User
        fd: FacultyData
        u, fd = row

        return u.name

    def sort_name(row):
        u: User
        fd: FacultyData
        u, fd = row

        return [u.last_name, u.first_name]

    def sort_workload(row):
        u: User
        fd: FacultyData
        u, fd = row

        CATS_sup, CATS_mark, CATS_moderate, CATS_pres = fd.CATS_assignment(config)
        return CATS_sup + CATS_mark + CATS_moderate + CATS_pres

    name = {"search": search_name, "order": sort_name}
    workload = {"order": sort_workload}
    columns = {"name": name, "workload": workload}

    with ServerSideInMemoryHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.convenor.faculty_workload_data, config)
        )


@convenor.route("/teaching_groups/<int:id>")
@roles_accepted("faculty", "admin", "root")
def teaching_groups(id):
    # id is a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current academic year
    current_year = get_current_year()

    organize_by = request.args.get("organize_by")

    if organize_by is None and session.get("convenor_groups_organize_by"):
        organize_by = session["convenor_groups_organize_by"]

    if organize_by not in ["student", "faculty"]:
        organize_by = "faculty"

    if organize_by is not None:
        session["convenor_groups_organize_by"] = organize_by

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # build list of allowed submission periods
    periods = set()
    period_names = OrderedSet()
    for p in config.ordered_periods:
        periods.add(p.submission_period)
        period_names.append((p.submission_period, p.display_name))

    if len(periods) == 0:
        flash(
            "Internal error: No submission periods have been set up for this ProjectClassConfig. Please contact a system administator.",
            "error",
        )
        return redirect(redirect_url())

    show_period = request.args.get("show_period")
    if show_period is not None and not isinstance(show_period, int):
        show_period = int(show_period)

    if show_period is None and session.get("convenor_groups_show_period"):
        show_period = session["convenor_groups_show_period"]

    if show_period not in periods:
        # get first allowed elmeent of periods
        for x in periods:
            break

        show_period = x

    if show_period is not None:
        session["convenor_groups_show_period"] = show_period

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/teaching_groups.html",
        pane="faculty",
        subpane="groups",
        pclass=pclass,
        config=config,
        current_year=current_year,
        convenor_data=data,
        organize_by=organize_by,
        show_period=show_period,
        period_names=period_names,
    )


@convenor.route("/teaching_groups_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def teaching_groups_ajax(id):
    # id is a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    organize_by = request.args.get("organize_by")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    if organize_by not in ["student", "faculty"]:
        organize_by = "faculty"

    # build list of allowed submission periods
    periods = set()
    period_names = OrderedSet()
    for p in config.ordered_periods:
        periods.add(p.submission_period)
        period_names.append((p.submission_period, p.display_name))

    if len(periods) == 0:
        return jsonify({})

    show_period = request.args.get("show_period")
    if show_period is not None and not isinstance(show_period, int):
        show_period = int(show_period)

    if show_period not in periods:
        # get first allowed element of periods
        for x in periods:
            break

        show_period = x

    if organize_by == "faculty":
        faculty_ids = (
            db.session.query(EnrollmentRecord.owner_id)
            .filter(EnrollmentRecord.pclass_id == id)
            .subquery()
        )

        faculty = (
            db.session.query(FacultyData)
            .join(faculty_ids, FacultyData.id == faculty_ids.c.owner_id)
            .join(User, User.id == FacultyData.id)
            .filter(User.active)
            .all()
        )

        return ajax.convenor.teaching_group_by_faculty(faculty, config, show_period)

    return ajax.convenor.teaching_group_by_student(
        config.submitting_students, config, show_period
    )


@convenor.route("/manual_assign/", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def manual_assign():
    sub_id = request.args.get("sub_id", None)
    sid = request.args.get("id", None)

    # reject request if neither sub_id nor sid is specified
    if sub_id is None and sid is None:
        abort(404)

    submitter: SubmittingStudent = (
        SubmittingStudent.query.get_or_404(sub_id) if sub_id is not None else None
    )
    rec: SubmissionRecord = (
        SubmissionRecord.query.get_or_404(sid) if sid is not None else None
    )

    if submitter is not None:
        current_config: ProjectClassConfig = submitter.config
    else:
        current_config: ProjectClassConfig = rec.period.config

    # construct selector form
    is_admin = validate_is_convenor(current_config.project_class, message=False)
    ManualAssignForm = ManualAssignFormFactory(current_config, is_admin)
    form = ManualAssignForm(request.form)

    # if submitter and record are both specified, check that SubmissionRecord belongs to it.
    # otherwise, we select the SubmissionRecord corresponding to the current period
    if submitter is not None:
        if rec is not None:
            if rec.owner.id != submitter.id:
                flash(
                    "Cannot display submitter documents for this combination of student and submission record, "
                    "because the specified submission record does not belong to the student",
                    "info",
                )
                return redirect(redirect_url())

        else:
            if hasattr(form, "selector") and form.selector.data is not None:
                rec: SubmissionRecord = submitter.get_assignment(
                    period=form.selector.data
                )
            else:
                rec: SubmissionRecord = submitter.get_assignment()

    else:
        # submitter was not specified, so SubmissionRecord must have been.
        # we extract the SubmittingStudent from the record
        assert rec is not None
        submitter = rec.owner

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash(
            "Can not reassign because the list of available Live Projects could not be found",
            "error",
        )
        return redirect(redirect_url())

    # reject if logged-in user is not *currently* a convenor for the project class associated with this submission
    # record (note they don't have to be the historical convenor associated with select_config)
    pclass = current_config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # ensure form selector reflects the record that is actually being displayed
    period: SubmissionPeriodRecord = rec.period
    if hasattr(form, "selector"):
        form.selector.data = period

    return render_template_context(
        "convenor/dashboard/manual_assign.html",
        rec=rec,
        config=select_config,
        url=url,
        text=text,
        form=form,
        submitter=submitter,
        allow_reassign_project=rec.project_id is None or not period.is_feedback_open,
    )


@convenor.route("/manual_assign_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def manual_assign_ajax(id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash(
            "Can not reassign because the list of available Live Projects could not be found",
            "error",
        )
        return jsonify({})

    if not validate_is_convenor(select_config.project_class):
        return jsonify({})

    base_query = select_config.live_projects.join(
        FacultyData, FacultyData.id == LiveProject.owner_id
    ).join(User, User.id == FacultyData.id)

    project = {
        "search": LiveProject.name,
        "order": LiveProject.name,
        "search_collation": "utf8_general_ci",
    }
    supervisor = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }

    columns = {"project": project, "supervisor": supervisor}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.convenor.manual_assign_data, rec))


@convenor.route("/assign_revert/<int:id>")
@roles_accepted("faculty", "admin", "root")
def assign_revert(id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)
    period: SubmissionPeriodRecord = rec.period

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash(
            "Can not revert assignment because the list of available Live Projects could not be found",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash(
            "Can not revert assignment for {name} because feedback is already open".format(
                name=rec.period.display_name
            ),
            "error",
        )
        return redirect(redirect_url())

    if rec.matching_record is None:
        flash(
            "Can not revert assignment for {name} because the automated matching data could not be found".format(
                name=rec.period.display_name
            ),
            "error",
        )
        return redirect(redirect_url())

    now = datetime.now()

    try:
        # remove any SubmissionRole instances for supervisor, marker and moderator
        rec.roles.filter(
            SubmissionRole.role.in_(
                [
                    SubmissionRole.ROLE_SUPERVISOR,
                    SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                    SubmissionRole.ROLE_MARKER,
                    SubmissionRole.ROLE_MODERATOR,
                ]
            )
        ).delete()

        match_record: MatchingRecord = rec.matching_record
        lp = match_record.project
        rec.project_id = lp.id

        for role in match_record.roles:
            role: MatchingRole

            weight = 1.0
            if role.role in [SubmissionRole.ROLE_MARKER]:
                weight = 1.0 / float(period.number_markers)

            new_role = SubmissionRole.build_(
                submission_id=rec.id,
                user_id=role.user_id,
                role=role.role,
                weight=weight,
            )

            db.session.add(new_role)

        log_db_commit(
            f'Reverted submission record {rec.id} to match assignment for "{period.display_name}" in "{period.config.name}"',
            user=current_user,
            project_classes=period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not revert assignment to match because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/assign_from_selection/<int:id>/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def assign_from_selection(id, sel_id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)
    period: SubmissionPeriodRecord = rec.period

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash(
            "Can not reassign because the list of available Live Projects could not be found",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash(
            "Can not reassign for {name} because feedback is already open".format(
                name=rec.period.display_name
            ),
            "error",
        )
        return redirect(redirect_url())

    sel: SelectionRecord = SelectionRecord.query.get_or_404(sel_id)

    try:
        # remove any SubmissionRole instances which have the owner as supervisor
        if rec.project is not None and not rec.project.generic:
            owner = rec.project.owner
            if owner is not None:
                # remove any SubmissionRole instances which have the owner as supervisor
                rec.roles.filter(
                    SubmissionRole.role.in_(
                        [
                            SubmissionRole.ROLE_SUPERVISOR,
                            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                        ]
                    ),
                    SubmissionRole.user_id == owner.id,
                ).delete()

        lp = sel.liveproject
        rec.project_id = lp.id

        if not lp.generic:
            new_owner = lp.owner
            if new_owner is not None:
                weight = 1.0
                role = SubmissionRole.build_(
                    submission_id=rec.id,
                    user_id=new_owner.id,
                    role=SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                    weight=weight,
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now(),
                )
                db.session.add(role)

        log_db_commit(
            f'Assigned project "{lp.name}" to submission {rec.id} from selection for "{period.display_name}" in "{period.config.name}"',
            user=current_user,
            project_classes=period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not assign project because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/assign_liveproject/<int:id>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def assign_liveproject(id, pid):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)
    period: SubmissionPeriodRecord = rec.period

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash(
            "Can not reassign because the list of available Live Projects could not be found",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash(
            "Can not reassign for {name} because feedback is already open".format(
                name=rec.period.display_name
            ),
            "error",
        )
        return redirect(redirect_url())

    lp: LiveProject = LiveProject.query.get_or_404(pid)

    if lp.config_id != select_config.id:
        flash(
            "Can not assign LiveProject #{num} for {name} because they do not belong to the same academic "
            "cycle.".format(num=lp.number, name=rec.period.display_name),
            "error",
        )
        return redirect(redirect_url())

    try:
        # remove any SubmissionRole instances that associate the previous project's owner as the supervisor
        if rec.project is not None and not rec.project.generic:
            owner = rec.project.owner
            if owner is not None:
                # remove any SubmissionRole instances that have the owner as supervisor
                rec.roles.filter(
                    SubmissionRole.role.in_(
                        [
                            SubmissionRole.ROLE_SUPERVISOR,
                            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                        ]
                    ),
                    SubmissionRole.user_id == owner.id,
                ).delete()

        # assign the new project
        rec.project_id = lp.id

        if not lp.generic:
            new_owner = lp.owner
            if new_owner is not None:
                weight = 1.0
                role = SubmissionRole.build_(
                    submission_id=rec.id,
                    user_id=new_owner.id,
                    role=SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                    weight=weight,
                    creation_timestamp=datetime.now(),
                )
                db.session.add(role)

        log_db_commit(
            f'Assigned live project "{lp.name}" to submission {rec.id} for "{period.display_name}" in "{period.config.name}"',
            user=current_user,
            project_classes=period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not assign project because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/deassign_project/<int:id>")
@roles_accepted("faculty", "admin", "root")
def deassign_project(id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash(
            "Can not reassign because the list of available Live Projects could not be found",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash(
            "Can not de-assign project for {name} because feedback is already open".format(
                name=rec.period.display_name
            ),
            "error",
        )
        return redirect(redirect_url())

    # as long as we don't set both project and project_id (or marker and marker_id) simultaneously to zero,
    # the before-update listener for SubmissionRecord will invalidate the correct workload cache entries
    try:
        if rec.project is not None and not rec.project.generic:
            owner = rec.project.owner
            if owner is not None:
                # remove any SubmissionRole instances which have the owner as supervisor
                rec.roles.filter(
                    SubmissionRole.role.in_(
                        [
                            SubmissionRole.ROLE_SUPERVISOR,
                            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                        ]
                    ),
                    SubmissionRole.user_id == owner.id,
                ).delete()

        rec.project = None
        log_db_commit(
            f'Removed project assignment from submission {rec.id} for "{rec.period.display_name}" in "{rec.period.config.name}"',
            user=current_user,
            project_classes=rec.period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deassign project because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/edit_feedback/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_feedback(id):
    # id is a MarkingReport instance
    report: MarkingReport = MarkingReport.query.get_or_404(id)
    sr: SubmitterReport = report.submitter_report
    record: SubmissionRecord = sr.record
    pclass = sr.workflow.event.pclass

    if record.retired:
        flash(
            "It is not possible to edit feedback for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period
    form = SubmissionRoleFeedbackForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        report.feedback_positive = form.positive_feedback.data
        report.feedback_improvement = form.improvement_feedback.data

        if report.feedback_submitted:
            report.feedback_timestamp = datetime.now()

        try:
            log_db_commit(
                f'Saved feedback for MarkingReport #{report.id} on submission {record.id} for "{period.display_name}" in "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save feedback due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    else:
        if request.method == "GET":
            form.positive_feedback.data = report.feedback_positive
            form.improvement_feedback.data = report.feedback_improvement

    return render_template_context(
        "faculty/dashboard/edit_feedback.html",
        form=form,
        title="Edit feedback",
        unique_id=f"report-{id}",
        formtitle='Edit feedback for <i class="fas fa-user-circle"></i> '
        "<strong>{name}</strong>".format(name=record.student_identifier["label"]),
        submit_url=url_for("convenor.edit_feedback", id=id, url=url),
        period=period,
        record=report,
        dont_show_warnings=True,
    )


@convenor.route("/submit_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def submit_feedback(id):
    # id is a MarkingReport instance
    report: MarkingReport = MarkingReport.query.get_or_404(id)
    sr: SubmitterReport = report.submitter_report
    record: SubmissionRecord = sr.record
    pclass = sr.workflow.event.pclass

    if record.retired:
        flash(
            "It is not possible to edit feedback for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if report.feedback_submitted:
        return redirect(redirect_url())

    if not report.feedback_positive and not report.feedback_improvement:
        flash(
            "Feedback is empty — please enter feedback before submitting.",
            "warning",
        )
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    try:
        report.feedback_submitted = True
        report.feedback_timestamp = datetime.now()

        log_db_commit(
            f'Submitted feedback for MarkingReport #{report.id} on submission {record.id} for "{period.display_name}" in "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not submit feedback due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/unsubmit_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unsubmit_feedback(id):
    # id is a MarkingReport instance
    report: MarkingReport = MarkingReport.query.get_or_404(id)
    sr: SubmitterReport = report.submitter_report
    record: SubmissionRecord = sr.record
    pclass = sr.workflow.event.pclass
    event = sr.workflow.event

    if record.retired:
        flash(
            "It is not possible to edit feedback for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash(
            "This operation is not permitted. It is not possible to unsubmit feedback after the marking event has been closed.",
            "error",
        )
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    try:
        report.feedback_submitted = False
        report.feedback_timestamp = None

        log_db_commit(
            f'Unsubmitted feedback for MarkingReport #{report.id} on submission {record.id} for "{period.display_name}" in "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not unsubmit feedback due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/push_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def push_feedback(id):
    # id identifies a SubmissionPeriodRecord
    period = SubmissionPeriodRecord.query.get_or_404(id)

    config: ProjectClassConfig = period.config
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if not period.closed:
        flash(
            "It is only possible to push feedback once the submission period is closed.",
            "info",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.push_feedback.push_period"]

    tk_name = f"Push feedback reports"
    tk_description = (
        "Send feedback reports by email for {config.name} {period.display_name}"
    )
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        email_task.si(id, current_user.id, True, None),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@convenor.route("/populate_supervision_events/<int:period_id>")
@roles_accepted("faculty", "admin", "root")
def populate_supervision_events(period_id):
    # period_id is a SubmissionPeriodRecord
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    populate = celery.tasks["app.tasks.events.populate"]

    tk_name = f'Populate supervision events for submission period "{period.display_name}" in "{config.name}"'
    tk_description = "Populate supervision events"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        populate.si(task_id, period_id, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@convenor.route("/inspect_period_units/<int:period_id>")
@roles_accepted("faculty", "admin", "root")
def inspect_period_units(period_id):
    # period_id is a SubmissionPeriodRecord
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/supervision_events/inspect_period_units.html",
        period=period,
        config=config,
        url=url,
        text=text,
    )


@convenor.route("/inspect_period_units_ajax/<int:period_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def inspect_period_units_ajax(period_id):
    """
    AJAX endpoint for inspect_period_units view
    """
    # period_id is a SubmissionPeriodRecord
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return jsonify({})

    base_query = period.units

    name = {
        "search": SubmissionPeriodUnit.name,
        "order": SubmissionPeriodUnit.name,
        "search_collation": "utf8_general_ci",
    }
    start_date = {"order": SubmissionPeriodUnit.start_date}
    end_date = {"order": SubmissionPeriodUnit.end_date}

    columns = {"name": name, "start_date": start_date, "end_date": end_date}

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(
                ajax.convenor.submission_period_units_data,
                period=period,
                url=url,
                text=text,
            )
        )


@convenor.route("/add_period_unit/<int:period_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_period_unit(period_id):
    # period_id is a SubmissionPeriodRecord
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.inspect_period_units", period_id=period.id)

    AddPeriodUnitForm = AddSubmissionPeriodUnitFormFactory(period)
    form = AddPeriodUnitForm(request.form)

    if form.validate_on_submit():
        unit = SubmissionPeriodUnit(
            owner_id=period.id,
            name=form.name.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
            last_edit_id=None,
            last_edit_timestamp=None,
        )

        try:
            db.session.add(unit)
            log_db_commit(
                f'Added new submission period unit "{unit.name}" to period "{period.display_name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new submission period unit due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/supervision_events/edit_period_unit.html",
        form=form,
        period=period,
        title="Add submission period unit",
        formtitle=f"Add unit to submission period <strong>{period.display_name}</strong>",
        url=url,
    )


@convenor.route("/edit_period_unit/<int:unit_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_period_unit(unit_id):
    # unit_id is a SubmissionPeriodUnit
    unit: SubmissionPeriodUnit = SubmissionPeriodUnit.query.get_or_404(unit_id)
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.inspect_period_units", period_id=period.id)

    EditPeriodUnitForm = EditSubmissionPeriodUnitFormFactory(period)
    form = EditPeriodUnitForm(obj=unit)
    form.unit = unit

    if form.validate_on_submit():
        unit.name = form.name.data
        unit.start_date = form.start_date.data
        unit.end_date = form.end_date.data
        unit.last_edit_id = current_user.id
        unit.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f'Saved changes to submission period unit "{unit.name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to submission period unit due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/supervision_events/edit_period_unit.html",
        form=form,
        unit=unit,
        title="Edit submission period unit",
        formtitle=f"Edit submission period unit <strong>{unit.name}</strong>",
        url=url,
    )


@convenor.route("/delete_period_unit/<int:unit_id>")
@roles_accepted("faculty", "admin", "root")
def delete_period_unit(unit_id):
    # unit_id is a SubmissionPeriodUnit
    unit: SubmissionPeriodUnit = SubmissionPeriodUnit.query.get_or_404(unit_id)
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    try:
        db.session.delete(unit)
        log_db_commit(
            f'Deleted submission period unit "{unit.name}" from period "{period.display_name}"',
            user=current_user,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete submission period unit due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("convenor.inspect_period_units", period_id=period.id))


@convenor.route("/inspect_unit_event_templates/<int:unit_id>")
@roles_accepted("faculty", "admin", "root")
def inspect_unit_event_templates(unit_id):
    # unit_id is a SubmissionPeriodUnit
    unit: SubmissionPeriodUnit = SubmissionPeriodUnit.query.get_or_404(unit_id)
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/supervision_events/inspect_unit_event_templates.html",
        unit=unit,
        period=period,
        config=config,
        url=url,
        text=text,
    )


@convenor.route("/inspect_unit_event_templates_ajax/<int:unit_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def inspect_unit_event_templates_ajax(unit_id):
    """
    AJAX endpoint for inspect_unit_event_templates view
    """
    # unit_id is a SubmissionPeriodUnit
    unit: SubmissionPeriodUnit = SubmissionPeriodUnit.query.get_or_404(unit_id)
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return jsonify({})

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    templates = unit.templates.all()

    return jsonify(
        ajax.convenor.supervision_event_templates_data(
            templates, unit, url=url, text=text
        )
    )


@convenor.route("/add_unit_event_template/<int:unit_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_unit_event_template(unit_id):
    # unit_id is a SubmissionPeriodUnit
    unit: SubmissionPeriodUnit = SubmissionPeriodUnit.query.get_or_404(unit_id)
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.inspect_unit_event_templates", unit_id=unit.id)

    AddSupervisionEventTemplateForm = AddSupervisionEventTemplateFormFactory(unit)
    form = AddSupervisionEventTemplateForm(request.form)

    if form.validate_on_submit():
        template = SupervisionEventTemplate(
            unit_id=unit.id,
            name=form.name.data,
            target_role=form.target_role.data,
            type=form.type.data,
            monitor_attendance=form.monitor_attendance.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
            last_edit_id=None,
            last_edit_timestamp=None,
        )

        try:
            db.session.add(template)
            log_db_commit(
                f'Added new supervision event template "{template.name}" to unit "{unit.name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new supervision event template due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/supervision_events/edit_unit_event_template.html",
        form=form,
        unit=unit,
        title="Add supervision event template",
        formtitle=f"Add event template to unit <strong>{unit.name}</strong>",
        url=url,
    )


@convenor.route("/edit_unit_event_template/<int:template_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_unit_event_template(template_id):
    # template_id is a SupervisionEventTemplate
    template: SupervisionEventTemplate = SupervisionEventTemplate.query.get_or_404(
        template_id
    )
    unit: SubmissionPeriodUnit = template.unit
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.inspect_unit_event_templates", unit_id=unit.id)

    EditSupervisionEventTemplateForm = EditSupervisionEventTemplateFormFactory(unit)
    form = EditSupervisionEventTemplateForm(obj=template)
    form.template = template

    if form.validate_on_submit():
        template.name = form.name.data
        template.target_role = form.target_role.data
        template.type = form.type.data
        template.monitor_attendance = form.monitor_attendance.data
        template.last_edit_id = current_user.id
        template.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f'Saved changes to supervision event template "{template.name}" in unit "{unit.name}"',
                user=current_user,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to supervision event template due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/supervision_events/edit_unit_event_template.html",
        form=form,
        event_template=template,
        unit=unit,
        title="Edit supervision event template",
        formtitle=f"Edit supervision event template <strong>{template.name}</strong> in unit <strong>{unit.name}</strong>",
        url=url,
    )


@convenor.route("/delete_unit_event_template/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def delete_unit_event_template(template_id):
    # template_id is a SupervisionEventTemplate
    template: SupervisionEventTemplate = SupervisionEventTemplate.query.get_or_404(
        template_id
    )
    unit: SubmissionPeriodUnit = template.unit
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    try:
        db.session.delete(template)
        log_db_commit(
            f'Deleted supervision event template "{template.name}" from unit "{unit.name}"',
            user=current_user,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete supervision event template due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url_for("convenor.inspect_unit_event_templates", unit_id=unit.id))


@convenor.route("/inspect_template_events/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def inspect_template_events(template_id):
    # template_id is a SupervisionEventTemplate
    template: SupervisionEventTemplate = SupervisionEventTemplate.query.get_or_404(
        template_id
    )
    unit: SubmissionPeriodUnit = template.unit
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/supervision_events/inspect_template_events.html",
        event_template=template,
        unit=unit,
        period=period,
        config=config,
        url=url,
        text=text,
    )


@convenor.route("/inspect_template_events_ajax/<int:template_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def inspect_template_events_ajax(template_id):
    """
    AJAX endpoint for inspect_template_events view
    """
    # template_id is a SupervisionEventTemplate
    template: SupervisionEventTemplate = SupervisionEventTemplate.query.get_or_404(
        template_id
    )
    unit: SubmissionPeriodUnit = template.unit
    period: SubmissionPeriodRecord = unit.owner
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return jsonify({})

    base_query = template.events

    name = {
        "search": SupervisionEvent.name,
        "order": SupervisionEvent.name,
        "search_collation": "utf8_general_ci",
    }
    datetime_col = {"order": SupervisionEvent.time}

    columns = {"name": name, "datetime": datetime_col}

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(
                ajax.convenor.supervision_events_data,
                template=template,
                url=url,
                text=text,
            )
        )


@convenor.route("/generate_feedback_reports/<int:id>")
@roles_accepted("faculty", "admin", "root")
def generate_feedback_reports(id):
    # id identifies a SubmissionPeriodRecord
    period = SubmissionPeriodRecord.query.get_or_404(id)

    config = period.config
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if not period.closed:
        flash(
            "It is only possible to push feedback once the submission period is closed.",
            "info",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    generate_task = celery.tasks["app.tasks.marking.generate_feedback_reports"]

    recipe = db.session.query(FeedbackRecipe).first()

    tk_name = f"Generate feedback reports"
    tk_description = "Generate feedback reports for {config.name} {period.display_name}"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        generate_task.si(recipe.id, period.id, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())
