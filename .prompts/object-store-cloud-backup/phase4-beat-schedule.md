# Phase 4 — Beat schedule registration and configuration keys

## Prerequisite

Phase 3 (backup task) must be complete.

## Context

This phase registers the scheduled Beat entry for `backup_object_stores` and adds the
required configuration keys to `instance/local.py`.  It follows the established pattern
from `ensure_box_token_schedule` in `initdb.py`.

## Files to read before writing any code

1. `initdb.py` lines 1–40 and 614–665 — the `ensure_box_token_schedule` canonical
   pattern for idempotent Beat registration.  Read the full function.
2. `app/models/scheduler.py` — `DatabaseSchedulerEntry`, `CrontabSchedule`,
   `IntervalSchedule` ORM models and their fields.
3. `instance/local.py` — existing config pattern; specifically how
   `OBJECT_STORAGE_BUCKETS`, `BACKUP_IS_LIVE`, and the Box-related keys are declared.
4. `serve.py` (or whatever startup file calls `ensure_*_schedule`) — to identify where
   to add the new `ensure_object_store_backup_schedule(app)` call.

## Changes required

### 4.1  New function in `initdb.py`

Add `ensure_object_store_backup_schedule(app)` immediately after
`ensure_box_token_schedule`.

```python
def ensure_object_store_backup_schedule(app) -> None:
    """
    Idempotently register the DatabaseSchedulerEntry for the object-store
    cloud backup Beat task.

    Does nothing if:
    - OBJECT_STORE_BACKUP_ENABLED is False or absent in app.config.
    - A DatabaseSchedulerEntry named "object-store-cloud-backup" already exists.
    """
    with app.app_context():
        if not app.config.get("OBJECT_STORE_BACKUP_ENABLED", False):
            return

        existing = (
            db.session.query(DatabaseSchedulerEntry)
            .filter_by(name="object-store-cloud-backup")
            .first()
        )
        if existing is not None:
            return

        # Daily at 03:30 — offset from the DB backup at 02:00 to avoid I/O contention
        crontab = (
            db.session.query(CrontabSchedule)
            .filter_by(
                minute="30", hour="3",
                day_of_week="*", day_of_month="*", month_of_year="*",
            )
            .first()
        )
        if crontab is None:
            crontab = CrontabSchedule(
                minute="30", hour="3",
                day_of_week="*", day_of_month="*", month_of_year="*",
            )
            db.session.add(crontab)
            db.session.flush()

        entry = DatabaseSchedulerEntry(
            name="object-store-cloud-backup",
            task="app.tasks.object_store_backup.backup_object_stores",
            interval_id=None,
            crontab_id=crontab.id,
            args=[],
            kwargs={},
            queue="default",
            exchange=None,
            routing_key=None,
            expires=None,
            enabled=True,
            last_run_at=datetime.now(),
            total_run_count=0,
            owner_id=None,   # Set post-deploy via admin UI (Phase 6)
        )
        db.session.add(entry)
        db.session.commit()
```

### 4.2  Call the new function at startup

In the same startup file where `ensure_box_token_schedule(app)` is called, add:

```python
ensure_object_store_backup_schedule(app)
```

immediately after the existing `ensure_box_token_schedule` call.

### 4.3  New configuration keys in `instance/local.py`

Add the following block near the existing object-storage configuration:

```python
# ── Object-store cloud backup ────────────────────────────────────────────────

# Set to True to enable the scheduled cloud backup of MinIO object buckets.
OBJECT_STORE_BACKUP_ENABLED = False   # set to True after configuring below

# Provider name.  Must match a registered CloudStorageProvider (currently only "box").
OBJECT_STORE_CLOUD_BACKUP_PROVIDER = "box"

# Box folder ID that serves as the backup root.
# All per-bucket subfolders will be created under this folder.
# Replace with the actual Box folder ID from your deployment.
OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER = ""   # e.g. "123456789012"

# Integer bucket-type constants to include in the cloud backup.
# Import from app.shared.cloud_object_store.bucket_types if needed at config time.
# THUMBNAILS_BUCKET (8) is excluded — thumbnails are regeneratable.
OBJECT_STORE_CLOUD_BACKUP_BUCKETS = [
    0,   # ASSETS_BUCKET
    3,   # BACKUP_BUCKET
    5,   # FEEDBACK_BUCKET
    6,   # PROJECT_BUCKET
    7,   # SUPERVISION_ASSETS_BUCKET
]

# Number of days to retain tombstoned objects in the cloud backup before pruning.
OBJECT_STORE_BACKUP_TOMBSTONE_TTL_DAYS = 90
```

**Note:** `OBJECT_STORE_BACKUP_ENABLED` defaults to `False` so the schedule entry is
created but does not fire until explicitly enabled and the `owner_id` is set via the
admin UI (Phase 6).

## Out of scope for this phase

- Restore tasks — Phase 5.
- Flask routes or template changes — Phases 6–8.
- The `owner_id` value on the `DatabaseSchedulerEntry` — set via the admin UI in Phase 6.

## Verification

```bash
grep -n "ensure_object_store_backup_schedule" initdb.py
grep -n "object-store-cloud-backup" initdb.py
grep -n "OBJECT_STORE_BACKUP_ENABLED" instance/local.py
grep -n "OBJECT_STORE_CLOUD_BACKUP_BUCKETS" instance/local.py
grep -n "OBJECT_STORE_BACKUP_TOMBSTONE_TTL_DAYS" instance/local.py
```

All should return at least one match.

Also confirm that starting the application with `OBJECT_STORE_BACKUP_ENABLED = False`
does not raise any errors and that the schedule entry is absent from the database
in that configuration.  With `OBJECT_STORE_BACKUP_ENABLED = True` (and a test
database), the entry should be created on first startup and not duplicated on
subsequent startups.
