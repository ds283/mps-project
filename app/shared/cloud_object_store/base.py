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

from .meta import ObjectMeta
from .drivers.local import LocalFileSystemDriver
from .drivers.google import GoogleCloudStorageDriver
from .drivers.amazons3 import AmazonS3CloudStorageDriver

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


class Driver:

    def get(self, key: PathLike) -> bytes:
        pass

    def get_range(self, key: PathLike, start: int, length: int) -> bytes:
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

    def __init__(self, uri: PathLike, data: Dict=None):
        uri_elements: SplitResult = urlsplit(uri)

        scheme = uri_elements.scheme
        if scheme not in _drivers:
            print('cloud_object_store: unsupported URI scheme "{scheme}"'.format(scheme=scheme))

        driver_type: Driver = _drivers[scheme]
        self._driver = driver_type(uri_elements, data)


    def get(self, key: PathLike) -> bytes:
        return self._driver.get(_as_path(key))


    def get_range(self, key: PathLike, start: int, length: int) -> bytes:
        return self._driver.get_range(_as_path(key), start=start, length=length)


    def put(self, key: PathLike, data: BytesLike, mimetype: Optional[str] = None) -> None:
        return self._driver.put(_as_path(key), _as_bytes(data), mimetype)


    def delete(self, key: PathLike) -> None:
        return self._driver.delete(_as_path(key))


    def copy(self, src: PathLike, dst: PathLike) -> None:
        return self._driver.copy(_as_path(src), _as_path(dst))


    def list(self, prefix: Optional[PathLike] = None) -> Dict[str, ObjectMeta]:
        return self._driver.list(prefix=prefix)


    def head(self, key: PathLike) -> ObjectMeta:
        return self._driver.head(_as_path(key))
