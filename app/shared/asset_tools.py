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
from .cloud_object_store import ObjectStore, ObjectMeta


_DEFAULT_STREAMING_CHUNKSIZE = 1024 * 1024


class AssetCloudScratchContextManager:
    """

    AssetCloudScratchContextManager
    -------------------------------

    The `AssetCloudScratchContextManager` class allows for managing scratch files in an asset cloud.

    Methods
    -------

    __init__(path: Path)
        Initializes a new instance of the `AssetCloudScratchContextManager` class.

    __enter__()
        This method is called when entering the context of the `AssetCloudScratchContextManager`.

    __exit__(type, value, traceback)
        This method is called when exiting the context of the `AssetCloudScratchContextManager`.

    Properties
    ----------

    path
        Gets the path of the scratch file.

    """
    def __init__(self, path: Path):
        self._path = path


    def __enter__(self):
        return self


    def __exit__(self, type, value, traceback):
        self._path.unlink(missing_ok=True)


    @property
    def path(self):
        return self._path


class AssetCloudAdapter:
    """

    The `AssetCloudAdapter` class is used to interface with an object store for managing assets.

    Attributes:
        - `_asset`: The asset object that the adapter is responsible for
        - `_storage`: The object store used for storing and retrieving assets
        - `_key_attr`: The attribute of the asset object that represents the key or unique identifier
        - `_size_attr`: The attribute of the asset object that represents the size or filesize
        - `_key`: The key or unique identifier of the asset
        - `_size`: The size or filesize of the asset

    Methods:
        - `record()`: Returns the asset object associated with the adapter
        - `exists()`: Checks if the asset exists in the object store
        - `get()`: Retrieves the asset from the object store
        - `delete()`: Deletes the asset from the object store
        - `duplicate()`: Creates a duplicate of the asset in the object store with a new key
        - `download_to_scratch()`: Downloads the asset to a scratch folder on the local filesystem
        - `stream(chunksize=_DEFAULT_STREAMING_CHUNKSIZE)`: Streams the asset data in chunks

    """
    def __init__(self, asset, storage: ObjectStore, key_attr: str='unique_name', size_attr: str='filesize'):
        self._asset = asset
        self._storage = storage

        self._key_attr = key_attr
        self._size_attr = size_attr

        self._key = getattr(self._asset, self._key_attr)
        self._size = getattr(self._asset, self._size_attr)


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
    """
    :class: AssetUploadManager

    A class that manages the upload of assets to an object store.

    :param asset: The asset object to be uploaded.
    :type asset: Any

    :param bytes: The bytes of the asset to be uploaded.
    :type bytes: bytes

    :param storage: The object store that the asset will be uploaded to.
    :type storage: ObjectStore

    :param length: The length of the asset in bytes. Default is None.
    :type length: Optional[int]

    :param mimetype: The mimetype of the asset. Default is None.
    :type mimetype: Optional[str]

    :param key_attr: The attribute name to store the unique key of the uploaded asset. Default is 'unique_name'.
    :type key_attr: str

    :param size_attr: The attribute name to store the size of the uploaded asset. Default is 'filesize'.
    :type size_attr: str

    :param mimetype_attr: The attribute name to store the mimetype of the uploaded asset. Default is 'mimetype'.
    :type mimetype_attr: str

    :ivar _asset: The asset object to be uploaded.
    :vartype _asset: Any

    :ivar _key: The unique key of the uploaded asset.
    :vartype _key: str

    :ivar _key_attr: The attribute name to store the unique key of the uploaded asset.
    :vartype _key_attr: str

    :ivar _size_attr: The attribute name to store the size of the uploaded asset.
    :vartype _size_attr: str

    :ivar _mimetype_attr: The attribute name to store the mimetype of the uploaded asset.
    :vartype _mimetype_attr: str

    :ivar _storage: The object store that the asset will be uploaded to.
    :vartype _storage: ObjectStore
    """
    def __init__(self, asset, bytes, storage: ObjectStore, key=None, length=None, mimetype=None,
                 key_attr: str='unique_name', size_attr: str='filesize',
                 mimetype_attr: str='mimetype'):
        self._asset = asset

        if key is None:
            self._key = str(uuid4())
        else:
            self._key = key

        self._key_attr = key_attr
        self._size_attr = size_attr
        self._mimetype_attr = mimetype_attr

        self._storage = storage

        setattr(self._asset, self._key_attr, self._key)

        if length is not None and self._size_attr is not None:
            setattr(self._asset, self._size_attr, length)

        if mimetype is not None and self._mimetype_attr is not None:
            setattr(self._asset, self._mimetype_attr, mimetype)

        self._storage.put(self._key, bytes, mimetype=mimetype)

        meta: ObjectMeta = self._storage.head(self._key)
        if self._size_attr is not None:
            recorded_size = getattr(self._asset, self._size_attr)

            if recorded_size is None or recorded_size == 0:
                print('AssetUploadManager: self._asset has zero length; ObjectMeta reports '
                      'length = {len}'.format(len=meta.size))
                setattr(self._asset, self._size_attr, meta.size)

            elif recorded_size != meta.size:
                print('AssetUploadManager: user-supplied filesize ({user}) does not match ObjectMeta size reported from '
                      'backend ({cloud})'.format(user=self._asset.filesize, cloud=meta.size))
                setattr(self._asset, self._size_attr, meta.size)


    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass
