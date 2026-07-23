#
# Created by David Seery on 13/10/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import subprocess
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from tarfile import TarFile, TarInfo
from tarfile import open as tarfile_open
from typing import Dict, List, Optional

import pandas as pd
from flask_migrate import upgrade
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import db
from app.models import (
    EnrollmentRecord,
    FacultyData,
    GradingRubric,
    MarkingEvent,
    ProjectClassConfig,
    Role,
    SubmissionPeriodRecord,
    User,
)
from app.models.scheduler import (
    CrontabSchedule,
    DatabaseSchedulerEntry,
    IntervalSchedule,
)
from app.shared.cloud_object_store import ObjectMeta, ObjectStore
from app.shared.scratch import ScratchFileManager
from app.shared.utils import get_current_year


def execute_query(app, query):
    try:
        result = db.session.execute(text(query))
    except SQLAlchemyError as e:
        app.logger.info("** encountered exception while emplacing SQL line")
        app.logger.info(f"     {query}")
        app.logger.exception("SQLAlchemyError exception", exc_info=e)


def get_current_datetime():
    now: datetime = datetime.now()
    now_str: str = now.strftime("%Y-%m-%d %H:%M:%S")

    # if month is Oct, Nov, Dec, current academic year matches current calendar year
    # otherwise, current academic year is calendar year - 1
    if now.month in [10, 11, 12]:
        current_year = now.year
    else:
        current_year = now.year - 1

    return {"timestamp": now_str, "main_year": str(current_year)}


def execute_scripts(app, script, data):
    with open(script, "r") as file:
        while line := file.readline():
            line = line.replace("$$TIMESTAMP", data["timestamp"])
            line = line.replace("$$MAIN_YEAR", data["main_year"])
            execute_query(app, line)


def sql_script_populate(app, script):
    data = get_current_datetime()

    db.session.begin()

    db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
    execute_scripts(app, script, data)
    db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

    db.session.commit()


def populate_table_if_empty(app, inspector, bucket: ObjectStore, table: str, sql_script: Path):
    if not inspector.has_table(table):
        app.logger.error(
            f'!! FATAL: database is missing the "{table}" table and is not ready. '
            f"Check that the Alembic migration script has run correctly, or "
            f"rebuild the database from a mysqldump dump."
        )
        exit()

    db.session.begin()
    out = db.session.execute(text(f"SELECT COUNT(*) FROM {table};")).first()
    count = out[0]
    db.session.commit()

    if count == 0:
        app.logger.info(f'** table "{table}" is empty, beginning to auto-populate using script "{sql_script}"')

        with ScratchFileManager(suffix=".sql") as scratch_path:
            with open(scratch_path.path, "wb") as f:
                data: bytes = bucket.get(str(sql_script), audit_data="populate_table_if_empty")
                f.write(data)

            sql_script_populate(app, scratch_path.path)


def tarfile_populate(app, bucket: ObjectStore, tarfile: str | Path):
    # get database details from configuration
    user = app.config["DATABASE_USER"]
    password = app.config["DATABASE_PASSWORD"]
    database = app.config["DATABASE_NAME"]
    db_hostname = app.config["DATABASE_HOSTNAME"]

    if isinstance(tarfile, str):
        tarfile = Path(tarfile)

    # try to drop all tables from the SQL database
    # these stops problems with later upgrades via Alembic, if the tables already exist (usually because they were
    # created by running Alembic during the boot process)
    tables = db.metadata.tables.keys()
    db.session.remove()
    db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
    for table in tables:
        db.session.execute(text(f"DROP TABLE {table};"))
    db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
    db.session.commit()

    full_suffix = "".join(tarfile.suffixes)

    with ScratchFileManager(suffix=full_suffix) as scratch_path:
        with open(scratch_path.path, "wb") as f:
            data: bytes = bucket.get(str(tarfile), audit_data="tarfile_populate")
            f.write(data)

        tf: TarFile = tarfile_open(name=scratch_path.path, mode="r")
        contents_list: List[TarInfo] = tf.getmembers()
        contents_dict: Dict[str, TarInfo] = {x.name: x for x in contents_list}

        if "database.sql" not in contents_dict:
            raise RuntimeError(f"!! initdb tarfile {tarfile} did not contain a database.sql script")

        to: TarInfo = contents_dict["database.sql"]
        fo = tf.extractfile(to)
        if fo is None:
            raise RuntimeError(f'!! initdb tarfile {tarfile} contains a "database.sql" object, but it did not extract correctly from the archive')

        p: subprocess.CompletedProcess = subprocess.run(
            ["mysql", "-h", db_hostname, f"-u{user}", f"-p{password}", database],
            input=fo.read(),
        )

        if p.returncode != 0:
            print(f"!! SQL database re-population did not complete successfully: return code = {p.returncode}")
            print(f"!!")
            print(f"!! stdout output")
            print(p.stdout)
            print(f"\n!! stderr output")
            print(p.stderr)

    # run Alembic upgrade
    db.session.remove()
    upgrade()


