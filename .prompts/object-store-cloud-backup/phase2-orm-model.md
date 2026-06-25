# Phase 2 — ORM model: `ObjectStoreBackupRecord` and Alembic migration

## Prerequisite

Phase 1 must be complete before starting this phase.

## Context

The object-store cloud backup feature needs a persistent record of each backup run so
that the restore UI can enumerate available snapshots and administrators can verify
backup health.  One `ObjectStoreBackupRecord` row is created per bucket per Beat
execution.  All rows from the same execution share a `run_id` UUID.

## Files to read before writing any code

1. `app/models/utilities.py` — where `BackupRecord`, `BackupConfiguration`, and
   related models live.  This file is the target for the new model.
2. `app/models/model_mixins.py` lines 933–1100 — `BaseAssetMixin` and related mixins
   (for pattern reference only; the new model does not use these mixins).
3. `app/models/__init__.py` — to see how models are exported and registered.
4. `app/shared/cloud_object_store/bucket_types.py` — the integer bucket-type constants
   that will be stored in `ObjectStoreBackupRecord.bucket_type`.
5. Any existing Alembic migration in `migrations/versions/` that added a table recently
   — use it as a pattern for the new migration file.

## Changes required

### 2.1  New model class in `app/models/utilities.py`

Add `ObjectStoreBackupRecord` after the existing `BackupRecord` class.

```python
class ObjectStoreBackupRecord(db.Model):
    """
    Tracks a single cloud-storage backup run for a single object-store bucket.
    One row per (run, bucket).  Rows from the same Beat execution share run_id.
    """
    __tablename__ = "object_store_backup_records"

    # ── Status constants ──────────────────────────────────────────────────────
    RUNNING = 0
    SUCCESS = 1
    FAILED  = 2
    PARTIAL = 3   # completed but with per-object errors

    STATUS_LABELS = {
        RUNNING: "Running",
        SUCCESS: "Success",
        FAILED:  "Failed",
        PARTIAL: "Partial",
    }

    # ── Primary key ───────────────────────────────────────────────────────────
    id = db.Column(db.Integer(), primary_key=True)

    # ── Run grouping ──────────────────────────────────────────────────────────
    # UUID string shared by all rows from the same Beat execution
    run_id = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=False, index=True)

    # ── Timing ───────────────────────────────────────────────────────────────
    timestamp   = db.Column(db.DateTime(), nullable=False,
                            default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime(), nullable=True)

    # ── Which bucket ─────────────────────────────────────────────────────────
    # Integer from cloud_object_store/bucket_types.py
    bucket_type  = db.Column(db.Integer(), nullable=False, index=True)
    bucket_label = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=True)
    # Human-readable label, e.g. "assets", "backup", "feedback"

    # ── Cloud location ────────────────────────────────────────────────────────
    provider_name    = db.Column(db.String(DEFAULT_STRING_LENGTH),
                                 nullable=False, default="box")
    cloud_folder_ref = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=True)
    # Provider-specific folder ID/ref for the objects/ subfolder of this bucket

    # ── Outcome ───────────────────────────────────────────────────────────────
    status = db.Column(db.Integer(), nullable=False, default=RUNNING)

    # ── Statistics ────────────────────────────────────────────────────────────
    object_count_total    = db.Column(db.Integer(), nullable=True)
    object_count_uploaded = db.Column(db.Integer(), nullable=True)
    object_count_skipped  = db.Column(db.Integer(), nullable=True)
    object_count_deleted  = db.Column(db.Integer(), nullable=True)
    # objects tombstoned this run (removed from MinIO since last backup)
    object_count_orphaned = db.Column(db.Integer(), nullable=True)
    # objects in bucket with no ORM asset row (nonce lookup failed)
    object_count_error    = db.Column(db.Integer(), nullable=True)

    bytes_uploaded = db.Column(db.BigInteger(), nullable=True)

    # ── Error detail ──────────────────────────────────────────────────────────
    # Truncated log of per-object errors; max ~4000 chars
    error_detail = db.Column(db.Text(), nullable=True)

    # ── Owner ─────────────────────────────────────────────────────────────────
    # Admin user whose Box tokens were used for this run
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    owner    = db.relationship("User", foreign_keys=[owner_id])

    # ── Upload mode ───────────────────────────────────────────────────────────
    # 0 = decrypted upload (plaintext to cloud); 1 = raw ciphertext
    UPLOAD_MODE_DECRYPTED  = 0
    UPLOAD_MODE_CIPHERTEXT = 1
    upload_mode = db.Column(db.Integer(), nullable=False,
                            default=UPLOAD_MODE_DECRYPTED)

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, "Unknown")

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.finished_at and self.timestamp:
            return (self.finished_at - self.timestamp).total_seconds()
        return None

    @property
    def readable_bytes_uploaded(self) -> str:
        """Human-readable upload volume, e.g. '34.2 MB'."""
        if self.bytes_uploaded is None:
            return "—"
        from ..shared.formatters import format_size
        return format_size(self.bytes_uploaded)
```

Import `Optional` from `typing` at the top of `utilities.py` if not already present.
Import `datetime` from `datetime` if not already present.

### 2.2  Export the new model

In `app/models/__init__.py`, add `ObjectStoreBackupRecord` to the imports from
`utilities` (or wherever the `__init__` exports model names).  Follow the existing
pattern for `BackupRecord`.

### 2.3  Alembic migration

Generate a new migration file in `migrations/versions/`.  The migration must:

- Create the `object_store_backup_records` table with all columns listed above.
- Add an index on `run_id` and `bucket_type` (already declared with `index=True`
  on the columns, so the autogenerate will include them).
- Add the foreign key to `users.id` for `owner_id`.
- Set a suitable revision message, e.g. `"add ObjectStoreBackupRecord table"`.

Use `flask db migrate -m "add ObjectStoreBackupRecord table"` to autogenerate, then
review the generated file to confirm it matches the intended schema.  Do not hand-edit
the migration to add logic beyond what autogenerate produces.

## Out of scope for this phase

- The backup or restore tasks.
- Any route or template changes.
- Any changes to `BackupRecord` or `BackupConfiguration`.

## Verification

```bash
grep -n "ObjectStoreBackupRecord" app/models/utilities.py
grep -n "ObjectStoreBackupRecord" app/models/__init__.py
grep -rn "object_store_backup_records" migrations/versions/
```

Each should return at least one match.  Also confirm:

```bash
flask db upgrade head   # should apply without error
flask db downgrade -1   # should reverse without error
flask db upgrade head   # should re-apply cleanly
```
