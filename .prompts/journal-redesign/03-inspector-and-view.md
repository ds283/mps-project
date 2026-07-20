# 03 — Inspector table + view-entry page: show the type

## Goal
Surface entry **type** (icon + colour + label) on the per-student journal inspector table
and the single-entry view page, and stop leaking restricted entries.

## Context
- Inspector template: `app/templates/convenor/journal/inspector.html` (DataTables
  `#journal-table`, server-side, AJAX → `/convenor/journal_ajax/<student.id>`).
- Row formatters: `app/ajax/convenor/journal.py` (`journal_data(...)` builds
  `timestamp/year/classes/title/owner/actions`).
- View page: `app/templates/convenor/journal/view_entry.html` (primary card header).
- AJAX endpoint feeding the table: `convenor.journal_ajax` in `app/convenor/journal.py`.

## Tasks
1. **Type column (AJAX formatter).** Add a `_type` template + `type` key to `journal_data`
   rendering a badge: `<span class="badge …"><i class="fas fa-…"></i> Label</span>` using the
   `JOURNAL_TYPE_DISPLAY` map from prompt 01. Add the `Type` column to `inspector.html`'s
   `<thead>` and to the DataTables `columns` array (place it between `Project classes` and
   `Title`; adjust the width percentages so they still total ~100%).
2. **Filter restricted entries.** In `convenor.journal_ajax`, filter the query through the
   `visible_journal_entries(current_user)` helper so restricted entries the user can't see
   never reach the table. If the student has hidden entries, keep the count accurate but
   excluded.
3. **View-entry badge.** In `view_entry.html`, add the type badge to the primary card header
   (next to the title) and a "Type" item in the metadata row. Guard the whole page with a
   visibility check — a user who can't see the entry gets a 403/redirect, not the content.
4. **Unread on view.** When a user opens `view_entry` (or the inspector marks-as-read
   action), call `entry.mark_read(current_user)`.

## Acceptance
- Inspector table shows a Type column with correct icon/colour/label per row.
- Restricted entries are absent from the table for users who lack access.
- View-entry page shows the type and blocks unauthorised access.
- Opening an entry marks it read for the current user.

## Commit
```
git add -A && git commit -m "journal-redesign(03): type column on inspector + view page, visibility filtering"
```
