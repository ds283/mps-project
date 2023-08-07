#
# Created by David Seery on 03/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from .asset_tools import AssetCloudAdapter
from ..database import db
from ..models import BackupConfiguration, BackupRecord

from .sqlalchemy import get_count

from datetime import datetime
from os import path, remove


def get_backup_config():
    """
    Get current backup configuration
    :return:
    """

    # get number of configuration records; should be exactly 1
    num = get_count(db.session.query(BackupConfiguration))

    if num == 0:
        # no configuration record is present; generate a default and
        # allow exceptions to propagate up to caller (we have no sensible way to handle them here)
        data: BackupConfiguration = BackupConfiguration(keep_hourly=7, keep_daily=2, limit=None,
                                                        last_changed=datetime.now())
        db.session.add(data)
        db.session.commit()

    elif num > 1:
        # remove all but most-recently-edited configuration
        keep_id = db.session.query(BackupConfiguration.id).order_by(BackupConfiguration.last_changed.desc()).scalar()

        BackupConfiguration.query().filter(~BackupConfiguration.id == keep_id).delete()
        db.session.commit()

    config: BackupConfiguration = db.session.query(BackupConfiguration).one()

    return config.keep_hourly, config.keep_daily, (config.limit, config.units), config.backup_max, config.last_changed


def set_backup_config(keep_hourly, keep_daily, limit, units):
    """
    Set current backup configuration
    :return:
    """

    # get number of configuration records; should be exactly 1
    num = get_count(db.session.query(BackupConfiguration))

    if num == 0:
        # no configuration record is present; generate a default and allow exceptions to propagate
        # back up to caller (we have no sensible way to handle them here)
        data: BackupConfiguration = BackupConfiguration(keep_hourly=keep_hourly, keep_daily=keep_daily,
                                                        limit=limit, units=units, last_changed=datetime.now())
        db.session.add(data)
        db.session.commit()
        return

    elif num > 1:
        # remove all but most-recently-edited configuration
        keep_id = db.session.query(BackupConfiguration.id).order_by(BackupConfiguration.last_changed.desc()).scalar()

        try:
            BackupConfiguration.query().filter(~BackupConfiguration.id == keep_id).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            pass

    config: BackupConfiguration = db.session.query(BackupConfiguration).one()

    config.keep_hourly = keep_hourly
    config.keep_daily = keep_daily
    config.limit = limit
    config.units = units
    config.last_changed = datetime.now()

    # allow exceptions to propagate back to caller; we have no sensible way to deal with them here
    db.session.commit()


def compute_current_backup_count():
    """
    This method is used to get the count of backup records in the database.

    :return: The count of backup records in the database.
    """
    return get_count(db.session.query(BackupRecord))


def compute_current_backup_size():
    """
    Returns the total size of the most recent backup record.

    :return: The total size of the most recent backup record. If no backup record exists, returns 0.
    """
    # find most recent backup record and return its recorded total size
    size = db.session.query(func.sum(BackupRecord.archive_size)).scalar()

    if size is None:
        return 0

    return size


def remove_backup(id):
    record = db.session.query(BackupRecord).filter_by(id=id).first()

    if record is None:
        return False, 'database record for backup {id} could not be found'.format(id=id)

    object_store = current_app.config.get('OBJECT_STORAGE_BACKUP')
    storage = AssetCloudAdapter(record, object_store, size_attr='archive_size')

    # delete database record first; if this succeeds but the storage deletion doesn't, then the stored
    # file will be orphaned and hopefully will be picked up by garbage collection. This is better than the
    # alternative of storage deletion succeeding (so the data is lost) but the database record remaining
    # (so we are misled about what backups are being retained)
    try:
        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        return False, 'could not delete database entry for this backup'

    storage.delete()

    return True, None
