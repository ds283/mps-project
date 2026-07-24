#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Shared infeasibility-diagnosis machinery for the matching optimizer (`app/tasks/matching.py`).

Kept generic (no MatchingAttempt-specific imports) so a future rollout to the scheduling
optimizer (`app/tasks/scheduling.py`) can reuse the registry, weights and report renderer.

See `.prompts/matching-feasibility/PLAN.md` and `.prompts/matching-feasibility/FEASIBILITY.md`
for the design rationale.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pulp

# ----------------------------------------------------------------------------------------------
# Weights: control which constraint the diagnostic solve prefers to blame (FEASIBILITY.md §3.2)
# ----------------------------------------------------------------------------------------------

# forced assignments (require hints, custom offers, base-match forces) are the least-preferred
# thing to blame, so they carry the heaviest weight
FORCED_WEIGHT_MULTIPLIER = 100.0

# leaving a student unassigned is the next worst outcome
UNASSIGNED_WEIGHT_MULTIPLIER = 20.0

# staffing a project outside its pool is preferable to leaving a student unassigned, but should
# still be preferred over relaxing a capacity/CATS number
OUT_OF_POOL_WEIGHT_MULTIPLIER = 5.0

# 'count'-type resource slacks (capacity, distinct-project limits, marker capacity,
# supervisor-is-marker): one project-place is worth roughly one project's worth of CATS
COUNT_WEIGHT_MULTIPLIER = 1.0

# CATS slacks are the cheapest, most politically acceptable repair, so they are weighted lightly
# and directly in CATS units (no multiplier against mean_CATS_per_project)
CATS_WEIGHT = 1.0

# small tiebreaker coefficient added to the pure-slack objective so the diagnostic draft solution
# is a sensible near-miss ranked by student preference. Must stay far below the smallest slack
# weight (CATS_WEIGHT = 1) even after summing over every selector, or the solver could trade
# slack for a better-ranked project.
DIAGNOSTIC_SCORE_EPSILON = 1e-6

# solver budget for the diagnostic pass (packaged CBC always; see matching.py _diagnose_infeasibility)
DIAGNOSTIC_TIME_LIMIT = 600

# tolerances used when reading slack values back out of the solved problem
INTEGER_SLACK_TOLERANCE = 0.5
CONTINUOUS_SLACK_TOLERANCE = 0.01


# ----------------------------------------------------------------------------------------------
# Violation categories
# ----------------------------------------------------------------------------------------------

CATEGORY_UNASSIGNED_STUDENT = "unassigned_student"
CATEGORY_FORCED_ASSIGNMENT = "forced_assignment"
CATEGORY_BASE_MATCH = "base_match"
CATEGORY_PROJECT_CAPACITY = "project_capacity"
CATEGORY_DISTINCT_PROJECTS = "distinct_projects"
CATEGORY_MARKER_CAPACITY = "marker_capacity"
CATEGORY_SUPERVISOR_IS_MARKER = "supervisor_is_marker"
CATEGORY_PCLASS_CATS_LIMIT = "pclass_cats_limit"
CATEGORY_GLOBAL_CATS_LIMIT = "global_cats_limit"
CATEGORY_OUT_OF_POOL_MARKER = "out_of_pool_marker"
CATEGORY_OUT_OF_POOL_SUPERVISOR = "out_of_pool_supervisor"

# pre-solve categories (FEASIBILITY.md §1.4) — detected before any solve is attempted, so they
# never carry a SlackEntry; they are appended to the report directly via presolve_violation()
CATEGORY_PRESOLVE_MISSING_OFFER_PROJECT = "presolve_missing_offer_project"
CATEGORY_PRESOLVE_NO_RANKED_PROJECTS = "presolve_no_ranked_projects"
CATEGORY_PRESOLVE_EXISTING_SUPERVISOR_CATS = "presolve_existing_supervisor_cats"
CATEGORY_PRESOLVE_EXISTING_MARKER_CATS = "presolve_existing_marker_cats"

# report statuses (top-level "status" field)
STATUS_DIAGNOSED = "diagnosed"
STATUS_FAILED = "failed"
STATUS_UNRESOLVED = "unresolved"
STATUS_PRESOLVE = "presolve"

# severity tiers mirror the CATS=warning / unassigned=error convention already used in
# app/models/matching_validation.py
_ERROR_CATEGORIES = {
    CATEGORY_UNASSIGNED_STUDENT,
    CATEGORY_FORCED_ASSIGNMENT,
    CATEGORY_BASE_MATCH,
    CATEGORY_PRESOLVE_MISSING_OFFER_PROJECT,
    CATEGORY_PRESOLVE_NO_RANKED_PROJECTS,
    CATEGORY_PRESOLVE_EXISTING_SUPERVISOR_CATS,
    CATEGORY_PRESOLVE_EXISTING_MARKER_CATS,
}


