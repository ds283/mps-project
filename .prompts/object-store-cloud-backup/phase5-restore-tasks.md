# Phase 5 — Restore tasks

## Prerequisite

Phase 3 (backup task) must be complete.  Phase 4 is independent of this phase.

## Context

This phase adds the user-initiated restore tasks to `app/tasks/object_store_backup.py`.
Restore is always user-initiated (never a Beat task) and follows the `TaskRecord` /
`register_task` / `mark_user_task_started` / `mark_user_task_ended` chain pattern used
by `manual_backup`.

Two tasks are needed:

- `restore_object_store_bucket` — restore a single bucket from a specific
  `ObjectStoreBackupRecord`.
- `restore_all_object_store_buckets` — restore all buckets from a specific `run_id` by
  sequentially calling the single-bucket logic for each record in the run.

## Files to read before writing any code

1. `app/tasks/object_store_backup.py` (post Phase 3) — extend this file.
2. `app/tasks/backup.py` — the `manual_backup` route's task-dispatch pattern shows
   `mark_user_task_started` / `mark_user_task_ended` / `mark_user_task_failed`.  Read
   lines around the `manual_backup` function.
3. `app/task_queue/background_task.py` — `register_task()`, `progress_update()`.
4. `app/shared/cloud_storage/base.py` — `CloudStorageLocation` API.
5. `app/shared/cloud_object_store/base.py` — `ObjectStore.put()` signature and return
   value (returns a `Mapping` containing `nonce`, `encrypted_size`, `compressed_size`).
6. `app/models/utilities.py` — `ObjectStoreBackupRecord` (post Phase 2) and
   `BackupRecord`.
7. `app/models/assets.py` — `SubmittedAsset`, `GeneratedAsset`, `TemporaryAsset`.
8. `app/models/__init__.py` — confirm which models are exported.

## Changes to `app/tasks/object_store_backup.py`

Add the following inside the `register_object_store_backup_tasks(celery)` factory,
alongside the existing `backup_object_stores` task.

### 5.1  Module-level helper: `_update_asset_nonce`

Add outside the factory (module level), alongside the other helper functions:

```python
def _update_asset_nonce(bucket_type: int, key: str, new_nonce_b64: str) -> bool:
    """
    Write *new_nonce_b64* to the ORM row for *key* in *bucket_type*.
    Also clears the `lost` flag on the row.
    Returns True if a row was found and updated, False if the key is orphaned.
    """
    model_classes = BUCKET_MODEL_MAP.get(bucket_type, [])
    for cls in model_classes:
        row = db.session.query(cls).filter_by(unique_name=key).first()
        if row is not None:
            row.nonce = new_nonce_b64
            row.lost = False
            db.session.commit()
            return True

    # BackupRecord special case (unique_name field is called `key` on BackupRecord)
    if bucket_type == buckets.BACKUP_BUCKET:
        row = db.session.query(BackupRecord).filter_by(key=key).first()
        if row is not None:
            row.nonce = new_nonce_b64
            db.session.commit()
            return True

    return False   # orphaned key — no ORM row found
```

### 5.2  Module-level helper: `_clear_lost_flags`

```python
def _clear_lost_flags(bucket_type: int, restored_keys: Set[str]) -> int:
    """
    For each key in *restored_keys*, clear the `lost` flag on any ORM row
    that refers to it.  Returns the count of rows updated.
    """
    updated = 0
    model_classes = BUCKET_MODEL_MAP.get(bucket_type, [])
    for cls in model_classes:
        rows = (
            db.session.query(cls)
            .filter(cls.unique_name.in_(restored_keys))
            .filter(cls.lost.is_(True))
            .all()
        )
        for row in rows:
            row.lost = False
            updated += 1
    if updated:
        db.session.commit()
    return updated
```

### 5.3  `restore_object_store_bucket` task

```python
@celery.task(bind=True, default_retry_delay=30)
def restore_object_store_bucket(
    self,
    task_id: str,
    record_id: int,
    overwrite: bool = False,
    owner_id: int = None,
):
```

Logic:

1. `progress_update(task_id, TaskRecord.RUNNING, 5, "Loading backup record...", autocommit=True)`

2. Load `record = db.session.get(ObjectStoreBackupRecord, record_id)`.
   If None, `progress_update(..., FAILED, 100, "Backup record not found")` and return.

3. Load `owner_user = db.session.get(User, owner_id)`.  Validate tokens.

4. Load `object_store = current_app.config["OBJECT_STORAGE_BUCKETS"].get(record.bucket_type)`.
   If None, fail with a descriptive message.

5. Build `location = CloudStorageLocation.from_user(...)` using `record.provider_name`,
   `owner_user`, and the configured root folder.

