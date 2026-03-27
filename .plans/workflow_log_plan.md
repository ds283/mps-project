# Workflow Log Implementation Plan

## Overview

This plan tracks implementation of a workflow log system for the MPS-Project platform.
The log captures database commits with human-readable summaries, linked users, project classes,
and the route/task that triggered the operation.

Status key: [ ] pending | [~] in progress | [x] complete

---

## TASK 1: Database Model [x]

**File:** `app/models/workflow_log.py` (new)

### Model: `WorkflowLogEntry`

| Column       | Type        | Notes                                 |
|--------------|-------------|---------------------------------------|
| id           | Integer PK  |                                       |
| timestamp    | DateTime    | indexed; set to `datetime.now()`      |
| initiator_id | Integer FK  | → `users.id`; nullable (Celery tasks) |
| endpoint     | String(255) | route name or Celery task name        |
| summary      | Text        | human-readable description            |

**Relationships:**

- `initiator`: many-to-one → `User`
- `project_classes`: many-to-many → `ProjectClass` via association table `workflow_log_to_pclass`

**Association table:** `workflow_log_to_pclass`

- `workflow_log_id` INTEGER FK → `workflow_log.id`
- `project_class_id` INTEGER FK → `project_classes.id`

**Files to update:**

- `app/models/__init__.py` — add `from .workflow_log import *`
- `app/models/associations.py` — add the association table, OR define it inside `workflow_log.py`

### Migration

Create Alembic migration using `flask db migrate` after adding the model, then review and
adjust the generated script. Migration should create:

- Table `workflow_log`
- Table `workflow_log_to_pclass`

---

## TASK 2: Size Estimate [x]

### Calculation

Per `WorkflowLogEntry` row (InnoDB estimates):

| Field        | Size (bytes) |
|--------------|--------------|
| id           | 4            |
| timestamp    | 8            |
| initiator_id | 4            |
| endpoint     | ~100 avg     |
| summary      | ~500 avg     |
| Row overhead | ~50          |
| **Total**    | **~666**     |

Per row in `workflow_log_to_pclass`:

| Field            | Size (bytes) |
|------------------|--------------|
| workflow_log_id  | 4            |
| project_class_id | 4            |
| B-tree overhead  | ~20          |
| **Total**        | **~28**      |

Assuming 1.5 project classes per log entry on average:

- Total per log entry ≈ 666 + 1.5 × 28 ≈ 708 bytes

**50 MB capacity:** 52,428,800 ÷ 708 ≈ **74,050 rows**

**Default retention:** 50,000 rows (comfortably within 50 MB budget)

---

## TASK 3: Prune Celery Task [x]

**File:** `app/tasks/workflow_log.py` (new)

```python
def register_workflow_log_tasks(celery):
    @celery.task(bind=True)
    def prune_workflow_log(self, max_rows=50000):
        # Count total rows
        # If count > max_rows, delete oldest (count - max_rows) rows by timestamp
        ...
```

**Strategy:** Delete by selecting the `(count - max_rows)` oldest rows using a subquery
on `timestamp` ordering. Use bulk delete for efficiency.

**Files to update:**

- `app/tasks/__init__.py` — add `from .workflow_log import register_workflow_log_tasks`
- `app/admin/forms.py` — add `("app.tasks.workflow_log.prune_workflow_log", "Prune workflow log")` to `tasks_available`

---

## TASK 4+5: Wrapper Function `log_db_commit()` [x]

**File:** `app/shared/workflow_logging.py` (new)

### Design

```python
def log_db_commit(
        summary: str,
        *,
        user=None,  # User instance, user id (int), or None
        project_classes=None,  # ProjectClass, list of ProjectClass, or None
        endpoint: str = None,  # explicit name; auto-detected from request context if None
        _commit: bool = True,  # if False, add log entry but don't commit (for callers that manage their own commit)
):
    """
    Create a WorkflowLogEntry and commit the session.

    For Flask route handlers: if endpoint is None, uses flask.request.endpoint.
    For Celery tasks: pass endpoint=current_task.name or a descriptive string.
    """
```

### Auto-detection logic

1. If `endpoint` is None and we're inside a Flask request context → use `flask.request.endpoint`
2. If `endpoint` is None and there's a current Celery task → use `celery.current_task.name`
3. Otherwise → use `"unknown"`

### Normalisation helpers

- Accept `user` as `User` instance, `int` id, or `None`
- Accept `project_classes` as single instance, list, or `None`

### Refactoring plan (Task 5)

The full replacement of `db.session.commit()` calls is a large task that will be done
incrementally over multiple sessions. Priority order:

1. **Marking workflow** — `app/tasks/marking.py` (high-value, recently changed)
2. **Submission/rollover** — `app/tasks/rollover.py`, `app/tasks/selecting.py`
3. **Student/faculty operations** — routes in `app/student/`, `app/faculty/`
4. **Admin operations** — routes in `app/admin/`
5. **All remaining** — systematic pass through remaining tasks and routes

