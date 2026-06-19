# Phase 2 — AVD dashboard: report grade column, thumbnails, embargo handling

Shared context: `.prompts/avd-dashboard/recon.md` (row/column design is
§10 — read this before touching `avd_dashboard_ajax()`'s columns) and
`.prompts/avd-dashboard/phase1-recon-output.md` (current state of the
route/template after Phase 1 landed — file names below assume that
output; re-confirm paths in your own Step 0 if anything's moved since).

This phase touches `avd_dashboard_ajax()` (in `app/dashboards/views.py`
per Phase 1) and `dashboards/avd_dashboard.html`. Scope is: the
`report_grade` column (sortable, default sort), supervision/presentation
grades as plain text in the row panel, thumbnails, and embargo/restriction
handling for both. **No consent badges, no staff-roles block, no details
child-row yet** — those are Phases 3–5. If you find yourself adding a
badge for AVD/exemplar consent or iterating `SubmissionRole`s, stop —
that's later.

## Step 0 — Reconnaissance (produce a written plan before touching code,

output to `.prompts/avd-dashboard/phase2-recon-output.md`)

1. **Embargo logic**: find where the current "Report restricted" text in
   the legacy archive view is produced (likely `app/ajax/archive.py` or
   wherever `retired_reports`/the row-builder for the old `reports.html`
   lived before Phase 1 — check git history if the file's been deleted,
   `git log --all --full-name -- '*archive*'` or similar). Identify the
   exact comparison used against `SubmissionRecord.report_embargo`
   (e.g. is it `report_embargo > datetime.now()`, i.e. "embargoed until
   this date and not yet released", or something else — confirm, don't
   assume) and what UI elements it currently suppresses when active
   (thumbnail? Original/Processed download buttons? both?). Quote the
   exact code found.
2. **Thumbnail mechanism**: locate `serve_thumbnail` and confirm its
   current call signature, the timeout/placeholder behaviour already
   built for it (per memory, this was hardened separately against Minio
   unavailability), and how it's invoked from any existing template (e.g.
   the convenor submitters view, if it renders thumbnails anywhere
   today) — reuse the exact same call pattern, don't reinvent it.
3. **Current `avd_dashboard_ajax()` columns dict**: copy verbatim. Confirm
   `report_grade` is a real column on `SubmissionRecord` (per
   `recon.md` §5 it is, `Numeric(8,3)`) and check whether
   `ServerSideSQLHandler` needs anything beyond `order`/`search` keys to
   make a `Numeric` column sortable (e.g. does it need an explicit
   `cast()` for search, or is `order` alone sufficient since we're not
   making it searchable as free text).
4. **Current row template** (`dashboards/avd_dashboard.html` or wherever
   Phase 1 left the row-rendering — confirm path): copy the relevant
   block verbatim so the edit is additive, not a rewrite.

Stop and present this plan before proceeding.

## Step 1 — `report_grade` column

- Add `report_grade` to the `columns` dict in `avd_dashboard_ajax()`,
  `order`-able against `SubmissionRecord.report_grade`. Not searchable as
  free text (it's numeric and has its own filter mechanism — see Step 3).
- Set this as the default sort column, descending (highest grade first),
  consistent with `recon.md` §10 point 2 — report grade is the primary
  sort key for AVD selection.
- Render it as a right-aligned numeric cell in the row template, one
  decimal place, matching the existing grade-display formatting already
  used elsewhere in the app (check `marking_dashboard.html` or similar
  for the exact format string rather than inventing one — e.g. `"%.1f"`
  vs `"%.1f%%"`; confirm which is used for `report_grade` specifically
  versus the `%`-suffixed health-indicator percentages on the Marking
  Dashboard, since those are a different kind of number).
- Add a "has grade" filter (tri-state: any / graded / ungraded) as a
  filter button alongside the existing pclass/year/group/tenant buttons,
  per `recon.md` — `report_grade.isnot(None)` / `.is_(None)`.

## Step 2 — Supervision / presentation grades as panel text

- In the row template, add a compact text line inside the existing
  identity block (not a new column): `Supervision {x} · Presentation {y}`,
  using `—` (em dash) when either is `None`, same formatting convention
  as Step 1. This sits in the panel cell that already exists from Phase 1
  (student name / project title / programme / year), not a new `<td>`.

## Step 3 — Thumbnails, with embargo handling

- Add a thumbnail to the left of each row's panel content, using the
  exact `serve_thumbnail` mechanism identified in Step 0.2 — same
  timeout/placeholder fallback, don't re-implement.
- **If the Step 0.1 recon confirms `report_embargo` is currently active
  for a given record** (i.e. the same condition the legacy view used to
  show "Report restricted"): suppress the thumbnail and show a small
  "Restricted until {date}" indicator in its place instead of the
  thumbnail image — same visual slot, different content, so the row
  layout doesn't jump around between embargoed and non-embargoed rows.
- Carry the same restriction check through to the "Original"/"Processed"
  download links if those already exist in the row template carried over
  from the legacy view — they should be suppressed (or shown disabled
  with the same "Restricted until {date}" label) under the identical
  condition, not a separately-invented one. If the legacy view didn't
  show Original/Processed in the AVD-relevant row context — confirm via
  Step 0.1 — say so rather than adding download buttons that weren't part
  of this phase's brief.
- Flag in your output whether `report_embargo` should also suppress
  anything from Phase 1 (it shouldn't — Phase 1 has no per-report
  content) or anything planned for Phases 3–5 per `recon.md` (it likely
  should suppress the feedback-document link in Phase 5, and arguably the
  AI-declaration/LLM-summary details panel content too) — don't implement
  those suppressions now, just note them as a forward dependency so
  Phase 5's prompt can reference this phase's embargo-check helper rather
  than re-deriving it.
- Factor the embargo check into one small reusable helper (e.g. a
  `SubmissionRecord.is_report_restricted` property, or a template macro,
  whichever matches how the legacy logic was structured) rather than
  duplicating the date comparison inline in three places across this
  phase and the two later phases that will need it.

## Step 4 — Verification

- `grep -rn "report_embargo"` — confirm every call site uses the new
  shared helper from Step 3, not a re-derived inline comparison.
- Manually confirm (describe what you checked):
    - a report with `report_embargo` in the future shows the restricted
      placeholder, not a thumbnail or broken image request
    - a report with `report_embargo` unset, or in the past, shows its
      thumbnail normally
    - sorting by report grade (both directions) returns correct order
      against a few known records, including records with `report_grade is
    None` — confirm where nulls sort (last, by default in most DBs — note
      if this needs an explicit `NULLS LAST`/equivalent for your DB backend)
    - the "has grade" filter correctly excludes/includes ungraded records
- Confirm no Phase 3–5 functionality was touched (`grep` for any new
  consent-related strings, `SubmissionRole` iteration, or child-row
  expansion code — none should exist yet).

## Out of scope for this phase

- AVD/exemplar consent badges, staff-roles block, details child-row,
  feedback document links — Phases 3, 4, and 5 respectively per
  `recon.md`'s phase breakdown.
