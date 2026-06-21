# Phase 7b — AVD dashboard: grade capsule, fix not-applicable vs. missing-but-graded distinction

Context: Phase 7 added the `.sv2-metric-cap.grades` capsule to the AVD
dashboard's right-hand column. Review of the result found the capsule
omits a grade item entirely whenever its value is `None` — but this
conflates two different cases:

- A submission period that doesn't use a presentation assessment at all
  (e.g. some periods have no presentation component) — correctly omitted,
  no presentation item should appear.
- A submission period that *does* use a presentation assessment, but it
  hasn't been graded yet — `submitters_v2.html`'s own capsule (the
  reference implementation, per Phase 7's Step 0.1) shows this as a
  dimmed `—` (`.sv2-mv-dim`), not by omitting the item.

The AVD dashboard's current capsule-building logic appears to treat both
cases the same way (omit), per the confirmed example: a record from a
submission period with no presentation assessment correctly shows no
presentation item — but the underlying logic doesn't yet distinguish that
from "presentation assessment exists for this period but isn't graded,"
which should still show the item with a `—`.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase7b-recon-output.md`, present before coding)

1. Copy verbatim the current AVD dashboard capsule-building code (the
   loop/filter over `grade_display_data()`'s output added in Phase 7).
2. Copy verbatim `submitters_v2.html`'s equivalent logic (the
   `visible_grades` filtering around `grade_display_data()`, per Phase
   7's Step 0.2 — re-confirm exactly how it decides "applicable but
   ungraded" (show `—`) vs. "not applicable to this period" (omit
   entirely)). Confirm whether this distinction is encoded in
   `grade_display_data()`'s own return shape (e.g. a third state per item,
   not just `grade: None`) or computed separately by `submitters_v2.html`
   from period/pclass configuration. State which — this determines
   whether the AVD dashboard's fix is a one-line change (if
   `grade_display_data()` already distinguishes the two cases and the AVD
   capsule logic just isn't checking the right field) or needs its own
   applicability check (if `submitters_v2.html` computes it separately
   from data not available to `grade_display_data()` alone).

## Step 1 — Fix

- Update the AVD dashboard's capsule logic to match
  `submitters_v2.html`'s behaviour exactly: omit an item only when it's
  genuinely not applicable to the submission period, show `—`
  (`.sv2-mv-dim`, same styling) when it's applicable but not yet graded.

## Step 2 — Verification

- Manually confirm (describe what you checked):
  - a record from a period with no presentation assessment still shows
    no presentation item (the Dimitri Verai case — must not regress)
  - a record from a period that does have a presentation assessment, but
    where it hasn't been graded yet, now shows "Presentation —" with the
    dimmed styling, matching `submitters_v2.html`'s treatment of the same
    case
  - Supervision and Report follow the same corrected logic if they have
    equivalent not-applicable-vs-ungraded cases (confirm whether they do
    — Report in particular, since every record in this dashboard has
    presumably already had a report submitted, may never hit the
    not-applicable case, but check rather than assume)
