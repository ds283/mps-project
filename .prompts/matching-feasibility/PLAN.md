# Plan: infeasibility diagnosis for the matching optimizer

## Context

`app/tasks/matching.py` builds a PuLP integer-programming problem to match students to
projects under capacity and CATS workload constraints. When the problem is infeasible the
solver returns `OUTCOME_INFEASIBLE` and the attempt becomes a dead end: no records, no score,
no diagnosis. Today the only way to understand *why* is to export the LP file and compute an
IIS in a commercial solver (Gurobi) offline — a manual workflow that doesn't scale and needs
tooling most users don't have.

This change adds an automatic **second solver pass** that runs only when the production solve
returns infeasible. The second pass relaxes the resource/demand constraints with slack
variables, minimizes *only* the weighted slack (dropping the score and all levelling/bias
terms — those choose among feasible solutions and are pure noise when locating infeasibility),
and reads the resulting slacks back to produce a structured, human-readable
`infeasibility_report`. It also stores a **coarse "best-available" draft solution** (ranked
crudely by student preference, no biases) so users can see what a near-miss allocation looks
like. **The diagnosis panel is a single remediation surface**: each violation carries a list of
concrete fixes that deep-link to the relevant editor (mostly existing — assessor/supervisor
pool, per-class CATS limits, custom offers — plus one new LiveProject capacity editor) or to an
editable "re-run with adjusted settings" form for match-level option levers.

Infeasible attempts remain **unusable for rollover selection and for populating
`SubmittingStudent` instances**, but may be **published to convenors** (read-only) so they can
see what does and doesn't work.

Design rationale and the constraint inventory live in
`.prompts/matching-feasibility/FEASIBILITY.md` (moved from `.prompts/matching-infeasibility/`).
Key decisions settled with the user:
- **Two-pass, not single-pass all-soft.** The production solve stays byte-for-byte unchanged.
  Justified by: `gapRel=0.25`/`timeLimit` making single-pass infeasibility indeterminate on
  large instances; the levelling plateau making gap-0 expensive on every run; and penalty
  dominance being a user-breakable correctness invariant. The diagnostic pass has a pure
  slack objective (no score to dominate) so weight-tuning affects *attribution* only, never
  correctness.
- The diagnostic pass drops **all** biases and levelling terms.
- `MatchingEnumeration` rows are **not** available for re-hydration testing (they exist only
  for the offline-upload workflow and are swept once `awaiting_upload` is False), so testing
  uses synthetic fixtures, not historical replay.
- **Pool eligibility is elasticized** (out-of-pool markers/supervisors become distinct, lightly
  weighted remediation categories), because downstream validation only *warns* on out-of-pool
  assignments — the solver's hard pool constraints are stricter than the system requires, and
  relaxing them adds no new decision variables. See §"Constraint families".
- **Match-level option levers** (`max_marking_multiplicity`, `max_different_*`, match CATS
  limits, `ignore_per_faculty_limits`, `force_base`) are fixed through an **editable re-run
  form** (clone + edit + relaunch), since no edit form for an existing `MatchingAttempt` exists
  and re-solving needs a fresh run regardless.
- A **global-vs-per-pclass CATS coherence check** is added both at edit time
  (`custom_CATS_limits`) and proactively in the diagnosis.

## Constraint families to elasticize (from FEASIBILITY.md §1.3, §6)

Keep hard: all structural/definitional constraints (ss/Z/Ysel/Ymark/yy links, levelling
brackets) and the `X<=R` (R=0) ranking eligibility and nosupv/nomark constraints. Relax with
one-sided slacks — **including pool eligibility** (see note below):

| Key | Constraint (matching.py loc) | Slack dir | Report category | Remediation lever |
|---|---|---|---|---|
| C1 | selector multiplicity `Σ_j X == m_l` (1654) | `+u_l`, integer | `unassigned_student` | (composite) |
| C2 | require/custom-offer `X[idx] == 1` (1668) | `+u`, binary | `forced_assignment` | edit hint / withdraw-redirect custom offer |
| C3 | base-match force `X==1` (1689), `Y==base_Y` (2017) | `+u`, binary | `base_match` | clear `force_base` (re-run form) |
| C4 | project capacity `S<=cap*P` where P=1 (1725) | `+u_kj`, integer | `project_capacity` | **raise LiveProject.capacity / clear enforce_capacity (NEW editor)** |
| C6 | distinct-project limits (1812, 1822) | `+u_k`, integer | `distinct_projects` | raise `max_different_*` (re-run form) |
| C7 | marker capacity `Σ_l Y <= M` where M>0 (1875) | `+u_ij`, integer | `marker_capacity` | raise `max_marking_multiplicity` (re-run form) |
| C9 | supervisor≠marker `ss+yy<=1` (1993) | `+u_kj`, binary | `supervisor_is_marker` | add another eligible assessor to pool |
| C11 | per-pclass CATS limits (2087, 2123) | `+u`, continuous | `pclass_cats_limit` | raise `EnrollmentRecord.CATS_*` (`custom_CATS_limits`) |
| CP-M | marker pool eligibility `Σ_l Y <= M` where **M=0** (1875) | `+u_ij`, integer | `out_of_pool_marker` | add to assessor pool OR accept out-of-pool |
| CP-S | supervisor pool eligibility `S<=cap*P` where **P=0** (1725) | `+u_kj`, integer | `out_of_pool_supervisor` | add to supervisor pool OR accept out-of-pool |

C10 (global CATS) is **already elastic** via `sup_elastic_CATS`/`mark_elastic_CATS` — in
diagnostic mode these become report sources too (`global_cats_limit`; lever: raise
`FacultyData.CATS_*` / match `supervising_limit`/`marking_limit` / set
`ignore_per_faculty_limits`). Parity constraints C5 (supervisor parity, 1782) and C8 (marker
parity, 1967) stay hard; conflicts route through them to C4/C7/C10 slacks.

**Pool eligibility is relaxed, not kept hard** (decision: elasticize pools). Rationale:
downstream validation treats an out-of-pool marker (matching_validation.py:278) and out-of-pool
supervisor (:298) as **warnings, not errors** — they don't block rollover — so the solver's hard
pool constraints are *stricter* than the system actually requires. Elasticizing them is cheap:
the `Y`/`S` variables already exist for `M=0`/`P=0` entries (the constraint just pins them to 0),
so this adds slack on existing constraints with **no new decision variables**. It lets the
diagnosis distinguish "*pool* too small" from "*capacity* too small" and offer a real choice
(enlarge the pool, or accept the already-permitted out-of-pool assignment). Guard against
blow-up: only register a pool slack for entries actually driven nonzero in the solution (filter
at report time), not one `SlackEntry` per candidate pair.

**Weights** (blame order; heaviest = least-preferred to blame), as named constants:
`forced_assignment`/`base_match` ≫ `unassigned_student` > `out_of_pool_*` > count-slacks
(capacity, distinct, marker, sup-is-marker) > CATS slacks. Note `out_of_pool_*` is **lighter**
than `unassigned_student` (assigning an out-of-pool assessor is preferable to leaving a student
with no project) but heavier than the count/CATS levers (prefer to relax a capacity or CATS
number before staffing outside the pool). This mirrors the existing "CATS = warning, unassigned
= error" convention in `matching_validation.py`.

## Pre-solve hard failures (FEASIBILITY.md §1.4)

Four sites currently raise bare `RuntimeError` before the solver runs (existing sup CATS >
limit at matching.py:2070; existing mark CATS > limit at 2106; selector with no valid
LiveProjects at 995; custom offer targets missing LiveProject at 938). These are the cheapest
diagnoses of all (no solve needed). Convert them to structured report items with a clean
`OUTCOME_INFEASIBLE` finish rather than crashing the Celery task. (matching.py:938/995 are in
`_build_ranking_matrix`/`_initialize`, upstream of solve — collect rather than raise.)

