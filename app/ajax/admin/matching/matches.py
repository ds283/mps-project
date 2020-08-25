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
    <span class="badge badge-primary">Finished</span>
    {% if m.solution_usable %}
        <span class="badge badge-success">Optimal solution</span>
    {% elif m.outcome == m.OUTCOME_NOT_SOLVED %}
        <span class="badge badge-warning">Not solved</span>
    {% elif m.outcome == m.OUTCOME_INFEASIBLE %}
        <span class="badge badge-danger">Infeasible</span>
    {% elif m.outcome == m.OUTCOME_UNBOUNDED %}
        <span class="badge badge-danger">Unbounded</span>
    {% elif m.outcome == m.OUTCOME_UNDEFINED %}
        <span class="badge badge-danger">Undefined</span>
    {% else %}
        <span class="badge badge-danger">Unknown outcome</span>
    {% endif %}
    <p></p>
    {% if m.is_modified %}
        <span class="badge badge-warning">Modified</span>
    {% else %}
        <span class="badge badge-success">Original</span>
    {% endif %}
    <p></p>
    {% if m.solution_usable %}
        {% if m.draft_to_selectors is not none %}
            <span class="badge badge-info">Draft to selectors: {{ m.draft_to_selectors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if m.draft_to_supervisors is not none %}
            <span class="badge badge-info">Draft to supervisors: {{ m.draft_to_supervisors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if m.final_to_selectors is not none %}
            <span class="badge badge-primary">Final to selectors: {{ m.final_to_selectors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if m.final_to_supervisors is not none %}
            <span class="badge badge-primary">Final to supervisors: {{ m.final_to_supervisors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
    {% endif %}
    <p></p>
    {% if m.published and current_user.has_role('root') %}
        <span class="badge badge-primary">Published</span>
    {% endif %}
    {% if m.selected %}
        <span class="badge badge-success">Selected</span>
    {% endif %}
{% else %}
    {% if m.awaiting_upload %}
        <span class="badge badge-success">Awaiting upload</span>
        {% if m.lp_file is not none %}
            <a href="{{ url_for('admin.download_generated_asset', asset_id=m.lp_file.id) }}">LP</a>
        {% endif %}
        {% if m.mps_file is not none %}
            <a href="{{ url_for('admin.download_generated_asset', asset_id=m.mps_file.id) }}">MPS</a>
        {% endif %}
    {% else %}
        <span class="badge badge-success">In progress</span>
    {% endif %}
{% endif %}
"""

_info = \
"""
<span class="badge badge-primary">Supervisor <i class="fas fa-less-than-equal"></i> {{ m.supervising_limit }} CATS</span>
<span class="badge badge-info">2nd mark <i class="fas fa-less-than-equal"></i> {{ m.marking_limit }} CATS</span>
<span class="badge badge-info">Marker multiplicity <i class="fas fa-less-than-equal"></i> {{ m.max_marking_multiplicity }}</span>
{% if m.ignore_per_faculty_limits %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Ignore per-faculty limits</span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-check"></i> Apply per-faculty limits</span>
{% endif %}
{% if m.ignore_programme_prefs %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Ignore programmes prefs/span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-check"></i> Apply programme prefs</span>
{% endif %}
{% if m.include_only_submitted %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Only submitted selectors</span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-check"></i> All selectors</span>
{% endif %}
<div>
    <span class="badge badge-success">Solver {{ m.solver_name }}</span>
</div>
<div>
    <div>Matching</div>
    <span class="badge badge-secondary">Programme {{ m.programme_bias }}</span>
    <span class="badge badge-secondary">Bookmarks {{ m.bookmark_bias }}</span>
</div>
<div>
    <div>Biases</div>
    <span class="badge badge-secondary">Levelling {{ m.levelling_bias }}</span>
    <span class="badge badge-secondary">Group tension {{ m.intra_group_tension }}</span>
    <span class="badge badge-secondary">S pressure {{ m.supervising_pressure }}</span>
    <span class="badge badge-secondary">M pressure {{ m.marking_pressure }}</span>
</div>
<div>
    <div>Penalties</div>
    <span class="badge badge-secondary">CATS violation {{ m.CATS_violation_penalty }}</span>
    <span class="badge badge-secondary">No assignment {{ m.no_assignment_penalty }}</span>
</div>
<p></p>
{% if m.use_hints %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Use hints</span>
{% else %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Ignore hints</span>
{% endif %}
<span class="badge badge-secondary">Encourage <i class="fas fa-times"></i> {{ m.encourage_bias }}</span>
<span class="badge badge-secondary">Discourage <i class="fas fa-times"></i> {{ m.discourage_bias }}</span>
<span class="badge badge-secondary">Strong encourage <i class="fas fa-times"></i> {{ m.strong_encourage_bias }}</span>
<span class="badge badge-secondary">Strong discourage <i class="fas fa-times"></i> {{ m.strong_discourage_bias }}</span>
<p></p>
{% if not m.ignore_programme_prefs %}
    {% set outcome = m.prefer_programme_status %}
    {% if outcome is not none %}
        {% set match, fail = outcome %}
        {% set match_pl = 's' %}{% if match == 1 %}{% set match_pl = '' %}{% endif %}
        {% set fail_pl = 's' %}{% if fail == 1 %}{% set fail_pl = '' %}{% endif %}
        <div>
            <span class="badge {% if match > 0 %}badge-success{% else %}badge-secondary{% endif %}">Matched {{ match }} programme pref{{ match_pl }}</span>
            <span class="badge {% if fail > 0 %}badge-warning{% elif match > 0 %}badge-success{% else %}badge-secondary{% endif %}">Failed {{ fail }} programme pref{{ fail_pl }}</span>
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
            <span class="badge {% if satisfied > 0 %}badge-success{% else %}badge-secondary{% endif %}">Satisfied {{ satisfied }} hint{{ satisfied_pl }}</span>
            <span class="badge {% if violated > 0 %}badge-warning{% elif satisfied > 0 %}badge-success{% else %}badge-secondary{% endif %}">Violated {{ violated }} hint{{ violated_pl }}</span>
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
        <span class="badge badge-secondary">Unknown</span>
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
            {% if loop.index <= 10 %}
                <p class="error-message">{{ item }}</p>
            {% elif loop.index == 11 %}
                <p class="error-message">...</p>
            {% endif %}            
        {% endfor %}
    </div>
{% endif %}
{% if warnings|length > 0 %}
    <div class="error-block">
        {% for item in warnings %}
            {% if loop.index <= 10 %}
                <p class="error-message">Warning: {{ item }}</p>
            {% elif loop.index == 11 %}
                <p class="error-message">...</p>
            {% endif %}
        {% endfor %}
    </div>
{% endif %}
"""


_score = \
"""
{% if m.solution_usable %}
    <span class="badge badge-success">Score {{ m.score }} original</span>
    {% set score = m.current_score %}
    {% if score %}
        <span class="badge badge-primary">Score {{ score|round(precision=2) }} now</span>
    {% else %}
        <span class="badge badge-warning">Current score undefined</span>
    {% endif %}
    <p></p>
    <span class="badge badge-info">&delta; max {{ m.delta_max }}</span>
    <span class="badge badge-info">&delta; min {{ m.delta_min }}</span>
    <span class="badge badge-primary">CATS max {{ m.CATS_max }}</span>
    <span class="badge badge-primary">CATS min {{ m.CATS_min }}</span>
{% else %}
    <span class="badge badge-secondary">Invalid</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% if m.finished and m.solution_usable %}
            <a class="dropdown-item" href="{{ url_for('admin.match_student_view', id=m.id, text=text, url=url) }}">
                <i class="fas fa-search fa-fw"></i> Inspect match...
            </a>
            <div role="separator" class="dropdown-divider"></div>
        {% endif %}    
        
        {% if not m.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if m.awaiting_upload %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.upload_match', match_id=m.id) }}"{% endif %}>
                    <i class="fas fa-cloud-upload fa-fw"></i> Upload solution...
                </a>
            {% endif %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.duplicate_match', id=m.id) }}"{% endif %}>
                <i class="fas fa-clone fa-fw"></i> Duplicate
            </a>
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.terminate_match', id=m.id) }}"{% endif %}>
                <i class="fas fa-hand-paper fa-fw"></i> Terminate
            </a>
        {% else %}
            {% if m.solution_usable %}
                <a class="dropdown-item" href="{{ url_for('admin.rename_match', id=m.id, url=url) }}">
                    <i class="fas fa-pencil-alt fa-fw"></i> Rename...
                </a>
                {% if m.is_modified %}
                    <a class="dropdown-item" href="{{ url_for('admin.revert_match', id=m.id) }}">
                        <i class="fas fa-undo fa-fw"></i> Revert to original
                    </a>
                {% endif %}
                <a class="dropdown-item" href="{{ url_for('admin.duplicate_match', id=m.id) }}">
                    <i class="fas fa-clone fa-fw"></i> Duplicate
                </a>
                <a class="dropdown-item" href="{{ url_for('admin.compare_match', id=m.id, text=text, url=url) }}">
                    <i class="fas fa-balance-scale fa-fw"></i> Compare to...
                </a>
                {% if is_root %}
                    <a class="dropdown-item" href="{{ url_for('admin.create_match', base_id=m.id) }}">
                        <i class="fas fa-plus-circle fa-fw"></i> Use as base...
                    </a>
                {% endif %}
            {% else %}
                <a class="dropdown-item disabled"><i class="fas fa-times"></i> Solution is not usable</a>
            {% endif %}

            {% if current_user.has_role('root') or current_user.id == m.creator_id %}
                <a class="dropdown-item" href="{{ url_for('admin.delete_match', id=m.id) }}">
                    <i class="fas fa-trash fa-fw"></i> Delete
                </a>
                {% if m.can_clean_up %}
                    <a class="dropdown-item" href="{{ url_for('admin.clean_up_match', id=m.id) }}">
                        <i class="fas fa-scissors fa-fw"></i> Clean up
                    </a>
                {% endif %}
            {% endif %}
            
            {% if current_user.has_role('root') %}
                <div role="separator" class="dropdown-divider"></div>
                <div class="dropdown-header">Superuser functions</div>
                
                {% if m.published %}
                    <a class="dropdown-item" href="{{ url_for('admin.unpublish_match', id=m.id) }}">
                        <i class="fas fa-stop-circle fa-fw"></i> Unpublish
                    </a>
                {% else %}
                    <a class="dropdown-item" href="{{ url_for('admin.publish_match', id=m.id) }}">
                        <i class="fas fa-share fa-fw"></i> Publish to convenors
                    </a>
                {% endif %}
                
                {% if m.selected %}
                    <a class="dropdown-item" href="{{ url_for('admin.deselect_match', id=m.id) }}">
                        <i class="fas fa-times fa-fw"></i> Deselect
                    </a>
                {% else %}
                    <a class="dropdown-item" href="{{ url_for('admin.select_match', id=m.id, force=0) }}">
                        <i class="fas fa-check fa-fw"></i> Select
                    </a>
                {% endif %}
                
                {% if m.selected or m.published %}
                    <div role="separator" class="dropdown-divider"></div>
                    <a class="dropdown-item" href="{{ url_for('admin.publish_matching_selectors', id=m.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> Email to selectors
                    </a>
                    <a class="dropdown-item" href="{{ url_for('admin.publish_matching_supervisors', id=m.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> Email to supervisors
                    </a>
                {% endif %}
            {% endif %}            
        {% endif %}        
    </div>
</div>
"""


_name = \
"""
<div>
    {% if m.finished and m.solution_usable %}
        <a href="{{ url_for('admin.match_student_view', id=m.id, text=text, url=url) }}">{{ m.name }}</a>
        {% if not m.is_valid %}
            <i class="fas fa-exclamation-triangle" style="color:red;"></i>
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
    <span class="badge badge-info">{{ m.records.count() }} selectors</span>
    <span class="badge badge-info">{{ m.supervisors.count() }} supervisors</span>
    <span class="badge badge-info">{{ m.markers.count() }} markers</span>
    <span class="badge badge-info">{{ m.projects.count() }} projects</span>
{% endif %}
{% set has_extra_matches = m.include_matches.first() is not none or m.base is not none %}
{% if has_extra_matches %}
    <p></p>
    {% if m.base is not none %}
        <span class="badge badge-success"><i class="fas fa-plus-circle"></i> Base: {{ m.base.name }}</span>
        {% if m.force_base %}
            <span class="badge badge-info">Force match</span>
        {% else %}
            <span class="badge badge-info">Bias {{ m.base_bias }}</span>
        {% endif %}
    {% endif %}
    {% for match in m.include_matches %}
        <span class="badge badge-primary"><i class="fas fa-arrow-right"></i> Inc: {{ match.name }}</span>
    {% endfor %}
{% endif %}
{% if m.finished and m.solution_usable %}
    <p></p>
    {% if m.construct_time %}
        <span class="badge badge-secondary"><i class="fas fa-stopwatch"></i> Construct {{ m.formatted_construct_time }}</span>
    {% endif %}
    {% if m.compute_time %}
        <span class="badge badge-secondary"><i class="fas fa-stopwatch"></i> Compute {{ m.formatted_compute_time }}</span>
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
