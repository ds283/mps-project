#
# Created by David Seery on 25/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional, Set
from uuid import uuid4

from celery import group as cgroup
from celery.exceptions import Ignore
from flask import current_app

import app.shared.cloud_object_store.bucket_types as buckets
from ..database import db
from ..models import BackupRecord, TaskRecord, User
from ..models.assets import GeneratedAsset, SubmittedAsset, TemporaryAsset
from ..models.utilities import ObjectStoreBackupRecord
from ..shared.asset_tools import decode_nonce, encode_nonce
from ..shared.cloud_object_store.base import ObjectStore
from ..shared.cloud_object_store.meta import ObjectMeta
from ..shared.cloud_storage import CloudItem, CloudStorageLocation
from ..task_queue import progress_update


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


def _sanitize_key(key: str) -> str:
    return key.replace("/", "__").replace("\\", "__")


def _build_nonce_map(bucket_type: int, keys: Set[str]) -> Dict[str, bytes]:
    result: Dict[str, bytes] = {}

    if bucket_type == buckets.BACKUP_BUCKET:
        rows = db.session.query(BackupRecord).filter(BackupRecord.unique_name.in_(keys)).all()
        for row in rows:
            if row.nonce is not None:
                try:
                    result[row.unique_name] = decode_nonce(row.nonce)
                except Exception:
                    pass
    else:
        model_classes = BUCKET_MODEL_MAP.get(bucket_type, [])
        for model_cls in model_classes:
            rows = db.session.query(model_cls).filter(model_cls.unique_name.in_(keys)).all()
            for row in rows:
                if row.nonce is not None and row.unique_name not in result:
                    try:
                        result[row.unique_name] = decode_nonce(row.nonce)
                    except Exception:
                        pass

    return result


def _get_object_data(
    object_store: ObjectStore,
    key: str,
    nonce_map: Dict[str, bytes],
    bucket_type: int,
) -> Optional[bytes]:
    if object_store.encrypted:
        if key in nonce_map:
            return object_store.get(key, audit_data="cloud_backup", nonce=nonce_map[key])
        else:
            current_app.logger.warning(
                "object_store_backup: key %s in bucket type %d has no ORM row / no nonce (orphaned object)",
                key,
                bucket_type,
            )
            return None
    else:
        return object_store.get(key, audit_data="cloud_backup", no_encryption=True)


def _is_up_to_date(cloud_meta: Optional[dict], plaintext_size: int) -> bool:
    return cloud_meta is not None and cloud_meta.get("plaintext_size") == plaintext_size


