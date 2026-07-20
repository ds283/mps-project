# 06 — Submitters page: journal button state + drawer

## Goal
Upgrade the existing "Journal" button on each submitter card so it shows review state
(count + unread dot) and opens the shared drawer, with quick-add available.

## Context
- Template: `app/templates/convenor/dashboard/submitters_v2.html` (card per submitter, action
  buttons: Journal, History, Roles, overflow).
- Route: `convenor.submitters` in `app/convenor/submitters.py`; card data via the submitters
  AJAX formatter in `app/ajax/convenor/`.

## Tasks
1. **Stateful button.** Replace the plain Journal button with the `journal_indicator` chip
   styled as a button (`<i class="fas fa-book"></i> Journal <count>` + red dot on unread,
   muted when nothing visible). Reuse the prompt-04 macro/JS; pass `data-student-id`.
2. **Drawer + quick add.** Clicking opens the shared drawer for that submitter. Add quick-add
   (either a `+` split on the button or a "Add entry…" item in the card overflow menu) opening
   the shared modal.
3. **Formatter.** Feed `journal_counts(current_user)` into the submitters card formatter so the
   button renders the right state server-side on first paint.

## Acceptance
- Journal button reflects visible/unread counts; muted when nothing visible to the user.
- Opens the shared drawer for the correct submitter; quick-add works and refreshes the button.
- Consistent with the selectors chip (same macro/JS); no teal; no console errors.

## Commit
```
git add -A && git commit -m "journal-redesign(06): journal button state + drawer on submitters page"
```
