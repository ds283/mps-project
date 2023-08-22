#
# Created by David Seery on 22/08/2023.
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

import boto3
from boto3.resources.base import ServiceResource


class AmazonS3CloudStorageDriver:

    def __init__(self, uri: SplitResult, data: Dict):

        if data is None \
                or not isinstance(data, dict) \
                or 'access_key' not in data \
                or 'secret_key' not in data:
            raise RuntimeError('cloud_object_store: access_key and secret_key credentials must be supplied')

        self._session = boto3.Session(
            aws_access_key_id=data['access_key'],
            aws_secret_access_key=data['secret_key']
        )
        self._storage: ServiceResource = self._session.resource('s3')

        self._bucket_name: str = uri.netloc
        self._bucket: ServiceResource = self._storage.Bucket(self._bucket_name)


    def get(self, key: Path) -> bytes:
