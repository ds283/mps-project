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


# language=jinja2
_status = \
"""
{% if m.finished %}
    <span class="badge bg-primary">Finished</span>
    {% if m.solution_usable %}
        <span class="badge bg-success">Optimal solution</span>
    {% elif m.outcome == m.OUTCOME_NOT_SOLVED %}
        <span class="badge bg-warning text-dark">Not solved</span>
    {% elif m.outcome == m.OUTCOME_INFEASIBLE %}
        <span class="badge bg-danger">Infeasible</span>
    {% elif m.outcome == m.OUTCOME_UNBOUNDED %}
        <span class="badge bg-danger">Unbounded</span>
    {% elif m.outcome == m.OUTCOME_UNDEFINED %}
        <span class="badge bg-danger">Undefined</span>
    {% else %}
        <span class="badge bg-danger">Unknown outcome</span>
    {% endif %}
    <div class="mt-1">
        {% if m.is_modified %}
            <span class="badge bg-warning text-dark">Modified</span>
        {% else %}
            <span class="badge bg-secondary">Original</span>
        {% endif %}
    </div>
    {% if m.finished %}
        <div class="mt-1">
            <span class="badge bg-secondary">{{ m.records.count() }} selectors</span>
            <span class="badge bg-secondary">{{ m.supervisors.count() }} supervisors</span>
            <span class="badge bg-secondary">{{ m.markers.count() }} markers</span>
            <span class="badge bg-secondary">{{ m.projects.count() }} projects</span>
        </div>
    {% endif %}
    <div class="mt-1">
        {% if m.published and current_user.has_role('root') %}
            <span class="badge bg-info text-dark">Published</span>
        {% endif %}
        {% if m.selected %}
            <span class="badge bg-success">Selected</span>
        {% endif %}
    </div>
{% else %}
    {% if m.awaiting_upload %}
        <span class="badge bg-info text-dark">Awaiting upload</span>
        {% if m.lp_file is not none %}
            <a class="text-decoration-none" href="{{ url_for('admin.download_generated_asset', asset_id=m.lp_file.id) }}">LP</a>
        {% endif %}
        {% if m.mps_file is not none %}
            <a class="text-decoration-none" href="{{ url_for('admin.download_generated_asset', asset_id=m.mps_file.id) }}">MPS</a>
        {% endif %}
    {% else %}
        <span class="badge bg-info text-dark">In progress</span>
    {% endif %}
{% endif %}
"""

