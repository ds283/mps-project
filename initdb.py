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
from typing import Optional, List, Dict

import pandas as pd
from dateutil import parser
from flask_migrate import upgrade
from sqlalchemy import text, func
from sqlalchemy.exc import SQLAlchemyError

from app.database import db
from app.models import (
    User,
    FacultyData,
    EnrollmentRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmissionPeriodRecord,
    ProjectClassConfig,
    SubmittingStudent,
    StudentData,
)
from app.shared.cloud_object_store import ObjectStore, ObjectMeta
from app.shared.conversions import is_integer
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

        p: subprocess.CompletedProcess = subprocess.run(["mysql", "-h", db_hostname, f"-u{user}", f"-p{password}", database], input=fo.read())

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
        self._bucket.put(self._lockfile_name, audit_data="LockFileManager", data=self._data, mimetype="application/octet-stream")

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


def store_supervisor_data(app, bucket: ObjectStore, csv_file: str | Path):
    if isinstance(csv_file, str):
        csv_file = Path(csv_file)

    full_suffix = "".join(csv_file.suffixes)

    # try to lookup a current SubmissionRole instance for this supervisor
    current_year = get_current_year()

    with ScratchFileManager(suffix=full_suffix) as scratch_path:
        with open(scratch_path.path, mode="wb") as f:
            data: bytes = bucket.get(str(csv_file), audit_data="store_supervisor_data")
            f.write(data)

        df = pd.read_csv(scratch_path.path, skiprows=[1, 2])
        for index, row in df.iterrows():
            supervisor_raw = str(row["Q2"])
            supervisor_name = supervisor_raw.split()

            student_and_project_raw = str(row["Q3"])
            student_and_project = student_and_project_raw.split()

            run_again = str(row["Q12"]).split()

            grade_raw = str(row["Q6_1"])
            flag, grade = is_integer(grade_raw)

            justification = str(row["Q7"])
            positive = str(row["Q8"])
            to_improve = str(row["Q9"])

            timestamp_str = str(row["RecordedDate"])
            timestamp = parser.parse(timestamp_str)
            if timestamp is None:
                timestamp = datetime.now()

            # split supervisor name into first + last
            supv_first = supervisor_name[0]

            if len(supervisor_name) == 3:
                # assume in first initial. last form
                if supervisor_name[1] in ["de", "De"]:
                    supv_last = supervisor_name[1] + " " + supervisor_name[2]
                else:
                    supv_last = supervisor_name[2]
            else:
                supv_last = supervisor_name[1]

            flag, candidate_number = is_integer(student_and_project[0])
            if not flag:
                print(f'!! Could not identify candidate number for student/project = "{student_and_project_raw}"')
                continue

            # available responses are "It's likely I will run this project again" and "I don't intend to run this project again"
            available_exemplar = run_again[0] == "It's"

            rec = (
                db.session.query(SubmissionRole)
                .join(SubmissionRecord, SubmissionRecord.id == SubmissionRole.submission_id)
                .join(User, User.id == SubmissionRole.user_id)
                .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
                .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
                .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
                .join(StudentData, StudentData.id == SubmittingStudent.student_id)
                .filter(
                    SubmissionRole.role.in_([SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR]),
                    ProjectClassConfig.year == current_year,
                    StudentData.exam_number == candidate_number,
                    User.last_name == supv_last,
                )
            ).all()

            if len(rec) == 0:
                print(
                    f'!! Could not find SubmissionRole record to match supervisor = "{supervisor_raw}" (supervisor_last = "{supv_last}"), candidate number = "{candidate_number}", student/project = "{student_and_project_raw}"'
                )
                continue

            elif len(rec) > 1:
                print(
                    f'!! Multiple SubmissionRole matches found for supervisor = "{supervisor_raw}" (supervisor_last = "{supv_last}"), candidate number = "{candidate_number}", student/project = "{student_and_project_raw}"'
                )
                continue

            rec: SubmissionRole = rec[0]
            rec.grade = grade
            rec.justification = justification
            rec.positive_feedback = positive
            rec.improvements_feedback = to_improve

            rec.signed_off = timestamp
            rec.submitted_feedback = True
            rec.feedback_timestamp = timestamp

            submission: SubmissionRecord = rec.submission
            submission.report_exemplar = available_exemplar

            # weighting not needed for supervisors
            rec.weight = None

            print(
                f"++ Updated SubmissionRole record for supervisor = {rec.user.name}, student = {rec.submission.owner.student.name}, with grade = {rec.grade}%"
            )

    db.session.commit()


