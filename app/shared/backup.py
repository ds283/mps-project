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

from ..models import db, BackupConfiguration, BackupRecord

from datetime import datetime
from os import path, remove


def get_backup_config():
    """
    Get current backup configuration
    :return:
    """

    # get number of configuration records; should be exactly 1
    num = db.session.query(func.count(BackupConfiguration.id)).scalar()

    if num == 0:

        # no configuration record is present; generate a default
        data = BackupConfiguration(keep_hourly=7, keep_daily=2, limit=None, last_changed=datetime.now())
        db.session.add(data)
        db.session.commit()

    elif num > 1:

        # remove all but most-recently-edited configuration
        keep_id = db.session.query(BackupConfiguration.id).order_by(BackupConfiguration.last_changed.desc()).scalar()

        BackupConfiguration.query().filter(~BackupConfiguration.id==keep_id).delete()
        db.session.commit()

    config = db.session.query(BackupConfiguration).one()

    return config.keep_hourly, config.keep_daily, (config.limit, config.units), config.backup_max, config.last_changed


def set_backup_config(keep_hourly, keep_daily, limit, units):
    """
    Set current backup configuration
    :return:
    """

    # get number of configuration records; should be exactly 1
    num = db.session.query(func.count(BackupConfiguration.id)).scalar()

    if num == 0:

        # no configuration record is present; generate a default
        data = BackupConfiguration(keep_hourly=keep_hourly, keep_daily=keep_daily,
                                   limit=limit, units=units, last_changed=datetime.now())
        db.session.add(data)
        db.session.commit()
        return

    elif num > 1:

        # remove all but most-recently-edited configuration
        keep_id = db.session.query(BackupConfiguration.id).order_by(BackupConfiguration.last_changed.desc()).scalar()

        BackupConfiguration.query().filter(~BackupConfiguration.id == keep_id).delete()
        db.session.commit()

    config = db.session.query(BackupConfiguration).one()

    config.keep_hourly = keep_hourly
    config.keep_daily = keep_daily
    config.limit = limit
    config.units = units
    config.last_changed = datetime.now()
    db.session.commit()


def get_backup_count():

    return db.session.query(func.count(BackupRecord.id)).scalar()


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

    db.session.delete(record)
    db.session.commit()

    return True, ""
