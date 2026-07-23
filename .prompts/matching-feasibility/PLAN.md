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
like. The report suggests concrete remediations — chiefly raising a `LiveProject`'s capacity,
which is currently not editable post-go-live and will be made editable by convenors.

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

## Constraint families to elasticize (from FEASIBILITY.md §1.3)

Keep hard: all structural/definitional constraints (ss/Z/Ysel/Ymark/yy links, levelling
brackets) and all eligibility constraints (`X<=R` with R=0, `S<=cap*P` with P=0, M=0 marker
entries, nosupv/nomark). Relax with one-sided slacks:

| Key | Constraint (matching.py loc) | Slack dir | Report category |
|---|---|---|---|
| C1 | selector multiplicity `Σ_j X == m_l` (1654) | `+u_l`, integer | `unassigned_student` |
| C2 | require/custom-offer `X[idx] == 1` (1668) | `+u`, binary | `forced_assignment` |
| C3 | base-match force `X==1` (1689), `Y==base_Y` (2017) | `+u`, binary | `base_match` |
| C4 | project capacity `S<=cap*P` where P=1 (1725) | `+u_kj`, integer | `project_capacity` |
| C6 | distinct-project limits (1812, 1822) | `+u_k`, integer | `distinct_projects` |
| C7 | marker capacity `Σ_l Y <= M` where M>0 (1875) | `+u_ij`, integer | `marker_capacity` |
| C9 | supervisor≠marker `ss+yy<=1` (1993) | `+u_kj`, binary | `supervisor_is_marker` |
| C11 | per-pclass CATS limits (2087, 2123) | `+u`, continuous | `pclass_cats_limit` |

C10 (global CATS) is **already elastic** via `sup_elastic_CATS`/`mark_elastic_CATS` — in
diagnostic mode these become report sources too (`global_cats_limit`). Parity constraints
C5 (supervisor parity, 1782) and C8 (marker parity, 1967) stay hard; conflicts route through
them to C4/C7/C10 slacks, which is the actionable side.

