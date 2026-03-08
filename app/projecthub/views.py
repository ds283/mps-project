#
# Created by David Seery on 02/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from datetime import date, timedelta, datetime
from functools import partial

from bokeh.embed import components
from bokeh.models import Label
from bokeh.plotting import figure
from flask import redirect, flash, request, jsonify, current_app, url_for
from flask_security import current_user, roles_accepted, login_required
from math import pi
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import with_polymorphic
from sqlalchemy.sql import func

import app.ajax as ajax
from . import projecthub
from .forms import AddFormatterArticleForm, EditFormattedArticleForm, MeetingSummaryForm, SupervisionNotesForm, build_event_team_form, \
    ReassignEventOwnerFormFactory
from .utils import validate_project_hub, validate_set_attendance
from ..database import db
from ..models import (
    SubmissionRecord,
    SubmittingStudent,
    StudentData,
    ProjectClassConfig,
    ProjectClass,
    LiveProject,
    SubmissionPeriodRecord,
    ConvenorSubmitterArticle,
    FormattedArticle,
    ProjectSubmitterArticle,
    User, SupervisionEvent, SubmissionRole,
)
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..tools import ServerSideSQLHandler


@projecthub.route("/hub/<int:subid>")
@roles_accepted("admin", "root", "faculty", "supervisor", "student", "office", "moderator", "external_examiner", "exam_board")
def hub(subid):
    # subid labels a SubmissionRecord
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(subid)

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())

    submitter: SubmittingStudent = record.owner
    student: StudentData = submitter.student
    suser: User = student.user

    if student is None or suser is None:
        flash(
            "The project page for this submitter (id={sid}) cannot be displayed because it is not associated "
            "with a student account. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(sid=submitter.id),
            "info",
        )
        return redirect(redirect_url())

    config: ProjectClassConfig = submitter.config

    if config is None:
        flash(
            "The project page for student {name} cannot be displayed because it is not linked to a project "
            "class configuration instance. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    pclass: ProjectClass = config.project_class

    if pclass is None:
        flash(
            "The project page for student {name} cannot be displayed because it is not linked to a project "
            "class instance. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    project: LiveProject = record.project

    if project is None:
        flash(
            "The project page for student {name} cannot be displayed because no project has "
            "been allocated. If you think this is an error, please contact a system "
            "administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if period is None:
        flash(
            "The project page for student {name} cannot be displayed because it is not linked to a "
            "submission period. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # generate burn-down doughnut chart if we can
    now = date.today()
    if not record.retired and period.start_date and now >= period.start_date and period.hand_in_date and now <= period.hand_in_date:
        total_time: timedelta = period.hand_in_date - period.start_date
        total_time_days: int = total_time.days

        used_time: timedelta = now - period.start_date
        used_time_days: int = used_time.days

        burnt_time = float(used_time_days) / float(total_time_days)
        angle = 2 * pi * burnt_time
        start_angle = pi / 2.0
        end_angle = pi / 2.0 - angle if angle < pi / 2.0 else 5.0 * pi / 2.0 - angle

        plot = figure(width=80, height=80, toolbar_location=None)
        plot.sizing_mode = "fixed"
        plot.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=start_angle,
            end_angle=end_angle,
            fill_color="tomato",
        )
        plot.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=end_angle,
            end_angle=start_angle,
            fill_color="palegreen",
        )
        plot.axis.visible = False
        plot.xgrid.visible = False
        plot.ygrid.visible = False
        plot.border_fill_color = None
        plot.toolbar.logo = None
        plot.background_fill_color = None
        plot.outline_line_color = None
        plot.toolbar.active_drag = None

        annotation = Label(
            x=0,
            y=0,
            x_units="data",
            y_units="data",
            text="{p:.2g}%".format(p=burnt_time * 100),
            background_fill_alpha=0.0,
            text_align="center",
            text_baseline="middle",
            text_font_style="bold",
        )
        plot.add_layout(annotation)

        burndown_script, burndown_div = components(plot)

    else:
        burndown_script = None
        burndown_div = None

    return render_template_context(
        "projecthub/hub.html",
        text=text,
        url=url,
        submitter=submitter,
        student=student,
        config=config,
        pclass=pclass,
        project=project,
        record=record,
        period=period,
        burndown_div=burndown_div,
        burndown_script=burndown_script,
        return_url=url_for("projecthub.hub", subid=subid, url=url, text=text),
        return_text=f'project page for {suser.name}'
    )


@projecthub.route("/edit_submission_period_articles/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def edit_submission_period_articles(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    return render_template_context(
        "projecthub/articles/article_list.html",
        text=text,
        url=url,
        title="Edit submission period articles",
        panel_title="Edit articles for submission period <strong>{name}</strong> in project "
        "class <strong>{pclass}</strong> "
        "({yra}&ndash;{yrb})".format(
            name=record.display_name, pclass=record.config.name, yra=record.config.submit_year_a, yrb=record.config.submit_year_b
        ),
        ajax_endpoint=url_for("projecthub.edit_submission_period_articles_ajax", pid=pid),
        add_endpoint=url_for("projecthub.add_submission_period_article", pid=pid),
    )


@projecthub.route("/edit_submission_period_articles_ajax/<int:pid>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def edit_submission_period_articles_ajax(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(config.project_class):
        return jsonify({})

    base_query = record.articles

    title = {"search": ConvenorSubmitterArticle.title, "order": ConvenorSubmitterArticle.title, "search_collation": "utf8_general_ci"}
    published = {
        "search": func.date_format(ConvenorSubmitterArticle.publication_timestamp, "%a %d %b %Y %H:%M:%S"),
        "order": ConvenorSubmitterArticle.publication_timestamp,
    }
    last_edit = {
        "search": func.date_format(ConvenorSubmitterArticle.last_edit_timestamp, "%a %d %b %Y %H:%M:%S"),
        "order": ConvenorSubmitterArticle.last_edit_timestamp,
    }

    columns = {"title": title, "published": published, "last_edit": last_edit}

    return_url = url_for("projecthub.edit_submission_period_articles", pid=pid)

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.projecthub.article_list_data, return_url, "submission period articles", "projecthub.edit_submission_period_article")
        )


@projecthub.route("add_submission_period_article/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "route")
def add_submission_period_article(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    form = AddFormatterArticleForm(request.form)

    if form.validate_on_submit():
        current_time = datetime.now()
        article = ConvenorSubmitterArticle(
            title=form.title.data,
            period_id=record.id,
            article=form.article.data,
            published=form.published.data,
            publish_on=form.publish_on.data if not form.published.data else None,
            creation_timestamp=current_time,
            creator_id=current_user.id,
            last_edit_timestamp=None,
            last_edit_id=None,
        )

        try:
            db.session.add(article)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new article because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("projecthub.edit_submission_period_articles", pid=pid))

    return render_template_context(
        "projecthub/articles/edit_article.html",
        form=form,
        record=record,
        title="Add new article",
        panel_title="Add new article or news story to period <strong>{pname}</strong> "
        "in project class <strong>{pclass}</strong> "
        "({yra}&ndash;{yrb})".format(
            pname=record.display_name, pclass=record.config.name, yra=record.config.submit_year_a, yrb=record.config.submit_year_b
        ),
        action_url=url_for("projecthub.add_submission_period_article", pid=pid),
    )


@projecthub.route("edit_submission_period_article/<int:aid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "route")
def edit_submission_period_article(aid):
    # pid is a SubmissionPeriodRecord
    article: ConvenorSubmitterArticle = ConvenorSubmitterArticle.query.get_or_404(aid)
    record: SubmissionPeriodRecord = article.period
    config: ProjectClassConfig = record.config

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    form = EditFormattedArticleForm(obj=article)

    if form.validate_on_submit():
        article.title = form.title.data
        article.period_id = record.id
        article.article = form.article.data
        article.published = form.published.data
        article.publish_on = form.publish_on.data if not article.published else None

        article.last_edit_timestamp = datetime.now()
        article.last_edit_id = current_user.id

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes to this article because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("projecthub.edit_submission_period_articles", pid=record.id))

    return render_template_context(
        "projecthub/articles/edit_article.html",
        form=form,
        article=article,
        record=record,
        title="Edit article",
        panel_title="Edit article in period <strong>{pname}</strong> "
        "in project class <strong>{pclass}</strong> "
        "({yra}&ndash;{yrb})".format(
            pname=record.display_name, pclass=record.config.name, yra=record.config.submit_year_a, yrb=record.config.submit_year_b
        ),
        action_url=url_for("projecthub.edit_submission_period_article", aid=aid),
    )


@projecthub.route("/show_formatted_article/<int:aid>")
@login_required
def show_formatted_article(aid):
    article: FormattedArticle = FormattedArticle.query.get_or_404(aid)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context("projecthub/articles/show_article.html", article=article, text=text, url=url)


@projecthub.route("/article_widget_ajax/<int:subid>", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "supervisor", "student", "office", "moderator", "external_examiner", "exam_board")
def article_widget_ajax(subid):
    # subid labels a SubmissionRecord
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(subid)

    if not validate_project_hub(record, current_user, message=True):
        return jsonify({})

    articles = with_polymorphic(FormattedArticle, [ConvenorSubmitterArticle, ProjectSubmitterArticle])
    base_query = record.article_list.join(User, User.id == articles.creator_id)

    title = {"search": FormattedArticle.title, "order": FormattedArticle.title, "search_collation": "utf8_general_ci"}
    published = {
        "search": func.date_format(FormattedArticle.publication_timestamp, "%a %d %b %Y %H:%M:%S"),
        "order": FormattedArticle.publication_timestamp,
    }
    author = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }

    columns = {"title": title, "published": published, "author": author}

    url = url_for("projecthub.hub", subid=subid)
    text = "project hub"

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.projecthub.widgets.articles, url, text))


