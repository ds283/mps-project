#
# Created by David Seery on 22/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Box cloud storage provider.

Wraps get_box_client() from app/shared/box_api.py so that all token lifecycle concerns
(proactive refresh, Redis lock, DBTokenStorage) remain owned by box_api.py.
"""

from io import BytesIO
from typing import BinaryIO, List, Optional, Union

from flask import url_for

from ..base import CloudItem, CloudStorageProvider
from ...box_api import get_box_client


class BoxCloudStorageProvider(CloudStorageProvider):
    """
    CloudStorageProvider implementation for Box.

    Construct via from_user() (user-delegated OAuth) or from_config() (server-delegated —
    not yet implemented; raises NotImplementedError).
    """

    def __init__(self, client, user=None):
        self._client = client
        self._user = user
        self._folder_item_cache: dict = {}  # folder_ref -> List[item]

    # -- Construction --------------------------------------------------------

    @classmethod
    def from_user(cls, user) -> "BoxCloudStorageProvider":
        """Build a provider from the Box OAuth tokens stored on *user*."""
        client = get_box_client(user)
        return cls(client=client, user=user)

    @classmethod
    def from_config(cls, cfg: dict) -> "BoxCloudStorageProvider":
        raise NotImplementedError("Server-delegated Box auth (JWT / app-user) is not yet implemented. Use from_user() for user-delegated OAuth.")

    # -- Introspection -------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "box"

    @property
    def display_name(self) -> str:
        return "Box"

    # -- Auth status & recovery ----------------------------------------------

    def is_authenticated(self) -> bool:
        if self._user is None:
            return True
        return bool(self._user.box_token_valid)

    def reauth_url(self) -> str:
        return url_for("oauth2.box_login", _external=False)

    def is_auth_error(self, exc: Exception) -> bool:
        """
        Return True when *exc* signals that the Box OAuth tokens are invalid or expired.
        Covers the `invalid_grant` 400 that the SDK raises when it tries to use the
        refresh token and Box rejects it.
        """
        try:
            from box_sdk_gen.box.errors import BoxAPIError

            if not isinstance(exc, BoxAPIError):
                return False
            body = exc.response_info.body or {}
            # 400 invalid_grant = refresh token expired / revoked
            if exc.response_info.status_code == 400 and body.get("error") == "invalid_grant":
                return True
            # 401 without a usable refresh token
            if exc.response_info.status_code == 401:
                return True
            return False
        except Exception:
            return False

    # -- Internal helpers ----------------------------------------------------

    def _get_folder_items(self, folder_id: str) -> list:
        """Retrieve all items in a Box folder, handling pagination."""
        items = []
        marker = None
        while True:
            page = self._client.folders.get_folder_items(
                folder_id=folder_id,
                limit=1000,
                marker=marker,
                usemarker=True,
            )
            if page.entries:
                items.extend(page.entries)
            marker = page.next_marker
            if not marker:
                break
        return items

    def _get_folder_items_cached(self, folder_ref: str) -> list:
        """Return cached folder listing; falls back to live fetch on cache miss."""
        if folder_ref not in self._folder_item_cache:
            self._folder_item_cache[folder_ref] = self._get_folder_items(folder_ref)
        return self._folder_item_cache[folder_ref]

    def invalidate_folder_cache(self, folder_ref: str) -> None:
        """Remove a folder from the cache (call after a successful upsert)."""
        self._folder_item_cache.pop(folder_ref, None)

    # -- Folder operations ---------------------------------------------------

    def get_or_create_folder(self, parent_ref: str, name: str) -> str:
        """Return the Box folder ID of *name* inside *parent_ref*, creating it if absent."""
        from box_sdk_gen import CreateFolderParent

        items = self._get_folder_items_cached(parent_ref)
        for item in items:
            if item.type == "folder" and item.name == name:
                return item.id

        folder = self._client.folders.create_folder(
            name=name,
            parent=CreateFolderParent(id=parent_ref),
        )
        self.invalidate_folder_cache(parent_ref)
        return folder.id

    def list_folder(self, folder_ref: str) -> List[CloudItem]:
        """Return all items in *folder_ref* as CloudItem instances."""
        raw_items = self._get_folder_items(folder_ref)
        result = []
        for item in raw_items:
            result.append(
                CloudItem(
                    ref=item.id,
                    name=item.name,
                    kind=item.type,  # "file" or "folder"
                    size=getattr(item, "size", None),
                    modified_at=getattr(item, "modified_at", None),
                )
            )
        return result

    # -- File operations -----------------------------------------------------

    def upsert_file(
        self,
        folder_ref: str,
        filename: str,
        data: Union[bytes, BinaryIO],
        mimetype: str = "application/octet-stream",
    ) -> str:
        """
        Upload *data* as *filename* inside *folder_ref*.
        Creates a new version if the filename already exists, never a duplicate entry.
        Returns the Box file ID.
        """
        from box_sdk_gen import (
            UploadFileAttributes,
            UploadFileAttributesParentField,
            UploadFileVersionAttributes,
        )

        # Check for an existing file with the same name
        items = self._get_folder_items_cached(folder_ref)
        existing_id: Optional[str] = None
        for item in items:
            if item.type == "file" and item.name == filename:
                existing_id = item.id
                break

        buf = BytesIO(data) if isinstance(data, bytes) else data

        if existing_id is None:
            result = self._client.uploads.upload_file(
                attributes=UploadFileAttributes(
                    name=filename,
                    parent=UploadFileAttributesParentField(id=folder_ref),
                ),
                file=buf,
                file_file_name=filename,
                file_content_type=mimetype,
            )
            self.invalidate_folder_cache(folder_ref)
            return result.entries[0].id
        else:
            result = self._client.uploads.upload_file_version(
                file_id=existing_id,
                attributes=UploadFileVersionAttributes(name=filename),
                file=buf,
                file_file_name=filename,
                file_content_type=mimetype,
            )
            self.invalidate_folder_cache(folder_ref)
            return result.entries[0].id

    def upsert_file_chunked(
        self,
        folder_ref: str,
        filename: str,
        stream: BinaryIO,
        size: int,
        mimetype: str = "application/octet-stream",
        chunk_size: int = 20 * 1024 * 1024,
    ) -> str:
        """
        Upload *stream* to Box using the chunked upload API.
        Falls back to upsert_file() when size < chunk_size.
        """
        if size < chunk_size:
            data = stream.read()
            return self.upsert_file(folder_ref, filename, data, mimetype)

        # Check for an existing file with the same name
        items = self._get_folder_items_cached(folder_ref)
        existing_id: Optional[str] = None
        for item in items:
            if item.type == "file" and item.name == filename:
                existing_id = item.id
                break

        if existing_id is None:
            result = self._client.chunked_uploads.upload_big_file(
                file=stream,
                file_name=filename,
                file_size=size,
                parent_folder_id=folder_ref,
            )
            self.invalidate_folder_cache(folder_ref)
            return result.id
        else:
            file_id = self._upload_chunked_version(existing_id, filename, stream, size)
            self.invalidate_folder_cache(folder_ref)
            return file_id

    def _upload_chunked_version(self, existing_id: str, filename: str, stream: BinaryIO, size: int) -> str:
        """Chunked version-replacement upload for an existing Box file."""
        from box_sdk_gen.internal.utils import (
            Hash,
            HashName,
            generate_byte_stream_from_buffer,
            iterate_chunks,
            read_byte_stream,
        )

        session = self._client.chunked_uploads.create_file_upload_session_for_existing_file(
            file_id=existing_id,
            file_size=size,
            file_name=filename,
        )
        upload_part_url = session.session_endpoints.upload_part
        commit_url = session.session_endpoints.commit
        part_size = session.part_size

        file_hash = Hash(algorithm=HashName.SHA1)
        parts = []
        offset = 0

        for chunk_stream in iterate_chunks(stream, part_size, size):
            chunk_buf = read_byte_stream(chunk_stream)
            chunk_len = len(chunk_buf)

            part_hash = Hash(algorithm=HashName.SHA1)
            part_hash.update_hash(chunk_buf)
            part_digest = f"sha={part_hash.digest_hash('base64')}"
            content_range = f"bytes {offset}-{offset + chunk_len - 1}/{size}"

            uploaded = self._client.chunked_uploads.upload_file_part_by_url(
                url=upload_part_url,
                request_body=generate_byte_stream_from_buffer(chunk_buf),
                digest=part_digest,
                content_range=content_range,
            )
            parts.append(uploaded.part)
            file_hash.update_hash(chunk_buf)
            offset += chunk_len

        full_digest = f"sha={file_hash.digest_hash('base64')}"
        committed = self._client.chunked_uploads.create_file_upload_session_commit_by_url(
            url=commit_url,
            parts=parts,
            digest=full_digest,
        )
        return committed.entries[0].id

    def download_file(self, file_ref: str) -> bytes:
        """Fetch file content via the Box API using the stored credential."""
        from box_sdk_gen.internal.utils import read_byte_stream

        stream = self._client.downloads.download_file(file_id=file_ref)
        return read_byte_stream(stream)

    def get_shareable_url(
        self,
        file_ref: str,
        access: str = "open",
    ) -> Optional[str]:
        """
        Create or update a shared link for *file_ref* and return its URL.
        Returns None if the Box API call fails (logged as a warning, not raised).
        """
        try:
            from box_sdk_gen import (
                AddShareLinkToFileSharedLink,
                AddShareLinkToFileSharedLinkAccessField,
            )

            _access_map = {
                "open": AddShareLinkToFileSharedLinkAccessField.OPEN,
                "company": AddShareLinkToFileSharedLinkAccessField.COMPANY,
                "collaborators": AddShareLinkToFileSharedLinkAccessField.COLLABORATORS,
            }
            access_field = _access_map.get(access, AddShareLinkToFileSharedLinkAccessField.OPEN)

            file_full = self._client.shared_links_files.add_share_link_to_file(
                file_id=file_ref,
                fields="shared_link",
                shared_link=AddShareLinkToFileSharedLink(access=access_field),
            )
            sl = file_full.shared_link
            return sl.url if sl else None
        except Exception as exc:
            from flask import current_app

            current_app.logger.warning(
                "BoxCloudStorageProvider: could not create shared link for file %s: %s",
                file_ref,
                exc,
            )
            return None

    def delete_file(self, file_ref: str) -> None:
        """Permanently delete *file_ref* from Box."""
        self._client.files.delete_file_by_id(file_id=file_ref)
