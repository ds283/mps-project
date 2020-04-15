#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_status = \
"""
{% if m.finished %}
    <span class="label label-primary">Finished</span>
    {% if m.solution_usable %}
        <span class="label label-success">Optimal solution</span>
    {% elif m.outcome == m.OUTCOME_NOT_SOLVED %}
        <span class="label label-warning">Not solved</span>
    {% elif m.outcome == m.OUTCOME_INFEASIBLE %}
        <span class="label label-danger">Infeasible</span>
    {% elif m.outcome == m.OUTCOME_UNBOUNDED %}
        <span class="label label-danger">Unbounded</span>
    {% elif m.outcome == m.OUTCOME_UNDEFINED %}
        <span class="label label-danger">Undefined</span>
    {% else %}
        <span class="label label-danger">Unknown outcome</span>
    {% endif %}
    <p></p>
    {% if m.is_modified %}
        <span class="label label-warning">Modified</span>
    {% else %}
        <span class="label label-success">Original</span>
    {% endif %}
    <p></p>
    {% if m.solution_usable %}
        {% if m.draft_to_selectors is not none %}
            <span class="label label-info">Draft to selectors: {{ m.draft_to_selectors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if m.draft_to_supervisors is not none %}
            <span class="label label-info">Draft to supervisors: {{ m.draft_to_supervisors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if m.final_to_selectors is not none %}
            <span class="label label-primary">Final to selectors: {{ m.final_to_selectors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if m.final_to_supervisors is not none %}
            <span class="label label-primary">Final to supervisors: {{ m.final_to_supervisors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
    {% endif %}
    <p></p>
    {% if m.published and current_user.has_role('root') %}
        <span class="label label-primary">Published</span>
    {% endif %}
    {% if m.selected %}
        <span class="label label-success">Selected</span>
    {% endif %}
{% else %}
    {% if m.awaiting_upload %}
        <span class="label label-success">Awaiting upload</span>
        {% if m.lp_file is not none %}
            <a href="{{ url_for('admin.download_generated_asset', asset_id=m.lp_file.id) }}">LP</a>
        {% endif %}
        {% if m.mps_file is not none %}
            <a href="{{ url_for('admin.download_generated_asset', asset_id=m.mps_file.id) }}">MPS</a>
        {% endif %}
    {% else %}
        <span class="label label-success">In progress</span>
    {% endif %}
{% endif %}
"""

