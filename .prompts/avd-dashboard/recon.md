# Reconnaissance: Archive reports → AVD Dashboard

Status: read-only investigation, no code changes yet. Confirms the exact
model fields, properties, and access-control patterns to use in the
implementation phases.

## 1. Current state (`app/archive/views.py`, `archive/reports.html`)

- Route: `GET /archive/reports`, ajax at `POST /archive/reports_ajax`.
- Access: `@roles_accepted("root", "admin", "archive_reports")`.
  **Important**: no `faculty`/convenor clause anywhere — this is correct
  per the brief ("they may not be convenors") and must be preserved as-is
  in the new dashboard, *not* widened to match `_can_access_marking_dashboard()`
  (which adds a convenor branch).
- Tenant handling: `allowed_tenant_ids = [t.id for t in current_user.tenants]`
  is computed and used to scope pclass/group/year option lists and the
  base query for non-root users — but there is **no tenant selector** in
  the UI and no per-request `tenant_id` param. A user with multiple tenant
  memberships sees every tenant unioned together, and pclass/year/group
  filter option-lists are similarly unioned. This is the gap to close, not
  a missing filter from scratch.
- `reports_ajax` columns dict only defines `name` and `year` — `records`
  (the freeform per-submission HTML blob, built server-side, presumably in
  `app/ajax/archive.py::retired_reports`, not in our file set) is
  `orderable: false`. Grade is not a column at all today; it's baked into
  that HTML blob alongside Turnitin data.

## 2. Tenant-scoping pattern to reuse (`app/dashboards/views.py`)

Canonical helpers, already private (`_`-prefixed) module functions:

```python
_get_accessible_tenants() -> List[Tenant]
    # root: all tenants. else: current_user.tenants.order_by(Tenant.name).all()

_get_default_tenant_id(accessible_tenants) -> int
    # current_user.tenants.order_by(Tenant.name).first(), else accessible_tenants[0]
```

Route-level pattern (seen identically in `ai_dashboard()`, reused by
`similarity_dashboard()` / `marking_dashboard()`):

```python
accessible_tenants = _get_accessible_tenants()
default_tenant_id = _get_default_tenant_id(accessible_tenants)
if len(accessible_tenants) == 1:
    selected_tenant_id = accessible_tenants[0].id
else:
    selected_tenant_id = int(request.args.get("tenant_id", default_tenant_id))
# clamp to accessible set, then resolve selected_tenant
```

`_get_accessible_pclasses(tenant_id)` shows the per-dashboard
"who can see this pclass" branching style — root/admin/`data_dashboard_AI`
get everything in-tenant; convenors get only their `convenor_list`. Our
equivalent (`_get_accessible_pclasses_for_avd`) is simpler: root/admin/
`archive_reports` get everything in-tenant; **no convenor branch**.

Decision needed before Phase 1: keep the existing `archive_reports` role
name (recommended — avoids a migration / re-grant exercise) rather than
introducing `data_dashboard_archive` to match the `data_dashboard_*`
naming convention used elsewhere. Functionally equivalent either way.

## 3. Dashboard shell pattern (`overview()`, `dashboards/overview.html`)

`overview()` gates on an OR of all dashboard roles and renders one summary
dict per dashboard card (`summary`, `marking_summary`, `similarity_summary`).
Each card on `dashboards.html` (screenshot 3) shows a small set of stat
chips ("4 tenants", "167 open concerns") plus an "Open dashboard" button.
Adding a fourth card means:
- a `_avd_dashboard_summary_for_user()` helper (counts: tenants, eligible
  reports, AVD-consented count — cheap aggregate queries, same shape as
  `_dashboard_summary_for_user()` / `_marking_summary_for_user()`)
- one new card block in `dashboards/overview.html`
- gate `overview()`'s access check to also accept `archive_reports`, or it
  won't render this card for archive-only users (currently `archive_reports`
  isn't in that OR list — they'd never reach the landing page).

