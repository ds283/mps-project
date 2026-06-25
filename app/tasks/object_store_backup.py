#
# Created by David Seery on 25/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import base64
import json
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional, Set
from uuid import uuid4

from celery.exceptions import Ignore
from flask import current_app

import app.shared.cloud_object_store.bucket_types as buckets
from ..database import db
from ..models import BackupRecord, User
from ..models.assets import GeneratedAsset, SubmittedAsset, TemporaryAsset
from ..models.utilities import ObjectStoreBackupRecord
from ..shared.cloud_object_store.base import ObjectStore
from ..shared.cloud_object_store.meta import ObjectMeta
from ..shared.cloud_storage import CloudItem, CloudStorageLocation


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
                    result[row.unique_name] = base64.b64decode(row.nonce)
                except Exception:
                    pass
    else:
        model_classes = BUCKET_MODEL_MAP.get(bucket_type, [])
        for model_cls in model_classes:
            rows = db.session.query(model_cls).filter(model_cls.unique_name.in_(keys)).all()
            for row in rows:
                if row.nonce is not None and row.unique_name not in result:
                    try:
                        result[row.unique_name] = base64.b64decode(row.nonce)
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
        for name, item in cloud_items.items():
            if name.endswith(".meta"):
                try:
                    raw = location.download_file(item.ref)
                    meta_index[name[:-5]] = json.loads(raw.decode("utf-8"))
                except Exception:
                    pass

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
        if not current_app.config.get("OBJECT_STORE_BACKUP_ENABLED", False):
            self.update_state(state="DISABLED", meta={"msg": "Object store backup not enabled"})
            raise Ignore()

        owner_user = db.session.get(User, owner_id)
        if owner_user is None or not owner_user.box_token_valid:
            current_app.logger.error(
                "object_store_backup: owner_id=%s is invalid or has no valid Box token", owner_id
            )
            raise Ignore()

        root_folder = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_ROOT_FOLDER")
        provider_name = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_PROVIDER", "box")
        location = CloudStorageLocation.from_user(
            provider_name=provider_name,
            user=owner_user,
            root_ref=root_folder,
            audit_data="object_store_backup",
        )

        run_id = str(uuid4())

        bucket_types = current_app.config.get("OBJECT_STORE_CLOUD_BACKUP_BUCKETS", [])
        all_stores: dict = current_app.config.get("OBJECT_STORAGE_BUCKETS", {})

        for bucket_type in bucket_types:
            object_store = all_stores.get(bucket_type)
            if object_store is None:
                current_app.logger.warning(
                    "object_store_backup: no ObjectStore configured for bucket_type=%d; skipping",
                    bucket_type,
                )
                continue

            record = ObjectStoreBackupRecord(
                bucket_type=bucket_type,
                status=ObjectStoreBackupRecord.RUNNING,
                owner_id=owner_id,
                provider_name=provider_name,
                run_id=run_id,
            )
            db.session.add(record)
            db.session.flush()

            try:
                _do_bucket_backup(location, object_store, bucket_type, run_id, record)
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
                continue

    return (backup_object_stores,)
