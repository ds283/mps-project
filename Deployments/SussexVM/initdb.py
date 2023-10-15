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

from app.shared.cloud_object_store import ObjectStore
import app.shared.cloud_object_store.bucket_types as buckets

# Google Cloud Storage service account
OBJECT_STORAGE_SERVICE_ACCOUNT_FILE = os.environ.get('OBJECT_STORAGE_SERVICE_ACCOUNT_FILE')
_storage_options = {'google_service_account': OBJECT_STORAGE_SERVICE_ACCOUNT_FILE,
                    'compressed': False}

INITDB_BUCKET_URI = os.environ.get("INITDB_STORAGE_BUCKET_URI")
INITDB_BUCKET = ObjectStore(INITDB_BUCKET_URI, buckets.INITDB_BUCKET, _storage_options)
INITDB_TARFILE = None
