#
# Created by ds283$ on 12/01/2024$.
# Copyright (c) 2024$ University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283$ <$>
#
from datetime import datetime
from typing import Dict
from urllib.parse import SplitResult, urlunsplit

from pymongo import MongoClient

from ..audit import AuditBackend


class MongoDBAuditBackend(AuditBackend):

    def __init__(self, mongodb_uri: SplitResult, data: Dict):
        self._db_name = data.get('audit_database', 'cloud_api_audit')
        if 'audit_database' in data:
            del data['audit_database']

        self._collection_name = data.get('audit_collection', 'audit_records')
        if 'audit_collection' in data:
            del data['audit_collection']

        self._client = MongoClient(urlunsplit(mongodb_uri))
        self._db = self._client[self._db_name]
        self._collection = self._db[self._collection_name]

    def store_audit_record(self, type: str, audit_data: str, driver: str=None, bucket: str=None, host_uri: str=None):
        now = datetime.now()
        audit_record = {'timestamp': now.isoformat(),
                        'type': type,
                        'data': audit_data,
                        'driver': driver,
                        'bucket': bucket,
                        'uri': host_uri}

        self._collection.insert_one(audit_record)

    def get_audit_records(self):
        cursor = self._collection.find(filter={}, projection={'_id': False})
        return list(cursor)
