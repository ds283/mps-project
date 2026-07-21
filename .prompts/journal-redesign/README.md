# Journal redesign — Claude Code implementation prompts

This folder contains a **numbered sequence of prompts** for Claude Code to implement the
convenor journal-system redesign in the `mps-project` repository.

## How to use

Run the prompts **in order**. Each prompt is self-contained and ends with an explicit
instruction to **commit** once its acceptance criteria are met, so every step is a clean
rollback point. Do not start a prompt until the previous one is committed and the app boots.

Suggested commit message convention:

```
journal-redesign(NN): <short summary>
```

## Sequence

| # | File | Theme | Depends on |
|---|------|-------|------------|
| 01 | `01-data-model.md` | Entry `type`, visibility, read-receipts + migration | — |
| 02 | `02-entry-form.md` | Type + visibility on the add/edit form | 01 |
| 03 | `03-inspector-and-view.md` | Type column on inspector + badge on view/entry pages | 01, 02 |
| 04 | `04-shared-drawer.md` | Reusable journal drawer (offcanvas) + quick-add modal + AJAX | 01–03 |
| 05 | `05-selectors-page.md` | Per-row journal chip + quick add on the selectors table | 04 |
| 06 | `06-submitters-page.md` | Journal button state + drawer on the submitters cards | 04 |
| 07 | `07-overview-summary.md` | "Journal activity" summary card on the overview dashboard | 04 |
| 08 | `08-journal-tab.md` | New top-level "Journal" dashboard tab + aggregate AJAX view | 04 |
| 09 | `09-review-fixes.md` | Single unread encoding + legend placement + selectors chip under name | 05, 07, 08 |

## Design intent (shared context for every prompt)

The journal is a lightweight, auditable record of actions/changes to a student's status
(enrol, delete, record communication, status change, note). The redesign makes entries
**discoverable** and **quick to act on** from the convenor's normal workflow.

Cross-cutting rules that apply to all prompts:

- **Not all entries are visible to the convenor.** Every count, list and indicator must be
  filtered through a single "visible to `current_user`" helper (added in prompt 01). Never
  leak the existence of a restricted entry beyond an aggregate "N further entries not
  visible to you" note.
- **"Needs review" = recent OR unread.** Recent means created within the last 30 days;
  unread means no read-receipt for `current_user` (prompt 01). Indicators combine both.
- **Entry types** get a consistent icon + colour everywhere they appear:
  - Communication — `fa-envelope`, indigo (`#3f51d6` on `#e7ecff`)
  - Status change — `fa-exchange-alt`, amber (`#b5730d` on `#fdeccf`)
  - Enrolment — `fa-user-plus`, teal (`#0b8794` on `#d8f3f5`)
  - Deletion — `fa-trash`, red (`#c23b2c` on `#fbe0dd`)
  - Note — `fa-sticky-note`, grey (`#555a61` on `#e9ebee`)
- **Stay within the existing design language**: Bootstrap 5, the app's blue primary for
  journal chrome (no new accent colours beyond the type swatches above), Font Awesome icons,
  DataTables + AJAX row formatters, WTForms with `hidden_tag()`, select2, `user.initials`.
- Follow every rule in the repo's root `CLAUDE.md` (hand-written migrations, `log_db_commit`
  for audited changes, form/CSRF conventions, etc.).

A full visual reference of the target UI (built as an HTML prototype) accompanies this
handoff; recreate its look using the codebase's existing Jinja/Bootstrap patterns rather
than copying markup verbatim.
