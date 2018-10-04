#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from os import path, makedirs, errno, rmdir, remove, scandir
from flask import current_app
import subprocess
import tarfile
from sqlalchemy.exc import SQLAlchemyError

from math import floor

from celery import group, chain

from ..database import db
from ..models import User, BackupRecord
from ..shared.backup import get_backup_config, get_backup_count, get_backup_size, remove_backup

from datetime import datetime, timedelta
from dateutil import parser

import random


def _count_dir_size(path):

    size = 0

    for entry in scandir(path):

        if entry.is_dir(follow_symlinks=False):
            size += _count_dir_size(entry.path)

        else:
            size += entry.stat(follow_symlinks=False).st_size

    return size


def _prune_empty_folders(path):

    file_count = 0

    for entry in scandir(path):

        if entry.is_dir(follow_symlinks=False):
            files_inside = _prune_empty_folders(entry.path)

            if files_inside == 0:
                rmdir(entry.path)

            else:
                file_count += files_inside

        else:
            file_count += 1

    return file_count


def register_backup_tasks(celery):

    @celery.task(default_retry_delay=30)
    def backup(owner_id=None, type=BackupRecord.SCHEDULED_BACKUP, tag='backup', description=None):

        seq = chain(build_backup_paths.s(tag), backup_database.s(), make_backup_archive.s(),
                    insert_backup_record.s(owner_id, type, description), clean_up.si())
        seq.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def build_backup_paths(self, tag):

        self.update_state(state='STARTED', meta='Preparing backup')

        # get name of backup folder
        backup_folder = current_app.config['BACKUP_FOLDER']

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

        return temp_SQL_file, backup_folder, backup_abspath, backup_relpath


    @celery.task(bind=True, default_retry_delay=30)
    def backup_database(self, paths):

        self.update_state(state='STARTED', meta='Performing database backup')

        # get database details from configuraiton
        root_password = current_app.config['DATABASE_ROOT_PASSWORD']
        db_hostname = current_app.config['DATABASE_HOSTNAME']

        temp_SQL_file, backup_folder, backup_abspath, backup_relpath = paths

        # dump database to SQL document
        p = subprocess.Popen(
            ["mysqldump", "-h", db_hostname, "-uroot", "-p{pwd}".format(pwd=root_password), "--opt", "--all-databases",
             "--skip-lock-tables", "-r", temp_SQL_file])
        stdout, stderr = p.communicate()

        if path.exists(temp_SQL_file) and path.isfile(temp_SQL_file):

            self.update_state(state='SUCCESS')
            return paths

        else:

            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def make_backup_archive(self, paths):

        self.update_state(state='STARTED', meta='Compressing database backup and website assets')

        # get location of assets folder from configuraiton
        assets_folder = current_app.config['ASSETS_FOLDER']

        temp_SQL_file, backup_folder, backup_abspath, backup_relpath = paths

        # embed into tar archive
        with tarfile.open(name=backup_abspath, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:

            archive.add(name=temp_SQL_file, arcname="database.sql")

            if path.exists(assets_folder):

                archive.add(name=assets_folder, arcname="assets", recursive=True)

            archive.close()

        if path.exists(backup_abspath) and path.isfile(backup_abspath):

            self.update_state(state='SUCCESS')
            return paths

        else:

            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def insert_backup_record(self, paths, owner_id, type, description):

        self.update_state(state='STARTED', meta='Writing backup receipts')

        temp_SQL_file, backup_folder, backup_abspath, backup_relpath = paths

        if path.exists(temp_SQL_file) and path.isfile(temp_SQL_file):
            db_size = path.getsize(temp_SQL_file)
        else:
            self.update_state(state='FAILED', meta='Missing database backup file')
            return

        if path.exists(backup_abspath) and path.isfile(backup_abspath):
            archive_size = path.getsize(backup_abspath)
        else:
            self.update_state(state='FAILED', meta='Missing compressed website archive')
            return

        if path.exists(backup_folder) and path.isdir(backup_folder):
            backup_size = _count_dir_size(backup_folder)
        else:
            self.update_state(state='FAILED', meta='Backup folder is not a directory')
            return

        # store details
        try:
            data = BackupRecord(owner_id=owner_id,
                                date=datetime.now(),
                                type=type,
                                description=description,
                                filename=backup_relpath,
                                db_size=db_size,
                                archive_size=archive_size,
                                backup_size=backup_size)
            db.session.add(data)
            db.session.commit()

            remove(temp_SQL_file)

        except SQLAlchemyError:

            db.session.rollback()
            raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def thin_bin(self, bin):

        self.update_state(state='STARTED', meta='Thinning backup bin')

        # l should be a list of ids for BackupRecords that need to be thinned down to just 1

        remain = bin
        while len(remain) > 1:

            index = random.randrange(len(remain))
            thin_id = remain[index]
            del remain[index]

            try:
                success, msg = remove_backup(thin_id)

                if not success:
                    self.update_state(state='FAILED', meta='Delete failed: {msg}'.format(msg=msg))
                    return
            except SQLAlchemyError:
                raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def thin_bins(self, bins, name):

        self.update_state(state='STARTED', meta='Thinning {n} backup bins'.format(n=name))

        # build group of tasks for each collection of backups we need to thin
        tasks = group(thin_bin.s(bins[k]) for k in bins.keys())
        tasks.apply_async()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def do_thinning(self):

        self.update_state(state='STARTED', meta='Building list of backups to be thinned')

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        max_hourly_age = timedelta(days=keep_hourly)
        max_daily_age = max_hourly_age + timedelta(weeks=keep_daily)

        # bin backups into categories (but only those tagged as ordinary scheduled backups; ie., we don't thin backups
        # that have been taken for special purposes, such as snapshots constructed before rolling over
        # the academic year) into hourly, daily, weekly groups depending on age
        daily = {}
        weekly = {}

        now = datetime.now()

        # query database for backup records, and queue a retry if it fails
        try:
            records = db.session.query(BackupRecord) \
                .filter_by(type=BackupRecord.SCHEDULED_BACKUP) \
                .order_by(BackupRecord.date.desc()).all()
        except SQLAlchemyError:
            raise self.retry()

        for record in records:

            age = now - record.date

            if age < max_hourly_age:

                # do nothing; in this period we just keep all backups
                pass

            elif age < max_daily_age:

                if age.days in daily:
                    daily[age.days].append(record.id)
                else:
                    daily[age.days] = [record.id]

            else:

                # work out age in weeks (as an integer)
                age_weeks = floor(float(age.days) / float(7))   # returns an Integer in Python3
                if age_weeks in weekly:
                    weekly[age_weeks].append(record.id)
                else:
                    weekly[age_weeks] = [record.id]

        thinning = group(thin_bins.si(daily, 'daily'), thin_bins.si(weekly, 'weekly'))
        thinning.apply_async()

        self.update_state(state='SUCCESS')

    @celery.task(default_retry_delay=30)
    def thin():

        seq = chain(drop_absent_backups.si(), do_thinning.si(), clean_up.si())
        seq.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def drop_absent_backups(self):

        self.update_state(state='STARTED', meta='Building list of backups')

        # query database for backup records, and queue a retry if it fails
        try:
            records = db.session.query(BackupRecord.id).all()
        except SQLAlchemyError:
            raise self.retry()

        # build a group of tasks, one for each backup
        seq = group(drop_backup_if_absent.si(id) for id in records)
        seq.apply_async()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def drop_backup_if_absent(self, id):

        self.update_state(state='STARTED', meta='Testing whether backup is available')

        # query database for backup records, and queue a retry if it fails
        try:
            record = db.session.query(BackupRecord).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Database record could not be loaded')

        backup_folder = current_app.config['BACKUP_FOLDER']
        abspath = path.join(backup_folder, record.filename)

        if not path.exists(abspath):
            db.session.delete(record)
            db.session.commit()

        self.update_state(state='SUCCESS')

    @celery.task(bind=True, default_retry_delay=30)
    def apply_size_limit(self):

        self.update_state(state='STARTED', meta='Enforcing limit of maximum size of backup folder')

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        # exit if we are not currently applying a backup limit
        if backup_max is None:
            return

        while get_backup_size() > backup_max and get_backup_count() > 0:

            try:
                oldest_backup = db.session.query(BackupRecord.id).order_by(BackupRecord.date.asc()).first()
            except SQLAlchemyError:
                return self.retry()

            if oldest_backup is not None:

                try:
                    success, msg = remove_backup(oldest_backup[0])
                except SQLAlchemyError:
                    return self.retry()

                if not success:
                    self.update_state(state='FAILED', meta='Delete failed: {msg}'.format(msg=msg))

            else:

                self.update_state(state='FAILED', meta='Database record for oldest backup could not be loaded')


    @celery.task(default_retry_delay=30)
    def limit_size():

        seq = chain(drop_absent_backups.si(), apply_size_limit.si(), clean_up.si())
        seq.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def clean_up(self):
        """
        Apply clean-up operations to the backup folder
        :param self:
        :param previous_result: Not used, just a placeholder because this item always appears in a chain of tasks
        :return:
        """

        self.update_state(state='STARTED', meta='Cleaning up backup folder')

        backup_path = current_app.config['BACKUP_FOLDER']
        _prune_empty_folders(backup_path)

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, serializer='pickle')
    def prune_backup_cutoff(self, id, limit):
        """
        Delete all backups older than the specified date
        :param duration:
        :param interval:
        :return:
        """

        if isinstance(limit, str):
            limit = parser.parse(limit)

        try:
            record = BackupRecord.query.filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record.date < limit:
            success, msg = remove_backup(id)

            if not success:
                self.update_state(state='FAILED', meta='Delete failed: {msg}'.format(msg=msg))


    @celery.task(bind=True)
    def delete_backup(self, id):
        """
        Delete a specified backup; just hand off to remove_backup() method.
        Designed to be called as part of a group constructed by the front end.
        :param self:
        :param id:
        :return:
        """

        try:
            success, msg = remove_backup(id)
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        if not success:
            self.update_state(state='FAILED', meta='Delete failed: {msg}'.format(msg=msg))
