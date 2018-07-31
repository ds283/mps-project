#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_meeting = \
"""
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    {% if project.meeting_confirmed(sel) %}
        <span class="label label-primary"><i class="fa fa-check"></i> Confirmed</span>
    {% else %}
        <span class="label label-danger"><i class="fa fa-times"></i> Required</span>
    {% endif %}
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="label label-warning">Optional</span>
{% else %}
    <span class="label label-default"><i class="fa fa-check"> Not required</span>
{% endif %}
"""

_status = \
"""
{% if project.is_available(sel) %}
    <span class="label label-success"><i class="fa fa-check"></i> Available for selection</span>
{% else %}
    {% if sel in project.confirm_waiting %}
        <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}" class="label label-warning">
            <i class="fa fa-times"></i> Cancel request
        </a>
    {% else %}
        <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}" class="label label-primary">
            <i class="fa fa-plus"></i> Request confirmation
        </a>
    {% endif %}
{% endif %}
"""

_bookmarks = \
"""
{% if sel.bookmarks.filter_by(liveproject_id=project.id).first() %}
    <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}"
       class="label label-primary">
       <i class="fa fa-times"></i> Remove
    </a>
{% else %}
    <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}"
       class="label label-default">
       <i class="fa fa-plus"></i> Add
    </a>
{% endif %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('student.view_project', sid=sel.id, pid=project.id) }}">
                View project
            </a>
        </li>
        <li>
            {% if sel.bookmarks.filter_by(liveproject_id=project.id).first() %}
                <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}">
                    Remove bookmark
                </a>
            {% else %}
                <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}">
                    Add bookmark
                </a>
            {% endif %}
        </li>
        <li {% if project.is_available(sel) %}class="disabled"{% endif %}>
            {% if not project.is_available(sel) %}
                {% if sel in project.confirm_waiting %}
                    <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}">
                        Cancel confirmation
                    </a>
                {% else %}
                    <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}">
                        Request confirmation
                    </a>
                {% endif %}
            {% else %}
                <a>Project available</a>
            {% endif %}
        </li>
    </ul>
</div>
"""

_project_prefer = \
"""
{% for programme in project.programmes %}
    {% if programme.active %}
        {{ programme.label()|safe }}
    {% endif %}
{% endfor %}
"""

_project_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
        {% if skill.group is none %}
            {{ skill.make_label()|safe }}
        {% else %}
            <a href="{{ url_for('student.add_skill_filter', id=sel.id, gid=skill.group.id) }}"
               class="label label-default" style="{{ skill.group.make_CSS_style() }}">
               {% if skill.group.add_group %}{{ skill.group.name }}:{% endif %}
               {{ skill.name }}
            </a>
        {% endif %}
    {% endif %}
{% endfor %}
"""

_project_group = \
"""
<a href="{{ url_for('student.add_group_filter', id=sel.id, gid=group.id) }}"
   class="label label-default" style="{{ group.make_CSS_style() }}">
   {{ group.name }}
</a>
"""

def liveprojects_data(sel, projects):
    data = [{'number': '{c}'.format(c=p.number),
             'name': '<a href="{url}">{name}</strong></a>'.format(name=p.name,
                                                                  url=url_for('student.view_project', sid=sel.id,
                                                                              pid=p.id)),
             'supervisor': '{name} <a href="mailto:{em}">{em}</a>'.format(name=p.owner.name,
                                                                         em=p.owner.email),
             'group': render_template_string(_project_group, sel=sel, group=p.group),
             'skills': render_template_string(_project_skills, sel=sel, skills=p.ordered_skills),
             'prefer': render_template_string(_project_prefer, project=p),
             'meeting': render_template_string(_meeting, sel=sel, project=p),
             'availability': render_template_string(_status, sel=sel, project=p),
             'bookmarks': render_template_string(_bookmarks, sel=sel, project=p),
             'menu': render_template_string(_menu, sel=sel, project=p)} for p in projects]

    return jsonify(data)
