#
# Created by David Seery on 2019-03-23.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

from app.shared.cloud_object_store import ObjectStore
import app.shared.cloud_object_store.bucket_types as buckets

PREFERRED_URL_SCHEME = 'https'

BACKUP_IS_LIVE = True
EMAIL_IS_LIVE = True

OBJECT_STORAGE_SERVICE_ACCOUNT_FILE = os.environ.get('OBJECT_STORAGE_SERVICE_ACCOUNT_FILE')
_storage_options = {'google_service_account': OBJECT_STORAGE_SERVICE_ACCOUNT_FILE}

OBJECT_STORAGE_ASSETS_URI = os.environ.get("OBJECT_STORAGE_ASSETS_URI")
OBJECT_STORAGE_ASSETS = ObjectStore(OBJECT_STORAGE_ASSETS_URI, buckets.ASSET_BUCKET, _storage_options)

OBJECT_STORAGE_BACKUP_URI = os.environ.get("OBJECT_STORAGE_BACKUP_URI")
OBJECT_STORAGE_BACKUP = ObjectStore(OBJECT_STORAGE_BACKUP_URI, buckets.BACKUP_BUCKET, _storage_options)
