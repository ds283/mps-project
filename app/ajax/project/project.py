#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, current_app

from sqlalchemy.event import listens_for

from ...database import db
from ...models import Project, EnrollmentRecord
from ...cache import cache

from urllib import parse


_project_name = \
"""
{% set offerable = project.is_offerable %}
<a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
    {{ project.name }}
</a>
{% if not offerable %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
{% if is_live %}
    <span class="label label-success">LIVE</span>
{% endif %}
{% if is_running %}
    <span class="label label-danger">RUNNING</span>
{% endif %}
{% if name_labels %}
    <p></p>
    {% for pclass in project.project_classes %}
        {% if pclass.active %}
            {% set style = pclass.make_CSS_style() %}
            <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }}</a>
        {% endif %}
    {% else %}
        <span class="label label-danger">No project classes</span>
    {% endfor %}
{% endif %}
{% if not offerable %}
    <p></p>
    {% set errors = project.errors %}
    {% set warnings = project.warnings %}
    {% if errors|length == 1 %}
        <span class="label label-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="label label-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="label label-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="label label-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="label label-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="label label-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="has-error">
            {% for item in errors %}
                {% if loop.index <= 5 %}
                    <p class="help-block">{{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="has-error">
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <p class="help-block">Warning: {{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
"""


_project_status = \
"""
{% if project.is_offerable %}
    {% if project.active %}
        <span class="label label-success"><i class="fa fa-check"></i> Project active</span>
    {% else %}
        <span class="label label-warning"><i class="fa fa-times"></i> Project inactive</span>
    {% endif %}
    {{ 'REPENROLLMENT'|safe }}
{% else %}
    <span class="label label-danger">Not available</span>
{% endif %}
"""


_project_pclasses = \
"""
{% for pclass in project.project_classes %}
    {% set style = pclass.make_CSS_style() %}
    <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
{% endfor %}
"""


_project_meetingreqd = \
"""
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    <span class="label label-danger">Required</span>
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="label label-warning">Optional</span>
{% elif project.meeting_reqd == project.MEETING_NONE %}
    <span class="label label-success">Not required</span>
{% else %}
    <span class="label label-default">Unknown</span>
{% endif %}
"""


_project_prefer = \
"""
{% for programme in project.ordered_programmes %}
    {% if programme.active %}
        {{ programme.short_label|safe }}
    {% endif %}
{% endfor %}
"""


_project_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
      {{ skill.short_label|safe }}
    {% endif %}
{% endfor %}
"""


_faculty_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
                <i class="fa fa-search"></i> Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Edit project</li>

        <li>
            <a href="{{ url_for('faculty.edit_project', id=project.id) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.edit_descriptions', id=project.id) }}">
                <i class="fa fa-pencil"></i> Descriptions...
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_assessors', id=project.id) }}">
                <i class="fa fa-cogs"></i> Assessors...
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_skills', id=project.id) }}">
                <i class="fa fa-cogs"></i> Transferable skills...
            </a>
        </li>

        <li>
            <a href="{{ url_for('faculty.attach_programmes', id=project.id) }}">
                <i class="fa fa-cogs"></i> Degree programmes...
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
            {% if project.active %}
                <a href="{{ url_for('faculty.deactivate_project', id=project.id) }}">
                    <i class="fa fa-wrench"></i> Make inactive
                </a>
            {% else %}
                <a href="{{ url_for('faculty.activate_project', id=project.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a>
            {% endif %}
        </li>
        {% if project.is_deletable %}
            <li>
                <a href="{{ url_for('faculty.delete_project', id=project.id) }}">
                    <i class="fa fa-trash"></i> Delete
                </a>
            </li>
        {% else %}
            <li class="disabled"><a>
                <i class="fa fa-trash"></i> Delete disabled
            </a></li>
        {% endif %}
    </ul>
</div>
"""


_convenor_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
                <i class="fa fa-search"></i> Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Edit project</li>

        <li>
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=pclass_id) }}">
                <i class="fa fa-pencil"></i> Descriptions...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=pclass_id, url=url_for('convenor.attached', id=pclass_id), text='convenor dashboard') }}">
                <i class="fa fa-cogs"></i> Assessors...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=pclass_id) }}">
                <i class="fa fa-cogs"></i> Transferable skills...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=pclass_id) }}">
                <i class="fa fa-cogs"></i> Degree programmes...
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fa fa-wrench"></i> Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


_unofferable_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
                <i class="fa fa-search"></i> Preview web page
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Edit project</li>

        <li>
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Descriptions...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=0, url=url_for('convenor.attached', id=0), text='convenor dashboard') }}">
                <i class="fa fa-cogs"></i> Assessors...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Transferable skills...
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=0) }}">
                <i class="fa fa-cogs"></i> Degree programmes...
            </a>
        </li>

        <li role="separator" class="divider"></li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-wrench"></i> Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


_attach_button = \
"""
<a href="{{ url_for('convenor.manual_attach_project', id=project.id, configid=config_id) }}" class="btn btn-warning btn-sm">
    <i class="fa fa-plus"></i> Manually attach
</a>
"""


