#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, current_app

from ...database import db
from ...models import StudentData
from ...cache import cache

from sqlalchemy.event import listens_for

from ...shared.utils import get_current_year

from urllib import parse


_actions = \
"""
<a href="{{ url_for('manage_users.edit_student', id=s.id, url=url_for('user_approver.correct', url=url, text=text)) }}" class="btn btn-sm btn-secondary">Edit record...</a>
"""

_rejected = \
"""
{% if s.validated_by is not none %}
    <a href="mailto:{{ s.validated_by.email }}">{{ s.validated_by.name }}</a>
    {% if s.validated_timestamp is not none %}
        <p>{{ s.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</p>
    {% endif %}
{% else %}
    <span class="badge badge-default">None</span>
{% endif %}
"""


@cache.memoize()
def _element(record_id, current_year):
    r = db.session.query(StudentData).filter_by(id=record_id).one()

    return {'name': {'display': r.user.name,
                      'sortstring': r.user.last_name + r.user.first_name},
             'email': r.user.email,
             'exam_number': r.exam_number,
             'programme': r.programme.full_name,
             'year': r.academic_year_label(current_year, show_details=True),
             'rejected_by': render_template_string(_rejected, s=r),
             'menu': render_template_string(_actions, s=r, url='REPURL', text='REPTEXT')}


@listens_for(StudentData, 'before_insert')
def _StudentData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        current_year = get_current_year()
        cache.delete_memoized(_element, target.id, current_year)


@listens_for(StudentData, 'before_update')
def _StudentData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        current_year = get_current_year()
        cache.delete_memoized(_element, target.id, current_year)


@listens_for(StudentData, 'before_delete')
def _StudentData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        current_year = get_current_year()
        cache.delete_memoized(_element, target.id, current_year)


def correction_data(record_ids, url='', text=''):
    current_year = get_current_year()

    bleach = current_app.extensions['bleach']

    def urlencode(s):
        s = s.encode('utf8')
        s = parse.quote_plus(s)
        return bleach.clean(s)

    url_enc = urlencode(url) if url is not None else ''
    text_enc = urlencode(text) if text is not None else ''

    def update(d):
        d.update({'menu': d['menu'].replace('REPURL', url_enc, 1).replace('REPTEXT', text_enc, 1)})
        return d

    data = [update(_element(r_id, current_year)) for r_id in record_ids]

    return jsonify(data)
