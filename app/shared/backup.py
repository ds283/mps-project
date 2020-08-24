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


def get_backup_count():
    return get_count(db.session.query(BackupRecord))


def get_backup_size():
    return db.session.query(func.sum(BackupRecord.archive_size)).scalar()


def remove_backup(id):
    record = db.session.query(BackupRecord).filter_by(id=id).first()

    if record is None:
        return False, 'database record for backup {id} could not be found'.format(id=id)

    backup_folder = current_app.config['BACKUP_FOLDER']
    abspath = path.join(backup_folder, record.filename)

    if not path.exists(abspath):
        return False, 'archive file "{file}" not found'.format(file=abspath)

    remove(abspath)

    try:
        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        return False, 'could not delete database entry for this backup'

    return True, ''
