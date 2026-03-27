#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from datetime import date, datetime, timedelta
from math import pi

from bokeh.embed import components
from bokeh.models import Label
from bokeh.plotting import figure
from celery import chain, group
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
    login_required,
    roles_accepted,
    roles_required,
)
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

import app.ajax as ajax

from ..database import db
from ..limiter import limiter
from ..models import (
    BackupLabel,
    BackupRecord,
    CrontabSchedule,
    DatabaseSchedulerEntry,
    EmailLog,
    EmailNotification,
    IntervalSchedule,
    MainConfig,
    MatchingAttempt,
    MessageOfTheDay,
    Notification,
    ProjectClass,
    StudentData,
    TaskRecord,
    Tenant,
    User,
    WorkflowLogEntry,
)
from ..shared.backup import (
    compute_current_backup_count,
    compute_current_backup_size,
    create_new_backup_labels,
    get_backup_config,
    remove_backup,
    set_backup_config,
)
from ..shared.context.global_context import render_template_context
from ..shared.context.matching import (
    get_ready_to_match_data,
)
from ..shared.context.rollover import get_rollover_data
from ..shared.formatters import format_size
from ..shared.internal_redis import get_redis
from ..shared.utils import (
    get_current_year,
    get_main_config,
    home_dashboard,
    redirect_url,
)
from ..shared.validators import (
    validate_is_admin_or_convenor,
)
from ..shared.workflow_logging import log_db_commit
from ..task_queue import progress_update, register_task
from ..tools import ServerSideSQLHandler
from . import admin
from .forms import (
    AddCrontabScheduledTask,
    AddIntervalScheduledTask,
    AddMessageFormFactory,
    BackupManageForm,
    EditBackupOptionsForm,
    EditCrontabScheduledTask,
    EditIntervalScheduledTask,
    EditMessageFormFactory,
    EmailLogForm,
    ManualBackupForm,
    ScheduleTypeForm,
)


@admin.route("/confirm_global_rollover")
@roles_required("root")
def confirm_global_rollover():
    """
    Show confirmation box for global advance of academic year
    :return:
    """
    data = get_rollover_data()

    if not data["rollover_ready"]:
        flash(
            "Can not initiate a rollover of the academic year because no project classes are ready",
            "info",
        )
        return redirect(redirect_url())

    if data["rollover_in_progress"]:
        flash(
            "Can not initiate a rollover of the academic year because one is already in progress",
            "info",
        )
        return redirect(redirect_url())

    next_year = get_current_year() + 1

    title = "Global rollover to {yeara}&ndash;{yearb}".format(
        yeara=next_year, yearb=next_year + 1
    )
    panel_title = "Global rollover of academic year to {yeara}&ndash;{yearb}".format(
        yeara=next_year, yearb=next_year + 1
    )
    action_url = url_for("admin.perform_global_rollover")
    message = (
        "<p><strong>Please confirm that you wish to advance the global academic year to "
        "{yeara}&ndash;{yearb}.</strong></p>"
        '<p class="mt-1">No project classes will be modified. Project class rollover must be initiated '
        "by individual module convenors.</p>"
        '<p class="mt-1">After the current academic year has been incremented, '
        "a routine database maintenance process will be "
        "run.</p>"
        '<p class="mt-2">This action cannot be undone.</p>'.format(
            yeara=next_year, yearb=next_year + 1
        )
    )
    submit_label = "Rollover to {yra}&ndash;{yrb}".format(
        yra=next_year, yrb=next_year + 1
    )

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_global_rollover")
@roles_required("root")
def perform_global_rollover():
    """
    Globally advance the academic year
    (doesn't actually do anything directly; the complex parts of rollover are done
    for each project class at a time decided by its convenor or an administrator)
    :return:
    """
    data = get_rollover_data()
    current_config = get_main_config()

    if not data["rollover_ready"]:
        flash(
            "Can not initiate a rollover of the academic year because no project classes are ready",
            "info",
        )
        return redirect(redirect_url())

    if data["rollover_in_progress"]:
        flash(
            "Can not initiate a rollover of the academic year because one is already in progress",
            "info",
        )
        return redirect(redirect_url())

    current_year = get_current_year()
    next_year = current_year + 1

    try:
        # insert new MainConfig instance for next year, rolling over most current settings
        new_year = MainConfig(
            year=next_year,
            enable_canvas_sync=current_config.enable_canvas_sync,
            canvas_url=current_config.canvas_url,
        )
        db.session.add(new_year)
        log_db_commit(
            f"Created new MainConfig record for academic year {next_year}-{next_year + 1} during global rollover",
            user=current_user,
        )

    except SQLAlchemyError as e:
        flash(
            "Could not complete rollover due to database error. Please check the logs.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    else:
        tk_name = "Perform global rollover to academic year {yra}-{yrb}".format(
            yra=next_year, yrb=next_year + 1
        )
        tk_description = "Perform global rollover"
        uuid = register_task(tk_name, owner=current_user, description=tk_description)

        celery = current_app.extensions["celery"]

        init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
        final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
        error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

        # need to perform a maintenance cycle to update students' academic years
        maintenance_cycle = celery.tasks["app.tasks.maintenance.maintenance"]

        # TODO: pruning of matching attempts must now be scheduled elsewhere in the lifecycle --
        #  this has still to be done

        # schedule all parts of the rollover+maintenance cycle
        seq = chain(
            init.si(uuid, tk_name),
            maintenance_cycle.si(),
            final.si(uuid, tk_name, current_user.id),
        ).on_error(error.si(uuid, tk_name, current_user.id))
        seq.apply_async(task_id=uuid)

    return home_dashboard()


@admin.route("/email_log")
@roles_accepted("root", "view_email")
def email_log():
    """
    Display a log of sent emails
    :return:
    """
    if current_user.has_role("root"):
        form = EmailLogForm(request.form)
    else:
        form = None

    if form is not None and form.validate_on_submit():
        if form.delete_age.data is True:
            return redirect(
                url_for("admin.confirm_delete_email_cutoff", cutoff=(form.weeks.data))
            )

    return render_template_context("admin/email_log.html", form=form)


@limiter.exempt
@admin.route("/email_log_ajax", methods=["POST"])
@roles_accepted("root", "view_email")
def email_log_ajax():
    """
    Ajax data point for email log
    :return:
    """
    base_query = db.session.query(EmailLog)

    # set up columns for server-side processing
    recipient = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collection": EmailLog.recipients,
        "search_collation": "utf8_general_ci",
    }
    address = {
        "search": User.email,
        "search_collection": EmailLog.recipients,
        "search_collation": "utf8_general_ci",
    }
    date = {
        "search": func.date_format(EmailLog.send_date, "%a %d %b %Y %H:%M:%S"),
        "order": EmailLog.send_date,
    }
    subject = {
        "search": EmailLog.subject,
        "order": EmailLog.subject,
        "search_collaboration": "utf8_general_ci",
    }

    columns = {
        "recipient": recipient,
        "address": address,
        "date": date,
        "subject": subject,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.email_log_data)


