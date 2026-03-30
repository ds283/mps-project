#
# Created by David Seery on 07/08/2023$.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import shutil
from pathlib import Path
from typing import Iterable, Tuple, Union
from uuid import uuid4

from flask import current_app


class ScratchFileManager:
    def __init__(self, suffix: str = None):
        folder = Path(current_app.config.get("SCRATCH_FOLDER"))
        name = str(uuid4())
        self._path: Path = folder / name

        if suffix is not None:
            self._path = self._path.with_suffix(suffix)

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        self._path.unlink(missing_ok=True)

    @property
    def path(self) -> Path:
        return self._path


class ScratchFolderManager:
    """
    Context manager for a temporary directory inside the app's scratch folder.
    The directory and all its contents are deleted when the context exits.
    Intended as a cache directory for tools such as preview-generator that
    need a writable folder but must not accumulate files on the container filesystem.
    """

    def __init__(self):
        scratch = Path(current_app.config.get("SCRATCH_FOLDER"))
        self._path: Path = scratch / str(uuid4())
        self._path.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        shutil.rmtree(self._path, ignore_errors=True)

    @property
    def path(self) -> Path:
        return self._path


# lightweight context-manager-like object that can be passed around Celery tasks without
# incurring a large serialization/deserialization cost.
# We store state as str rather than Path, to avoid problems with serializing PosixPath instances
class ScratchGroupManager:
    def __init__(self, folder: Union[Path, str, None]):
        if folder is not None:
            self._folder: str = str(folder)
        else:
            self._folder = None

        self._files = {}

    def copy(self, key: str, src: Path, suffix: str = None):
        name = str(uuid4())
        path: Path = Path(self._folder) / name

        # emplace the new file
        path.write_bytes(src.read_bytes())

        self._files[key] = str(path)

    def get(self, key: str, default=None) -> Path:
        if key in self._files:
            return Path(self._files[key])

        return default

    def keys(self) -> Iterable[str]:
        return self._files.keys()

    def values(self) -> Iterable[Path]:
        return [Path(p) for p in self._files.values()]

    def items(self) -> Iterable[Tuple[str, Path]]:
        return [(key, Path(p)) for key, p in self._files.items()]

    def cleanup(self):
        for p in self._files.values():
            Path(p).unlink(missing_ok=True)