---

## Implementation

### Phase 0 — quick wins (independent, ship first)

1. **Make per-pclass CATS limits (C11) elastic in the *production* problem**, mirroring C10:
   add slack vars, reuse `CATS_violation_penalty` in the objective. Fixes the C10/C11
   asymmetry and removes a class of avoidable hard infeasibilities. Files: `_create_PuLP_problem`
   (matching.py:2087, 2123) + objective term (matching.py:1588). No schema change.

### Phase 1 — diagnostic core

2. **New module `app/tasks/matching_diagnostics.py`** (generic, so scheduling.py can reuse
   later). Contents:
   - `SlackEntry` dataclass: `var, category, weight, selector/project/supervisor/marker/config_id,
     limit_value` (enumeration indices; resolved to ORM ids at report time).
   - A `SlackRegistry` accumulator.
   - Report renderer: filter `pulp.value(var) > 0.5` (int/binary) / `> 0.01` (continuous CATS),
     resolve indices → ORM objects via the enumeration dicts, build the report dict.
   - `REMEDIATION` mapping category → suggested action metadata (see report schema below).
   - Weight constants.

3. **Diagnostic mode in `_create_PuLP_problem`** (Route 1 from FEASIBILITY.md §3.4 —
   `diagnostic: bool = False` param). At each of the 8 elasticizable sites, branch: normal mode
   emits today's constraint; diagnostic mode emits the relaxed form + registers a `SlackEntry`.
   In diagnostic mode: skip `_build_score_function`, skip **all** levelling/bias terms, set
   objective `min Σ w·u`. Extend the `PuLPProblem` namedtuple with a `slack_registry` field
   (`None` in normal mode). Because every diagnostic branch is guarded by `if diagnostic`,
   production behaviour when `diagnostic=False` is provably unchanged.
   - Note: the *diagnostic* solve should not use elastic C10 as separate slack — fold C10 and
     C11 into the registry uniformly so all CATS violations surface identically.

4. **`_diagnose_infeasibility(record, init_data, base_data)`** in matching.py:
   - Rebuild via `_create_PuLP_problem(data, base_data, record, diagnostic=True)`.
   - Solve with **packaged CBC always** (ignore `record.solver`; the whole point is users lack
     commercial solvers), `gapRel=0`, own `timeLimit` (start 600 s). Add a `progress_update`
     ("Match was infeasible; diagnosing conflicting constraints…").
   - Render report from the registry; store to `record.infeasibility_report` (JSON).
   - **Store the coarse draft solution**: the diagnostic solve produces a full assignment.
     Add a small `ε·(preference score)` tiebreaker to the pure-slack objective (ε small enough
     not to perturb slack minimization) so the draft is a *sensible* near-miss ranked by student
     preference. Reuse the existing `_store_PuLP_solution` machinery but tolerantly (see §5
     below) to write `MatchingRecord`/`MatchingRole` rows flagged as draft.
   - Wrap everything in `try/except`: a diagnosis failure must never turn INFEASIBLE into task
     FAILURE — log and leave a `{"status": "failed", ...}` report.
   - Edge case: if the diagnostic problem is itself infeasible (a kept-hard contradiction, e.g.
     a base-match force with R=0), store `{"status": "unresolved"}` and fall back to today's
     behaviour.

5. **Wire into `_process_PuLP_solution`** (matching.py:3205, the `Infeasible` branch) and the
   `Not Solved` branch where appropriate. Call `_diagnose_infeasibility` inline (all inputs
   already in memory). Thread `init_data`/`base_data` — they are in scope in `_execute_live`'s
   caller.

6. **Pre-solve failure collection**: refactor the four §1.4 sites to append to a
   pre-solve report list instead of raising; if the list is non-empty after `_initialize`,
   short-circuit to `OUTCOME_INFEASIBLE` with the report and a clean finish.

### Phase 2 — model, storage, lifecycle

7. **`infeasibility_report` column on `PuLPMixin`** (`app/models/matching.py:58`, so
   `ScheduleAttempt` inherits it for the future scheduling rollout):
   `db.Column(db.Text(collation="utf8_bin"), nullable=True)`. Add `infeasibility_report_data`
   read property (`json.loads`, `None`-safe) + writer, following the `LLMOrchestrationJob.
   recent_workflows` pattern (llm_orchestration.py:336). **Hand-written Alembic migration**
   (find chain tip per CLAUDE.md; `collation='utf8_bin'` in the migration per the column rule).

   **Report JSON schema**:
   ```json
   {
     "status": "diagnosed | failed | unresolved | presolve",
     "generated": "iso-8601",
     "diagnostic_solve_time": 12.3,
     "violations": [
       {
         "category": "project_capacity",
         "severity": "error | warning",
         "amount": 2,
         "message": "Project «X» (owner «Y») needs 2 place(s) beyond its capacity of 4.",
         "entities": {"project_id": 123, "supervisor_id": null, ...},
         "remediations": [
           {"type": "increase_capacity", "label": "Increase capacity",
            "url": "<liveproject capacity editor + url/text>"},
           {"type": "rerun_option", "label": "Ignore capacity for this run",
            "option": "…", "url": "<re-run form + url/text>"}
         ]
       }
     ]
   }
   ```
   `remediations` is a **list** (a violation usually has 2–3 possible fixes; e.g.
   `out_of_pool_marker` → "add to assessor pool" OR "accept out-of-pool"). Each carries a
   pre-rendered `url` threaded with the `url`/`text` return convention. Store ORM ids (future
   linking) plus a pre-rendered `message` (survives entity deletion). `severity` follows the
   weight tiers: unassigned/forced/base = error; out-of-pool/CATS/capacity = warning. The
   category→remediation mapping lives in `REMEDIATION` in `matching_diagnostics.py`; URL builders
   need `LiveProject`/`EnrollmentRecord`/`FacultyData` ids from `entities`, so resolve them in the
   report renderer (which has the enumeration dicts) rather than in the template.

8. **New draft-solution flag**. Add `is_draft = db.Column(db.Boolean(), default=False)` (or
   reuse a report-status check) on `MatchingAttempt` so views can distinguish a genuine
   solution from a diagnostic draft. `MatchingRecord`s exist but the attempt is INFEASIBLE.
   Keep `solution_usable` returning **False** for infeasible attempts (do NOT add INFEASIBLE to
   it) — this preserves every existing select/populate/rollover gate automatically.

9. **`_store_PuLP_solution` tolerance for drafts** (matching.py:2288): the hard
   `len(assigned) != multiplicity` check at 2390 must not crash on a partial draft where some
   students are unassigned. Add a `draft: bool` param: in draft mode, store whatever assignments
   exist and skip the strict multiplicity assertion; unassigned students simply have no record
   (which the tolerant `convert_selector` / validation step-2 already handle gracefully).

### Phase 3 — lifecycle gating

10. **Publish gate** (`publish_match`/`unpublish_match`, admin/matching.py:2978/3019): relax
    from `solution_usable` to `solution_usable OR (finished AND outcome==INFEASIBLE AND has
    report)`. Add a helper e.g. `record.publishable` on the model to centralize this.

11. **Keep hard-blocked** (verify, no change needed since they all key on `solution_usable`):
    - `select_match`/`deselect_match` (3099/3185) — rollover selection.
    - `populate_submitters` path (`_validate_match_populate_submitters` 3236, task 4252) —
      same-cycle `SubmittingStudent` population.
    - rollover `allocated_match` (selected=True only) — transitively blocked.
    Add an explicit outcome check comment at each so the intent is durable.