@projecthub.route("/set_attendance/<int:event_id>/<int:attendance>")
@roles_accepted("faculty", "admin", "root", "office")
def set_attendance(event_id, attendance):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)

    if not validate_set_attendance(event, current_user, message=True):
        return redirect(redirect_url())

    if not SupervisionEvent.attendance_valid(attendance):
        flash(f'Cannot set attendance for event "{event.name}" because the attendance setting is not valid.', "error")
        return redirect(redirect_url())

    try:
        event.attendance = attendance
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes to this event because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@projecthub.route("/event_details/<int:event_id>")
@roles_accepted("root", "admin", "faculty", "office")
def event_details(event_id):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)
    record: SubmissionRecord = event.sub_record

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # Only show the team-edit button when there is more than one supervisor role on the record
    # (i.e. there is at least one eligible non-owner team member)
    num_supervisor_roles = len(record.supervisor_roles)

    # Determine whether the current user is a convenor (or admin/root) for this project class,
    # so the template can conditionally show the "Reassign owner" button
    config: ProjectClassConfig = record.period.config
    is_target_convenor = validate_is_convenor(config.project_class, message=False)

    # Determine whether the current user is the event owner
    owner_role = event.owner
    is_event_owner = (
        owner_role is not None
        and owner_role.user_id is not None
        and owner_role.user_id == current_user.id
    )

    return render_template_context(
        "projecthub/event/event_details.html",
        event=event,
        record=record,
        url=url,
        text=text,
        num_supervisor_roles=num_supervisor_roles,
        is_target_convenor=is_target_convenor,
        is_event_owner=is_event_owner,
        edit_summary_url=url_for(
            "projecthub.edit_meeting_summary",
            event_id=event_id,
            url=request.url,
            text="meeting summary",
        ),
        edit_notes_url=url_for(
            "projecthub.edit_supervision_notes",
            event_id=event_id,
            url=request.url,
            text="meeting summary",
        ),
        edit_team_url=url_for(
            "projecthub.edit_event_team",
            event_id=event_id,
            url=request.url,
            text="event details",
        ),
    )


