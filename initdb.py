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
from typing import Optional, List, Dict, Set

import pandas as pd
from dateutil import parser
from flask_migrate import upgrade
from numpy import nan
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
    Tenant,
    ProjectClass, Project, ProjectTagGroup, ProjectTag, LiveProject, SupervisionEvent, SubmissionPeriodUnit,
)
from app.models.emails import EmailTemplate, EmailTemplateTypesMixin
from app.shared.cloud_object_store import ObjectStore, ObjectMeta
from app.shared.conversions import is_integer
from app.shared.scratch import ScratchFileManager
from app.shared.sqlalchemy import get_count
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


def store_attendance_data(app, bucket: ObjectStore, csv_file: str | Path):
    if isinstance(csv_file, str):
        csv_file = Path(csv_file)

    full_suffix = "".join(csv_file.suffixes)

    current_year = get_current_year()

    with ScratchFileManager(suffix=full_suffix) as scratch_path:
        with open(scratch_path.path, mode="wb") as f:
            data: bytes = bucket.get(str(csv_file), audit_data="store_attendance_data")
            f.write(data)

        def get_value(value):
            if value is None:
                return None

            if value is nan:
                return None

            if isinstance(value, str) and len(value) == 0:
                return None

            if isinstance(value, str):
                return value.strip()

            return str(value).strip()

        df = pd.read_csv(scratch_path.path)
        print(df)
        for index, row in df.iterrows():
            student_raw_name = get_value(row["Student"])
            week_raw: str = get_value(row["Week"])
            attendance_raw = get_value(row["Attendance"])
            summary_raw = get_value(row["Summary"])
            notes_raw = get_value(row["Notes"])

            student_name = student_raw_name.split()
            # split student name into first + last
            student_first = student_name[0]

            if len(student_name) == 3:
                # assume in first initial. last form
                if student_name[1] in ["de", "De"]:
                    student_last = student_name[1] + " " + student_name[2]
                else:
                    student_last = student_name[2]
            else:
                student_last = student_name[1]

            rec = (
                db.session.query(SupervisionEvent)
                .join(SubmissionPeriodUnit, SubmissionPeriodUnit.id == SupervisionEvent.unit_id)
                .join(SubmissionRecord, SubmissionRecord.id == SupervisionEvent.sub_record_id)
                .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
                .join(StudentData, StudentData.id == SubmittingStudent.student_id)
                .join(User, User.id == StudentData.id)
                .filter(
                    ProjectClassConfig.year == current_year,
                    User.last_name == student_last,
                    User.first_name == student_first,
                    SubmissionPeriodUnit.name == week_raw,
                )
                .order_by(SubmissionPeriodUnit.start_date)
            ).all()

            if len(rec) == 0:
                print(f'!! Could not find SupervisionEvent record for student = "{student_raw_name}" (student_last = "{student_last}"), week = "{week_raw}"')
                continue

            elif len(rec) > 1:
                print(f'!! Multiple SupervisionEvent matches found for student = "{student_raw_name}" (student_last = "{student_last}"), week = "{week_raw}"; using only the first record')

            attendance_map = {
                "Yes, and was on time": SupervisionEvent.ATTENDANCE_ON_TIME,
                "Yes, but was not on time": SupervisionEvent.ATTENDANCE_LATE,
                "No": SupervisionEvent.ATTENDANCE_NO_SHOW_NOTIFIED,
            }

            if attendance_raw not in attendance_map:
                print(f'!! Could not identify attendance for student = "{student_raw_name}" (student_last = "{student_last}"), week = "{week_raw}", attendance = "{attendance_raw}"')
                continue

            rec: SupervisionEvent = rec[0]
            rec.attendance = attendance_map[attendance_raw]
            rec.meeting_summary = summary_raw
            rec.supervision_notes = notes_raw

            print(f"++ Updated SupervisionEvent record for student = {student_raw_name}, week = {week_raw}")

    db.session.commit()