_attach_other_button = \
"""
<a href="{{ url_for('convenor.manual_attach_other_project', id=project.id, configid=config_id) }}" class="btn btn-warning btn-sm">
    <i class="fa fa-plus"></i> Manually attach
</a>
"""



_menus = {'convenor': _convenor_menu,
          'faculty': _faculty_menu,
          'unofferable': _unofferable_menu,
          'attach': _attach_button,
          'attach_other': _attach_other_button,
          None: ''}


_flags = [(False, False, False), (False, False, True),
          (False, True, False), (False, True, True),
          (True, False, False), (True, False, True),
          (True, True, False), (True, True, True)]


_config_proxy = 999999999
_pclass_proxy = 888888888
_config_proxy_str = str(_config_proxy)
_pclass_proxy_str = str(_pclass_proxy)


@cache.memoize()
def _element(project_id, menu_template, is_running, is_live, name_labels):
    p = db.session.query(Project).filter_by(id=project_id).one()

    menu_string = _menus[menu_template]

    return {'name': render_template_string(_project_name, project=p, is_running=is_running, is_live=is_live,
                                           text='REPTEXT', url='REPURL', name_labels=name_labels),
             'owner': {
                 'display': '<a href="mailto:{em}">{nm}</a>'.format(em=p.owner.user.email, nm=p.owner.user.name),
                 'sortvalue': p.owner.user.last_name + p.owner.user.first_name},
             'status': render_template_string(_project_status, project=p),
             'pclasses': render_template_string(_project_pclasses, project=p),
             'meeting': render_template_string(_project_meetingreqd, project=p),
             'group': p.group.make_label(),
             'prefer': render_template_string(_project_prefer, project=p),
             'skills': render_template_string(_project_skills, skills=p.ordered_skills),
             'menu': render_template_string(menu_string, project=p, config_id=_config_proxy, pclass_id=_pclass_proxy,
                                            text='REPTEXT', url='REPURL')}


def _process(project_id, enrollment_id, menu_template, config, text_enc, url_enc, name_labels):
    p = db.session.query(Project).filter_by(id=project_id).one()
    if enrollment_id is not None:
        e = db.session.query(EnrollmentRecord).filter_by(id=enrollment_id).first()
    else:
        e = None

    is_running = (p.running_counterpart(config.id) is not None) if config is not None else False
    is_live = (p.live_counterpart(config.id) is not None) if config is not None else False

    record = _element(project_id, menu_template, is_running, is_live, name_labels)

    # need to replace text and url in 'name' field
    # need to replace text, url, config_id and pclass_id in 'menu' field
    # need to replace supervisor status in 'status' field
    name = record['name']
    status = record['status']
    menu = record['menu']

    if e is not None:
        status = status.replace('REPENROLLMENT', e.supervisor_label, 1)
    else:
        status = status.replace('REPENROLLMENT', '', 1)

    name = name.replace('REPTEXT', text_enc, 1).replace('REPURL', url_enc, 1)

    menu = menu.replace('REPTEXT', text_enc, 1).replace('REPURL', url_enc, 1)
    if config is not None:
        menu = menu.replace(_config_proxy_str, str(config.id), 1).replace(_pclass_proxy_str, str(config.pclass_id), 8)

    record.update({'name': name, 'status': status, 'menu': menu})
    return record


@listens_for(Project, 'before_update')
def _Project_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project, 'before_insert')
def _Project_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project, 'before_delete')
def _Project_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.project_classes, 'append')
def _Project_project_classes_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.project_classes, 'remove')
def _Project_project_classes_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.skills, 'append')
def _Project_skills_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.skills, 'remove')
def _Project_skills_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.programmes, 'append')
def _Project_programmes_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.programmes, 'remove')
def _Project_programmes_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.assessors, 'append')
def _Project_assessors_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(Project.assessors, 'remove')
def _Project_assessors_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, target.id, t, f[0], f[1], f[2])


@listens_for(EnrollmentRecord, 'before_update')
def _EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = db.session.query(Project.id).filter_by(owner_id=target.owner_id).all()
        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id[0], t, f[0], f[1], f[2])


@listens_for(EnrollmentRecord, 'before_insert')
def _EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = db.session.query(Project.id).filter_by(owner_id=target.owner_id).all()
        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id[0], t, f[0], f[1], f[2])


@listens_for(EnrollmentRecord, 'before_delete')
def _EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = db.session.query(Project.id).filter_by(owner_id=target.owner_id).all()
        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id[0], t, f[0], f[1], f[2])


def build_data(projects, menu_template=None, config=None, text=None, url=None, name_labels=False):
    bleach = current_app.extensions['bleach']

    def urlencode(s):
        s = s.encode('utf8')
        s = parse.quote_plus(s)
        return bleach.clean(s)

    url_enc = urlencode(url) if url is not None else ''
    text_enc = urlencode(text) if text is not None else ''

    data = [_process(p_id, e_id, menu_template, config, text_enc, url_enc, name_labels) for p_id, e_id in projects]

    return jsonify(data)