Naming: recommend **"AVD Dashboard"** (or "Exemplar / AVD Dashboard") as
the card title, distinct from the "Assessment archive" tab already present
under Convenor (screenshot 2) and from "Archive" elsewhere in the nav,
which refers to that separate concept.

## 4. Consent fields (`app/models/submissions.py`, `SubmissionRecord`)

Two **parallel, independently-tracked** consent flags exist — easy to
conflate, must not be:

- `exemplar_consent_*` — has a supervisor-approval gate
  (`exemplar_supervisor_approved`); property `exemplar_fully_approved`.
- `openday_consent_*` — **no approval step**; property `openday_consent_active`.

**Confirmed with David: badge both consent types, separately**, since this
dashboard is also used to browse the back-catalogue for purposes other
than AVDs:

- **AVD / open day** — `openday_consent_active`. Single flag, no approval
  step.
- **Exemplar** — student and supervisor consent shown as two *separate*
  indicators rather than collapsed into `exemplar_fully_approved`:
  - student side: `exemplar_consent_active`
  - supervisor side: `exemplar_supervisor_approved` (tri-state: `None` =
    not yet actioned, `True` = approved, `False` = declined)

```python
@property
def openday_consent_active(self) -> bool:
    return self.openday_consent_granted_at is not None and not self.openday_consent_withdrawn

@property
def exemplar_consent_active(self) -> bool:
    return self.exemplar_consent_granted_at is not None and not self.exemplar_consent_withdrawn
```

So each row needs two small badge clusters: "AVD: [active/withdrawn/
invited/not asked]" and "Exemplar: student [active/withdrawn/not asked] ·
supervisor [approved/declined/pending]". Badge states for both consent
types follow the same shape: never asked (`*_granted_at is None`, no
invitation sent) / invited, awaiting response / active / withdrawn.
`consent_invitation_sent_at` / `consent_reminder_sent_at` are shared
fields covering invitation tracking for both types (not split per type —
worth checking at implementation time whether one invitation covers both
consent questions or there are two separate invitation flows; the model
only has one pair of `consent_invitation_sent_at`/`consent_reminder_sent_at`
columns, so it looks like a single combined invitation).

## 5. Grades + provenance (`SubmissionRecord`)

All three grades already exist as plain numeric columns with provenance:

```python
supervision_grade, report_grade, presentation_grade   # Numeric(8,3)
supervision_event_id / report_event_id / presentation_event_id  # -> MarkingEvent
supervision_generated_by / report_generated_by / presentation_generated_by  # -> User
```

This directly answers point 6 (presentation grade absent today) and gives
a free hook into point 7 (marking history) — `report_event` /
`presentation_event` relationships resolve straight to the `MarkingEvent`
that produced the grade, which is the same object the Marking Dashboard
already renders health/risk data for (screenshot 4: distribution,
submitted, feedback, grade SD/CV). A "view marking event" link from each
AVD row is cheap to add once the FK is exposed.

For sortable/filterable grade columns in `ServerSideSQLHandler`: add
`report_grade`, `presentation_grade`, `supervision_grade` to the `columns`
dict in `reports_ajax` (currently only `name`/`year` are defined — `order`
needs to point at the actual column, `search` can be omitted or coerced
to text). "Has grade" filter is `SubmissionRecord.report_grade.isnot(None)`
/ `.is_(None)`.

## 6. Marking history / intervention flag (`app/models/markingevent.py`)

`SubmitterReport` (FK `record_id` → `SubmissionRecord`, backref
`SubmissionRecord.submitter_reports`, dynamic) carries three distinct
signals that must **not** be conflated:

```python
out_of_tolerance: bool
    # Set by _check_tolerance_and_grade() when MarkingReport grades disagree
    # beyond tolerance and moderation is specifically required. Cleared if a
    # convenor resets the workflow state. This is the narrow "out-of-tolerance"
    # trigger only.

convenor_intervention: bool
    # STICKY audit flag. Set True the first time this SubmitterReport ever
    # entered the REQUIRES_CONVENOR_INTERVENTION workflow state, for ANY
    # reason (out-of-tolerance grading is one path in, but per David this can
    # also be triggered by risk flags etc.) — never cleared thereafter. This
    # is the correct field for "did this report ever need intervention", and
    # it is broader than moderation specifically.

accepted_moderator_report_id / accepted_moderator_report / moderator_accepted_by
    # Non-null only if a ModeratorReport was actually produced AND accepted
    # (implicitly on first submission, or explicitly by a convenor).
```

