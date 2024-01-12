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
from typing import Dict, Union, List, Optional, Mapping, Type
from urllib.parse import urlsplit, SplitResult
from zlib import compress as zlib_compress
from zlib import decompress as zlib_decompress

from .drivers.amazons3 import AmazonS3CloudStorageDriver
from .drivers.google import GoogleCloudStorageDriver
from .drivers.local import LocalFileSystemDriver
from .meta import ObjectMeta
from .audit import AuditBackend
from .audit_backends.mongodb import MongoDBAuditBackend

_drivers = {'file': LocalFileSystemDriver,
            'gs': GoogleCloudStorageDriver,
            's3': AmazonS3CloudStorageDriver}

_audit_backends = {'mongodb': MongoDBAuditBackend}


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
        raise NotImplementedError(
            'The uses_nonce() method should be implemented by concrete EncryptionPipeline instances')

    @property
    def database_key(self) -> int:
        raise NotImplementedError(
            'The database_key() method should be implemented by concrete EncryptionPipeline instances')

    def make_nonce(self) -> bytes:
        pass

    def encrypt(self, nonce: BytesLike, data: BytesLike) -> bytes:
        raise NotImplementedError(
            'The encrypt() method should be implemented by concrete EncryptionPipeline instances')

    def decrypt(self, none: BytesLike, data: BytesLike) -> bytes:
        raise NotImplementedError(
            'The decrypt() method should be implemented by concrete EncryptionPipeline instances')


class Driver:

    def __init__(self, uri: SplitResult, data: Dict):
        pass

    def get_driver_name(self):
        raise NotImplementedError('The get_driver_name() method should be implemented by concrete Driver instances')

    def get_bucket_name(self):
        raise NotImplementedError('The get_bucket_name() method should be implemented by concrete Driver instances')

    def get_host_uri(self):
        raise NotImplementedError('The get_host_uri() method should be implemented by concrete Driver instances')

    def get(self, key: PathLike) -> bytes:
        raise NotImplementedError('The get() method should be implemented by concrete Driver instances')

    def get_range(self, key: PathLike, start: int, length: int) -> BytesLike:
        raise NotImplementedError('The get_range() method should be implemented by concrete Driver instances')

    def put(self, key: PathLike, data: BytesLike, mimetype: Optional[str] = None) -> None:
        raise NotImplementedError('The put() method should be implemented by concrete Driver instances')

    def delete(self, key: PathLike) -> None:
        raise NotImplementedError('The delete() method should be implemented by concrete Driver instances')

    def list(self, prefix: Optional[PathLike] = None) -> Dict[str, ObjectMeta]:
        raise NotImplementedError('The list() method should be implemented by concrete Driver instances')

    def copy(self, src: PathLike, dst: PathLike) -> None:
        raise NotImplementedError('The copy() method should be implemented by concrete Driver instances')

    def head(self, key: PathLike) -> ObjectMeta:
        raise NotImplementedError('The head() method should be implemented by concrete Driver instances')


