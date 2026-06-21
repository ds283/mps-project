# Phase 5 recon output — details child-row, language analysis, risk breakdown, feedback documents

## 1. Current state confirmed (post Phase 4b)

`app/dashboards/views.py::avd_dashboard_ajax()` (lines ~2814-3013) builds `columns =
{"report": report_col, "report_grade": report_grade_col, "role_holder_search": ...,
"programme_search": ..., "group_search": ..., "pclass_search": ...}` and calls
`handler.build_payload(avd_dashboard_rows)`. `avd_dashboard_rows()` lives in
`app/ajax/archive/reports.py:306`, exactly as phase4b-recon-output.md describes: it builds
`identity_parts` via `_identity_line_parts()`, computes `convenor_intervention` /
`out_of_tolerance_unassigned` / `moderation_outcome` from the latest `SubmitterReport`, and
renders the `_report` Jinja string (macros: `turnitin_chips`, `identity_line`,
`consent_badges`, `flags_line`, `staff_roles`). Two real DataTables columns only
(`report`, `report_grade`); extra dict keys on each row (like the `details` field this phase
adds) are not columns and DataTables ignores them unless referenced — confirmed safe per
phase4b-recon-output.md §3.

## 2. Corrections to this prompt's header / to recon.md's framing

- **`risk_factors_ui_summary` is a plain method, not a `@property`.** Verified directly at
  `app/models/submissions.py:2246`: `def risk_factors_ui_summary(self) -> dict:` (no
  decorator). Existing call sites (`submitters_macros.html:159`,
  `submitters_v2.html:892`) call it as `r.risk_factors_ui_summary()`. This prompt's header
  matches recon.md's phrasing exactly, so no behaviour change — just flagging that a
  same-named subagent recon pass earlier in this conversation incorrectly asserted it was a
  property; the source confirms it is not.
- **`risk_factors_ui_summary()` is itself gated on `language_analysis_complete` at existing
  call sites** (`submitters_v2.html:892`: `r.risk_factors_ui_summary() if
  r.language_analysis_complete else none`). This phase follows the same convention rather
  than calling it unconditionally — see §5.
- **`SubmissionRecord.RISK_WORD_COUNT_DISCREPANCY` already exists** and is already computed
  by `_compute_risk_factors()`-equivalent logic at `app/models/submissions.py:2703-2723`,
  using `config.effective_word_count_tolerance` (default 15%) to decide whether the
  stated/measured word-count gap is "significant". This directly answers the open question
  in this prompt's Step 2 about inventing a threshold: **no threshold needs inventing** —
  the system already has one, tenant/pclass-configurable, and it already appears in
  `risk_factors_ui_summary()`'s `factors` list under key `"word_count_discrepancy"` whenever
  `discrepancy_pct > tolerance`. Decision: render the existing `discrepancy_pct`/
  `tolerance_pct` values (pulled from `risk_factors_data` directly, not recomputed) as an
  inline badge next to the stated/measured word counts, sourced from the same factor that
  also appears in the full risk-factor breakdown — no duplicate computation.
- **`metrics.get("page_count")` (used internally by the document-length risk factor) is a
  pre-existing, unrelated latent bug** — `app/tasks/language_analysis.py` only ever sets
  page count at the top level (`data["_page_count"] = page_count`, line 1690), never inside
  `metrics`, so that risk factor's page-limit branch is dead code today. Not touched in this
  phase (out of scope, no instruction to fix it); this phase reads `_page_count` (the correct
  key, confirmed by recon.md §8) directly for display.
- **`accepted_moderator_report` lives on `SubmitterReport`, not `SubmissionRecord`** — confirmed
  at `app/models/markingevent.py:1086-1099`. Not needed for this phase anyway — see §4.

## 3. DataTables child-row mechanism — no existing precedent (Step 0.7)

Confirmed zero matches anywhere in the repo for `row().child`, `dt-control`, `fnOpen`, or
similar (grepped `app/static/**/*.js` and `app/templates/**/*.html`). This phase introduces
DataTables' own built-in child-row API (`table.row(tr).child(html).show()` /
`.child.hide()`) for the first time in this codebase — not a home-grown mechanism, but the
library feature already shipped with the DataTables bundle this page already imports via
`import_datatables()`.

