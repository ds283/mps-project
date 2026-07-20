# 04 — Shared journal drawer + quick-add modal + AJAX endpoints

## Goal
Build the reusable pieces every list/dashboard surface uses: a right-side **offcanvas
drawer** that previews a student's visible entries, a native Bootstrap **quick-add modal**,
and the AJAX endpoints that feed them. Later prompts (05–08) only wire these in.

## Context
- The drawer/modal appear on the selectors table, submitters cards, overview card and the
  Journal tab, so they must be a single shared partial + JS, not per-page copies.
- Existing AJAX conventions: blueprint routes under `app/convenor/…`, JSON/HTML fragments,
  DataTables formatters in `app/ajax/convenor/`.
- Reference look: the prototype's `#journalDrawer` offcanvas and `#addModal` modal.

## Tasks
1. **Drawer partial.** Add `app/templates/convenor/journal/_drawer.html` — a single
   `offcanvas offcanvas-end` (id `journalDrawer`, ~440px) rendered once in the convenor
   dashboard layout. Header uses the app blue (no teal). Body is populated by AJAX on open.
   Include the "N further entries not visible to you" locked note and a "Mark all read" action.
2. **Drawer content endpoint.** `convenor.journal_drawer_ajax/<sid>` returns the rendered
   entry list HTML for a student (visible entries only, newest first, unread flagged, recent
   tagged, type icon/colour, truncated body). Reuse `visible_journal_entries`.
3. **Quick-add modal.** Add `_add_modal.html` — a native Bootstrap `modal fade modal-lg`
   reusing the prompt-02 form fields (Title, Type, Entry, Project classes, Restrict). Submits
   via AJAX to a `convenor.quick_add_journal_entry/<sid>` endpoint; on success it closes,
   toasts, and refreshes the opener (drawer body + the triggering row/badge). Keep
   `hidden_tag()`/CSRF.
4. **Shared JS.** One JS module (in the existing convenor static bundle or a small included
   script) that: opens the drawer for a `data-student-id`, loads its AJAX body, wires
   "Mark all read" (→ `mark_read` endpoint) and the quick-add modal, and exposes a
   `refreshJournalIndicators(studentId)` used by callers to repaint a chip/button after a change.
5. **Indicator macro.** Add a Jinja macro `journal_indicator(counts, student_id)` (e.g. in a
   `_macros.html`) that renders the standard chip: book icon + visible count, `has-unread`
   style + red dot when `counts.unread`, muted/`0` when nothing visible, `data-student-id`
   for the JS. This is the single source of truth for the indicator used in 05–08.

## Acceptance
- Drawer opens from any element with the trigger + `data-student-id`, shows that student's
  visible entries with type/unread/recent styling, and the locked-note count is correct.
- Quick-add modal creates an entry via AJAX and the drawer/indicator update without a full
  page reload.
- Restricted entries never appear in the drawer body.
- No teal; chrome uses the app's primary blue.

## Commit
```
git add -A && git commit -m "journal-redesign(04): shared journal drawer, quick-add modal, indicator macro + AJAX"
```