class ObjectStore:

    def __init__(self, uri: PathLike, database_key: int, data: Dict):
        self._database_key = database_key

        uri_elements: SplitResult = urlsplit(uri)

        scheme = uri_elements.scheme
        if scheme not in _drivers:
            raise NotImplementedError(f'cloud_object_store: unsupported URI scheme "{scheme}"')

        self._encryption_pipeline: EncryptionPipeline
        self._encryption_pipeline = data.get('encryption_pipeline', None)
        if 'encryption_pipeline' in data:
            del data['encryption_pipeline']

        # enable/disable transparent compression based on user setting in data
        self._compressed = data.get('compressed', False)
        if 'compressed' in data:
            del data['compressed']

        # generate driver instance
        driver_type: Type[Driver] = _drivers[scheme]
        self._driver = driver_type(uri_elements, data)

        # cache bucketname and uri for use in audit
        self._driver_name = self._driver.get_driver_name()
        self._bucket_name = self._driver.get_bucket_name()
        self._host_uri = self._driver.get_host_uri()

        # enable/disable API auditing based on user setting in data
        self._audit = data.get('audit', False)
        if 'audit' in data:
            del data['audit']

        if 'audit_backend' in data and data['audit_backend'] is not None:
            backend_uri_elements: SplitResult = urlsplit(data['audit_backend'])

            backend_scheme = backend_uri_elements.scheme
            if backend_scheme not in _audit_backends:
                raise NotImplementedError(f'cloud_object_store: unsupported audit backend URI scheme "{backend_scheme}"')

            audit_backend_type: Type[AuditBackend] = _audit_backends[backend_scheme]
            self._audit_backend = audit_backend_type(backend_uri_elements, data)
        else:
            self._audit_backend = None

    @property
    def database_key(self) -> int:
        return self._database_key

    @property
    def encrypted(self) -> bool:
        return self._encryption_pipeline is not None

    @property
    def uses_nonce(self) -> Optional[bool]:
        if not self.encrypted:
            return None

        return self._encryption_pipeline.uses_nonce

    @property
    def encryption_type(self) -> Optional[int]:
        if not self.encrypted:
            return None

        return self._encryption_pipeline.database_key

    @property
    def compressed(self) -> bool:
        return self._compressed

    def get(self, key: PathLike, audit_data: str, nonce: Optional[BytesLike] = None, no_encryption=False,
            decompress=None, initial_buf_size=None) -> bytes:
        data: bytes = self._driver.get(_as_path(key))

        # generate audit record if auditing is enabled
        if self._audit and self._audit_backend is not None:
            self._audit_backend.store_audit_record('get', audit_data, driver=self._driver_name,
                                                   bucket=self._bucket_name, host_uri=self._host_uri)

        if self._encryption_pipeline is not None and not no_encryption:
            if self._encryption_pipeline.uses_nonce and nonce is None:
                raise RuntimeError('ObjectStore: the configured encryption pipeline expects a nonce, '
                                   'but none was provided')

            decrypt_data: bytes = self._encryption_pipeline.decrypt(nonce, data)
        else:
            decrypt_data: bytes = data

        # if decompress is specified, it takes priority
        # otherwise, we decompress depending on the value assigned to this object store
        # note condition is not[ (decompress is None and self._compressed) or decompress ]
        if (decompress is not None or not self._compressed) and not decompress:
            return decrypt_data

        return zlib_decompress(decrypt_data, bufsize=initial_buf_size)

    def get_range(self, key: PathLike, audit_data: str, start: int, length: int, no_encryption=False) -> bytes:
        if self.encrypted and not no_encryption:
            raise RuntimeError('ObjectStore: you cannot use get_range() with an encrypted object store. '
                               'Download the object completely using get() to decrypt it.')

        if self.compressed:
            raise RuntimeError('ObjectStore: you cannot use get_range() with a compressed object store. '
                               'Download the object completely using get() to decompress it.')

        data = self._driver.get_range(_as_path(key), start=start, length=length)

        # generate audit record if auditing is enabled
        if self._audit and self._audit_backend is not None:
            self._audit_backend.store_audit_record('get_range', audit_data, driver=self._driver_name,
                                                   bucket=self._bucket_name, host_uri=self._host_uri)

        return data

    def put(self, key: PathLike, audit_data: str, data: BytesLike, mimetype: Optional[str] = None,
            validate_nonce=None, no_encryption=False, no_compress=False) -> Mapping:
        compressed_size = None
        encrypted_size = None

        if self.compressed and not no_compress:
            compress_data: bytes = zlib_compress(_as_bytes(data))
            compressed_size = len(compress_data)
        else:
            compress_data: bytes = _as_bytes(data)

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

            put_data: bytes = self._encryption_pipeline.encrypt(nonce, compress_data)
            encrypted_size = len(put_data)
        else:
            put_data: bytes = compress_data

        self._driver.put(_as_path(key), put_data, mimetype)

        # generate audit record if auditing is enabled
        if self._audit and self._audit_backend is not None:
            self._audit_backend.store_audit_record('put', audit_data, driver=self._driver_name,
                                                   bucket=self._bucket_name, host_uri=self._host_uri)

        return {'nonce': nonce,
                'encrypted_size': encrypted_size,
                'compressed_size': compressed_size}

    def delete(self, key: PathLike, audit_data: str) -> None:
        self._driver.delete(_as_path(key))

        # generate audit record if auditing is enabled

        # generate audit record if auditing is enabled
        if self._audit and self._audit_backend is not None:
            self._audit_backend.store_audit_record('delete', audit_data, driver=self._driver_name,
                                                   bucket=self._bucket_name, host_uri=self._host_uri)

    def copy(self, src: PathLike, dst: PathLike, audit_data: str) -> None:
        if self._encryption_pipeline is not None:
            raise RuntimeError('ObjectStore: can not use copy with an encrypted store. '
                               'Downnload and re-upload the file to generate a unique encrypted duplicate.')

        self._driver.copy(_as_path(src), _as_path(dst))

        # generate audit record if auditing is enabled

        # generate audit record if auditing is enabled
        if self._audit and self._audit_backend is not None:
            self._audit_backend.store_audit_record('copy', audit_data, driver=self._driver_name,
                                                   bucket=self._bucket_name, host_uri=self._host_uri)

    def list(self, audit_data: str, prefix: Optional[PathLike] = None) -> Dict[str, ObjectMeta]:
        data = self._driver.list(prefix=prefix)

        # generate audit record if auditing is enabled
        if self._audit:

            # generate audit record if auditing is enabled
            if self._audit and self._audit_backend is not None:
                self._audit_backend.store_audit_record('list', audit_data, driver=self._driver_name,
                                                       bucket=self._bucket_name, host_uri=self._host_uri)

        return data

    def head(self, key: PathLike, audit_data: str) -> ObjectMeta:
        data = self._driver.head(_as_path(key))

        # generate audit record if auditing is enabled
        if self._audit:

            # generate audit record if auditing is enabled
            if self._audit and self._audit_backend is not None:
                self._audit_backend.store_audit_record('head', audit_data, driver=self._driver_name,
                                                       bucket=self._bucket_name, host_uri=self._host_uri)

        return data
