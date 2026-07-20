# 01 — Data model: entry type, visibility, read-receipts

## Goal
Extend the journal data model so the UI can (a) categorise entries by type, (b) restrict
an entry's visibility, and (c) track which entries each user has read. Provide the query
helpers the later prompts depend on.

## Context
- Model: `app/models/journal.py` → `StudentJournalEntry` (owner nullable = auto entries;
  `title`/`entry` are `EncryptedType`; `project_classes` m2m via `journal_entry_to_pclass_config`).
- `StudentData` has `journal_entries` backref (`lazy="dynamic"`).
- Migrations are hand-written — follow the chain-tip procedure in root `CLAUDE.md`.
  Do **not** run `flask db migrate`.

## Tasks
1. **Entry type.** Add an integer-coded `entry_type` column to `StudentJournalEntry` with a
   module-level enum/const map and labels:
   `NOTE=0, COMMUNICATION=1, STATUS_CHANGE=2, ENROLMENT=3, DELETION=4`.
   Default `NOTE`. Add a `type_label` and `type_icon`/`type_colour` helper (or a single
   dict `JOURNAL_TYPE_DISPLAY`) so templates and AJAX formatters render icon + colour
   consistently (values per README).
   - Where the code auto-creates entries (enrolment, deletion, recorded comms), set the
     appropriate `entry_type` instead of leaving the default. Grep for existing
     `StudentJournalEntry(` construction sites and update them.
2. **Visibility.** Add a boolean `restricted` column (default `False`). When `True`, the
   entry is visible only to its `owner` and to users with a convenor/admin role for the
   entry's project class(es). Implement a method
   `StudentJournalEntry.is_visible_to(user) -> bool` encoding this rule (auto/unrestricted
   entries are visible to any convenor/admin who can see the student).
3. **Read-receipts.** Add a `student_journal_entry_read` association table
   (`entry_id`, `user_id`, `read_timestamp`) and helpers:
   - `StudentJournalEntry.is_read_by(user) -> bool`
   - `StudentJournalEntry.mark_read(user)` / `mark_unread(user)` (idempotent; use
     `datetime.now()`, not `utcnow`).
4. **Query helpers on `StudentData`** (used by every UI prompt):
   - `visible_journal_entries(user)` → query filtered by `is_visible_to`.
   - `journal_counts(user)` → dict `{visible, unread, recent}` where recent = created within
     the last 30 days. Keep it efficient (avoid decrypting bodies just to count).
5. **Migration.** Hand-write one Alembic migration adding the two columns + the read table,
   with a matching `downgrade`. Verify the chain tip first and that the new revision id is
   unused.

## Acceptance
- App boots; `flask db upgrade` applies cleanly and `downgrade` reverts.
- Existing entries default to `NOTE` / `restricted=False` / unread for everyone.
- `is_visible_to`, `is_read_by`, `visible_journal_entries`, `journal_counts` are unit-exercisable
  from a shell and return sensible values.
- No body decryption happens in the count path.

## Commit
```
git add -A && git commit -m "journal-redesign(01): entry type, visibility flag, read-receipts + helpers"
```
