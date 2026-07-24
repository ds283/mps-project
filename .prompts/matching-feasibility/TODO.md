# TODO: matching infeasibility diagnosis

Working docs: `PLAN.md` (approved plan), `FEASIBILITY.md` (design rationale + constraint inventory).
Commit each verified phase separately as a clean rollback point.

## Phase 0 — quick wins (independent, ship first)
- [ ] Make per-pclass CATS limits (C11) elastic in the **production** problem, mirroring C10
      (`sup_elastic_CATS`/`mark_elastic_CATS`). Add slack vars at `_create_PuLP_problem`
      (matching.py:2087, 2123), penalty term reusing `CATS_violation_penalty` (matching.py:1588).
- [ ] Verify a previously-infeasible-due-to-pclass-CATS attempt now solves; feasible attempts unchanged.

## Phase 1 — diagnostic core
- [x] New module `app/tasks/matching_diagnostics.py`: `SlackEntry` dataclass, `SlackRegistry`,
      weight constants, report renderer, `REMEDIATION` category→action map.
- [x] Add `diagnostic: bool = False` param to `_create_PuLP_problem`; branch the elasticizable
      sites (C1 1654, C2 1668, C3 1689/2017, C4 1725, C6 1812/1822, C7 1875, C9 1993, C11 2087/2123,
      **CP-M/CP-S pool eligibility** — the `M=0`/`P=0` cases at 1875/1725);
      in diagnostic mode skip score + all levelling/bias terms, objective `min Σ w·u` (+ ε·pref
      tiebreaker for a sensible draft). Fold C10 into the registry too. Pool slacks add NO new
      variables (Y/S already exist); register a pool `SlackEntry` only for entries driven nonzero.
      (Implementation note: CP-S required also dropping the `P` factor from the C5 supervisor
      parity sum in diagnostic mode — otherwise an out-of-pool S assignment is invisible to
      demand-parity and the solver never uses the slack. CP-M needed no parity change since Ymark
      isn't pre-multiplied by pool eligibility. See comments at the C4/C5 sites in matching.py.)
- [x] Extend `PuLPProblem` namedtuple with `slack_registry` (None in normal mode).
- [x] `_diagnose_infeasibility(record, init_data, base_data)`: rebuild diagnostic problem, solve
      packaged CBC `gapRel=0` timeLimit 600s, progress_update message, render + store report,
      store coarse draft via tolerant `_store_PuLP_solution`. try/except → `{"status":"failed"}`;
      diagnostic-infeasible → `{"status":"unresolved"}`.
- [x] Wire into `_process_PuLP_solution` Infeasible branch (matching.py:3205), thread init/base data.
- [x] Pre-solve failure collection: convert the 4 RuntimeErrors (matching.py:938, 995, 2070, 2106)
      into structured `{"status":"presolve"}` report items + clean OUTCOME_INFEASIBLE finish.
      Wired into `create_match` only (short-circuits before `_create_PuLP_problem`); `offline_match`
      and `process_offline_solution` still call the now-tolerant `_build_ranking_matrix` but are not
      yet wired to short-circuit on `presolve_failures` — left for a follow-up, noted in commit.
      Also required pulling `infeasibility_report` (PuLPMixin column + migration) forward from
      Phase 2, since Phase 1 has nowhere else to persist the report.

## Phase 2 — model, storage, lifecycle
- [x] `infeasibility_report` Text column on `PuLPMixin` (collation utf8_bin) + JSON
      property/writer (LLMOrchestrationJob.recent_workflows pattern). Report schema in PLAN.md §7 —
      note `remediations` is a **list** per violation, entity ids resolved in the renderer.
      (Pulled forward into Phase 1 — see migration 6d4e2a9f1c73.)
- [x] `is_draft` Boolean on `MatchingAttempt`. Keep `solution_usable` False for INFEASIBLE
      (unchanged — only checks OPTIMAL/FEASIBLE). `_store_PuLP_solution` sets `record.is_draft = draft`.
- [x] `_store_PuLP_solution` `draft: bool` param: skip strict `len(assigned)!=multiplicity`
      assertion (matching.py:2390) in draft mode; store partial assignments.
      (Pulled forward into Phase 1 alongside `_diagnose_infeasibility`, which already calls with
      `draft=True`; Phase 2 added the `record.is_draft` flag write.)
- [x] Hand-written Alembic migration (chain-tip check per CLAUDE.md; utf8_bin in migration) —
      `9f2a8b1c4d6e` (down_revision `6d4e2a9f1c73`), `is_draft` Boolean on `matching_attempts`.

## Phase 3 — lifecycle gating
- [ ] Publish gate relax: `publishable` model helper = usable OR (finished & INFEASIBLE & has report);
      apply in `publish_match`/`unpublish_match` (admin/matching.py:2978/3019).
- [ ] Confirm select/deselect (3099/3185), populate (`_validate_match_populate_submitters` 3236,
      task 4252), rollover `allocated_match` stay hard-blocked; add durable comments.
- [ ] `matching_workspace` (1888) read-only draft access for INFEASIBLE+is_draft + banner;
      audit all `solution_usable` gates (276, 922, 986, 1106, 1212, 1271, 1291, 1400, 1717, 1776,
      1888, 1964, 2206, …): view gates relaxed, mutation gates unchanged.

## Phase 4 — UI surfacing + editable re-run
- [ ] Card "View diagnosis" affordance + draft-records summary (matches_v2.py `_card` ~44);
      new `matching_diagnosis_ajax(id)` route (on-demand fragment, like match_statistics_ajax).
- [ ] New `_diagnosis.html` panel = **single remediation surface**: reads differently from
      error_block badges (full-width, grouped by category, errors-first, amount + per-violation
      `remediations` button list, interpretation caveat). Semantic Bootstrap tokens;
      `render_convenor_actions` for the button rows.
- [ ] **Editable** `rerun_match(id)` form (admin/matching.py): pre-fill from infeasible attempt,
      expose match-option levers (`max_marking_multiplicity`, `max_different_*`, match CATS limits,
      `ignore_per_faculty_limits`, `force_base`, biases), pre-highlight diagnosis-implicated ones;
      on submit `_clone_match_config(src, overrides)` (config only, no records/enums) + launch
      `create_match`. `rerun_option` remediations deep-link here. Menu item for infeasible attempts
      (matches_v2.py ~163).
- [ ] Draft banner in `workspace.html`.

## Phase 5 — remediation editors (single-surface fixes)
- [ ] **NEW** `edit_liveproject_capacity` route (app/convenor/projects.py near
      `edit_liveproject_supervisors` ~885) + small WTForms form (app/convenor/forms.py) with
      capacity/enforce_capacity (reuse DescriptionSettingsMixinFactory fields). CSRF hidden_tag;
      url/text return; log_db_commit; pclass-ownership guard. Category `project_capacity` → here.
- [ ] Report renderer builds correct deep-links (with url/text) for the **reused** editors:
      assessor pool (`liveproject_attach_assessor` 3307 / `attach_assessors` 2991),
      supervisor pool (`edit_liveproject_supervisors` 885), `custom_CATS_limits` (documents.py:178),
      custom-offer CRUD (selector_details.py:771+). **Verify each accepts/round-trips url/text**;
      add where missing.
- [ ] `out_of_pool_*` "accept out-of-pool" alternative = informational note (validation only warns;
      no data edit).
- [ ] CATS coherence: helper comparing EnrollmentRecord vs FacultyData CATS limits; non-blocking
      warning in `custom_CATS_limits` (documents.py:178) when per-class > global; diagnosis advisory
      on CATS violations involving incoherent limits.

## Verification (see PLAN.md)
- [ ] 8 synthetic fixtures: project_capacity, forced_assignment, marker_capacity,
      supervisor_is_marker, pclass_cats_limit, out_of_pool_marker, out_of_pool_supervisor,
      + feasible control. Check category, amount, remediations deep-links, draft unassigned set,
      and weight ordering (capacity blamed before pool).
- [ ] Feasible-path regression (identical outcome/score/records/timing).
- [ ] Lifecycle checks (publish ok; select/populate/rollover blocked).
- [ ] Single-surface UI: each remediation type deep-links + returns via url/text (capacity, pools,
      CATS, offers, editable re-run with flagged option pre-highlighted).
- [ ] Re-run loop both routes: data fix (capacity) + option fix (max_marking_multiplicity).
- [ ] CATS coherence: edit-time warning + diagnosis advisory.
- [ ] ruff check + format.
