# 05 — Selectors page: per-row journal chip + quick add

## Goal
Make the journal a first-class column on the selectors table: each row shows the
`journal_indicator` chip (opening the drawer) and a quick-add button, so a convenor never
has to leave the page to review or record an entry.

## Context
- Template: `app/templates/convenor/dashboard/selectors.html`.
- Route: `convenor.selectors` in `app/convenor/selectors.py`.
- Row data comes from a DataTables AJAX formatter in `app/ajax/convenor/selectors*.py`
  (grep for the selectors row builder). Uses the shared pieces from prompt 04.

## Tasks
1. **New column.** Add a `Journal` column to the selectors table header and DataTables
   `columns` config (before the existing `Actions`/menu column). Keep column-count/order in
   sync between template `<thead>` and JS.
2. **Formatter.** In the selectors AJAX formatter, compute `journal_counts(current_user)` for
   each student and render the `journal_indicator(counts, sid)` macro from prompt 04. Add a
   small green quick-add `+` button next to it (opens the shared quick-add modal for that sid).
   Do the counts efficiently (batch, avoid per-row N+1 where practical).
3. **Actions menu.** Keep the existing "View journal…" item but point it at the drawer
   (`data-student-id`) rather than navigating away; leave a secondary "Open full journal page"
   link to the inspector.
4. **Legend.** Add the small legend under the table ("muted book = no entries visible to you;
   red dot = unread"), matching the mock.

## Acceptance
- Every selector row shows the chip with correct visible/unread state; muted+0 when nothing
  is visible.
- Chip opens the drawer for the right student; `+` opens quick-add; both update in place.
- Table still sorts/paginates; column counts line up; no console errors.

## Commit
```
git add -A && git commit -m "journal-redesign(05): per-row journal chip + quick add on selectors page"
```