def import_supervisor_data(app, initial_db=None):
    # import initdb ObjectStore from which we can download the CATS limits
    if initial_db is None:
        initial_db = import_module("app.initdb.initdb")

    init_bucket: ObjectStore = initial_db.INITDB_BUCKET
    supervisor_CSV: str = initial_db.INITDB_SUPERVISOR_IMPORT

    _wait_until_unlocked(init_bucket)

    with LockFileManager(init_bucket) as lock:
        contents = init_bucket.list(audit_data="import_supervisor_data")

        if supervisor_CSV not in contents:
            print(f'** ignored INITDB_SUPERVISOR_IMPORT="{supervisor_CSV}", which was not present in the initdb object store')
            return

        print(f'** using INITDB_SUPERVISOR_IMPORT="{supervisor_CSV}" to import supervisor marking data')
        store_supervisor_data(app, init_bucket, supervisor_CSV)


def store_examiner_data(app, bucket: ObjectStore, csv_file: str | Path):
    if isinstance(csv_file, str):
        csv_file = Path(csv_file)

    full_suffix = "".join(csv_file.suffixes)

    # try to lookup a current SubmissionRole instance for this supervisor
    current_year = get_current_year()

    with ScratchFileManager(suffix=full_suffix) as scratch_path:
        with open(scratch_path.path, mode="wb") as f:
            data: bytes = bucket.get(str(csv_file), audit_data="store_examiner_data")
            f.write(data)

        df = pd.read_csv(scratch_path.path, skiprows=[1, 2])
        for index, row in df.iterrows():
            examiner_raw = str(row["Q2"])
            examiner_name = examiner_raw.split()

            student_and_project_raw = str(row["Q3"])
            student_and_project = student_and_project_raw.split()

            grade_raw = str(row["Q6_1"])
            flag, grade = is_integer(grade_raw)

            justification = str(row["Q7"])
            positive = str(row["Q8"])
            to_improve = str(row["Q9"])

            timestamp_str = str(row["RecordedDate"])
            timestamp = parser.parse(timestamp_str)
            if timestamp is None:
                timestamp = datetime.now()

            # split supervisor name into first + last
            examiner_first = examiner_name[0]

            if len(examiner_name) == 3:
                # assume in first initial. last form
                if examiner_name[1] in ["de", "De"]:
                    examiner_last = examiner_name[1] + " " + examiner_name[2]
                else:
                    examiner_last = examiner_name[2]
            else:
                examiner_last = examiner_name[1]

            flag, candidate_number = is_integer(student_and_project[0])
            if not flag:
                print(f'!! Could not identify candidate number for student/project = "{student_and_project_raw}"')
                continue

            rec = (
                db.session.query(SubmissionRole)
                .join(SubmissionRecord, SubmissionRecord.id == SubmissionRole.submission_id)
                .join(User, User.id == SubmissionRole.user_id)
                .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
                .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
                .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
                .join(StudentData, StudentData.id == SubmittingStudent.student_id)
                .filter(
                    SubmissionRole.role.in_([SubmissionRole.ROLE_MARKER]),
                    ProjectClassConfig.year == current_year,
                    StudentData.exam_number == candidate_number,
                    User.last_name == examiner_last,
                )
            ).all()

            if len(rec) == 0:
                print(
                    f'!! Could not find SubmissionRole record to match examiner = "{examiner_raw}" (examiner_last = "{examiner_last}"), candidate number = "{candidate_number}", student/project = "{student_and_project_raw}"'
                )
                continue

            elif len(rec) > 1:
                print(
                    f'!! Multiple SubmissionRole matches found for examiner = "{examiner_raw}" (examiner_last = "{examiner_last}"), candidate number = "{candidate_number}", student/project = "{student_and_project_raw}"'
                )
                continue

            rec: SubmissionRole = rec[0]
            rec.grade = grade
            rec.justification = justification
            rec.positive_feedback = positive
            rec.improvements_feedback = to_improve

            rec.signed_off = timestamp
            rec.submitted_feedback = True
            rec.feedback_timestamp = timestamp

            rec.weight = 0.5

            print(
                f"++ Updated SubmissionRole record for examiner = {rec.user.name}, student = {rec.submission.owner.student.name}, with grade = {rec.grade}%"
            )

    db.session.commit()


def import_examiner_data(app, initial_db=None):
    # import initdb ObjectStore from which we can download the CATS limits
    if initial_db is None:
        initial_db = import_module("app.initdb.initdb")

    init_bucket: ObjectStore = initial_db.INITDB_BUCKET
    examiner_CSV: str = initial_db.INITDB_EXAMINER_IMPORT

    _wait_until_unlocked(init_bucket)

    with LockFileManager(init_bucket) as lock:
        contents = init_bucket.list(audit_data="import_examiner_data")

        if examiner_CSV not in contents:
            print(f'** ignored INITDB_EXAMINER_IMPORT="{examiner_CSV}", which was not present in the initdb object store')
            return

        print(f'** using INITDB_EXAMINER_IMPORT="{examiner_CSV}" to import examiner marking data')
        store_examiner_data(app, init_bucket, examiner_CSV)
