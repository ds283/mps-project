# Phase 3 — Overview tab redesign (60/40 split)

**Prerequisite: Phases 1 and 2 are complete and verified.**

---

## Objective

Replace the current layout of `convenor/dashboard/status.html` with a two-column 60/40 split. The left column (60%)
carries submission management; the right column (40%) carries selection management. The actions panel from Phase 2 sits
above both columns.

This phase is **template-only**. No Python changes except one small model property check (Step 1).

---

## Step 1 — Read before writing

Read these files in full:

- `app/templates/convenor/dashboard/status.html` — understand every existing section and its data dependencies
- `app/templates/convenor/dashboard/overview_cards/submitter_card.html` (if it exists) — the current submission period
  rendering
- `app/shared/context/convenor_dashboard.py` — confirm `marking_urgent_count` computation and what `convenor_data`
  contains
- The `MarkingEvent` model — confirm whether a `workflow_status_summary` or equivalent property exists returning counts
  of (complete, pending_upload, in_progress, risk_flags). If it does not exist, note this — we will need a small
  helper (see Step 3)
- The `SubmissionPeriodRecord` model — confirm `has_active_marking_event`, `closed`, `feedback_open` properties

---

## Step 2 — Left column: submission management

The left column contains, in order:

### A. Active submission period card

One card per submission period in `config.periods`, with the **current period** (where
`submission_period == config.submission_period`) rendered expanded at the top, others collapsed below it (use a
`<details>`/`<summary>` element or Bootstrap collapse — whichever is more consistent with the rest of the app).

Each expanded period card shows:

1. **Header row**: period display name, status chip(s) (`Feedback open`, `⚠ N pending upload` if applicable), Configure
   button → `url_for('convenor.edit_period_record', pid=period.id)`, "Full detail →" link →
   `url_for('convenor.periods', id=pclass.id)#period_section_N`
2. **Date/settings summary line**: start date, hand-in date, supervision unit count, markers per submission — all on one
   line in `text-body-secondary small`
3. **Marking events sub-section**:
    - Section label "Marking events" with "Add event" button
    - One row per `MarkingEvent` in `period.marking_events`:
        - Event name, workflow count, status chip
        - Active events: highlighted with `border-info` left border or similar
        - Buttons: "Workflows" (→ workflows inspector) for closed events; "Inspect" (primary style) for active events
    - Below the event rows: 4-cell status grid (Complete / Pending upload / In progress / Risk flags) — populated from
      the helper in Step 3
    - Action buttons: "Send marking emails", "Calculate conflation", "Generate feedback" — use existing route names from
      Phase 0
4. **Supervision units summary line** (not a list): "N supervision units · «first week» – «last week»" with two
   buttons: "Inspect units" and "Populate events". This replaces the full scrolling list. The full list remains
   accessible via "Inspect units".
5. **Period closure notice** if `period.has_active_marking_event`: small `text-danger` line "Period closure unavailable
   while marking events are active"

### B. Submitters card

Below the period card. Shows:

- 4-cell metric grid: Uploaded / Missing / Risk flags / Feedback released
- Action buttons: "Assign markers", "Assign moderators", "Marking analysis"
- "View all N →" link to `url_for('convenor.submitters', id=pclass.id)`

Data source: derive counts from `config.submitting_students` filtered appropriately, or reuse what is already in
`convenor_data` if sufficient.

---

## Step 3 — Workflow status summary helper

Check whether `MarkingEvent` already has a property returning `(complete, pending_upload, in_progress, risk_flags)`
counts.

If it does not, add a `workflow_status_summary` property to `MarkingEvent` in the model file:

```python
@property
def workflow_status_summary(self) -> dict:
    """Return counts of workflows by status for display in the period card."""
    # implement using self.workflows relationship
    # keys: complete, pending_upload, in_progress, risk_flags
    # derive from existing WorkflowMixin state constants
```

Use existing state constants — do not invent new ones. Keep this a Python property, not a separate query.

---

## Step 4 — Right column: selection management

The right column contains, in order:

### A. Cycle lifecycle card

- Small alert strip at top if there are action items (blocking only) — message only, link text "see actions panel
  above ↑", no full detail here
- Lifecycle stepper: reuse the existing stepper already in `status.html` (it is already there — move it, do not rewrite
  it)
- Deadline line + action buttons: "Change deadline", "Reset popularity", "Close selections"

### B. Selection metrics card

- 3-cell metric grid: Submitted / Bookmarked / Confirmations outstanding — with denominator in smaller text
- Secondary line: "No bookmarks: N · No bookmarks or submission: N"
- "View selectors →" link

### C. Popular projects card

- Compact table: rank, truncated project name (link), selections count, views count
- "cf. N days" interval selector — reuse the existing AJAX mechanism from `popular_projects_ajax`
- "Reset popularity" button (can be removed here if already in the lifecycle card above)

---

## Step 5 — Column wrapper markup

Use Bootstrap grid for the split:

```html

<div class="row g-3">
    <div class="col-12 col-lg-7">
        {# left column — submission management #}
    </div>
    <div class="col-12 col-lg-5">
        {# right column — selection management #}
    </div>
</div>
```

`col-12` on small screens (stacks vertically, left/submission first), `col-lg-7`/`col-lg-5` at large breakpoint. This
gives approximately 58/42 — close enough to the target 60/40.

Add column labels above each column's first card:

```html
<p class="small fw-semibold text-body-secondary text-uppercase mb-2">
    <i class="fas fa-file-alt fa-fw"></i> Submission management
    <span class="badge bg-primary-subtle text-primary-emphasis rounded-pill ms-1">Period #N active</span>
</p>
```

---

## Step 6 — Remove superseded content from `status.html`

After the new layout is in place, identify and remove (or mark `{# SUPERSEDED by Phase 3 #}`) the old sections that are
now replaced:

- The old full submission period section (long card with supervision unit list)
- The old selector metrics section if replaced by the right column
- Any duplicate lifecycle stepper

Do not remove the forms (`golive_form`, `change_form`, `issue_form`) if they are still rendered — they may be needed for
POST handling. If they are only used for display data now available inline, mark them as candidates for future removal
but leave them in for this phase.

---

## Step 7 — Verification

1. Grep `status.html` for `supervision_units` or equivalent — confirm the full unit list is gone and replaced by the
   summary line.
2. Confirm the marking event rows appear **inside** the period card, not below it.
3. Confirm `col-lg-7` / `col-lg-5` are the column classes (not hardcoded widths).
4. Confirm no inline `style` attributes set font sizes or hex colours.
5. Confirm the popular projects AJAX call (`popular_projects_ajax`) still functions — the `<tbody id>` it targets must
   still be present with the same id.

Report results of all five checks.