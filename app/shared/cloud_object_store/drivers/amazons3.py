#
# Created by David Seery on 22/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from io import BytesIO
from pathlib import Path
from typing import Dict
from urllib.parse import SplitResult

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError, UnknownKeyError

from ..meta import ObjectMeta


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

        # we need to use an S3 Client rather than an S3 Resource, because a Resource provides
        # no methods to retrieve specific byte ranges, only entire objects.
        # See: https://github.com/boto/boto3/issues/3339, https://github.com/boto/s3transfer/pull/260
        self._storage: BaseClient = self._session.client('s3',
                                                         endpoint_url=data.get('endpoint_url', None),
                                                         region_name=data.get('region', None))

        if 'endpoint_url' in data:
            self._endpoint_url = data['endpoint_url']
        else:
            self._endpoint_url = None

        self._bucket_name: str = uri.netloc

    def get_driver_name(self):
        return 'AmazonS3CloudStorage'

    def get_bucket_name(self):
        return self._bucket_name

    def get_host_uri(self):
        return self._endpoint_url

    def get(self, key: Path) -> bytes:
        outstream = BytesIO()

        # we could use download_fileobj() or get_object() here
        # download_fileobj() is a managed transfer service that retrieves the object data using parallel
        # threads if it is sufficiently large. This means that it is faster, but there are fewer configuration
        # options.
        # Meanwhile, get_object() is a lower level API call that retrieves the object directly. It may be
        # slower for large files, but there are more configuration options
        try:
            self._storage.download_fileobj(Bucket=self._bucket_name, Key=str(key), Fileobj=outstream)
        except ClientError as e:
            raise FileNotFoundError(str(e))

        return outstream.getvalue()

    def get_range(self, key: Path, start: int, length: int) -> bytes:
        # see get() for the difference between download_fileobj() and get_object()
        try:
            response = self._storage.get_object(self._bucket_name, Key=str(key),
                                                Range="bytes {start}-{end}".format(start=start, end=start + length - 1))
        except ClientError as e:
            raise FileNotFoundError(str(e))
        return BytesIO(response['Body'].read()).getvalue()

    def put(self, key: Path, data: bytes, mimetype: str = None) -> None:
        self._storage.upload_fileobj(Fileobj=BytesIO(data), Bucket=self._bucket_name, Key=str(key),
                                     ExtraArgs={'ContentDisposition': mimetype})

    def delete(self, key: Path) -> None:
        try:
            self._storage.delete_object(Bucket=self._bucket_name, Key=str(key))
        except ClientError as e:
            raise FileNotFoundError(str(e))

    def copy(self, src: Path, dst: Path) -> None:
        try:
            self._storage.copy_object(Bucket=self._bucket_name, Key=str(dst), CopySource=str(src))
        except ClientError as e:
            raise FileNotFoundError(str(e))

    def list(self, prefix: Path = None):
        if prefix is not None:
            prefix_str = str(prefix)
        else:
            prefix_str = None

        data = {}
        continuation_token = None

        while True:
            extra_args = {}
            if prefix_str is not None:
                extra_args['Prefix'] = prefix_str
            if continuation_token is not None:
                extra_args['ContinuationToken'] = continuation_token

            response = self._storage.list_objects_v2(Bucket=self._bucket_name, **extra_args)
            contents = response['Contents']
            data.update({str(obj['Key']): self.head(obj['Key']) for obj in contents})

            is_truncated = response['IsTruncated']
            if not is_truncated:
                break

            continuation_token = response['NextContinuationToken']

        return data

    def head(self, key: Path) -> ObjectMeta:
        key_str = str(key)
        try:
            response = self._storage.head_object(Bucket=self._bucket_name, Key=key_str)
        except ClientError as e:
            raise FileNotFoundError(str(e))
        except UnknownKeyError as e:
            raise FileNotFoundError(str(e))

        data: ObjectMeta = ObjectMeta()
        data.location = key_str
        data.size = response['ContentLength']
        data.mimetype = response['ContentType']

        return data