12. **Inspector/workspace access for infeasible drafts**. `matching_workspace` (admin/matching.py:1870)
    hard-rejects non-usable solutions at 1888. Add a read-only path: allow entry when
    `outcome==INFEASIBLE AND is_draft`, render a prominent **"Diagnostic draft — not a usable
    solution"** banner, and keep all per-record edit actions blocked (they already gate on
    `selected`; add an `is_draft`/infeasible guard too). This is the ~20-gate surface noted in
    exploration — audit each `solution_usable` gate (admin/matching.py lines 276, 922, 986, 1106,
    1212, 1271, 1291, 1400, 1717, 1776, 1888, 1964, 2206, …): read-only *view* gates get the
    relaxed condition; *mutation* gates (revert, edit roles, reassign, delete-record, duplicate,
    select, populate) stay `solution_usable`-only.

### Phase 4 — UI surfacing

13. **Matches dashboard card** (`app/ajax/admin/matching/matches_v2.py`, `_card` ~line 44):
    the Infeasible line gains a **"View diagnosis"** affordance and a draft-records summary.
    Follow the on-demand fragment pattern of `match_statistics_ajax` (admin/matching.py:264):
    new route `matching_diagnosis_ajax(id)` renders a new template
    `app/templates/admin/matching_workspace/_diagnosis.html`.

14. **Diagnosis panel = the single remediation surface** — must read **differently** from the
    existing error/warning badge+popover (`error_block.html`). Design: a full-width panel, not
    badges. Explanatory header ("The optimizer found the following minimal set of relaxations that
    would make this problem solvable"); violations grouped by category, errors-first then
    warnings; each row shows the `message` + an **amount** ("needs 2 more places") + its
    **`remediations` list** rendered as inline "Fix" buttons, each deep-linking (with `url`/`text`)
    to the relevant editor. Buttons split into two routes (see items 15–16). Include the
    interpretation caveat (FEASIBILITY.md §3.6): "one minimal repair, not a unique explanation;
    violations attributed to workload limits in preference to student assignments where possible."
    Semantic Bootstrap tokens per the template-colour rule; the `render_convenor_actions`
    CTA-banner macro is a good fit for the per-violation button rows.

15. **Re-run as an *editable* clone form** (decision: editable re-run form). New route
    `rerun_match(id)` (admin/matching.py) → renders a form **pre-filled from the infeasible
    attempt's configuration**, with the match-level option levers editable
    (`max_marking_multiplicity`, `max_different_group_projects`/`all_projects`,
    `supervising_limit`/`marking_limit`, `ignore_per_faculty_limits`, `force_base`, biases). The
    form **pre-highlights the levers the diagnosis implicated** (pass the set of relevant option
    names from the report). On submit: factor `_clone_match_config(src, overrides) ->
    MatchingAttempt` (config only — option columns + `config_members`/`supervisors`/`markers`/
    `projects` associations + `base`; **no** records/enumerations), apply the edited overrides,
    launch `create_match`. Reuse the existing `duplicate` task's config-copy logic if it cleanly
    separates config from records. `rerun_option`-type remediations in the panel deep-link here
    with the target option pre-focused. Menu entry for infeasible attempts (matches_v2.py ~163,
    replacing the dead "Solution is not usable" item). Closes the loop:
    read diagnosis → fix data or adjust settings → re-run.

### Phase 5 — remediation editors (the single-surface fixes)

The diagnosis panel wires each violation to an editor. **Most already exist**; the only genuinely
new editor is LiveProject capacity. Phase 5 = (a) build the one missing editor, (b) make sure the
report renderer can produce a correct deep-link for each remediation type, (c) the CATS-coherence
check.

16. **LiveProject capacity editor (NEW)** — convenor blueprint, convenors+root.
    `capacity`/`enforce_capacity` are real columns on `live_projects` (via
    `ProjectDescriptionMixin`/`ProjectConfigurationMixin`, model_mixins.py:785/393). Add
    `edit_liveproject_capacity` near the existing LiveProject editors (`app/convenor/projects.py`
    — `edit_liveproject_supervisors` at 885, alternatives editors). Small WTForms `Form`
    (flask_security base) with `capacity` IntegerField + `enforce_capacity` BooleanField, reusing
    `DescriptionSettingsMixinFactory` field defs (faculty/forms.py:307) where practical. CSRF via
    `form.hidden_tag()`; `url`/`text` return; `log_db_commit`; guard convenor owns the pclass.
    Category `project_capacity` → this route.

17. **Reuse existing editors for the other data levers** (no new code beyond correct URL
    builders in the report renderer):
    - `out_of_pool_marker` / `supervisor_is_marker` → assessor pool: `liveproject_attach_assessor`
      (projects.py:3307) or the pool manager `attach_assessors` (2991).
    - `out_of_pool_supervisor` → supervisor pool: `edit_liveproject_supervisors` (projects.py:885).
    - `pclass_cats_limit` → `custom_CATS_limits` (convenor/documents.py:178).
    - `global_cats_limit` → FacultyData CATS edit (admin) and/or the re-run form's match CATS
      limits / `ignore_per_faculty_limits`.
    - `forced_assignment` → custom-offer CRUD (selector_details.py:771+) / selection-hint edit.
    Each needs the target entity id (from `entities`) + `url`/`text`. **Verify each of these
    editors accepts and round-trips `url`/`text`**; where one doesn't yet, add it (small,
    per the return-link convention). For the "accept out-of-pool" alternative on
    `out_of_pool_*`, there is no data edit — it's an informational note that the draft's
    out-of-pool assignment is valid (validation only warns), so re-running won't remove it; the
    real fix is either enlarge the pool or leave as-is.

