---
paths:
  - app/tasks/**
---

# Background tasks and TaskRecord

All Celery tasks launched via `register_task()` must ensure the associated `TaskRecord` reaches a
terminal state (`SUCCESS`, `FAILURE`, or `TERMINATED`).

- When a task calls `self.replace(chain)`, the replacement chain runs with new Celery task IDs.
  The outer chain (including any `final` task) is abandoned and will not execute. The replacement
  chain is solely responsible for updating the `TaskRecord`.
- Any chain passed to `self.replace()` **must** include:
  - A final task that calls `progress_update(celery_id, TaskRecord.SUCCESS, 100, ...)` on success.
  - An `.on_error(error_task.si(celery_id))` handler that calls
    `progress_update(celery_id, TaskRecord.FAILURE, 100, ...)` on failure.
- The `celery_id` (TaskRecord UUID) must be threaded as an explicit argument to all tasks in a
  replacement chain so they can update the `TaskRecord`. Do not rely on the Celery task ID
  for this purpose — task IDs change when `self.replace()` is used.
- The `task_failure` and `task_revoked` Celery signals in `make_celery.py` act as a catch-all
  safety net for directly-launched tasks (where Celery task_id == TaskRecord UUID), but do not
  cover tasks inside replacement chains.

## Key symbols

| Symbol | Defined in | Notes |
|---|---|---|
| `register_task()` | `app/task_queue/background_task.py` | Decorator; creates and registers a `TaskRecord` |
| `progress_update()` | `app/task_queue/background_task.py` | Updates `TaskRecord` state, progress, and message |
| `TaskRecord` | `app/models/utilities.py` (export: `app/models`) | Import as `from ..models import TaskRecord` |
