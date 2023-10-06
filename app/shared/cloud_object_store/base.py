#
# Created by David Seery on 09/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from io import BytesIO
from pathlib import Path
from typing import Dict, Union, List, Optional
from urllib.parse import urlsplit, SplitResult

from .drivers.amazons3 import AmazonS3CloudStorageDriver
from .drivers.google import GoogleCloudStorageDriver
from .drivers.local import LocalFileSystemDriver
from .meta import ObjectMeta

_drivers = {'file': LocalFileSystemDriver,
            'gs': GoogleCloudStorageDriver,
            's3': AmazonS3CloudStorageDriver}


PathLike = Union[str, List[str], Path]
BytesLike = Union[bytes, BytesIO]

DELIMITER = "/"


def _as_path(raw: PathLike) -> Path:
    if isinstance(raw, str):
        return Path(raw)
    if isinstance(raw, list):
        return Path(DELIMITER.join(raw))
    if isinstance(raw, Path):
        return raw
    raise ValueError(f"Cannot convert type {type(raw)} to type Path.")


def _as_bytes(raw: BytesLike) -> bytes:
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, BytesIO):
        return raw.read()
    raise ValueError(f"Cannot convert type {type(raw)} to type bytes.")


class EncryptionPipeline:

    @property
    def uses_nonce(self) -> bool:
        pass

    @property
    def database_key(self) -> int:
        pass

    def make_nonce(self) -> bytes:
        pass

    def encrypt(self, nonce: BytesLike, data: BytesLike) -> bytes:
        pass

    def decrypt(self, none: BytesLike, data: BytesLike) -> bytes:
        pass


class Driver:

    def get(self, key: PathLike) -> bytes:
        pass

    def get_range(self, key: PathLike, start: int, length: int) -> BytesLike:
        pass

    def put(self, key: PathLike, data: BytesLike, mimetype: Optional[str] = None) -> None:
        pass

    def delete(self, key: PathLike) -> None:
        pass

    def list(self, prefix: Optional[PathLike] = None) -> List[ObjectMeta]:
        pass

    def copy(self, src: PathLike, dst: PathLike) -> None:
        pass

    def head(self, key: PathLike) -> ObjectMeta:
        pass


class ObjectStore:

    def __init__(self, uri: PathLike, database_key: int, data: Dict=None):
        self._database_key = database_key

        uri_elements: SplitResult = urlsplit(uri)

        scheme = uri_elements.scheme
        if scheme not in _drivers:
            print('cloud_object_store: unsupported URI scheme "{scheme}"'.format(scheme=scheme))

        self._encryption_pipeline: EncryptionPipeline
        self._encryption_pipeline = None
        if 'encryption_pipeline' in data:
            self._encryption_pipeline = data['encryption_pipeline']
            del data['encryption_pipeline']

        driver_type: Driver = _drivers[scheme]
        self._driver = driver_type(uri_elements, data)

    @property
    def database_key(self) -> int:
        return self._database_key

    @property
    def encrypted(self) -> bool:
        return self._encryption_pipeline is not None

    @property
    def uses_nonce(self) -> bool:
        if not self.encrypted:
            return None

        return self._encryption_pipeline.uses_nonce

    @property
    def encryption_type(self) -> Optional[int]:
        if not self.encrypted:
            return None

        return self._encryption_pipeline.database_key

    def get(self, key: PathLike, nonce: Optional[BytesLike] = None, no_encryption=False) -> bytes:
        data: bytes = self._driver.get(_as_path(key))

        if self._encryption_pipeline is None or no_encryption:
            return data

        if self._encryption_pipeline.uses_nonce and nonce is None:
            raise RuntimeError('ObjectStore: the encryption pipeline expects a nonce, but none was provided')

        return self._encryption_pipeline.decrypt(nonce, data)

    def get_range(self, key: PathLike, start: int, length: int, no_encryption=False) -> bytes:
        if self.encrypted and not no_encryption:
            raise RuntimeError('ObjectStore: you cannot use get_range() with an encrypted object store. '
                               'Download the object completely using get() to decrypt it.')

        return self._driver.get_range(_as_path(key), start=start, length=length)

    def put(self, key: PathLike, data: BytesLike, mimetype: Optional[str] = None,
            validate_nonce=None, no_encryption=False) -> Optional[bytes]:
        nonce = None
        if self._encryption_pipeline is not None and not no_encryption:
            attempts = 0
            while nonce is None:
                if attempts > 100:
                    raise RuntimeError('ObjectStore: failed to find acceptable nonce after 100 attempts')

                nonce = self._encryption_pipeline.make_nonce()
                if not validate_nonce(nonce):
                    attempts += 1
                    nonce = None

            put_data: bytes = self._encryption_pipeline.encrypt(nonce, _as_bytes(data))
        else:
            put_data: bytes = _as_bytes(data)

        self._driver.put(_as_path(key), put_data, mimetype, nonce)
        return nonce

    def delete(self, key: PathLike) -> None:
        return self._driver.delete(_as_path(key))

    def copy(self, src: PathLike, dst: PathLike) -> None:
        if self._encryption_pipeline is not None:
            raise RuntimeError('ObjectStore: can not use copy with an encrypted store. '
                               'Downnload and re-upload the file to generate a unique encrypted duplicate.')
        return self._driver.copy(_as_path(src), _as_path(dst))

    def list(self, prefix: Optional[PathLike] = None) -> Dict[str, ObjectMeta]:
        return self._driver.list(prefix=prefix)

    def head(self, key: PathLike) -> ObjectMeta:
        return self._driver.head(_as_path(key))
