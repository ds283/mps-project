# Phase 4b — AVD dashboard: consolidate into the agreed two-column panel layout

Shared context: `.prompts/avd-dashboard/recon.md` §10 (the row/column
design this phase implements — read it in full, it's the spec for this
phase) and the four mockups iterated earlier in the design conversation
(referenced in §10's "explicitly rejected" list — useful for what *not*
to reproduce). Also read `.prompts/avd-dashboard/phase4-recon-output.md`
for current state: `app/dashboards/views.py::avd_dashboard_ajax()`,
`app/ajax/archive/reports.py` (now containing `staff_roles()`,
`report_flags()`, `_latest_submitter_report()`,
`_moderation_outcome_text()` per Phase 4), `app/templates/dashboards/
avd_dashboard.html`.

This is a **layout consolidation phase, not a new-content phase**. Every
piece of content already exists (student/title from Phase 1, grades from
Phase 2, period from Phase 2b, consent badges from Phase 3, staff roles +
flags from Phase 4) — this phase reorganises it into the two-column
structure §10 specifies and removes the columns §10 explicitly rejected.
No new data, no new queries beyond what sorting/column changes require.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase4b-recon-output.md`, present before coding)

1. Copy verbatim the current `columns` dict in `avd_dashboard_ajax()` and
   the current DataTables column definitions in `avd_dashboard.html`
   (currently: Student / Year and project class / Report grade /
   Submissions, per the screenshot reviewed in this conversation).
2. Copy verbatim the current row-rendering template/macros in
   `app/ajax/archive/reports.py` for each of: the student/title cell, the
   "Year and project class" cell, the consent badges block (Phase 3), the
   `staff_roles()`/`report_flags()` macros (Phase 4), and the Turnitin/
   grade content currently in the "Submissions" cell.
3. Confirm exactly how the existing `data: 'name', render: {_: 'display',
   sort: 'sortstring'}` pattern (used for the current Student column) is
   implemented server-side, since this phase needs to extend it to also
   carry programme/research group/year/period/supervisor names into the
   *search* index of the single consolidated panel column (per `recon.md`
   §10's note that free-text search should cover all of this without
   dedicated columns) — confirm the search-string-building code, don't
   assume it already includes everything needed.
4. Confirm current responsive/wrapping behaviour issues visible in the
   screenshot (e.g. the project-class badge + "Submission Period #1"
   wrapping awkwardly in a narrow column) — these should resolve
   naturally once the panel has the full row width to work with, but
   note if anything needs explicit CSS attention.

## Step 1 — Collapse to two columns

- **Column 1 — "Report"**: single panel cell containing, top to bottom
  (per §10 and the final mockup from this conversation):
  - thumbnail (left-aligned, already wired in Phase 2 — keep as-is,
    known to not render in dev per earlier note, not a regression to
    chase)
  - student name + project title on one line
  - compact identity line: programme · research group · year ·
    submission period (Phase 2b's addition) · supervision grade ·
    presentation grade — all as plain text, **not** separate columns
  - consent badges block (Phase 3 — unchanged, just relocated into this
    panel if it isn't already inline with the rest)
  - flags line: `convenor_intervention`, Turnitin score/band, AI risk
    (still pending — Phase 5, leave a gap/placeholder if Phase 5 hasn't
    landed yet, don't fabricate AI-risk content in this phase), feedback
    doc link (also Phase 5 — same note)
  - staff-roles block (Phase 4 — unchanged content, just confirm it sits
    inside this same panel, not a separate area)
- **Column 2 — "Report grade"**: unchanged from Phase 2 — single
  sortable numeric column, right-aligned, default sort.
- **Remove** the "Year and project class" column entirely — its content
  moves into the panel's identity line per Step 1's Column 1, not
  deleted from the row, just no longer a separate `<td>`/DataTables
  column. Don't drop the project-class colour badge if one already
  exists — keep it inline in the identity line.
- **Remove** the separate "Submissions" column — its remaining content
  (Original/Processed download buttons, Turnitin block) folds into
  Column 1's flags/footer area.

## Step 2 — Search index

- Extend whatever `sortstring`/search-field construction Step 0.3
  identified so the single Column 1's search also matches: programme
  name, research group name, project class name, supervisor/marker/
  moderator names (the last three should already be covered if Phase 4's
  search wiring — `roles.any(user.has(...))` — was implemented as a
  *filter* rather than folded into the *search index*; confirm which it
  is and reconcile, since `recon.md` §10 asked for this to work via the
  DataTables search box specifically, not a separate query parameter).

## Step 3 — Verification

- Manually confirm (describe what you checked):
  - the table now has exactly two columns, Report and Report grade
  - every piece of content present before this phase (student, title,
    programme, group, year, period, both consent badges, both secondary
    grades, staff roles, intervention flag, Turnitin) is still visible
    somewhere in the Report panel — nothing silently dropped
  - sorting by Report grade still works correctly, including the Phase 2b
    period tiebreak
  - free-text search now matches on programme/group/supervisor/marker
    names typed into the DataTables search box (not just student name)
  - the layout doesn't visually break at typical viewport widths — no
    awkward column-too-narrow wrapping of the kind visible in the
    screenshot reviewed in this conversation
  - all existing filters (tenant/pclass/year/group/has-grade/AVD-consent/
    exemplar-consent) still narrow results correctly post-consolidation
- `grep` to confirm no leftover references to the removed "Year and
  project class" or "Submissions" column definitions.

## Out of scope for this phase

- Any new content (AI risk display, feedback document links, details
  child-row) — Phase 5. This phase only reorganises what already exists.
