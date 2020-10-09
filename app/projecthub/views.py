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
from datetime import date, timedelta
from math import pi

from flask import render_template, redirect, flash, request, jsonify, current_app, url_for
from flask_security import current_user, roles_accepted, login_required
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func
from bokeh.embed import components
from bokeh.plotting import figure
from bokeh.models import Label

from . import projecthub

from .utils import validate_project_hub

import app.ajax as ajax
from ..database import db
from ..models import SubmissionRecord, SubmittingStudent, StudentData, ProjectClassConfig, ProjectClass, LiveProject, \
    SubmissionPeriodRecord, ProjectHubLayout, ConvenorSubmitterArticle
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..tools import ServerSideHandler


@projecthub.route('/hub/<int:subid>')
@roles_accepted('admin', 'root', 'faculty', 'supervisor', 'student', 'office', 'moderator', 'external_examiner', 'exam_board')
def hub(subid):
    # subid labels a SubmissionRecord
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(subid)

    if not validate_project_hub(record, current_user, message=True):
        return redirect(redirect_url())

    submitter: SubmittingStudent = record.owner
    student: StudentData = submitter.student

    if student is None or student.user is None:
        flash('The project hub for this submitter (id={sid}) cannot be displayed because it is not associated '
              'with a student account. This is almost certainly caused by a database error. Please contact '
              'a system administrator.'.format(sid=submitter.id), 'info')
        return redirect(redirect_url())

    config: ProjectClassConfig = submitter.config

    if config is None:
        flash('The project hub for student {name} cannot be displayed because it is not linked to a project '
              'class configuration instance. This is almost certainly caused by a database error. Please contact '
              'a system administrator.'.format(name=student.user.name), 'info')
        return redirect(redirect_url())

    pclass: ProjectClass = config.project_class

    if pclass is None:
        flash('The project hub for student {name} cannot be displayed because it is not linked to a project '
              'class instance. This is almost certainly caused by a database error. Please contact '
              'a system administrator.'.format(name=student.user.name), 'info')
        return redirect(redirect_url())

    project: LiveProject = record.project

    if project is None:
        flash('The project hub for student {name} cannot be displayed because no project has '
              'been allocated. If you think this is an error, please contact a system '
              'administrator.'.format(name=student.user.name), 'info')
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if period is None:
        flash('The project hub for student {name} cannot be displayed because it is not linked to a '
              'submission period. This is almost certainly caused by a database error. Please contact '
              'a system administrator.'.format(name=student.user.name), 'info')
        return redirect(redirect_url())

    text = request.args.get('text', None)
    url = request.args.get('url', None)

    layout = {'resources-widget': {'x': 5, 'y': 3, 'w': 7, 'h': 5},
              'news-widget': {'x': 0, 'y': 0, 'w': 12, 'h': 3},
              'journal-widget': {'x': 0, 'y': 3, 'w': 5, 'h': 5}}

    saved_layout: ProjectHubLayout = db.session.query(ProjectHubLayout) \
        .filter_by(owner_id=subid, user_id=current_user.id).first()

    if saved_layout is not None:
        layout.update(json.loads(saved_layout.serialized_layout))

    # generate burn-down doughnut chart if we can
    now = date.today()
    if not record.retired and period.start_date and now >= period.start_date \
            and period.hand_in_date and now <= period.hand_in_date:
        total_time: timedelta = period.hand_in_date - period.start_date
        total_time_days: int = total_time.days

        used_time: timedelta = now - period.start_date
        used_time_days: int = used_time.days

        burnt_time = float(used_time_days) / float(total_time_days)
        angle = 2*pi * burnt_time
        start_angle = pi/2.0
        end_angle = pi/2.0 - angle if angle < pi/2.0 else 5.0*pi/2.0 - angle

        plot = figure(width=80, height=80, toolbar_location=None)
        plot.sizing_mode = 'fixed'
        plot.annular_wedge(x=0, y=0, inner_radius=0.75, outer_radius=1, direction='clock', line_color=None,
                           start_angle=start_angle, end_angle=end_angle, fill_color='tomato')
        plot.annular_wedge(x=0, y=0, inner_radius=0.75, outer_radius=1, direction='clock', line_color=None,
                           start_angle=end_angle, end_angle=start_angle, fill_color='palegreen')
        plot.axis.visible = False
        plot.xgrid.visible = False
        plot.ygrid.visible = False
        plot.border_fill_color = None
        plot.toolbar.logo = None
        plot.background_fill_color = None
        plot.outline_line_color = None
        plot.toolbar.active_drag = None

        annotation = Label(x=0, y=0, x_units='data', y_units='data',
                           text='{p:.2g}%'.format(p=burnt_time * 100), render_mode='css',
                           background_fill_alpha=0.0, text_align='center',
                           text_baseline='middle', text_font_style='bold')
        plot.add_layout(annotation)

        burndown_script, burndown_div = components(plot)

    else:
        burndown_script = None
        burndown_div = None

    return render_template("projecthub/hub.html", text=text, url=url, submitter=submitter, student=student,
                           config=config, pclass=pclass, project=project, record=record, period=period,
                           layout=layout, burndown_div=burndown_div, burndown_script=burndown_script)


