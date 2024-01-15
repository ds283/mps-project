#
# Created by David Seery on 15/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import tarfile
from datetime import datetime
from io import BytesIO
from os import path
from pathlib import Path
from tokenize import Ignore
from typing import Type
from urllib.parse import urlsplit, SplitResult

import pandas as pd
from flask import current_app

from ..shared.cloud_object_store.audit import AuditBackend
from ..shared.cloud_object_store.base import _audit_backends, ObjectStore
from ..shared.scratch import ScratchFileManager


def register_cloud_api_audit_tasks(celery):

    @celery.task(bind=True, default_retry_delay=120)
    def send_api_events_to_telemetry(self):
        self.update_state(state='STARTED', meta={'msg': 'Initiating deposit to cloud API audit events to telemetry'})

        # check if Cloud API auditing is currently enabled
        enabled = bool(int(current_app.config.get('OBJECT_STORAGE_AUDIT_API', 0)))
        if not enabled:
            self.update_state(state='FINISHED', meta={'msg': 'Cloud API auditing is currently disabled: did not run'})
            raise Ignore()

        object_store: ObjectStore = current_app.config.get('OBJECT_STORAGE_TELEMETRY')
        if object_store is None:
            self.update_state(state='FAILURE', meta={'msg': 'Telemetry ObjectStore bucket is not configured'})
            raise Ignore()

        # find URI for the backend
        backend_uri = current_app.config.get('OBJECT_STORAGE_AUDIT_BACKEND_URI')
        if backend_uri is None:
            self.update_state(state='FAILURE', meta={'msg': 'No backend storage specified for Cloud API audit'})
            raise Ignore()

        # determine whether the specified URI scheme is supported
        elements: SplitResult = urlsplit(backend_uri)
        scheme = elements.scheme
        if scheme not in _audit_backends:
            self.update_state(state='FAILURE', meta={'msg': 'Unsupported Cloud API audit backend URI scheme'})
            raise Ignore()

        # get concrete backend implementation from cloud_object_store
        backend_type: Type[AuditBackend] = _audit_backends[scheme]

        # populate data dict with any extra configuration details that are needed; this has to be done on
        # a scheme-by-scheme basis, since different backends may need different configuration
        data = {}
        if scheme == 'mongodb':
            data = data | {'audit_database': current_app.config.get('OBJECT_STORAGE_AUDIT_BACKEND_DATABASE'),
                           'audit_collection': current_app.config.get('OBJECT_STORAGE_AUDIT_BACKEND_COLLECTION')}

        # instantiate the backend
        backend: AuditBackend = backend_type(elements, data)

        # get all audit records from the backend
        # what's supplied is a Pandas DataFrame containing the details
        self.update_state('PROGRESS', meta={'msg': 'Obtaining audit records from Cloud API backend'})
        now = datetime.now()
        records: pd.DataFrame = backend.get_audit_records(latest=now)
        rows: int = records.shape[0]
        print(f'send_api_events_to_telemetry: obtained Pandas DataFrame containing {rows} records')

        if rows == 0:
            self.update_state(state='SUCCESS', meta={'msg': 'No audit records were returned from Cloud API backend'})
            return True

        yr = now.strftime("%Y")
        mo = now.strftime("%m")
        dy = now.strftime("%d")
        time = now.strftime("%H_%M_%S")
        csv_key = 'Cloud_API_events_{yr}-{mo}-{dy}-{time}.csv'.format(yr=yr, mo=mo, dy=dy, time=time)
        tgz_key = 'Cloud_API_events_{yr}-{mo}-{dy}-{time}.tar.gz'.format(yr=yr, mo=mo, dy=dy, time=time)

        with ScratchFileManager(suffix='.csv') as csv_scratch:
            csv_path: Path = csv_scratch.path
            records.to_csv(str(csv_path), index_label='rowid')

            if not path.exists(csv_path) or not path.isfile(csv_path):
                self.update_state(state='FAILURE', meta={'msg': 'Extraction of Cloud API backend data to CSV file did '
                                                                'not produce any usable output'})
                raise self.retry()

            self.update_state('PROGRESS', meta={'msg': 'Compressing extracted CSV file'})

            with ScratchFileManager(suffix='.tar.gz') as archive_scratch:
                archive_path: Path = archive_scratch.path

                with tarfile.open(name=archive_path, mode='w:gz', format=tarfile.PAX_FORMAT) as archive:
                    archive.add(name=csv_path, arcname=csv_key)
                    archive.close()

                if not path.exists(archive_path) or not path.isfile(archive_path):
                    self.update_state(state='FAILURE', meta={'msg': 'Compression of extracted Cloud API backend data '
                                                                    'did not produce any usable output'})
                    raise self.retry()

                self.update_state('PROGRESS', meta={'msg': 'Uploading compressed CSV to telemetry object store'})

                with open(archive_path, 'rb') as f:
                    _ = object_store.put(tgz_key, audit_data='send_cloud_api_events_to_telemetry',
                                         data=BytesIO(f.read()), mimetype='application/gzip')

        # delete current events from backend
        # we synchronize the events that are deleted using the same timestamp used to obtain records, so
        # none should get lost (in theory)
        self.update_state('PROGRESS', meta={'msg': 'Requesting backend to remove records sent to telemetry'})
        backend.delete_audit_records(latest=now)

        self.update_state('SUCCESS', meta={'msg': 'Completed successfully'})
        return True
