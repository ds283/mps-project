# Feedback UI Implementation Progress

## Task 1 — Initiate generation of feedback ✅ COMPLETE

### 1a: New fields on ConflationReport + Alembic migration ✅
- Added `recipe` (String), `feedback_celery_id` (String), `feedback_generation_failed` (Boolean) columns
  to `ConflationReport` in `app/models/markingevent.py`
- Migration: `migrations/versions/f0a1b2c3d4e5_conflation_report_feedback_fields.py`
  (revision: `f0a1b2c3d4e5`, down_revision: `c7d8e9f0a1b2`)

### 1b: Track celery_id/failed in generate_feedback_report ✅
- `app/tasks/marking.py` — `generate_feedback_report`:
  - Sets `cr.feedback_celery_id` and clears `feedback_generation_failed` after idempotency check
  - Clears `feedback_celery_id`, sets `cr.recipe = recipe.label`, clears `feedback_generation_failed` on success
- `app/tasks/feedback_orchestration.py` — `feedback_record_error`:
  - Sets `cr.feedback_generation_failed = True`, clears `cr.feedback_celery_id` as belt-and-braces

### 1c: Advance MarkingEvent to READY_TO_PUSH_FEEDBACK ✅
- `app/tasks/feedback_orchestration.py` — `feedback_record_done`:
  - After job completion, checks if all ConflationReports for the event have feedback
  - Advances `event.workflow_state` to `READY_TO_PUSH_FEEDBACK` if so
- New imports: `MarkingEvent`, `MarkingEventWorkflowStates` added to feedback_orchestration.py

### 1d: New route + form + template ✅
- `app/convenor/forms.py` — `GenerateFeedbackFormFactory(pclass_id)` added
  - `QuerySelectField` for `FeedbackRecipe` filtered by pclass_id
- `app/convenor/markingevent.py` — `generate_marking_event_feedback(event_id)` route added
  - GET: shows recipe selection form
  - POST: calls `launch_feedback_job()` synchronously, redirects to workflow inspector
  - Removed `generate_feedback_reports` Celery task from `app/tasks/marking.py`
  - Removed now-unused `launch_feedback_job` and `report_error` imports from marking.py
- Template: `app/templates/convenor/feedback/generate_feedback_form.html` created

### 1e: Update MarkingEvent.get_convenor_actions ✅
- `app/models/markingevent.py` — new `generate_feedback_url` parameter added
- CTA for `READY_TO_GENERATE_FEEDBACK` state surfaced
- Call site in `event_marking_workflows_inspector` updated

### 1f: Update AJAX menus ✅
- `app/ajax/convenor/markingevent.py` — `_period_marking_event_menu` updated:
  - "Conflation reports…" item for `>= READY_TO_GENERATE_FEEDBACK`
  - "Generate feedback…" item for `READY_TO_GENERATE_FEEDBACK`
  - "Fill missing feedback…" + "Send feedback…" items for `READY_TO_PUSH_FEEDBACK`
- Stub routes added in `app/convenor/markingevent.py`:
  - `marking_event_conflation_reports` (placeholder, Task 2)
  - `push_marking_event_feedback` (placeholder, Task 3)

---

## Task 2 — ConflationReport inspector 🔲 PENDING

## Task 3 — Push feedback tasks 🔲 PENDING

## Task 4 — Advance MarkingEvent to CLOSED 🔲 PENDING
(Logic planned in mark_feedback_sent callback, Task 3)