def severity_for_category(category: str) -> str:
    return "error" if category in _ERROR_CATEGORIES else "warning"


def weight_for_category(category: str, mean_CATS_per_project: float) -> float:
    if category in (CATEGORY_FORCED_ASSIGNMENT, CATEGORY_BASE_MATCH):
        return FORCED_WEIGHT_MULTIPLIER * mean_CATS_per_project
    if category == CATEGORY_UNASSIGNED_STUDENT:
        return UNASSIGNED_WEIGHT_MULTIPLIER * mean_CATS_per_project
    if category in (CATEGORY_OUT_OF_POOL_MARKER, CATEGORY_OUT_OF_POOL_SUPERVISOR):
        return OUT_OF_POOL_WEIGHT_MULTIPLIER * mean_CATS_per_project
    if category in (
        CATEGORY_PROJECT_CAPACITY,
        CATEGORY_DISTINCT_PROJECTS,
        CATEGORY_MARKER_CAPACITY,
        CATEGORY_SUPERVISOR_IS_MARKER,
    ):
        return COUNT_WEIGHT_MULTIPLIER * mean_CATS_per_project
    if category in (CATEGORY_PCLASS_CATS_LIMIT, CATEGORY_GLOBAL_CATS_LIMIT):
        return CATS_WEIGHT

    raise ValueError('No weight is defined for slack category "{c}"'.format(c=category))


# ----------------------------------------------------------------------------------------------
# Remediation metadata
# ----------------------------------------------------------------------------------------------

# Category -> list of possible remediations. `url`/`text` deep-links are attached by the report
# renderer in later phases (Phase 5), once the corresponding editors exist; for now each entry
# carries only a stable `type` (used by the future URL builder) and a human-readable `label`.
REMEDIATION: Dict[str, List[Dict[str, str]]] = {
    CATEGORY_UNASSIGNED_STUDENT: [],
    CATEGORY_FORCED_ASSIGNMENT: [
        {"type": "edit_hint", "label": "Edit the require hint or withdraw the custom offer"},
    ],
    CATEGORY_BASE_MATCH: [
        {"type": "rerun_option", "label": "Clear 'force base match' and re-run"},
    ],
    CATEGORY_PROJECT_CAPACITY: [
        {"type": "increase_capacity", "label": "Increase the project's capacity"},
    ],
    CATEGORY_DISTINCT_PROJECTS: [
        {"type": "rerun_option", "label": "Raise the distinct-project limit for this run"},
    ],
    CATEGORY_MARKER_CAPACITY: [
        {"type": "rerun_option", "label": "Raise the marking multiplicity limit for this run"},
    ],
    CATEGORY_SUPERVISOR_IS_MARKER: [
        {"type": "attach_assessor", "label": "Add another eligible assessor to the pool"},
    ],
    CATEGORY_PCLASS_CATS_LIMIT: [
        {"type": "edit_pclass_cats", "label": "Raise the per-class CATS limit"},
    ],
    CATEGORY_GLOBAL_CATS_LIMIT: [
        {"type": "edit_global_cats", "label": "Raise the faculty member's global CATS limit"},
        {"type": "rerun_option", "label": "Ignore per-faculty limits for this run"},
    ],
    CATEGORY_OUT_OF_POOL_MARKER: [
        {"type": "attach_assessor", "label": "Add to the assessor pool"},
        {"type": "accept_out_of_pool", "label": "Accept the out-of-pool assignment"},
    ],
    CATEGORY_OUT_OF_POOL_SUPERVISOR: [
        {"type": "attach_supervisor", "label": "Add to the supervisor pool"},
        {"type": "accept_out_of_pool", "label": "Accept the out-of-pool assignment"},
    ],
    CATEGORY_PRESOLVE_MISSING_OFFER_PROJECT: [
        {"type": "edit_hint", "label": "Fix or withdraw the custom offer"},
    ],
    CATEGORY_PRESOLVE_NO_RANKED_PROJECTS: [],
    CATEGORY_PRESOLVE_EXISTING_SUPERVISOR_CATS: [
        {"type": "edit_global_cats", "label": "Raise the faculty member's global supervising CATS limit"},
    ],
    CATEGORY_PRESOLVE_EXISTING_MARKER_CATS: [
        {"type": "edit_global_cats", "label": "Raise the faculty member's global marking CATS limit"},
    ],
}


# ----------------------------------------------------------------------------------------------
# Slack registry
# ----------------------------------------------------------------------------------------------


