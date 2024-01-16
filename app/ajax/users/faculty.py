#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, get_template_attribute
from sqlalchemy.event import listens_for

from .shared import menu, name, active
from ...cache import cache
from ...database import db
from ...models import User, FacultyData, EnrollmentRecord
from ...shared.utils import detuple


# language=jinja2
_affiliation = """
{% for group in f.affiliations %}
    {{ simple_label(group.make_label(group.name)) }}
{% endfor %}
"""


# language=jinja2
_enrolled = """
{% for record in f.enrollments %}
    {% set pclass = record.pclass %}
    {{ simple_label(pclass.make_label()) }}
{% endfor %}
"""


# language=jinja2
_settings = """
{% if f.sign_off_students %}
    <span class="badge bg-info">Require meetings</span>
{% endif %}
<span class="badge bg-primary">Default capacity {{ f.project_capacity }}</span>
{% if f.enforce_capacity %}
    <span class="badge bg-info">Enforce capacity</span>
{% endif %}
{% if f.show_popularity %}
    <span class="badge bg-info">Show popularity</span>
{% endif %}
<p>
{% if f.CATS_supervision is not none %}
    <span class="badge bg-warning text-dark">S: {{ f.CATS_supervision }} CATS</span>
{% else %}
    <span class="badge bg-secondary">S: Default CATS</span>
{% endif %}
{% if f.CATS_marking is not none %}
    <span class="badge bg-warning text-dark">Mk {{ f.CATS_marking }} CATS</span>
{% else %}
    <span class="badge bg-secondary">Mk: Default CATS</span>
{% endif %}
{% if f.CATS_moderation is not none %}
    <span class="badge bg-warning text-dark">Mo {{ f.CATS_moderation }} CATS</span>
{% else %}
    <span class="badge bg-secondary">Mo: Default</span>
{% endif %}
{% if f.CATS_presentation is not none %}
    <span class="badge bg-warning text-dark">P {{ f.CATS_presentation }} CATS</span>
{% else %}
    <span class="badge bg-secondary">P: Default CATS</span>
{% endif %}
"""


@cache.memoize()
def _element(user_id, current_user_id):
    f = db.session.query(FacultyData).filter_by(id=user_id).one()
    u = db.session.query(User).filter_by(id=user_id).one()
    cu = db.session.query(User).filter_by(id=current_user_id).one()

    simple_label = get_template_attribute("labels.html", "simple_label")

    return {
        "name": render_template_string(name, u=u, f=f, simple_label=simple_label),
        "active": render_template_string(active, u=u, simple_label=simple_label),
        "office": f.office,
        "settings": render_template_string(_settings, f=f),
        "affiliation": render_template_string(_affiliation, f=f, simple_label=simple_label),
        "enrolled": render_template_string(_enrolled, f=f, simple_label=simple_label),
        "menu": render_template_string(menu, user=u, cuser=cu, pane="faculty"),
    }


def _process(user_id, current_user_id):
    u = db.session.query(User).filter_by(id=user_id).one()

    record = _element(user_id, current_user_id)

    name = record["name"]
    if u.currently_active:
        name = name.replace("REPACTIVE", '<span class="badge bg-success">ACTIVE</span>', 1)
    else:
        name = name.replace("REPACTIVE", "", 1)

    record.update({"name": name})

    return record


def _delete_cache_entry(user_id):
    ids = db.session.query(User.id).filter_by(active=True).all()
    for id in ids:
        cache.delete_memoized(_element, user_id, id[0])


@listens_for(User, "before_insert")
def _User_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(User, "before_update")
def _User_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        if db.object_session(target).is_modified(target, include_collections=False):
            _delete_cache_entry(target.id)


@listens_for(User, "before_delete")
def _User_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(FacultyData, "before_update")
def _FacultyData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        # this turns out to be an extremely expensive flush, so we want to avoid it
        # unless the contents of FacultyData are really changed. We instrument the affiliations
        # collection separately, and we don't care about other collections such as 'assessor_for'
        if db.object_session(target).is_modified(target, include_collections=False):
            _delete_cache_entry(target.id)


@listens_for(FacultyData, "before_delete")
def _FacultyData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(FacultyData.affiliations, "append")
def _FacultyData_affiliations_insert_handler(target, value, initiator):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(FacultyData.affiliations, "remove")
def _FacultyData_affiliations_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(EnrollmentRecord, "before_insert")
def _EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


@listens_for(EnrollmentRecord, "before_update")
def _EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        if db.object_session(target).is_modified(target, include_collections=False):
            _delete_cache_entry(target.owner_id)


@listens_for(EnrollmentRecord, "before_delete")
def _EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


def build_faculty_data(current_user_id, faculty_ids):
    data = [_process(detuple(f_id), current_user_id) for f_id in faculty_ids]

    return data