def _upsert_with_sidecar(location, folder_ref, key, data: bytes, cloud_items_index: dict):
    filename = _sanitize_key(key)
    meta_filename = filename + ".meta"
    meta_payload = json.dumps({
        "plaintext_size": len(data),
        "object_key": key,
        "backed_up_at": datetime.now().isoformat(),
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
                "deleted_at": datetime.now().isoformat(),
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


class _CloudAuthError(Exception):
    """Sentinel raised by _do_bucket_restore when the cloud provider returns an auth error."""


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

    # BackupRecord uses unique_name too, but has no `lost` flag
    if bucket_type == buckets.BACKUP_BUCKET:
        row = db.session.query(BackupRecord).filter_by(unique_name=key).first()
        if row is not None:
            row.nonce = new_nonce_b64
            db.session.commit()
            return True

    return False


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


def _do_bucket_restore(
    location,
    object_store,
    record,
    overwrite: bool,
    owner_user,
    task_id: str = None,
    progress_start: int = 15,
    progress_end: int = 95,
):
    """
    Download every object in *record.cloud_folder_ref* and put it back into
    *object_store*.  Progress updates are emitted every 50 objects if *task_id*
    is provided, scaled between *progress_start* and *progress_end*.

    Raises _CloudAuthError if the cloud provider rejects credentials (user has
    already been notified via location.handle_auth_error).
    Returns (restored, skipped, errors, orphaned, total).
    """
    cloud_items = {item.name: item for item in location.list_folder(record.cloud_folder_ref)}
    existing_keys = object_store.list_keys(audit_data="cloud_restore")

    restored = skipped = errors = orphaned = 0
    restored_keys: Set[str] = set()

    filenames = [n for n in cloud_items if not n.endswith(".meta")]
    total = len(filenames)
    progress_range = progress_end - progress_start

    for i, filename in enumerate(filenames):
        key = filename.replace("__", "/")
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
            new_nonce = result.get("nonce") if result else None
            if new_nonce:
                new_nonce_b64 = encode_nonce(new_nonce)
                found = _update_asset_nonce(record.bucket_type, key, new_nonce_b64)
                if not found:
                    orphaned += 1
                    current_app.logger.warning(
                        "cloud_restore: key %s has no ORM row in bucket %s",
                        key, record.bucket_label,
                    )
            restored_keys.add(key)
            restored += 1
        except Exception as exc:
            if location.handle_auth_error(exc, notify_user=owner_user):
                raise _CloudAuthError(str(exc)) from exc
            errors += 1
            current_app.logger.warning(
                "cloud_restore: error restoring key %s: %s", key, exc
            )

        if task_id is not None and i % 50 == 0:
            pct = progress_start + int(progress_range * i / max(total, 1))
            progress_update(
                task_id,
                TaskRecord.RUNNING,
                pct,
                f"Restoring {record.bucket_label}: {i}/{total} objects...",
                autocommit=True,
            )

    _clear_lost_flags(record.bucket_type, restored_keys)
    return restored, skipped, errors, orphaned, total


def register_object_store_backup_tasks(celery):

    def _do_bucket_backup(location, object_store, bucket_type, run_id, record):
        bucket_label = BUCKET_LABEL_MAP.get(bucket_type, str(bucket_type))
        record.bucket_label = bucket_label
        record.run_id = run_id

        # Ensure folder structure
        bucket_folder_ref = location.get_or_create_folder(None, bucket_label)
        objects_folder_ref = location.get_or_create_folder(bucket_folder_ref, "objects")
        tombstone_folder_ref = location.get_or_create_folder(bucket_folder_ref, "tombstones")
        record.cloud_folder_ref = objects_folder_ref
        db.session.commit()

        # Build folder index (one list_folder call per folder)
        cloud_items: Dict[str, CloudItem] = {
            item.name: item
            for item in location.list_folder(objects_folder_ref)
        }
        meta_index: Dict[str, dict] = {}
        _meta_items = [(name, item) for name, item in cloud_items.items() if name.endswith(".meta")]
        if _meta_items:
            _app = current_app._get_current_object()

            def _fetch_meta(args):
                _name, _item = args
                with _app.app_context():
                    _raw = location.download_file(_item.ref)
                return _name[:-5], json.loads(_raw.decode("utf-8"))

            _n_workers = min(20, len(_meta_items))
            with ThreadPoolExecutor(max_workers=_n_workers) as _pool:
                _futures = {_pool.submit(_fetch_meta, ni): ni[0] for ni in _meta_items}
                for _fut in as_completed(_futures):
                    _sidecar_name = _futures[_fut]
                    try:
                        _key, _meta = _fut.result()
                        meta_index[_key] = _meta
                    except Exception as exc:
                        current_app.logger.warning(
                            "object_store_backup: could not read .meta sidecar %s: %s",
                            _sidecar_name, exc
                        )

        # Enumerate bucket
        bucket_meta: Dict[str, ObjectMeta] = object_store.list(audit_data="cloud_backup")
        bucket_keys: Set[str] = set(bucket_meta.keys())
        record.object_count_total = len(bucket_keys)

        # Build nonce map (single bulk query pass)
        nonce_map = _build_nonce_map(bucket_type, bucket_keys)

        # Main upload loop
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

        # Tombstone pass
        deleted = _handle_tombstones(location, cloud_items, bucket_keys, tombstone_folder_ref)

        # Finalise record
        record.object_count_uploaded = uploaded
        record.object_count_skipped  = skipped
        record.object_count_error    = errors
        record.object_count_orphaned = orphaned
        record.object_count_deleted  = deleted
        record.bytes_uploaded        = bytes_up
        record.finished_at           = datetime.now()
        record.status = (
            ObjectStoreBackupRecord.SUCCESS if errors == 0
            else ObjectStoreBackupRecord.PARTIAL
        )
        if error_messages:
            record.error_detail = "\n".join(error_messages[:50])
        db.session.commit()

    @celery.task(bind=True, default_retry_delay=60)
    def backup_object_stores(self, owner_id: int = None):
        """
        Coordinator task: validates credentials, creates per-bucket ObjectStoreBackupRecord
        rows, then fans out one backup_single_bucket task per bucket to the backup_tasks queue.
        Returns quickly so the upstream TaskRecord chain completes without blocking.
        """
        if not current_app.config.get("OBJECT_STORE_BACKUP_ENABLED", False):
            self.update_state(state="DISABLED", meta={"msg": "Object store backup not enabled"})
            raise Ignore()

        owner_user = db.session.get(User, owner_id)
        if owner_user is None or not owner_user.box_token_valid:
            current_app.logger.error(
                "object_store_backup: owner_id=%s is invalid or has no valid Box token", owner_id
            )
            raise Ignore()

        provider_name = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_PROVIDER", "box")
        run_id = str(uuid4())

        bucket_types = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_BUCKETS", [])
        all_stores: dict = current_app.config.get("OBJECT_STORAGE_BUCKETS", {})

        # Mark any RUNNING records for these buckets as FAILED — they belong to an
        # interrupted previous run and will never complete.
        if bucket_types:
            stale = (
                db.session.query(ObjectStoreBackupRecord)
                .filter(
                    ObjectStoreBackupRecord.bucket_type.in_(bucket_types),
                    ObjectStoreBackupRecord.status == ObjectStoreBackupRecord.RUNNING,
                )
                .all()
            )
            for r in stale:
                r.status = ObjectStoreBackupRecord.FAILED
                r.error_detail = "Abandoned: new backup run started"
            if stale:
                db.session.commit()

        # Create one ObjectStoreBackupRecord per bucket upfront so the dashboard
        # shows them immediately, then fan out one Celery task per bucket.
        records: List[ObjectStoreBackupRecord] = []
        for bucket_type in bucket_types:
            if all_stores.get(bucket_type) is None:
                current_app.logger.warning(
                    "object_store_backup: no ObjectStore configured for bucket_type=%d; skipping",
                    bucket_type,
                )
                continue
            record = ObjectStoreBackupRecord(
                bucket_type=bucket_type,
                bucket_label=BUCKET_LABEL_MAP.get(bucket_type, str(bucket_type)),
                status=ObjectStoreBackupRecord.RUNNING,
                owner_id=owner_id,
                provider_name=provider_name,
                run_id=run_id,
            )
            db.session.add(record)
            records.append(record)

        db.session.flush()   # populate record.id for all rows
        db.session.commit()

        if not records:
            return

        bucket_group = cgroup(
            backup_single_bucket.si(record_id=record.id, owner_id=owner_id)
            for record in records
        )
        try:
            bucket_group.apply_async()
        except Exception as exc:
            for record in records:
                record.status = ObjectStoreBackupRecord.FAILED
                record.error_detail = f"Failed to dispatch backup tasks: {exc}"
            db.session.commit()
            raise

    @celery.task(bind=True, default_retry_delay=60)
    def backup_single_bucket(self, record_id: int, owner_id: int = None):
        """
        Per-bucket backup task, routed to the backup_tasks queue.  Backs up one
        MinIO bucket to cloud storage using the pre-created ObjectStoreBackupRecord
        identified by *record_id*.
        """
        record = db.session.get(ObjectStoreBackupRecord, record_id)
        if record is None:
            current_app.logger.error(
                "object_store_backup: ObjectStoreBackupRecord #%s not found", record_id
            )
            return

        owner_user = db.session.get(User, owner_id)
        if owner_user is None or not owner_user.box_token_valid:
            record.status = ObjectStoreBackupRecord.FAILED
            record.error_detail = "Owner user is invalid or has no valid Box token"
            db.session.commit()
            current_app.logger.error(
                "object_store_backup: owner_id=%s is invalid or has no valid Box token", owner_id
            )
            return

        bucket_type = record.bucket_type
        object_store = current_app.config.get("OBJECT_STORAGE_BUCKETS", {}).get(bucket_type)
        if object_store is None:
            record.status = ObjectStoreBackupRecord.FAILED
            record.error_detail = f"No ObjectStore configured for bucket_type={bucket_type}"
            db.session.commit()
            current_app.logger.warning(
                "object_store_backup: no ObjectStore configured for bucket_type=%d; skipping",
                bucket_type,
            )
            return

        root_folder = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER")
        location = CloudStorageLocation.from_user(
            provider_name=record.provider_name,
            user=owner_user,
            root_ref=root_folder,
            audit_data="object_store_backup",
        )

        try:
            _do_bucket_backup(location, object_store, bucket_type, record.run_id, record)
        except Exception as exc:
            if location.handle_auth_error(exc, notify_user=owner_user):
                record.status = ObjectStoreBackupRecord.FAILED
                record.error_detail = str(exc)
                db.session.commit()
                return
            record.status = ObjectStoreBackupRecord.FAILED
            record.error_detail = str(exc)
            db.session.commit()
            current_app.logger.exception(
                "object_store_backup: unhandled error for bucket_type=%d: %s",
                bucket_type, exc,
            )

    @celery.task(bind=True, default_retry_delay=30)
    def restore_selected_object_store_buckets(
        self,
        task_id: str,
        record_ids: list,
        overwrite: bool = False,
        owner_id: int = None,
    ):
        progress_update(task_id, TaskRecord.RUNNING, 5, "Loading backup records...", autocommit=True)

        records = [db.session.get(ObjectStoreBackupRecord, rid) for rid in record_ids]
        records = [r for r in records if r is not None]
        if not records:
            progress_update(
                task_id, TaskRecord.FAILURE, 100,
                "No valid backup records found for the selected buckets.",
                autocommit=True,
            )
            return

        owner_user = db.session.get(User, owner_id)
        if owner_user is None or not owner_user.box_token_valid:
            progress_update(
                task_id, TaskRecord.FAILURE, 100,
                "Owner user is invalid or has no valid cloud storage token",
                autocommit=True,
            )
            return

        root_folder = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER")
        n = len(records)
        total_restored = total_skipped = total_errors = total_orphaned = 0

        for idx, record in enumerate(records):
            object_store = current_app.config["OBJECT_STORAGE_BUCKETS"].get(record.bucket_type)
            if object_store is None:
                current_app.logger.warning(
                    "cloud_restore: no ObjectStore configured for bucket_type=%d; skipping",
                    record.bucket_type,
                )
                continue

            location = CloudStorageLocation.from_user(
                provider_name=record.provider_name,
                user=owner_user,
                root_ref=root_folder,
                audit_data="cloud_restore",
            )

            p_start = 15 + int(80 * idx / n)
            p_end = 15 + int(80 * (idx + 1) / n)

            progress_update(
                task_id, TaskRecord.RUNNING, p_start,
                f"Restoring {record.bucket_label} ({idx + 1}/{n})...",
                autocommit=True,
            )

            try:
                restored, skipped, errors, orphaned, _ = _do_bucket_restore(
                    location, object_store, record, overwrite, owner_user,
                    task_id=task_id, progress_start=p_start, progress_end=p_end,
                )
            except _CloudAuthError as exc:
                progress_update(
                    task_id, TaskRecord.FAILURE, 100,
                    f"Cloud storage authentication error: {exc}",
                    autocommit=True,
                )
                return

            total_restored += restored
            total_skipped += skipped
            total_errors += errors
            total_orphaned += orphaned

        msg = (
            f"Restore complete: {n} buckets — "
            f"{total_restored} restored, {total_skipped} skipped, "
            f"{total_orphaned} orphaned, {total_errors} errors."
        )
        progress_update(task_id, TaskRecord.SUCCESS, 100, msg, autocommit=True)

    return (
        backup_object_stores,
        backup_single_bucket,
        restore_selected_object_store_buckets,
    )
