#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ...shared.utils import get_current_year
from flask import render_template_string, jsonify

from ...database import db
from ...models import User, StudentData
from ...cache import cache

from sqlalchemy.event import listens_for

from .shared import menu, name


@cache.memoize()
def _element(user_id, current_user_id):
    s = db.session.query(StudentData).filter_by(id=user_id).one()
    u = db.session.query(User).filter_by(id=user_id).one()
    cu = db.session.query(User).filter_by(id=current_user_id).one()

    return {'name': {
                'display': render_template_string(name, u=u),
                'sortstring': u.last_name + u.first_name},
             'active': u.active_label,
             'programme': s.programme.label,
             'cohort': s.cohort_label,
             'acadyear': {
                 'display': s.academic_year_label(show_details=True),
                 'sortvalue': s.academic_year},
             'menu': render_template_string(menu, user=u, cuser=cu, pane='students')}


def _process(user_id, current_user_id):
    u = db.session.query(User).filter_by(id=user_id).one()

    record = _element(user_id, current_user_id)

    name = record['name']
    display = name['display']
    if u.currently_active:
        display = display.replace('REPACTIVE', '<span class="badge badge-success">ACTIVE</span>', 1)
    else:
        display = display.replace('REPACTIVE', '', 1)

    name.update({'display': display})
    record.update({'name': name})

    return record


@listens_for(User, 'before_insert')
def _User_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(User, 'before_update')
def _User_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        if db.object_session(target).is_modified(target, include_collections=False):
            ids = db.session.query(User.id).filter_by(active=True).all()
            for id in ids:
                cache.delete_memoized(_element, target.id, id[0])


@listens_for(User, 'before_delete')
def _User_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(StudentData, 'before_insert')
def _StudentData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


@listens_for(StudentData, 'before_update')
def _StudentData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        if db.object_session(target).is_modified(target, include_collections=False):
            ids = db.session.query(User.id).filter_by(active=True).all()
            for id in ids:
                cache.delete_memoized(_element, target.id, id[0])


@listens_for(StudentData, 'before_delete')
def _StudentData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        ids = db.session.query(User.id).filter_by(active=True).all()
        for id in ids:
            cache.delete_memoized(_element, target.id, id[0])


def build_student_data(student_ids, current_user_id):
    data = [_process(s_id, current_user_id) for s_id in student_ids]

    return jsonify(data)