18. **Global-vs-per-pclass CATS coherence check** (decision: both edit-time and diagnosis).
    - **Edit-time**: in `custom_CATS_limits` (convenor/documents.py:178), after validation, warn
      (flash, non-blocking) when a per-pclass `EnrollmentRecord.CATS_supervision`/`marking` is set
      **above** the faculty member's global `FacultyData.CATS_*` — the per-class limit can never
      bind, so it is almost certainly a mistake. Factor the comparison into a small helper so the
      diagnosis path can reuse it.
    - **Diagnosis**: when a `global_cats_limit`/`pclass_cats_limit` violation involves a faculty
      member with incoherent limits, attach an advisory remediation ("per-class limit of N exceeds
      global limit of M; raise the global limit or lower the per-class limit") rather than only the
      generic "raise CATS" button.

### Cross-cutting

- **Deletion**: `infeasibility_report` is a scalar column (deletes with the row); draft
  `MatchingRecord`/`MatchingRole`/`MatchingEnumeration` already cascade (matching.py:1008/1065;
  utilities.py:1420). No new cleanup needed. Confirm `perform_delete_match` (admin/matching.py:719)
  still allows deleting infeasible attempts (it refuses on `published`/`selected` only —
  publishing an infeasible attempt will now block delete until unpublished, which is correct).
- **Scheduling out of scope**, but the diagnostics module + mixin column are placed so the future
  rollout to `app/tasks/scheduling.py` is mostly mechanical.

## Files touched (representative)

- `app/tasks/matching_diagnostics.py` — **new** (SlackEntry, registry, weights, renderer, remediation).
- `app/tasks/matching.py` — diagnostic mode in `_create_PuLP_problem`; `_diagnose_infeasibility`;
  wire into `_process_PuLP_solution`; pre-solve failure collection; `_store_PuLP_solution` draft
  tolerance; extend `PuLPProblem` namedtuple; Phase-0 C11 elasticization; `_clone_match_config` helper.
- `app/models/matching.py` — `infeasibility_report` column + property on `PuLPMixin`; `is_draft`;
  `publishable`/report accessors.
- `migrations/versions/<new>.py` — **new** hand-written Alembic migration (chain-tip check first).
- `app/admin/matching.py` — publish gate; workspace read-only draft access; editable
  `rerun_match` form; `matching_diagnosis_ajax`; audit of `solution_usable` gates.
- `app/ajax/admin/matching/matches_v2.py` — card diagnosis affordance + menu re-run item.
- `app/templates/admin/matching_workspace/_diagnosis.html`, `workspace.html` — **new panel** + draft banner.
- `app/convenor/projects.py`, `app/convenor/forms.py`, template — **new** LiveProject capacity editor.
- `app/convenor/documents.py` — CATS-coherence warning in `custom_CATS_limits`.
- Verify/patch `url`/`text` round-trip on the reused editors (`edit_liveproject_supervisors`,
  `liveproject_attach_assessor`/`attach_assessors`, `custom_CATS_limits`, custom-offer CRUD).

## Verification

No project test suite; verify by running the stack and with targeted synthetic fixtures.

1. **Synthetic infeasible fixtures** (construct via a scratch script against a dev DB, or a
   throwaway management shell), each engineered to trip exactly one category:
   (a) two students force-ranked onto a capacity-1 enforced project → `project_capacity`;
   (b) a require-hint on a full project → `forced_assignment`;
   (c) marker `max_marking_multiplicity` too low for the cohort → `marker_capacity`;
   (d) sole eligible marker == the supervisor → `supervisor_is_marker`;
   (e) per-pclass CATS limit below existing commitments → `pclass_cats_limit`;
   (f) assessor pool empty/too small for a project that uses markers → `out_of_pool_marker`;
   (g) supervisor pool too small (P=0 forced) → `out_of_pool_supervisor`;
   (h) a feasible control → empty report, normal OPTIMAL path unchanged.
   Confirm each produces exactly the expected violation category, a sensible `amount`, correct
   `remediations` deep-links, and a draft solution with the expected unassigned students.
   Confirm the weight ordering: when both a capacity fix and an out-of-pool fix could resolve a
   conflict, the report blames capacity (lighter) not the pool.
2. **Production-path regression**: run a known-feasible attempt; confirm identical outcome,
   score, records, and comparable `compute_time` to before (diagnostic code never executes when
   `diagnostic=False`).
3. **Lifecycle**: confirm an infeasible attempt can be published, is visible read-only to a
   convenor, cannot be selected, cannot populate submitters, and cannot be chosen at rollover.
4. **UI / single surface**: load the diagnosis panel via the card affordance; confirm it reads
   distinctly from the error/warning popovers; confirm each remediation type deep-links correctly
   and returns to the diagnosis via `url`/`text`: capacity editor (new), assessor pool, supervisor
   pool, `custom_CATS_limits`, custom-offer CRUD, and the editable re-run form (with the flagged
   option pre-highlighted).
5. **Re-run loop** (both routes): (i) data fix — increase a project's capacity → re-run → solves;
   (ii) option fix — raise `max_marking_multiplicity` in the re-run form → re-run → solves (or
   reports a different, now-smaller, infeasibility).
6. **CATS coherence**: set an `EnrollmentRecord` per-class limit above the faculty global in
   `custom_CATS_limits` → confirm the non-blocking warning; confirm the diagnosis advisory appears
   on a CATS violation involving that faculty member.
7. `ruff check app/tasks/matching.py app/tasks/matching_diagnostics.py app/models/matching.py`
   and `ruff format --line-length 150`.

## Out of scope / deferred

- Editable drafts (chosen: read-only). Hand-editing an infeasible draft toward feasibility would
  require new re-validation semantics and is deliberately excluded.
- Lexicographic count-minimization second pass for crisper attribution (FEASIBILITY.md §2 Phase 2).
- Rollout to `app/tasks/scheduling.py`.
