# TODO: matching infeasibility diagnosis

Working docs: `PLAN.md` (approved plan), `FEASIBILITY.md` (design rationale + constraint inventory).
Commit each verified phase separately as a clean rollback point.

## Phase 0 — quick wins (independent, ship first)
- [ ] Make per-pclass CATS limits (C11) elastic in the **production** problem, mirroring C10
      (`sup_elastic_CATS`/`mark_elastic_CATS`). Add slack vars at `_create_PuLP_problem`
      (matching.py:2087, 2123), penalty term reusing `CATS_violation_penalty` (matching.py:1588).
- [ ] Verify a previously-infeasible-due-to-pclass-CATS attempt now solves; feasible attempts unchanged.

## Phase 1 — diagnostic core
- [ ] New module `app/tasks/matching_diagnostics.py`: `SlackEntry` dataclass, `SlackRegistry`,
      weight constants, report renderer, `REMEDIATION` category→action map.
- [ ] Add `diagnostic: bool = False` param to `_create_PuLP_problem`; branch the 8 elasticizable
      sites (C1 1654, C2 1668, C3 1689/2017, C4 1725, C6 1812/1822, C7 1875, C9 1993, C11 2087/2123);
      in diagnostic mode skip score + all levelling/bias terms, objective `min Σ w·u` (+ ε·pref
      tiebreaker for a sensible draft). Fold C10 into the registry too.
- [ ] Extend `PuLPProblem` namedtuple with `slack_registry` (None in normal mode).
- [ ] `_diagnose_infeasibility(record, init_data, base_data)`: rebuild diagnostic problem, solve
      packaged CBC `gapRel=0` timeLimit 600s, progress_update message, render + store report,
      store coarse draft via tolerant `_store_PuLP_solution`. try/except → `{"status":"failed"}`;
      diagnostic-infeasible → `{"status":"unresolved"}`.
- [ ] Wire into `_process_PuLP_solution` Infeasible branch (matching.py:3205), thread init/base data.
- [ ] Pre-solve failure collection: convert the 4 RuntimeErrors (matching.py:938, 995, 2070, 2106)
      into structured `{"status":"presolve"}` report items + clean OUTCOME_INFEASIBLE finish.

## Phase 2 — model, storage, lifecycle
- [ ] `infeasibility_report` Text column on `PuLPMixin` (collation utf8_bin) + JSON
      property/writer (LLMOrchestrationJob.recent_workflows pattern). Report schema in PLAN.md §7.
- [ ] `is_draft` Boolean on `MatchingAttempt`. Keep `solution_usable` False for INFEASIBLE.
- [ ] `_store_PuLP_solution` `draft: bool` param: skip strict `len(assigned)!=multiplicity`
      assertion (matching.py:2390) in draft mode; store partial assignments.
- [ ] Hand-written Alembic migration (chain-tip check per CLAUDE.md; utf8_bin in migration).

## Phase 3 — lifecycle gating
- [ ] Publish gate relax: `publishable` model helper = usable OR (finished & INFEASIBLE & has report);
      apply in `publish_match`/`unpublish_match` (admin/matching.py:2978/3019).
- [ ] Confirm select/deselect (3099/3185), populate (`_validate_match_populate_submitters` 3236,
      task 4252), rollover `allocated_match` stay hard-blocked; add durable comments.
- [ ] `matching_workspace` (1888) read-only draft access for INFEASIBLE+is_draft + banner;
      audit all `solution_usable` gates (276, 922, 986, 1106, 1212, 1271, 1291, 1400, 1717, 1776,
      1888, 1964, 2206, …): view gates relaxed, mutation gates unchanged.

## Phase 4 — UI surfacing
- [ ] Card "View diagnosis" affordance + draft-records summary (matches_v2.py `_card` ~44);
      new `matching_diagnosis_ajax(id)` route (on-demand fragment, like match_statistics_ajax).
- [ ] New `_diagnosis.html` panel — reads differently from error_block badges: full-width,
      grouped by category, errors-first, amount + remediation buttons, interpretation caveat.
      Semantic Bootstrap tokens; `render_convenor_actions` for buttons where it fits.
- [ ] `rerun_match(id)` endpoint + `_clone_match_config` helper (config only, no records/enums);
      menu item for infeasible attempts (matches_v2.py ~163).
- [ ] Draft banner in `workspace.html`.

## Phase 5 — LiveProject capacity editing (convenor)
- [ ] `edit_liveproject_capacity` route (app/convenor/projects.py ~467) + small WTForms form
      (app/convenor/forms.py) with capacity/enforce_capacity (reuse DescriptionSettingsMixinFactory
      fields). CSRF hidden_tag; url/text return convention; log_db_commit; pclass-ownership guard.
- [ ] Point diagnosis `increase_capacity` remediation url here.

## Verification (see PLAN.md)
- [ ] 6 synthetic fixtures (one per category + feasible control).
- [ ] Feasible-path regression (identical outcome/score/records/timing).
- [ ] Lifecycle checks (publish ok; select/populate/rollover blocked).
- [ ] UI + capacity round-trip + full re-run loop.
- [ ] ruff check + format.
