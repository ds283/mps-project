#
# Created by David Seery on 2019-03-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from celery import group, chain
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import UploadedAsset, TaskRecord, User
from ..task_queue import progress_update, register_task
from ..shared.sqlalchemy import get_count
from ..shared.utils import make_generated_asset_filename, canonical_uploaded_asset_filename

import csv


def register_batch_create_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def students(self, asset_id, current_user_id, task_uuid):
        try:
            asset = db.session.query(UploadedAsset).filter_by(id=asset_id).first()
            user = db.session.query(User).filter_by(id=current_user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if asset is None or user is None:
            self.update_state(state='FAILURE', meta='Could not load database records')
            progress_update(task_uuid, TaskRecord.FAILURE, 100, "Database error", autocommit=True)
            raise Ignore()

        progress_update(task_uuid, TaskRecord.RUNNING, 10, "Inspecting uploaded user list...", autocommit=True)

        with open(canonical_uploaded_asset_filename(asset.filename), 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

            required_fields = ['Name', 'Registration Number', 'Student Status', 'Year of Course', 'Course Code',
                               'Username', 'Email Address', 'Start Date']

            missing_fields = []
            for item in required_fields:
                if item not in headers:
                    missing_fields.append(item)

            if len(missing_fields) > 0:
                user.post_message('Failed to process student batch creation; the following columns were missing: '
                                  '{missing}.'.format(missing=', '.join(missing_fields)), 'error')
                progress_update(task_uuid, TaskRecord.FAILURE, 100, "Uploaded file was not in correct format", autocommit=True)
                return

