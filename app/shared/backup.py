#
# Created by David Seery on 03/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from sqlalchemy import func

from ..models import db, BackupConfiguration

from datetime import datetime


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

    return config.keep_hourly, config.keep_daily, config.limit, config.units, config.last_changed


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
