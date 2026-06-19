# Phase 2b — AVD dashboard: surface submission period, secondary sort

Shared context: `.prompts/avd-dashboard/recon.md` §12 (base query is now
rooted on `SubmissionRecord`, one row per record — this is *why* a
student can now appear more than once, once per submission period, which
is what prompted this phase) and
`.prompts/avd-dashboard/phase2-recon-output.md` for current file/function
names: `app/dashboards/views.py::avd_dashboard_ajax()`,
`app/ajax/archive/reports.py::avd_dashboard_rows()`,
`app/templates/dashboards/avd_dashboard.html`.

Small, scoped addition — not part of Phase 3 (consent), which stays
focused on consent badges only. Two things only:

1. Each row shows which submission period it belongs to.
2. The ajax endpoint applies submission period as a secondary sort key,
   so rows from the same period are grouped together regardless of
   whatever primary sort (report grade, student name, etc.) is active.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase2b-recon-output.md`, present before coding)

1. Confirm the relationship path from `SubmissionRecord` to
   `SubmissionPeriodRecord` used in the current `avd_dashboard_ajax()`
   query (it must already join through this somewhere, since eligibility
   was switched to `SubmissionPeriodRecord.closed` in Phase 2 — find and
   quote the existing join).
2. Confirm `SubmissionPeriodRecord.display_name` (property, per
   `app/models/project_class.py` — already known to produce e.g.
   "Submission Period #1") is the right thing to show, or whether
   something shorter/more row-appropriate already exists elsewhere in the
   codebase for this purpose (e.g. check how the legacy `reports.html`
   row rendered "Submission Period #1" — visible in screenshot 1 of the
   original review thread — and reuse that exact wording/format rather
   than inventing new copy).
3. Confirm `SubmissionPeriodRecord.submission_period` (an `Integer`) is
   the right column to sort on for "grouping by period" — check whether
   it's per-`ProjectClassConfig`-relative (i.e. period 1, 2, 3... within
   each year) or globally meaningful across years, since the dashboard
   spans years (per the year filter from Phase 1). If it's only
   meaningful within a year, the secondary sort likely needs to be
   `(year, submission_period)` or similar, not `submission_period` alone
   — confirm and state the reasoning before implementing.
4. Confirm how `ServerSideSQLHandler` currently applies sort (per
   `recon.md` §5/§10, the existing pattern is `columns` dict with `order`
   clauses) and how to append a secondary/tiebreak `order_by` clause after
   whatever column the user has actively sorted by — this should not
   replace the user's chosen sort, just break ties within it.

## Step 1 — Surface submission period on the row

- Add the period's display name (per Step 0.2) to the existing identity
  line in the row panel (alongside programme/year, established in
  Phase 1/2), not a new column — this is descriptive context, not a
  sortable/filterable dimension in its own right (no new filter button
  requested here).

## Step 2 — Secondary sort

- In `avd_dashboard_ajax()`, after applying whatever primary `order_by`
  the request specifies (report grade default from Phase 2, or whatever
  column the user clicked), append the period-grouping key from Step 0.3
  as a secondary `order_by` clause, so ties in the primary sort group by
  period rather than coming back in arbitrary/DB-default order.
- This should compose correctly with every existing filter from Phases
  1–2 (tenant, pclass, year, group, has-grade) — it's purely an `order_by`
  addition, not a new filter.

## Step 3 — Verification

- Manually confirm (describe what you checked):
  - each row visibly shows its submission period
  - sorting by report grade (both directions) still works, and rows that
    tie on grade are grouped by period rather than interleaved
  - the default sort (grade descending, from Phase 2) still has period as
    the correct tiebreak
  - existing filters (tenant/pclass/year/group/has-grade) still narrow
    results correctly with the new secondary sort in place
- Confirm no Phase 3+ functionality (consent badges, staff roles, details
  child-row) was touched.

## Out of scope

- Colour-coding by project class (e.g. a sidebar accent) — explicitly
  deferred until the dashboard's overall output is evaluated, not part of
  this phase or Phase 3.
- Consent badges, staff-roles block, details child-row, feedback document
  links — Phases 3–5.
