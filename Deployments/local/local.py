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

APP_NAME = 'mpsprojects'

OBJECT_STORAGE_ENDPOINT_URL = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL")
OBJECT_STORAGE_REGION = os.environ.get("OBJECT_STORAGE_REGION")

_base_storage_options = {'endpoint_url': OBJECT_STORAGE_ENDPOINT_URL,
                         'region': OBJECT_STORAGE_REGION}

OBJECT_STORAGE_ASSETS_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_ASSETS_ACCESS_KEY")
OBJECT_STORAGE_ASSETS_SECRET_KEY = os.environ.get("OBJECT_STORAGE_ASSETS_SECRET_KEY")

_assets_storage_options = _base_storage_options | {'access_key': OBJECT_STORAGE_ASSETS_ACCESS_KEY,
                                                   'secret_key': OBJECT_STORAGE_ASSETS_SECRET_KEY}

OBJECT_STORAGE_BACKUP_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_BACKUP_ACCESS_KEY")
OBJECT_STORAGE_BACKUP_SECRET_KEY = os.environ.get("OBJECT_STORAGE_BACKUP_SECRET_KEY")

_backup_storage_options = _base_storage_options | {'access_key': OBJECT_STORAGE_BACKUP_ACCESS_KEY,
                                                   'secret_key': OBJECT_STORAGE_BACKUP_SECRET_KEY}

OBJECT_STORAGE_ASSETS_URI = os.environ.get("OBJECT_STORAGE_ASSETS_URI")
OBJECT_STORAGE_ASSETS = ObjectStore(OBJECT_STORAGE_ASSETS_URI, buckets.ASSETS_BUCKET, _assets_storage_options)

OBJECT_STORAGE_BACKUP_URI = os.environ.get("OBJECT_STORAGE_BACKUP_URI")
OBJECT_STORAGE_BACKUP = ObjectStore(OBJECT_STORAGE_BACKUP_URI, buckets.BACKUP_BUCKET, _backup_storage_options)

BRANDING_LABEL = 'MPS projects management'
BRANDING_LOGIN_LANDING_STRING = 'Welcome to the MPS projects portal'
BRANDING_PUBLIC_LANDING_STRING = 'Welcome to the MPS public projects list'

ENABLE_PUBLIC_BROWSER = True

VIDEO_EXPLAINER_PANOPTO_SERVER = 'sussex.cloud.panopto.eu'
VIDEO_EXPLAINER_PANOPTO_SESSION = 'c2274660-a8f0-4f71-ba13-acd101735f7b'
