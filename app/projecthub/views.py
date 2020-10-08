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

from flask import render_template, redirect, flash, request, jsonify, current_app
from flask_security import current_user, roles_accepted, login_required
from sqlalchemy.exc import SQLAlchemyError

from . import projecthub

from .utils import validate_project_hub

from ..database import db
from ..models import SubmissionRecord, SubmittingStudent, StudentData, ProjectClassConfig, ProjectClass, LiveProject, \
    SubmissionPeriodRecord, ProjectHubLayout
from ..shared.utils import redirect_url


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

    return render_template("projecthub/hub.html", text=text, url=url, submitter=submitter, student=student,
                           config=config, pclass=pclass, project=project, record=record, period=period,
                           layout=layout)


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