# language=jinja2
_info = \
"""
<span class="badge bg-info text-dark">Supervisor <i class="fas fa-less-than-equal"></i> {{ m.supervising_limit }} CATS</span>
<span class="badge bg-info text-dark">Marker <i class="fas fa-less-than-equal"></i> {{ m.marking_limit }} CATS</span>
<span class="badge bg-info text-dark">Marker multiplicity <i class="fas fa-less-than-equal"></i> {{ m.max_marking_multiplicity }}</span>
{% if m.max_different_all_projects is not none %}
    <span class="badge bg-info text-dark">Max all types <i class="fas fa-less-than-equal"></i> {{ m.max_different_all_projects }}</span>
{% endif %}
{% if m.max_different_group_projects is not none %}
    <span class="badge bg-info text-dark">Max group types <i class="fas fa-less-than-equal"></i> {{ m.max_different_group_projects }}</span>
{% endif %}
{% if m.ignore_per_faculty_limits %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Ignore per-faculty limits</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-check"></i> Apply per-faculty limits</span>
{% endif %}
{% if m.ignore_programme_prefs %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Ignore programmes prefs</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-check"></i> Apply programme prefs</span>
{% endif %}
{% if m.include_only_submitted %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Only submitted selectors</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-check"></i> All selectors</span>
{% endif %}
<div>
    <span class="badge bg-info text-dark">Solver {{ m.solver_name }}</span>
</div>
<div class="mt-1">
    <strong class="mr-1">Matching</strong>
    <span class="badge bg-secondary">Programme {{ m.programme_bias }}</span>
    <span class="badge bg-secondary">Bookmarks {{ m.bookmark_bias }}</span>
</div>
<div class="mt-1">
    <strong class="mr-1">Biases</strong>
    <span class="badge bg-secondary">Levelling {{ m.levelling_bias }}</span>
    <span class="badge bg-secondary">Group tension {{ m.intra_group_tension }}</span>
    <span class="badge bg-secondary">S pressure {{ m.supervising_pressure }}</span>
    <span class="badge bg-secondary">M pressure {{ m.marking_pressure }}</span>
</div>
<div class="mt-1">
    <strong class="mr-1">Penalties</strong>
    <span class="badge bg-secondary">CATS violation {{ m.CATS_violation_penalty }}</span>
    <span class="badge bg-secondary">No assignment {{ m.no_assignment_penalty }}</span>
</div>
<div class="mt-1">
    {% if m.use_hints %}
        <span class="badge bg-info text-dark"><i class="fas fa-check"></i> Use hints</span>
        {% if m.require_to_encourage %}
            <span class="badge bg-warning text-dark"><i class="fas fa-exclamation"></i> Require &rarr; Encourage</span>
        {% endif %}
        {% if m.forbid_to_discourage %}
            <span class="badge bg-warning text-dark"><i class="fas fa-exclamation"></i> Forbid &rarr; Discourage</span>
        {% endif %}
        <span class="badge bg-secondary">Encourage <i class="fas fa-check"></i> {{ m.encourage_bias }}</span>
        <span class="badge bg-secondary">Discourage <i class="fas fa-times"></i> {{ m.discourage_bias }}</span>
        <span class="badge bg-secondary">Strong encourage <i class="fas fa-check"></i><i class="fas fa-check ms-1"></i> {{ m.strong_encourage_bias }}</span>
        <span class="badge bg-secondary">Strong discourage <i class="fas fa-times"></i><i class="fas fa-times ms-1"></i> {{ m.strong_discourage_bias }}</span>
    {% else %}
        <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Ignore hints</span>
    {% endif %}
</div>
<div class="mt-1">
    {% if not m.ignore_programme_prefs %}
        {% set outcome = m.prefer_programme_status %}
        {% if outcome is not none %}
            {% set match, fail = outcome %}
            {% set match_pl = 's' %}{% if match == 1 %}{% set match_pl = '' %}{% endif %}
            {% set fail_pl = 's' %}{% if fail == 1 %}{% set fail_pl = '' %}{% endif %}
            <div>
                <span class="badge {% if match > 0 %}bg-success{% else %}bg-secondary{% endif %}">Matched {{ match }} programme pref{{ match_pl }}</span>
                <span class="badge {% if fail > 0 %}bg-warning text-dark{% elif match > 0 %}bg-success{% else %}bg-secondary{% endif %}">Failed {{ fail }} programme pref{{ fail_pl }}</span>
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
                <span class="badge {% if satisfied > 0 %}bg-success{% else %}bg-secondary{% endif %}">Satisfied {{ satisfied }} hint{{ satisfied_pl }}</span>
                <span class="badge {% if violated > 0 %}bg-warning text-dark{% elif satisfied > 0 %}bg-success{% else %}bg-secondary{% endif %}">Violated {{ violated }} hint{{ violated_pl }}</span>
            </div>
        {% endif %}
    {% endif %}
</div>
<div class="mt-1">
    Created by
    <a class="text-decoration-none" href="mailto:{{ m.created_by.email }}">{{ m.created_by.name }}</a>
    on
    {% if m.creation_timestamp is not none %}
        {{ m.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% else %}
        <span class="badge bg-secondary">Unknown</span>
    {% endif %}
</div>
{% if m.last_edited_by is not none %}
    <div class="mt-1">
        Last edited by 
        <a class="text-decoration-none" href="mailto:{{ m.last_edited_by.email }}">{{ m.last_edited_by.name }}</a>
        {% if m.last_edit_timestamp is not none %}
            {{ m.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    </div>
{% endif %}
{% if m.solution_usable %}
    <div class="mt-1">
        {% if m.draft_to_selectors is not none %}
            <div><i class="fas fa-envelope"></i> <strong>Draft to selectors</strong>: {{ m.draft_to_selectors.strftime("%a %d %b %Y %H:%M:%S") }}</div>
        {% endif %}
        {% if m.draft_to_supervisors is not none %}
            <div><i class="fas fa-envelope"></i> <strong>Draft to supervisors</strong>: {{ m.draft_to_supervisors.strftime("%a %d %b %Y %H:%M:%S") }}</div>
        {% endif %}
        {% if m.final_to_selectors is not none %}
            <div><i class="fas fa-envelope"></i> <strong>Final to selectors</strong>: {{ m.final_to_selectors.strftime("%a %d %b %Y %H:%M:%S") }}</div>
        {% endif %}
        {% if m.final_to_supervisors is not none %}
            <div><i class="fas fa-envelope"></i> <strong>Final to supervisors</strong>: {{ m.final_to_supervisors.strftime("%a %d %b %Y %H:%M:%S") }}</div>
        {% endif %}
    </div>
{% endif %}
<div class="mt-1">
    {% set errors = m.errors %}
    {% set warnings = m.warnings %}
    {% if errors|length == 1 %}
        <span class="badge bg-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="badge bg-danger">{{ errors|length }} errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="badge bg-warning text-dark">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="badge bg-warning text-dark">{{ warnings|length }} warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="error-block">
            {% for item in errors %}
                {% if loop.index <= 10 %}
                    <div class="error-message">{{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="error-message">Further errors suppressed...</div>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="error-block">
            {% for item in warnings %}
                {% if loop.index <= 10 %}
                    <div class="error-message">Warning: {{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="error-message">Further errors suppressed...</div>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
</div>
"""