For "was this report ever moderated at all" (regardless of acceptance),
`SubmitterReport.moderator_reports` is an existing dynamic backref from
`ModeratorReport.submitter_report` — `submitter_report.moderator_reports.count() > 0`
answers that directly; no new helper property needed. Recommend adding one
small convenience property for readability, e.g.:

```python
@property
def was_moderated(self) -> bool:
    """True if at least one ModeratorReport was ever produced for this report,
    whether or not it was the one ultimately accepted."""
    return self.moderator_reports.first() is not None
```

So the AVD "marking history" indicator for a row should surface all three
independently: **convenor intervention** (sticky, broad — any reason),
**out of tolerance** (the specific moderation-tolerance trigger), and
**moderated** (a `ModeratorReport` exists, with a link to whichever one was
accepted if any). A report can have `convenor_intervention = True` with no
`ModeratorReport` at all (e.g. triggered by a risk flag, not grading
disagreement), so these three states are genuinely independent and the UI
should not collapse them into a single "had an intervention" badge.

Caveat carried over from the original recon: `SubmitterReport` is scoped
per `(record, workflow)`, i.e. per marking event — a student can have more
than one `SubmitterReport` across re-marking events/periods. Use the
`submitter_reports` dynamic backref and decide whether to show the latest,
or all, when more than one exists.

`ConflationReport` (FK `submission_record_id` → `SubmissionRecord`) is the
feedback-document anchor (point 8 below) and also exists per marking
event/conflation run.

## 7. Feedback documents (point 8 of the brief)

Simpler than expected: `SubmissionRecord.feedback_reports` is **already a
direct relationship** (via the `submission_record_to_feedback_report`
secondary table) — no need to traverse `ConflationReport` to reach the
PDFs for display purposes. `ConflationReport` is still the right place to
look if we also want the *conflation/marking* report (not just the
generated feedback PDF) or per-event provenance, but the document link
itself can come straight off the `SubmissionRecord` we're already querying.

## 8. Basic report stats / AI declaration / LLM summary (`language_analysis.py`)

Everything lives in `SubmissionRecord.language_analysis` (JSON blob via
`language_analysis_data` property — already deserialises safely). Confirmed
keys produced by the pipeline:

