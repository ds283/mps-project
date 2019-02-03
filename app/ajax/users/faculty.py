#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

from ...database import db
from ...models import User, FacultyData, EnrollmentRecord
from ...cache import cache

from sqlalchemy.event import listens_for

from .shared import menu


_affiliation = \
"""
{% for group in f.affiliations %}
    {{ group.make_label(group.name)|safe }}
{% endfor %}
"""


_enrolled = \
"""
{% for record in f.enrollments %}
    {% set pclass = record.pclass %}
    {{ pclass.make_label()|safe }}
{% endfor %}
"""


_settings = \
"""
{% if f.sign_off_students %}
    <span class="label label-info">Require meetings</span>
{% endif %}
<span class="label label-primary">Default capacity {{ f.project_capacity }}</span>
{% if f.enforce_capacity %}
    <span class="label label-info">Enforce capacity</span>
{% endif %}
{% if f.show_popularity %}
    <span class="label label-info">Show popularity</span>
{% endif %}
<p>
{% if f.CATS_supervision %}
    <span class="label label-warning">CATS supv {{ f.CATS_supervision }}</span>
{% else %}
    <span class="label label-default">Default supervisory CATS</span>
{% endif %}
{% if f.CATS_markign %}
    <span class="label label-warning">CATS mark {{ f.CATS_marking }}</span>
{% else %}
    <span class="label label-default">Default marking CATS</span>
{% endif %}
"""


_name = \
"""
{{ u.name }}
<div>
    {% if u.theme == u.THEME_DEFAULT %}
        <span class="label label-primary">Default</span>
    {% elif u.theme == u.THEME_FLAT %}
        <span class="label label-primary">Flat</span>
    {% elif u.theme == u.THEME_DARK %}
        <span class="label label-primary">Dark</span>
    {% else %}
        <span class="label label-danger">Unknown theme</span>
    {% endif %}
</div>
<div>
    {% if f.is_convenor %}
        {% for item in f.convenor_list %}
            {{ item.make_label('Convenor ' + item.abbreviation)|safe }}
        {% endfor %}
    {% endif %}
</div>
"""


@cache.memoize()
def _element(user_id, current_user_id):
    f = db.session.query(FacultyData).filter_by(id=user_id).one()
    u = db.session.query(User).filter_by(id=user_id).one()
    cu = db.session.query(User).filter_by(id=current_user_id).one()

    return {'name': {
                'display': render_template_string(_name, u=u, f=f),
                'sortstring': u.last_name + u.first_name},
             'active': u.active_label,
             'office': f.office,
             'settings': render_template_string(_settings, f=f),
             'affiliation': render_template_string(_affiliation, f=f),
             'enrolled': render_template_string(_enrolled, f=f),
             'menu': render_template_string(menu, user=u, cuser=cu, pane='faculty')}


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


@listens_for(FacultyData, 'before_insert')
def _FacultyData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(FacultyData, 'before_update')
def _FacultyData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(FacultyData, 'before_delete')
def _FacultyData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.id)


@listens_for(EnrollmentRecord, 'before_insert')
def _EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.owner_id)


@listens_for(EnrollmentRecord, 'before_update')
def _EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.owner_id)


@listens_for(EnrollmentRecord, 'before_delete')
def _EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_element, target.owner_id)


def build_faculty_data(faculty_ids, current_user_id):
    data = [_element(f_id, current_user_id) for f_id in faculty_ids]

    return jsonify(data)
