#
# Created by David Seery on 17/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import humanize
from flask import current_app

import app.shared.cloud_object_store.encryption_types as encryptions
from .cloud_object_store import ObjectStore, ObjectMeta

_DEFAULT_STREAMING_CHUNKSIZE = 1024 * 1024


class AssetCloudScratchContextManager:
    """
    A context manager for handling temporary asset files in a cloud object store.

    This class provides a context manager interface for managing temporary asset files stored in a cloud object store.
    Upon entering the context, the class initializes with a given path to the asset file. Upon exiting the context,
    the asset file is deleted.

    Attributes:
        _path (pathlib.Path): The path to the asset file.

    Args:
        path (pathlib.Path): The path to the asset file.

    """
    def __init__(self, path: Path):
        self._path = path


    def __enter__(self):
        return self


    def __exit__(self, type, value, traceback) -> None:
        self._path.unlink(missing_ok=True)


    @property
    def path(self) -> Path:
        return self._path


class AssetCloudAdapter:
    """
    AssetCloudAdapter

    This class represents an adapter for interacting with assets stored in a cloud object store. It provides methods for
    manipulating and retrieving assets.

    Attributes:
        _asset (object): The asset object.
        _storage (ObjectStore): The object store used for storage.
        _storage_encrypted (bool): Flag indicating if the storage is encrypted.
        _key_attr (str): The attribute name for the key of the asset object.
        _size_attr (str): The attribute name for the size of the asset object.
        _encryption_attr (str): The attribute name for the encryption type of the asset object.
        _nonce_attr (str): The attribute name for the nonce of the asset object.
        _key (str): The key of the asset in the object store.
        _size (int): The size of the asset.
        _encryption (str): The encryption type of the asset.
        _nonce (bytes): The nonce of the asset.

    Methods:
        record(self) -> object:
            Returns the asset object.

        exists(self) -> bool:
            Checks if the asset exists in the object store.

        get(self) -> bytes:
            Retrieves the asset from the object store.

        delete(self):
            Deletes the asset from the object store.

        duplicate(self, validate_nonce) -> (str, bytes):
            Creates a duplicate of the asset in the object store with a new key and nonce.

        download_to_scratch(self) -> AssetCloudScratchContextManager:
            Downloads the asset to a scratch file for temporary use.

        stream(self, chunksize=_DEFAULT_STREAMING_CHUNKSIZE, no_encryption=False):
            Streams the asset from the object store.
    """
    def __init__(self, asset, storage: ObjectStore, key_attr: str='unique_name', size_attr: str='filesize',
                 encryption_attr: str='encryption', nonce_attr: str='nonce', compressed_attr: str='compressed'):
        self._asset = asset
        self._storage = storage
        self._storage_encrypted = self._storage.encrypted
        self._storage_compressed = self._storage.compressed

        self._key_attr = key_attr
        self._size_attr = size_attr

        self._encryption_attr = encryption_attr
        self._nonce_attr = nonce_attr

        self._compressed_attr = compressed_attr

        self._key = getattr(self._asset, self._key_attr)

        # size refers to the size of the asset before compression and encryption
        self._size = getattr(self._asset, self._size_attr)

        self._encryption = getattr(self._asset, self._encryption_attr)
        self._compressed = getattr(self._asset, self._compressed_attr)
        self._nonce = None

        if hasattr(self._asset, 'bucket'):
            bucket = getattr(self._asset, 'bucket')
            store_bucket = self._storage.database_key
            if bucket != store_bucket:
                raise RuntimeError(f'AssetCloudAdapter: asset was stored in bucket #{bucket}, but the '
                                   f'object storage is #{store_bucket}')

        if self._encryption is not None and self._encryption != encryptions.ENCRYPTION_NONE:
            if not self._storage_encrypted:
                raise RuntimeError('AssetCloudAdapter: asset was stored with encryption, '
                                   'but object storage is not encrypted')

            if self._storage.encryption_type != self._encryption:
                raise RuntimeError(f'AssetCloudAdapter: asset was stored with encryption type '
                                   f'#{self._encryption}, but object storage has encryption type '
                                   f'#{self._storage.encryption_type}')

            if self._storage.uses_nonce:
                base64_nonce = getattr(self._asset, self._nonce_attr)
                self._nonce = base64.urlsafe_b64decode(base64_nonce)


    def record(self):
        return self._asset


    def exists(self):
        blobs = self._storage.list()
        return self._key in blobs


    def get(self):
        if self._encryption == encryptions.ENCRYPTION_NONE:
            return self._storage.get(self._key, None, no_encryption=True,
                                     decompress=self._compressed, initial_buf_size=self._size)

        return self._storage.get(self._key, self._nonce, decompress=self._compressed, initial_buf_size=self._size)


    def delete(self):
        self._storage.delete(self._key)


    def duplicate(self, validate_nonce):
        new_key = str(uuid4())

        # if the file is not encrypted then we can duplicate it directly using an API call.
        # Otherwise, we want to re-encrypt it using a new nonce, so that we do not duplicate nonces.
        # That means we have to download and re-upload using a new nonce.

        # no need to check if storage is encrypted; if it isn't, and we are set to ENCRYPTION_NONE, an exception
        # will have been raised in the constructor
        if self._encryption == encryptions.ENCRYPTION_NONE:
            new_nonce = None
            self._storage.copy(self._key, new_key)
        else:
            meta: ObjectMeta = self._storage.head(self._key)
            data: bytes = self.get()
            new_nonce: bytes = self._storage.put(new_key, data, mimetype=meta.mimetype, validate_nonce=validate_nonce)

        return new_key, new_nonce


    def download_to_scratch(self):
        scratch_folder = Path(current_app.config.get('SCRATCH_FOLDER'))
        scratch_file = str(uuid4())
        scratch_path = scratch_folder / scratch_file

        with open(scratch_path, 'wb') as f:
            f.write(self.get())

        return AssetCloudScratchContextManager(scratch_path)


    def stream(self, chunksize=_DEFAULT_STREAMING_CHUNKSIZE, no_encryption=False):
        # no need to check if storage is encrypted; if it isn't, and we are set to ENCRYPTION_NONE, an exception
        # will have been raised in the constructor
        if self._encryption != encryptions.ENCRYPTION_NONE:
            raise RuntimeError('AssetCloudAdapter: it is not possible to use streaming with an encrypted asset. '
                               'Download the entire asset to obtain a decrypted copy.')

        if self._compressed:
            raise RuntimeError('AssetCloudAdapter: it is not possible to use streaming with a compressed asset. '
                               'Download the entire asset to obtain a decompressed copy.')

        # adapted from https://stackoverflow.com/questions/43215889/downloading-a-file-from-an-s3-bucket-to-the-users-computer
        offset = 0
        total_bytes = self._size

        while total_bytes > 0:
            start = offset
            length = chunksize if chunksize < total_bytes else total_bytes

            offset += length
            total_bytes -= length

            yield self._storage.get_range(self._key, start=start, length=length)