@projecthub.route("/edit_event_team/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("root", "admin", "faculty", "office")
def edit_event_team(event_id):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)
    record: SubmissionRecord = event.sub_record

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # Build a form class whose query is scoped to this event's eligible supervisors
    EventTeamForm = build_event_team_form(event)

    # Pre-populate the multi-select with the current team members
    form = EventTeamForm(obj=event)

    if form.validate_on_submit():
        # Replace the team relationship with the newly selected roles.
        # We must not include the owner in the team list.
        selected_roles = form.team.data or []
        # Guard: silently drop the owner if somehow included
        new_team = [r for r in selected_roles if r.id != event.owner_id]

        try:
            # Clear existing team and replace
            current_team = event.team.all()
            for role in current_team:
                event.team.remove(role)
            for role in new_team:
                event.team.append(role)
            db.session.commit()
            flash(f'Supervision team for event "{event.name}" has been updated.', "success")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to the supervision team because of a database error. "
                "Please contact a system administrator.",
                "error",
            )

        if url is not None:
            return redirect(url)

        return redirect(url_for("projecthub.event_details", event_id=event_id))

    return render_template_context(
        "projecthub/event/edit_event_team.html",
        form=form,
        event=event,
        record=record,
        url=url,
        text=text,
        action_url=url_for("projecthub.edit_event_team", event_id=event_id, url=url, text=text),
    )


