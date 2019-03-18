#
# Created by David Seery on 2019-03-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from celery import group, chain
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_
from sqlalchemy.sql.functions import func

from ..database import db
from ..models import UploadedAsset, TaskRecord, User, StudentBatch, StudentBatchItem, DegreeProgramme, StudentData
from ..task_queue import progress_update, register_task
from ..shared.sqlalchemy import get_count
from ..shared.utils import make_generated_asset_filename, canonical_uploaded_asset_filename

import csv
from datetime import datetime
from dateutil.parser import parse


def register_batch_create_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def students(self, record_id, asset_id, current_user_id, current_year):
        try:
            record = db.session.query(StudentBatch).filter_by(id=record_id).first()
            asset = db.session.query(UploadedAsset).filter_by(id=asset_id).first()
            user = db.session.query(User).filter_by(id=current_user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None or asset is None or user is None:
            self.update_state(state='FAILURE', meta='Could not load database records')

            record.celery_finished = True
            record.success = False

            try:
                db.session.commit()
            except SQLAlchemyError:
                raise self.retry()

            raise RuntimeError('Could not load database records')

        progress_update(record.celery_id, TaskRecord.RUNNING, 10, "Inspecting uploaded user list...", autocommit=True)

        with open(canonical_uploaded_asset_filename(asset.filename), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

            required_fields = ['Name', 'Registration Number', 'Student Status', 'Year of Course', 'Course Code',
                               'Username', 'Email Address', 'Start Date']

            missing_fields = []
            for item in required_fields:
                if item not in headers:
                    missing_fields.append(item)

            if len(missing_fields) > 0:
                user.post_message('Failed to process student batch creation; the following columns were missing: '
                                  '{missing}.'.format(missing=', '.join(missing_fields)), 'error')
                progress_update(record.celery_id, TaskRecord.FAILURE, 100,
                                "Uploaded file was not in correct format", autocommit=True)

                record.celery_finished = True
                record.success = False

                try:
                    db.session.commit()
                except SQLAlchemyError:
                    raise self.retry()

                raise RuntimeError('Missing fields in input CSV')

            progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Reading uploaded user list...", autocommit=True)

            lines = 0
            interpreted_lines = 0

            ignored_lines = []

            for row in reader:
                lines += 1

                # in Python 3.6, row is an OrderedDict

                # get name and break into comma-separated parts
                name = row['Name']
                name_parts = [x.strip() for x in name.split(',') if len(x) > 0]

                if len(name_parts) == 0:
                    ignored_lines.append('<line #{no}>'.format(no=lines))
                    continue

                if len(name_parts) >= 2:
                    last_name_parts = [x.strip() for x in name_parts[0].split(' ') if len(x) > 0]
                    first_name_parts = [x.strip() for x in name_parts[1].split(' ') if len(x) > 0]

                    if len(last_name_parts) == 0 or len(first_name_parts) == 0:
                        print('## skipping row {row} because cannot identify one or both of first and last name'.format(row=lines))
                        ignored_lines.append('<line #{no}>'.format(no=lines))
                        continue

                    last_name = ' '.join(last_name_parts)
                    first_name = first_name_parts[0]

                else:
                    last_name_parts = [x.strip() for x in name_parts[0].split(' ') if len(x) > 0]

                    if len(last_name_parts) == 0:
                        print('## skipping row {row} because cannot identify last name'.format(row=lines))
                        ignored_lines.append('<line #{no}>'.format(no=lines))
                        continue

                    last_name = ' '.join(last_name_parts)
                    first_name = '<Unknown>'

                username = row['Username']

                registration_number = int(row['Registration Number'])

                intermitting = (row['Student Status'].lower() == 'intermitting')

                course_code = row['Course Code']
                programme = db.session.query(DegreeProgramme).filter_by(course_code=course_code).first()

                # ignore lines where we cannot determine the programme -- they're probably V&E students
                if programme is None:
                    print('## skipping row "{user}" because cannot identify degree programme'.format(user=username))
                    ignored_lines.append(username)
                    continue

                email = row['Email Address']

                # ignore cases where the email address is 'INTERMITTING'
                if email.lower() == 'intermitting':
                    print('## skipping row "{user}" because email is "INTERMITTING"'.format(user=username))
                    ignored_lines.append(username)
                    continue

                # convert start date string into
                start_date = parse(row['Start Date'])
                year_of_course = int(row['Year of Course'])

                # attempt to deduce whether a foundation year or repeated years have been involved
                cohort = None
                foundation_year = False
                repeated_years = None

                if isinstance(start_date, datetime):
                    cohort = start_date.year
                    estimated_year_of_course = current_year - start_date.year + 1

                    difference = estimated_year_of_course - year_of_course
                    if difference > 0:
                        if difference == 1:
                            foundation_year = True
                            repeated_years = 0

                        else:
                            foundation_year = True
                            repeated_years = difference - 1

                dont_convert = False

                # test whether we can find an existing student record with this email address.
                # if we can, check whether it is a student account.
                # If not, there's not much we can do
                existing_record = db.session.query(User) \
                    .join(StudentData, StudentData.id == User.id) \
                    .filter(or_(func.lower(User.email) == func.lower(email),
                                func.lower(User.username) == func.lower(username),
                                StudentData.exam_number == registration_number)).first()
                if existing_record is not None:
                    if not existing_record.has_role('student'):
                        print('## skipping row "{user}" because existing user is not a student'.format(user=username))
                        ignored_lines.append(username)
                        continue

                    if existing_record.email.lower() != email.lower():
                        dont_convert = True

                item = StudentBatchItem(parent_id=record.id,
                                        existing_id=existing_record.id if existing_record is not None else None,
                                        user_id=username,
                                        first_name=first_name,
                                        last_name=last_name,
                                        email=email,
                                        exam_number=registration_number,
                                        cohort=cohort,
                                        programme_id=programme.id if programme is not None else None,
                                        foundation_year=foundation_year,
                                        repeated_years=repeated_years,
                                        intermitting=intermitting,
                                        dont_convert=dont_convert)

                interpreted_lines += 1
                db.session.add(item)

        progress_update(record.celery_id, TaskRecord.RUNNING, 90, "Finalizing import...", autocommit=False)

        if lines == interpreted_lines:
            user.post_message('Successfully imported batch list "{name}"'.format(name=record.name), 'success',
                              autocommit=False)

        elif interpreted_lines < lines:
            user.post_message('Imported batch list "{name}", but some records could not be read successfully '
                              'or were inconsistent with existing entries: '
                              '{ignored}'.format(name=record.name, ignored=', '.join(ignored_lines)),
                              'success', autocommit=False)

        else:
            user.post_message('Batch list "{name}" was not correctly imported due to errors'.format(name=record.name),
                              'error', autocommit=False)

        record.total_lines = lines
        record.interpreted_lines = interpreted_lines
        record.celery_finished = True
        record.success = (interpreted_lines <= lines)
        db.session.commit()
