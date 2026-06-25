# Phase 6 — Flask routes and forms

## Prerequisites

Phases 1–5 must be complete.

## Context

This phase adds the Flask routes that power the Cloud backup tab, including:
- The main `cloud_backup` view (status + run history).
- The AJAX endpoint for the run-history DataTable.
- The "run now" form that dispatches `backup_object_stores` immediately.
- The configuration save form that updates provider, root folder, and backup account.
- The restore confirmation views that dispatch restore tasks.

It also adds the two new WTForms form classes to `app/admin/forms.py`.

**Account/folder change reset:** When the backup account (`owner_id` on the
`DatabaseSchedulerEntry`) or the root folder (`OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER`
from config) is changed via the UI, all existing `ObjectStoreBackupRecord` rows must be
deleted and the `DatabaseSchedulerEntry.owner_id` updated.  This is a destructive
action and requires a separate confirmation route.

## Files to read before writing any code

1. `app/admin/system.py` lines 1–50 and 1273–1855 — `backups_overview`,
   `manage_backups`, `manage_backups_ajax`, `manual_backup` routes.  Study the
   `manual_backup` dispatch chain carefully.
2. `app/admin/forms.py` lines 1–40 and 1057–1070 — existing backup forms; note the
   `QuerySelectField` / `QuerySelectMultipleField` patterns.
3. `app/admin/utilities.py` lines 1–30 and 526–645 — `download_backup`, `edit_backup`
   patterns.
4. `app/ajax/site/backups.py` — AJAX row formatter pattern.
5. `app/task_queue/background_task.py` — `register_task()` and `progress_update()`.
6. `app/tasks/object_store_backup.py` (post Phase 5) — task names for dispatch.
7. `app/models/utilities.py` (post Phase 2) — `ObjectStoreBackupRecord` fields.
8. `app/models/scheduler.py` — `DatabaseSchedulerEntry` fields.
9. `app/models/__init__.py` — confirm `DatabaseSchedulerEntry` is exported.
10. `app/shared/cloud_object_store/bucket_types.py` — bucket-type constants.

## New form classes in `app/admin/forms.py`

### `CloudBackupConfigForm`

```python
class CloudBackupConfigForm(Form):
    """Edit cloud backup configuration: provider, backup account, root folder."""

    backup_account = QuerySelectField(
        "Backup account",
        query_factory=lambda: User.query.filter_by(box_token_valid=True).order_by(User.last_name),
        get_label=lambda u: f"{u.name} ({u.email})",
        allow_blank=True,
        blank_text="— not configured —",
        description=(
            "The administrator account whose Box credentials will be used for "
            "scheduled backups.  The account must have completed Box OAuth authorisation."
        ),
    )

    root_folder_id = StringField(
        "Root folder ID",
        validators=[
            DataRequired(message="Please enter a Box folder ID"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
        description=(
            "The Box folder ID that serves as the backup root.  All per-bucket "
            "subfolders will be created inside this folder.  Find the folder ID "
            "in the Box URL when viewing the folder: .../folder/<id>"
        ),
    )

    save_config = SubmitField("Save configuration")
```

### `CloudBackupRestoreForm`

```python
class CloudBackupRestoreForm(Form):
    """Confirm a restore operation."""

    SKIP_EXISTING  = 0
    OVERWRITE_ALL  = 1

    restore_mode = RadioField(
        "Restore mode",
        choices=[
            (0, "Skip existing objects"),
            (1, "Overwrite all objects"),
        ],
        coerce=int,
        default=0,
    )

    confirm = SubmitField("Confirm restore")
```

## New routes

All new routes go in `app/admin/system.py` (unless it becomes unwieldy, in which case
create `app/admin/backup_cloud.py` following the existing blueprint pattern).  All
routes are decorated with `@roles_required("root")`.

### `GET  /cloud_backup`  →  `cloud_backup`

Template context:

