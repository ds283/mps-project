#
# Created by David Seery on 02/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from . import projecthub

from flask import render_template, redirect, url_for, flash, request
from flask_security import current_user, roles_accepted, roles_required

from ..models import SubmissionRecord, SubmittingStudent, StudentData, ProjectClassConfig, ProjectClass, LiveProject, \
    SubmissionPeriodRecord

from .utils import validate_project_hub
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

    return render_template("projecthub/hub.html", text=text, url=url, submitter=submitter, student=student,
                           config=config, pclass=pclass, project=project, record=record, period=period)
