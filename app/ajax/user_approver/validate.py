#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, current_app, get_template_attribute

from ...database import db
from ...models import StudentData
from ...cache import cache

from sqlalchemy.event import listens_for

from ...shared.utils import get_current_year

from urllib import parse


# language=jinja2
_actions = """
<a href="{{ url_for('user_approver.approve', id=s.id, url=url, text=text) }}" class="btn btn-sm btn-outline-success btn-table-block">Approve</a>
<a href="{{ url_for('user_approver.reject', id=s.id, url=url, text=text) }}" class="btn btn-sm btn-outline-danger btn-table-block">Reject</a>
"""

# language=jinja2
_academic_year = """
{{ simple_label(r.academic_year_label(show_details=True)) }}
"""


@cache.memoize()
def _element(record_id):
    r = db.session.query(StudentData).filter_by(id=record_id).one()

    simple_label = get_template_attribute("labels.html", "simple_label")

    return {
        "name": {"display": r.user.name, "sortstring": r.user.last_name + r.user.first_name},
        "email": r.user.email,
        "exam_number": r.exam_number,
        "registration_number": r.registration_number,
        "programme": r.programme.full_name,
        "year": render_template_string(_academic_year, r=r, simple_label=simple_label),
        "menu": render_template_string(_actions, s=r, url="REPURL", text="REPTEXT"),
    }


@listens_for(StudentData, "before_insert")
def _StudentData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(StudentData, "before_update")
def _StudentData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(StudentData, "before_delete")
def _StudentData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


def validate_data(record_ids, url="", text=""):
    bleach = current_app.extensions["bleach"]

    def urlencode(s):
        s = s.encode("utf8")
        s = parse.quote_plus(s)
        return bleach.clean(s)

    url_enc = urlencode(url) if url is not None else ""
    text_enc = urlencode(text) if text is not None else ""

    def update(d):
        d.update({"menu": d["menu"].replace("REPURL", url_enc, 2).replace("REPTEXT", text_enc, 2)})
        return d

    data = [update(_element(r_id)) for r_id in record_ids]

    return jsonify(data)