def import_attendance_data(app, initial_db=None):
    # import initdb ObjectStore from which we can download the data
    if initial_db is None:
        initial_db = import_module("app.initdb.initdb")

    init_bucket: ObjectStore = initial_db.INITDB_BUCKET
    attendance_CSV: str = initial_db.INITDB_ATTENDANCE_IMPORT

    _wait_until_unlocked(init_bucket)

    with LockFileManager(init_bucket) as lock:
        contents = init_bucket.list(audit_data="import_attendance_data")

        if attendance_CSV not in contents:
            print(f'** ignored INITDB_ATTENDANCE_IMPORT="{attendance_CSV}", which was not present in the initdb object store')
            return

        print(f'** using INITDB_ATTENDANCE_IMPORT="{attendance_CSV}" to import attendance data')
        store_attendance_data(app, init_bucket, attendance_CSV)


# tenant names used for assignment
_TENANT_DATA_SCIENCE = "Data Science MSc"
_TENANT_PHYSICS_ASTRONOMY = "Physics & Astronomy"

# ProjectClass names that map to the Data Science MSc tenant
_DS_PCLASS_NAMES = {"Data Science", "Human & Social Data Science"}

# ResearchGroup names that map to the Data Science MSc tenant (used as fallback for faculty
# with no enrollment records)
_DS_RESEARCH_GROUP_NAMES = {"Informatics", "Engineering & Design", "Life Sciences", "Mathematics"}


def assign_tenants(app):
    """
    Assign Tenant records to each User based on their role and enrolment data.

    Faculty users:
      - Assigned the "Data Science MSc" tenant if they have an EnrollmentRecord for a
        ProjectClass whose name is "Data Science" or "Human and Social Data Science".
      - Assigned the "Physics & Astronomy" tenant if they have an EnrollmentRecord for
        any other ProjectClass.
      - A faculty member may therefore be assigned both tenants simultaneously.
      - If a faculty member has no enrollment records at all, a fallback based on their
        ResearchGroup affiliations is used instead: they are assigned "Data Science MSc"
        if any affiliation is in {"Informatics", "Engineering & Design", "Life Sciences",
        "Mathematics"}, and "Physics & Astronomy" otherwise.

    Student users:
      - Assigned the "Data Science MSc" tenant if their degree programme name contains
        the substring "Data Science".
      - Otherwise assigned the "Physics & Astronomy" tenant.
      - A student is assigned exactly one tenant.
    """
    # look up the two tenant records we need
    ds_tenant: Tenant = db.session.query(Tenant).filter(Tenant.name == _TENANT_DATA_SCIENCE).first()
    if ds_tenant is None:
        print(f'!! assign_tenants: could not find Tenant with name "{_TENANT_DATA_SCIENCE}" — aborting')
        return

    pa_tenant: Tenant = db.session.query(Tenant).filter(Tenant.name == _TENANT_PHYSICS_ASTRONOMY).first()
    if pa_tenant is None:
        print(f'!! assign_tenants: could not find Tenant with name "{_TENANT_PHYSICS_ASTRONOMY}" — aborting')
        return

    users: List[User] = db.session.query(User).all()
    assigned_count = 0

    for user in users:
        user: User

        if user.has_role("faculty"):
            fd: FacultyData = db.session.query(FacultyData).filter(FacultyData.id == user.id).first()
            if fd is None:
                print(f'-- !! assign_tenants: user "{user.name}" has faculty role but no FacultyData record — skipping')
                continue

            want_ds = False
            want_pa = False

            enrollments = fd.enrollments.all()

            if len(enrollments) > 0:
                # primary path: determine tenants from enrollment records
                for enrollment in enrollments:
                    enrollment: EnrollmentRecord
                    pclass: ProjectClass = enrollment.pclass
                    if pclass is None:
                        continue

                    if pclass.name in _DS_PCLASS_NAMES:
                        want_ds = True
                    else:
                        want_pa = True
            else:
                # fallback path: no enrollment records — use ResearchGroup affiliations
                affiliations = fd.affiliations.all()
                affiliation_names = {g.name for g in affiliations}
                if affiliation_names & _DS_RESEARCH_GROUP_NAMES:
                    want_ds = True
                else:
                    want_pa = True
                print(
                    f'-- ?? assign_tenants: faculty user "{user.name}" has no enrollment records; '
                    f'falling back to research group affiliations {affiliation_names}'
                )

            if want_ds and ds_tenant not in user.tenants:
                user.tenants.append(ds_tenant)
                print(f'-- >> assign_tenants: assigned tenant "{_TENANT_DATA_SCIENCE}" to faculty user "{user.name}"')

            if want_pa and pa_tenant not in user.tenants:
                user.tenants.append(pa_tenant)
                print(f'-- >> assign_tenants: assigned tenant "{_TENANT_PHYSICS_ASTRONOMY}" to faculty user "{user.name}"')

            assigned_count += 1

        elif user.has_role("student"):
            sd: StudentData = db.session.query(StudentData).filter(StudentData.id == user.id).first()
            if sd is None:
                print(f'-- !! assign_tenants: user "{user.name}" has student role but no StudentData record — skipping')
                continue

            programme = sd.programme
            if programme is None:
                print(f'-- !! assign_tenants: student user "{user.name}" has no degree programme — skipping')
                continue

            if "Data Science" in programme.name:
                if ds_tenant not in user.tenants:
                    user.tenants.append(ds_tenant)
                print(f'-- >> assign_tenants: assigned tenant "{_TENANT_DATA_SCIENCE}" to student user "{user.name}"')
            else:
                if pa_tenant not in user.tenants:
                    user.tenants.append(pa_tenant)
                print(f'-- >> assign_tenants: assigned tenant "{_TENANT_PHYSICS_ASTRONOMY}" to student user "{user.name}"')

            assigned_count += 1

    db.session.commit()
    print(f"** assign_tenants: tenant assignment complete; processed {assigned_count} user(s)")