class AssetUploadManager:
    """
    The AssetUploadManager class is responsible for managing the upload of assets to the object store.

    :param asset: The asset to be uploaded.
    :param data: The byte data of the asset.
    :param storage: The object store where the asset will be uploaded.
    :param key: The unique key of the asset.
    :param length: The length of the asset in bytes.
    :param mimetype: The mimetype of the asset.
    :param key_attr: The attribute name to store the asset key in the asset object.
    :param size_attr: The attribute name to store the asset size in the asset object.
    :param mimetype_attr: The attribute name to store the asset mimetype in the asset object.
    :param encryption_attr: The attribute name to store the asset encryption type in the asset object.
    :param nonce_attr: The attribute name to store the asset nonce in the asset object.
    :param comment: A comment to be associated with the asset.
    :param validate_nonce: A flag indicating whether to validate the nonce during encryption.
    """
    def __init__(self, asset, data, storage: ObjectStore, key=None, length=None, mimetype=None,
                 key_attr: str='unique_name', size_attr: str='filesize',
                 mimetype_attr: str='mimetype', encryption_attr: str='encryption',
                 nonce_attr: str='nonce', compressed_attr: str='compressed',
                 comment: str=None, validate_nonce=None):
        self._asset = asset

        if key is None:
            self._key = str(uuid4())
        else:
            self._key = key

        self._key_attr = key_attr
        self._size_attr = size_attr
        self._mimetype_attr = mimetype_attr

        self._encryption_attr = encryption_attr
        self._nonce_attr = nonce_attr

        self._compressed_attr = compressed_attr

        self._storage = storage

        setattr(self._asset, self._key_attr, self._key)

        if length is None:
            if isinstance(data, bytes):
                length = len(data)
            elif isinstance(data, BytesIO):
                length = data.getbuffer().nbytes

        if length is not None and self._size_attr is not None:
            setattr(self._asset, self._size_attr, length)

        if mimetype is not None and self._mimetype_attr is not None:
            setattr(self._asset, self._mimetype_attr, mimetype)

        nonce: data = self._storage.put(self._key, data, mimetype=mimetype, validate_nonce=validate_nonce)
        if self._storage.encrypted and nonce is None:
            raise RuntimeError('AssetUploadManager: object storage is marked as encrypted, but '
                               'return nonce is None')

        if hasattr(self._asset, self._encryption_attr):
            if self._storage.encrypted:
                setattr(self._asset, self._encryption_attr, self._storage.encryption_type)
            else:
                setattr(self._asset, self._encryption_attr, encryptions.ENCRYPTION_NONE)
        if hasattr(self._asset, self._nonce_attr):
            if nonce is not None:
                base64_nonce = base64.urlsafe_b64encode(nonce).decode('ascii')
            else:
                base64_nonce = None
            setattr(self._asset, self._nonce_attr, base64_nonce)

        if hasattr(self._asset, self._compressed_attr):
            setattr(self._asset, self._compressed_attr, self._storage.compressed)

        meta: ObjectMeta = self._storage.head(self._key)
        if self._size_attr is not None:
            if length is None or length == 0:
                print(f'AssetUploadManager: self._asset has zero length; ObjectMeta reports '
                      f'length = {humanize.naturalsize((meta.size))}')
                setattr(self._asset, self._size_attr, meta.size)

            elif length != meta.size:
                print(f'AssetUploadManager: user-supplied filesize ({humanize.naturalsize(length)}) '
                      f'does not match ObjectMeta size reported from cloud '
                      f'backend ({humanize.naturalsize(meta.size)}). This is normal is encryption is being used.')

        if hasattr(self._asset, 'lost'):
            setattr(self._asset, 'lost', False)
        if hasattr(self._asset, 'unattached'):
            setattr(self._asset, 'unattached', False)

        if hasattr(self._asset, 'bucket'):
            setattr(self._asset, 'bucket', storage.database_key)
        if hasattr(self._asset, 'comment'):
            setattr(self._asset, 'comment', comment)


    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass
