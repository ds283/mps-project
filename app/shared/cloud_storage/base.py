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
Two-layer cloud storage abstraction, mirroring the Driver/ObjectStore split used for
internal object-store buckets.

  CloudStorageProvider — ABC; one concrete class per backend (Box, Google Drive, …).
                         Knows how to talk to the provider; holds the credential.
                         Never used directly by task code.

  CloudStorageLocation — Facade; holds (provider, root_ref).  Adds an audit layer.
                         This is what task code imports and calls.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO, List, Optional, Union


# ---------------------------------------------------------------------------
# CloudItem
# ---------------------------------------------------------------------------


@dataclass
class CloudItem:
    """Provider-agnostic descriptor for a file or folder returned by list_folder."""

    ref: str  # opaque provider ID (Box file/folder ID, Drive fileId, …)
    name: str
    kind: str  # "file" | "folder"
    size: Optional[int] = None
    modified_at: Optional[datetime] = None
    # Shareable/download URL if the provider can return it at list time.
    # Callers must fall back to location.get_shareable_url(item.ref) when None.
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# CloudStorageProvider ABC
# ---------------------------------------------------------------------------


class CloudStorageProvider(ABC):
    """
    Low-level provider interface. One concrete class per backend.

    Never instantiate directly from task code — obtain a CloudStorageLocation via
    CloudStorageLocation.from_user() or CloudStorageLocation.from_config() instead.
    """

    # -- Introspection -------------------------------------------------------

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier, e.g. "box", "gdrive"."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. "Box", "Google Drive"."""

    # -- Construction --------------------------------------------------------

    @classmethod
    @abstractmethod
    def from_user(cls, user) -> "CloudStorageProvider":
        """Build a provider from a User row's stored OAuth tokens."""

    @classmethod
    @abstractmethod
    def from_config(cls, cfg: dict) -> "CloudStorageProvider":
        """Build a provider from application config (service-account / server-delegated auth)."""

    # -- Auth status & recovery ----------------------------------------------

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Return True if the stored credential is believed to be valid."""

    @abstractmethod
    def reauth_url(self) -> str:
        """Return the URL the user must visit to re-link their account."""

    @abstractmethod
    def is_auth_error(self, exc: Exception) -> bool:
        """Return True when *exc* indicates that the credential has expired or been revoked."""

    # -- Folder operations ---------------------------------------------------

    @abstractmethod
    def get_or_create_folder(self, parent_ref: str, name: str) -> str:
        """
        Return the provider ref for the subfolder named *name* inside *parent_ref*,
        creating it if it does not exist.  Idempotent.
        """

    @abstractmethod
    def list_folder(self, folder_ref: str) -> List[CloudItem]:
        """Return all items in *folder_ref*."""

    # -- File operations -----------------------------------------------------

    @abstractmethod
    def upsert_file(
        self,
        folder_ref: str,
        filename: str,
        data: Union[bytes, BinaryIO],
        mimetype: str = "application/octet-stream",
    ) -> str:
        """
        Upload *data* as *filename* inside *folder_ref*.  If a file with that name
        already exists in the folder, create a new version rather than a duplicate entry.
        Returns the provider file ref.
        """

    @abstractmethod
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
        Upload *stream* as *filename* inside *folder_ref* using chunked/multipart upload.
        *size* must be the total byte length of the stream.
        *chunk_size* is the per-part size in bytes (default 20 MB).
        Creates a new version if the filename already exists.
        Returns the provider file ref.

        Falls back to upsert_file() for streams smaller than *chunk_size*.
        """

    @abstractmethod
    def download_file(self, file_ref: str) -> bytes:
        """Fetch the content of *file_ref* via the provider API. Returns raw bytes."""

    @abstractmethod
    def get_shareable_url(
        self,
        file_ref: str,
        access: str = "open",
    ) -> Optional[str]:
        """
        Create or retrieve a human-readable shareable link for *file_ref*.
        Returns None if the provider does not support external sharing.
        *access* is provider-specific; supported values: "open", "company", "collaborators".
        """

    @abstractmethod
    def delete_file(self, file_ref: str) -> None:
        """Permanently delete *file_ref*."""


# ---------------------------------------------------------------------------
# CloudStorageLocation  (facade)
# ---------------------------------------------------------------------------


