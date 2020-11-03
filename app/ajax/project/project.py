#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, current_app, url_for

from sqlalchemy.event import listens_for

from ...database import db
from ...models import Project, EnrollmentRecord, ResearchGroup, SkillGroup, TransferableSkill, DegreeProgramme, \
    DegreeType, ProjectDescription, User, ProjectClassConfig
from ...cache import cache
from ...shared.utils import get_count

from urllib import parse


_project_name = \
"""
{% set offerable = project.is_offerable %}
<a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
    {{ project.name }}
</a>
{% if not offerable %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
<div>
    {{ 'REPNEWCOMMENTS'|safe }}
    {% if is_live %}
        <span class="badge badge-success">LIVE</span>
    {% endif %}
    {% if is_running %}
        <span class="badge badge-danger">RUNNING</span>
    {% endif %}
    {% set num = project.num_descriptions %}
    {% if num > 0 %}
        {% set pl = 's' %}{% if num == 1 %}{% set pl = '' %}{% endif %}
        <span class="badge badge-info">{{ num }} variant{{ pl }}</span>
    {% endif %}
</div>
{% if name_labels %}
    <div>
        {% for pclass in project.project_classes %}
            {% if pclass.active %}
                {% set style = pclass.make_CSS_style() %}
                <a class="badge badge-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }}</a>
            {% endif %}
        {% else %}
            <span class="badge badge-danger">No project classes</span>
        {% endfor %}
    </div>
{% endif %}
{% if not offerable %}
    <p></p>
    {% set errors = project.errors %}
    {% set warnings = project.warnings %}
    {% if errors|length == 1 %}
        <span class="badge badge-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="badge badge-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="badge badge-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="badge badge-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="badge badge-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="badge badge-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="error-block">
            {% for item in errors %}
                {% if loop.index <= 5 %}
                    <div class="error-message">{{ item }}</div>
                {% elif loop.index == 6 %}
                    <div class="error-message">Further errors suppressed...</div>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="error-block">
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <div class="error-message">Warning: {{ item }}</div>
                {% elif loop.index == 6 %}
                    <div class="error-message">Further errors suppressed...</div>
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
        <span class="badge badge-success"><i class="fas fa-check"></i> Project active</span>
    {% else %}
        <span class="badge badge-warning"><i class="fas fa-times"></i> Project inactive</span>
    {% endif %}
    {{ 'REPENROLLMENT'|safe }}
    {{ 'REPAPPROVAL'|safe }}
{% else %}
    <span class="badge badge-danger">Not available</span>
{% endif %}
"""


_project_pclasses = \
"""
{% for pclass in project.project_classes %}
    {% set style = pclass.make_CSS_style() %}
    <a class="badge badge-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
{% endfor %}
"""


_project_meetingreqd = \
"""
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    <span class="badge badge-danger">Required</span>
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="badge badge-warning">Optional</span>
{% elif project.meeting_reqd == project.MEETING_NONE %}
    <span class="badge badge-success">Not required</span>
{% else %}
    <span class="badge badge-secondary">Unknown</span>
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
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit project</div>

        <a class="dropdown-item" href="{{ url_for('faculty.edit_project', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.edit_descriptions', id=project.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Variants...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.attach_assessors', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.attach_skills', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Transferable skills...
        </a>
        <a class="dropdown-item" href="{{ url_for('faculty.attach_programmes', id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Degree programmes...
        </a>

        <div role="separator" class="dropdown-divider"></div>

        {% if project.active %}
            <a class="dropdown-item" href="{{ url_for('faculty.deactivate_project', id=project.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('faculty.activate_project', id=project.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
        {% if project.is_deletable %}
            <a class="dropdown-item" href="{{ url_for('faculty.delete_project', id=project.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item disabled">
                <i class="fas fa-trash fa-fw"></i> Delete disabled
            </a>
        {% endif %}
    </div>
</div>
"""


_convenor_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit project</div>

        <a class="dropdown-item" href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-cogs fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Variants...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=pclass_id, url=url_for('convenor.attached', id=pclass_id), text='convenor dashboard') }}">
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-cogs fa-fw"></i> Transferable skills...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=pclass_id) }}">
            <i class="fas fa-cogs fa-fw"></i> Degree programmes...
        </a>
        {% if not in_current %}
            <a class="dropdown-item" href="{{ url_for('convenor.inject_liveproject', pid=project.id, pclass_id=pclass_id) }}">
                <i class="fas fa-cogs fa-fw"></i> Generate LiveProject...
            </a>
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>

        {% if project.active %}
            <a class="dropdown-item" href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=pclass_id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


_unofferable_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit project</div>

        <a class="dropdown-item" href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=0) }}">
            <i class="fas fa-cogs fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.edit_descriptions', id=project.id, pclass_id=0) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Variants...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.attach_assessors', id=project.id, pclass_id=0, url=url_for('convenor.attached', id=0), text='convenor dashboard') }}">
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=0) }}">
            <i class="fas fa-cogs fa-fw"></i> Transferable skills...
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=0) }}">
            <i class="fas fa-cogs fa-fw"></i> Degree programmes...
        </a>

        <div role="separator" class="dropdown-divider"></div>

        {% if project.active %}
            <a class="dropdown-item" href="{{ url_for('convenor.deactivate_project', id=project.id, pclass_id=0) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('convenor.activate_project', id=project.id, pclass_id=0) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


_attach_button = \
"""
<a href="{{ url_for('convenor.manual_attach_project', id=project.id, configid=config_id) }}" class="btn btn-warning btn-sm">
    <i class="fas fa-plus"></i> Manually attach
</a>
"""


_attach_other_button = \
"""
<a href="{{ url_for('convenor.manual_attach_other_project', id=project.id, configid=config_id) }}" class="btn btn-warning btn-sm">
    <i class="fas fa-plus"></i> Manually attach
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
def _element(project_id, menu_template, is_running, is_live, in_current, name_labels):
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
             'group': p.group.make_label() if p.group is not None \
                 else '<span class="badge badge-warning">Missing research group</span>',
             'prefer': render_template_string(_project_prefer, project=p),
             'skills': render_template_string(_project_skills, skills=p.ordered_skills),
             'menu': render_template_string(menu_string, project=p, config_id=_config_proxy, pclass_id=_pclass_proxy,
                                            in_current=in_current, text='REPTEXT', url='REPURL')}


def _process(project_id, enrollment_id, current_user_id, menu_template, config, text_enc, url_enc, name_labels,
             show_approvals):
    p = db.session.query(Project).filter_by(id=project_id).one()

    if enrollment_id is not None:
        e = db.session.query(EnrollmentRecord).filter_by(id=enrollment_id).first()
    else:
        e = None

    is_running = (p.running_counterpart(config.id) is not None) if config is not None else False
    is_live = (p.live_counterpart(config.id) is not None) if config is not None else False
    in_current = (p.prior_counterpart(config.id) is not None) if config is not None else False

    # _element is cached
    record = _element(project_id, menu_template, is_running, is_live, in_current, name_labels)

    # need to replace text and url in 'name' field
    # need to replace text, url, config_id and pclass_id in 'menu' field
    # need to replace supervisor status in 'status' field
    # need to replace new comment notification in 'name' field
    name = record['name']
    status = record['status']
    menu = record['menu']

    name = name.replace('REPTEXT', text_enc, 1).replace('REPURL', url_enc, 1)

    status = replace_enrollment_text(e, status)
    name = replace_comment_notification(current_user_id, name, p)
    status = replace_approval_tags(p, show_approvals, config, status)
    menu = replace_menu_anchor(text_enc, url_enc, config, menu)

    record.update({'name': name, 'status': status, 'menu': menu})
    return record


def replace_menu_anchor(text_enc, url_enc, config, menu):
    menu = menu.replace('REPTEXT', text_enc, 1).replace('REPURL', url_enc, 1)

    if config is not None:
        menu = menu.replace(_config_proxy_str, str(config.id), 1).replace(_pclass_proxy_str, str(config.pclass_id), 8)

    return menu


def replace_approval_tags(p: Project, show_approvals: bool, config: ProjectClassConfig, status: str):
    repapprove = ''

    # if the project is not active, there is no need to do anything with its approval tag;
    # just replace it by nothing. You can't approve an inactive project.
    # Also, check that at least one project class this project belongs to is published
    published = p.project_classes.filter_by(publish=True).first() is not None
    if show_approvals:
        if p.active and published:

            # if no config supplied, we don't know which project class we are looking at and therefore which
            # description is relevant. So we must describe the project as a whole
            if config is None:
                state = p.approval_state

                if state == Project.DESCRIPTIONS_APPROVED:
                    repapprove = '<span class="badge badge-success"><i class="fas fa-check"></i> Approval: All approved</span>'
                elif state == Project.SOME_DESCRIPTIONS_QUEUED:
                    repapprove = '<span class="badge badge-warning">Approval: Some queued</span>'
                elif state == Project.SOME_DESCRIPTIONS_REJECTED:
                    repapprove = '<span class="badge badge-info">Approval: Some rejected</span>'
                elif state == Project.SOME_DESCRIPTIONS_UNCONFIRMED:
                    repapprove = '<span class="badge badge-secondary">Approval: Some unconfirmed</span>'
                elif state == Project.APPROVALS_NOT_ACTIVE:
                    repapprove = ''
                elif state == Project.APPROVALS_NOT_OFFERABLE:
                    repapprove = '<span class="badge badge-danger">Approval: Not offerable/span>'
                else:
                    repapprove = '<span class="badge badge-danger">Unknown approval state</span>'

            # otherwise, we can pick the correct description
            else:
                desc = p.get_description(config.pclass_id)

                if desc is None:
                    repapprove = '<span class="badge badge-secondary">Approval: No description</span>'
                else:
                    state = desc.workflow_state
                    if desc.requires_confirmation and not desc.confirmed:
                        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
                            repapprove = """<div class="dropdown" style="display: inline-block;">
                                                <a class="badge badge-light dropdown-toggle" data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">Approval: Not confirmed</a>
                                                <div class="dropdown-menu">
                                                    <a class="dropdown-item" href="{url}"><i class="fas fa-check fa-fw"></i> Confirm</a>
                                                </div>
                                            </div>""".format(url=url_for('convenor.confirm_description', config_id=config.id, did=desc.id))
                        else:
                            repapprove = '<span class="badge badge-secondary">Approval: Not confirmed</span>'
                    else:
                        if state == ProjectDescription.WORKFLOW_APPROVAL_VALIDATED:
                            repapprove = '<span class="badge badge-success"><i class="fas fa-check"></i> Approval: Approved</span>'
                        elif state == ProjectDescription.WORKFLOW_APPROVAL_QUEUED:
                            repapprove = '<span class="badge badge-warning">Approval: Queued</span>'
                        elif state == ProjectDescription.WORKFLOW_APPROVAL_REJECTED:
                            repapprove = '<span class="badge badge-danger">Approval: Rejected</span>'
                        else:
                            repapprove = '<span class="badge badge-danger">Unknown approval state</span>'

                        if desc.validated_by:
                            repapprove += ' <span class="badge badge-info">Signed-off: ' + desc.validated_by.name + '</span>'
                            if desc.validated_timestamp:
                                repapprove += ' <span class="badge badge-info">' + desc.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") + '</span>'
        else:
            repapprove = '<span class="badge badge-secondary"><i class="fas fa-ban"></i> Can\'t approve</span>'

    status = status.replace('REPAPPROVAL', repapprove, 1)
    return status


def replace_comment_notification(current_user_id, name, p):
    repcomments = ''

    if current_user_id is not None:
        u = db.session.query(User).filter_by(id=current_user_id).one()
        if p.has_new_comments(u):
            repcomments = '<span class="badge badge-warning">New comments</span>'

    name = name.replace('REPNEWCOMMENTS', repcomments, 1)
    return name


def replace_enrollment_text(e, status):
    repenroll = ''

    if e is not None:
        repenroll = e.supervisor_label

    status = status.replace('REPENROLLMENT', repenroll, 1)
    return status


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


@listens_for(ProjectDescription, 'before_insert')
def _ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_id = target.parent_id
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


@listens_for(ProjectDescription, 'before_update')
def _ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_id = target.parent_id
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


@listens_for(ProjectDescription, 'before_delete')
def _ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_id = target.parent_id
        for t in _menus:
            for f in _flags:
                cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


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


@listens_for(ResearchGroup, 'before_update')
def _ResearchGroup_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for project in target.projects:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, project.id, t, f[0], f[1], f[2])


@listens_for(ResearchGroup, 'before_delete')
def _ResearchGroup_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for project in target.projects:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, project.id, t, f[0], f[1], f[2])


@listens_for(TransferableSkill, 'before_update')
def _TransferableSkill_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for project in target.projects:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, project.id, t, f[0], f[1], f[2])


@listens_for(TransferableSkill, 'before_delete')
def _TransferableSkill_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for project in target.projects:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, project.id, t, f[0], f[1], f[2])


@listens_for(SkillGroup, 'before_update')
def _SkillGroup_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = set()
        for skill in target.skills:
            for project in skill.projects:
                p_ids.add(project.id)

        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


@listens_for(SkillGroup, 'before_delete')
def _SkillGroup_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = set()
        for skill in target.skills:
            for project in skill.projects:
                p_ids.add(project.id)

        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


@listens_for(DegreeProgramme, 'before_update')
def _DegreeProgramme_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for project in target.projects:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, project.id, t, f[0], f[1], f[2])


@listens_for(DegreeProgramme, 'before_delete')
def _DegreeProgramme_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        for project in target.projects:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, project.id, t, f[0], f[1], f[2])


@listens_for(DegreeType, 'before_update')
def _DegreeType_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = set()
        for programme in target.degree_programmes:
            for project in programme.projects:
                p_ids.add(project.id)

        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


@listens_for(DegreeType, 'before_delete')
def _DegreeType_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        p_ids = set()
        for programme in target.degree_programmes:
            for project in programme.projects:
                p_ids.add(project.id)

        for p_id in p_ids:
            for t in _menus:
                for f in _flags:
                    cache.delete_memoized(_element, p_id, t, f[0], f[1], f[2])


def build_data(projects, current_user_id=None, menu_template=None, config=None, text=None, url=None, name_labels=False,
               show_approvals=True):
    bleach = current_app.extensions['bleach']

    def urlencode(s):
        s = s.encode('utf8')
        s = parse.quote_plus(s)
        return bleach.clean(s)

    url_enc = urlencode(url) if url is not None else ''
    text_enc = urlencode(text) if text is not None else ''

    data = [_process(p_id, e_id, current_user_id, menu_template, config, text_enc, url_enc, name_labels, show_approvals)
            for p_id, e_id in projects]

    return jsonify(data)