**Chosen approach: pre-rendered HTML included in each row's JSON payload** (`"details"` key,
sibling to `"report"`/`"report_grade"`, not a DataTables column), toggled client-side. Rejected
alternative: a lazy per-row `GET /dashboards/avd/record/<id>` endpoint fetching details on
first expand.

Tradeoff stated: the lazy-endpoint approach avoids paying the rendering/serialisation cost for
rows nobody expands, and avoids growing the per-page JSON payload. But it requires a second
authenticated endpoint duplicating `_can_access_avd_dashboard()` plus per-record access logic,
adds a round-trip delay on every first click, and breaks from this codebase's established
row-formatter convention (`.claude/rules/ajax-datatables.md`: "Row formatters: ... pre-evaluate
the templates in the current Jinja2 environment ... apply to the rows to be formatted" — i.e.
this codebase's convention is to render everything server-side as part of the row payload, not
lazily per-interaction). `ServerSideSQLHandler` already paginates (10-50 rows/page typically),
so the overhead is bounded per page load, and instant expand (no spinner, no failure mode) is
better UX for a low-traffic internal dashboard. Going with pre-rendered HTML for consistency
with the rest of this codebase's AJAX/DataTables pattern.

**Multiple rows expanded at once**: allowed (no global "close others" tracking). Simpler, and
the prompt says this is fine.

## 4. Per-role MarkingReport / ModeratorReport link resolution (Step 0.4/0.5)

Confirmed `MarkingReport.role_id`/`.role` and `ModeratorReport.role_id`/`.role` are both direct
FKs to `SubmissionRole` (`app/models/markingevent.py:1270-1278` and `:1441-1449`), with reverse
backrefs `SubmissionRole.marking_reports` / `SubmissionRole.moderator_reports` (both
`lazy="dynamic"`). This means **no need to traverse `MarkingEvent` → `MarkingWorkflow` →
`SubmitterReport` at all** — for a role already in the main row's `staff_roles` block, the
report is reached directly as `role.marking_reports` / `role.moderator_reports`, ordered by
`creation_timestamp.desc(), id.desc()` to pick the most recent if a role has accumulated more
than one report across re-marking events. This is simpler than the
`accepted_moderator_report`/`_latest_submitter_report()` path recon.md §0.5 suggested checking,
and reuses an existing, direct relationship rather than re-deriving anything new.

**Link targets** (existing routes, reused as-is, no new routes):
- `MarkingReport` → `faculty.view_marking_report` (`/view_marking_report/<int:report_id>`,
  `app/faculty/views.py:3771`) — genuinely read-only, already linked from
  `similarity_concern_detail.html` (an existing dashboard), confirming precedent for linking a
  dashboard row to this view.
- `ModeratorReport` → `faculty.moderator_report_form` (`/moderator_report_form/<int:mod_report_id>`,
  `app/faculty/views.py:3914`) — only existing route for a `ModeratorReport`; combined
  display+edit, no separate read-only view exists.

**Known, pre-existing permission gap (not introduced by this phase)**: both routes are
decorated `@roles_accepted("faculty", "admin", "root")`. The AVD dashboard's own gate
(`_can_access_avd_dashboard()`) accepts `root`/`admin`/`data_dashboard_reports` — a
`data_dashboard_reports`-only user (no `faculty`/`admin`/`root`) would get redirected/blocked
clicking through. This exact same gap already exists for the Similarity dashboard's
`_can_access_similarity_dashboard()` (root/admin/`data_dashboard_similarity`/convenor), which
already links to `faculty.view_marking_report` from `similarity_concern_detail.html` today.
Decision: reuse the established pattern as-is (per this prompt's own instruction to prefer
existing precedent) rather than widening `faculty.view_marking_report`'s/`moderator_report_form`'s
decorator — that is a cross-blueprint security-decorator change affecting other call sites,
and arguably a separate decision, not a silent side-fix bundled into this phase. Flagging here
rather than fixing unilaterally.

## 5. Embargo gating — where the line is drawn (Step 3)

Decision: suppress (when `is_report_restricted`) — **feedback document links**, **AI
declaration text/found-state**, **`report_summary`**. Keep visible — word/page/table/figure
counts, stated-word-count/discrepancy badge, the full risk-factor breakdown (presence/resolved/
resolver/annotation), and staff role report links.

