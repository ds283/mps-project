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

    # -- Construction --------------------------------------------------------

    @classmethod
    def from_user(cls, user) -> "BoxCloudStorageProvider":
        """Build a provider from the Box OAuth tokens stored on *user*."""
        client = get_box_client(user)
        return cls(client=client, user=user)

    @classmethod
    def from_config(cls, cfg: dict) -> "BoxCloudStorageProvider":
        raise NotImplementedError(
            "Server-delegated Box auth (JWT / app-user) is not yet implemented. "
            "Use from_user() for user-delegated OAuth."
        )

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

    # -- Folder operations ---------------------------------------------------

    def get_or_create_folder(self, parent_ref: str, name: str) -> str:
        """Return the Box folder ID of *name* inside *parent_ref*, creating it if absent."""
        from box_sdk_gen import CreateFolderParent

        items = self._get_folder_items(parent_ref)
        for item in items:
            if item.type == "folder" and item.name == name:
                return item.id

        folder = self._client.folders.create_folder(
            name=name,
            parent=CreateFolderParent(id=parent_ref),
        )
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
        items = self._get_folder_items(folder_ref)
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
            return result.entries[0].id
        else:
            result = self._client.uploads.upload_file_version(
                file_id=existing_id,
                attributes=UploadFileVersionAttributes(name=filename),
                file=buf,
                file_file_name=filename,
                file_content_type=mimetype,
            )
            return result.entries[0].id

    def download_file(self, file_ref: str) -> bytes:
        """Fetch file content via the Box API using the stored credential."""
        buf = BytesIO()
        self._client.downloads.download_file(file_id=file_ref, output_stream=buf)
        return buf.getvalue()

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