_info = \
"""
<span class="label label-primary">Supervisor <i class="fa fa-chevron-circle-down"></i> {{ m.supervising_limit }} CATS</span>
<span class="label label-info">2nd mark <i class="fa fa-chevron-circle-down"></i> {{ m.marking_limit }} CATS</span>
<span class="label label-info">Marker multiplicity <i class="fa fa-chevron-circle-down"></i> {{ m.max_marking_multiplicity }}</span>
{% if m.ignore_per_faculty_limits %}
    <span class="label label-warning"><i class="fa fa-times"></i> Ignore per-faculty limits</span>
{% else %}
    <span class="label label-default"><i class="fa fa-check"></i> Apply per-faculty limits</span>
{% endif %}
{% if m.ignore_programme_prefs %}
    <span class="label label-warning"><i class="fa fa-times"></i> Ignore programmes prefs/span>
{% else %}
    <span class="label label-default"><i class="fa fa-check"></i> Apply programme prefs</span>
{% endif %}
{% if m.include_only_submitted %}
    <span class="label label-warning"><i class="fa fa-times"></i> Only submitted selectors</span>
{% else %}
    <span class="label label-default"><i class="fa fa-check"></i> All selectors</span>
{% endif %}
<div>
    <span class="label label-success">Solver {{ m.solver_name }}</span>
</div>
<div>
    <div>Matching</div>
    <span class="label label-default">Programme {{ m.programme_bias }}</span>
    <span class="label label-default">Bookmarks {{ m.bookmark_bias }}</span>
</div>
<div>
    <div>Biases</div>
    <span class="label label-default">Levelling {{ m.levelling_bias }}</span>
    <span class="label label-default">Group tension {{ m.intra_group_tension }}</span>
    <span class="label label-default">S pressure {{ m.supervising_pressure }}</span>
    <span class="label label-default">M pressure {{ m.marking_pressure }}</span>
</div>
<div>
    <div>Penalties</div>
    <span class="label label-default">CATS violation {{ m.CATS_violation_penalty }}</span>
    <span class="label label-default">No assignment {{ m.no_assignment_penalty }}</span>
</div>
<p></p>
{% if m.use_hints %}
    <span class="label label-success"><i class="fa fa-check"></i> Use hints</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Ignore hints</span>
{% endif %}
<span class="label label-default">Encourage <i class="fa fa-times"></i> {{ m.encourage_bias }}</span>
<span class="label label-default">Discourage <i class="fa fa-times"></i> {{ m.discourage_bias }}</span>
<span class="label label-default">Strong encourage <i class="fa fa-times"></i> {{ m.strong_encourage_bias }}</span>
<span class="label label-default">Strong discourage <i class="fa fa-times"></i> {{ m.strong_discourage_bias }}</span>
<p></p>
{% if not m.ignore_programme_prefs %}
    {% set outcome = m.prefer_programme_status %}
    {% if outcome is not none %}
        {% set match, fail = outcome %}
        {% set match_pl = 's' %}{% if match == 1 %}{% set match_pl = '' %}{% endif %}
        {% set fail_pl = 's' %}{% if fail == 1 %}{% set fail_pl = '' %}{% endif %}
        <div>
            <span class="label {% if match > 0 %}label-success{% else %}label-default{% endif %}">Matched {{ match }} programme pref{{ match_pl }}</span>
            <span class="label {% if fail > 0 %}label-warning{% elif match > 0 %}label-success{% else %}label-default{% endif %}">Failed {{ fail }} programme pref{{ fail_pl }}</span>
        </div>
    {% endif %}
{% endif %}
{% if m.use_hints %}
    {% set outcome = m.hint_status %}
    {% if outcome is not none %}
        {% set satisfied, violated = outcome %}
        {% set satisfied_pl = 's' %}{% if satisfied == 1 %}{% set satisfied_pl = '' %}{% endif %}
        {% set violated_pl = 's' %}{% if violated == 1 %}{% set violated_pl = '' %}{% endif %}
        <div>
            <span class="label {% if satisfied > 0 %}label-success{% else %}label-default{% endif %}">Satisfied {{ satisfied }} hint{{ satisfied_pl }}</span>
            <span class="label {% if violated > 0 %}label-warning{% elif satisfied > 0 %}label-success{% else %}label-default{% endif %}">Violated {{ violated }} hint{{ violated_pl }}</span>
        </div>
    {% endif %}
{% endif %}
<div style="padding-top: 5px;">
    Created by
    <a href="mailto:{{ m.created_by.email }}">{{ m.created_by.name }}</a>
    on
    {% if m.creation_timestamp is not none %}
        {{ m.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% else %}
        <span class="label label-default">Unknown</span>
    {% endif %}
    {% if m.last_edited_by is not none %}
        <p></p>
        Last edited by 
        <a href="mailto:{{ m.last_edited_by.email }}">{{ m.last_edited_by.name }}</a>
        {% if m.last_edit_timestamp is not none %}
            {{ m.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    {% endif %}
</div>
<p></p>
{% set errors = m.errors %}
{% set warnings = m.warnings %}
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
            {% if loop.index <= 10 %}
                <p class="help-block">{{ item }}</p>
            {% elif loop.index == 11 %}
                <p class="help-block">...</p>
            {% endif %}            
        {% endfor %}
    </div>
{% endif %}
{% if warnings|length > 0 %}
    <div class="has-error">
        {% for item in warnings %}
            {% if loop.index <= 10 %}
                <p class="help-block">Warning: {{ item }}</p>
            {% elif loop.index == 11 %}
                <p class="help-block">...</p>
            {% endif %}
        {% endfor %}
    </div>
{% endif %}
"""