@projecthub.route('/save_hub_layout', methods=['POST'])
@login_required
def save_hub_layout():
    data = request.get_json()

    # discard notification if ill-formed
    if 'payload' not in data or 'record_id' not in data or 'user_id' not in data or 'timestamp' not in data:
        return jsonify({'status': 'ill_formed'})

    payload = data['payload']
    record_id = data['record_id']
    user_id = data['user_id']

    try:
        timestamp = int(data['timestamp'])
    except ValueError:
        return jsonify({'status': 'ill_formed'})

    if payload is None or record_id is None or user_id is None:
        return jsonify({'status': 'ill_formed'})

    record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()

    if record is None:
        return jsonify({'status': 'database_error'})

    if user_id != current_user.id:
        return jsonify({'status': 'bad_login'})

    try:
        layout = {item['widget']:
                      {'x': item['x'], 'y': item['y'], 'w': item['w'], 'h': item['h']}
                  for item in payload}
    except KeyError:
        return jsonify({'status': 'ill_formed'})

    saved_layout: ProjectHubLayout = db.session.query(ProjectHubLayout) \
        .filter_by(owner_id=record_id, user_id=user_id).first()

    if saved_layout is None:
        new_layout = ProjectHubLayout(owner_id=record_id,
                                      user_id=user_id,
                                      serialized_layout=json.dumps(layout),
                                      timestamp=timestamp)

        try:
            db.session.add(new_layout)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return jsonify({'status': 'database_error'})

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
                return jsonify({'status': 'database_error'})

    return jsonify({'status': 'ok'})


@projecthub.route('/edit_subpd_record_articles/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def edit_subpd_record_articles(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    return render_template('projecthub/articles/article_list.html', text=text, url=url,
                           title='Edit submission period articles',
                           panel_title='Edit articles for submission period {name}'.format(name=record.display_name),
                           ajax_endpoint=url_for('projecthub.edit_subpd_record_articles_ajax', pid=pid))


@projecthub.route('/edit_subpd_record_articles_ajax/<int:pid>', methods=['POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_subpd_record_articles_ajax(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)

    # reject if user is not a convenor for the project owning this submission period
    if not validate_is_convenor(record.config.project_class):
        return jsonify({})

    base_query = record.articles

    title = {'search': ConvenorSubmitterArticle.title,
             'order': ConvenorSubmitterArticle.title,
             'search_collation': 'utf8_general_ci'}
    published = {'search': func.date_format(ConvenorSubmitterArticle.publication_timestamp, "%a %d %b %Y %H:%M:%S"),
                 'order': ConvenorSubmitterArticle.publication_timestamp,
                 'search_collation': 'utf8_general_ci'}
    last_edit = {'search': func.date_format(ConvenorSubmitterArticle.last_edit_timestamp, "%a %d %b %Y %H:%M:%S"),
                 'order': ConvenorSubmitterArticle.last_edit_timestamp,
                 'search_collation': 'utf8_general_ci'}

    columns = {'title': title,
               'published': published,
               'last_edit': last_edit}

    with ServerSideHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.projecthub.article_list_data)