def demerge_project_tags(app):
    def demerge_tags(project, allowed_tenant_ids: Set[int]):
        if len(allowed_tenant_ids) == 0:
            raise RuntimeError(f'-- !! demerge_project_tags: no allowed tenant ids provided')

        for tag in project.tags:
            tag_group: ProjectTagGroup = tag.group

            is_ok: bool = any([(t.id in allowed_tenant_ids) for t in tag_group.tenants])

            if not is_ok:
                print(f'-- >> demerge_project_tags: removing tag "{tag.name}" from project "{project.name}" (allowed tenant ids = {allowed_tenant_ids})')

                replacement_tag = (
                    db.session.query(ProjectTag)
                    .join(ProjectTagGroup, ProjectTagGroup.id == ProjectTag.group_id)
                    .filter(
                        ProjectTag.name == tag.name,
                        ProjectTagGroup.tenants.any(Tenant.id.in_(allowed_tenant_ids)),
                    )
                    .first()
                )

                if replacement_tag is not None:
                    project.tags.remove(tag)
                    project.tags.append(replacement_tag)
                else:
                    default_group = (
                        db.session.query(ProjectTagGroup)
                        .filter(
                            ProjectTagGroup.default == True,
                            ProjectTagGroup.tenants.any(Tenant.id.in_(allowed_tenant_ids)),
                        )
                        .first()
                    )

                    if default_group is None:
                        print(
                            f'-- !! demerge_project_tags: could not find replacement tag for "{tag.name}" and no default list exists: removing this tag')
                        project.tags.remove(tag)
                    else:
                        print(
                            f'-- >> demerge_project_tags: could not find replacement tag for "{tag.name}": creating new tag in default list {default_group.name}')
                        new_tag = ProjectTag(
                            name = tag.name,
                            group = default_group,
                            active=True
                        )
                        db.session.add(new_tag)
                        db.session.flush()
                        project.tags.remove(tag)
                        project.tags.append(new_tag)

    projects: List[Project] = db.session.query(Project).all()

    for project in projects:
        project: Project
        allowed_tenant_ids: Set[int] = set([p.tenant_id for p in project.project_classes])
        if len(allowed_tenant_ids) == 0:
            if project.owner is not None:
                allowed_tenant_ids = set([t.id for t in project.owner.user.tenants])
            else:
                print(f'-- !! demerge_project_tags: could not find allowed tenant ids for project "{project.name}"')
                continue

        demerge_tags(project, allowed_tenant_ids)

    liveprojects: List[LiveProject] = db.session.query(LiveProject).all()

    for project in liveprojects:
        project: LiveProject
        allowed_tenant_ids: List[int] = [project.config.project_class.tenant_id]
        demerge_tags(project, allowed_tenant_ids)

    db.session.commit()
    db.session.begin()

    all_tags: List[ProjectTag] = db.session.query(ProjectTag).all()
    for tag in all_tags:
        tag: ProjectTag

        if get_count(tag.projects) == 0 and get_count(tag.live_projects) == 0:
            print(f'-- >> demerge_project_tags: tag "{tag.name}" in group "{tag.group.name}" is not used: pruning this tag')
            db.session.delete(tag)

    db.session.commit()


