#
# Created by David Seery on 30/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from pathlib import Path

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

import app.shared.cloud_object_store.bucket_types as buckets

from ..database import db
from ..models import GeneratedAsset, SubmittedAsset, ThumbnailAsset
from ..models.defaults import DEFAULT_STRING_LENGTH
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.scratch import ScratchFolderManager

_ASSET_TYPES = {
    "GeneratedAsset": GeneratedAsset,
    "SubmittedAsset": SubmittedAsset,
}


def dispatch_thumbnail_task(asset) -> None:
    """
    Fire-and-forget dispatch of the generate_thumbnails task for a SubmittedAsset
    or GeneratedAsset.  Must be called after db.session.flush() so that asset.id
    is populated.
    """
    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.thumbnails.generate_thumbnails"]
    task.apply_async(args=[type(asset).__name__, asset.id])


def dispatch_force_regenerate_thumbnail_task(asset) -> None:
    """
    Fire-and-forget dispatch of the force_regenerate_thumbnails task for a SubmittedAsset
    or GeneratedAsset.  Clears error state, deletes existing thumbnails, and re-generates.
    """
    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.thumbnails.force_regenerate_thumbnails"]
    task.apply_async(args=[type(asset).__name__, asset.id])


def register_thumbnail_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def force_regenerate_thumbnails(self, asset_type: str, asset_id: int):
        """
        Clear thumbnail error state, delete existing ThumbnailAsset records and their
        physical files, then dispatch a fresh generate_thumbnails task.
        """
        self.update_state(state="STARTED")

        if asset_type not in _ASSET_TYPES:
            current_app.logger.error(
                f"force_regenerate_thumbnails: unknown asset type '{asset_type}'"
            )
            self.update_state(state="FINISHED")
            return

        model_class = _ASSET_TYPES[asset_type]

        try:
            asset = db.session.query(model_class).filter_by(id=asset_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if asset is None:
            current_app.logger.warning(
                f"force_regenerate_thumbnails: {asset_type} id #{asset_id} not found; skipping"
            )
            self.update_state(state="FINISHED")
            return

        bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")
        thumbnails_store = bucket_map.get(buckets.THUMBNAILS_BUCKET)

        # clear error state
        asset.thumbnail_error = False
        asset.thumbnail_error_message = None

        # delete existing thumbnail records and physical files
        for thumbnail_asset, fk_attr in (
            (asset.small_thumbnail, "small_thumbnail_id"),
            (asset.medium_thumbnail, "medium_thumbnail_id"),
        ):
            if thumbnail_asset is not None:
                setattr(asset, fk_attr, None)
                if thumbnails_store is not None:
                    try:
                        thumbnails_store.delete(
                            thumbnail_asset.unique_name,
                            audit_data=f"force_regenerate_thumbnails: {asset_type} id #{asset_id}",
                        )
                    except FileNotFoundError:
                        pass
                db.session.delete(thumbnail_asset)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                f"force_regenerate_thumbnails: SQLAlchemyError for {asset_type} id #{asset_id}",
                exc_info=e,
            )
            self.update_state(state="FINISHED")
            return

        # dispatch fresh thumbnail generation
        celery_app = current_app.extensions["celery"]
        gen_task = celery_app.tasks["app.tasks.thumbnails.generate_thumbnails"]
        gen_task.apply_async(args=[asset_type, asset_id])

        self.update_state(state="FINISHED")

    @celery.task(bind=True, default_retry_delay=30)
    def generate_thumbnails(self, asset_type: str, asset_id: int):
        self.update_state(state="STARTED")

        if asset_type not in _ASSET_TYPES:
            raise ValueError(f"generate_thumbnails: unknown asset type '{asset_type}'")

        model_class = _ASSET_TYPES[asset_type]

        try:
            asset = db.session.query(model_class).filter_by(id=asset_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if asset is None:
            current_app.logger.warning(
                f"generate_thumbnails: {asset_type} id #{asset_id} not found; skipping"
            )
            self.update_state(state="FINISHED")
            return

        bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")
        thumbnails_store = bucket_map.get(buckets.THUMBNAILS_BUCKET)
        source_store = bucket_map.get(asset.bucket)

        if thumbnails_store is None:
            current_app.logger.error(
                "generate_thumbnails: no ObjectStore for THUMBNAILS_BUCKET"
            )
            _set_thumbnail_error(asset, "Thumbnails bucket is not configured")
            self.update_state(state="FINISHED")
            return

        if source_store is None:
            current_app.logger.error(
                f"generate_thumbnails: no ObjectStore for bucket {asset.bucket}"
            )
            _set_thumbnail_error(
                asset, f"No object store configured for bucket {asset.bucket}"
            )
            self.update_state(state="FINISHED")
            return

        try:
            from preview_generator.manager import PreviewManager

            adapter = AssetCloudAdapter(
                asset,
                source_store,
                audit_data=f"generate_thumbnails: {asset_type} id #{asset_id}",
            )

            with adapter.download_to_scratch() as scratch_file:
                with ScratchFolderManager() as cache_dir:
                    manager = PreviewManager(str(cache_dir.path), create_folder=False)

                    small_preview_path = Path(
                        manager.get_jpeg_preview(
                            str(scratch_file.path), width=200, height=200
                        )
                    )
                    medium_preview_path = Path(
                        manager.get_jpeg_preview(
                            str(scratch_file.path), width=400, height=400
                        )
                    )

                    small_data = small_preview_path.read_bytes()
                    medium_data = medium_preview_path.read_bytes()

            # upload small thumbnail
            small_asset = ThumbnailAsset(timestamp=datetime.now())
            with AssetUploadManager(
                small_asset,
                data=small_data,
                storage=thumbnails_store,
                audit_data=f"generate_thumbnails small: {asset_type} id #{asset_id}",
                mimetype="image/jpeg",
                validate_nonce=None,
            ):
                pass

            # upload medium thumbnail
            medium_asset = ThumbnailAsset(timestamp=datetime.now())
            with AssetUploadManager(
                medium_asset,
                data=medium_data,
                storage=thumbnails_store,
                audit_data=f"generate_thumbnails medium: {asset_type} id #{asset_id}",
                mimetype="image/jpeg",
                validate_nonce=None,
            ):
                pass

            # stash references to any old thumbnails so we can clean them up after commit
            old_small = asset.small_thumbnail
            old_medium = asset.medium_thumbnail

            # clear FKs before deleting old records to avoid FK constraint violations
            asset.small_thumbnail_id = None
            asset.medium_thumbnail_id = None

            db.session.add(small_asset)
            db.session.add(medium_asset)
            db.session.flush()

            asset.small_thumbnail = small_asset
            asset.medium_thumbnail = medium_asset
            asset.thumbnail_error = False
            asset.thumbnail_error_message = None

            # delete old thumbnail records and their physical assets
            for old_asset in (old_small, old_medium):
                if old_asset is not None:
                    old_store = bucket_map.get(old_asset.bucket)
                    if old_store is not None:
                        try:
                            old_store.delete(
                                old_asset.unique_name,
                                audit_data=f"generate_thumbnails: replace thumbnail for {asset_type} id #{asset_id}",
                            )
                        except FileNotFoundError:
                            pass
                    db.session.delete(old_asset)

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(
                f"generate_thumbnails: error generating thumbnails for {asset_type} id #{asset_id}",
                exc_info=e,
            )
            _set_thumbnail_error(asset, str(e))

        self.update_state(state="FINISHED")


def _set_thumbnail_error(asset, message: str) -> None:
    """Set thumbnail_error flag and message on an asset, committing to the database."""
    try:
        asset.thumbnail_error = True
        asset.thumbnail_error_message = message[:DEFAULT_STRING_LENGTH]
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError while setting thumbnail_error flag", exc_info=e
        )