_score = \
"""
{% if m.solution_usable %}
    <span class="label label-success">Score {{ m.score }} original</span>
    {% set score = m.current_score %}
    {% if score %}
        <span class="label label-primary">Score {{ score|round(precision=2) }} now</span>
    {% else %}
        <span class="label label-warning">Current score undefined</span>
    {% endif %}
    <p></p>
    <span class="label label-info">&delta; max {{ m.delta_max }}</span>
    <span class="label label-info">&delta; min {{ m.delta_min }}</span>
    <span class="label label-primary">CATS max {{ m.CATS_max }}</span>
    <span class="label label-primary">CATS min {{ m.CATS_min }}</span>
{% else %}
    <span class="label label-default">Invalid</span>
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
    <ul class="dropdown-menu dropdown-menu-right">
        {% if m.finished and m.solution_usable %}
            <li>
                <a href="{{ url_for('admin.match_student_view', id=m.id, text=text, url=url) }}">
                    <i class="fa fa-search"></i> Inspect match...
                </a>
            </li>
            <li role="separator" class="divider">
        {% endif %}    
        
        {% if not m.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if m.awaiting_upload %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('admin.upload_match', match_id=m.id) }}"{% endif %}>
                        <i class="fa fa-cloud-upload"></i> Upload solution...
                    </a>
                </li>
            {% endif %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('admin.duplicate_match', id=m.id) }}"{% endif %}>
                    <i class="fa fa-clone"></i> Duplicate
                </a>
            </li>
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('admin.terminate_match', id=m.id) }}"{% endif %}>
                    <i class="fa fa-hand-paper-o"></i> Terminate
                </a>
            </li>
        {% else %}
            {% if m.solution_usable %}
                <li>
                    <a href="{{ url_for('admin.rename_match', id=m.id, url=url) }}">
                        <i class="fa fa-exchange"></i> Rename...
                    </a>
                </li>
                {% if m.is_modified %}
                    <li>
                        <a href="{{ url_for('admin.revert_match', id=m.id) }}">
                            <i class="fa fa-undo"></i> Revert to original
                        </a>
                    </li>
                {% endif %}
                <li>
                    <a href="{{ url_for('admin.duplicate_match', id=m.id) }}">
                        <i class="fa fa-clone"></i> Duplicate
                    </a>
                </li>
                <li>
                    <a href="{{ url_for('admin.compare_match', id=m.id, text=text, url=url) }}">
                        <i class="fa fa-balance-scale"></i> Compare to...
                    </a>
                </li>
                {% if is_root %}
                    <li>
                        <a href="{{ url_for('admin.create_match', base_id=m.id) }}">
                            <i class="fa fa-plus-circle"></i> Use as base...
                        </a>
                    </li>
                {% endif %}
            {% else %}
                <li class="disabled">
                    <a><i class="fa fa-times"></i> Solution is not usable</a>
                </li>
            {% endif %}

            {% if current_user.has_role('root') or current_user.id == m.creator_id %}
                <li>
                    <a href="{{ url_for('admin.delete_match', id=m.id) }}">
                        <i class="fa fa-trash"></i> Delete
                    </a>
                </li>
                <li>
                    {% if m.can_clean_up %}
                        <a href="{{ url_for('admin.clean_up_match', id=m.id) }}">
                            <i class="fa fa-scissors"></i> Clean up
                        </a>
                    {% endif %}
                </li>
            {% endif %}
            
            {% if current_user.has_role('root') %}
                <li role="separator" class="divider">
                <li class="dropdown-header">Superuser functions</li>
                
                {% if m.published %}
                    <li>
                        <a href="{{ url_for('admin.unpublish_match', id=m.id) }}">
                            <i class="fa fa-stop-circle"></i> Unpublish
                        </a>
                    </li>
                {% else %}
                    <li>
                        <a href="{{ url_for('admin.publish_match', id=m.id) }}">
                            <i class="fa fa-share"></i> Publish to convenors
                        </a>
                    </li>
                {% endif %}
                
                {% if m.selected %}
                    <li>
                        <a href="{{ url_for('admin.deselect_match', id=m.id) }}">
                            <i class="fa fa-times"></i> Deselect
                        </a>
                    </li>
                {% else %}
                    <li>
                        <a href="{{ url_for('admin.select_match', id=m.id, force=0) }}">
                            <i class="fa fa-check"></i> Select
                        </a>
                    </li>
                {% endif %}
                
                {% if m.selected or m.published %}
                    <li role="separator" class="divider">
                    <li>
                        <a href="{{ url_for('admin.publish_matching_selectors', id=m.id) }}">
                            <i class="fa fa-envelope-o"></i> Email to selectors
                        </a>
                    </li>
                    <li>
                        <a href="{{ url_for('admin.publish_matching_supervisors', id=m.id) }}">
                            <i class="fa fa-envelope-o"></i> Email to supervisors
                        </a>
                    </li>
                {% endif %}
            {% endif %}            
        {% endif %}        
    </ul>
</div>
"""