# language=jinja2
_score = \
"""
{% if m.solution_usable %}
    <span class="badge bg-success">Score {{ m.score }} original</span>
    {% set score = m.current_score %}
    {% if score %}
        <span class="badge bg-primary">Score {{ score|round(precision=2) }} now</span>
    {% else %}
        <span class="badge bg-warning text-dark">Current score undefined</span>
    {% endif %}
    <p></p>
    <span class="badge bg-secondary">&delta; max {{ m.delta_max }}</span>
    <span class="badge bg-secondary">&delta; min {{ m.delta_min }}</span>
    <span class="badge bg-secondary">CATS max {{ m.CATS_max }}</span>
    <span class="badge bg-secondary">CATS min {{ m.CATS_min }}</span>
{% else %}
    <span class="badge bg-secondary">Invalid</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if m.finished and m.solution_usable %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.match_student_view', id=m.id, text=text, url=url) }}">
                <i class="fas fa-search fa-fw"></i> Inspect match...
            </a>
            <div role="separator" class="dropdown-divider"></div>
        {% endif %}    
        
        {% if not m.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if m.awaiting_upload %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.upload_match', match_id=m.id) }}"{% endif %}>
                    <i class="fas fa-cloud-upload-alt fa-fw"></i> Upload solution...
                </a>
            {% endif %}
            <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.duplicate_match', id=m.id) }}"{% endif %}>
                <i class="fas fa-clone fa-fw"></i> Duplicate
            </a>
            <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.terminate_match', id=m.id) }}"{% endif %}>
                <i class="fas fa-hand-paper fa-fw"></i> Terminate
            </a>
        {% else %}
            {% if m.solution_usable %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.rename_match', id=m.id, url=url) }}">
                    <i class="fas fa-pencil-alt fa-fw"></i> Rename...
                </a>
                {% if m.is_modified %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.revert_match', id=m.id) }}">
                        <i class="fas fa-undo fa-fw"></i> Revert to original
                    </a>
                {% endif %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.duplicate_match', id=m.id) }}">
                    <i class="fas fa-clone fa-fw"></i> Duplicate
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.compare_match', id=m.id, text=text, url=url) }}">
                    <i class="fas fa-balance-scale fa-fw"></i> Compare to...
                </a>
                {% if is_root %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.create_match', base_id=m.id) }}">
                        <i class="fas fa-plus-circle fa-fw"></i> Use as base...
                    </a>
                {% endif %}
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-times"></i> Solution is not usable</a>
            {% endif %}

            {% if current_user.has_role('root') or current_user.id == m.creator_id %}
                {% if not m.published and not m.selected %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.delete_match', id=m.id) }}">
                        <i class="fas fa-trash fa-fw"></i> Delete
                    </a>
                {% endif %}
                {% if m.can_clean_up %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.clean_up_match', id=m.id) }}">
                        <i class="fas fa-cut fa-fw"></i> Clean up
                    </a>
                {% endif %}
            {% endif %}
            
            {% if current_user.has_role('root') %}
                <div role="separator" class="dropdown-divider"></div>
                <div class="dropdown-header">Superuser functions</div>
                
                {% if m.published %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.unpublish_match', id=m.id) }}">
                        <i class="fas fa-stop-circle fa-fw"></i> Unpublish
                    </a>
                {% else %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_match', id=m.id) }}">
                        <i class="fas fa-share fa-fw"></i> Publish to convenors
                    </a>
                {% endif %}
                
                {% if m.selected %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deselect_match', id=m.id) }}">
                        <i class="fas fa-times fa-fw"></i> Deselect
                    </a>
                {% else %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.select_match', id=m.id, force=0) }}">
                        <i class="fas fa-check fa-fw"></i> Select
                    </a>
                {% endif %}
                
                {% if m.selected or m.published %}
                    <div role="separator" class="dropdown-divider"></div>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_matching_selectors', id=m.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> {% if m.selected %}Final{% else %}Draft{% endif %} email to selectors
                    </a>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_matching_supervisors', id=m.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> {% if m.selected %}Final{% else %}Draft{% endif %} email to supervisors
                    </a>
                    {% if config is not none and not config.select_in_previous_cycle %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.populate_submitters_from_match', match_id=m.id, config_id=config.id) }}">
                            <i class="fas fa-wrench fa-fw"></i> Populate submitters
                        </a>
                    {% endif %}
                {% endif %}
            {% endif %}            
        {% endif %}        
    </div>
</div>
"""


