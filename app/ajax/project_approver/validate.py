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

from ...database import db
from ...models import ProjectDescription
from ...cache import cache

from sqlalchemy.event import listens_for

from ...shared.utils import get_current_year

from urllib import parse


_actions = \
"""
<a href="{{ url_for('project_approver.approve', id=r.id, url=url, text=text) }}" class="btn btn-sm btn-success">Approve</a>
<a href="{{ url_for('project_approver.reject', id=r.id, url=url, text=text) }}" class="btn btn-sm btn-danger">Reject</a>
"""


_title = \
"""
{% set pclass = r.parent.project_classes.first() %}
{% set disabled = (pclass is none) %}
<a {% if not disabled %}href="{{ url_for('faculty.project_preview', id=r.parent.id, pclass=pclass.id, show_selector=0, url=url, text=text) }}"{% endif %}>
    {%- if r.parent -%}{{ r.parent.name }}{%- else -%}<unnamed project>{%- endif -%}/{%- if r.label -%}{{ r.label }}{%- else -%}<unnamed description>{%- endif -%}
</a> 
"""


_owner = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
"""


_pclasses = \
"""
{% set ns = namespace(count=0) %}
{% if r.default is not none %}
    <span class="label label-success">Default</span>
    {% set ns.count = ns.count + 1 %}
{% endif %}
{% for pclass in r.project_classes %}
    {% if pclass.active %}
        {% set style = pclass.make_CSS_style() %}
        <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
        {% set ns.count = ns.count + 1 %}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default">None</span>
{% endif %}
{% if r.has_modules %}
    <p></p>
    <span class="label label-primary"><i class="fa fa-exclamation-circle"></i> Has recommended modules</span>
{% endif %}
"""


@cache.memoize()
def _element(r_id):
    record = db.session.query(ProjectDescription).filter_by(id=r_id).one()

    return {'name': render_template_string(_title, r=record, url='REPURL', text='REPTEXT'),
            'owner': render_template_string(_owner, f=record.parent.owner),
            'pclasses': render_template_string(_pclasses, r=record),
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
        d.update({'menu': d['menu'].replace('REPURL', url_enc, 2).replace('REPTEXT', text_enc, 2)})
        return d

    data = [update(_element(r_id)) for r_id in record_ids]

    return jsonify(data)