class CloudStorageLocation:
    """
    Facade over a CloudStorageProvider.  Holds (provider, root_ref) and adds a
    structured audit log for every mutating operation.

    Construct via the class-method helpers rather than directly:

        location = CloudStorageLocation.from_user(
            provider_name="box",
            user=box_user,
            root_ref=folder_id,
            audit_data="export_period_marking",
        )
    """

    def __init__(
        self,
        provider: CloudStorageProvider,
        root_ref: str,
        audit_data: str = "",
    ):
        self._provider = provider
        self._root_ref = root_ref
        self._audit_data = audit_data

    # -- Properties ----------------------------------------------------------

    @property
    def provider(self) -> CloudStorageProvider:
        return self._provider

    @property
    def root_ref(self) -> str:
        return self._root_ref

    # -- Construction helpers ------------------------------------------------

    @classmethod
    def from_user(
        cls,
        provider_name: str,
        user,
        root_ref: str,
        audit_data: str = "",
    ) -> "CloudStorageLocation":
        """
        Build a location from a User row's stored OAuth tokens.
        *provider_name* must be registered in the registry (e.g. "box").
        """
        from .registry import get_provider_class

        provider_cls = get_provider_class(provider_name)
        provider = provider_cls.from_user(user)
        return cls(provider, root_ref, audit_data)

    @classmethod
    def from_config(
        cls,
        provider_name: str,
        root_ref: str,
        data: dict,
    ) -> "CloudStorageLocation":
        """
        Build a location from application config (service-account / server-delegated auth).
        *data* is passed to the provider's from_config class method.
        """
        from .registry import get_provider_class

        provider_cls = get_provider_class(provider_name)
        audit_data = data.get("audit_data", "")
        provider = provider_cls.from_config(data)
        return cls(provider, root_ref, audit_data)

    # -- Folder operations ---------------------------------------------------

    def get_or_create_folder(self, parent_ref: Optional[str], name: str) -> str:
        """
        Return the ref for a subfolder named *name* inside *parent_ref*, creating it
        if absent.  Pass parent_ref=None to create the folder directly under root_ref.
        """
        effective_parent = parent_ref if parent_ref is not None else self._root_ref
        t0 = time.monotonic()
        try:
            result = self._provider.get_or_create_folder(effective_parent, name)
            self._log_audit("get_or_create_folder", folder_ref=effective_parent, name=name, elapsed_ms=int((time.monotonic() - t0) * 1000))
            return result
        except Exception as exc:
            self._log_audit(
                "get_or_create_folder", folder_ref=effective_parent, name=name, elapsed_ms=int((time.monotonic() - t0) * 1000), error=repr(exc)
            )
            raise

    def list_folder(self, folder_ref: str) -> List[CloudItem]:
        """Return all items in *folder_ref*. Not audited (read-only)."""
        return self._provider.list_folder(folder_ref)

    # -- File operations -----------------------------------------------------

    def upsert_file(
        self,
        folder_ref: str,
        filename: str,
        data: Union[bytes, BinaryIO],
        mimetype: str = "application/octet-stream",
    ) -> str:
        """Upload *data* as *filename*; version-replace if the name already exists."""
        size = len(data) if isinstance(data, bytes) else None
        t0 = time.monotonic()
        try:
            result = self._provider.upsert_file(folder_ref, filename, data, mimetype)
            self._log_audit("upsert_file", folder_ref=folder_ref, name=filename, bytes=size, elapsed_ms=int((time.monotonic() - t0) * 1000))
            return result
        except Exception as exc:
            self._log_audit(
                "upsert_file", folder_ref=folder_ref, name=filename, bytes=size, elapsed_ms=int((time.monotonic() - t0) * 1000), error=repr(exc)
            )
            raise

    def upsert_file_chunked(
        self,
        folder_ref: str,
        filename: str,
        stream: BinaryIO,
        size: int,
        mimetype: str = "application/octet-stream",
        chunk_size: int = 20 * 1024 * 1024,
    ) -> str:
        """Chunked upload via the provider; audited."""
        t0 = time.monotonic()
        try:
            result = self._provider.upsert_file_chunked(folder_ref, filename, stream, size, mimetype, chunk_size)
            self._log_audit(
                "upsert_file_chunked",
                folder_ref=folder_ref,
                name=filename,
                bytes=size,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
            return result
        except Exception as exc:
            self._log_audit(
                "upsert_file_chunked",
                folder_ref=folder_ref,
                name=filename,
                bytes=size,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=repr(exc),
            )
            raise

    def download_file(self, file_ref: str) -> bytes:
        """Fetch content of *file_ref* via the provider API."""
        t0 = time.monotonic()
        try:
            data = self._provider.download_file(file_ref)
            self._log_audit("download_file", file_ref=file_ref, bytes=len(data), elapsed_ms=int((time.monotonic() - t0) * 1000))
            return data
        except Exception as exc:
            self._log_audit("download_file", file_ref=file_ref, elapsed_ms=int((time.monotonic() - t0) * 1000), error=repr(exc))
            raise

    def get_shareable_url(
        self,
        file_ref: str,
        access: str = "open",
    ) -> Optional[str]:
        """Return a human-readable shareable link. Not audited (read-only)."""
        return self._provider.get_shareable_url(file_ref, access)

    def delete_file(self, file_ref: str) -> None:
        """Permanently delete *file_ref*."""
        t0 = time.monotonic()
        try:
            self._provider.delete_file(file_ref)
            self._log_audit("delete_file", file_ref=file_ref, elapsed_ms=int((time.monotonic() - t0) * 1000))
        except Exception as exc:
            self._log_audit("delete_file", file_ref=file_ref, elapsed_ms=int((time.monotonic() - t0) * 1000), error=repr(exc))
            raise

    # -- Auth error convenience ----------------------------------------------

    def handle_auth_error(self, exc: Exception, notify_user=None) -> bool:
        """
        Check whether *exc* is an auth error for this provider.
        If so — and *notify_user* is given — post a 'please re-link' danger message to that
        user.  Returns True when *exc* was an auth error so the caller can branch on it.
        """
        if not self._provider.is_auth_error(exc):
            return False
        if notify_user is not None:
            try:
                reauth = self._provider.reauth_url()
                msg = (
                    f"Cloud storage export failed: your {self._provider.display_name} "
                    f"account credentials are no longer valid. "
                    f'Please <a href="{reauth}">re-link your {self._provider.display_name} '
                    f"account</a> and try again."
                )
            except Exception:
                msg = (
                    f"Cloud storage export failed: your {self._provider.display_name} "
                    "account credentials are no longer valid. Please re-link your account."
                )
            notify_user.post_message(msg, "danger", autocommit=True)
        return True

    # -- Internal ------------------------------------------------------------

    def _log_audit(self, operation: str, **kwargs) -> None:
        """
        Emit a structured audit record to the Flask app logger.
        A MongoDB backend following the ObjectStore pattern can be wired in here later.
        """
        try:
            from flask import current_app

            parts = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
            current_app.logger.info(
                "cloud_storage audit: op=%s provider=%s audit_data=%s %s",
                operation,
                self._provider.provider_name,
                self._audit_data,
                parts,
            )
        except Exception:
            pass
