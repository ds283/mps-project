#
# Created by David Seery on 09/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from pathlib import Path
from typing import Dict
from urllib.parse import SplitResult

from google.cloud.storage import Client, Bucket, Blob
from google.oauth2 import service_account

from ..meta import ObjectMeta


class GoogleCloudStorageDriver:

    def __init__(self, uri: SplitResult, data: Dict):

        if data is None \
                or not isinstance(data, dict) \
                or 'google_service_account' not in data:
            raise RuntimeError('cloud_object_store: google_service_account credentials must be supplied')

        credentials_file = Path(data['google_service_account']).resolve()
        with open(credentials_file) as f:
            credentials_data = json.load(f)

        credentials = service_account.Credentials.from_service_account_info(info=credentials_data)
        project_id = credentials_data['project_id']

        self._storage: Client = Client(project=project_id, credentials=credentials)

        self._bucket_name: str = uri.netloc
        self._bucket: Bucket = self._storage.get_bucket(self._bucket_name)


    def get(self, key: Path) -> bytes:
        blob: Blob = self._bucket.get_blob(str(key))
        return blob.download_as_bytes()


    def get_range(self, key: Path, start: int, length: int) -> bytes:
        blob: Blob = self._bucket.get_blob(str(key))
        # start is first byte returned, end is last byte returned (so need the -1)
        return blob.download_as_bytes(start=start, end=start+length-1)


    def put(self, key: Path, data: bytes, mimetype: str = None) -> None:
        blob = self._bucket.blob(str(key))
        blob.upload_from_string(data, content_type=mimetype)


    def delete(self, key: Path) -> None:
        blob: Blob = self._bucket.get_blob(str(key))
        blob.delete()


    def copy(self, src: Path, dst: Path) -> None:
        blob: Blob = self._bucket.get_blob(str(src))
        self._bucket.copy_blob(blob, destination_bucket=self._bucket, new_name=str(dst))


    def list(self, prefix: Path = None):
        if prefix is not None:
            blobs = self._bucket.list_blobs(prefix=str(prefix))
        else:
            blobs = self._bucket.list_blobs()

        data = {}

        for blob in blobs:
            blob: Blob
            key = blob.name
            meta: ObjectMeta = self.head(key)
            data[str(key)] = meta

        return data


    def head(self, key: Path) -> ObjectMeta:
        blob: Blob = self._bucket.get_blob(str(key))

        data: ObjectMeta = ObjectMeta()
        data.location = blob.name
        data.size = blob.size

        return data
