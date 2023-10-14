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

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.shared.cloud_object_store import ObjectStore, ObjectMeta
from app.shared.scratch import ScratchFileManager


def execute_query(app, query):
    try:
        result = db.session.execute(text(query))
    except SQLAlchemyError as e:
        app.logger.info('** encountered exception while emplacing SQL line')
        app.logger.info(f'     {query}')
        app.logger.exception("SQLAlchemyError exception", exc_info=e)


def get_current_datetime():
    now: datetime = datetime.now()
    now_str: str = now.strftime('%Y-%m-%d %H:%M:%S')

    # if month is Oct, Nov, Dec, current academic year matches current calendar year
    # otherwise, current academic year is calendar year - 1
    if now.month in [10, 11, 12]:
        current_year = now.year
    else:
        current_year = now.year-1

    return {'timestamp': now_str,
            'main_year': str(current_year)}


def execute_scripts(app, script, data):
    with open(script, 'r') as file:
        while line := file.readline():
            line = line.replace('$$TIMESTAMP', data['timestamp'])
            line = line.replace('$$MAIN_YEAR', data['main_year'])
            execute_query(app, line)


def sql_script_populate(app, script):
    data = get_current_datetime()

    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
    execute_scripts(app, script, data)
    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))

    db.session.commit()


def populate_table_if_empty(app, inspector, bucket: ObjectStore, table: str, sql_script: Path):
    if not inspector.has_table(table):
        app.logger.error(f'!! FATAL: database is missing the "{table}" table and is not ready. '
                         f'Check that the Alembic migration script has run correctly, or '
                         f'rebuild the database from a mysqldump dump.')
        exit()

    out = db.session.execute(text(f'SELECT COUNT(*) FROM {table};')).first()
    count = out[0]

    if count == 0:
        app.logger.info(f'** table "{table}" is empty, beginning to auto-populate using script "{sql_script}"')

        with ScratchFileManager(suffix='.sql') as scratch_path:
            with open(scratch_path.path, 'wb') as f:
                data: bytes = bucket.get(str(sql_script))
                f.write(data)

            sql_script_populate(app, scratch_path.path)


def tarfile_populate(app, bucket: ObjectStore, tarfile: Path):
    # get database details from configuration
    user = app.config['DATABASE_USER']
    password = app.config['DATABASE_PASSWORD']
    database = app.config['DATABASE_NAME']
    db_hostname = app.config['DATABASE_HOSTNAME']

    with ScratchFileManager(suffix=tarfile.suffix) as scratch_path:
        with open(scratch_path.path, 'wb') as f:
            data: bytes = bucket.get(str(tarfile))
            f.write(data)

        tf: TarFile = tarfile_open(name=scratch_path.path, mode='r')
        contents_list: List[TarInfo] = tf.getmembers()
        contents_dict: Dict[str, TarInfo] = {x.name: x for x in contents_list}

        if 'database.sql' not in contents_dict:
            raise RuntimeError(f'!! initdb tarfile {tarfile} did not contain a database.sql script')

        to: TarInfo = contents_dict['database.sql']
        fo = tf.extractfile(to)
        if fo is None:
            raise RuntimeError(f'!! initdb tarfile {tarfile} contains a "database.sql" object, but it did '
                               f'not extract correctly from the archive')

        p: subprocess.CompletedProcess = \
            subprocess.run(['mysql', "-h", db_hostname, f"-u{user}", f"-p{password}", database], stdin=fo)

        if p.returncode != 0:
            raise RuntimeError(f'!! mysql re-population did not complete successfully')


def initial_populate_database(app, inspector):
    # first import ObjectStore containing the initial database setup scripts
    initial_db = import_module('app.initdb.initdb')
    init_bucket: ObjectStore = initial_db.INITDB_BUCKET
    init_tarfile: Optional[Path] = initial_db.INITDB_TARFILE

    # query the bucket for a list of contents
    contents = init_bucket.list()

    lockfile_name = '_lockfile'
    if lockfile_name in contents:
        print(f'** initdb bucket is locked; waiting for lock to be released')
        count = 0
        max_cycles = 100

        while True:
            # sleep for 5 seconds
            time.sleep(5)
            count += 1
            print(f'   -- waiting ({count})')

            if count > max_cycles:
                print(f'   -- waited for {max_cycles} cycles, breaking out now')
                break

            try:
                data: ObjectMeta = init_bucket.head(lockfile_name)
            except FileNotFoundError:
                print(f'** initdb bucket lock has been released')
                break

        return

    class LockFileManager:
        def __init__(self, bucket: ObjectStore):
            self._bucket = bucket
            self._data = 'lock'.encode()

        def __enter__(self):
            self._bucket.put(lockfile_name, self._data, mimetype='application/octet-stream')

        def __exit__(self, exc_type, exc_val, exc_tb):
            self._bucket.delete(lockfile_name)

    with LockFileManager(init_bucket) as lock:
        tar_files: List[Path] = []
        sql_files: List[Path] = []

        for object in contents:
            object: str
            fname: Path = Path(object)
            if fname.suffix in ['.tar', '.tar.gz', '.tar.bz2']:
                tar_files.append(fname)
            elif fname.suffix in ['.sql']:
                sql_files.append(fname)
            else:
                print(f'** ignored unmatched object in initial bucket with name "{object}"')

        if len(tar_files) > 1:
            print(f'** more than one tarfile was present in the initial object bucket')

            if init_tarfile is not None and init_tarfile in tar_files:
                print(f'** using tarfile {init_tarfile} specified in environment')

                tarfile_populate(app, init_bucket, init_tarfile)
            else:
                tar_files.sort(reverse=True)
                use_tarfile = tar_files[0]
                print(f'** using tarfile {use_tarfile} to populate database')

                tarfile_populate(app, init_bucket, use_tarfile)

        for sql_file in sql_files:
            table: str = sql_file.stem

            # first three characters of table should be of the form NN_ where NN is a number that
            # indicates the sequence in which the tables should be populated
            table = table[3:]
            populate_table_if_empty(app, inspector, init_bucket, table, sql_file)
