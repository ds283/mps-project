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

## Task 2 — ConflationReport inspector ✅ COMPLETE

### Task 7: Inspector route + template ✅
- `app/convenor/markingevent.py` — `marking_event_conflation_reports(event_id)` fully implemented
  - Loads active `FeedbackOrchestrationJob` instances for progress panel
  - Computes per-state counts: total, with_feedback, sent, failed, in_progress, stale
  - Renders `convenor/markingevent/conflation_reports_inspector.html`
- `app/templates/convenor/markingevent/conflation_reports_inspector.html` created
  - Back nav + event summary card
  - State summary badges (stale, generating, failed, with feedback, sent)
  - Active jobs progress panel (reusing same pattern as `marking_workflow_inspector.html`)
  - DataTable for `conflation-reports-table` with columns: student, project, grades, feedback, actions

### Task 8: AJAX endpoint + row formatter ✅
- `app/convenor/markingevent.py` — `conflation_reports_ajax(event_id)` POST endpoint added
  - Joins `ConflationReport → SubmissionRecord → SubmittingStudent → StudentData → User`
  - `ServerSideSQLHandler` with student name search/order column
  - Calls `partial(ajax.convenor.conflation_report_data, event_id)`
- `app/ajax/convenor/markingevent.py` — `conflation_report_data(event_id, crs)` added
  - Template strings: `_conflation_report_student`, `_conflation_report_project`,
    `_conflation_report_grades`, `_conflation_report_feedback`, `_conflation_report_menu`
  - Student: name + candidate number
  - Project: project name + supervisor name
  - Grades: target→value dict with stale badge, generated_by, timestamp
  - Feedback: reports list with thumbnail, download link, recipe label, sent status, spinner for in-progress
  - Menu: inline POST forms for reconflate (if stale) and delete feedback; links for regenerate, view emails
- `app/ajax/convenor/__init__.py` — `conflation_report_data` exported

### Task 9: Individual CR action routes ✅
- `app/convenor/markingevent.py`:
  - `_conflation_report_editable(cr)` helper: returns `not cr.feedback_sent`
  - `reconflate_conflation_report(cr_id)` — POST, re-runs single-CR conflation, clears `is_stale`
  - `delete_conflation_report_feedback(cr_id)` — POST, deletes FeedbackReports, regresses event state if needed
  - `regenerate_conflation_report_feedback(cr_id)` — GET/POST, reuses `generate_feedback_form.html`
  - `view_conflation_report_emails(cr_id)` — GET, lists `cr.feedback_emails`
- `app/templates/convenor/markingevent/conflation_report_emails.html` created
  - Shows student/event summary, lists EmailLog entries with recipients and send_date

---

## Task 3 — Push feedback tasks ✅ COMPLETE

### 3a: PushFeedbackForm ✅
- `app/convenor/forms.py` — `PushFeedbackForm` added
  - `delay_hours` (IntegerField, default 1, 0–168), `test_email` (StringField, optional)
  - `notify_supervisors`, `notify_markers`, `notify_moderators` (BooleanField)
  - `submit` (SubmitField)

### 3b: Module-level helpers in `app/tasks/push_feedback.py` ✅
- `MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024` defined at module level
- `_collect_cr_feedback_attachments(cr)` — builds `EmailWorkflowItemAttachment` list from `cr.feedback_reports`
- `_build_target_roles(notify_supervisors, notify_markers, notify_moderators)` — returns `List[int]` of role types
- `_build_student_email_item(cr, user_id, defer, test_email)` — builds student `EmailWorkflowItem` with
  `mark_feedback_sent` callback
- `_build_faculty_email_items_for_cr(cr, defer, test_email, target_roles)` — builds per-faculty-member
  `EmailWorkflowItem` list with `link_feedback_email_to_cr` callback
- All helpers moved from inside the `register_push_feedback_tasks` closure to module level so they can be
  imported directly by route handlers

### 3c: New Celery tasks in `register_push_feedback_tasks` ✅
- `mark_feedback_sent(email_log_id, cr_id, user_id)` — callback after student email sent:
  sets `cr.feedback_sent`, records push user/timestamp, links `EmailLog` to `cr.feedback_emails`,
  advances `MarkingEvent` to `CLOSED` if all CRs are sent (Task 4)
- `link_feedback_email_to_cr(email_log_id, cr_id)` — callback after faculty email sent:
  links `EmailLog` to `cr.feedback_emails`
- `push_marking_event_feedback_task(event_id, user_id, delay_hours, test_email, ...)` — whole-event push:
  creates ONE student `EmailWorkflow` + ONE faculty `EmailWorkflow`; iterates all unsent CRs

### 3d: Routes in `app/convenor/markingevent.py` ✅
- `push_marking_event_feedback(event_id)` — GET/POST:
  - GET: renders `push_feedback_form.html` with unsent/total counts
  - POST: dispatches `push_marking_event_feedback_task` via `celery.tasks.get(...)`, redirects to inspector
- `push_single_cr_feedback(cr_id)` — GET/POST:
  - GET: renders same `push_feedback_form.html` with `single_student` context
  - POST: directly creates `EmailWorkflow` + items using module-level helpers (no Celery wrapper)
  - Guards: `_conflation_report_editable(cr)` + `feedback_reports.count() > 0`
- `EmailWorkflow` added to top-level model imports

### 3e: Template ✅
- `app/templates/convenor/feedback/push_feedback_form.html` created
  - Event summary card (period, total students, awaiting-send badge)
  - `PushFeedbackForm` rendered: delay_hours, test_email, faculty notification checkboxes, submit
  - "All sent" success alert shown when `unsent_count == 0`

---

## Task 4 — Advance MarkingEvent to CLOSED ✅ COMPLETE

- Implemented inside `mark_feedback_sent` Celery callback in `app/tasks/push_feedback.py`:
  ```python
  event: MarkingEvent = cr.marking_event
  if event is not None and event.workflow_state == MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK:
      all_crs = event.conflation_reports.all()
      if all_crs and all(c.feedback_sent for c in all_crs):
          event.workflow_state = MarkingEventWorkflowStates.CLOSED
  ```
- Fires after every student feedback email is confirmed sent; advances to `CLOSED` once all CRs are sent