- `metrics.word_count`, `metrics.appendix_word_count`
- `_page_count` (top-level, set during text extraction)
- `metrics.figure_count`, `metrics.table_count`
- `stated_word_count_found` / `stated_word_count` (student's declared word
  count vs. measured — this is the "number of words, measured and
  reported" pair from the brief)
- `genai_statement_found` / `genai_statement` (AI declaration text)
- `report_summary` (1–2 paragraph LLM-generated content summary — exactly
  the "LLM summary" requested)

Risk flags (AI risk + Turnitin risk, with resolver/annotation) come from a
**separate**, already-fully-built mechanism: `risk_factors_ui_summary()`
on `SubmissionRecord`, returning per-factor dicts with `present`,
`resolved`, `resolved_by_name`, `resolved_at`, `annotation` — this can be
reused as-is rather than re-deriving anything. Relevant keys:
`RISK_AI_COMPLIANCE` / `RISK_AI_USE` (AI risk) and `RISK_TURNITIN`
(Turnitin risk) out of `ALL_RISK_TYPES`.

Recommend exposing all of this via a row-expand / "Details" modal rather
than flattening into table columns (confirmed in the original review —
too many fields for one row), populated either inline in the ajax payload
per row or lazily via a small `GET /dashboards/avd/record/<id>` endpoint
that calls `risk_factors_ui_summary()` + reads the JSON blob.

## 9. Thumbnails

Reuse the same `serve_thumbnail` view / Minio-backed mechanism already
used elsewhere (and already the subject of separate timeout/placeholder
hardening work) — same component, just a new call site in the AVD
dashboard's report cards/rows.

## Decisions (resolved)

1. Both consent types badged separately — see §4.
2. **Role renamed**: `archive_reports` → `data_dashboard_reports`, matching
   the `data_dashboard_AI` / `data_dashboard_marking` / `data_dashboard_similarity`
   convention. This is a real rename, not just an alias — needs a migration
   (or manual role-grant update) to move existing holders of `archive_reports`
   onto the new role name, and every `@roles_accepted(...)` /
   `current_user.has_role(...)` reference updated. Worth a `grep -rn
   "archive_reports"` across the codebase as the first step of Phase 1 to
   scope this fully (templates, forms, seed/fixture data, and any
   role-management UI may all reference the string).
3. **`overview()` access gate**: add `data_dashboard_reports` to the OR
   condition so these users reach the dashboards landing page. Per David:
   they should only see the cards/dashboards they're actually entitled to
   — i.e. the AVD card should be gated independently within
   `dashboards/overview.html` (same pattern already used for the AI/
   Marking/Similarity cards, which are presumably each conditionally
   rendered based on the relevant `_can_access_*_dashboard()` check — needs
   confirming against the template, not yet viewed in this recon pass).
   `data_dashboard_reports`-only users should not see the AI/Marking/
   Similarity cards unless they separately hold those roles.
4. `convenor_intervention` / `out_of_tolerance` / `moderator_reports` are
   three independent signals — see §6.

## 10. Row/column design (resolved via mockup iteration)

Settled on two real `ServerSideSQLHandler` columns, not the twelve
originally sketched:

1. **Report** — a single rich, non-sortable-by-click panel cell, but
   searchable/sortable under the hood the same way the existing "Student"
   column works today (`data: 'name', render: {_: 'display', sort:
   'sortstring'}` — sort key travels with the row independent of the
   rendered HTML). Contains, top to bottom:
   - thumbnail
   - student name + project title
   - compact identity line: programme · research group · year ·
     supervision grade · presentation grade (text, not separate columns —
     see point 2 below)
   - consent badges: AVD (`openday_consent_active`, visually dominant —
     small solid teal pill) and exemplar (`exemplar_consent_active` +
     `exemplar_supervisor_approved`, muted text, shown only when not in
     the "never asked" default-silent state — see point 3)
   - flags only when present (nothing rendered when absent — no "not
     flagged"/"not moderated"/"no intervention" placeholder badges):
     `convenor_intervention`, Turnitin score/band, AI risk
     (`risk_factors_ui_summary()`, wording "AI flagged" / "AI flagged ·
     resolved", with a small note icon appended only when an annotation
     exists — clicking it opens the same details panel as everything
     else, not a separate popover), feedback document link
     (`SubmissionRecord.feedback_reports`)
   - staff-roles block: **generic** iteration over the record's
     `SubmissionRole`s (not hard-coded to supervisor/marker/moderator —
     label by `role.role` so any future role type appears automatically
     without a template change), each row showing the role holder's name;
     the moderator's role line specifically carries the outcome inline
     ("grade accepted" / "out of tolerance, no moderator assigned yet")
     rather than a separate badge — this is the resolution for surfacing
     `out_of_tolerance` / `was_moderated` / `accepted_moderator_report`
     from §6, tied to the role rather than floating freestanding
   - "Show full marking & report details" inline link — row-click or this
     link expands a DataTables child row (not a separate "Details" column)
     containing: word/page/table/figure counts, stated vs measured word
     count, AI declaration text, `report_summary`, full
     `risk_factors_ui_summary()` breakdown with resolver name + annotation
     for every present factor, and links through to each role's
     `MarkingReport`/`ModeratorReport`.

2. **Report grade** — the single sortable numeric column, right-aligned,
   default sort. Supervision and presentation grades are *not* separate
   columns; they're compact text inside the Report panel. Rationale:
   report grade is the one explicitly identified as primary for AVD
   selection; making the other two full columns for parity would
   reintroduce the column-bloat problem without a corresponding use case.
   If sorting by supervision/presentation grade independently becomes a
   real need later, that's a column-set toggle to revisit, not a default.

Explicitly rejected along the way, with reasoning, in case it resurfaces:
- Twelve flat columns (student/title/programme/group/supervisor/year/three
  grades/status/details) — too much for a row to carry, and several
  (programme/group/year) duplicate the existing filter-button row with no
  added sort value over what filtering already provides.
- A dedicated "Supervisor" column — `SubmissionRole` allows more than one
  supervisor per record, so a single sortable column doesn't fit; resolved
  instead by listing all roles generically in the panel and relying on
  free-text search across role-holder names for "find everything under
  supervisor X". A true group-by-supervisor view, if wanted later, is a
  different UI shape (pivot/grouping) and out of scope here.
- A dedicated "Details" column containing only a disclosure toggle —
  replaced by row-click-to-expand-child-row plus an inline text link,
  consistent with not spending a whole column on pure chrome.
- Always-visible "not flagged" / "no intervention" / "not moderated"
  badges — pure noise on the common case; absence of a badge is the
  signal.

Filter-button row above the table is **unchanged in shape**, just
extended: tenant selector (new, per §2), existing pclass/year/group
buttons, plus new AVD-consent and exemplar-consent filter buttons. Slicing
by research group, project class, year, or consent state stays
filter-button territory; it does not need to also exist as a sortable
table column.

## 11. Embargo / report restriction (`report_embargo` on `SubmissionRecord`)

**Resolved in Phase 2.** `is_report_restricted` is now a real property on
`SubmissionRecord` (`app/models/submissions.py`):
`report_embargo is not None`. **Presence-only, not a date comparison** —
despite the column name suggesting "embargoed until this date," it's
confirmed to behave as a flat boolean flag in the current codebase. Any
future phase needing this check uses the property, not a re-derived
inline comparison.

Suppression call sites confirmed/implemented in Phase 2: thumbnail
(replaced with a restriction indicator in the same visual slot). Still
pending, per the original forward-dependency note: feedback document link
(Phase 5) and AI-declaration/LLM-summary details-panel content (Phase 5)
should both gate on `is_report_restricted` too.

## 12. Base query restructure (Phase 2)

Phase 2 rewrote `avd_dashboard_ajax()`'s base query to be rooted on
`SubmissionRecord` directly — one row per record, not one row per student
with submissions nested underneath (the shape the legacy `reports.html`
used, visible in screenshot 1 of this thread: one card per student,
multiple submissions listed inside). This is the right structural choice
given grades, embargo, and (in later phases) consent and risk all live on
`SubmissionRecord`, but it's a bigger change than "add a column," so two
things worth confirming rather than assuming correct:

- **Eligibility criteria changed**: from `SubmittingStudent.retired` to
  `SubmissionPeriodRecord.closed`. This is a real semantic change, not a
  refactor-only side effect — it changes which reports are eligible to
  appear, not just how they're grouped. Worth confirming the total
  eligible-report count still matches expectations against the legacy
  view's "725 entries" baseline (screenshot 1, original review) before
  later phases build on this query. **Confirmed**: dashboard now reports
  803 eligible reports, and this is expected, not a bug — per-record
  (rather than per-student) rows mean a student with more than one
  submission period now contributes more than one row, which the legacy
  per-student-with-nested-submissions view collapsed into one card. This
  is also what prompted Phase 2b (below): each row needs to visibly show
  which submission period it belongs to, and a secondary sort by period
  is needed so same-period rows group together regardless of primary
  sort.
- The legacy per-student-with-nested-submissions shape is gone; if
  anything elsewhere still depends on that grouping (unlikely, given
  `app/archive/` was deleted in Phase 1, but worth a mental note), it
  would need separate handling.

`app/ajax/archive/reports.py::retired_reports()` was renamed to
`avd_dashboard_rows()` and restructured to one card per report (not per
student) as part of this same change.

## 13. Submission period grouping (Phase 2b) and deferred colour-coding

Phase 2b adds the submission period (`SubmissionPeriodRecord.display_name`)
to each row's identity line and a secondary sort key so same-period rows
group together under whatever primary sort is active — small addition,
not folded into Phase 3 since it's unrelated to consent. See the
Phase 2b prompt for details, including the open question of whether
`submission_period` (an `Integer`) is meaningful to sort on globally or
only within a year — needs confirming against the model before
implementation.

**Deferred, explicitly out of scope for now**: colour-coding rows by
project class (e.g. a coloured sidebar accent, matching the existing
dashboard convention of colour-as-navigational-cue — blue/green/orange/
teal already assigned per-dashboard, but pclass colour-coding *within* a
dashboard's rows would be a different, additional colour dimension).
David wants to evaluate the dashboard's output as it stands once Phases
3–5 land before deciding on this, rather than designing it now.

## Suggested phase breakdown for implementation prompts

1. **Move + tenant-scope + role rename**: relocate `reports()`/
   `reports_ajax()` into `app/dashboards/views.py` (or a sibling module
   imported by it) as `avd_dashboard()`/`avd_dashboard_ajax()`; add tenant
   selector using `_get_accessible_tenants`/`_get_default_tenant_id`; add
   the `_can_access_avd_dashboard()` gate (root/admin/
   `data_dashboard_reports` only — no convenor clause); rename
   `archive_reports` → `data_dashboard_reports` everywhere (`grep -rn
   "archive_reports"` first to scope templates/forms/fixtures/role-admin
   UI, plus a migration or manual role-grant update for existing holders);
   add `data_dashboard_reports` to the `overview()` access OR-condition,
   gating the new card independently in `dashboards/overview.html` so
   report-only users see just that card; retire the old `Archive` nav
   dropdown entry. Verify with `grep` for any remaining
   `url_for('archive.reports...')` references before deleting the old
   route.
2. **Report grade column + thumbnails**: add `report_grade` as the one
   real sortable/searchable `ServerSideSQLHandler` column, default sort
   desc; add "has grade" / grade-band filter buttons; wire in the existing
   `serve_thumbnail` mechanism. Supervision/presentation grades render as
   plain text inside the Report panel in this same phase since they share
   the row template — no separate columns.
3. **Report panel — identity, consent, flags**: build the rich Report
   column per §10 — thumbnail, student/title, identity line, AVD +
   exemplar consent badges (`openday_consent_active`,
   `exemplar_consent_active`, `exemplar_supervisor_approved`, each only
   rendered when not in the silent "never asked" state), filter buttons
   for AVD/exemplar consent alongside existing pclass/year/group buttons,
   `convenor_intervention` flag, Turnitin score/band, AI risk via
   `risk_factors_ui_summary()` (note icon only when an annotation is
   present), feedback document link via `SubmissionRecord.feedback_reports`.
4. **Staff-roles block**: generic iteration over each `SubmissionRecord`'s
   `SubmissionRole`s (label by `role.role`, not hard-coded role types);
   moderator role line carries outcome inline using `out_of_tolerance` /
   `moderator_reports` backref (new `was_moderated` convenience property)
   / `accepted_moderator_report`; ensure role-holder names are included in
   the server-side search index so free-text search covers "find reports
   supervised by X" without a dedicated column or filter.
5. **Details child-row**: row-click / inline-link expansion (not a
   dedicated column) surfacing word/page/table/figure counts, stated vs
   measured word count, AI declaration text, `report_summary`, full
   `risk_factors_ui_summary()` breakdown with resolver name + annotation
   for every present factor, and links through to each role's
   `MarkingReport`/`ModeratorReport` — reusing existing model methods
   throughout, no new computation logic.

Each phase as a standalone Claude Code prompt with an explicit
reconnaissance-plan-then-verify-by-grep structure, per your usual pattern.