**Weights** (blame order; heaviest = least-preferred to blame), as named constants:
`forced_assignment`/`base_match` ≫ `unassigned_student` > count-slacks (capacity, distinct,
marker, sup-is-marker) > CATS slacks. This mirrors the existing "CATS = warning, unassigned =
error" convention in `matching_validation.py`.

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
         "remediation": {"type": "increase_capacity", "project_id": 123,
                         "url": "<convenor edit capacity url>", "label": "Increase capacity"}
       }
     ]
   }
   ```
   Store ORM ids (future linking) plus a pre-rendered message (survives entity deletion).
   `severity` follows the weight tiers: unassigned/forced/base = error; CATS/capacity = warning.

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

14. **Diagnosis panel** — must read **differently** from the existing error/warning badge+popover
    (`error_block.html`). Design: a full-width panel, not badges. Group violations by category
    with an explanatory header ("The optimizer found the following minimal set of relaxations
    that would make this problem solvable"), errors-first then warnings, each row showing the
    message + an **amount** ("needs 2 more places") + a **remediation button** where applicable
    (e.g. "Increase capacity of project X" linking to the new convenor capacity editor via the
    `url`/`text` return convention). Include the interpretation caveat (FEASIBILITY.md §3.6):
    "one minimal repair, not a unique explanation; violations attributed to workload limits in
    preference to student assignments where possible." Use semantic Bootstrap tokens per the
    template-colour rule; consider the `render_convenor_actions` CTA-banner macro for the
    remediation buttons where it fits.

15. **Re-run action** (chosen: include now). New endpoint `rerun_match(id)` (admin/matching.py):
    clone the `MatchingAttempt` *configuration* (all option columns + `config_members`,
    `supervisors`, `markers`, `projects` associations, `base`/`force_base`, biases, limits) into
    a fresh attempt with a derived name, **without** copying records/enumerations, then launch
    `create_match`. Reuse the existing `duplicate` task's config-copy logic if it cleanly
    separates config from records; otherwise factor a `_clone_match_config(src) -> MatchingAttempt`
    helper. Offer it in the Actions `_menu` for infeasible attempts (matches_v2.py ~line 163,
    replacing the dead "Solution is not usable" item). This completes the loop:
    read diagnosis → fix capacity/CATS → one-click re-run.

### Phase 5 — LiveProject capacity editing (convenor)

16. **New convenor route + form to edit a `LiveProject`'s `capacity`/`enforce_capacity`**
    (chosen: convenor blueprint, convenors+root). `capacity`/`enforce_capacity` are real columns
    on `live_projects` (via `ProjectDescriptionMixin`/`ProjectConfigurationMixin`,
    model_mixins.py:785/393). Add `edit_liveproject_capacity` near the existing alternatives
    editor (`app/convenor/projects.py` ~467). Form in `app/convenor/forms.py`: a small WTForms
    `Form` (flask_security base) with `capacity` IntegerField + `enforce_capacity` BooleanField
    — reuse field definitions from `DescriptionSettingsMixinFactory` (faculty/forms.py:307) where
    practical, per the mixin-sharing convention. CSRF via `form.hidden_tag()`. Thread the
    `url`/`text` return convention so the diagnosis panel's "Increase capacity" button returns to
    the diagnosis. `log_db_commit` on save. Guard: convenor must own/administer the project's
    pclass.
    - The diagnosis remediation `url` for `increase_capacity` points here.

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
- `app/admin/matching.py` — publish gate; workspace read-only draft access; `rerun_match`;
  `matching_diagnosis_ajax`; audit of `solution_usable` gates.
- `app/ajax/admin/matching/matches_v2.py` — card diagnosis affordance + menu re-run item.
- `app/templates/admin/matching_workspace/_diagnosis.html`, `workspace.html` — **new panel** + draft banner.
- `app/convenor/projects.py`, `app/convenor/forms.py`, template — LiveProject capacity editor.

## Verification

No project test suite; verify by running the stack and with targeted synthetic fixtures.

1. **Synthetic infeasible fixtures** (construct via a scratch script against a dev DB, or a
   throwaway management shell), each engineered to trip exactly one category:
   (a) two students force-ranked onto a capacity-1 enforced project → `project_capacity`;
   (b) a require-hint on a full project → `forced_assignment`;
   (c) assessor pool smaller than cohort×valence → `marker_capacity`;
   (d) sole eligible marker == the supervisor → `supervisor_is_marker`;
   (e) per-pclass CATS limit below existing commitments → `pclass_cats_limit`;
   (f) a feasible control → empty report, normal OPTIMAL path unchanged.
   Confirm each produces exactly the expected violation category, a sensible `amount`, and a
   draft solution with the expected unassigned students.
2. **Production-path regression**: run a known-feasible attempt; confirm identical outcome,
   score, records, and comparable `compute_time` to before (diagnostic code never executes when
   `diagnostic=False`).
3. **Lifecycle**: confirm an infeasible attempt can be published, is visible read-only to a
   convenor, cannot be selected, cannot populate submitters, and cannot be chosen at rollover.
4. **UI**: load the diagnosis panel via the card affordance; confirm it reads distinctly from
   the error/warning popovers, remediation buttons deep-link correctly, and the capacity editor
   round-trips (edit → return to diagnosis → re-run → feasible).
5. **Re-run loop**: infeasible attempt → increase a project's capacity → re-run → verify the new
   attempt solves (or reports a different, now-smaller, infeasibility).
6. `ruff check app/tasks/matching.py app/tasks/matching_diagnostics.py app/models/matching.py`
   and `ruff format --line-length 150`.

## Out of scope / deferred

- Editable drafts (chosen: read-only). Hand-editing an infeasible draft toward feasibility would
  require new re-validation semantics and is deliberately excluded.
- Lexicographic count-minimization second pass for crisper attribution (FEASIBILITY.md §2 Phase 2).
- Rollout to `app/tasks/scheduling.py`.
