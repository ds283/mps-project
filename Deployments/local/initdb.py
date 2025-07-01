#
# Created by David Seery on 13/10/2023$.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

import app.shared.cloud_object_store.bucket_types as buckets
from app.shared.cloud_object_store import ObjectStore

INITDB_STORAGE_ENDPOINT_URL = os.environ.get("INITDB_STORAGE_ENDPOINT_URL")
INITDB_STORAGE_REGION = os.environ.get("INITDB_STORAGE_REGION")

# objects stored in the bucket aren't transparently encrypted or compressed
# for encryption, we have no way to store the nonce
# for compression, we would need a user accessible form of zlib
_storage_options = {'endpoint_url': INITDB_STORAGE_ENDPOINT_URL,
                    'region': INITDB_STORAGE_REGION,
                    'compressed': False}

# get credentials to access assets in bucket
INITDB_STORAGE_ACCESS_KEY = os.environ.get("INITDB_STORAGE_ACCESS_KEY")
INITDB_STORAGE_SECRET_KEY = os.environ.get("INITDB_STORAGE_SECRET_KEY")

_storage_options = _storage_options | {'access_key': INITDB_STORAGE_ACCESS_KEY,
                                       'secret_key': INITDB_STORAGE_SECRET_KEY}

INITDB_BUCKET_URI = os.environ.get("INITDB_STORAGE_BUCKET_URI")
INITDB_BUCKET = ObjectStore(INITDB_BUCKET_URI, buckets.INITDB_BUCKET, _storage_options)
INITDB_TARFILE = None

# INITDB_CATS_LIMITS_FILE = "DS-CATS-data.csv"
# INITDB_SUPERVISOR_IMPORT = "supervisor.csv"
# INITDB_EXAMINER_IMPORT = "examiner.csv"