@dataclass
class SlackEntry:
    """
    One elasticized constraint in the diagnostic problem. `selector`/`project`/`supervisor`/
    `marker` are enumeration indices (not ORM ids) — they are resolved to ORM ids at report-render
    time via the enumeration dicts on `InitializationData`.
    """

    var: pulp.LpVariable
    category: str
    weight: float
    selector: Optional[int] = None
    project: Optional[int] = None
    supervisor: Optional[int] = None
    marker: Optional[int] = None
    config_id: Optional[int] = None
    limit_value: Optional[float] = None


class SlackRegistry:
    """Accumulates SlackEntry instances while the diagnostic problem is being constructed."""

    def __init__(self):
        self.entries: List[SlackEntry] = []

    def add(self, entry: SlackEntry) -> SlackEntry:
        self.entries.append(entry)
        return entry

    def objective_terms(self):
        return [entry.weight * entry.var for entry in self.entries]

    def __len__(self):
        return len(self.entries)


# ----------------------------------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------------------------------


def presolve_violation(category: str, message: str, **entities) -> dict:
    """
    Build a violation dict for a pre-solve failure (FEASIBILITY.md §1.4), detected before any
    solve is attempted so there is no SlackEntry / amount to report.
    """
    return {
        "category": category,
        "severity": severity_for_category(category),
        "amount": None,
        "message": message,
        "entities": entities,
        "remediations": [dict(r) for r in REMEDIATION.get(category, [])],
    }


def _selector_name(idx, data) -> str:
    return data.selector_data.dict[idx].student.user.name


def _selector_id(idx, data) -> Optional[int]:
    return None if idx is None else data.selector_data.dict[idx].id


def _project_name(idx, data) -> str:
    return data.project_data.dict[idx].name


def _project_id(idx, data) -> Optional[int]:
    return None if idx is None else data.project_data.dict[idx].id


def _faculty_name(idx, enumeration) -> str:
    return enumeration.dict[idx].user.name


def _faculty_id(idx, enumeration) -> Optional[int]:
    return None if idx is None else enumeration.dict[idx].id


