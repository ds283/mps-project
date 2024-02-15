#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import functools
import subprocess
import tarfile
from datetime import datetime, timedelta
from io import BytesIO
from math import floor
from operator import itemgetter
from os import path
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

from celery import group, chain
from celery.exceptions import Ignore
from dateutil import parser
from flask import current_app, render_template
from flask_mailman import EmailMessage
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from .. import register_task
from ..database import db
from ..models import BackupRecord, validate_nonce
from ..shared.asset_tools import AssetUploadManager
from ..shared.backup import get_backup_config, compute_current_backup_count, compute_current_backup_size, remove_backup
from ..shared.cloud_object_store import ObjectStore
from ..shared.formatters import format_size
from ..shared.scratch import ScratchFileManager


def register_backup_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def backup(self, owner_id=None, type=BackupRecord.SCHEDULED_BACKUP, tag="backup", description=None):
        self.update_state(state="STARTED", meta={"msg": "Initiating database backup"})

        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            self.update_state(state="FINISHED", meta={"msg": "Backup is not live: did not run"})
            raise Ignore()

        # get backup object store
        object_store: ObjectStore = current_app.config.get("OBJECT_STORAGE_BACKUP")
        if object_store is None:
            self.update_state(state="FAILURE", meta={"msg": "Backup ObjectStore bucket is not configured"})
            raise Ignore()

        # construct unique key for backup object
        now = datetime.now()
        key = "{yr}-{mo}-{dy}-{tag}-{time}-{uuid}.tar.gz".format(
            yr=now.strftime("%Y"), mo=now.strftime("%m"), dy=now.strftime("%d"), time=now.strftime("%H_%M_%S"), tag=tag, uuid=str(uuid4())
        )

        with ScratchFileManager(suffix=".sql") as SQL_scratch:
            SQL_scratch_path: Path = SQL_scratch.path

            self.update_state(state="PROGRESS", meta={"msg": "Performing mysqldump on main database"})

            # get database details from configuration
            user = current_app.config["DATABASE_USER"]
            password = current_app.config["DATABASE_PASSWORD"]
            database = current_app.config["DATABASE_NAME"]
            db_hostname = current_app.config["DATABASE_HOSTNAME"]

            # dump database to SQL document
            p: subprocess.CompletedProcess = subprocess.run(
                [
                    "mysqldump",
                    "-h",
                    db_hostname,
                    f"-u{user}",
                    f"-p{password}",
                    database,
                    "--opt",
                    "--skip-lock-tables",
                    f"--result-file={str(SQL_scratch_path)}",
                ]
            )

            if not path.exists(SQL_scratch_path) or not path.isfile(SQL_scratch_path):
                self.update_state(state="FAILURE", meta={"msg": "mysqldump failed or did not produce a readable file"})
                raise Ignore()

            self.update_state(state="PROGRESS", meta={"msg": "Compressing mysqldump output"})

            with ScratchFileManager(suffix=".tar.gz") as archive_scratch:
                archive_scratch_path: Path = archive_scratch.path

                with tarfile.open(name=archive_scratch_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
                    archive.add(name=SQL_scratch_path, arcname="database.sql")
                    archive.close()

                if not path.exists(archive_scratch_path) or not path.isfile(archive_scratch_path):
                    self.update_state(state="FAILURE", meta={"msg": "archive construction failed or did not produce a readable file"})
                    raise Ignore()

                # store details
                uncompressed_size = SQL_scratch_path.stat().st_size
                this_archive_size = archive_scratch_path.stat().st_size

                current_backup_size = db.session.query(func.sum(BackupRecord.archive_size)).scalar()
                if current_backup_size is None:
                    current_backup_size = 0

                # bucket, comment, encryption, encrypted_sie, compressed, compressed_size
                # fields will be populated by AssetUploadManager
                data = BackupRecord(
                    owner_id=owner_id,
                    date=now,
                    type=type,
                    description=description,
                    db_size=uncompressed_size,
                    archive_size=this_archive_size,
                    backup_size=current_backup_size + this_archive_size,
                    locked=False,
                    last_validated=None,
                    labels=[],
                )

                with open(archive_scratch_path, "rb") as f:
                    with AssetUploadManager(
                        data,
                        data=BytesIO(f.read()),
                        storage=object_store,
                        audit_data=f'backup task (key="{key}")',
                        key=key,
                        length=this_archive_size,
                        mimetype="application/gzip",
                        size_attr="archive_size",
                        validate_nonce=validate_nonce,
                    ) as upload_mgr:
                        pass

                try:
                    db.session.add(data)
                    db.session.commit()

                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    raise self.retry()

        return True

    @celery.task(bind=True, default_retry_delay=30)
    def do_thinning(self):
        self.update_state(state="STARTED", meta={"msg": "Building list of backups to be thinned"})

        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        max_hourly_age = timedelta(days=keep_hourly)
        max_daily_age = None if keep_daily is None else max_hourly_age + timedelta(weeks=keep_daily)

        # bin backups into categories (but only those tagged as ordinary scheduled backups; ie., we don't thin backups
        # that have been taken for special purposes, such as snapshots constructed before rolling over
        # the academic year) into hourly, daily, weekly groups depending on age
        daily = {}
        weekly = {}

        now = datetime.now()

        # query database for backup records, and queue a retry if it fails
        # note we only thin scheduled backups; other types are retained
        try:
            records: List[BackupRecord] = (
                db.session.query(BackupRecord)
                .filter(BackupRecord.type == BackupRecord.SCHEDULED_BACKUP, ~BackupRecord.locked)
                .order_by(BackupRecord.date.desc())
                .all()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        for record in records:
            record: BackupRecord

            # deduce current age of the backup as a timedelta
            age: timedelta = now - record.date

            if age < max_hourly_age:
                # do nothing; in this period we just keep all backups
                pass

            elif max_daily_age is None or (max_daily_age is not None and age < max_daily_age):
                # bin into groups based on age in days
                if age.days in daily:
                    daily[age.days].append((record.id, str(record.date)))
                else:
                    daily[age.days] = [(record.id, str(record.date))]

            else:
                # work out age in weeks (as an integer)
                age_weeks = floor(float(age.days) / float(7))  # returns an Integer in Python3

                # bin into groups based on age in weeks
                if age_weeks in weekly:
                    weekly[age_weeks].append((record.id, str(record.date)))
                else:
                    weekly[age_weeks] = [(record.id, str(record.date))]

        daily_list = [thin_bin.s(k, "days", daily[k]) for k in daily]
        weekly_list = [thin_bin.s(k, "weeks", weekly[k]) for k in weekly]

        total_list = daily_list + weekly_list

        # issue_thinning_result() will email a report to a specific email address; this is used for debugging,
        # but we don't usually want it running on the production version
        # thin_tasks = chord(group(*total_list), issue_thinning_result.s(str(now), 'D.Seery@sussex.ac.uk'))
        thin_tasks = group(*total_list)
        raise self.replace(thin_tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def thin_bin(self, period: int, unit: str, input_bin: List[Tuple[int, str]]):
        self.update_state(state="STARTED", meta={"msg": "Thinning backup bin for {period} {unit}".format(period=period, unit=unit)})

        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        # sort records from the bin into order, then retain the oldest record.
        # This means that re-running the thinning task is idempotent and stable under small changes in binning.
        # output_bin will eventually contain the retained record from this bin
        output_bin = sorted(((r[0], parser.parse(r[1])) for r in input_bin), key=itemgetter(1))

        # keep a list of backups that we drop
        dropped = []

        while len(output_bin) > 1:
            # get the last element
            drop_element = output_bin.pop()
            drop_id = drop_element[0]

            try:
                drop_record: BackupRecord = db.session.query(BackupRecord).filter_by(id=drop_id).first()
                dropped.append((drop_id, str(drop_record.date)))

                success, msg = remove_backup(drop_id)

                if not success:
                    self.update_state(state="FAILED", meta={"msg": "Delete failed: {msg}".format(msg=msg)})
                    raise self.retry()

            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        retained_record: BackupRecord = db.session.query(BackupRecord).filter_by(id=(output_bin[0])[0]).first()

        self.update_state(state="SUCCESS")
        return {"period": period, "unit": unit, "retained": (retained_record.id, str(retained_record.date)), "dropped": dropped}

    @celery.task(bind=True, default_retry_delay=30)
    def issue_thinning_result(self, thinning_result, timestamp_str: str, email: str):
        self.update_state(state="STARTED", meta={"msg": "Issue backup thinning report to {r}".format(r=email)})

        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        # order thinning_result by bins
        def sort_comparator(a, b):
            a_unit = a["unit"]
            b_unit = b["unit"]
            result = a_unit > b_unit
            if result != 0:
                return result

            a_period = a["period"]
            b_period = b["period"]
            return a_period > b_period

        sorted_result = sorted(thinning_result, key=functools.cmp_to_key(sort_comparator))

        timestamp = parser.parse(timestamp_str)
        timestamp_human = timestamp.strftime("%a %d %b %Y %H:%M:%S")

        app_name = current_app.config.get("APP_NAME", "mpsprojects")

        msg = EmailMessage(
            subject=f"[{app_name}] Backup thinning report at {timestamp_human}",
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=[email],
        )
        msg.body = render_template("email/backups/report_thinning.txt", result=sorted_result, date=timestamp_human)

        task_id = register_task(msg.subject, description="Send backup thinning report to {r}".format(r=", ".join(msg.to)))

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        self.update_state(state="SUCCESS")

    @celery.task(bind=True, default_retry_delay=30)
    def thin(self):
        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        seq = chain(drop_absent_backups.si(), do_thinning.si())
        raise self.replace(seq)

    @celery.task(bind=True, default_retry_delay=30)
    def drop_absent_backups(self):
        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        self.update_state(state="STARTED", meta={"msg": "Building list of backups"})

        # build list of objects in store, but only do it once so that we are not generating a lot of
        # LIST API requests that will each be billed
        object_store: ObjectStore = current_app.config["OBJECT_STORAGE_BACKUP"]
        contents = object_store.list(audit_data="drop_absent_backups")

        # query database for backup records, and queue a retry if it fails
        try:
            records: List[BackupRecord] = db.session.query(BackupRecord).all()

            # for each backup record we hold, test whether the counterpart object is in the object store
            for record in records:
                record: BackupRecord
                if record.unique_name not in contents:
                    print(f'Backup "{record.unique_name}" has no counterpart in the object store: deleting')
                    db.session.delete(record)
                else:
                    record.last_validated = datetime.now()

            # for each object in the object store, test whether there is a counterpart object
            for item in contents.keys():
                item: str
                record: BackupRecord = db.session.query(BackupRecord).filter_by(unique_name=item).first()

                if record is None:
                    print(f'Object store item "{item}" has no counterpart backup record: deleting')
                    object_store.delete(item)

            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True

    @celery.task(bind=True, default_retry_delay=30)
    def apply_size_limit(self):
        self.update_state(state="STARTED", meta={"msg": "Enforcing limit of maximum size of backup folder"})

        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()

        # exit if we are not currently applying a backup limit
        if backup_max is None:
            return

        # cache current size of backup folder and number of recorded backups
        current_size = compute_current_backup_size()
        current_count = compute_current_backup_count()

        # remember initial size and count
        initial_size = current_size
        initial_count = current_count

        # number of dropped backups
        dropped = 0

        while current_size > backup_max and current_count > 0:
            print(
                "apply_size_limit: current backup size = {current}, maximum size = "
                "{maxsize}, backup count = {count}".format(current=format_size(current_size), maxsize=format_size(backup_max), count=current_count)
            )
            try:
                oldest_backup: BackupRecord = db.session.query(BackupRecord.id).order_by(BackupRecord.date.asc()).first()

            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()

            if oldest_backup is not None:
                try:
                    success, msg = remove_backup(oldest_backup[0])
                    dropped += 1

                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    return self.retry()

                if not success:
                    print(
                        "apply_size_limit: failed to remove backup {timestamp} "
                        '("{desc}")'.format(timestamp=oldest_backup.timestamp, desc=oldest_backup.description)
                    )
                    self.update_state(state="FAILED", meta={"msg": "Delete failed: {msg}".format(msg=msg)})
                    raise self.retry()

            else:
                self.update_state(state="FAILED", meta={"msg": "Database record for oldest backup could not be loaded"})
                raise self.retry()

            # update cached values
            current_size = compute_current_backup_size()
            current_count = compute_current_backup_count()

        # return status (currently ignored by caller, but useful for debugging Celery jobs)
        return {"initial size": initial_size, "initial count": initial_count, "dropped": dropped, "new size": current_size, "limit": backup_max}

    @celery.task(bind=True, default_retry_delay=30)
    def limit_size(self):
        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        seq = chain(drop_absent_backups.si(), apply_size_limit.si())
        raise self.replace(seq)

    @celery.task(bind=True, serializer="pickle")
    def prune_backup_cutoff(self, id, limit):
        """
        Delete all backups older than the specified date
        :param duration:
        :param interval:
        :return:
        """
        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            raise Ignore()

        if isinstance(limit, str):
            limit = parser.parse(limit)

        try:
            record = BackupRecord.query.filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record.date < limit:
            success, msg = remove_backup(id)

            if not success:
                self.update_state(state="FAILED", meta={"msg": "Prune failed: {msg}".format(msg=msg)})
            else:
                self.update_state(state="SUCCESS", meta={"msg": "Prune backup succeeded"})

    @celery.task(bind=True)
    def delete_backup(self, id):
        """
        Delete a specified backup; just hand off to remove_backup() method.
        Designed to be called as part of a group constructed by the front end.
        :param self:
        :param id:
        :return:
        """
        # don't execute if we are not on a live backup platform
        if not current_app.config.get("BACKUP_IS_LIVE", False):
            self.update_state(state="SUCCESS", meta={"msg": "Ignored because backup is not currently live"})
            return

        try:
            success, msg = remove_backup(id)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if not success:
            self.update_state(state="FAILED", meta={"msg": "Delete failed: {msg}".format(msg=msg)})
        else:
            self.update_state(state="SUCCESS", meta={"msg": "Delete backup succeeded"})
