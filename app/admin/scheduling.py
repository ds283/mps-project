#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from typing import List

from celery import chain
from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask_security import (
    current_user,
    roles_accepted,
    roles_required,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

import app.ajax as ajax

from ..database import db
from ..models import (
    AssessorAttendanceData,
    EnrollmentRecord,
    FacultyData,
    PresentationAssessment,
    ProjectClass,
    Room,
    ScheduleAttempt,
    ScheduleSlot,
    SubmissionRecord,
    TaskRecord,
    User,
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
    validate_schedule_inspector,
    validate_using_assessment,
)
from ..task_queue import progress_update, register_task
from . import admin
from .actions import pair_slots
from .forms import (
    CompareScheduleFormFactory,
    ImposeConstraintsScheduleFormFactory,
    NewScheduleFormFactory,
    RenameScheduleFormFactory,
)


@admin.route("/assessment_schedules/<int:id>")
@roles_required("root")
def assessment_schedules(id):
    """
    Manage schedules associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash(
            "It is only possible to generate schedules once collection of faculty availabilities is closed (or has been skipped).",
            "info",
        )
        return redirect(redirect_url())

    matches = get_count(assessment.scheduling_attempts)

    return render_template_context(
        "admin/presentations/scheduling/manage.html",
        pane="manage",
        info=matches,
        assessment=assessment,
    )


@admin.route("/assessment_schedules_ajax/<int:id>")
@roles_required("root")
def assessment_schedules_ajax(id):
    """
    AJAX data point for schedules associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return jsonify({})

    if not assessment.availability_closed and not assessment.skip_availability:
        return jsonify({})

    return ajax.admin.assessment_schedules_data(
        assessment.scheduling_attempts,
        text="assessment schedule manager",
        url=url_for("admin.assessment_schedules", id=id),
    )


@admin.route("/create_assessment_schedule/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def create_assessment_schedule(id):
    """
    Create a new schedule associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash(
            "It is only possible to generate schedules once collection of faculty availabilities is closed (or has been skipped).",
            "info",
        )
        return redirect(redirect_url())

    if not assessment.is_valid:
        flash(
            "It is not possible to generate a schedule for an assessment that contains validation errors. "
            "Correct any indicated errors before attempting to try again.",
            "info",
        )
        return redirect(redirect_url())

    if assessment.number_slots <= 0:
        flash(
            "It is not possible to generate a schedule for this assessment, because it does not yet have any defined session slots.",
            "info",
        )
        return redirect(redirect_url())

    NewScheduleForm = NewScheduleFormFactory(assessment)
    form = NewScheduleForm(request.form)

    if form.validate_on_submit():
        offline = False

        if form.submit.data:
            task_name = 'Perform optimal scheduling for "{name}"'.format(
                name=form.name.data
            )
            desc = "Automated assessment scheduling task"

        elif form.offline.data:
            offline = True
            task_name = 'Generate file for offline scheduling for "{name}"'.format(
                name=form.name.data
            )
            desc = "Produce .LP file for download and offline scheduling"

        else:
            raise RuntimeError("Unknown submit button in create_assessment_schedule()")

        uuid = register_task(task_name, owner=current_user, description=desc)

        schedule = ScheduleAttempt(
            owner_id=assessment.id,
            name=form.name.data,
            tag=form.tag.data,
            celery_id=uuid,
            finished=False,
            awaiting_upload=offline,
            celery_finished=False,
            outcome=None,
            published=False,
            deployed=False,
            construct_time=None,
            compute_time=None,
            assessor_assigned_limit=form.assessor_assigned_limit.data,
            assessor_multiplicity_per_session=form.assessor_multiplicity_per_session.data,
            if_needed_cost=form.if_needed_cost.data,
            levelling_tension=form.levelling_tension.data,
            ignore_coscheduling=form.ignore_coscheduling.data,
            all_assessors_in_pool=form.all_assessors_in_pool.data,
            solver=form.solver.data,
            creation_timestamp=datetime.now(),
            creator_id=current_user.id,
            last_edit_timestamp=None,
            last_edit_id=None,
            score=None,
            lp_file_id=None,
        )

        db.session.add(schedule)
        db.session.commit()

        if offline:
            celery = current_app.extensions["celery"]
            schedule_task = celery.tasks["app.tasks.scheduling.offline_schedule"]

            schedule_task.apply_async(args=(schedule.id, current_user.id), task_id=uuid)

            return redirect(url_for("admin.assessment_schedules", id=assessment.id))

        else:
            celery = current_app.extensions["celery"]
            schedule_task = celery.tasks["app.tasks.scheduling.create_schedule"]

            schedule_task.apply_async(args=(schedule.id,), task_id=uuid)

            return redirect(url_for("admin.assessment_schedules", id=assessment.id))

    else:
        if request.method == "GET":
            form.all_assessors_in_pool.data = ScheduleAttempt.AT_LEAST_ONE_IN_POOL

    matches = get_count(assessment.scheduling_attempts)

    return render_template_context(
        "admin/presentations/scheduling/create.html",
        pane="create",
        info=matches,
        form=form,
        assessment=assessment,
    )


@admin.route("/adjust_assessment_schedule/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def adjust_assessment_schedule(id):
    """
    Generate options page for re-imposition of constraints
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    schedule: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)
    assessment: PresentationAssessment = schedule.owner

    current_year = get_current_year()
    if not validate_assessment(schedule.owner, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash(
            "It is only possible to adjust a schedule once collection of faculty availabilities is closed (or has been skipped).",
            "info",
        )
        return redirect(redirect_url())

    if not assessment.is_valid:
        flash(
            "It is not possible to adjust a schedule for an assessment that contains validation errors. "
            "Correct any indicated errors before attempting to try again.",
            "info",
        )
        return redirect(redirect_url())

    if schedule.is_valid:
        flash(
            "This schedule does not contain any validation errors, so does not require adjustment.",
            "info",
        )
        return redirect(redirect_url())

    ImposeConstraintsScheduleForm = ImposeConstraintsScheduleFormFactory(assessment)
    form = ImposeConstraintsScheduleForm(request.form)

    if form.validate_on_submit():
        allow_new_slots = form.allow_new_slots.data
        name = form.name.data
        tag = form.tag.data

        return redirect(
            url_for(
                "admin.perform_adjust_assessment_schedule",
                id=id,
                name=name,
                tag=tag,
                new_slots=allow_new_slots,
            )
        )

    else:
        if request.method == "GET":
            # find name for adjusted schedule
            suffix = 2
            while suffix < 100:
                new_name = "{name} #{suffix}".format(name=schedule.name, suffix=suffix)

                if (
                    ScheduleAttempt.query.filter_by(
                        name=new_name, owner_id=schedule.owner_id
                    ).first()
                    is None
                ):
                    break

                suffix += 1

            if suffix > 100:
                flash(
                    'Can not adjust schedule "{name}" because a new unique tag could not '
                    "be generated.".format(name=schedule.name),
                    "error",
                )
                return redirect(redirect_url())

            form.name.data = new_name

            guess_id = db.session.query(func.max(ScheduleAttempt.id)).scalar() + 1
            new_tag = "schedule_{n}".format(n=guess_id)

            form.tag.data = new_tag

    return render_template_context(
        "admin/presentations/scheduling/adjust_options.html", record=schedule, form=form
    )


@admin.route("/perform_adjust_assessment_schedule/<int:id>")
@roles_required("root")
def perform_adjust_assessment_schedule(id):
    """
    Adjust an existing schedule to re-impose constraints
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    old_schedule: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)
    assessment: PresentationAssessment = old_schedule.owner

    current_year = get_current_year()
    if not validate_assessment(old_schedule.owner, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash(
            "It is only possible to adjust a schedule once collection of faculty availabilities is closed (or has been skipped).",
            "info",
        )
        return redirect(redirect_url())

    if not assessment.is_valid:
        flash(
            "It is not possible to adjust a schedule for an assessment that contains validation errors. "
            "Correct any indicated errors before attempting to try again.",
            "info",
        )
        return redirect(redirect_url())

    if old_schedule.is_valid:
        flash(
            "This schedule does not contain any validation errors, so does not require adjustment.",
            "info",
        )
        return redirect(redirect_url())

    new_name = request.args.get("name", None)
    new_tag = request.args.get("tag", None)

    if new_name is None:
        flash("A name for the adjusted schedule was not supplied.", "error")
        return redirect(redirect_url())

    if new_tag is None:
        flash("A tag for the adjusted schedule was not supplied.", "error")
        return redirect(redirect_url())

    allow_new_slots = request.args.get("new_slots", False)

    uuid = register_task(
        'Schedule job "{name}"'.format(name=new_name),
        owner=current_user,
        description="Automated assessment scheduling task",
    )

    new_schedule = ScheduleAttempt(
        owner_id=old_schedule.owner_id,
        name=new_name,
        tag=new_tag,
        celery_id=uuid,
        finished=False,
        celery_finished=False,
        awaiting_upload=False,
        outcome=None,
        published=old_schedule.published,
        construct_time=None,
        compute_time=None,
        assessor_assigned_limit=old_schedule.assessor_assigned_limit,
        assessor_multiplicity_per_session=old_schedule.assessor_multiplicity_per_session,
        if_needed_cost=old_schedule.if_needed_cost,
        levelling_tension=old_schedule.levelling_tension,
        ignore_coscheduling=old_schedule.ignore_coscheduling,
        all_assessors_in_pool=old_schedule.all_assessors_in_pool,
        solver=old_schedule.solver,
        creation_timestamp=datetime.now(),
        creator_id=current_user.id,
        last_edit_timestamp=None,
        last_edit_id=None,
        score=None,
        lp_file_id=None,
    )

    try:
        db.session.add(new_schedule)
        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            "A database error was encountered. Please check that the supplied name and tag are unique.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    schedule_task = celery.tasks["app.tasks.scheduling.recompute_schedule"]

    schedule_task.apply_async(
        args=(new_schedule.id, old_schedule.id, allow_new_slots), task_id=uuid
    )

    return redirect(url_for("admin.assessment_schedules", id=old_schedule.owner.id))


@admin.route("/terminate_schedule/<int:id>")
@roles_required("root")
def terminate_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if record.finished:
        flash(
            'Can not terminate scheduling task "{name}" because it has finished.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    title = "Terminate schedule"
    panel_title = "Terminate schedule <strong>{name}</strong>".format(name=record.name)

    action_url = url_for(
        "admin.perform_terminate_schedule", id=id, url=request.referrer
    )
    message = (
        "<p>Please confirm that you wish to terminate the scheduling job "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Terminate job"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_terminate_schedule/<int:id>")
@roles_required("root")
def perform_terminate_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if record.finished:
        flash(
            'Can not terminate scheduling task "{name}" because it has finished.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(url)

    if not record.celery_finished:
        celery = current_app.extensions["celery"]
        celery.control.revoke(record.celery_id, terminate=True, signal="SIGUSR1")

    try:
        if not record.celery_finished:
            progress_update(
                record.celery_id,
                TaskRecord.TERMINATED,
                100,
                "Task terminated by user",
                autocommit=False,
            )

        # delete all ScheduleSlot records associated with this ScheduleAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(ScheduleSlot).filter_by(owner_id=record.id).delete()

        expire_time = datetime.now() + timedelta(days=1)
        if record.lp_file is not None:
            record.lp_file.expiry = expire_time
            record.lp_file = None

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not terminate scheduling task "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/delete_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def delete_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        flash(
            'Can not delete schedule "{name}" because it has not terminated.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if record.deployed:
        flash(
            'Can not delete schedule "{name}" because it has been deployed.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not current_user.has_role("root") and current_user.id != record.creator_id:
        flash(
            'Schedule "{name}" cannot be deleted because it belongs to another user',
            "info",
        )
        return redirect(redirect_url())

    title = "Delete schedule"
    panel_title = "Delete schedule <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_delete_schedule", id=id, url=request.referrer)

    if record.published:
        message = (
            "<p>Please confirm that you wish to delete the schedule "
            "<strong>{name}</strong>. Note that this schedule has been "
            "published to project convenors.</p>"
            "<p>This action cannot be undone.</p>".format(name=record.name)
        )
    else:
        message = (
            "<p>Please confirm that you wish to delete the schedule "
            "<strong>{name}</strong>.</p>"
            "<p>This action cannot be undone.</p>".format(name=record.name)
        )

    submit_label = "Delete schedule"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_delete_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(url)

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        flash(
            'Can not delete schedule "{name}" because it has not terminated.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(url)

    if record.deployed:
        flash(
            'Can not delete schedule "{name}" because it has been deployed.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(url)

    if not current_user.has_role("root") and current_user.id != record.creator_id:
        flash(
            'Schedule "{name}" cannot be deleted because it belongs to another user',
            "info",
        )
        return redirect(url)

    try:
        # delete all ScheduleSlots associated with this ScheduleAttempt
        for slot in record.slots:
            slot.assessors = []
            slot.talks = []
            db.session.delete(slot)
        db.session.flush()

        expire_time = datetime.now() + timedelta(days=1)
        if record.lp_file is not None:
            record.lp_file.expiry = expire_time
            record.lp_file = None

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not delete schedule "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/revert_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def revert_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not revert schedule "{name}" because it is still awaiting '
                "manual upload".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not revert schedule "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not revert schedule "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    title = "Revert schedule"
    panel_title = "Revert schedule <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_revert_schedule", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to revert the schedule "
        "<strong>{name}</strong> to its original state.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Revert schedule"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_revert_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_revert_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        # TODO consider an alternative implementation here
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not revert schedule "{name}" because it is still awaiting '
                "manual upload".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not revert schedule "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not revert schedule "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    # hand off revert job to asynchronous queue
    celery = current_app.extensions["celery"]
    revert = celery.tasks["app.tasks.scheduling.revert"]

    tk_name = "Revert {name}".format(name=record.name)
    tk_description = "Revert schedule to its original state"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        revert.si(record.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url)


@admin.route("/duplicate_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def duplicate_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            if not record.celery_finished:
                flash(
                    'Can not duplicate schedule "{name}" because the files for offline processing '
                    "are still being generated.".format(name=record.name),
                    "error",
                )
                return redirect(redirect_url())
        else:
            flash(
                'Can not duplicate schedule "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
            return redirect(redirect_url())

    if record.finished and not record.solution_usable:
        flash(
            'Can not duplicate schedule "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    suffix = 2
    while suffix < 100:
        new_name = "{name} #{suffix}".format(name=record.name, suffix=suffix)

        if ScheduleAttempt.query.filter_by(name=new_name).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash(
            'Can not duplicate schedule "{name}" because a new unique tag could not '
            "be generated.".format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    # hand off duplicate job to asynchronous queue
    celery = current_app.extensions["celery"]
    duplicate = celery.tasks["app.tasks.scheduling.duplicate"]

    tk_name = "Duplicate {name}".format(name=record.name)
    tk_description = "Duplicate presentation assessment schedule"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        duplicate.si(record.id, new_name, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/rename_schedule/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def rename_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    RenameScheduleForm = RenameScheduleFormFactory(record.owner)
    form = RenameScheduleForm(obj=record)
    form.schedule = record

    if form.validate_on_submit():
        try:
            record.name = form.name.data
            record.tag = form.tag.data
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                'Could not rename schedule "{name}" due to a database error. '
                "Please contact a system administrator.".format(name=record.name),
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context(
        "admin/presentations/scheduling/rename.html", form=form, record=record, url=url
    )


@admin.route("/compare_schedule/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def compare_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for comparison because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    CompareScheduleForm = CompareScheduleFormFactory(
        record.owner_id, record.id, current_user.has_role("root")
    )
    form = CompareScheduleForm(request.form)

    if form.validate_on_submit():
        comparator = form.target.data
        return redirect(
            url_for(
                "admin.do_schedule_compare",
                id1=id,
                id2=comparator.id,
                text=text,
                url=url,
            )
        )

    return render_template_context(
        "admin/presentations/schedule_inspector/compare_setup.html",
        form=form,
        record=record,
        text=text,
        url=url,
    )


@admin.route("/do_schedule_compare/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_schedule_compare(id1, id2):
    record1: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id1)
    record2: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id2)

    pclass_filter = request.args.get("pclass_filter")
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None:
        url = redirect_url()

    if not validate_schedule_inspector(record1) or not validate_schedule_inspector(
        record2
    ):
        return redirect(url)

    if record1.owner_id != record2.owner_id:
        flash(
            "It is only possible to compare two schedules belonging to the same assessment. "
            'Schedule "{name1}" belongs to assessment "{assess1}", but schedule '
            '"{name2}" belongs to assessment "{assess2}"'.format(
                name1=record1.name,
                name2=record2.name,
                assess1=record1.owner.name,
                assess2=record2.owner.name,
            )
        )
        return redirect(url)

    if not validate_assessment(record1.owner):
        return redirect(url)

    if not record1.finished:
        if record1.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting '
                "manual upload.".format(name=record1.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for comparison because it has not yet '
                "terminated.".format(name=record1.name),
                "error",
            )
        return redirect(url)

    if not record1.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record1.name),
            "info",
        )
        return redirect(url)

    if not record2.finished:
        if record2.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting '
                "manual upload.".format(name=record2.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for comparison because it has not yet '
                "terminated.".format(name=record2.name),
                "error",
            )
        return redirect(url)

    if not record2.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record2.name),
            "info",
        )
        return redirect(url)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_schedule_pclass_filter"):
        pclass_filter = session["admin_schedule_pclass_filter"]

    pclasses = record1.available_pclasses

    return render_template_context(
        "admin/presentations/schedule_inspector/compare.html",
        record1=record1,
        record2=record2,
        text=text,
        url=url,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
    )


@admin.route("/do_schedule_compare_ajax/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_schedule_compare_ajax(id1, id2):
    record1: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id1)
    record2: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id2)

    if not validate_schedule_inspector(record1) or not validate_schedule_inspector(
        record2
    ):
        return jsonify({})

    if record1.owner_id != record2.owner_id:
        flash(
            "It is only possible to compare two schedules belonging to the same assessment. "
            'Schedule "{name1}" belongs to assessment "{assess1}", but schedule '
            '"{name2}" belongs to assessment "{assess2}"'.format(
                name1=record1.name,
                name2=record2.name,
                assess1=record1.owner.name,
                assess2=record2.owner.name,
            )
        )
        return jsonify({})

    if not validate_assessment(record1.owner):
        return jsonify({})

    if not record1.finished:
        if record1.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting '
                "manual upload.".format(name=record1.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for comparison because it has not yet '
                "terminated.".format(name=record1.name),
                "error",
            )
        return jsonify({})

    if not record1.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record1.name),
            "info",
        )
        return jsonify({})

    if not record2.finished:
        if record2.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting '
                "manual upload.".format(name=record2.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for comparison because it has not yet '
                "terminated.".format(name=record2.name),
                "error",
            )
        return jsonify({})

    if not record2.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record2.name),
            "info",
        )
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    flag, pclass_value = is_integer(pclass_filter)

    pairs = pair_slots(record1.ordered_slots, record2.ordered_slots, flag, pclass_value)

    return ajax.admin.compare_schedule_data(pairs, record1.id, record2.id)


@admin.route("/publish_schedule/<int:id>")
@roles_required("root")
def publish_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for publication because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for publication because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if record.deployed:
        flash(
            'Schedule "{name}" is deployed and is not available to be published.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    try:
        record.published = True
        db.session.commit()
    except SQLAlchemyError as e:
        db.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not publish schedule "{record.name}" because of a database error. '
            "Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/unpublish_schedule/<int:id>")
@roles_required("root")
def unpublish_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                f'Schedule "{record.name}" is not yet available for unpublication because it is still awaiting '
                "manual upload.",
                "error",
            )
        else:
            flash(
                f'Schedule "{record.name}" is not yet available for unpublication because it has not yet '
                "terminated.",
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            f'Schedule "{record.name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared with convenors.",
            "info",
        )
        return redirect(redirect_url())

    try:
        record.published = False
        db.session.commit()
    except SQLAlchemyError as e:
        db.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not unpublish schedule "{record.name}" because of a database error. '
            "Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/publish_schedule_submitters/<int:id>")
@roles_required("root")
def publish_schedule_submitters(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for sharing with submitters because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for sharing with submitters because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    task_id = register_task(
        "Send schedule to submitters",
        owner=current_user,
        description='Email details of schedule "{name}" to submitters'.format(
            name=record.name
        ),
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.scheduling.publish_to_submitters"]

    task.apply_async(args=(id, current_user.id, task_id), task_id=task_id)

    return redirect(redirect_url())


@admin.route("/publish_schedule_assessors/<int:id>")
@roles_required("root")
def publish_schedule_assessors(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for sharing with assessors because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for sharing with assessors because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    task_id = register_task(
        "Send draft schedule to assessors",
        owner=current_user,
        description='Email details of schedule "{name}" to assessors'.format(
            name=record.name
        ),
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.scheduling.publish_to_assessors"]

    task.apply_async(args=(id, current_user.id, task_id), task_id=task_id)

    return redirect(redirect_url())


@admin.route("/deploy_schedule/<int:id>")
@roles_required("root")
def deploy_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if record.owner.is_deployed:
        flash(
            f'The assessment "{record.name}" already has a deployed schedule. Only one schedule can be deployed at a time.',
            "info",
        )

    if not record.finished:
        if record.awaiting_upload:
            flash(
                f'Schedule "{record.name}" is not yet available for deployment because it is still awaiting manual upload.',
                "error",
            )
        else:
            flash(
                f'Schedule "{record.name}" is not available for deployment because it has not yet terminated.',
                "info",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            f'Schedule "{record.name}" did not yield an usable solution and is not available for deployment.',
            "info",
        )
        return redirect(redirect_url())

    try:
        record.deployed = True
        record.published = False
        db.session.commit()
    except SQLAlchemyError as e:
        db.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not deploy schedule "{record.name}" because of a database error. '
            "Please contact a system administrator",
            "error",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    deploy_task = celery.tasks["app.tasks.deploy_schedule.deploy_schedule"]

    tk_name = f'Deploy schedule "{record.name}"'
    tk_description = "Populate presentation assessor roles for deployed schedule"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        deploy_task.si(record.id, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/undeploy_schedule/<int:id>")
@roles_required("root")
def undeploy_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                f'Schedule "{record.name}" is not yet available for undeployment because it is still awaiting manual upload.',
                "error",
            )
        else:
            flash(
                f'Schedule "{record.name}" is not available for undeployment because it has not yet terminated.',
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            f'Schedule "{record.name}" did not yield an usable solution and is not available for deployment.',
            "info",
        )
        return redirect(redirect_url())

    if not record.is_revokable:
        flash(
            f'Schedule "{record.name}" is not revokable. This may be because some scheduled slots are in the past, or because some feedback has already been entered.',
            "error",
        )

    try:
        record.deployed = False
        db.session.commit()
    except SQLAlchemyError as e:
        db.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not revoke deployment of schedule "{record.name}" because of a database error. '
            "Please contact a system administrator",
            "error",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    undeploy_task = celery.tasks["app.tasks.deploy_schedule.undeploy_schedule"]

    tk_name = f'Undeploy schedule "{record.name}"'
    tk_description = "Remove presentation assessor roles for undeployed schedule"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        undeploy_task.si(record.id, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/schedule_view_sessions/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_sessions(id):
    """
    Sessions view in schedule inspector
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                f'Schedule "{record.name}" is not yet available for inspection because it is still awaiting manual upload.',
                "error",
            )
        else:
            flash(
                f'Schedule "{record.name}" is not yet available for inspection because it has not yet terminated.',
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            f'Schedule "{record.name}" is not available for inspection because it did not yield an optimal solution.',
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    building_filter, pclass_filter, room_filter, session_filter = (
        _store_schedule_filters()
    )

    pclasses = record.available_pclasses
    buildings = record.available_buildings
    rooms = record.available_rooms
    sessions = record.available_sessions

    return render_template_context(
        "admin/presentations/schedule_inspector/sessions.html",
        pane="sessions",
        record=record,
        pclasses=pclasses,
        buildings=buildings,
        rooms=rooms,
        sessions=sessions,
        pclass_filter=pclass_filter,
        building_filter=building_filter,
        room_filter=room_filter,
        session_filter=session_filter,
        text=text,
        url=url,
    )


@admin.route("/schedule_view_faculty/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_faculty(id):
    """
    Faculty view in schedule inspector
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                f'Schedule "{record.name}" is not yet available for inspection because it is still awaiting manual upload.',
                "error",
            )
        else:
            flash(
                f'Schedule "{record.name}" is not yet available for inspection because it has not yet terminated.',
                "error",
            )

        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            f'Schedule "{record.name}" is not available for inspection because it did not yield an optimal solution.',
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    building_filter, pclass_filter, room_filter, session_filter = (
        _store_schedule_filters()
    )

    pclasses = record.available_pclasses
    buildings = record.available_buildings
    rooms = record.available_rooms
    sessions = record.available_sessions

    return render_template_context(
        "admin/presentations/schedule_inspector/faculty.html",
        pane="faculty",
        record=record,
        pclasses=pclasses,
        buildings=buildings,
        rooms=rooms,
        sessions=sessions,
        pclass_filter=pclass_filter,
        building_filter=building_filter,
        room_filter=room_filter,
        session_filter=session_filter,
        text=text,
        url=url,
    )


def _store_schedule_filters():
    pclass_filter = request.args.get("pclass_filter")
    building_filter = request.args.get("building_filter")
    room_filter = request.args.get("room_filter")
    session_filter = request.args.get("session_filter")

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_pclass_filter"):
        pclass_filter = session["admin_pclass_filter"]

    if pclass_filter is not None:
        session["admin_pclass_filter"] = pclass_filter

    if building_filter is None and session.get("admin_building_filter"):
        building_filter = session["admin_building_filter"]

    if building_filter is not None:
        session["admin_building_filter"] = building_filter

    if room_filter is None and session.get("admin_room_filter"):
        building_filter = session["admin_room_filter"]

    if room_filter is not None:
        session["admin_room_filter"] = room_filter

    if session_filter is None and session.get("admin_session_filter"):
        session_filter = session["admin_session_filter"]

    if session_filter is not None:
        session["admin_session_filter"] = session_filter

    return building_filter, pclass_filter, room_filter, session_filter


@admin.route("/schedule_view_sessions_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_sessions_ajax(id):
    """
    AJAX data point for Sessions view in Schedule inspector
    """
    if not validate_using_assessment():
        return jsonify({})

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    pclass_filter = request.args.get("pclass_filter")
    building_filter = request.args.get("building_filter")
    room_filter = request.args.get("room_filter")
    session_filter = request.args.get("session_filter")

    # now want to extract all slots from 'record' that satisfy the filters
    slots = record.slots
    joined_room = False

    flag, session_value = is_integer(session_filter)
    if flag:
        slots = slots.filter_by(session_id=session_value)

    flag, building_value = is_integer(building_filter)
    if flag:
        slots = slots.join(Room, Room.id == ScheduleSlot.room_id).filter(
            Room.building_id == building_value
        )
        joined_room = True

    flag, room_value = is_integer(room_filter)
    if flag:
        if not joined_room:
            slots = slots.join(Room, Room.id == ScheduleSlot.room_id)
        slots = slots.filter(Room.id == room_value)

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        slots = [t for t in slots.all() if t.has_pclass(pclass_value)]
    else:
        slots = slots.all()

    return ajax.admin.schedule_view_sessions(slots, record, url=url, text=text)


@admin.route("/schedule_view_faculty_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_faculty_ajax(id):
    """
    AJAX data point for Faculty view in Schedule inspector
    """
    if not validate_using_assessment():
        return jsonify({})

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    pclass_filter = request.args.get("pclass_filter")
    building_filter = request.args.get("building_filter")
    room_filter = request.args.get("room_filter")
    session_filter = request.args.get("session_filter")

    assessors = []
    for assessor in record.owner.ordered_assessors:
        slots = record.get_faculty_slots(assessor.faculty.id)
        joined_room = False

        flag, session_value = is_integer(session_filter)
        if flag:
            slots = slots.filter_by(session_id=session_value)

        flag, building_value = is_integer(building_filter)
        if flag:
            slots = slots.join(Room, Room.id == ScheduleSlot.room_id).filter(
                Room.building_id == building_value
            )
            joined_room = True

        flag, room_value = is_integer(room_filter)
        if flag:
            if not joined_room:
                slots = slots.join(Room, Room.id == ScheduleSlot.room_id)
            slots = slots.filter(Room.id == room_value)

        flag, pclass_value = is_integer(pclass_filter)
        if flag:
            slots = [t for t in slots.all() if t.has_pclass(pclass_value)]
        else:
            slots = slots.all()

        assessors.append((assessor, slots))

    return ajax.admin.schedule_view_faculty(assessors, record, url=url, text=text)


@admin.route("/schedule_delete_slot/<int:id>")
@roles_accepted("root", "admin", "faculty")
def schedule_delete_slot(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not slot.is_empty:
        flash("This schedule slot cannot be deleted because it is not empty.", "error")
        return redirect(redirect_url())

    try:
        db.session.delete(slot)
        db.session.commit()
    except SQLAlchemyError as e:
        db.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove this session because of a database error. "
            "Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/schedule_adjust_assessors/<int:id>")
@roles_accepted("root", "admin", "faculty")
def schedule_adjust_assessors(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                f'Schedule "{record.name}" is not yet available for inspection because it is still awaiting manual upload.',
                "error",
            )
        else:
            flash(
                f'Schedule "{record.name}" is not yet available for inspection because it has not yet terminated.',
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            f'Schedule "{record.name}" is not available for inspection because it did not yield an optimal solution.',
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    return render_template_context(
        "admin/presentations/schedule_inspector/assign_assessors.html",
        url=url,
        text=text,
        slot=slot,
        rec=record,
    )


@admin.route("/schedule_assign_assessors_ajax/<int:id>")
@roles_accepted("root", "admin", "faculty")
def schedule_assign_assessors_ajax(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    candidates = []
    pclass: ProjectClass = slot.pclass

    for assessor in record.owner.ordered_assessors:
        assessor: AssessorAttendanceData
        # candidate assessors should be available in this slot
        if slot.session.faculty_available(
            assessor.faculty_id
        ) or slot.session.faculty_ifneeded(assessor.faculty_id):
            is_candidate = True

            if pclass is not None:
                # assessors should also be enrolled for the project class corresponding to this slot
                enrolment = assessor.faculty.get_enrollment_record(pclass.id)
                available = (
                    enrolment is not None
                    and enrolment.presentations_state
                    == EnrollmentRecord.PRESENTATIONS_ENROLLED
                )

                if not available:
                    is_candidate = False

            # check whether this faculty has any existing assignments in this session
            num_existing = get_count(
                db.session.query(ScheduleSlot).filter(
                    ScheduleSlot.owner_id == record.id,
                    ScheduleSlot.session_id == slot.session_id,
                    ScheduleSlot.assessors.any(id=assessor.faculty_id),
                )
            )

            # if not, can offer them as a candidate
            if num_existing > 0:
                is_candidate = False

            if is_candidate:
                slots: List[ScheduleSlot] = record.get_faculty_slots(
                    assessor.faculty_id
                ).all()

                score = len(slots)

                if not assessor.confirmed:
                    score += 10000

                if not slot.assessor_has_overlap(assessor.faculty_id):
                    score += 100

                candidates.append((assessor, slots, score))

    return ajax.admin.assign_assessor_data(candidates, slot, url=url, text=text)


@admin.route("/schedule_adjust_assessors/<int:slot_id>/<int:fac_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_attach_assessor(slot_id, fac_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for inspection because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" is not available for inspection because it did not yield an optimal solution.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not record.owner.includes_faculty(fac_id):
        flash(
            "The specified faculty member is not attached to this assessment", "error"
        )
        return redirect(redirect_url())

    item: AssessorAttendanceData = record.owner.assessors_query.filter(
        AssessorAttendanceData.faculty_id == fac_id
    ).first()

    if item is None:
        flash("Could not attach this faculty member due to a database error", "error")
        return redirect(redirect_url())

    if get_count(slot.assessors.filter_by(id=item.faculty_id)) == 0:
        fac: FacultyData = item.faculty
        user: User = fac.user
        slot.assessors.append(fac)

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                f'Could not attach assessor "{user.name}" to this slot in schedule "{record.name}" because of a database error. '
                "Please contact a system administrator",
                "error",
            )

    return redirect(redirect_url())


@admin.route("/schedule_remove_assessors/<int:slot_id>/<int:fac_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_remove_assessor(slot_id, fac_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not record.owner.includes_faculty(fac_id):
        flash(
            "The specified faculty member is not attached to this assessment", "error"
        )
        return redirect(redirect_url())

    item = record.owner.assessors_query.filter(
        AssessorAttendanceData.faculty_id == fac_id
    ).first()

    if item is None:
        flash("Could not attach this faculty member due to a database error", "error")
        return redirect(redirect_url())

    if get_count(slot.assessors.filter_by(id=item.faculty_id)) > 0:
        slot.assessors.remove(item.faculty)

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        db.session.commit()

    return redirect(redirect_url())


@admin.route("/schedule_adjust_submitter/<int:slot_id>/<int:talk_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_adjust_submitter(slot_id, talk_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    talk = SubmissionRecord.query.get_or_404(talk_id)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    return render_template_context(
        "admin/presentations/schedule_inspector/assign_presentation.html",
        url=url,
        text=text,
        slot=slot,
        rec=record,
        talk=talk,
    )


@admin.route("/schedule_assign_submitter_ajax/<int:slot_id>/<int:talk_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_assign_submitter_ajax(slot_id, talk_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    talk = SubmissionRecord.query.get_or_404(talk_id)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    pclass: ProjectClass = slot.pclass

    def check_valid(s):
        if s.pclass is not None and pclass is not None:
            if s.pclass.id != pclass.id:
                return False

        return s.session.submitter_available(talk.id) and s.id != slot.id

    slots = [s for s in record.slots.all() if check_valid(s)]

    return ajax.admin.assign_submitter_data(slots, slot, talk, url=url, text=text)


@admin.route("/schedule_move_submitter/<int:old_id>/<int:new_id>/<int:talk_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_move_submitter(old_id, new_id, talk_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    old_slot: ScheduleSlot = ScheduleSlot.query.get_or_404(old_id)
    new_slot: ScheduleSlot = ScheduleSlot.query.get_or_404(new_id)
    record: ScheduleAttempt = old_slot.owner  # = ScheduleAttempt

    if old_slot.owner_id != new_slot.owner_id:
        flash(
            "Cannot move specified talk because destination slot does not belong to the same ScheduleAttempt instance.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    talk = SubmissionRecord.query.get_or_404(talk_id)

    if not record.owner.includes_submitter(talk.id):
        flash(
            "The specified submitting student is not attached to this assessment",
            "error",
        )
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if get_count(old_slot.talks.filter_by(id=talk.id)) > 0:
        old_slot.talks.remove(talk)

    if get_count(new_slot.talks.filter_by(id=talk.id)) == 0:
        new_slot.talks.append(talk)

    record.last_edit_id = current_user.id
    record.last_edit_timestamp = datetime.now()

    db.session.commit()

    return redirect(
        url_for(
            "admin.schedule_adjust_submitter",
            slot_id=new_id,
            talk_id=talk_id,
            url=url,
            text=text,
        )
    )


@admin.route("/schedule_move_room/<int:slot_id>/<int:room_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_move_room(slot_id, room_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    room: Room = Room.query.get_or_404(room_id)

    record = slot.owner

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    available_rooms = slot.alternative_rooms
    if room in available_rooms:
        slot.room_id = room.id
        db.session.commit()

    else:
        flash(
            'Cannot assign venue "{room}" to this slot because it is unavailable, or does not meet '
            "the required criteria.".format(room=room.full_name)
        )

    return redirect(redirect_url())


@admin.route("/assessment_manage_attendees/<int:id>")
@roles_required("root")
def assessment_manage_attendees(id):
    """
    Manage student attendees for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter")

    if pclass_filter is None and session.get("attendees_pclass_filter"):
        pclass_filter = session["attendees_pclass_filter"]

    if pclass_filter is not None:
        session["attendees_pclass_filter"] = pclass_filter

    attend_filter = request.args.get("attend_filter")

    if attend_filter is None and session.get("attendees_attend_filter"):
        attend_filter = session["attendees_attend_filter"]

    if attend_filter is not None:
        session["attendees_attend_filter"] = attend_filter

    pclasses = data.available_pclasses

    return render_template_context(
        "admin/presentations/manage_attendees.html",
        assessment=data,
        pclass_filter=pclass_filter,
        attend_filter=attend_filter,
        pclasses=pclasses,
    )


@admin.route(
    "/merge_change_schedule/<int:source_id>/<int:target_id>/<int:source_sched>/<int:target_sched>"
)
@roles_accepted("root", "faculty", "admin")
def merge_change_schedule(source_id, target_id, source_sched, target_sched):
    """
    Makes target into a copy of source
    :param source_id:
    :param target_id:
    :return:
    """
    if source_id is not None:
        source = ScheduleSlot.query.get_or_404(source_id)
    else:
        source = None

    if target_id is not None:
        target = ScheduleSlot.query.get_or_404(target_id)
    else:
        target = None

    source_schedule = ScheduleAttempt.query.get_or_404(source_sched)
    target_schedule = ScheduleAttempt.query.get_or_404(target_sched)

    if not validate_schedule_inspector(
        source_schedule
    ) or not validate_schedule_inspector(target_schedule):
        return redirect(redirect_url())

    # check that source and target schedules are owned by the same assessent
    if source_schedule.owner_id != target_schedule.owner_id:
        flash(
            "It is only possible to merge two schedules belonging to the same assessment. "
            'Schedule "{name1}" belongs to assessment "{assess1}", but schedule '
            '"{name2}" belongs to assessment "{assess2}"'.format(
                name1=source_schedule.name,
                name2=target_schedule.name,
                assess1=source_schedule.owner.name,
                assess2=target_schedule.owner.name,
            )
        )
        return redirect(redirect_url())

    if not validate_assessment(source_schedule.owner):
        return redirect(redirect_url())

    if not source_schedule.finished:
        if source_schedule.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for merging because it is still awaiting manual upload.'.format(
                    name=source_schedule.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for merging because it has not yet terminated.'.format(
                    name=source_schedule.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not source_schedule.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for merging.".format(name=source_schedule.name),
            "info",
        )
        return redirect(redirect_url())

    if target_schedule is not None and not target_schedule.finished:
        if target_schedule.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for merging because it is still awaiting manual upload.'.format(
                    name=target_schedule.name
                ),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for merging because it has not yet terminated.'.format(
                    name=target_schedule.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if target_schedule is not None and not target_schedule.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for merging.".format(name=target_schedule.name),
            "info",
        )
        return redirect(redirect_url())

    if source is None and target is not None:
        # remove target session
        db.session.delete(target)

    elif target is None and source is not None:
        # find first free occupancy label for this room in the target schedule
        max_label = (
            db.session.query(func.max(ScheduleSlot.occupancy_label))
            .filter_by(
                owner_id=target_schedule.id,
                session_id=source.session_id,
                room_id=source.room_id,
            )
            .scalar()
        )

        if max_label is None:
            slot_label = 1
        else:
            slot_label = int(max_label) + 1

        # create new target slot
        data = ScheduleSlot(
            owner_id=target_schedule.id,
            session_id=source.session_id,
            room_id=source.room_id,
            assessors=source.assessors,
            talks=source.talks,
            occupancy_label=slot_label,
            original_assessors=source.original_assessors,
            original_talks=source.original_talks,
        )
        db.session.add(data)

    else:
        target.session_id = source.session_id
        target.room_id = source.room_id
        target.assessors = source.assessors
        target.talks = source.talks

    target_schedule.last_edit_id = current_user.id
    target_schedule.last_edit_timestamp = datetime.now()

    db.session.commit()

    return redirect(redirect_url())
