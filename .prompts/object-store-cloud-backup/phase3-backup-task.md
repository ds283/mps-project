# Phase 3 — Backup Beat task: `app/tasks/object_store_backup.py`

## Prerequisites

Phase 1 (provider layer) and Phase 2 (ORM model) must be complete.

## Context

This phase creates the new Celery Beat task that backs up all configured object-store
buckets to a `CloudStorageLocation` (initially Box).  It creates one
`ObjectStoreBackupRecord` row per bucket per run, implements the incremental skip-logic
via `.meta` sidecar files, handles tombstoning of deleted objects, and wires the new
task module into the task registry.

## Files to read before writing any code

Read each file in full before making any changes:

1. `app/tasks/backup.py` — existing DB backup task; primary pattern reference for
   Beat task structure, `BACKUP_IS_LIVE` guard, `ObjectStore` usage, and error handling.
2. `app/tasks/cloud_export_period_marking.py` — primary reference for
   `CloudStorageLocation` usage inside a Celery task.
3. `app/tasks/cloud_api_audit.py` — secondary reference for a minimal Beat task
   that lists and puts objects.
4. `app/tasks/__init__.py` — where to add the new import.
5. `app/__init__.py` lines ~300–332 — where `register_*_tasks(celery)` calls live.
6. `app/shared/cloud_storage/base.py` — `CloudStorageLocation` API (post Phase 1).
7. `app/shared/cloud_object_store/base.py` — `ObjectStore` API.
8. `app/shared/cloud_object_store/bucket_types.py` — bucket-type integer constants.
9. `app/models/utilities.py` — `ObjectStoreBackupRecord` (post Phase 2).
10. `app/models/assets.py` — `SubmittedAsset`, `GeneratedAsset`, `ThumbnailAsset`,
    `TemporaryAsset` — needed for the nonce-map builder.
11. `app/models/model_mixins.py` lines 933–1100 — `BaseAssetMixin`,
    `InstrumentedAssetMixinFactory` — confirms which model classes carry `.nonce`.
12. `app/models/__init__.py` — confirm `BackupRecord` is exported here (needed for
    `BACKUP_BUCKET` nonce lookup).

## New file: `app/tasks/object_store_backup.py`

Create this file from scratch.  Structure it as follows.

### Module-level constants

```python
# Map bucket_type int → human-readable label used as Box subfolder name
BUCKET_LABEL_MAP: Dict[int, str] = {
    buckets.ASSETS_BUCKET:             "assets",
    buckets.BACKUP_BUCKET:             "backup",
    buckets.FEEDBACK_BUCKET:           "feedback",
    buckets.PROJECT_BUCKET:            "project",
    buckets.SUPERVISION_ASSETS_BUCKET: "supervision",
}

# Map bucket_type int → ORM model classes that carry nonce/encryption metadata
# for objects in that bucket.  Order matters: check each class in turn.
BUCKET_MODEL_MAP: Dict[int, List[type]] = {
    buckets.ASSETS_BUCKET:             [SubmittedAsset, GeneratedAsset, TemporaryAsset],
    buckets.BACKUP_BUCKET:             [],  # BackupRecord handled separately below
    buckets.FEEDBACK_BUCKET:           [GeneratedAsset],
    buckets.PROJECT_BUCKET:            [SubmittedAsset],
    buckets.SUPERVISION_ASSETS_BUCKET: [SubmittedAsset],
}

# Box chunked-upload threshold (bytes).  Objects larger than this use
# upsert_file_chunked instead of upsert_file.
CHUNKED_UPLOAD_THRESHOLD = 20 * 1024 * 1024   # 20 MB
```

### Helper functions (module level, not inside `register_...`)

These are pure functions with no Celery dependency and should be outside the factory:

#### `_sanitize_key(key: str) -> str`
Replace any characters not safe for Box filenames.  Object keys are UUIDs and should
survive as-is; the function is a safety net:
```python
def _sanitize_key(key: str) -> str:
    return key.replace("/", "__").replace("\\", "__")
```

#### `_build_nonce_map(bucket_type: int, keys: Set[str]) -> Dict[str, bytes]`
Query the ORM to find the nonce (decoded from base64) for each key in `keys`.

- For bucket types in `BUCKET_MODEL_MAP` with non-empty lists, query each model class
  for rows whose `unique_name` is in `keys` and whose `nonce` is not None.  Decode
  `base64.b64decode(row.nonce)` and store in the result dict.
- For `BACKUP_BUCKET`, query `BackupRecord` using `BackupRecord.key` (not
  `unique_name`) as the object key field, and `BackupRecord.nonce` for the nonce.
- Keys that cannot be found in any model are omitted from the map (they are orphaned
  objects — the backup task will log and skip them for encrypted buckets, or proceed
  without decryption for unencrypted buckets).
- Return `Dict[str, bytes]` mapping object key → raw nonce bytes.

#### `_get_object_data(object_store: ObjectStore, key: str, nonce_map: Dict[str, bytes], bucket_type: int) -> Optional[bytes]`
Download one object, decrypting if the bucket is encrypted.