# language=jinja2
_name = \
"""
<div>
    {% if m.finished and m.solution_usable %}
        <a class="text-decoration-none" href="{{ url_for('admin.match_student_view', id=m.id, text=text, url=url) }}"><strong>{{ m.name }}</strong></a>
        {% if m.has_issues %}
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
{% set has_extra_matches = m.include_matches.first() is not none or m.base is not none %}
{% if has_extra_matches %}
    <div class="mt-1">
        {% if m.base is not none %}
            <p><span class="badge bg-success"><i class="fas fa-plus-circle"></i></span> <strong>Base</strong>: {{ m.base.name }}</p>
            {% if m.force_base %}
                <span class="badge bg-info text-dark">Force match</span>
            {% else %}
                <span class="badge bg-info text-dark">Bias {{ m.base_bias }}</span>
            {% endif %}
        {% endif %}
        {% for match in m.include_matches %}
            <p><span class="badge bg-primary"><i class="fas fa-arrow-right"></i></span> <strong>Inc</strong>: {{ match.name }}</p>
        {% endfor %}
    </div>
{% endif %}
{% if m.finished and m.solution_usable %}
    <div class="mt-1">
        {% if m.construct_time %}
            <span class="badge bg-secondary"><i class="fas fa-stopwatch"></i> Build {{ m.formatted_construct_time }}</span>
        {% endif %}
        {% if m.compute_time %}
            <span class="badge bg-secondary"><i class="fas fa-stopwatch"></i> Solve {{ m.formatted_compute_time }}</span>
        {% endif %}
    </div>
{% endif %}
"""


def matches_data(matches, config=None, text=None, url=None, is_root=False):
    """
    Build AJAX JSON payload
    :param pclass:
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
                                            is_root=is_root, config=config)} for m in matches]

    return jsonify(data)