_name = \
"""
<div>
    {% if m.finished and m.solution_usable %}
        <a href="{{ url_for('admin.match_student_view', id=m.id, text=text, url=url) }}">{{ m.name }}</a>
        {% if not m.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    {% else %}
        {{ m.name }}
    {% endif %}
</div>
<p></p>
{% for config in m.config_members %}
    {% set pclass = config.project_class %}
    {{ pclass.make_label(pclass.abbreviation)|safe }}
{% endfor %}
{% if m.finished %}
    <p></p>
    <span class="label label-info">{{ m.records.count() }} selectors</span>
    <span class="label label-info">{{ m.supervisors.count() }} supervisors</span>
    <span class="label label-info">{{ m.markers.count() }} markers</span>
    <span class="label label-info">{{ m.projects.count() }} projects</span>
{% endif %}
{% set has_extra_matches = m.include_matches.first() is not none or m.base is not none %}
{% if has_extra_matches %}
    <p></p>
    {% if m.base is not none %}
        <span class="label label-success"><i class="fa fa-plus-circle"></i> Base: {{ m.base.name }}</span>
        {% if m.force_base %}
            <span class="label label-info">Force match</span>
        {% else %}
            <span class="label label-info">Bias {{ m.base_bias }}</span>
        {% endif %}
    {% endif %}
    {% for match in m.include_matches %}
        <span class="label label-primary"><i class="fa fa-arrow-right"></i> Inc: {{ match.name }}</span>
    {% endfor %}
{% endif %}
{% if m.finished and m.solution_usable %}
    <p></p>
    {% if m.construct_time %}
        <span class="label label-default"><i class="fa fa-clock-o"></i> Construct {{ m.formatted_construct_time }}</span>
    {% endif %}
    {% if m.compute_time %}
        <span class="label label-default"><i class="fa fa-clock-o"></i> Compute {{ m.formatted_compute_time }}</span>
    {% endif %}
{% endif %}
"""


def matches_data(matches, text=None, url=None, is_root=False):
    """
    Build AJAX JSON payload
    :param matches:
    :return:
    """
    number = len(matches)
    allow_compare = number > 1

    data = [{'name': render_template_string(_name, m=m, text=text, url=url),
             'status': render_template_string(_status, m=m),
             'score': {
                 'display': render_template_string(_score, m=m),
                 'value': float(m.score) if m.solution_usable and m.score is not None else 0
             },
             'info': render_template_string(_info, m=m),
             'menu': render_template_string(_menu, m=m, text=text, url=url, compare=allow_compare,
                                            is_root=is_root)} for m in matches]

    return jsonify(data)
