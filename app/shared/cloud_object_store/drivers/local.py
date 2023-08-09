#
# Created by David Seery on 09/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from pathlib import Path
from typing import Dict
from urllib.parse import SplitResult

from ..meta import ObjectMeta


def _check_is_object(prefix: Path, leaf: Path) -> None:
    abs_path = prefix / leaf

    if not abs_path.exists():
        raise RuntimeError('cloud_object_store: could not find asset with specified key="{key}"'.format(key=leaf))

    if not abs_path.is_file():
        raise RuntimeError('cloud_object_store: asset with specified key="{key}" is not a stored '
                           'object'.format(key=leaf))

    return abs_path


def _check_prefix_ok(prefix: Path, leaf: Path) -> None:
    if leaf is not None:
        abs_path = prefix / leaf
    else:
        abs_path = prefix

    if not abs_path.exists():
        return

    if abs_path.is_file():
        raise RuntimeError('cloud_object_store: prefix="{prefix}" conflicts with an asset key'.format(prefix=leaf))

    return abs_path


def _check_not_exists(prefix: Path, leaf: Path) -> None:
    abs_path = prefix / leaf

    if abs_path.exists():
        raise RuntimeError('cloud_object_store: an asset with key="{key}" already exists in the '
                           'store'.format(key=leaf))

    return abs_path


class LocalFileSystemDriver:

    def __init__(self, uri: SplitResult, data: Dict):

        if uri.hostname is not None and len(uri.hostname) > 0:
            print('cloud_object_store: hostname is not supported for file:// handler '
                  '(hostname={name})'.format(name=uri.hostname))

        self._root = Path(uri.path).resolve()

        if self._root.is_file():
            raise RuntimeError('cloud_object_store: supplied file:// root is a file, not a directory '
                               '({path})'.format(path=self._root))

        if not self._root.exists():
            self._root.mkdir(parents=True)


    def get(self, key: Path) -> bytes:
        abs_path: Path = _check_is_object(self._root, key)
        return abs_path.read_bytes()


    def get_range(self, key: Path, start: int, length: int) -> bytes:
        abs_path: Path = _check_is_object(self._root, key)
        with open(abs_path, 'rb') as f:
            f.seek(start, 0)
            return f.read(length)


    def put(self, key: Path, data: bytes, mimetype: str = None) -> None:
        abs_path: Path = _check_not_exists(self._root, key)
        with open(abs_path, 'wb') as f:
            f.write(data)


    def delete(self, key: Path) -> None:
        abs_path: Path = _check_is_object(self._root, key)
        abs_path.unlink(missing_ok=True)


    def copy(self, src: Path, dst: Path) -> None:
        src_path: Path = _check_is_object(self._root, src)
        dst_path: Path = _check_not_exists(self._root, dst)

        dst_path.write_bytes(src_path.read_bytes())


    def list(self, prefix: Path=None) -> Dict[str, ObjectMeta]:
        abs_prefix: Path = _check_prefix_ok(self._root, prefix)

        data = {}

        if not abs_prefix.exists():
            return data

        for item in abs_prefix.rglob("*"):
            if item.is_file():
                key = item.relative_to(self._root)
                meta: ObjectMeta = self.head(key)
                data[str(key)] = meta

        return data


    def head(self, key: Path) -> ObjectMeta:
        abs_path: Path = _check_is_object(self._root, key)

        data: ObjectMeta = ObjectMeta()
        data.location = key
        data.size = abs_path.stat().st_size

        return data