@admin.route("/display_email/<int:id>")
@roles_accepted("root", "view_email")
def display_email(id):
    """
    Display a specific email
    :param id:
    :return:
    """
    email = EmailLog.query.get_or_404(id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if text is None and url is None:
        url = url_for("admin.email_log")
        text = "email log"

    return render_template_context(
        "admin/display_email.html", email=email, text=text, url=url
    )


@admin.route("/delete_email/<int:id>")
@roles_required("root")
def delete_email(id):
    """
    Delete an email
    :param id:
    :return:
    """
    email = EmailLog.query.get_or_404(id)

    try:
        db.session.delete(email)
        log_db_commit(
            f"Deleted email log record #{id}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not delete email because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for("admin.email_log"))


@admin.route("/confirm_delete_all_emails")
@roles_required("root")
def confirm_delete_all_emails():
    """
    Show confirmation box to delete all emails
    :return:
    """

    title = "Confirm delete"
    panel_title = "Confirm delete of all emails retained in log"

    action_url = url_for("admin.delete_all_emails")
    message = (
        "<p>Please confirm that you wish to delete all emails retained in the log.</p>"
        "<p>This action cannot be undone.</p>"
    )
    submit_label = "Delete all"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/delete_all_emails")
@roles_required("root")
def delete_all_emails():
    """
    Delete all emails stored in the log
    :return:
    """

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    delete_email = celery.tasks["app.tasks.prune_email.delete_all_email"]

    tk_name = "Manual delete email"
    tk_description = "Manually delete all email"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        delete_email.si(),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.email_log"))


@admin.route("/confirm_delete_email_cutoff/<int:cutoff>")
@roles_required("root")
def confirm_delete_email_cutoff(cutoff):
    """
    Show confirmation box to delete emails with a cutoff
    :return:
    """

    pl = "s"
    if cutoff == 1:
        pl = ""

    title = "Confirm delete"
    panel_title = "Confirm delete all emails older than {c} week{pl}".format(
        c=cutoff, pl=pl
    )

    action_url = url_for("admin.delete_email_cutoff", cutoff=cutoff)
    message = (
        "<p>Please confirm that you wish to delete all emails older than {c} week{pl}.</p>"
        "<p>This action cannot be undone.</p>".format(c=cutoff, pl=pl)
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/delete_email_cutoff/<int:cutoff>")
@roles_required("root")
def delete_email_cutoff(cutoff):
    """
    Delete all emails older than the given cutoff
    :param cutoff:
    :return:
    """

    pl = "s"
    if cutoff == 1:
        pl = ""

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    prune_email = celery.tasks["app.tasks.prune_email.prune_email_log"]

    tk_name = "Manual delete email"
    tk_description = "Manually delete email older than {c} week{pl}".format(
        c=cutoff, pl=pl
    )
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        prune_email.si(duration=cutoff, interval="weeks"),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.email_log"))


@admin.route("/scheduled_email")
@roles_accepted("root", "view_email")
def scheduled_email():
    """
    Display scheduled outgoing email
    :return:
    """
    return render_template_context("admin/scheduled_email.html")


@admin.route("/scheduled_email_ajax", methods=["POST"])
@roles_accepted("root", "view_email")
def scheduled_email_ajax():
    """
    AJAX data point for scheduled email list
    :return:
    """
    base_query = db.session.query(EmailNotification).join(
        User, User.id == EmailNotification.owner_id
    )

    recipient = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    timestamp = {
        "search": func.date_format(EmailNotification.timestamp, "%a %d %b %Y %H:%M:%S"),
        "order": EmailNotification.timestamp,
    }
    type = {"order": EmailNotification.event_type}

    columns = {"recipient": recipient, "timestamp": timestamp, "type": type}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.scheduled_email)


@admin.route("/hold_notification/<int:eid>")
@roles_accepted("root", "view_email")
def hold_notification(eid):
    """
    Mark an outgoing notification as held
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    notification.held = True

    try:
        log_db_commit(
            f"Marked email notification #{eid} as held",
            user=current_user,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not mark notification as held because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/release_notification/<int:eid>")
@roles_accepted("root", "view_email")
def release_notification(eid):
    """
    Mark an outgoing notification as not held (released)
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    notification.held = False

    try:
        log_db_commit(
            f"Released email notification #{eid} from held status",
            user=current_user,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not mark notification as released because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/delete_notification/<int:eid>")
@roles_accepted("root", "view_email")
def delete_notification(eid):
    """
    Mark an outgoing notification as held
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = "Confirm delete"
    panel_title = "Confirm delete scheduled notification"

    action_url = url_for("admin.do_delete_notification", eid=eid)
    message = (
        "<p>Please confirm that you wish to delete a scheduled email notification to "
        '<i class="fas fa-user-circle"></i> <strong>{name}</strong></p>'
        "<p>This action cannot be undone.</p>".format(name=notification.owner.name)
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        url=url,
    )


@admin.route("/do_delete_notification/<int:eid>")
@roles_accepted("root", "view_email")
def do_delete_notification(eid):
    """
    Delete an email notification
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.scheduled_email")

    try:
        db.session.delete(notification)
        log_db_commit(
            f"Deleted scheduled email notification #{eid}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not delete notification because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/edit_messages")
@roles_accepted("faculty", "admin", "root")
def edit_messages():
    """
    Edit message-of-the-day type messages
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    return render_template_context("admin/edit_messages.html")


@admin.route("/messages_ajax")
@roles_accepted("faculty", "admin", "root")
def messages_ajax():
    """
    Ajax data point for message-of-the-day list
    :return:
    """

    if not validate_is_admin_or_convenor():
        return jsonify({})

    if current_user.has_role("admin") or current_user.has_role("root"):
        # admin users can edit all messages
        messages = MessageOfTheDay.query.all()

    else:
        # convenors can only see their own messages
        messages = MessageOfTheDay.query.filter_by(user_id=current_user.id).all()

    return ajax.admin.messages_data(messages)


@admin.route("/add_message", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_message():
    """
    Add a new message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    # convenors can't show login-screen messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        AddMessageForm = AddMessageFormFactory(convenor_editing=True)
        form = AddMessageForm(request.form)
    else:
        AddMessageForm = AddMessageFormFactory(convenor_editing=False)
        form = AddMessageForm(request.form)

    if form.validate_on_submit():
        if "show_login" in form._fields:
            show_login = form._fields.get("show_login").data
        else:
            show_login = False

        data = MessageOfTheDay(
            user_id=current_user.id,
            issue_date=datetime.now(),
            show_students=form.show_students.data,
            show_faculty=form.show_faculty.data,
            show_office=form.show_office.data,
            show_login=show_login,
            dismissible=form.dismissible.data,
            title=form.title.data,
            body=form.body.data,
            project_classes=form.project_classes.data,
        )
        db.session.add(data)

        try:
            log_db_commit(
                f"Added new broadcast message '{form.title.data}'",
                user=current_user,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not add message because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_messages"))

    return render_template_context(
        "admin/edit_message.html", form=form, title="Add new broadcast message"
    )


@admin.route("/edit_message/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_message(id):
    """
    Edit a message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data: MessageOfTheDay = MessageOfTheDay.query.get_or_404(id)

    # convenors can't show login-screen messages and can only edit their own messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if data.user_id != current_user.id:
            flash("Only administrative users can edit messages that they do not own")
            return home_dashboard()

        EditMessageForm = EditMessageFormFactory(convenor_editing=True)
        form = EditMessageForm(obj=data)

    else:
        EditMessageForm = EditMessageFormFactory(convenor_editing=False)
        form = EditMessageForm(obj=data)

    if form.validate_on_submit():
        if "show_login" in form._fields:
            show_login = form._fields.get("show_login").data
        else:
            show_login = False

        data.show_students = form.show_students.data
        data.show_faculty = form.show_faculty.data
        data.show_office = form.show_office.data
        data.show_login = show_login
        data.dismissible = form.dismissible.data
        data.title = form.title.data
        data.body = form.body.data
        data.project_classes = form.project_classes.data

        try:
            log_db_commit(
                f"Saved edits to broadcast message '{data.title}'",
                user=current_user,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save edited message because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_messages"))

    return render_template_context(
        "admin/edit_message.html",
        message=data,
        form=form,
        title="Edit broadcast message",
    )


@admin.route("/delete_message/<int:id>")
@roles_accepted("faculty", "admin", "root")
def delete_message(id):
    """
    Delete message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = MessageOfTheDay.query.get_or_404(id)

    # convenors can only delete their own messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if data.user_id != current_user.id:
            flash("Only administrative users can edit messages that are not their own.")
            return home_dashboard()

    db.session.delete(data)
    log_db_commit(
        f"Deleted broadcast message '{data.title}'",
        user=current_user,
    )

    return redirect(redirect_url())


@admin.route("/dismiss_message/<int:id>")
@login_required
def dismiss_message(id):
    """
    Record that the current user has dismissed a particular message
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    if current_user not in message.dismissed_by:
        message.dismissed_by.append(current_user)
        log_db_commit(
            f"Recorded dismissal of broadcast message #{id} by user",
            user=current_user,
        )

    return redirect(redirect_url())


@admin.route("/reset_dismissals/<int:id>")
@roles_accepted("faculty", "admin", "root")
def reset_dismissals(id):
    """
    Remove dismissals from a message (eg. we might want to do this after updating the text)
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    # convenors can only reset their own messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if message.user_id != current_user.id:
            flash(
                "Only administrative users can reset dismissals for messages that are not their own."
            )
            return home_dashboard()

    message.dismissed_by = []
    log_db_commit(
        f"Reset all dismissals for broadcast message #{id}",
        user=current_user,
    )

    return redirect(redirect_url())


@admin.route("/scheduled_tasks")
@roles_required("root")
def scheduled_tasks():
    """
    UI for scheduling periodic tasks (database backup, prune email log, etc.)
    :return:
    """

    return render_template_context("admin/scheduled_tasks.html")


@admin.route("/scheduled_ajax")
@roles_required("root")
def scheduled_ajax():
    """
    Ajax data source for scheduled periodic tasks
    :return:
    """

    tasks = db.session.query(DatabaseSchedulerEntry).all()
    return ajax.site.scheduled_task_data(tasks)


@admin.route("/add_scheduled_task", methods=["GET", "POST"])
@roles_required("root")
def add_scheduled_task():
    """
    Add a new scheduled task
    :return:
    """

    form = ScheduleTypeForm(request.form)

    if form.validate_on_submit():
        if form.type.data == "interval":
            return redirect(url_for("admin.add_interval_task"))

        elif form.type.data == "crontab":
            return redirect(url_for("admin.add_crontab_task"))

        else:
            flash(
                "The task type was not recognized. If this error persists, please contact the system administrator."
            )
            return redirect(url_for("admin.scheduled_tasks"))

    return render_template_context(
        "admin/scheduled_type.html", form=form, title="Select schedule type"
    )


@admin.route("/add_interval_task", methods=["GET", "POST"])
@roles_required("root")
def add_interval_task():
    """
    Add a new task specified by a simple interval
    :return:
    """

    form = AddIntervalScheduledTask(request.form)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(
            every=form.every.data, period=form.period.data
        ).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data, period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)
        now = datetime.now()

        data = DatabaseSchedulerEntry(
            name=form.name.data,
            owner_id=form.owner.data.id,
            task=form.task.data,
            interval_id=sch.id,
            crontab_id=None,
            args=args,
            kwargs=kwargs,
            queue=form.queue.data,
            exchange=None,
            routing_key=None,
            expires=form.expires.data,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            date_changed=now,
        )

        db.session.add(data)
        log_db_commit(
            f"Added new fixed-interval scheduled task '{form.name.data}'",
            user=current_user,
        )

        return redirect(url_for("admin.scheduled_tasks"))

    return render_template_context(
        "admin/edit_scheduled_task.html", form=form, title="Add new fixed-interval task"
    )


@admin.route("/add_crontab_task", methods=["GET", "POST"])
@roles_required("root")
def add_crontab_task():
    """
    Add a new task specified by a crontab
    :return:
    """

    form = AddCrontabScheduledTask(request.form)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(
            minute=form.minute.data,
            hour=form.hour.data,
            day_of_week=form.day_of_week.data,
            day_of_month=form.day_of_month.data,
            month_of_year=form.month_of_year.data,
        ).first()

        if sch is None:
            sch = CrontabSchedule(
                minute=form.minute.data,
                hour=form.hour.data,
                day_of_week=form.day_of_week.data,
                day_of_month=form.day_of_month.data,
                month_of_year=form.month_of_year.data,
            )
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)
        now = datetime.now()

        data = DatabaseSchedulerEntry(
            name=form.name.data,
            owner_id=form.owner.data.id,
            task=form.task.data,
            interval_id=None,
            crontab_id=sch.id,
            args=args,
            kwargs=kwargs,
            queue=form.queue.data,
            exchange=None,
            routing_key=None,
            expires=form.expires.data,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            date_changed=now,
        )

        db.session.add(data)
        log_db_commit(
            f"Added new crontab scheduled task '{form.name.data}'",
            user=current_user,
        )

        return redirect(url_for("admin.scheduled_tasks"))

    return render_template_context(
        "admin/edit_scheduled_task.html", form=form, title="Add new crontab task"
    )


@admin.route("/edit_interval_task/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_interval_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditIntervalScheduledTask(obj=data)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(
            every=form.every.data, period=form.period.data
        ).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data, period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.queue = form.queue.data
        data.interval_id = sch.id
        data.crontab_id = None
        data.args = args
        data.kwargs = kwargs
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        log_db_commit(
            f"Saved edits to fixed-interval scheduled task '{data.name}'",
            user=current_user,
        )

        return redirect(url_for("admin.scheduled_tasks"))

    else:
        if request.method == "GET":
            form.every.data = data.interval.every
            form.period.data = data.interval.period

    return render_template_context(
        "admin/edit_scheduled_task.html",
        task=data,
        form=form,
        title="Edit fixed-interval task",
    )


@admin.route("/edit_crontab_task/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_crontab_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditCrontabScheduledTask(obj=data)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(
            minute=form.minute.data,
            hour=form.hour.data,
            day_of_week=form.day_of_week.data,
            day_of_month=form.day_of_month.data,
            month_of_year=form.month_of_year.data,
        ).first()

        if sch is None:
            sch = CrontabSchedule(
                minute=form.minute.data,
                hour=form.hour.data,
                day_of_week=form.day_of_week.data,
                day_of_month=form.day_of_month.data,
                month_of_year=form.month_of_year.data,
            )
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.queue = form.queue.data
        data.interval_id = None
        data.crontab_id = sch.id
        data.args = args
        data.kwargs = kwargs
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        log_db_commit(
            f"Saved edits to crontab scheduled task '{data.name}'",
            user=current_user,
        )

        return redirect(url_for("admin.scheduled_tasks"))

    else:
        if request.method == "GET":
            form.minute.data = data.crontab.minute
            form.hour.data = data.crontab.hour
            form.day_of_week.data = data.crontab.day_of_week
            form.day_of_month.data = data.crontab.day_of_month
            form.month_of_year.data = data.crontab.month_of_year

    return render_template_context(
        "admin/edit_scheduled_task.html",
        task=data,
        form=form,
        title="Add new crontab task",
    )


@admin.route("/delete_scheduled_task/<int:id>")
@roles_required("root")
def delete_scheduled_task(id):
    """
    Remove an existing scheduled task
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    db.session.delete(task)
    log_db_commit(
        f"Deleted scheduled task '{task.name}'",
        user=current_user,
    )

    return redirect(redirect_url())


@admin.route("/activate_scheduled_task/<int:id>")
@roles_required("root")
def activate_scheduled_task(id):
    """
    Mark a scheduled task as active
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = True
    log_db_commit(
        f"Activated scheduled task '{task.name}'",
        user=current_user,
    )

    return redirect(redirect_url())


@admin.route("/deactivate_scheduled_task/<int:id>")
@roles_required("root")
def deactivate_scheduled_task(id):
    """
    Mark a scheduled task as inactive
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = False
    log_db_commit(
        f"Deactivated scheduled task '{task.name}'",
        user=current_user,
    )

    return redirect(redirect_url())


@admin.route("/launch_scheduled_task/<int:id>")
@roles_required("root")
def launch_scheduled_task(id):
    """
    Launch a specified task as a background task
    :param id:
    :return:
    """

    record = DatabaseSchedulerEntry.query.get_or_404(id)

    task_id = register_task(
        record.name, current_user, "Scheduled task launched from web user interface"
    )

    celery = current_app.extensions["celery"]
    tk = celery.tasks[record.task]

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, record.name),
        tk.signature(record.args, record.kwargs, immutable=True),
        final.si(task_id, record.name, current_user.id, notify=True),
    ).on_error(error.si(task_id, record.name, current_user.id))

    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/backups_overview", methods=["GET", "POST"])
@roles_required("root")
def backups_overview():
    """
    Generate the backup overview
    :return:
    """

    form = EditBackupOptionsForm(request.form)

    keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()
    limit, units = lim

    backup_count = compute_current_backup_count()
    backup_total_size = compute_current_backup_size()

    if backup_total_size is None:
        size = "(no backups currently held)"
    else:
        size = format_size(backup_total_size)

    if form.validate_on_submit():
        set_backup_config(
            form.keep_hourly.data,
            form.keep_daily.data,
            form.backup_limit.data,
            form.limit_units.data,
        )
        flash("Your new backup configuration has been saved", "success")

    else:
        if request.method == "GET":
            form.keep_hourly.data = keep_hourly
            form.keep_daily.data = keep_daily
            form.backup_limit.data = limit
            form.limit_units.data = units

    # if there are enough datapoints, generate some plots showing how the backup size is scaling with time
    if backup_count > 1:
        # extract lists of data points
        backup_dates = (
            db.session.query(BackupRecord.date).order_by(BackupRecord.date).all()
        )
        archive_size = (
            db.session.query(BackupRecord.archive_size)
            .order_by(BackupRecord.date)
            .all()
        )
        backup_size = (
            db.session.query(BackupRecord.backup_size).order_by(BackupRecord.date).all()
        )

        MB_SIZE = 1024 * 1024

        dates = [x[0] for x in backup_dates]
        arc_size = [x[0] / MB_SIZE for x in archive_size]
        bk_size = [x[0] / MB_SIZE for x in backup_size]

        archive_plot = figure(
            title="Archive size as a function of time",
            x_axis_label="Time of backup",
            x_axis_type="datetime",
            width=800,
            height=300,
        )
        archive_plot.sizing_mode = "scale_width"
        archive_plot.line(
            dates,
            arc_size,
            legend_label="archive size in Mb",
            line_color="blue",
            line_width=2,
        )
        archive_plot.toolbar.logo = None
        archive_plot.border_fill_color = None
        archive_plot.background_fill_color = "lightgrey"
        archive_plot.legend.location = "bottom_right"

        backup_plot = figure(
            title="Total backup size as a function of time",
            x_axis_label="Time of backup",
            x_axis_type="datetime",
            width=800,
            height=300,
        )
        backup_plot.sizing_mode = "scale_width"
        backup_plot.line(
            dates,
            bk_size,
            legend_label="backup size in Mb",
            line_color="red",
            line_width=2,
        )
        backup_plot.toolbar.logo = None
        backup_plot.border_fill_color = None
        backup_plot.background_fill_color = "lightgrey"
        backup_plot.legend.location = "bottom_right"

        archive_script, archive_div = components(archive_plot)
        backup_script, backup_div = components(backup_plot)

    else:
        archive_script = None
        archive_div = None
        backup_script = None
        backup_div = None

    # extract data on last few backups
    last_batch = BackupRecord.query.order_by(BackupRecord.date.desc()).limit(4).all()

    if backup_max is not None:
        # construct empty/full gauge
        how_full = float(backup_total_size) / float(backup_max)
        angle = 2 * pi * how_full
        start_angle = pi / 2.0
        end_angle = pi / 2.0 - angle if angle < pi / 2.0 else 5.0 * pi / 2.0 - angle

        gauge = figure(width=150, height=150, toolbar_location=None)
        gauge.sizing_mode = "scale_width"
        gauge.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=start_angle,
            end_angle=end_angle,
            fill_color="red",
        )
        gauge.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=end_angle,
            end_angle=start_angle,
            fill_color="grey",
        )
        gauge.axis.visible = False
        gauge.xgrid.visible = False
        gauge.ygrid.visible = False
        gauge.border_fill_color = None
        gauge.toolbar.logo = None
        gauge.background_fill_color = None
        gauge.outline_line_color = None
        gauge.toolbar.active_drag = None

        annotation = Label(
            x=0,
            y=0,
            x_units="data",
            y_units="data",
            text="{p:.2g}%".format(p=how_full * 100),
            background_fill_alpha=0.0,
            text_align="center",
            text_baseline="middle",
            text_font_style="bold",
        )
        gauge.add_layout(annotation)

        gauge_script, gauge_div = components(gauge)

    else:
        gauge_script = None
        gauge_div = None

    return render_template_context(
        "admin/backup_dashboard/overview.html",
        pane="overview",
        form=form,
        backup_size=size,
        backup_count=backup_count,
        last_change=last_change,
        archive_script=archive_script,
        archive_div=archive_div,
        backup_script=backup_script,
        backup_div=backup_div,
        last_batch=last_batch,
        gauge_script=gauge_script,
        gauge_div=gauge_div,
    )


@admin.route("/manage_backups", methods=["GET", "POST"])
@roles_required("root")
def manage_backups():
    """
    Generate the backup-management view
    :return:
    """
    type_filter = request.args.get("type_filter")

    if type_filter is None:
        type_filter = session.get("admin_backup_type_filter")

    if type_filter is not None and type_filter not in [
        "all",
        "scheduled",
        "rollover",
        "golive",
        "close",
        "confirm",
        "batch-student",
        "batch-faculty",
    ]:
        type_filter = "all"

    if type_filter is not None:
        session["admin_backup_type_filter"] = type_filter

    property_filter = request.args.get("property_filter")

    if property_filter is None:
        property_filter = session.get("admin_backup_property_filter")

    if property_filter is not None and property_filter not in ["all", "labels", "lock"]:
        property_filter = "all"

    if property_filter is not None:
        session["admin_backup_property_filter"] = property_filter

    backup_count = compute_current_backup_count()

    form = BackupManageForm(request.form)

    if form.validate_on_submit() and form.delete_age.data is True:
        return redirect(
            url_for("admin.confirm_delete_backup_cutoff", cutoff=(form.weeks.data))
        )

    return render_template_context(
        "admin/backup_dashboard/manage.html",
        pane="view",
        backup_count=backup_count,
        form=form,
        type_filter=type_filter,
        property_filter=property_filter,
    )


@admin.route("/manage_backups_ajax", methods=["POST"])
@roles_required("root")
def manage_backups_ajax():
    """
    Ajax data point for backup-management view
    :return:
    """
    type_filter = request.args.get("type_filter")
    property_filter = request.args.get("property_filter")

    base_query = db.session.query(BackupRecord).join(
        User, User.id == BackupRecord.owner_id
    )

    if type_filter == "scheduled":
        base_query = base_query.filter(
            BackupRecord.type == BackupRecord.SCHEDULED_BACKUP
        )
    elif type_filter == "rollover":
        base_query = base_query.filter(
            BackupRecord.type == BackupRecord.PROJECT_ROLLOVER_FALLBACK
        )
    elif type_filter == "golive":
        base_query = base_query.filter(
            BackupRecord.type == BackupRecord.PROJECT_GOLIVE_FALLBACK
        )
    elif type_filter == "close":
        base_query = base_query.filter(
            BackupRecord.type == BackupRecord.PROJECT_CLOSE_FALLBACK
        )
    elif type_filter == "confirm":
        base_query = base_query.filter(
            BackupRecord.type == BackupRecord.PROJECT_ISSUE_CONFIRM_FALLBACK
        )
    elif type_filter == "batch-student":
        base_query = base_query.filter(
            BackupRecord.type == BackupRecord.BATCH_STUDENT_IMPORT_FALLBACK
        )

    if property_filter == "labels":
        base_query = base_query.filter(BackupRecord.labels.any(BackupLabel.id != None))
    elif property_filter == "lock":
        base_query = base_query.filter(BackupRecord.locked)

    date = {
        "search": func.date_format(BackupRecord.date, "%a %d %b %Y %H:%M:%S"),
        "order": BackupRecord.date,
    }
    initiated = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    type = {"order": BackupRecord.type}
    description = {
        "search": BackupRecord.description,
        "order": BackupRecord.description,
        "search_collation": "utf8_general_ci",
    }
    key = {
        "search": BackupRecord.unique_name,
        "order": BackupRecord.unique_name,
        "search_collation": "utf8_general_ci",
    }
    db_size = {"order": BackupRecord.db_size}
    archive_size = {"order": BackupRecord.archive_size}

    columns = {
        "date": date,
        "initiated": initiated,
        "type": type,
        "description": description,
        "key": key,
        "db_size": db_size,
        "archive_size": archive_size,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.backups_data)


@admin.route("/manual_backup", methods=["GET", "POST"])
@roles_required("root")
def manual_backup():
    """
    Initiate manual backup
    :return:
    """
    form = ManualBackupForm(request.form)

    if form.validate_on_submit():
        label_list = create_new_backup_labels(form)
        label_ids = [l.id for l in label_list]

        tk_name = f"Manual backup initiated by {current_user.name}"
        tk_description = "Perform a manual backup"
        task_id = register_task(tk_name, owner=current_user, description=tk_description)

        celery = current_app.extensions["celery"]
        backup_task = celery.tasks["app.tasks.backup.backup"]

        init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
        final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
        error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

        unlock_date_str = (
            str(form.unlock_date.data) if form.unlock_date.data is not None else None
        )
        args = (
            current_user.id,
            BackupRecord.MANUAL_BACKUP,
            "backup",
            form.description.data,
            form.locked.data,
            unlock_date_str,
            label_ids,
        )

        seq = chain(
            init.si(task_id, tk_name),
            backup_task.signature(args, None, immutable=True),
            final.si(task_id, tk_name, current_user.id, notify=True),
        ).on_error(error.si(task_id, tk_name, current_user.id))

        seq.apply_async(task_id=task_id)
        return redirect(url_for("admin.manage_backups"))

    else:
        if request.method == "GET":
            default_unlock_date = date.today() + timedelta(weeks=24)

            form.unlock_date.data = default_unlock_date

    return render_template_context("admin/manual_backup.html", form=form)


@admin.route("/confirm_delete_all_backups")
@roles_required("root")
def confirm_delete_all_backups():
    """
    Show confirmation box to delete all backups
    :return:
    """
    title = "Confirm delete"
    panel_title = "Confirm delete all backups"

    action_url = url_for("admin.delete_all_backups")
    message = "<p>Please confirm that you wish to delete all backups.</p><p>Locked backups are not deleted.</p><p>This action cannot be undone.</p>"
    submit_label = "Delete all"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/delete_all_backups")
@roles_required("root")
def delete_all_backups():
    """
    Delete all backups
    :return:
    """
    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    del_backup = celery.tasks["app.tasks.backup.delete_backup"]

    tk_name = "Manual delete backups"
    tk_description = "Manually delete all backups"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    backups = db.session.query(BackupRecord.id).filter_by(~BackupRecord.locked).all()
    work_group = group(del_backup.si(id[0]) for id in backups)

    seq = chain(
        init.si(task_id, tk_name),
        work_group,
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.manage_backups"))


@admin.route("/confirm_delete_backup_cutoff/<int:cutoff>")
@roles_required("root")
def confirm_delete_backup_cutoff(cutoff):
    """
    Show confirmation box to delete all backups older than a given cutoff
    :param cutoff:
    :return:
    """
    pl = "s"
    if cutoff == 1:
        pl = ""

    title = "Confirm delete"
    panel_title = "Confirm delete all backups older than {c} week{pl}".format(
        c=cutoff, pl=pl
    )

    action_url = url_for("admin.delete_backup_cutoff", cutoff=cutoff)
    message = (
        "<p>Please confirm that you wish to delete all backups older than {c} week{pl}.</p>"
        "<p>This action cannot be undone.</p>".format(c=cutoff, pl=pl)
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/delete_backup_cutoff/<int:cutoff>")
@roles_required("root")
def delete_backup_cutoff(cutoff):
    """
    Delete all backups older than the given cutoff
    :param cutoff:
    :return:
    """
    pl = "s"
    if cutoff == 1:
        pl = ""

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    del_backup = celery.tasks["app.tasks.backup.prune_backup_cutoff"]

    tk_name = "Manual delete backups"
    tk_description = "Manually delete backups older than {c} week{pl}".format(
        c=cutoff, pl=pl
    )
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    now = datetime.now()
    delta = timedelta(weeks=cutoff)
    limit = now - delta

    backups = db.session.query(BackupRecord.id).all()
    work_group = group(del_backup.si(id[0], limit) for id in backups)

    seq = chain(
        init.si(task_id, tk_name),
        work_group,
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.manage_backups"))


@admin.route("/confirm_delete_backup/<int:id>")
@roles_required("root")
def confirm_delete_backup(id):
    """
    Show confirmation box to delete a backup
    :return:
    """
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(id)

    if backup.locked:
        flash(
            f"Backup {backup.date.trftime('%a %d %b %Y %H:%M:%S')} cannot be deleted because it is locked.",
            "info",
        )
        return redirect(redirect_url())

    title = "Confirm delete"
    panel_title = "Confirm delete of backup {d}".format(
        d=backup.date.strftime("%a %d %b %Y %H:%M:%S")
    )

    action_url = url_for("admin.delete_backup", id=id)
    message = (
        "<p>Please confirm that you wish to delete the backup {d}.</p>"
        "<p>This action cannot be undone.</p>".format(
            d=backup.date.strftime("%a %d %b %Y %H:%M:%S")
        )
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/delete_backup/<int:id>")
@roles_required("root")
def delete_backup(id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(id)

    if backup.locked:
        flash(
            f"Backup {backup.date.trftime('%a %d %b %Y %H:%M:%S')} cannot be deleted because it is locked.",
            "info",
        )
        return redirect(redirect_url())

    success, msg = remove_backup(id)

    if not success:
        flash(
            f'Could not delete backup. Backend message = "{msg}". Please contact a system administrator.',
            "error",
        )

    return redirect(url_for("admin.manage_backups"))


@admin.route("/background_tasks")
@roles_required("root")
def background_tasks():
    """
    List all background tasks
    :return:
    """
    status_filter = request.args.get("status_filter")

    if status_filter is None and session.get("background_task_status_filter"):
        status_filter = session["background_task_status_filter"]

    if status_filter is not None:
        if status_filter not in ["all", "pending", "running", "success", "failure"]:
            status_filter = "all"
        session["background_task_status_filter"] = status_filter

    return render_template_context(
        "admin/background_tasks.html", status_filter=status_filter
    )


@admin.route("/background_ajax", methods=["POST"])
@roles_required("root")
def background_ajax():
    """
    Ajax data point for background tasks view
    :return:
    """
    status_filter = request.args.get("status_filter")

    base_query = db.session.query(TaskRecord).join(User, User.id == TaskRecord.owner_id)

    if status_filter == "pending":
        base_query = base_query.filter(TaskRecord.status == TaskRecord.PENDING)
    elif status_filter == "running":
        base_query = base_query.filter(TaskRecord.status == TaskRecord.RUNNING)
    elif status_filter == "success":
        base_query = base_query.filter(TaskRecord.status == TaskRecord.SUCCESS)
    elif status_filter == "failure":
        base_query = base_query.filter(
            or_(
                TaskRecord.status == TaskRecord.FAILURE,
                TaskRecord.status == TaskRecord.TERMINATED,
            )
        )

    identifier = {"search": TaskRecord.id, "order": TaskRecord.id}
    name = {
        "search": TaskRecord.name,
        "order": TaskRecord.id,
        "search_collation": "utf8_general_ci",
    }
    owner = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    start_time = {
        "search": func.date_format(TaskRecord.start_date, "%a %d %b %Y %H:%M:%S"),
        "order": TaskRecord.start_date,
    }
    status = {"order": TaskRecord.status}
    progress = {"order": TaskRecord.progress}
    message = {
        "search": TaskRecord.message,
        "order": TaskRecord.message,
        "search_collation": "utf8_general_ci",
    }

    columns = {
        "id": identifier,
        "name": name,
        "owner": owner,
        "start_at": start_time,
        "status": status,
        "progress": progress,
        "message": message,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.background_task_data)


@admin.route("/terminate_background_task/<string:id>")
@roles_required("root")
def terminate_background_task(id):
    record = TaskRecord.query.get_or_404(id)

    if (
        record.status == TaskRecord.SUCCESS
        or record.status == TaskRecord.FAILURE
        or record.status == TaskRecord.TERMINATED
    ):
        flash(
            'Could not terminate background task "{name}" because it has finished.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    celery.control.revoke(record.id, terminate=True, signal="SIGUSR1")

    try:
        # update progress bar
        progress_update(
            record.id,
            TaskRecord.TERMINATED,
            100,
            "Task terminated by user",
            autocommit=False,
        )

        # remove task from database
        db.session.delete(record)
        log_db_commit(
            f"Terminated and removed background task '{record.name}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        flash(
            'Could not terminate task "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@admin.route("/delete_background_task/<string:id>")
@roles_required("root")
def delete_background_task(id):
    record = TaskRecord.query.get_or_404(id)

    if record.status == TaskRecord.PENDING or record.status == TaskRecord.RUNNING:
        flash(
            'Could not delete match "{name}" because it has not terminated.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    try:
        # remove task from database
        db.session.delete(record)
        log_db_commit(
            f"Deleted background task record '{record.name}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Could not delete match "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/notifications_ajax")
@limiter.exempt
def notifications_ajax():
    """
    Retrieve all notifications for the current user and take care of keep-alive tasks;
    must exit as quickly as possible
    :return:
    """
    # return empty JSON if not logged in; we don't want this endpoint to require that the user is logged in,
    # otherwise we will end up triggering 'you do not have sufficient privileges to view this resource' errors
    # when the session ends but a webpage is still open
    if not current_user.is_authenticated:
        return jsonify({})

    # get timestamp that client wants messages from, if provided
    since = request.args.get("since", 0, type=int)

    redis = get_redis()
    redis.hset("_pings", str(current_user.id), str((datetime.now().isoformat(), since)))

    # query for all notifications associated with the current user
    notifications = (
        current_user.notifications.filter(Notification.timestamp >= since)
        .order_by(Notification.timestamp.asc())
        .all()
    )

    data = [
        {"uuid": n.uuid, "type": n.type, "payload": n.payload, "timestamp": n.timestamp}
        for n in notifications
    ]

    return jsonify(data)


def _compute_allowed_matching_years(current_year):
    # check which year we are going to offer, and whether any project classes are ready to match
    pre_allowed_years = db.session.query(MatchingAttempt.year).distinct().all()
    allowed_years = {y for (y,) in pre_allowed_years}

    data = get_ready_to_match_data()
    if data["matching_ready"] and not data["rollover_in_progress"]:
        allowed_years = allowed_years | {current_year}

    return allowed_years, data


@admin.route("/workflow_log")
@roles_required("root")
def workflow_log():
    """
    Display the workflow log inspector.
    """
    pclass_filter = request.args.get("pclass_filter")
    tenant_filter = request.args.get("tenant_filter")

    # Restore filters from session if not supplied in the request
    if pclass_filter is None and session.get("admin_workflow_log_pclass_filter"):
        pclass_filter = session["admin_workflow_log_pclass_filter"]

    if pclass_filter is not None:
        pclass = db.session.query(ProjectClass).filter_by(id=pclass_filter).first()
        if pclass is None:
            pclass_filter = "all"

    if pclass_filter is not None:
        session["admin_workflow_log_pclass_filter"] = pclass_filter

    if tenant_filter is None and session.get("admin_workflow_log_tenant_filter"):
        tenant_filter = session["admin_workflow_log_tenant_filter"]

    if tenant_filter is not None:
        tenant = db.session.query(Tenant).filter_by(id=tenant_filter).first()
        if tenant is None:
            tenant_filter = "all"

    if tenant_filter is not None:
        session["admin_workflow_log_tenant_filter"] = tenant_filter

    # Build lists for filter controls
    tenants = db.session.query(Tenant).order_by(Tenant.name).all()
    pclasses = db.session.query(ProjectClass).filter_by(active=True).order_by(ProjectClass.name).all()

    return render_template_context(
        "admin/workflow_log.html",
        tenants=tenants,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        tenant_filter=tenant_filter,
    )


@limiter.exempt
@admin.route("/workflow_log_ajax", methods=["POST"])
@roles_required("root")
def workflow_log_ajax():
    """
    AJAX data point for workflow log inspector.
    """
    pclass_filter = request.args.get("pclass_filter")
    tenant_filter = request.args.get("tenant_filter")

    # Outer-join User and StudentData so we can search on both without losing background-task entries
    base_query = (
        db.session.query(WorkflowLogEntry)
        .outerjoin(User, User.id == WorkflowLogEntry.initiator_id)
        .outerjoin(StudentData, StudentData.id == WorkflowLogEntry.student_id)
    )

    try:
        pclass_value = int(pclass_filter)
        base_query = base_query.filter(
            WorkflowLogEntry.project_classes.any(ProjectClass.id == pclass_value)
        )
    except (TypeError, ValueError):
        try:
            tenant_value = int(tenant_filter)
            base_query = base_query.filter(
                WorkflowLogEntry.project_classes.any(
                    ProjectClass.tenant_id == tenant_value
                )
            )
        except (TypeError, ValueError):
            pass

    columns = {
        "user": {
            "search": func.concat(User.first_name, " ", User.last_name),
            "search_collation": "utf8_general_ci",
        },
        "student": {
            "search": func.concat(StudentData.first_name, " ", StudentData.last_name),
            "order": [StudentData.last_name, StudentData.first_name],
            "search_collation": "utf8_general_ci",
        },
        "endpoint": {
            "search": WorkflowLogEntry.endpoint,
            "order": WorkflowLogEntry.endpoint,
            "search_collation": "utf8_bin",
        },
        "timestamp": {
            "search": func.date_format(
                WorkflowLogEntry.timestamp, "%a %d %b %Y %H:%M:%S"
            ),
            "order": WorkflowLogEntry.timestamp,
        },
        "summary": {
            "search": WorkflowLogEntry.summary,
            "search_collation": "utf8_general_ci",
        },
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.workflow_log_data)


@admin.route("/workflow_log_export")
@roles_required("root")
def workflow_log_export():
    """
    Trigger an asynchronous export of the workflow log to an Excel spreadsheet,
    which will be deposited in the current user's Download Centre.
    """
    pclass_filter = request.args.get("pclass_filter")
    tenant_filter = request.args.get("tenant_filter")

    pclass_id = None
    try:
        pclass_id = int(pclass_filter)
    except (TypeError, ValueError):
        pass

    tenant_id = None
    try:
        tenant_id = int(tenant_filter)
    except (TypeError, ValueError):
        pass

    celery = current_app.extensions["celery"]
    export_task = celery.tasks["app.tasks.workflow_log.export_workflow_log"]
    export_task.apply_async(
        kwargs={
            "user_id": current_user.id,
            "pclass_id": pclass_id,
            "tenant_id": tenant_id,
        }
    )

    flash(
        "Your workflow log export is being prepared and will appear in your "
        "<strong>Download Centre</strong> when ready.",
        "info",
    )
    return redirect(
        url_for(
            "admin.workflow_log",
            pclass_filter=pclass_filter,
            tenant_filter=tenant_filter,
        )
    )
