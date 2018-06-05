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

from celery import group, chain

from ..models import db, User, BackupRecord
from ..shared.backup import get_backup_config, get_backup_count, get_backup_size, remove_backup

from datetime import datetime, timedelta

import random


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
        backup_subfolder = path.join(now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"))
        backup_absfolder = path.join(backup_folder, backup_subfolder)

        backup_leafname = "{tag}_{time}.tar.gz".format(tag=tag, time=now_str)
        backup_relpath = path.join(backup_subfolder, backup_leafname)
        backup_abspath = path.join(backup_absfolder, backup_leafname)

        # ensure backup destination exists on disk
        if not path.exists(backup_absfolder):
            try:
                makedirs(backup_absfolder)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise self.retry()

        # ensure final archive name is unique
        count = 1
        if path.exists(backup_abspath):
            while path.exists(backup_abspath):
                backup_leafname = "{tag}_{time}_{ct}.tar.gz".format(tag=tag, time=now_str, ct=count)
                backup_relpath = path.join(backup_subfolder, backup_leafname)
                backup_abspath = path.join(backup_absfolder, backup_leafname)

                count += 1
                if count > 50:
                    raise self.retry()

        # name of temporary SQL dump file
        temp_SQL_file = path.join(backup_absfolder, 'SQL_temp_{tag}.sql'.format(tag=now_str))

        count = 1
        if path.exists(temp_SQL_file):
            while path.exists(temp_SQL_file):
                temp_SQL_file = path.join(backup_absfolder, 'SQL_temp_{tag}_{ct}.sql'.format(tag=now_str, ct=count))

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
            with tarfile.open(name=backup_abspath, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:

                archive.add(name=temp_SQL_file, arcname="database.sql")

                if path.exists(assets_folder):

                    archive.add(name=assets_folder, arcname="assets", recursive=True)

                archive.close()

            remove(temp_SQL_file)

            archive_size = path.getsize(backup_abspath)
            backup_size = _count_dir_size(backup_folder)

            # store details
            data = BackupRecord(owner_id=owner_id,
                                date=now,
                                type=type,
                                description=description,
                                filename=backup_relpath,
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
    def do_thinning(self):

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        max_hourly_age = timedelta(days=keep_hourly)
        max_daily_age = max_hourly_age + timedelta(weeks=keep_daily)

        # bin backups (but only those tagged as ordinary scheduled backups; ie., we don't thin backps
        # that have been taken for special purposes, such as snapshots constructed before rolling over
        # the academic year) into hourly, daily, weekly groups depending on age
        hourly = {}
        daily = {}
        weekly = {}

        now = datetime.now()

        for record in db.session.query(BackupRecord).filter_by(type=BackupRecord.SCHEDULED_BACKUP).order_by(
                BackupRecord.date.desc()).all():

            age = now - record.date

            if age < max_hourly_age:

                # work out age in hours (as an integer)
                age_hours = floor(float(age.seconds) / float(60*60))       # floor returns an Integer in Python3
                if age_hours in hourly:
                    hourly[age_hours].append(record.id)
                else:
                    hourly[age_hours] = [record.id]

            elif age < max_daily_age:

                # work out age in days (as an integer)
                age_days = floor(float(age.seconds) / float(60*60*24))      # as above, returns an Integer in Python3
                if age_days in daily:
                    daily[age_days].append(record.id)
                else:
                    daily[age_days] = [record.id]

            else:

                # work out age in weeks (as an integer)
                age_weeks = floor(float(age.seconds) / float(60*60*24*7))   # as above, returns an Integer in Python3
                if age_weeks in weekly:
                    weekly[age_weeks].append(record.id)
                else:
                    weekly[age_weeks] = [record.id]

        thinning = group(thin_class.s(hourly), thin_class.s(daily), thin_class.s(weekly))
        thinning.apply_async()


    @celery.task(bind=True, default_retry_delay = 2*60)
    def thin(self):

        seq = chain(do_thinning.s(), clean_up.s())
        seq.apply_async()


    @celery.task(bind=True, default_retry_delay = 2*60)
    def apply_size_limit(self):

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        while get_backup_size() > backup_max and get_backup_count() > 0:

            oldest_backup = db.session.query(BackupRecord.id).order_by(BackupRecord.date.asc()).first()

            if oldest_backup is not None:

                success, msg = remove_backup(oldest_backup[0])
                if not success:
                    self.update_state(state='FAILED', meta='Delete failed: {msg}'.format(msg=msg))

            else:

                self.update_state(state='FAILED', meta='Database record for oldest backup could not be loaded')


    @celery.task(bind=True, default_retry_delay = 2*60)
    def limit_size(self):

        seq = chain(apply_size_limit.s(), clean_up.s())
        seq.apply_async()


    def prune_empty_folders(path):

        file_count = 0

        for entry in scandir(path):

            if entry.is_dir(follow_symlinks=False):
                files_inside = prune_empty_folders(entry.path)

                if files_inside == 0:
                    remove(entry.path)

                else:
                    file_count += files_inside

            else:
                file_count += 1

        return file_count


    @celery.task(bind=True)
    def clean_up(self):

        backup_path = current_app.config['BACKUP_FOLDER']
        prune_empty_folders(backup_path)
