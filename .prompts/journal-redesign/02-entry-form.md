# 02 — Add/edit entry form: type + visibility

## Goal
Let convenors set the entry **type** and **restrict visibility** when creating/editing a
journal entry, on the existing full-page form.

## Context
- Template: `app/templates/convenor/journal/edit_entry.html` (extends `base_form.html`,
  uses `wtf.render_field`, TinyMCE on `#entry-editor`, select2 on `#project_classes`).
- Route + form: `convenor.add_journal_entry` / `convenor.edit_journal_entry` in
  `app/convenor/journal.py`; the WTForms class lives with the other convenor forms
  (grep for the current journal form class, e.g. `JournalEntryForm`).

## Tasks
1. **Form fields.** Add to the journal entry form:
   - `entry_type` — a `SelectField`/`QuerySelectField` populated from the type map added in
     prompt 01 (labels in type order). Render with select2 (`select2-small` classes per
     `CLAUDE.md`).
   - `restricted` — a `BooleanField` labelled "Restrict visibility to project convenors and
     me", with help text explaining who can then see the entry.
   Share config via the existing form mixins where possible.
2. **Persist.** In the add and edit POST handlers, save `entry_type` and `restricted`.
   Use `form.validate_on_submit()` (not manual method checks) and keep the `hidden_tag()`
   CSRF pattern. Set `last_edit_timestamp = datetime.now()` on edit.
3. **Template.** Insert the Type select directly under the Title field and the restrict
   checkbox below the project-classes field, matching the mock's order:
   Title → Type → Entry (rich text) → Project classes → Restrict visibility → Save/Cancel.
4. **Audit.** Wrap the create/edit DB commit with `log_db_commit(...)` (per `CLAUDE.md`)
   describing the action.

## Acceptance
- Creating and editing an entry round-trips `entry_type` and `restricted` correctly.
- Editing preserves the existing TinyMCE body and select2 project-class behaviour.
- Type select shows all five types with correct labels; default is Note.

## Commit
```
git add -A && git commit -m "journal-redesign(02): type + visibility on add/edit entry form"
```