For each replacement:

- Identify what User, ProjectClass/ProjectClassConfig context is available
- Replace `db.session.commit()` with `log_db_commit(summary, user=..., project_classes=..., endpoint=...)`
- If no meaningful context is available, call with just `summary`

**Note:** The `_commit=False` variant allows callers to add a log entry without committing,
useful when the caller has its own `try/except/rollback` pattern and manages the commit itself.
In that case, `log_db_commit(..., _commit=False)` adds the entry to the session, and the
caller's subsequent `db.session.commit()` persists both.

---

## TASK 6: Workflow Log Inspector [x]

### Routes in `app/admin/system.py`

```python
@admin.route("/workflow_log")
@roles_required("root")
def workflow_log():
    # Filtering: pclass_filter, tenant_filter (stored in session)
    ...


@limiter.exempt
@admin.route("/workflow_log_ajax", methods=["POST"])
@roles_required("root")
def workflow_log_ajax():
    # ServerSideSQLHandler columns:
    # - user: initiator name (searchable)
    # - endpoint: endpoint field (searchable, orderable)
    # - project_classes: (searchable via M2M)
    # - timestamp: (orderable)
    # - summary: (searchable)
    # - menu: actions
    ...
```

### Template: `app/templates/admin/workflow_log.html`

- Extends `base_app.html`
- Uses `datatables.html` macros
- Filter controls (project class dropdown, tenant dropdown) similar to `reports/workload`
- DataTables table with columns: User, Endpoint, Project classes, Timestamp, Summary

### AJAX formatter: `app/ajax/site/workflow_log.py`

```python
def workflow_log_data(entries):
    # Format each WorkflowLogEntry as a dict for DataTables
    ...
```

**Update:** `app/ajax/site/__init__.py` — add `from .workflow_log import workflow_log_data`

---

## TASK 7: Export to CSV/Excel [x]

### Export task in `app/tasks/workflow_log.py`

```python
@celery.task(bind=True, default_retry_delay=30)
def export_workflow_log(self, user_id, pclass_id=None, tenant_id=None):
    # Query WorkflowLogEntry rows (filtered by pclass/tenant if provided)
    # Build pandas DataFrame
    # Export to .xlsx using ScratchFileManager
    # Upload as GeneratedAsset
    # Create DownloadCentreItem for the user
    # Post notification message to user
    ...
```

### Export route in `app/admin/system.py`

```python
@admin.route("/workflow_log_export")
@roles_required("root")
def workflow_log_export():
    # Trigger export_workflow_log.delay(current_user.id, pclass_id=..., tenant_id=...)
    # Flash message pointing to Download Centre
    # Redirect back to workflow_log
    ...
```

### Template update

Add export button to `app/templates/admin/workflow_log.html`:

```html
<a href="{{ url_for('admin.workflow_log_export', ...) }}" class="btn btn-outline-secondary">
    <i class="fas fa-file-excel fa-fw"></i> Export to Excel
</a>
```

---

## TASK 8: Menu Entry [x]

**File:** `app/templates/base.html`

Add to the `{% if is_root %}` block inside Site management dropdown, after "Background tasks":

```html
<a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.workflow_log') }}">
    <i class="fas fa-list-alt fa-fw"></i> Workflow log...
</a>
```

---

## Implementation Status

| Task | Description                    | Status | Notes                            |
|------|--------------------------------|--------|----------------------------------|
| 1    | Database model                 | [x]    | app/models/workflow_log.py       |
| 2    | Size estimate                  | [x]    | ~74k rows in 50 MB; default 50k  |
| 3    | Prune Celery task              | [x]    | app/tasks/workflow_log.py        |
| 4+5  | log_db_commit() wrapper + plan | [x]    | app/shared/workflow_logging.py   |
| 6    | Inspector route + UI           | [x]    | admin.workflow_log + template    |
| 7    | Export to CSV/Excel            | [x]    | admin.workflow_log_export + task |
| 8    | Menu entry                     | [x]    | base.html Site management menu   |

---

## Files Created / Modified

### New files

- `.plans/workflow_log_plan.md` (this file)
- `app/models/workflow_log.py`
- `app/tasks/workflow_log.py`
- `app/shared/workflow_logging.py`
- `app/ajax/site/workflow_log.py`
- `app/templates/admin/workflow_log.html`
- `migrations/versions/<hash>_add_workflow_log_model.py`

### Modified files

- `app/models/__init__.py` — add workflow_log import
- `app/tasks/__init__.py` — register workflow log tasks
- `app/admin/system.py` — add inspector + export routes
- `app/admin/forms.py` — add prune task to task list
- `app/ajax/site/__init__.py` — add workflow_log_data export
- `app/templates/base.html` — add menu entry
