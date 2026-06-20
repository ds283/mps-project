# Phase 5 — AVD dashboard: details child-row, language analysis, full risk breakdown, feedback documents

Shared context: `.prompts/avd-dashboard/recon.md` §8 (language analysis
fields), §6 (risk_factors_ui_summary()), §7 (feedback documents), §11
(embargo — `is_report_restricted`, must gate this phase's content), §10
(details child-row design). Also read whatever Phase 4b actually wrote to
the repo's `recon.md` §15 and `.prompts/avd-dashboard/phase4b-recon-
output.md` for current file/function names — confirm these before
relying on names below, since this prompt is written from the Phase 4b
summary reported in conversation, not a direct read of the post-4b repo
state: `app/ajax/archive/reports.py` (now has `_report` template,
`identity_line()`, `flags_line()` macros), `app/dashboards/
views.py::avd_dashboard_ajax()`, `app/templates/dashboards/
avd_dashboard.html`.

This is the last content phase. Scope: row-click-to-expand child row
containing word/page/table/figure counts, stated vs. measured word count,
AI declaration text, `report_summary` (LLM summary), full
`risk_factors_ui_summary()` breakdown (every present factor, resolver
name, annotation), links to each role's `MarkingReport`/`ModeratorReport`,
and the feedback document link (`SubmissionRecord.feedback_reports`) —
all gated by `is_report_restricted` per §11 where indicated.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase5-recon-output.md`, present before coding)

1. Confirm current exact names/locations of everything Phase 4b left
   behind (per the warning above — don't trust the names in this prompt's
   header without checking).
2. Confirm `SubmissionRecord.language_analysis_data` (the deserialising
   property over the JSON blob, per `recon.md` §8) and the exact key
   paths: `metrics.word_count`, `metrics.appendix_word_count`,
   `_page_count`, `metrics.figure_count`, `metrics.table_count`,
   `stated_word_count_found`/`stated_word_count`,
   `genai_statement_found`/`genai_statement`, `report_summary`. Quote
   verbatim from current source — these were recorded in the original
   recon pass and may have shifted.
3. Confirm `risk_factors_ui_summary()`'s exact return shape (per `recon.md`
   §8: per-factor `present`/`resolved`/`resolved_by_name`/`resolved_at`/
   `annotation`) and the `RISK_AI_COMPLIANCE`/`RISK_AI_USE`/
   `RISK_TURNITIN` keys out of `ALL_RISK_TYPES`. Quote verbatim.
4. Confirm how `report_event`/`presentation_event`/`supervision_event`
   relationships (per `recon.md` §5) resolve to a `MarkingEvent`, and how
   to reach each role's individual `MarkingReport` from there — check
   whether `MarkingReport` has a direct, queryable link back to a
   specific `SubmissionRole` (per `recon.md` §6's mention of
   `MarkingReport.role`) so the details panel can link "Dr X's marking
   report" rather than just "the marking event."
5. Confirm `ModeratorReport` access similarly (per
   `SubmitterReport.accepted_moderator_report` /
   `_latest_submitter_report()` from Phase 4).
6. Confirm `SubmissionRecord.feedback_reports` relationship (per
   `recon.md` §7) and what a `FeedbackReport` exposes for a download
   link (filename, asset/file path, content-type).
7. Find the existing DataTables child-row expansion pattern, if one
   exists anywhere else in the app already (the brief in `recon.md` §10
   calls for "row-click or inline-link expansion") — reuse the
   established pattern rather than introducing a new one if precedent
   exists; if none exists, propose the implementation approach
   (server-rendered HTML returned via a small endpoint vs. client-side
   toggle of pre-rendered hidden content) and state the tradeoff
   considered, since this is a real architectural choice for this phase.
8. Confirm `is_report_restricted`'s exact current definition (per
   `recon.md` §11, confirmed in Phase 2 as presence-only:
   `report_embargo is not None`).

## Step 1 — Expand trigger

- Wire up the "Show full marking & report details" inline link (and/or
  row click, per the established pattern from Step 0.7) to expand a
  DataTables child row beneath the clicked row. Collapse on second
  click/re-click. Only one row expanded at a time is fine but not
  required — state which you implemented and why if it's a meaningful
  complexity tradeoff.

## Step 2 — Details content

Within the child row, render (each item only if data is present — same
"absence is the signal" convention as the rest of the dashboard, no
placeholder "N/A" rows for every field that happens to be empty):

- Word/page/table/figure counts: measured word count, stated/declared
  word count (with a visible flag if they differ significantly — check
  whether `stated_word_count_found` already implies a mismatch state, or
  whether this phase needs to compute "significant difference" itself;
  if the latter, don't invent a threshold — ask in your recon output
  rather than picking one silently, since this affects what counts as
  worth flagging)
- AI declaration: whether one was found, and its text if present
- LLM report summary (`report_summary`) — render as plain prose, not
  inside a code block or anything implying it's raw data
- Full risk-factor breakdown: every factor from
  `risk_factors_ui_summary()` that is `present`, showing resolved state,
  resolver name, resolved date, and annotation text if any (this is
  where the Phase 3-era "note icon" on the flags line in the main row
  should link to/expand)
- Staff role report links: for each role already listed in the main row's
  staff-roles block (Phase 4), link through to that role's
  `MarkingReport` where one exists; link the moderator's `ModeratorReport`
  similarly
- Feedback document link(s) via `SubmissionRecord.feedback_reports`

## Step 3 — Embargo gating

- If `is_report_restricted` is true for this record: suppress the
  feedback document link and the AI-declaration/LLM-summary content
  specifically (per `recon.md` §11's forward-dependency note) — these are
  closer to "the report's actual content/derived content" than the
  metadata (word counts, risk-factor presence) which can probably still
  show. State your reasoning on exactly where you drew this line, since
  `recon.md` flagged this as "arguably should suppress" rather than a
  hard requirement — if you judge differently after reviewing the actual
  embargo use case, say so explicitly rather than silently picking.

## Step 4 — Verification

- Manually confirm (describe what you checked):
  - expand/collapse works correctly and doesn't break DataTables sorting/
    pagination/search underneath
  - a record with no AI risk factors present shows a clean details panel
    (no empty risk section)
  - a record with a resolved AI risk factor and an annotation shows the
    annotation text
  - a restricted (`is_report_restricted`) record's details panel
    correctly omits whatever Step 3 decided to gate
  - staff-role report links resolve to the correct individual
    `MarkingReport` (not just any report on the event)
  - feedback document link downloads/opens correctly for a non-restricted
    record
- Confirm no regression to columns/sort/filters from Phases 1–4b.

## Out of scope

- This is the last planned content phase per `recon.md`'s phase
  breakdown. Project-class colour-coding (sidebar accent) remains
  explicitly deferred per §13, for evaluation once this phase lands.