```python
# Most recent run_id group
latest_run_id = (
    db.session.query(ObjectStoreBackupRecord.run_id)
    .order_by(ObjectStoreBackupRecord.timestamp.desc())
    .limit(1)
    .scalar()
)
latest_records = (
    db.session.query(ObjectStoreBackupRecord)
    .filter_by(run_id=latest_run_id)
    .all()
    if latest_run_id else []
)

# Schedule entry
schedule_entry = (
    db.session.query(DatabaseSchedulerEntry)
    .filter_by(name="object-store-cloud-backup")
    .first()
)

# Config form prepopulated from schedule_entry
form = CloudBackupConfigForm(obj=schedule_entry)
# Pre-fill root_folder_id from app.config (not from DB)
if not form.root_folder_id.data:
    form.root_folder_id.data = current_app.config.get(
        "OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER", ""
    )

# Alert badge: True if latest run had any FAILED or PARTIAL records
cloud_backup_alert = any(
    r.status in (ObjectStoreBackupRecord.FAILED, ObjectStoreBackupRecord.PARTIAL)
    for r in latest_records
)

return render_template(
    "admin/backup_dashboard/cloud_backup.html",
    pane="cloud",
    form=form,
    latest_records=latest_records,
    schedule_entry=schedule_entry,
    cloud_backup_alert=cloud_backup_alert,
)
```

### `POST /cloud_backup`  →  `cloud_backup` (form save)

Handle `CloudBackupConfigForm` POST.

**Account or folder change detection:**

```python
old_owner_id = schedule_entry.owner_id if schedule_entry else None
new_owner = form.backup_account.data   # User ORM row or None
new_owner_id = new_owner.id if new_owner else None
new_folder = form.root_folder_id.data.strip()
old_folder = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER", "")

account_changed = (new_owner_id != old_owner_id)
folder_changed  = (new_folder != old_folder)

if account_changed or folder_changed:
    # Redirect to confirmation route before saving
    session["pending_cloud_config"] = {
        "owner_id":  new_owner_id,
        "root_folder": new_folder,
    }
    return redirect(url_for("admin.confirm_cloud_backup_config_change"))
```

If unchanged, just update `schedule_entry.owner_id` and `db.session.commit()`.  Emit a
flash message.  For the root folder, emit a warning flash that it must be updated in
`instance/local.py` as well (since it lives in config, not the DB).

### `GET  /confirm_cloud_backup_config_change`  →  `confirm_cloud_backup_config_change`

Display a confirmation page explaining:
- The backup account / root folder is being changed.
- All existing `ObjectStoreBackupRecord` rows will be deleted.
- The next scheduled backup will start fresh.

Render a simple confirmation template with Confirm / Cancel buttons.

### `POST /confirm_cloud_backup_config_change`  →  `apply_cloud_backup_config_change`

```python
pending = session.pop("pending_cloud_config", None)
if pending is None:
    flash("No pending configuration change.", "warning")
    return redirect(url_for("admin.cloud_backup"))

# Delete all existing backup records
db.session.query(ObjectStoreBackupRecord).delete()

# Update schedule entry
entry = (
    db.session.query(DatabaseSchedulerEntry)
    .filter_by(name="object-store-cloud-backup")
    .first()
)
if entry:
    entry.owner_id = pending["owner_id"]

db.session.commit()

flash(
    "Cloud backup configuration updated.  All previous backup records have been cleared.  "
    f"Note: the root folder ID must also be updated in instance/local.py to take effect.",
    "warning",
)
return redirect(url_for("admin.cloud_backup"))
```

### `POST /cloud_backup_ajax`  →  `cloud_backup_ajax`

Server-side DataTable endpoint.  Serves rows of `ObjectStoreBackupRecord` grouped by
`run_id`.  Use the `ServerSideSQLHandler` pattern from `manage_backups_ajax`.

