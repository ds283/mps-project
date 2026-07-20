# 08 — New top-level "Journal" dashboard tab

## Goal
Add a top-level **Journal** tab to the convenor dashboard: an aggregate, filterable list of
all entries visible to the convenor across selectors and submitters, with search, filter
chips and quick-add.

## Context
- Convenor dashboard tab strip + panes live in the dashboard layout / `overview.html` and the
  routes in `app/convenor/dashboard.py`. Follow how existing tabs (Selectors, Submitters,
  Tasks) register their nav pill, pane, and server-side DataTables AJAX endpoint.
- Reuse prompt-01 helpers, prompt-04 drawer/modal/macros, prompt-03 type badge formatter.

## Tasks
1. **Nav pill + count.** Add a `Journal` pill to the dashboard tab strip using the standard
   styling (app blue/grey — **no teal**), with a grey count badge = unread entries for the
   convenor. Add the matching tab-pane.
2. **Route + template.** Add `convenor.journal_tab` (or extend the dashboard route) rendering
   `convenor/dashboard/journal.html`: a header bar (blue) with an "Add entry…" button, a row
   of compact stat chips (accessible / unread / this month / auto-generated), filter chips
   (All / Unread / This month / Selectors / Submitters), a search box, and a DataTables table
   (Entry, Student, Type, Created by, When, Review→Open-drawer).
3. **Aggregate AJAX.** Add `convenor.journal_tab_ajax` — server-side DataTables endpoint over
   **all visible entries** for the convenor's config, joined to student + type, honouring the
   filter chips (as query params) and search. Unread rows get the highlight class; recent rows
   get the `new` tag. Filtering must go through `visible_journal_entries`.
4. **Wire actions.** "Open" opens the shared drawer for the entry's student; "Add entry…" opens
   the shared quick-add modal (student chosen in-modal, or pre-Selectors/Submitters scoping).
5. **Auto badge.** Entries with no owner render the `Auto` badge in the Created-by column.

## Acceptance
- Journal tab appears in the strip with an accurate unread count and activates like other tabs.
- Table lists only entries visible to the convenor, across selectors + submitters, with
  correct type badges, unread/recent styling, working search + filter chips + pagination.
- Row "Open" opens the drawer; "Add entry…" creates an entry that appears after refresh.
- No teal anywhere; chrome matches the app's Bootstrap vocabulary; no console errors.

## Commit
```
git add -A && git commit -m "journal-redesign(08): aggregate journal tab on convenor dashboard"
```
