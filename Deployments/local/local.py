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

OBJECT_STORAGE_ASSETS_URI = os.environ.get("OBJECT_STORAGE_ASSETS_URI")
OBJECT_STORAGE_ASSETS = ObjectStore(OBJECT_STORAGE_ASSETS_URI)

OBJECT_STORAGE_BACKUP_URI = os.environ.get("OBJECT_STORAGE_BACKUP_URI")
OBJECT_STORAGE_BACKUP = ObjectStore(OBJECT_STORAGE_BACKUP_URI)