- If `object_store.encrypted` is True and `key` in `nonce_map`:
  call `object_store.get(key, audit_data="cloud_backup", nonce=nonce_map[key])`.
- If `object_store.encrypted` is True and `key` **not** in `nonce_map`:
  log a warning at `current_app.logger.warning(...)` indicating the key is orphaned
  (no ORM row / no nonce).  Return `None` — the caller increments `object_count_orphaned`.
- If `object_store.encrypted` is False:
  call `object_store.get(key, audit_data="cloud_backup", no_encryption=True)`.
- Return the bytes, or `None` on orphaned-key.

#### `_is_up_to_date(cloud_meta: Optional[dict], plaintext_size: int) -> bool`
Decide whether to skip re-uploading an object.

`cloud_meta` is a dict loaded from the object's `.meta` sidecar file (or `None` if no
sidecar exists).  Return `True` only when `cloud_meta` is not None and
`cloud_meta.get("plaintext_size") == plaintext_size`.

#### `_upsert_with_sidecar(location, folder_ref, key, data, cloud_items_index)`
Upload the object bytes and its `.meta` sidecar to `folder_ref`.

`cloud_items_index` is `Dict[str, CloudItem]` — the cached listing of what is already
in the folder (see §folder index below).

```python
def _upsert_with_sidecar(location, folder_ref, key, data: bytes, cloud_items_index: dict):
    filename = _sanitize_key(key)
    meta_filename = filename + ".meta"
    meta_payload = json.dumps({
        "plaintext_size": len(data),
        "object_key": key,
        "backed_up_at": datetime.utcnow().isoformat(),
    }).encode("utf-8")

    size = len(data)
    if size >= CHUNKED_UPLOAD_THRESHOLD:
        location.upsert_file_chunked(
            folder_ref, filename, BytesIO(data), size,
            mimetype="application/octet-stream",
        )
    else:
        location.upsert_file(folder_ref, filename, data,
                             mimetype="application/octet-stream")

    location.upsert_file(folder_ref, meta_filename, meta_payload,
                         mimetype="application/json")
```

#### `_handle_tombstones(location, cloud_items_index, bucket_keys, tombstone_folder_ref) -> int`
Move objects present in the cloud backup but absent from MinIO into `tombstones/`.

```python
def _handle_tombstones(location, cloud_items_index: dict,
                       bucket_keys: Set[str], tombstone_folder_ref: str) -> int:
    deleted_count = 0
    for filename, cloud_item in list(cloud_items_index.items()):
        if filename.endswith(".meta"):
            continue
        key = filename.replace("__", "/")   # reverse _sanitize_key
        if key in bucket_keys:
            continue
        # Object deleted from MinIO — move to tombstones/
        try:
            data = location.download_file(cloud_item.ref)
            location.upsert_file(tombstone_folder_ref, filename, data)
            tombstone_meta = json.dumps({
                "deleted_at": datetime.utcnow().isoformat(),
                "original_key": key,
            }).encode("utf-8")
            location.upsert_file(tombstone_folder_ref, filename + ".tombstone",
                                 tombstone_meta)
            location.delete_file(cloud_item.ref)
            # Also delete the sidecar if present
            meta_item = cloud_items_index.get(filename + ".meta")
            if meta_item:
                location.delete_file(meta_item.ref)
            deleted_count += 1
        except Exception as exc:
            current_app.logger.warning(
                "object_store_backup: tombstone failed for key %s: %s", key, exc
            )
    return deleted_count
```

### `register_object_store_backup_tasks(celery)` factory function

Contains one inner task: `backup_object_stores`.

#### `backup_object_stores` task

Signature:
```python
@celery.task(bind=True, default_retry_delay=60)
def backup_object_stores(self, owner_id: int = None):
```

Logic:

1. **Guard:**
   ```python
   if not current_app.config.get("OBJECT_STORE_BACKUP_ENABLED", False):
       self.update_state(state="DISABLED", meta={"msg": "Object store backup not enabled"})
       raise Ignore()
   ```

2. **Resolve owner / build location:**
   Load `owner_user = db.session.get(User, owner_id)`.  If `None` or
   `not owner_user.box_token_valid`, log an error and return (do not raise — Beat
   tasks should not produce FAILURE state for configuration problems; use `Ignore()`).

   ```python
   root_folder = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER")
   provider_name = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_PROVIDER", "box")
   location = CloudStorageLocation.from_user(
       provider_name=provider_name,
       user=owner_user,
       root_ref=root_folder,
       audit_data="object_store_backup",
   )
   ```

3. **Generate `run_id`:**
   ```python
   run_id = str(uuid4())
   ```

4. **Iterate over configured buckets:**
   ```python
   bucket_types = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_BUCKETS", [])
   all_stores: dict = current_app.config.get("OBJECT_STORAGE_BUCKETS", {})
   ```

   For each `bucket_type` in `bucket_types`:
   - Look up `object_store = all_stores.get(bucket_type)`.  Skip with a warning if None.
   - Create an `ObjectStoreBackupRecord` row with `status=RUNNING`, flush to get an id.
   - Call `_do_bucket_backup(location, object_store, bucket_type, run_id, record)`.
   - If an auth error is detected (`location.handle_auth_error(exc, notify_user=owner_user)`
     returns True), set `record.status = FAILED`, commit, and `return` from the task
     entirely — Box tokens are invalid for all remaining buckets too.
   - For non-auth exceptions, set `record.status = FAILED`, record `error_detail`, commit,
     and `continue` to the next bucket.