Reasoning: this mirrors the precedent already set in Phase 2 — the report's own
thumbnail and Original/Processed download buttons are suppressed by `is_report_restricted`,
but staff-role names and flags elsewhere in the row are not. Marking/moderator reports are a
different document (assessor output, not the student's submitted report) so they stay
visible — moderation/marking activity isn't "the report's content," it's downstream evaluation
of it, and convenors/admins reviewing an embargoed record still need to see who marked it and
link through. Risk-factor *presence* (a flag was raised, resolved or not) is operationally
necessary even during an embargo (someone still has to resolve it), but the *annotation text*
written by whoever resolved it can itself describe report content — annotations are **not**
suppressed here since they're written by staff about a risk factor, not extracted from the
report text itself, and `risk_factors_ui_summary()`'s own factors (including annotation) are
already shown unconditionally elsewhere in the app regardless of embargo (e.g.
`submitters_v2.html`) — so no precedent for gating annotations specifically. AI declaration text
and `report_summary`, by contrast, are both *directly extracted/derived from the embargoed
document's content* — closest to "the report's actual content" per this prompt's own framing —
so those are suppressed, along with the feedback PDF link (a generated artifact of the
marking process tied 1:1 to this specific report).

## 6. Main-row flags_line gap closure (cross-referenced by this prompt's Step 2)

Phase 4b's recon explicitly left a gap: *"AI risk and the feedback-document link remain absent
(no placeholder) pending Phase 5."* This prompt's Step 2 says the full risk-factor breakdown
"is where the Phase 3-era 'note icon' on the flags line in the main row should link to/expand"
— which only makes sense if a note icon (attached to *something* on the main row) exists to
click. Decision: close the **AI-risk** half of that gap only, not the feedback-link half:

- Add a small "AI flagged" / "AI flagged · resolved" badge to `flags_line()`, derived from
  just `RISK_AI_COMPLIANCE`/`RISK_AI_USE` (matching recon.md §10's exact wording) — Turnitin
  already has its own dedicated chip (`turnitin_chips()`), and the remaining risk types
  (document length, similarity, chunking-failure) were never part of the agreed main-row
  design, only the full breakdown. A small note icon is appended only when either AI factor
  carries a non-empty annotation. Both the badge and the note icon share a `avd-details-toggle`
  class with the new "Show full marking & report details" link, so clicking any of them expands
  the same child row — satisfying "clicking it opens the same details panel as everything else,
  not a separate popover" from recon.md §10.
- **Not adding** a main-row feedback-document indicator. This prompt's own Scope paragraph and
  Step 2 bullet list place "the feedback document link" inside the child row's content, not the
  main row; Step 1's expand trigger is described as a single inline link, with no second trigger
  for feedback specifically. Recon.md §10's original (broader) design wanted a main-row feedback
  indicator too, but since this prompt's literal Step 1/Step 2 text doesn't ask for it, and
  CLAUDE.md instructs against adding scope beyond what's asked, this phase leaves it inside the
  child row only.

## 7. Significant-difference word-count flag — resolved, not asked (Step 2)

Per §2 above: not inventing a threshold. The inline badge next to stated/measured word counts in
the details panel reads the already-computed `discrepancy_pct`/`tolerance_pct` straight off
`risk_factors_data["word_count_discrepancy"]` (same source the full breakdown section also
reads), shown only when that factor's `present` is `True` (i.e. the system already decided the
gap exceeds tolerance) — no separate/duplicate "significant" computation.

## 8. Data availability gating (language analysis vs. risk factors vs. role reports)

Following `submitters_v2.html:892`'s exact precedent, this phase only reads
`language_analysis_data` / calls `risk_factors_ui_summary()` when
`record.language_analysis_complete` is `True` — otherwise metrics/AI-declaration/summary/risk
sections are all omitted (not rendered as "pending" or "N/A", consistent with "absence is the
signal"). Staff-role report links and feedback-document links are independent of this flag
(they come from separate relationships) and are evaluated unconditionally.

## Step 4 — Verification (static; live browser/DB check deferred per user request)

Confirmed by code inspection, not a live browser session:

- **Expand/collapse vs. DataTables sort/pagination/search**: `avd_dashboard_ajax()`'s
  `columns` dict (Python, server-side) is untouched — `report`/`report_grade`/
  `role_holder_search`/`programme_search`/`group_search`/`pclass_search` are exactly as
  before this phase. The new `details` field is a sibling key on each row's JSON payload,
  never referenced by any DataTables `columns[].data` path, so it cannot affect sort/search/
  paging (confirmed both server-side, where `ServerSideSQLHandler.build_payload()` passes
  `row_formatter(...)`'s output straight through to `jsonify()` with no filtering, and
  client-side, where DataTables only inspects `columns[].data` to build cells). Expand/
  collapse itself uses DataTables' own `row().child()` API — the standard mechanism for
  exactly this purpose — bound via a delegated handler on `tbody` so it survives redraws
  triggered by sort/search/page changes (DataTables itself auto-closes any open child row on
  redraw, which is expected, documented behaviour, not a bug introduced here).
- **Clean panel when no risk factors present**: `risk_factors_ui_summary()` returns
  `factors: []`, `has_any_present: False` when nothing is present (confirmed from its source
  at `submissions.py:2287-2295`); the `{% if rf.has_any_present %}` guard around the entire
  "Risk factors" block means nothing renders. `_ai_risk_summary()` also returns `None` when
  `factors` is empty, so the main-row AI badge doesn't render either.
- **Resolved AI factor with annotation**: traced a factor dict with
  `present=True, resolved=True, annotation="..."` through `risk_factors_ui_summary()` →
  `_details_context()` (adds `resolved_at_display`) → the `_details` template's resolved
  branch, which renders the success badge, "resolved by `<name>` · `<date>`", and the
  annotation text in the bordered `<div>` beneath it. `_ai_risk_summary()` independently
  picks up the same annotation for the main-row note icon's tooltip trigger.
- **Restricted record gating**: traced `restricted=True` through `_details_context()` —
  `genai_status`/`genai_statement`/`report_summary` all stay `None` (their computation is
  inside `if not restricted:`), so their template sections (`{% if genai_status is not none %}`,
  `{% if report_summary %}`) don't render; `feedback_links` is forced to `[]`. Metrics,
  `risk_factors_ui_summary()`, and `_role_report_links()` are computed unconditionally, so
  those sections still render, per the §5 decision. The restricted-notice block
  (`{% if restricted %}`) renders explaining what's hidden.
- **Staff-role report links resolve to the correct individual report**: `_role_report_links()`
  iterates exactly the `roles` list already used for the main row's `staff_roles()` block (the
  same `record.roles.all()`), and for each role queries `role.marking_reports`/
  `role.moderator_reports` — both direct backrefs off `MarkingReport.role_id`/
  `ModeratorReport.role_id` (FKs to `submission_roles.id`) — so the report linked is provably
  scoped to that specific role, not "any report on the event."
- **Feedback document download**: `_feedback_links()` builds
  `url_for("admin.download_generated_asset", asset_id=fr.asset_id)` off
  `record.feedback_reports.all()` — identical to the already-working pattern at
  `view_feedback.html:97-98`/`app/admin/utilities.py:347` (which performs its own
  `asset.has_access(current_user.id)` check, independent of how the link was reached).
- **No regression to columns/sort/filters**: confirmed by grep that `avd_dashboard_ajax()`
  (`app/dashboards/views.py`) was not edited at all in this phase, and that the DataTables
  `columns:`/`order:`/filter-button markup in `avd_dashboard.html` is untouched apart from
  capturing the table instance in a `table` variable and appending the new delegated click
  handler after initialisation.

Not checked (deferred — would require live DB state and a browser): actual rendered
appearance, click responsiveness, and confirming a real embargoed/AI-flagged record exists
in the dev database to click through.

## Summary of code changes

- `app/ajax/archive/reports.py`: add `_ai_risk_summary()`, `_format_resolved_at()`,
  `_role_report_links()`, `_feedback_links()`, `_details_context()` helpers; extend `_report`
  Jinja string's `flags_line` macro with the AI-risk badge/note-icon; add the "Show full
  marking & report details" link; add a new `_details` Jinja string + `_build_details_templ()`;
  wire a `"details"` key into each row's payload in `avd_dashboard_rows()`.
- `app/templates/dashboards/avd_dashboard.html`: add a delegated click handler on
  `.avd-details-toggle` using DataTables' `row().child()` API to expand/collapse.
- No model-layer changes — every field/method/relationship needed already exists.