_LOCKFILE_NAME = "_lockfile"


class LockFileManager:
    def __init__(self, bucket: ObjectStore, lockfile_name: str = _LOCKFILE_NAME):
        self._bucket = bucket
        self._data = "lock".encode()
        self._lockfile_name = lockfile_name

    def __enter__(self):
        self._bucket.put(
            self._lockfile_name,
            audit_data="LockFileManager",
            data=self._data,
            mimetype="application/octet-stream",
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._bucket.delete(self._lockfile_name, audit_data="LockFileManager")


def _wait_until_unlocked(bucket: ObjectStore):
    contents = bucket.list(audit_data="_wait_until_unlocked")

    if _LOCKFILE_NAME not in contents:
        return

    print(f"** initdb bucket is locked; waiting for lock to be released")
    count = 0
    max_cycles = 100

    while True:
        # sleep for 5 seconds
        time.sleep(5)
        count += 1
        print(f"   -- waiting ({count})")

        if count > max_cycles:
            print(f"   -- waited for {max_cycles} cycles, breaking out now")
            break

        try:
            data: ObjectMeta = bucket.head(_LOCKFILE_NAME, audit_data="initial_populate_database")
        except FileNotFoundError:
            print(f"** initdb bucket lock has been released")
            break


def initial_populate_database(app, inspector, initial_db=None):
    # first import ObjectStore containing the initial database setup scripts
    if initial_db is None:
        initial_db = import_module("app.initdb.initdb")
    init_bucket: ObjectStore = initial_db.INITDB_BUCKET
    init_tarfile: Optional[str] = initial_db.INITDB_TARFILE

    _wait_until_unlocked(init_bucket)

    with LockFileManager(init_bucket) as lock:
        contents = init_bucket.list(audit_data="initial_populate_database")
        tar_files: List[Path] = []
        sql_files: List[Path] = []

        for object in contents:
            object: str
            fname: Path = Path(object)

            full_suffix = "".join(fname.suffixes)
            if full_suffix in [".tar", ".tar.gz", ".tar.bz2"]:
                tar_files.append(fname)
            elif full_suffix in [".sql"]:
                sql_files.append(fname)
            elif object != _LOCKFILE_NAME:
                print(f'** ignored unmatched object in initial bucket with name "{object}"')

        if len(tar_files) > 1:
            print(f"** more than one tarfile was present in the initial object bucket")

        if len(tar_files) > 0:
            if init_tarfile is not None and init_tarfile in tar_files:
                print(f"** using tarfile {init_tarfile} specified in environment")

                tarfile_populate(app, init_bucket, init_tarfile)
            else:
                tar_files.sort(reverse=True)
                use_tarfile = tar_files[0]
                print(f"** using tarfile {use_tarfile} to populate database")

                tarfile_populate(app, init_bucket, use_tarfile)

        for sql_file in sql_files:
            table: str = sql_file.stem

            # first three characters of table should be of the form NN_ where NN is a number that
            # indicates the sequence in which the tables should be populated
            table = table[3:]
            populate_table_if_empty(app, inspector, init_bucket, table, sql_file)


def store_CATS_limits(app, bucket: ObjectStore, csv_file: str | Path):
    if isinstance(csv_file, str):
        csv_file = Path(csv_file)

    full_suffix = "".join(csv_file.suffixes)

    with ScratchFileManager(suffix=full_suffix) as scratch_path:
        with open(scratch_path.path, "wb") as f:
            data: bytes = bucket.get(str(csv_file), audit_data="store_CATS_limits")
            f.write(data)

        df = pd.read_csv(scratch_path.path)
        for index, row in df.iterrows():
            email = str(row["email"]).lower()
            name = str(row["Name"])
            surname = str(row["Surname"])
            full_name = name + " " + surname

            fd: FacultyData = db.session.query(FacultyData).join(User, User.id == FacultyData.id).filter(func.lower(User.email) == email).first()
            if fd is None:
                print(f'-- !! could not find FacultyData record for user "{full_name}" <{email}>')
                continue

            CATS_supv_string = row["CATS supervision"]
            CATS_mark_string = row["CATS marking"]

            try:
                new_supv_limit = int(CATS_supv_string)
            except ValueError:
                new_supv_limit = None

            try:
                new_mark_limit = int(CATS_mark_string)
            except ValueError:
                new_mark_limit = None

            if new_supv_limit is not None:
                if fd.CATS_supervision is not None:
                    print(
                        f'-- !! "{full_name}" <{email}> ignoring new supervision CATS limit {new_supv_limit} because a limit of {fd.CATS_supervision} is already set'
                    )
                    if fd.CATS_supervision > new_supv_limit:
                        print(f'-- !! "{full_name}" <{email}> existing supervision limit is larger than specified limit in CATS file')

                else:
                    fd.CATS_supervision = new_supv_limit
                    print(f'-- >> "{full_name}" <{email}> set supervision CATS limit to {new_supv_limit}')

            if new_mark_limit is not None:
                if fd.CATS_marking is not None:
                    print(
                        f'-- !! "{full_name}" <{email}> ignoring new marking CATS limit {new_mark_limit} because a limit of {fd.CATS_marking} is already set'
                    )
                    if fd.CATS_marking > new_mark_limit:
                        print(f'-- !! "{full_name}" <{email}> existing marking limit is larger than specified limit in CATS file')

                else:
                    fd.CATS_marking = new_mark_limit
                    print(f'-- >> "{full_name}" <{email}> set marking CATS limit to {new_mark_limit}')

            ds_rec: EnrollmentRecord = fd.get_enrollment_record(pclass=7)
            hsds_rec: EnrollmentRecord = fd.get_enrollment_record(pclass=8)

            if ds_rec is not None:
                if ds_rec.CATS_supervision is not None and ds_rec.CATS_supervision < fd.CATS_supervision:
                    print(
                        f' -- !! "{full_name}" <{email}> supervision limit of {ds_rec.CATS_supervision} for DS is lower than global limit of {fd.CATS_supervision}'
                    )
                if ds_rec.CATS_marking is not None and ds_rec.CATS_marking < fd.CATS_marking:
                    print(
                        f' -- !! "{full_name}" <{email}> supervision limit of {ds_rec.CATS_supervision} for DS is lower than global limit of {fd.CATS_supervision}'
                    )

            if hsds_rec is not None:
                if hsds_rec.CATS_supervision is not None and hsds_rec.CATS_supervision < fd.CATS_supervision:
                    print(
                        f' -- !! "{full_name}" <{email}> supervision limit of {hsds_rec.CATS_supervision} for HSDS is lower than global limit of {fd.CATS_supervision}'
                    )
                if hsds_rec.CATS_marking is not None and hsds_rec.CATS_marking < fd.CATS_marking:
                    print(
                        f' -- !! "{full_name}" <{email}> supervision limit of {hsds_rec.CATS_supervision} for HSDS is lower than global limit of {fd.CATS_supervision}'
                    )

    db.session.commit()


def populate_CATS_limits(app, initial_db=None):
    # import initdb ObjectStore from which we can download the CATS limits
    if initial_db is None:
        initial_db = import_module("app.initdb.initdb")

    init_bucket: ObjectStore = initial_db.INITDB_BUCKET
    CATS_csv: str = initial_db.INITDB_CATS_LIMITS_FILE

    _wait_until_unlocked(init_bucket)

    with LockFileManager(init_bucket) as lock:
        contents = init_bucket.list(audit_data="populate_CATS_limits")

        if CATS_csv not in contents:
            print(f'** ignored INITDB_CATS_LIMITS_FILE="{CATS_csv}", which was not present in the initdb object store')
            return

        print(f'** using INITDB_CATS_LIMITS_FILE="{CATS_csv}" to set CATS limits')
        store_CATS_limits(app, init_bucket, CATS_csv)


# ---------------------------------------------------------------------------
# Ensure built-in roles exist
# ---------------------------------------------------------------------------

# Roles that must exist for the application to function correctly.
# Each entry is (name, description, colour).
_REQUIRED_ROLES: List[Dict] = [
    {
        "name": "data_dashboard_AI",
        "description": "Read-only access to the AI data dashboard for all project classes and cycles "
        "belonging to the user's tenants. Does not grant permission to launch "
        "analysis pipeline tasks.",
        "colour": "#5a6fd6",
    },
    {
        "name": "data_dashboard_marking",
        "description": "Read-only access to the marking dashboard for all project classes and cycles "
        "belonging to the user's tenants. Does not grant permission to modify "
        "marking events or workflows.",
        "colour": "#2d8a4e",
    },
    {
        "name": "data_dashboard_similarity",
        "description": "Read-only access to the similarity dashboard for all project classes and cycles "
        "belonging to the user's tenants. Does not grant permission to launch "
        "similarity rebuild tasks.",
        "colour": "#c05810",
    },
    {
        "name": "data_dashboard_reports",
        "description": "Read-only access to the AVD dashboard for all project classes and cycles "
        "belonging to the user's tenants. Does not grant convenor or marking "
        "permissions.",
        "colour": "#1a8a8a",
    },
    {
        "name": "ticket_subscriber",
        "description": "Eligible to be added as a ticket watcher; grants no operational permissions.",
        "colour": "#7a5ad6",
    },
]


def ensure_roles(app) -> None:
    """
    Idempotently create any roles that are required by the application but may
    not yet exist in the database (e.g. after a schema migration that introduces
    a new feature).  Safe to call on every startup.
    """
    with app.app_context():
        created = 0
        for spec in _REQUIRED_ROLES:
            existing = db.session.query(Role).filter_by(name=spec["name"]).first()
            if existing is None:
                role = Role(
                    name=spec["name"],
                    description=spec["description"],
                    colour=spec["colour"],
                )
                db.session.add(role)
                created += 1
                print(f"** ensure_roles: created role '{spec['name']}'")

        if created:
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                app.logger.exception("SQLAlchemyError in ensure_roles", exc_info=e)
        else:
            print("** ensure_roles: all required roles already present")


# ---------------------------------------------------------------------------
# Back-fill ProjectClassConfig.grading_rubric
# ---------------------------------------------------------------------------


def ensure_config_rubrics(app) -> None:
    """
    Idempotently assign a grading rubric to any ProjectClassConfig whose
    grading_rubric is currently None.  Picks the GradingRubric with the
    lowest primary key that belongs to the same ProjectClass.  Safe to call
    on every startup.
    """
    with app.app_context():
        updated = 0
        configs = db.session.query(ProjectClassConfig).all()
        for config in configs:
            if config.grading_rubric is not None:
                continue

            rubric = db.session.query(GradingRubric).filter(GradingRubric.pclass_id == config.pclass_id).order_by(GradingRubric.id.asc()).first()
            if rubric is None:
                continue

            config.grading_rubric = rubric
            updated += 1
            print(f"** ensure_config_rubrics: {config.project_class.name} ({config.year}) → rubric '{rubric.label}'")

        if updated:
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                app.logger.exception("SQLAlchemyError in ensure_config_rubrics", exc_info=e)
        else:
            print("** ensure_config_rubrics: all ProjectClassConfig instances already have a rubric (or none available)")


# ---------------------------------------------------------------------------
# Historical MarkingEvent state back-fill
# ---------------------------------------------------------------------------


def ensure_historical_marking_events(app) -> None:
    """
    Idempotently fix state flags on historical MarkingEvents (year < current year).

    For every MarkingEvent whose parent ProjectClassConfig.year is strictly less
    than the current academic year:

    - MarkingReport.report_submitted  → True
    - MarkingReport.feedback_submitted → True
    - SubmitterReport.workflow_state  → FEEDBACK_AVAILABLE (DROPPED records untouched)
    - MarkingWorkflow.completed       → True
    - MarkingEvent.workflow_state     → CLOSED

    Safe to call on every startup; skips records already in the correct state.
    """
    from app.models.markingevent import (
        MarkingEventWorkflowStates,
        SubmitterReportWorkflowStates,
    )

    with app.app_context():
        current_year = get_current_year()

        historical_events = (
            db.session.query(MarkingEvent)
            .join(MarkingEvent.period)
            .join(SubmissionPeriodRecord.config)
            .filter(ProjectClassConfig.year < current_year)
            .all()
        )

        if not historical_events:
            print("** ensure_historical_marking_events: no historical events found")
            return

        mr_report_updated = 0
        mr_feedback_updated = 0
        sr_updated = 0
        wf_updated = 0
        event_updated = 0

        for event in historical_events:
            for workflow in event.workflows.all():
                for sr in workflow.submitter_reports.all():
                    for mr in sr.marking_reports.all():
                        if not mr.report_submitted:
                            mr.report_submitted = True
                            mr_report_updated += 1
                        if not mr.feedback_submitted:
                            mr.feedback_submitted = True
                            mr_feedback_updated += 1

                    if sr.workflow_state not in (
                        SubmitterReportWorkflowStates.FEEDBACK_AVAILABLE,
                        SubmitterReportWorkflowStates.DROPPED,
                    ):
                        sr.workflow_state = SubmitterReportWorkflowStates.FEEDBACK_AVAILABLE
                        sr_updated += 1

                if not workflow.completed:
                    workflow.completed = True
                    wf_updated += 1

            if event.workflow_state != MarkingEventWorkflowStates.CLOSED:
                event.workflow_state = MarkingEventWorkflowStates.CLOSED
                event_updated += 1

        if any([mr_report_updated, mr_feedback_updated, sr_updated, wf_updated, event_updated]):
            try:
                db.session.commit()
                print(
                    f"** ensure_historical_marking_events: "
                    f"fixed {mr_report_updated} MarkingReport.report_submitted, "
                    f"{mr_feedback_updated} MarkingReport.feedback_submitted, "
                    f"{sr_updated} SubmitterReport→FEEDBACK_AVAILABLE, "
                    f"{wf_updated} MarkingWorkflow.completed, "
                    f"{event_updated} MarkingEvent→CLOSED"
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                app.logger.exception("SQLAlchemyError in ensure_historical_marking_events", exc_info=e)
        else:
            print("** ensure_historical_marking_events: all historical events already in correct state")


# ---------------------------------------------------------------------------
# Box token maintenance beat schedule
# ---------------------------------------------------------------------------


def ensure_box_token_schedule(app) -> None:
    """
    Idempotently create the DatabaseSchedulerEntry for the Box token maintenance
    task if it does not already exist.  Safe to call on every startup.
    """
    with app.app_context():
        existing = db.session.query(DatabaseSchedulerEntry).filter_by(name="box-token-maintenance").first()
        if existing is not None:
            print("** ensure_box_token_schedule: schedule entry already present")
            return

        interval = db.session.query(IntervalSchedule).filter_by(every=24, period="hours").first()
        if interval is None:
            interval = IntervalSchedule(every=24, period="hours")
            db.session.add(interval)
            db.session.flush()

        now = datetime.now()
        entry = DatabaseSchedulerEntry(
            name="box-token-maintenance",
            task="app.tasks.box_tokens.maintain_box_tokens",
            interval_id=interval.id,
            crontab_id=None,
            args=[],
            kwargs={},
            queue="default",
            exchange=None,
            routing_key=None,
            expires=None,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            owner_id=None,
        )
        db.session.add(entry)

        try:
            db.session.commit()
            print("** ensure_box_token_schedule: created 'box-token-maintenance' schedule entry")
        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.exception("SQLAlchemyError in ensure_box_token_schedule", exc_info=e)


# ---------------------------------------------------------------------------
# Object-store cloud backup beat schedule
# ---------------------------------------------------------------------------


def ensure_object_store_backup_schedule(app) -> None:
    """
    Idempotently register the DatabaseSchedulerEntry for the object-store
    cloud backup Beat task.

    Does nothing if:
    - OBJECT_STORE_BACKUP_ENABLED is False or absent in app.config.
    - A DatabaseSchedulerEntry named "object-store-cloud-backup" already exists.
    """
    with app.app_context():
        if not app.config.get("OBJECT_STORE_BACKUP_ENABLED", False):
            print("** ObjectStore backup is not enabled, skipping check for scheduled task")
            return

        existing = db.session.query(DatabaseSchedulerEntry).filter_by(name="object-store-cloud-backup").first()
        if existing is not None:
            print("** ensure_object_store_backup_schedule: schedule entry already present")
            return

        # Daily at 03:30 — offset from the DB backup at 02:00 to avoid I/O contention
        crontab = (
            db.session.query(CrontabSchedule)
            .filter_by(
                minute="30",
                hour="3",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
            )
            .first()
        )
        if crontab is None:
            crontab = CrontabSchedule(
                minute="30",
                hour="3",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
            )
            db.session.add(crontab)
            db.session.flush()

        now = datetime.now()
        entry = DatabaseSchedulerEntry(
            name="object-store-cloud-backup",
            task="app.tasks.object_store_backup.backup_object_stores",
            interval_id=None,
            crontab_id=crontab.id,
            args=[],
            kwargs={},
            queue="default",
            exchange=None,
            routing_key=None,
            expires=None,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            owner_id=None,
        )
        db.session.add(entry)

        try:
            db.session.commit()
            print("** ensure_object_store_backup_schedule: created 'object-store-cloud-backup' schedule entry")
        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.exception("SQLAlchemyError in ensure_object_store_backup_schedule", exc_info=e)


def ensure_tombstone_prune_schedule(app) -> None:
    """
    Idempotently register the DatabaseSchedulerEntry for the object-store
    tombstone pruning Beat task.

    Does nothing if:
    - OBJECT_STORE_BACKUP_ENABLED is False or absent in app.config.
    - A DatabaseSchedulerEntry named "object-store-tombstone-prune" already exists.
    """
    with app.app_context():
        if not app.config.get("OBJECT_STORE_BACKUP_ENABLED", False):
            print("** ObjectStore backup is not enabled, skipping check for scheduled task")
            return

        existing = db.session.query(DatabaseSchedulerEntry).filter_by(name="object-store-tombstone-prune").first()
        if existing is not None:
            print("** ensure_tombstone_prune_schedule: schedule entry already present")
            return

        # Daily at 04:30 — after the 03:30 backup run, to avoid overlap
        crontab = (
            db.session.query(CrontabSchedule)
            .filter_by(
                minute="30",
                hour="4",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
            )
            .first()
        )
        if crontab is None:
            crontab = CrontabSchedule(
                minute="30",
                hour="4",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
            )
            db.session.add(crontab)
            db.session.flush()

        now = datetime.now()
        entry = DatabaseSchedulerEntry(
            name="object-store-tombstone-prune",
            task="app.tasks.object_store_backup.prune_object_store_tombstones",
            interval_id=None,
            crontab_id=crontab.id,
            args=[],
            kwargs={"retention_days": 90},
            queue="default",
            exchange=None,
            routing_key=None,
            expires=None,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            owner_id=None,
        )
        db.session.add(entry)

        try:
            db.session.commit()
            print("** ensure_tombstone_prune_schedule: created 'object-store-tombstone-prune' schedule entry")
        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.exception("SQLAlchemyError in ensure_tombstone_prune_schedule", exc_info=e)
