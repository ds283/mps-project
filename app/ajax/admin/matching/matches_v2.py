#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Optional

from flask import current_app, get_template_attribute, jsonify, render_template

from jinja2 import Environment, Template
from markupsafe import Markup

# language=jinja2
_card = """
<div class="card mb-3{% if m.selected %} border-primary{% endif %}" data-match-id="{{ m.id }}"
     {% if m.selected %}style="box-shadow: 0 0 0 .2rem var(--bs-primary-bg-subtle);"{% endif %}>
    <div class="card-body">
        <div class="row g-3 align-items-start">
            <div class="col-12 col-lg-3 mdash-col">
                {% if m.finished and m.solution_usable %}
                    <a class="text-decoration-none fw-semibold"
                       href="{{ url_for('admin.matching_workspace', id=m.id, view='student', text=text, url=url) }}">{{ m.name }}</a>
                {% else %}
                    <span class="fw-semibold">{{ m.name }}</span>
                {% endif %}
                <div class="mt-1 d-flex flex-wrap gap-1">
                    {% for cfg_member in m.config_members %}
                        {% set pclass = cfg_member.project_class %}
                        {{ simple_label(pclass.make_label(pclass.abbreviation)) }}
                    {% endfor %}
                </div>
            </div>
            <div class="col-12 col-lg-2 mdash-col">
                {% if m.finished %}
                    {% if m.solution_usable %}
                        <div class="small text-success fw-semibold"><i class="fas fa-check-circle"></i> Optimal solution</div>
                    {% elif m.outcome == m.OUTCOME_NOT_SOLVED %}
                        <div class="small text-danger"><i class="fas fa-times-circle"></i> Not solved</div>
                    {% elif m.outcome == m.OUTCOME_INFEASIBLE %}
                        <div class="small text-danger"><i class="fas fa-ban"></i> Infeasible</div>
                    {% elif m.outcome == m.OUTCOME_UNBOUNDED %}
                        <div class="small text-danger"><i class="fas fa-times-circle"></i> Unbounded</div>
                    {% else %}
                        <div class="small text-danger"><i class="fas fa-exclamation-triangle"></i> Undefined</div>
                    {% endif %}
                {% elif m.awaiting_upload %}
                    <div class="small text-primary fw-semibold"><i class="fas fa-clock"></i> Awaiting upload</div>
                {% else %}
                    <div class="small text-primary fw-semibold"><i class="fas fa-clock"></i> In progress</div>
                {% endif %}
                {% if m.is_modified %}
                    <div class="small" style="color: var(--bs-info-text-emphasis);"><i class="fas fa-info-circle"></i> Modified</div>
                {% endif %}
                {% if m.published %}
                    <div class="small text-success"><i class="fas fa-check-circle"></i> Published</div>
                {% endif %}
                {% if m.selected %}
                    <div class="small text-success fw-semibold"><i class="fas fa-star"></i> Current</div>
                {% endif %}
            </div>
            <div class="col-12 col-lg-3 mdash-col">
                {% if m.solution_usable %}
                    {# one wrapping line rather than four stacked ones: the counts are secondary
                       information and should not set the height of the card #}
                    <div class="small text-body-secondary">
                        {{ m.records.count() }} selectors &middot; {{ m.supervisors.count() }} supervisors
                        &middot; {{ m.markers.count() }} markers &middot; {{ m.projects.count() }} projects
                    </div>
                {% endif %}
            </div>
            <div class="col-12 col-lg-4 text-lg-end">
                <div class="d-flex flex-wrap gap-2 justify-content-lg-end">
                    {% if m.finished and m.solution_usable %}
                        <a class="btn btn-sm btn-primary"
                           href="{{ url_for('admin.matching_workspace', id=m.id, view='student', text=text, url=url) }}">
                            Open <i class="fas fa-arrow-right ms-1"></i>
                        </a>
                    {% endif %}
                    {{ render_menu(m, text=text, url=url, is_root=is_root, config=config) }}
                </div>
            </div>
        </div>

        {% if m.solution_usable %}
            <div class="mt-3 pt-3 border-top">
                <button type="button" class="btn btn-sm btn-outline-primary mdash-compute-btn" data-match-id="{{ m.id }}">
                    <i class="fas fa-sync-alt me-1"></i>Compute summary statistics
                </button>
                <div class="mt-2" id="mdash-stats-{{ m.id }}"></div>
            </div>

            <div class="mt-3 pt-2 border-top d-flex flex-wrap gap-2 align-items-center">
                <button class="btn btn-xs mdash-cfg-toggle" type="button"
                        data-bs-toggle="collapse" data-bs-target="#mdash-cfg-{{ m.id }}"
                        aria-expanded="false" aria-controls="mdash-cfg-{{ m.id }}">
                    <i class="fas fa-sliders-h me-1"></i><span class="mdash-toggle-label"
                        data-closed="Configuration" data-open="Hide configuration"></span><i
                        class="fas fa-chevron-down ms-2 mdash-toggle-caret"></i>
                </button>
                <button class="btn btn-xs mdash-tim-toggle" type="button"
                        data-bs-toggle="collapse" data-bs-target="#mdash-tim-{{ m.id }}"
                        aria-expanded="false" aria-controls="mdash-tim-{{ m.id }}">
                    <i class="fas fa-history me-1"></i><span class="mdash-toggle-label"
                        data-closed="Timing &amp; provenance" data-open="Hide timing &amp; provenance"></span><i
                        class="fas fa-chevron-down ms-2 mdash-toggle-caret"></i>
                </button>
            </div>

            <div class="collapse mt-3" id="mdash-cfg-{{ m.id }}">
                <div class="p-3 rounded" style="background: var(--bs-tertiary-bg);">
                    <div class="row g-4">
                        <div class="col-6 col-xl-4">
                            <div class="cfg-grp-h">Limits &amp; multiplicities</div>
                            <div class="d-flex flex-wrap gap-2">
                                <span class="cfg-chip">Supervising CATS <b>{{ m.supervising_limit }}</b></span>
                                <span class="cfg-chip">Marking CATS <b>{{ m.marking_limit }}</b></span>
                                <span class="cfg-chip">Marker multiplicity <b>{{ m.max_marking_multiplicity }}</b></span>
                                <span class="cfg-chip">Max project types
                                    <b>{% if m.max_different_all_projects is none %}no limit{% else %}{{ m.max_different_all_projects }}{% endif %}</b>
                                </span>
                                <span class="cfg-chip">Max group types
                                    <b>{% if m.max_different_group_projects is none %}no limit{% else %}{{ m.max_different_group_projects }}{% endif %}</b>
                                </span>
                            </div>
                        </div>
                        <div class="col-6 col-xl-4">
                            <div class="cfg-grp-h">Policies</div>
                            <div class="d-flex flex-wrap gap-2">
                                {% if not m.ignore_per_faculty_limits %}
                                    <span class="cfg-chip"><i class="fas fa-check-circle text-success"></i>Per-faculty limits applied</span>
                                {% else %}
                                    <span class="cfg-chip">Per-faculty limits not applied</span>
                                {% endif %}
                                {% if not m.ignore_programme_prefs %}
                                    <span class="cfg-chip"><i class="fas fa-check-circle text-success"></i>Programme prefs applied</span>
                                {% else %}
                                    <span class="cfg-chip">Programme prefs not applied</span>
                                {% endif %}
                                {% if m.include_only_submitted %}
                                    <span class="cfg-chip">Only submitted selectors</span>
                                {% else %}
                                    <span class="cfg-chip">All selectors</span>
                                {% endif %}
                                {% if m.solver_name %}
                                    {% if m.solver_name.endswith(' external') %}
                                        <span class="cfg-chip"><i class="fas fa-microchip"></i>{{ m.solver_name[:-9] }}
                                            <span class="text-body-secondary">external</span></span>
                                    {% else %}
                                        <span class="cfg-chip"><i class="fas fa-microchip"></i>{{ m.solver_name }}</span>
                                    {% endif %}
                                {% endif %}
                            </div>
                        </div>
                        <div class="col-6 col-xl-4">
                            <div class="cfg-grp-h">Convenor hints
                                {% if m.use_hints %}
                                    <span class="text-success ms-1"><i class="fas fa-check"></i> enforced</span>
                                {% else %}
                                    <span class="ms-1">disabled</span>
                                {% endif %}
                            </div>
                            {% if m.use_hints %}
                                <div class="d-flex flex-wrap gap-2">
                                    <span class="cfg-chip"><i class="fas fa-arrow-up text-success"></i>Encourage <b>&times;{{ "%.3f"|format(m.encourage_bias) }}</b></span>
                                    <span class="cfg-chip"><i class="fas fa-arrow-down text-danger"></i>Discourage <b>&times;{{ "%.3f"|format(m.discourage_bias) }}</b></span>
                                    <span class="cfg-chip"><i class="fas fa-angle-double-up text-success"></i>Strong enc. <b>&times;{{ "%.3f"|format(m.strong_encourage_bias) }}</b></span>
                                    <span class="cfg-chip"><i class="fas fa-angle-double-down text-danger"></i>Strong disc. <b>&times;{{ "%.3f"|format(m.strong_discourage_bias) }}</b></span>
                                    {% if m.require_to_encourage %}
                                        <span class="cfg-chip">Require &rarr; strong encourage</span>
                                    {% endif %}
                                    {% if m.forbid_to_discourage %}
                                        <span class="cfg-chip">Forbid &rarr; strong discourage</span>
                                    {% endif %}
                                </div>
                            {% endif %}
                        </div>
                        <div class="col-6 col-xl-4">
                            <div class="cfg-grp-h">Objective weights</div>
                            <div class="d-flex flex-wrap gap-2">
                                <span class="cfg-chip">Programme <b>{{ "%.3f"|format(m.programme_bias) }}</b></span>
                                <span class="cfg-chip">Bookmark <b>{{ "%.3f"|format(m.bookmark_bias) }}</b></span>
                                <span class="cfg-chip">Levelling <b>{{ "%.3f"|format(m.levelling_bias) }}</b></span>
                                <span class="cfg-chip">Group tension <b>{{ "%.3f"|format(m.intra_group_tension) }}</b></span>
                                <span class="cfg-chip">Sup. pressure <b>{{ "%.3f"|format(m.supervising_pressure) }}</b></span>
                                <span class="cfg-chip">Mark. pressure <b>{{ "%.3f"|format(m.marking_pressure) }}</b></span>
                            </div>
                        </div>
                        <div class="col-6 col-xl-4">
                            <div class="cfg-grp-h">Penalties</div>
                            <div class="d-flex flex-wrap gap-2">
                                <span class="cfg-chip">CATS violation <b>{{ "%.3f"|format(m.CATS_violation_penalty) }}</b></span>
                                <span class="cfg-chip">No assignment <b>{{ "%.3f"|format(m.no_assignment_penalty) }}</b></span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="collapse mt-3" id="mdash-tim-{{ m.id }}">
                <div class="p-3 rounded d-flex flex-wrap gap-4" style="background: var(--bs-tertiary-bg);">
                    {% if m.base is not none %}
                        <div>
                            <div class="cfg-grp-h">Based on</div>
                            <div class="small">
                                <i class="fas fa-link text-body-secondary me-1"></i>
                                {% if m.base.solution_usable %}
                                    <a class="text-decoration-none"
                                       href="{{ url_for('admin.matching_workspace', id=m.base.id, view='student', text=text, url=url) }}">{{ m.base.name }}</a>
                                {% else %}
                                    <span>{{ m.base.name }}</span>
                                {% endif %}
                            </div>
                            <div class="mt-1 d-flex flex-wrap gap-1 align-items-center">
                                {% if m.force_base %}
                                    <span class="badge rounded-pill"
                                          style="background: var(--bs-warning-bg-subtle); color: var(--bs-warning-text-emphasis);">
                                        <i class="fas fa-lock me-1"></i>Forced inheritance
                                    </span>
                                {% else %}
                                    <span class="badge rounded-pill"
                                          style="background: var(--bs-secondary-bg-subtle); color: var(--bs-secondary-text-emphasis);">
                                        Biased inheritance
                                    </span>
                                {% endif %}
                                <span class="cfg-chip">base bias <b>{{ "%.3f"|format(m.base_bias) }}</b></span>
                            </div>
                        </div>
                    {% endif %}
                    <div>
                        <div class="cfg-grp-h">Timings</div>
                        <div class="d-flex flex-wrap gap-2">
                            <span class="cfg-chip"><i class="fas fa-hammer"></i>Build <b>{{ m.formatted_construct_time }}</b></span>
                            <span class="cfg-chip"><i class="fas fa-stopwatch"></i>Solve <b>{{ m.formatted_compute_time }}</b></span>
                        </div>
                    </div>
                </div>
            </div>
        {% endif %}

        <div class="mt-2 text-body-secondary small">
            Created by <a class="text-decoration-none" href="mailto:{{ m.created_by.email }}">{{ m.created_by.name }}</a>
            {% if m.creation_timestamp %}{{ m.creation_timestamp.strftime("%a %d %b %Y %H:%M") }}{% endif %}
        </div>
    </div>
</div>
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark dropdown-menu-end">
        {% if m.finished and m.solution_usable %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.matching_workspace', id=m.id, view='student', text=text, url=url) }}">
                <i class="fas fa-search fa-fw"></i> Inspect: student view
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.matching_workspace', id=m.id, view='faculty', text=text, url=url) }}">
                <i class="fas fa-search fa-fw"></i> Inspect: faculty view
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.match_dists_view', id=m.id, text=text, url=url) }}">
                <i class="fas fa-chart-bar fa-fw"></i> View distributions
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.match_export_excel', matching_id=m.id) }}">
                <i class="fas fa-file fa-fw"></i> Export to Excel&hellip;
            </a>
            <div role="separator" class="dropdown-divider"></div>
        {% endif %}

        {% if not m.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if m.awaiting_upload %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.upload_match', match_id=m.id) }}"{% endif %}>
                    <i class="fas fa-cloud-upload-alt fa-fw"></i> Upload solution&hellip;
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
                    <i class="fas fa-pencil-alt fa-fw"></i> Rename&hellip;
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
                    <i class="fas fa-balance-scale fa-fw"></i> Compare to&hellip;
                </a>
                {% if is_root %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.create_match', base_id=m.id) }}">
                        <i class="fas fa-link fa-fw"></i> Use as base&hellip;
                    </a>
                {% endif %}
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-times fa-fw"></i> Solution is not usable</a>
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
                            <i class="fas fa-upload fa-fw"></i> Populate submitters&hellip;
                        </a>
                    {% endif %}
                {% endif %}
            {% endif %}
        {% endif %}
    </div>
</div>
"""


def _build_templ(source: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(source)


def matches_dashboard_data(matches: List, config=None, is_root: bool = False, text: Optional[str] = None, url: Optional[str] = None):
    """
    Build the AJAX JSON payload for the top-level Matches list (matches_v2_ajax). Renders one
    card per attempt from cheap fields only (name/tags, status flags, counts, actions menu). The
    expensive statistics bundle (score/programme-pref/hint/delta/CATS/errors/warnings) is
    deliberately excluded — it is fetched per-card, on demand, via match_statistics_ajax. See
    .prompts/matching-workspace/PLAN.md ("no new caching" non-goal).
    """
    simple_label = get_template_attribute("labels.html", "simple_label")

    menu_templ = _build_templ(_menu)

    def render_menu(m, text=None, url=None, is_root=False, config=None):
        return Markup(render_template(menu_templ, m=m, text=text, url=url, is_root=is_root, config=config))

    card_templ = _build_templ(_card)

    cards = [
        {
            "id": m.id,
            "html": render_template(
                card_templ,
                m=m,
                config=config,
                is_root=is_root,
                text=text,
                url=url,
                simple_label=simple_label,
                render_menu=render_menu,
            ),
        }
        for m in matches
    ]

    return jsonify({"cards": cards})