6. `progress_update(..., RUNNING, 15, f"Listing cloud backup for {record.bucket_label}...", autocommit=True)`

7. `cloud_items = {item.name: item for item in location.list_folder(record.cloud_folder_ref)}`

8. `existing_keys = object_store.list_keys(audit_data="cloud_restore")`

9. **Restore loop:**
   ```python
   restored = skipped = errors = orphaned = 0
   restored_keys = set()

   filenames = [n for n in cloud_items if not n.endswith(".meta")]
   total = len(filenames)

   for i, filename in enumerate(filenames):
       key = filename.replace("__", "/")   # reverse _sanitize_key
       cloud_item = cloud_items[filename]

       if not overwrite and key in existing_keys:
           skipped += 1
           continue

       try:
           data = location.download_file(cloud_item.ref)
           result = object_store.put(
               key,
               audit_data="cloud_restore",
               data=data,
               no_encryption=False,
           )
           # Re-encryption returns a new nonce; update the ORM row
           new_nonce = result.get("nonce") if result else None
           if new_nonce:
               found = _update_asset_nonce(record.bucket_type, key, new_nonce)
               if not found:
                   orphaned += 1
                   current_app.logger.warning(
                       "cloud_restore: key %s has no ORM row in bucket %s",
                       key, record.bucket_label,
                   )
           restored_keys.add(key)
           restored += 1
       except Exception as exc:
           errors += 1
           current_app.logger.warning(
               "cloud_restore: error restoring key %s: %s", key, exc
           )

       # Update progress every 50 objects
       if i % 50 == 0:
           pct = 15 + int(80 * i / max(total, 1))
           progress_update(
               task_id, TaskRecord.RUNNING, pct,
               f"Restoring {record.bucket_label}: {i}/{total} objects...",
               autocommit=True,
           )
   ```

10. `_clear_lost_flags(record.bucket_type, restored_keys)`

11. Handle auth errors: wrap the loop body in a try/except that calls
    `location.handle_auth_error(exc, notify_user=owner_user)` and fails the task
    if True.

12. Summary message:
    ```python
    msg = (
        f"Restore complete: {record.bucket_label} — "
        f"{restored} restored, {skipped} skipped, {orphaned} orphaned, {errors} errors."
    )
    progress_update(task_id, TaskRecord.SUCCESS, 100, msg, autocommit=True)
    ```

### 5.4  `restore_all_object_store_buckets` task

```python
@celery.task(bind=True, default_retry_delay=30)
def restore_all_object_store_buckets(
    self,
    task_id: str,
    run_id: str,
    overwrite: bool = False,
    owner_id: int = None,
):
```

Logic:

1. `progress_update(task_id, TaskRecord.RUNNING, 5, "Loading run records...", autocommit=True)`

2. ```python
   records = (
       db.session.query(ObjectStoreBackupRecord)
       .filter_by(run_id=run_id)
       .filter(ObjectStoreBackupRecord.status.in_([
           ObjectStoreBackupRecord.SUCCESS,
           ObjectStoreBackupRecord.PARTIAL,
       ]))
       .all()
   )
   ```
   If empty, fail with "No completed backup records found for this run."

3. Load `owner_user` and validate as above.

4. Loop over each `record`, building a `location`, iterating the cloud folder, and
   calling the same restore logic as in `restore_object_store_bucket` (extract
   the inner loop into a shared module-level function `_do_bucket_restore(...)` to
   avoid duplication).

5. Update progress proportionally across all records in the run.

6. Emit a final summary `progress_update(..., SUCCESS, 100, ...)`.

**Note:** Refactor `restore_object_store_bucket` to call `_do_bucket_restore` as well,
rather than duplicating the loop logic.

### 5.5  Return value from the factory

Update the `return` statement at the end of `register_object_store_backup_tasks` to
include the new tasks:

```python
return (
    backup_object_stores,
    restore_object_store_bucket,
    restore_all_object_store_buckets,
)
```

## Out of scope for this phase

- Flask routes that dispatch these tasks — Phase 6.
- Template changes — Phases 7 and 8.

## Verification

```bash
grep -n "def restore_object_store_bucket" app/tasks/object_store_backup.py
grep -n "def restore_all_object_store_buckets" app/tasks/object_store_backup.py
grep -n "_update_asset_nonce" app/tasks/object_store_backup.py
grep -n "_clear_lost_flags" app/tasks/object_store_backup.py
grep -n "_do_bucket_restore" app/tasks/object_store_backup.py
```

Confirm that `log_db_commit` is not used anywhere in this file — `db.session.commit()`
only.  Confirm that `progress_update` calls always pass `autocommit=True`.