5. **Return** — no notification needed for a Beat task.

#### `_do_bucket_backup(location, object_store, bucket_type, run_id, record)` (inner function inside the factory)

This is not a Celery task — it is a regular function called by `backup_object_stores`.

Logic:

1. Determine `bucket_label = BUCKET_LABEL_MAP.get(bucket_type, str(bucket_type))`.
   Update `record.bucket_label = bucket_label` and `record.run_id = run_id`.

2. **Ensure folder structure:**
   ```python
   bucket_folder_ref   = location.get_or_create_folder(None, bucket_label)
   objects_folder_ref  = location.get_or_create_folder(bucket_folder_ref, "objects")
   tombstone_folder_ref = location.get_or_create_folder(bucket_folder_ref, "tombstones")
   record.cloud_folder_ref = objects_folder_ref
   db.session.commit()
   ```

3. **Build folder index** (one `list_folder` call per folder):
   ```python
   cloud_items: Dict[str, CloudItem] = {
       item.name: item
       for item in location.list_folder(objects_folder_ref)
   }
   ```
   This is the skip-logic index.  Parse `.meta` sidecars into a separate dict:
   ```python
   meta_index: Dict[str, dict] = {}
   for name, item in cloud_items.items():
       if name.endswith(".meta"):
           try:
               raw = location.download_file(item.ref)
               meta_index[name[:-5]] = json.loads(raw.decode("utf-8"))
           except Exception:
               pass
   ```

4. **Enumerate bucket:**
   ```python
   bucket_meta: Dict[str, ObjectMeta] = object_store.list(audit_data="cloud_backup")
   bucket_keys: Set[str] = set(bucket_meta.keys())
   record.object_count_total = len(bucket_keys)
   ```

5. **Build nonce map** (single bulk query pass):
   ```python
   nonce_map = _build_nonce_map(bucket_type, bucket_keys)
   ```

6. **Main upload loop:**
   ```python
   uploaded = skipped = errors = orphaned = 0
   bytes_up = 0
   error_messages = []

   for key in bucket_keys:
       filename = _sanitize_key(key)
       try:
           data = _get_object_data(object_store, key, nonce_map, bucket_type)
           if data is None:
               orphaned += 1
               continue
           if _is_up_to_date(meta_index.get(filename), len(data)):
               skipped += 1
               continue
           _upsert_with_sidecar(location, objects_folder_ref, key, data, cloud_items)
           bytes_up += len(data)
           uploaded += 1
       except Exception as exc:
           errors += 1
           error_messages.append(f"{key}: {exc}")
           current_app.logger.warning(
               "object_store_backup: error backing up key %s in bucket %s: %s",
               key, bucket_label, exc,
           )
   ```

7. **Tombstone pass:**
   ```python
   deleted = _handle_tombstones(location, cloud_items, bucket_keys, tombstone_folder_ref)
   ```

8. **Finalise record:**
   ```python
   record.object_count_uploaded = uploaded
   record.object_count_skipped  = skipped
   record.object_count_error    = errors
   record.object_count_orphaned = orphaned
   record.object_count_deleted  = deleted
   record.bytes_uploaded        = bytes_up
   record.finished_at           = datetime.utcnow()
   record.status = (
       ObjectStoreBackupRecord.SUCCESS if errors == 0
       else ObjectStoreBackupRecord.PARTIAL
   )
   if error_messages:
       record.error_detail = "\n".join(error_messages[:50])
   db.session.commit()
   ```

### Wire in the new module

In `app/tasks/__init__.py`, add:
```python
from .object_store_backup import register_object_store_backup_tasks
```

In `app/__init__.py`, alongside the other `register_*_tasks(celery)` calls, add:
```python
tasks.register_object_store_backup_tasks(celery)
```

## Out of scope for this phase

- Beat schedule registration (`initdb.py`) — Phase 4.
- Restore tasks — Phase 5.
- Flask routes — Phase 6.
- Any template changes — Phases 7 and 8.

## Verification

```bash
grep -n "register_object_store_backup_tasks" app/tasks/__init__.py
grep -n "register_object_store_backup_tasks" app/__init__.py
grep -n "def backup_object_stores" app/tasks/object_store_backup.py
grep -n "def _do_bucket_backup" app/tasks/object_store_backup.py
grep -n "_build_nonce_map" app/tasks/object_store_backup.py
grep -n "_handle_tombstones" app/tasks/object_store_backup.py
grep -n "OBJECT_STORE_BACKUP_ENABLED" app/tasks/object_store_backup.py
```

All should return at least one match.

Also verify that `ObjectStoreBackupRecord` is imported inside the factory function
or at module level, and that `db.session.commit()` is used (not `log_db_commit`)
throughout — this is a periodic maintenance task.