def populate_email_templates(app):
    """
    Populate the EmailTemplate table with the default email templates found in
    app/templates/email/.

    Rules:
      - Where both an .html and a .txt file exist with the same stem, use the .html
        version for html_body and ignore the .txt file.
      - Where only a .txt file exists, use it for html_body.
      - tenant_id and pclass_id are set to None (global defaults).
      - version is set to 1.
      - If a record with the same type already exists, it is skipped.
    """

    # Locate the email templates directory relative to this file's location.
    # initdb.py lives at the project root, alongside the 'app' package.
    base_dir: Path = Path(__file__).parent / "app" / "templates" / "email"

    # Each entry is a tuple of:
    #   (type_constant, relative_template_path, subject, comment)
    # relative_template_path is relative to base_dir and should NOT include the extension;
    # the function will resolve .html vs .txt automatically.
    _TEMPLATE_DEFINITIONS = [
        # ── backups ──────────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.BACKUP_REPORT_THINNING,
            "backups/report_thinning",
            "[mpsprojects] Backup thinning report at {date}",
            "Periodic report sent to administrators summarising which backup records were "
            "retained and which were dropped during the automated backup-thinning process.",
        ),
        # ── close_selection ──────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.CLOSE_SELECTION_CONVENOR,
            "close_selection/convenor",
            '[mpsprojects] "{name}": student selections now closed',
            "Advisory email sent to the project convenor (and co-convenors / office contacts) "
            "when student selections for a project class are closed, summarising submission "
            "statistics.",
        ),
        # ── go_live ──────────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.GO_LIVE_CONVENOR,
            "go_live/convenor",
            '[mpsprojects] "{name}": project list now published to students',
            "Advisory email sent to the project convenor (and co-convenors / office contacts) "
            "when the project list for a project class goes live, confirming the number of "
            "projects published and the student selection deadline.",
        ),
        (
            EmailTemplateTypesMixin.GO_LIVE_FACULTY,
            "go_live/faculty",
            "{name}: project list now published to students",
            "Notification email sent to enrolled faculty supervisors when the project list "
            "goes live, listing their published projects and advising whether any require "
            "student sign-off before selection.",
        ),
        (
            EmailTemplateTypesMixin.GO_LIVE_SELECTOR,
            "go_live/selector",
            "{name}: project list now available",
            "Notification email sent to student selectors when the project list for their "
            "project class goes live, providing the selection deadline and a link to the "
            "live platform.",
        ),
        # ── maintenance ──────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.MAINTENANCE_LOST_ASSETS,
            "maintenance/lost_assets",
            "[{app_name}] Lost asset report at {time}",
            "Maintenance report emailed to administrators listing asset records whose "
            "corresponding objects could not be found in the cloud object store.",
        ),
        (
            EmailTemplateTypesMixin.MAINTENANCE_UNATTACHED_ASSETS,
            "maintenance/unattached_assets",
            "[{app_name}] Unattached asset report at {time}",
            "Maintenance report emailed to administrators listing submitted asset records "
            "that are not attached to any submission record or period attachment.",
        ),
        # ── marking ──────────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.MARKING_MARKER,
            "marking/marker",
            "IMPORTANT: {abbv} project marking: candidate {number} - DEADLINE {deadline} - DO NOT REPLY",
            "Email sent to examiners / markers distributing the student report for marking, "
            "together with any additional attachments specified by the convenor, and "
            "providing the marking deadline.",
        ),
        (
            EmailTemplateTypesMixin.MARKING_SUPERVISOR,
            "marking/supervisor",
            "IMPORTANT: {abbv} project marking: {stu} - DEADLINE {deadline} - DO NOT REPLY",
            "Email sent to project supervisors distributing the student report for marking, "
            "together with any additional attachments specified by the convenor, and "
            "providing the marking deadline.",
        ),
        # ── matching ─────────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_FACULTY,
            "matching/draft_notify_faculty",
            "Notification: Draft Final Year Project allocation for {yra}-{yrb}",
            "Email sent to faculty supervisors notifying them of their draft project "
            "allocations in a matching attempt, broken down by project class.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_DRAFT_NOTIFY_STUDENTS,
            "matching/draft_notify_students",
            'Notification: Draft project allocation for "{name}" {yra}-{yrb}',
            "Email sent to student selectors notifying them of their draft project "
            "allocation in a matching attempt.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_DRAFT_UNNEEDED_FACULTY,
            "matching/draft_unneeded_faculty",
            "Notification: Draft Final Year Project allocation for {yra}-{yrb}",
            "Email sent to faculty supervisors who have no allocations in a draft matching "
            "attempt, informing them that they are not needed for this cycle.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_FACULTY,
            "matching/final_notify_faculty",
            "Notification: Final Year Project allocation for {yra}-{yrb}",
            "Email sent to faculty supervisors notifying them of their final confirmed "
            "project allocations, broken down by project class.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_FINAL_NOTIFY_STUDENTS,
            "matching/final_notify_students",
            'Notification: Final project allocation for "{name}" {yra}-{yrb}',
            "Email sent to student selectors notifying them of their final confirmed "
            "project allocation.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_FINAL_UNNEEDED_FACULTY,
            "matching/final_unneeded_faculty",
            "Notification: Final Year Project allocation for {yra}-{yrb}",
            "Email sent to faculty supervisors who have no allocations in the final "
            "matching, informing them that they are not needed for this cycle.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_GENERATED,
            "matching/generated",
            "Files for offline matching of {name} are now ready",
            "Email sent to the requesting user when the LP/MPS files needed for offline "
            "matching have been generated and are ready for download.",
        ),
        (
            EmailTemplateTypesMixin.MATCHING_NOTIFY_EXCEL_REPORT,
            "matching/notify_excel_report",
            "Excel report for matching {name} is now ready",
            "Email sent to the requesting user when an Excel summary report for a matching "
            "attempt has been generated and is ready for download.",
        ),
        # ── notifications ────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.NOTIFICATIONS_REQUEST_MEETING,
            "notifications/request_meeting",
            "{name}: project meeting request",
            "Email sent jointly to a student and their prospective supervisor when the "
            "student requests a confirmation meeting for a project that requires sign-off "
            "before selection.",
        ),
        (
            EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_ROLLUP,
            "notifications/faculty/rollup",
            "{branding_label}: summary of notifications and events",
            "Daily summary email sent to faculty members grouping together all pending "
            "notifications and outstanding confirmation requests into a single digest.",
        ),
        (
            EmailTemplateTypesMixin.NOTIFICATIONS_FACULTY_SINGLE,
            "notifications/faculty/single",
            "{subject}",
            "Individual notification email sent promptly to a faculty member for a single "
            "event (e.g. a new confirmation request), used when the user has opted out of "
            "grouped summaries.",
        ),
        (
            EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_ROLLUP,
            "notifications/student/rollup",
            "{branding_label}: summary of notifications and events",
            "Daily summary email sent to students grouping together all pending "
            "notifications and outstanding confirmation requests into a single digest.",
        ),
        (
            EmailTemplateTypesMixin.NOTIFICATIONS_STUDENT_SINGLE,
            "notifications/student/single",
            "{subject}",
            "Individual notification email sent promptly to a student for a single event, "
            "used when the user has opted out of grouped summaries.",
        ),
        # ── project_confirmation ─────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REMINDER,
            "project_confirmation/confirmation_reminder",
            "Reminder: please check projects for {name}",
            "Reminder email sent to faculty supervisors who have not yet confirmed their "
            "project descriptions after the initial confirmation request was issued.",
        ),
        (
            EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REQUESTED,
            "project_confirmation/confirmation_requested",
            "Please check projects for {name}",
            "Initial email sent to faculty supervisors asking them to review and confirm "
            "their project descriptions before the project list goes live.",
        ),
        (
            EmailTemplateTypesMixin.PROJECT_CONFIRMATION_NEW_COMMENT,
            "project_confirmation/new_comment",
            '[mpsprojects] A comment was posted on "{proj}/{desc}"',
            "Notification email sent to watchers of a project description when a new "
            "comment is posted during the project approval workflow.",
        ),
        (
            EmailTemplateTypesMixin.PROJECT_CONFIRMATION_REVISE_REQUEST,
            "project_confirmation/revise_request",
            "Projects: please consider revising {name}/{desc}",
            "Email sent to a faculty supervisor by a project approver requesting that a "
            "specific project description be revised before it can be approved.",
        ),
        # ── push_feedback ────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_MARKER,
            "push_feedback/push_to_marker",
            "{pclass} {period}: Examiner feedback for project students",
            "Email sent to examiners / markers when feedback is pushed, summarising the "
            "feedback they provided for each of their assigned students.",
        ),
        (
            EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_STUDENT,
            "push_feedback/push_to_student",
            "{proj}: Feedback for {name}",
            "Email sent to a student when their project feedback is released, including "
            "supervisor and examiner comments and any attached feedback report.",
        ),
        (
            EmailTemplateTypesMixin.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR,
            "push_feedback/push_to_supervisor",
            "{pclass} {period}: Feedback for supervision students",
            "Email sent to supervisors when feedback is pushed, summarising the feedback "
            "they provided for each of their supervised students.",
        ),
        # ── scheduling ───────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REMINDER,
            "scheduling/availability_reminder",
            "Reminder: availability for event {name}",
            "Reminder email sent to faculty assessors who have not yet confirmed their "
            "availability for a presentation assessment event.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_AVAILABILITY_REQUEST,
            "scheduling/availability_request",
            "Availability request for event {name}",
            "Initial email sent to faculty assessors requesting that they enter their "
            "availability for a presentation assessment event before the specified deadline.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_FACULTY,
            "scheduling/draft_notify_faculty",
            'Notification: Draft timetable for project assessment "{name}"',
            "Email sent to faculty assessors notifying them of their assigned slots in a "
            "draft presentation timetable.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_DRAFT_NOTIFY_STUDENTS,
            "scheduling/draft_notify_students",
            'Notification: Draft timetable for project assessment "{name}"',
            "Email sent to student submitters notifying them of their assigned slot in a "
            "draft presentation timetable.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_DRAFT_UNNEEDED_FACULTY,
            "scheduling/draft_unneeded_faculty",
            'Notification: Draft timetable for project assessment "{name}"',
            "Email sent to faculty assessors who are not required in a draft presentation "
            "timetable, informing them that no sessions have been assigned to them.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_FACULTY,
            "scheduling/final_notify_faculty",
            'Notification: Final timetable for project assessment "{name}"',
            "Email sent to faculty assessors notifying them of their assigned slots in the "
            "final published presentation timetable.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_FINAL_NOTIFY_STUDENTS,
            "scheduling/final_notify_students",
            'Notification: Final timetable for project assessment "{name}"',
            "Email sent to student submitters notifying them of their assigned slot in the "
            "final published presentation timetable.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_FINAL_UNNEEDED_FACULTY,
            "scheduling/final_unneeded_faculty",
            'Notification: Final timetable for project assessment "{name}"',
            "Email sent to faculty assessors who are not required in the final published "
            "presentation timetable, informing them that no sessions have been assigned to them.",
        ),
        (
            EmailTemplateTypesMixin.SCHEDULING_GENERATED,
            "scheduling/generated",
            "Files for offline scheduling of {name} are now ready",
            "Email sent to the requesting user when the LP file needed for offline "
            "scheduling of a presentation assessment has been generated and is ready for "
            "download or attachment.",
        ),
        # ── services ─────────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.SERVICES_CC_EMAIL,
            "services/cc_email",
            "{subject}",
            "Wrapper template used to deliver a copy (CC) of a bulk distribution-list "
            "email to a nominated notify address, with a preamble explaining the context.",
        ),
        (
            EmailTemplateTypesMixin.SERVICES_SEND_EMAIL,
            "services/send_email",
            "{subject}",
            "Wrapper template used to deliver the body of a bulk distribution-list email "
            "to individual recipients, with optional per-recipient personalisation.",
        ),
        # ── student_notifications ────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED,
            "student_notifications/choices_received",
            "Your project choices have been received ({pcl})",
            "Confirmation email sent to a student immediately after they submit their "
            "ranked project preferences, listing the recorded selection and the current "
            "submission deadline.",
        ),
        (
            EmailTemplateTypesMixin.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY,
            "student_notifications/choices_received_proxy",
            "An administrator has submitted project choices on your behalf ({pcl})",
            "Confirmation email sent to a student when a system administrator submits a "
            "project selection on their behalf, listing the recorded selection and advising "
            "that the student may override it before the deadline.",
        ),
        # ── system ───────────────────────────────────────────────────────────────
        (
            EmailTemplateTypesMixin.SYSTEM_GARBAGE_COLLECTION,
            "system/garbage_collection",
            "[mpsprojects] Garbage collection statistics",
            "Periodic advisory email sent to administrators containing garbage-collection "
            "statistics gathered during routine database and asset maintenance.",
        ),
    ]

    def _read_template(stem: str) -> Optional[str]:
        """
        Given a path stem relative to base_dir (no extension), return the content of
        the best available template file.  Prefers .html over .txt.  Returns None if
        neither exists.
        """
        html_path: Path = base_dir / (stem + ".html")
        txt_path: Path = base_dir / (stem + ".txt")

        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        elif txt_path.exists():
            return txt_path.read_text(encoding="utf-8")
        else:
            return None

    added = 0
    skipped = 0

    for type_constant, stem, subject, comment in _TEMPLATE_DEFINITIONS:
        # skip if a record with this type already exists
        existing: Optional[EmailTemplate] = db.session.query(EmailTemplate).filter_by(type=type_constant).first()
        if existing is not None:
            print(f'-- >> populate_email_templates: skipping type={type_constant} ("{stem}") — record already exists')
            skipped += 1
            continue

        body: Optional[str] = _read_template(stem)
        if body is None:
            print(f'-- !! populate_email_templates: could not find template file for stem "{stem}" — skipping')
            skipped += 1
            continue

        record = EmailTemplate(
            active=True,
            tenant_id=None,
            pclass_id=None,
            type=type_constant,
            subject=subject,
            html_body=body,
            comment=comment,
            version=1,
            last_used=None,
        )
        db.session.add(record)
        added += 1
        print(f'-- >> populate_email_templates: added type={type_constant} ("{stem}")')

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("SQLAlchemyError exception while populating email templates", exc_info=e)
        return

    print(f"** populate_email_templates: complete — {added} record(s) added, {skipped} skipped")
