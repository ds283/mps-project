#
# Created by David Seery on 2019-03-23.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import base64
import os

from app.shared.cloud_object_store import ObjectStore
import app.shared.cloud_object_store.bucket_types as buckets
from app.shared.cloud_object_store.encryption.chacha20_poly1305 import ChaCha20_Poly1305


# APP CONFIGURATION
APP_NAME = 'mpsprojects'

# branding labels
BRANDING_LABEL = 'MPS projects management'
BRANDING_LOGIN_LANDING_STRING = 'Welcome to the MPS projects portal'
BRANDING_PUBLIC_LANDING_STRING = 'Welcome to the MPS public projects list'

# public browser
ENABLE_PUBLIC_BROWSER = True

# features
BACKUP_IS_LIVE = True
EMAIL_IS_LIVE = True


# FLASK

PREFERRED_URL_SCHEME = 'https'


# CLOUD API AUDIT

# get cloud API audit configuration
OBJECT_STORAGE_AUDIT_API = bool(int(os.environ.get("OBJECT_STORAGE_AUDIT_API", 0)))
OBJECT_STORAGE_AUDIT_BACKEND_URI = os.environ.get("OBJECT_STORAGE_AUDIT_BACKEND_URI")
OBJECT_STORAGE_AUDIT_BACKEND_DATABASE = os.environ.get("OBJECT_STORAGE_AUDIT_BACKEND_DATABASE")
OBJECT_STORAGE_AUDIT_BACKEND_COLLECTION = os.environ.get("OBJECT_STORAGE_AUDIT_BACKEND_COLLECTION")


# OBJECT BUCKETS

# Google Cloud Storage service account
OBJECT_STORAGE_SERVICE_ACCOUNT_FILE = os.environ.get('OBJECT_STORAGE_SERVICE_ACCOUNT_FILE')

# default storage options, inherited by all buckets
_storage_options = {'google_service_account': OBJECT_STORAGE_SERVICE_ACCOUNT_FILE,
                    'compressed': True,
                    'audit': OBJECT_STORAGE_AUDIT_API,
                    'audit_database': OBJECT_STORAGE_AUDIT_BACKEND_DATABASE,
                    'audit_collection': OBJECT_STORAGE_AUDIT_BACKEND_COLLECTION,
                    'audit_backend': OBJECT_STORAGE_AUDIT_BACKEND_URI}

# -- ASSETS BUCKET

OBJECT_STORAGE_ASSETS_URI = os.environ.get("OBJECT_STORAGE_ASSETS_URI")

# set up encryption pipeline for assets bucket
OBJECT_STORAGE_ASSETS_ENCRYPT_KEY = os.environ.get("OBJECT_STORAGE_ASSETS_ENCRYPT_KEY")
_assets_encrypt_key = base64.urlsafe_b64decode(OBJECT_STORAGE_ASSETS_ENCRYPT_KEY)

_assets_storage_options = _storage_options | {'encryption_pipeline': ChaCha20_Poly1305(_assets_encrypt_key)}

OBJECT_STORAGE_ASSETS = ObjectStore(OBJECT_STORAGE_ASSETS_URI, buckets.ASSETS_BUCKET, _assets_storage_options)

# -- BACKUP BUCKET

OBJECT_STORAGE_BACKUP_URI = os.environ.get("OBJECT_STORAGE_BACKUP_URI")

# set up encryption pipeline for backup bucket
OBJECT_STORAGE_BACKUP_ENCRYPT_KEY = os.environ.get("OBJECT_STORAGE_BACKUP_ENCRYPT_KEY")
_backup_encrypt_key = base64.urlsafe_b64decode(OBJECT_STORAGE_BACKUP_ENCRYPT_KEY)

_backup_storage_options = _storage_options | {'encryption_pipeline': ChaCha20_Poly1305(_backup_encrypt_key)}

OBJECT_STORAGE_BACKUP = ObjectStore(OBJECT_STORAGE_BACKUP_URI, buckets.BACKUP_BUCKET, _backup_storage_options)

# -- TELEMETRY BUCKET

OBJECT_STORAGE_TELEMETRY_URI = os.environ.get("OBJECT_STORAGE_TELEMETRY_URI")

_telemetry_storage_options = _storage_options

OBJECT_STORAGE_TELEMETRY = ObjectStore(OBJECT_STORAGE_TELEMETRY_URI, buckets.TELEMETRY_BUCKET, _telemetry_storage_options)
