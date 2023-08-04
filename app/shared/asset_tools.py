#
# Created by David Seery on 17/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from pathlib import Path
from uuid import uuid4

from flask import current_app
from object_store import ObjectStore
from object_store._internal import ObjectMeta

_DEFAULT_STREAMING_CHUNKSIZE = 1024 * 1024


class AssetCloudScratchContextManager:

    def __init__(self, path: Path):
        self._path = path


    def __enter__(self):
        pass


    def __exit__(self, type, value, traceback):
        self._path.unlink(missing_ok=True)


    @property
    def path(self):
        return self._path


class AssetCloudAdapter:

    def __init__(self, asset, storage: ObjectStore):
        self._asset = asset
        self._storage = storage

        self._key = self._asset.unique_name
        self._size = self._asset.filesize


    def record(self):
        return self._asset


    def exists(self):
        blobs = self._storage.list()
        return self._key in blobs


    def get(self):
        return self._storage.get(self._key)


    def delete(self):
        self._storage.delete(self._key)


    def duplicate(self):
        new_key = str(uuid4())
        self._storage.copy(self._key, new_key)
        return new_key


    def download_to_scratch(self):
        scratch_folder = Path(current_app.config.get('SCRATCH_FOLDER'))
        scratch_file = str(uuid4())
        scratch_path = scratch_folder / scratch_file

        with open(scratch_path, 'wb') as f:
            f.write(self.get())

        return AssetCloudScratchContextManager(scratch_path)


    def stream(self, chunksize=_DEFAULT_STREAMING_CHUNKSIZE):
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

    def __init__(self, asset, bytes, storage: ObjectStore, length=None, mimetype=None):
        self._asset = asset
        self._key = str(uuid4())

        self._storage = storage

        self._asset.unique_name = self._key

        if length is not None and hasattr(self._asset, 'filesize'):
            self._asset.filesize = length

        if mimetype is not None and hasattr(self._asset, 'mimetype'):
            self._asset.mimetype = mimetype

        self._storage.put(self._key, bytes)

        meta: ObjectMeta = self._storage.head(self._key)
        if self._asset.filesize is None or self._asset.filesize == 0:
            print('AssetUploadManager: self._asset has zero length; ObjectMeta reports '
                  'length = {len}'.format(len=meta.size))
            self._asset.filesize = meta.size

        elif self._asset.filesize != meta.size:
            print('AssetUploadManager: user-supplied filesize ({user}) does not match ObjectMeta size reported from '
                  'backend ({cloud})'.format(user=self._asset.filesize, cloud=meta.size))


    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        pass