The grouping is non-trivial for a standard server-side handler.  A pragmatic approach:
query all distinct `run_id` values ordered by `MAX(timestamp) DESC`, then for each
`run_id` in the current page slice query its constituent records.  Assemble the row
data by calling the formatter function from `app/ajax/site/cloud_backups.py` (new file,
Phase 7).

Alternatively, query at the per-record level ordered by `timestamp DESC` and let the
template handle grouping — simpler to implement with `ServerSideSQLHandler` but
produces one row per bucket rather than per run.  **Use the per-record approach for
Phase 6** with a note that run-level grouping can be added in a follow-up.  The run
history table in Phase 7 will visually group rows by `run_id` using a DataTables
`rowGroup` extension or simple CSS class matching.

Column set for per-record DataTable:

| Column name | Source field |
|---|---|
| `timestamp` | `ObjectStoreBackupRecord.timestamp` |
| `run_id` | `ObjectStoreBackupRecord.run_id` (truncated, for grouping) |
| `bucket` | `ObjectStoreBackupRecord.bucket_label` |
| `total` | `object_count_total` |
| `uploaded` | `object_count_uploaded` |
| `errors` | `object_count_error` |
| `bytes` | `bytes_uploaded` |
| `status` | `status` |
| `menu` | action buttons |

### `GET+POST /cloud_backup_run_now`  →  `cloud_backup_run_now`

Dispatch `backup_object_stores` immediately as a user-visible task.

```python
schedule_entry = ...  # load from DB
owner_id = schedule_entry.owner_id if schedule_entry else None

task_id = register_task("Cloud backup", owner=current_user,
                         description="Manual object-store cloud backup")
celery = current_app.extensions["celery"]
backup_task = celery.tasks["app.tasks.object_store_backup.backup_object_stores"]
init  = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

seq = chain(
    init.si(task_id, "Cloud backup"),
    backup_task.si(owner_id=owner_id),
    final.si(task_id, "Cloud backup", current_user.id, notify=True),
).on_error(error.si(task_id, "Cloud backup", current_user.id))

seq.apply_async(task_id=task_id)
return redirect(url_for("admin.cloud_backup"))
```

### `GET+POST /confirm_cloud_backup_restore/<int:record_id>`  →  `cloud_backup_restore`

Display `CloudBackupRestoreForm` with scope = single bucket (from `record_id`).
On POST, dispatch `restore_object_store_bucket`:

```python
task_id = register_task("Restore cloud backup", owner=current_user, description=...)
celery = current_app.extensions["celery"]
restore_task = celery.tasks["app.tasks.object_store_backup.restore_object_store_bucket"]
# ... chain as above
restore_task.si(
    task_id=task_id,
    record_id=record_id,
    overwrite=(form.restore_mode.data == CloudBackupRestoreForm.OVERWRITE_ALL),
    owner_id=schedule_entry.owner_id,
)
```

### `GET+POST /confirm_cloud_backup_restore_run/<run_id>`  →  `cloud_backup_restore_run`

Same pattern but dispatches `restore_all_object_store_buckets` with `run_id`.

## Out of scope for this phase

- Template files (`cloud_backup.html`, AJAX formatter) — Phase 7.
- `nav.html` pill and overview strip — Phase 8.

## Verification

```bash
grep -n "cloud_backup" app/admin/system.py | head -30
grep -n "CloudBackupConfigForm"  app/admin/forms.py
grep -n "CloudBackupRestoreForm" app/admin/forms.py
grep -n "confirm_cloud_backup_config_change" app/admin/system.py
grep -n "ObjectStoreBackupRecord" app/admin/system.py
```

Confirm that:
- All new routes are registered under the correct Blueprint.
- `@roles_required("root")` is present on every new route.
- `session["pending_cloud_config"]` is used for the change-detection flow.
- No `log_db_commit` calls appear in this file for the new routes — use plain
  `db.session.commit()` for backup-infrastructure changes.