def _render_slack_entry(entry: SlackEntry, data, value: float) -> dict:
    category = entry.category
    entities: Dict[str, Optional[int]] = {}
    amount = round(value, 2)

    if category == CATEGORY_UNASSIGNED_STUDENT:
        name = _selector_name(entry.selector, data)
        entities["selector_id"] = _selector_id(entry.selector, data)
        amount = int(round(value))
        required = int(entry.limit_value) if entry.limit_value is not None else None
        if required is not None:
            got = required - amount
            message = 'Student "{n}" could only be assigned {g} of {r} required project(s).'.format(n=name, g=got, r=required)
        else:
            message = 'Student "{n}" could not be assigned the required number of projects (short by {a}).'.format(n=name, a=amount)

    elif category == CATEGORY_FORCED_ASSIGNMENT:
        sel_name = _selector_name(entry.selector, data)
        proj_name = _project_name(entry.project, data)
        entities["selector_id"] = _selector_id(entry.selector, data)
        entities["project_id"] = _project_id(entry.project, data)
        amount = 1
        message = 'Required assignment of "{s}" to project "{p}" could not be honoured.'.format(s=sel_name, p=proj_name)

    elif category == CATEGORY_BASE_MATCH:
        entities["selector_id"] = _selector_id(entry.selector, data)
        entities["project_id"] = _project_id(entry.project, data)
        entities["marker_id"] = _faculty_id(entry.marker, data.marker_data)
        amount = 1
        if entry.selector is not None and entry.project is not None:
            sel_name = _selector_name(entry.selector, data)
            proj_name = _project_name(entry.project, data)
            message = 'Base-match assignment of "{s}" to project "{p}" could not be reproduced.'.format(s=sel_name, p=proj_name)
        else:
            message = "A base-match marker assignment could not be reproduced."

    elif category == CATEGORY_PROJECT_CAPACITY:
        proj_name = _project_name(entry.project, data)
        entities["project_id"] = _project_id(entry.project, data)
        entities["supervisor_id"] = _faculty_id(entry.supervisor, data.supervisor_data)
        amount = int(round(value))
        message = 'Project "{p}" needed {a} more place(s) beyond its capacity of {l}.'.format(p=proj_name, a=amount, l=entry.limit_value)

    elif category == CATEGORY_OUT_OF_POOL_SUPERVISOR:
        proj_name = _project_name(entry.project, data)
        sup_name = _faculty_name(entry.supervisor, data.supervisor_data)
        entities["project_id"] = _project_id(entry.project, data)
        entities["supervisor_id"] = _faculty_id(entry.supervisor, data.supervisor_data)
        amount = int(round(value))
        message = (
            '"{s}" is not in the supervisor pool for project "{p}", but {a} assignment(s) were needed there to keep the problem feasible.'.format(
                s=sup_name, p=proj_name, a=amount
            )
        )

    elif category == CATEGORY_DISTINCT_PROJECTS:
        sup_name = _faculty_name(entry.supervisor, data.supervisor_data)
        entities["supervisor_id"] = _faculty_id(entry.supervisor, data.supervisor_data)
        amount = int(round(value))
        message = '"{s}" needed {a} more distinct project(s) than the configured limit of {l}.'.format(s=sup_name, a=amount, l=entry.limit_value)

    elif category == CATEGORY_MARKER_CAPACITY:
        mark_name = _faculty_name(entry.marker, data.marker_data)
        proj_name = _project_name(entry.project, data)
        entities["marker_id"] = _faculty_id(entry.marker, data.marker_data)
        entities["project_id"] = _project_id(entry.project, data)
        amount = int(round(value))
        message = '"{m}" needed {a} extra marking assignment(s) on project "{p}" beyond the per-project limit of {l}.'.format(
            m=mark_name, a=amount, p=proj_name, l=entry.limit_value
        )

    elif category == CATEGORY_OUT_OF_POOL_MARKER:
        mark_name = _faculty_name(entry.marker, data.marker_data)
        proj_name = _project_name(entry.project, data)
        entities["marker_id"] = _faculty_id(entry.marker, data.marker_data)
        entities["project_id"] = _project_id(entry.project, data)
        amount = int(round(value))
        message = (
            '"{m}" is not in the assessor pool for project "{p}", but {a} marking assignment(s) were needed there '
            "to keep the problem feasible.".format(m=mark_name, p=proj_name, a=amount)
        )

    elif category == CATEGORY_SUPERVISOR_IS_MARKER:
        proj_name = _project_name(entry.project, data)
        name = _faculty_name(entry.supervisor, data.supervisor_data)
        entities["project_id"] = _project_id(entry.project, data)
        entities["supervisor_id"] = _faculty_id(entry.supervisor, data.supervisor_data)
        entities["marker_id"] = _faculty_id(entry.marker, data.marker_data)
        amount = 1
        message = 'The only way to staff project "{p}" makes "{n}" both supervisor and marker.'.format(p=proj_name, n=name)

    elif category == CATEGORY_PCLASS_CATS_LIMIT:
        entities["config_id"] = entry.config_id
        if entry.supervisor is not None:
            name = _faculty_name(entry.supervisor, data.supervisor_data)
            entities["supervisor_id"] = _faculty_id(entry.supervisor, data.supervisor_data)
            role = "supervising"
        else:
            name = _faculty_name(entry.marker, data.marker_data)
            entities["marker_id"] = _faculty_id(entry.marker, data.marker_data)
            role = "marking"
        message = '"{n}" exceeds their per-class {r} CATS limit of {l} by {a} CATS.'.format(n=name, r=role, l=entry.limit_value, a=amount)

    elif category == CATEGORY_GLOBAL_CATS_LIMIT:
        if entry.supervisor is not None:
            name = _faculty_name(entry.supervisor, data.supervisor_data)
            entities["supervisor_id"] = _faculty_id(entry.supervisor, data.supervisor_data)
            role = "supervising"
        else:
            name = _faculty_name(entry.marker, data.marker_data)
            entities["marker_id"] = _faculty_id(entry.marker, data.marker_data)
            role = "marking"
        message = '"{n}" exceeds their global {r} CATS limit by {a} CATS.'.format(n=name, r=role, a=amount)

    else:
        message = 'Unrecognized slack category "{c}" (amount={a}).'.format(c=category, a=amount)

    return {
        "category": category,
        "severity": severity_for_category(category),
        "amount": amount,
        "message": message,
        "entities": entities,
        "remediations": [dict(r) for r in REMEDIATION.get(category, [])],
    }


def render_violations(registry: Optional[SlackRegistry], data) -> List[dict]:
    """Filter the registry for entries with a solved value above tolerance, and render each."""
    if registry is None:
        return []

    violations = []
    for entry in registry.entries:
        value = pulp.value(entry.var)
        if value is None:
            continue

        tolerance = CONTINUOUS_SLACK_TOLERANCE if entry.var.cat == pulp.LpContinuous else INTEGER_SLACK_TOLERANCE
        if value <= tolerance:
            continue

        violations.append(_render_slack_entry(entry, data, value))

    return violations


def build_infeasibility_report(
    status: str,
    data=None,
    registry: Optional[SlackRegistry] = None,
    presolve_failures: Optional[List[dict]] = None,
    diagnostic_solve_time: Optional[float] = None,
) -> dict:
    violations: List[dict] = []

    if presolve_failures:
        violations.extend(presolve_failures)

    if registry is not None and data is not None:
        violations.extend(render_violations(registry, data))

    return {
        "status": status,
        "generated": datetime.now().isoformat(),
        "diagnostic_solve_time": diagnostic_solve_time,
        "violations": violations,
    }
