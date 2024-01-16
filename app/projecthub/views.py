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
from math import pi

from flask import render_template, redirect, flash, request, jsonify, current_app, url_for
from flask_security import current_user, roles_accepted, login_required
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import with_polymorphic
from sqlalchemy.sql import func
from bokeh.embed import components
from bokeh.plotting import figure
from bokeh.models import Label

from . import projecthub

from .utils import validate_project_hub
from .forms import AddFormatterArticleForm, EditFormattedArticleForm

import app.ajax as ajax
from ..database import db
from ..models import (
    SubmissionRecord,
    SubmittingStudent,
    StudentData,
    ProjectClassConfig,
    ProjectClass,
    LiveProject,
    SubmissionPeriodRecord,
    ProjectHubLayout,
    ConvenorSubmitterArticle,
    FormattedArticle,
    ProjectSubmitterArticle,
    User,
)
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

    if not record.uses_project_hub:
        flash(
            "The project hub has been disabled for this submission. If you think this is incorrect, "
            "please contact your supervisor or the projects convenor.",
            "info",
        )
        return redirect(redirect_url())

    submitter: SubmittingStudent = record.owner
    student: StudentData = submitter.student

    if student is None or student.user is None:
        flash(
            "The project hub for this submitter (id={sid}) cannot be displayed because it is not associated "
            "with a student account. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(sid=submitter.id),
            "info",
        )
        return redirect(redirect_url())

    config: ProjectClassConfig = submitter.config

    if config is None:
        flash(
            "The project hub for student {name} cannot be displayed because it is not linked to a project "
            "class configuration instance. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    pclass: ProjectClass = config.project_class

    if pclass is None:
        flash(
            "The project hub for student {name} cannot be displayed because it is not linked to a project "
            "class instance. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    project: LiveProject = record.project

    if project is None:
        flash(
            "The project hub for student {name} cannot be displayed because no project has "
            "been allocated. If you think this is an error, please contact a system "
            "administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if period is None:
        flash(
            "The project hub for student {name} cannot be displayed because it is not linked to a "
            "submission period. This is almost certainly caused by a database error. Please contact "
            "a system administrator.".format(name=student.user.name),
            "info",
        )
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    layout = {
        "resources-widget": {"x": 5, "y": 3, "w": 7, "h": 5},
        "news-widget": {"x": 0, "y": 0, "w": 12, "h": 3},
        "journal-widget": {"x": 0, "y": 3, "w": 5, "h": 5},
    }

    saved_layout: ProjectHubLayout = db.session.query(ProjectHubLayout).filter_by(owner_id=subid, user_id=current_user.id).first()

    if saved_layout is not None:
        layout.update(json.loads(saved_layout.serialized_layout))

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

    return render_template(
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
        layout=layout,
        burndown_div=burndown_div,
        burndown_script=burndown_script,
    )


@projecthub.route("/save_hub_layout", methods=["POST"])
@login_required
def save_hub_layout():
    data = request.get_json()

    # discard notification if ill-formed
    if "payload" not in data or "record_id" not in data or "user_id" not in data or "timestamp" not in data:
        return jsonify({"status": "ill_formed"})

    payload = data["payload"]
    record_id = data["record_id"]
    user_id = data["user_id"]

    try:
        timestamp = int(data["timestamp"])
    except ValueError:
        return jsonify({"status": "ill_formed"})

    if payload is None or record_id is None or user_id is None:
        return jsonify({"status": "ill_formed"})

    record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()

    if record is None:
        return jsonify({"status": "database_error"})

    if user_id != current_user.id:
        return jsonify({"status": "bad_login"})

    try:
        layout = {item["widget"]: {"x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"]} for item in payload}
    except KeyError:
        return jsonify({"status": "ill_formed"})

    saved_layout: ProjectHubLayout = db.session.query(ProjectHubLayout).filter_by(owner_id=record_id, user_id=user_id).first()

    if saved_layout is None:
        new_layout = ProjectHubLayout(owner_id=record_id, user_id=user_id, serialized_layout=json.dumps(layout), timestamp=timestamp)

        try:
            db.session.add(new_layout)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return jsonify({"status": "database_error"})

    else:
        if saved_layout.timestamp is None or timestamp > saved_layout.timestamp:
            old_layout = json.loads(saved_layout.serialized_layout)
            old_layout.update(layout)

            saved_layout.serialized_layout = json.dumps(old_layout)
            saved_layout.timestamp = timestamp

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return jsonify({"status": "database_error"})

    return jsonify({"status": "ok"})


@projecthub.route("/edit_subpd_record_articles/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def edit_subpd_record_articles(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if not config.uses_project_hub:
        flash(
            "It is not possible to edit articles or news for {pclass}/{period} because project hubs "
            "are currently disabled for this project class. Please contact a system administrator if you "
            "believe this is an error.".format(pclass=config.name, period=record.display_name)
        )
        return redirect(redirect_url())

    return render_template(
        "projecthub/articles/article_list.html",
        text=text,
        url=url,
        title="Edit submission period articles",
        panel_title="Edit articles for submission period <strong>{name}</strong> in project "
        "class <strong>{pclass}</strong> "
        "({yra}&ndash;{yrb})".format(
            name=record.display_name, pclass=record.config.name, yra=record.config.submit_year_a, yrb=record.config.submit_year_b
        ),
        ajax_endpoint=url_for("projecthub.edit_subpd_record_articles_ajax", pid=pid),
        add_endpoint=url_for("projecthub.add_subpd_record_article", pid=pid),
    )


@projecthub.route("/edit_subpd_record_articles_ajax/<int:pid>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def edit_subpd_record_articles_ajax(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(record.config.project_class):
        return jsonify({})

    if not config.uses_project_hub:
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

    return_url = url_for("projecthub.edit_subpd_record_articles", pid=pid)

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.projecthub.article_list_data, return_url, "submission period articles", "projecthub.edit_subpd_record_article")
        )


@projecthub.route("add_subpd_record_article/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "route")
def add_subpd_record_article(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if not config.uses_project_hub:
        flash(
            "It is not possible to edit articles or news for {pclass}/{period} because project hubs "
            "are currently disabled for this project class. Please contact a system administrator if you "
            "believe this is an error.".format(pclass=config.name, period=record.display_name)
        )
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

        return redirect(url_for("projecthub.edit_subpd_record_articles", pid=pid))

    return render_template(
        "projecthub/articles/edit_article.html",
        form=form,
        record=record,
        title="Add new article",
        panel_title="Add new article or news story to period <strong>{pname}</strong> "
        "in project class <strong>{pclass}</strong> "
        "({yra}&ndash;{yrb})".format(
            pname=record.display_name, pclass=record.config.name, yra=record.config.submit_year_a, yrb=record.config.submit_year_b
        ),
        action_url=url_for("projecthub.add_subpd_record_article", pid=pid),
    )


@projecthub.route("edit_subpd_record_article/<int:aid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "route")
def edit_subpd_record_article(aid):
    # pid is a SubmissionPeriodRecord
    article: ConvenorSubmitterArticle = ConvenorSubmitterArticle.query.get_or_404(aid)
    record: SubmissionPeriodRecord = article.period
    config: ProjectClassConfig = record.config

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if not config.uses_project_hub:
        flash(
            "It is not possible to edit articles or news for {pclass}/{period} because project hubs "
            "are currently disabled for this project class. Please contact a system administrator if you "
            "believe this is an error.".format(pclass=config.name, period=record.display_name)
        )
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

        return redirect(url_for("projecthub.edit_subpd_record_articles", pid=record.id))

    return render_template(
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
        action_url=url_for("projecthub.edit_subpd_record_article", aid=aid),
    )


@projecthub.route("/show_formatted_article/<int:aid>")
@login_required
def show_formatted_article(aid):
    article: FormattedArticle = FormattedArticle.query.get_or_404(aid)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template("projecthub/articles/show_article.html", article=article, text=text, url=url)


@projecthub.route("/article_widget_ajax/<int:subid>", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "supervisor", "student", "office", "moderator", "external_examiner", "exam_board")
def article_widget_ajax(subid):
    # subid labels a SubmissionRecord
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(subid)

    if not validate_project_hub(record, current_user, message=True):
        return jsonify({})

    if not record.uses_project_hub:
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
