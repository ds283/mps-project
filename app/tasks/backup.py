#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from os import path, makedirs, errno, remove
from flask import current_app
import subprocess
import tarfile

from celery.exceptions import Ignore

from ..models import db, User, BackupRecord

from datetime import datetime


def register_backup_tasks(celery):

    @celery.task()
    def backup(owner_id=None, type=BackupRecord.SCHEDULED_BACKUP, tag='backup'):

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
        backup_dest = path.join(backup_folder, now.strftime("%Y"), now.strftime("%m"))
        backup_archive = path.join(backup_dest, "{tag}_{time}.tar.gz".format(tag=tag, time=now_str))

        # ensure backup destination exists on disk
        if not path.exists(backup_dest):
            try:
                makedirs(backup_dest)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise Ignore

        # ensure final archive name is unique
        count = 1
        if path.exists(backup_archive):
            while path.exists(backup_archive):
                backup_archive = path.join(backup_dest, "{tag}_{time}_{ct}.tar.gz".format(tag=tag, time=now_str, ct=count))
                count += 1
                if count > 50:
                    raise Ignore        # fail silently TODO: should we be noisy?

        # name of temporary SQL dump file
        temp_SQL_file = path.join(backup_dest, 'SQL_temp_{tag}.sql'.format(tag=now_str))

        count = 1
        if path.exists(temp_SQL_file):
            while path.exists(temp_SQL_file):
                temp_SQL_file = path.join(backup_dest, 'SQL_temp_{tag}_{ct}.sql'.format(tag=now_str, ct=count))
                count += 1
                if count > 50:
                    raise Ignore        # fail silently TODO: should we be noisy?

        # dump database to SQL document
        p = subprocess.Popen(
            ["mysqldump", "-h", db_hostname, "-uroot", "-p{pwd}".format(pwd=root_password), "--opt", "--all-databases",
             "--skip-lock-tables", "-r", temp_SQL_file])
        stdout, stderr = p.communicate()

        if path.exists(temp_SQL_file) and path.isfile(temp_SQL_file):

            # embed into tar archive
            with tarfile.open(name=backup_archive, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:

                archive.add(name=temp_SQL_file, arcname="database.sql")

                if path.exists(assets_folder):

                    archive.add(name=assets_folder, arcname="assets", recursive=True)

                archive.close()

            remove(temp_SQL_file)

            # store details
            data = BackupRecord(owner_id=owner_id,
                                date=now,
                                type=type,
                                filename=backup_archive)
            db.session.add(data)
            db.session.commit()
