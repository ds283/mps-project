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
def _element(user_id):
    u = db.session.query(User).filter_by(id=user_id).one()
    s = db.session.query(StudentData).filter_by(id=user_id).one()

    year = get_current_year()

    return {'name': {
                'display': render_template_string(name, u=u),
                'sortstring': u.last_name + u.first_name},
             'active': u.active_label,
             'programme': s.programme.label,
             'cohort': s.cohort_label,
             'acadyear': {
                 'display': s.academic_year_label(year),
                 'sortvalue': s.academic_year(year)},
             'menu': render_template_string(menu, user=u, pane='students')}


@listens_for(User, 'before_insert')
def _User_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(User, 'before_update')
def _User_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(User, 'before_delete')
def _User_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(StudentData, 'before_insert')
def _StudentData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(StudentData, 'before_update')
def _StudentData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(StudentData, 'before_delete')
def _StudentData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


def build_student_data(student_ids):
    data = [_element(s_id) for s_id in student_ids]

    return jsonify(data)
