#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from os import path, makedirs, errno, remove, scandir
from flask import current_app
import subprocess
import tarfile

from math import floor

from celery import group

from ..models import db, User, BackupRecord
from ..shared.backup import get_backup_config

from datetime import datetime, timedelta

import random

from os import path, remove


def _count_dir_size(path):

    size = 0

    for entry in scandir(path):

        if entry.is_dir(follow_symlinks=False):
            size += _count_dir_size(entry.path)

        else:
            size += entry.stat(follow_symlinks=False).st_size

    return size


def register_backup_tasks(celery):

    @celery.task(bind=True, default_retry_delay = 2*60)
    def backup(self, owner_id=None, type=BackupRecord.SCHEDULED_BACKUP, tag='backup', description=None):

        # get name of backup folder and database root password from app config
        backup_folder = current_app.config['BACKUP_FOLDER']
        assets_folder = current_app.config['ASSETS_FOLDER']
        root_password = current_app.config['DATABASE_ROOT_PASSWORD']
        db_hostname = current_app.config['DATABASE_HOSTNAME']

        # get current time
        now = datetime.now()

        # convert to filename-friendly format
        now_str = now.strftime("%H_%M_%S")

        # set up folder hierarchy
        backup_dest = path.join(backup_folder, now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"))
        backup_archive = path.join(backup_dest, "{tag}_{time}.tar.gz".format(tag=tag, time=now_str))

        # ensure backup destination exists on disk
        if not path.exists(backup_dest):
            try:
                makedirs(backup_dest)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise self.retry()

        # ensure final archive name is unique
        count = 1
        if path.exists(backup_archive):
            while path.exists(backup_archive):
                backup_archive = path.join(backup_dest, "{tag}_{time}_{ct}.tar.gz".format(tag=tag, time=now_str, ct=count))
                count += 1
                if count > 50:
                    raise self.retry()

        # name of temporary SQL dump file
        temp_SQL_file = path.join(backup_dest, 'SQL_temp_{tag}.sql'.format(tag=now_str))

        count = 1
        if path.exists(temp_SQL_file):
            while path.exists(temp_SQL_file):
                temp_SQL_file = path.join(backup_dest, 'SQL_temp_{tag}_{ct}.sql'.format(tag=now_str, ct=count))
                count += 1
                if count > 50:
                    raise self.retry()

        # dump database to SQL document
        p = subprocess.Popen(
            ["mysqldump", "-h", db_hostname, "-uroot", "-p{pwd}".format(pwd=root_password), "--opt", "--all-databases",
             "--skip-lock-tables", "-r", temp_SQL_file])
        stdout, stderr = p.communicate()

        if path.exists(temp_SQL_file) and path.isfile(temp_SQL_file):

            db_size = path.getsize(temp_SQL_file)

            # embed into tar archive
            with tarfile.open(name=backup_archive, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:

                archive.add(name=temp_SQL_file, arcname="database.sql")

                if path.exists(assets_folder):

                    archive.add(name=assets_folder, arcname="assets", recursive=True)

                archive.close()

            remove(temp_SQL_file)

            archive_size = path.getsize(backup_archive)
            backup_size = _count_dir_size(backup_folder)

            # store details
            data = BackupRecord(owner_id=owner_id,
                                date=now,
                                type=type,
                                description=description,
                                filename=backup_archive,
                                db_size=db_size,
                                archive_size=archive_size,
                                backup_size=backup_size)
            db.session.add(data)
            db.session.commit()

        else:

            self.update_status(state='FAILED', meta='SQL dump from mysqldump was not generated')


    @celery.task(bind=True, default_retry_delay = 2*60)
    def thin_list(self, l):

        # l should be a list of ids for BackupRecords that need to be thinned down to just 1

        remain = l
        while len(remain) > 1:

            index= random.randrange(len(remain))
            thin_id = remain[index]
            del remain[index]

            # will raise an exception if record does not exist
            record = db.session.query(BackupRecord).filter_by(id=thin_id).one()

            if path.exists(record.filename):

                remove(record.filename)
                db.session.remove(record)
                db.commit()

            else:

                self.update_state(state='FAILED', meta='Could not locate backup file to be thinned')



    @celery.task(bind=True, default_retry_delay = 2*60)
    def thin_class(self, records):

        # build group of tasks for each collection of backups we need to thin
        tasks = group([ thin_list.s(records[k]) for k in records.keys ])
        tasks.apply_async()


    @celery.task(bind=True, default_retry_delay = 2*60)
    def thin(self):

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        max_hourly_age = timedelta(days=keep_hourly)
        max_daily_age = max_hourly_age + timedelta(weeks=keep_daily)

        # bin backups into hourly, daily, weekly groups depending on age
        hourly = {}
        daily = {}
        weekly = {}

        now = datetime.now()

        for record in db.session.query(BackupRecord).order_by(BackupRecord.date.desc()).all():

            age = now - record.date

            if age < max_hourly_age:

                # work out age in hours
                age_hours = floor(age.seconds / (60*60))       # floor returns an Integer in Python3
                if age_hours in hourly:
                    hourly[age_hours].append(record.id)
                else:
                    hourly[age_hours] = [record.id]

            elif age < max_daily_age:

                # work out age in days
                age_days = floor(age.days)                     # as above, returns an Integer in Python3
                if age_days in daily:
                    daily[age_days].append(record.id)
                else:
                    daily[age_days] = [record.id]

            else:

                # work out age in weeks
                age_weeks = floor(age.days / 7)                # as above, returns an Integer in Python3
                if age_weeks in weekly:
                    weekly[age_weeks].append(record.id)
                else:
                    weekly[age_weeks] = [record.id]

        thinning = group(thin_class.s(hourly), thin_class.s(daily), thin_class.s(weekly))
        result = thinning.apply_async()
