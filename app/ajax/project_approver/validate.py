#
# Created by David Seery on 2019-02-24.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, current_app
from .common import title, owner, pclasses

from ...database import db
from ...models import ProjectDescription
from ...cache import cache

from sqlalchemy.event import listens_for

from ...shared.utils import get_current_year

from urllib import parse


_actions = \
"""
<a href="{{ url_for('project_approver.approve', id=r.id, url=url) }}" class="btn btn-sm btn-success btn-table-block">Approve</a>
<a href="{{ url_for('project_approver.reject', id=r.id, url=url) }}" class="btn btn-sm btn-danger btn-table-block">Reject</a>
"""


@cache.memoize()
def _element(r_id):
    record = db.session.query(ProjectDescription).filter_by(id=r_id).one()

    return {'name': render_template_string(title, r=record, url='REPURL', text='REPTEXT'),
            'owner': render_template_string(owner, f=record.parent.owner),
            'pclasses': render_template_string(pclasses, r=record),
            'menu': render_template_string(_actions, r=record, url='REPURL', text='REPTEXT')}


@listens_for(ProjectDescription, 'before_insert')
def _ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription, 'before_update')
def _ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription, 'before_delete')
def _ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription.project_classes, 'append')
def _ProjectDescription_project_classes_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription.project_classes, 'remove')
def _ProjectDescription_project_classes_delete_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription.team, 'append')
def _ProjectDescription_team_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription.team, 'remove')
def _ProjectDescription_team_delete_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription.modules, 'append')
def _ProjectDescription_modules_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(ProjectDescription.modules, 'remove')
def _ProjectDescription_modules_delete_handler(target, value, initiator):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


def validate_data(record_ids, url='', text=''):
    bleach = current_app.extensions['bleach']

    def urlencode(s):
        s = s.encode('utf8')
        s = parse.quote_plus(s)
        return bleach.clean(s)

    url_enc = urlencode(url) if url is not None else ''
    text_enc = urlencode(text) if text is not None else ''

    def update(d):
        d.update({'name': d['name'].replace('REPURL', url_enc, 1).replace('REPTEXT', text_enc, 1)})
        d.update({'menu': d['menu'].replace('REPURL', url_enc, 2)})
        return d

    data = [update(_element(r_id)) for r_id in record_ids]

    return jsonify(data)