@projecthub.route("/edit_meeting_summary/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("root", "admin", "faculty", "office")
def edit_meeting_summary(event_id):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)
    record: SubmissionRecord = event.sub_record

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = MeetingSummaryForm(obj=event)

    if form.validate_on_submit():
        event.meeting_summary = form.meeting_summary.data
        event.last_edit_id = current_user.id
        event.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to the meeting summary because of a database error. "
                "Please contact a system administrator.",
                "error",
            )

        if url is not None:
            return redirect(url)

        return redirect(url_for("projecthub.event_details", event_id=event_id))

    return render_template_context(
        "projecthub/event/edit_meeting_summary.html",
        form=form,
        event=event,
        record=record,
        url=url,
        text=text,
        action_url=url_for("projecthub.edit_meeting_summary", event_id=event_id, url=url, text=text),
    )


@projecthub.route("/edit_supervision_notes/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("root", "admin", "faculty", "office")
def edit_supervision_notes(event_id):
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)
    record: SubmissionRecord = event.sub_record

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = SupervisionNotesForm(obj=event)

    if form.validate_on_submit():
        event.supervision_notes = form.supervision_notes.data
        event.last_edit_id = current_user.id
        event.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to the supervision notes because of a database error. "
                "Please contact a system administrator.",
                "error",
            )

        if url is not None:
            return redirect(url)

        return redirect(url_for("projecthub.event_details", event_id=event_id))

    return render_template_context(
        "projecthub/event/edit_supervision_notes.html",
        form=form,
        event=event,
        record=record,
        url=url,
        text=text,
        action_url=url_for("projecthub.edit_supervision_notes", event_id=event_id, url=url, text=text),
    )


@projecthub.route("/reassign_event_owner/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def reassign_event_owner(event_id):
    """
    Allow the convenor (or an admin/root user), or the current owner of a SupervisionEvent,
    to reassign ownership to one of the current team members.
    The new owner is removed from the team collection; the previous owner is added to it.
    """
    event: SupervisionEvent = SupervisionEvent.query.get_or_404(event_id)

    # Resolve the submission record and project class config
    record: SubmissionRecord = event.sub_record
    if record is None:
        flash("Cannot reassign event owner because the associated submission record could not be found.", "error")
        return redirect(redirect_url())

    sub: SubmittingStudent = record.owner
    config: ProjectClassConfig = sub.config
    pclass: ProjectClass = config.project_class

    # Determine whether the current user is a convenor/admin for this project class
    is_target_convenor = validate_is_convenor(pclass, message=False)

    # Determine whether the current user is the event owner (via their SubmissionRole)
    owner_role: SubmissionRole = event.owner
    is_event_owner = (
        owner_role is not None
        and owner_role.user_id is not None
        and owner_role.user_id == current_user.id
    )

    # Only the convenor/admin or the event owner may perform this action
    if not is_target_convenor and not is_event_owner:
        flash("You do not have permission to reassign the owner of this event.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # Check that the event actually has team members to reassign to
    team_members = event.team.all()
    if not team_members:
        flash("Cannot reassign event owner because there are no other team members to assign as the new owner.", "warning")
        return redirect(url)

    ReassignForm = ReassignEventOwnerFormFactory(event)
    form = ReassignForm(request.form)

    if form.validate_on_submit():
        new_owner_role: SubmissionRole = form.new_owner.data
        old_owner_role: SubmissionRole = event.owner

        if new_owner_role is None:
            flash("Please select a team member to become the new event owner.", "error")
            return redirect(url)

        if old_owner_role is not None and new_owner_role.id == old_owner_role.id:
            flash("The selected team member is already the event owner.", "warning")
            return redirect(url)

        try:
            # Remove the new owner from the team collection (they are becoming the owner)
            if new_owner_role in event.team:
                event.team.remove(new_owner_role)

            # Add the old owner to the team collection (they are being demoted to team member)
            if old_owner_role is not None and old_owner_role not in event.team:
                event.team.append(old_owner_role)

            # Update the owner
            event.owner_id = new_owner_role.id

            db.session.commit()
            flash(
                f'Event owner has been reassigned to <strong>{new_owner_role.user.name}</strong>.',
                "success",
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not reassign event owner due to a database error. Please contact a system administrator.", "error")

        return redirect(url)

    return render_template_context(
        "projecthub/event/reassign_event_owner.html",
        form=form,
        event=event,
        record=record,
        sub=sub,
        url=url,
        is_target_convenor=is_target_convenor,
        is_event_owner=is_event_owner,
    )
