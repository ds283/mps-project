#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, jsonify, session
from flask_security import current_user, roles_required, roles_accepted

from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from . import user_approver

from ..database import db
from ..models import StudentData, DegreeProgramme, DegreeType, WorkflowMixin

from ..shared.utils import get_current_year
from ..shared.conversions import is_integer

import app.ajax as ajax

from datetime import datetime


@user_approver.route('/validate')
@roles_required('user_approver')
def validate():
    """
    Validate student records
    :return:
    """
    url = request.args.get('url', None)
    text = request.args.get('text', None)

    if url is None or text is None:
        url = request.referrer
        text = 'approvals dashboard'

    prog_filter = request.args.get('prog_filter')

    if prog_filter is None and session.get('user_approver_prog_filter'):
        prog_filter = session['user_approver_prog_filter']

    if prog_filter is not None:
        session['user_approver_prog_filter'] = prog_filter

    year_filter = request.args.get('year_filter')

    if year_filter is None and session.get('user_approver_year_filter'):
        year_filter = session['user_approver_year_filter']

    if year_filter is not None:
        session['user_approver_year_filter'] = year_filter

    prog_query = db.session.query(StudentData.programme_id).distinct().subquery()
    programmes = db.session.query(DegreeProgramme) \
        .join(prog_query, prog_query.c.programme_id == DegreeProgramme.id) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()

    return render_template('user_approver/validate.html', url=url, text=text, prog_filter=prog_filter,
                           year_filter=year_filter, programmes=programmes)


@user_approver.route('/validate_ajax')
@roles_required('user_approver')
def validate_ajax():
    url = request.args.get('url', None)
    text = request.args.get('text', None)

    prog_filter = request.args.get('prog_filter')
    year_filter = request.args.get('year_filter')

    records = db.session.query(StudentData.id) \
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
                or_(and_(StudentData.last_edit_id == None, StudentData.creator_id != current_user.id),
                    and_(StudentData.last_edit_id != None, StudentData.last_edit_id != current_user.id)))

    flag, prog_value = is_integer(prog_filter)
    if flag:
        records = records.filter(StudentData.programme_id == prog_value)

    flag, year_value = is_integer(year_filter)
    if flag:
        current_year = get_current_year()
        nonf = records.filter(StudentData.foundation_year == False,
                              current_year - StudentData.cohort + 1 - StudentData.repeated_years == year_value)
        foun = records.filter(StudentData.foundation_year == True,
                              current_year - StudentData.cohort - StudentData.repeated_years == year_value)

        records = nonf.union(foun)

    elif year_filter == 'grad':
        current_year = get_current_year()
        nonf = records.filter(StudentData.foundation_year == False,
                              current_year - StudentData.cohort + 1 - StudentData.repeated_years > DegreeType.duration)
        foun = records.filter(StudentData.foundation_year == True,
                              current_year - StudentData.cohort - StudentData.repeated_years > DegreeType.duration)

        records = nonf.union(foun)

    record_ids = [r[0] for r in records.all()]

    return ajax.user_approver.validate_data(record_ids, url=url, text=text)


@user_approver.route('/approve/<int:id>')
@roles_required('user_approver')
def approve(id):
    record = StudentData.query.get_or_404(id)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    record.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED
    record.validator_id = current_user.id
    record.validated_timestamp = datetime.now()
    db.session.commit()

    return redirect(url_for('user_approver.validate', url=url, text=text))


@user_approver.route('/reject/<int:id>')
@roles_required('user_approver')
def reject(id):
    record = StudentData.query.get_or_404(id)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    record.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_REJECTED
    record.validator_id = current_user.id
    record.validated_timestamp = datetime.now()
    db.session.commit()

    return redirect(url_for('user_approver.validate', url=url, text=text))


@user_approver.route('/correct')
@roles_accepted('user_approver', 'admin', 'root')
def correct():
    """
    Correct a student record that has been rejected for containing errors
    :return:
    """
    url = request.args.get('url', None)
    text = request.args.get('text', None)

    if url is None or text is None:
        url = request.referrer
        text = 'approvals dashboard'

    prog_filter = request.args.get('prog_filter')

    if prog_filter is None and session.get('user_approver_prog_filter'):
        prog_filter = session['user_approver_prog_filter']

    if prog_filter is not None:
        session['user_approver_prog_filter'] = prog_filter

    year_filter = request.args.get('year_filter')

    if year_filter is None and session.get('user_approver_year_filter'):
        year_filter = session['user_approver_year_filter']

    if year_filter is not None:
        session['user_approver_year_filter'] = year_filter

    prog_query = db.session.query(StudentData.programme_id).distinct().subquery()
    programmes = db.session.query(DegreeProgramme) \
        .join(prog_query, prog_query.c.programme_id == DegreeProgramme.id) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()

    return render_template('user_approver/correct.html', url=url, text=text, prog_filter=prog_filter,
                           year_filter=year_filter, programmes=programmes)


@user_approver.route('/correct_ajax')
@roles_accepted('user_approver', 'admin', 'root')
def correct_ajax():
    url = request.args.get('url', None)
    text = request.args.get('text', None)

    prog_filter = request.args.get('prog_filter')
    year_filter = request.args.get('year_filter')

    records = db.session.query(StudentData.id) \
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED,
                or_(and_(StudentData.last_edit_id == None, StudentData.creator_id == current_user.id),
                    and_(StudentData.last_edit_id != None, StudentData.last_edit_id == current_user.id)))

    flag, prog_value = is_integer(prog_filter)
    if flag:
        records = records.filter(StudentData.programme_id == prog_value)

    flag, year_value = is_integer(year_filter)
    if flag:
        current_year = get_current_year()
        nonf = records.filter(StudentData.foundation_year == False,
                              current_year - StudentData.cohort + 1 - StudentData.repeated_years == year_value)
        foun = records.filter(StudentData.foundation_year == True,
                              current_year - StudentData.cohort - StudentData.repeated_years == year_value)

        records = nonf.union(foun)

    elif year_filter == 'grad':
        current_year = get_current_year()
        nonf = records.filter(StudentData.foundation_year == False,
                              current_year - StudentData.cohort + 1 - StudentData.repeated_years > DegreeType.duration)
        foun = records.filter(StudentData.foundation_year == True,
                              current_year - StudentData.cohort - StudentData.repeated_years > DegreeType.duration)

        records = nonf.union(foun)

    record_ids = [r[0] for r in records.all()]

    return ajax.user_approver.correction_data(record_ids, url=url, text=text)
