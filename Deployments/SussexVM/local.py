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

import app.shared.cloud_object_store.bucket_types as buckets
from app.shared.cloud_object_store import ObjectStore
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

# get URI for storage provider
OBJECT_STORAGE_ENDPOINT_URL = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL")
OBJECT_STORAGE_REGION = os.environ.get("OBJECT_STORAGE_REGION")

_base_storage_options = {
    "endpoint_url": OBJECT_STORAGE_ENDPOINT_URL,
    "region": OBJECT_STORAGE_REGION,
    "compressed": True,
    "audit": OBJECT_STORAGE_AUDIT_API,
    "audit_database": OBJECT_STORAGE_AUDIT_BACKEND_DATABASE,
    "audit_collection": OBJECT_STORAGE_AUDIT_BACKEND_COLLECTION,
    "audit_backend": OBJECT_STORAGE_AUDIT_BACKEND_URI,
}

# -- ASSETS BUCKET

# get credentials to access assets bucket
OBJECT_STORAGE_ASSETS_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_ASSETS_ACCESS_KEY")
OBJECT_STORAGE_ASSETS_SECRET_KEY = os.environ.get("OBJECT_STORAGE_ASSETS_SECRET_KEY")

# set up encryption pipeline for assets bucket
OBJECT_STORAGE_ASSETS_ENCRYPT_KEY = os.environ.get("OBJECT_STORAGE_ASSETS_ENCRYPT_KEY")
_assets_encrypt_key = base64.urlsafe_b64decode(OBJECT_STORAGE_ASSETS_ENCRYPT_KEY)

# create ObjectStore data block for assets bucket
_assets_storage_options = _base_storage_options | {
    "access_key": OBJECT_STORAGE_ASSETS_ACCESS_KEY,
    "secret_key": OBJECT_STORAGE_ASSETS_SECRET_KEY,
    "encryption_pipeline": ChaCha20_Poly1305(_assets_encrypt_key),
}

# create ObjectStore for assets bucket
OBJECT_STORAGE_ASSETS_URI = os.environ.get("OBJECT_STORAGE_ASSETS_URI")
OBJECT_STORAGE_ASSETS = ObjectStore(OBJECT_STORAGE_ASSETS_URI, buckets.ASSETS_BUCKET, _assets_storage_options)

# -- BACKUP BUCKET


# get credentials to access backup bucket
OBJECT_STORAGE_BACKUP_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_BACKUP_ACCESS_KEY")
OBJECT_STORAGE_BACKUP_SECRET_KEY = os.environ.get("OBJECT_STORAGE_BACKUP_SECRET_KEY")

# set up encryption pipeline for backup bucket
OBJECT_STORAGE_BACKUP_ENCRYPT_KEY = os.environ.get("OBJECT_STORAGE_BACKUP_ENCRYPT_KEY")
_backup_encrypt_key = base64.urlsafe_b64decode(OBJECT_STORAGE_BACKUP_ENCRYPT_KEY)

_backup_storage_options = _base_storage_options | {
    "access_key": OBJECT_STORAGE_BACKUP_ACCESS_KEY,
    "secret_key": OBJECT_STORAGE_BACKUP_SECRET_KEY,
    "encryption_pipeline": ChaCha20_Poly1305(_backup_encrypt_key),
}

# create ObjectStore for backup bucket
OBJECT_STORAGE_BACKUP_URI = os.environ.get("OBJECT_STORAGE_BACKUP_URI")
OBJECT_STORAGE_BACKUP = ObjectStore(OBJECT_STORAGE_BACKUP_URI, buckets.BACKUP_BUCKET, _backup_storage_options)

# -- TELEMETRY BUCKET

# get credentials to access telemetry bucket
OBJECT_STORAGE_TELEMETRY_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_TELEMETRY_ACCESS_KEY")
OBJECT_STORAGE_TELEMETRY_SECRET_KEY = os.environ.get("OBJECT_STORAGE_TELEMETRY_SECRET_KEY")

_telemetry_storage_options = _base_storage_options | {
    "access_key": OBJECT_STORAGE_TELEMETRY_ACCESS_KEY,
    "secret_key": OBJECT_STORAGE_TELEMETRY_SECRET_KEY,
    "compressed": False,
}

# create ObjectStore for telemetry bucket
OBJECT_STORAGE_TELEMETRY_URI = os.environ.get("OBJECT_STORAGE_TELEMETRY_URI")
OBJECT_STORAGE_TELEMETRY = ObjectStore(OBJECT_STORAGE_TELEMETRY_URI, buckets.TELEMETRY_BUCKET, _telemetry_storage_options)

# -- FEEDBACK BUCKET

# get credentials to access feedback bucket
OBJECT_STORAGE_FEEDBACK_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_FEEDBACK_ACCESS_KEY")
OBJECT_STORAGE_FEEDBACK_SECRET_KEY = os.environ.get("OBJECT_STORAGE_FEEDBACK_SECRET_KEY")

# set up encryption pipeline for feedback bucket
OBJECT_STORAGE_FEEDBACK_ENCRYPT_KEY = os.environ.get("OBJECT_STORAGE_FEEDBACK_ENCRYPT_KEY")
_feedback_encrypt_key = base64.urlsafe_b64decode(OBJECT_STORAGE_FEEDBACK_ENCRYPT_KEY)

_feedback_storage_options = _base_storage_options | {
    "access_key": OBJECT_STORAGE_FEEDBACK_ACCESS_KEY,
    "secret_key": OBJECT_STORAGE_FEEDBACK_SECRET_KEY,
    "encryption_pipeline": ChaCha20_Poly1305(_feedback_encrypt_key),
}

# create ObjectStore for feedback bucket
OBJECT_STORAGE_FEEDBACK_URI = os.environ.get("OBJECT_STORAGE_FEEDBACK_URI")
OBJECT_STORAGE_FEEDBACK = ObjectStore(OBJECT_STORAGE_FEEDBACK_URI, buckets.FEEDBACK_BUCKET, _feedback_storage_options)

# -- PROJECT BUCKET

# get credentials to access project bucket
OBJECT_STORAGE_PROJECT_ACCESS_KEY = os.environ.get("OBJECT_STORAGE_PROJECT_ACCESS_KEY")
OBJECT_STORAGE_PROJECT_SECRET_KEY = os.environ.get("OBJECT_STORAGE_PROJECT_SECRET_KEY")

# set up encryption pipeline for project bucket
OBJECT_STORAGE_PROJECT_ENCRYPT_KEY = os.environ.get("OBJECT_STORAGE_PROJECT_ENCRYPT_KEY")
_project_encrypt_key = base64.urlsafe_b64decode(OBJECT_STORAGE_PROJECT_ENCRYPT_KEY)

_project_storage_options = _base_storage_options | {
    "access_key": OBJECT_STORAGE_PROJECT_ACCESS_KEY,
    "secret_key": OBJECT_STORAGE_PROJECT_SECRET_KEY,
    "encryption_pipeline": ChaCha20_Poly1305(_project_encrypt_key),
}

# create ObjectStore for project bucket
OBJECT_STORAGE_PROJECT_URI = os.environ.get("OBJECT_STORAGE_PROJECT_URI")
OBJECT_STORAGE_PROJECT = ObjectStore(OBJECT_STORAGE_PROJECT_URI, buckets.PROJECT_BUCKET, _project_storage_options)
