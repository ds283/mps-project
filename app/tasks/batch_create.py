#
# Created by David Seery on 2019-03-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import csv
from datetime import datetime

from celery import group
from celery.exceptions import Ignore
from dateutil.parser import parse
from flask import current_app
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.sql.functions import func

from app.manage_users.actions import register_user
from ..database import db
from ..models import TemporaryAsset, TaskRecord, User, StudentBatch, StudentBatchItem, DegreeProgramme, StudentData
from ..shared.asset_tools import canonical_temporary_asset_filename
from ..task_queue import progress_update

OUTCOME_CREATED = 0
OUTCOME_MERGED = 1
OUTCOME_FAILED = 3
OUTCOME_IGNORED = 4
OUTCOME_ERROR = 5

BATCH_IMPORT_LIFETIME_SECONDS = 24*60*60


class SkipRow(Exception):
    """Report an exception associated with processing a single row"""


def _overwrite_record(item: StudentBatchItem) -> int:
    student_record: StudentData = item.existing_record
    user_record: User = student_record.user

    # disable validation so that the order in which we set fields does not matter
    student_record.disable_validate = True

    if item.first_name is not None and user_record.first_name != item.first_name:
        user_record.first_name = item.first_name

    if item.last_name is not None and user_record.last_name != item.last_name:
        user_record.last_name = item.last_name

    if item.user_id is not None and user_record.username != item.user_id:
        user_record.username = item.user_id

    if item.email is not None and user_record.email != item.email:
        user_record.email = item.email

    if item.exam_number is not None and student_record.exam_number != item.exam_number:
        student_record.exam_number = item.exam_number

    if item.registration_number is not None and student_record.registration_number != item.registration_number:
        student_record.registration_number = item.registration_number

    if item.cohort is not None and student_record.cohort != item.cohort:
        student_record.cohort = item.cohort

    if item.foundation_year is not None and student_record.foundation_year != item.foundation_year:
        student_record.foundation_year = item.foundation_year

    if item.repeated_years is not None and student_record.repeated_years != item.repeated_years:
        student_record.repeated_years = item.repeated_years

    if item.programme_id is not None and student_record.programme_id != item.programme_id:
        student_record.programme_id = item.programme_id

    if item.intermitting is not None and student_record.intermitting != item.intermitting:
        student_record.intermitting = item.intermitting

    student_record.workflow_state = StudentData.WORKFLOW_APPROVAL_VALIDATED

    # delete validation sentinel
    del student_record.disable_validate

    return OUTCOME_MERGED


def _create_record(item, user_id) -> int:
    user: User = register_user(first_name=item.first_name,
                               last_name=item.last_name,
                               username=item.user_id,
                               email=item.email,
                               roles=['student'],
                               random_password=True,
                               ask_confirm=False)

    # create new student record and mark it as automatically validated
    data = StudentData(id=user.id,
                       exam_number=item.exam_number,
                       registration_number=item.registration_number,
                       intermitting=item.intermitting,
                       cohort=item.cohort,
                       programme_id=item.programme_id,
                       foundation_year=item.foundation_year,
                       repeated_years=item.repeated_years,
                       creator_id=user_id,
                       creation_timestamp=datetime.now())

    # exceptions will be caught in parent
    db.session.add(data)
    db.session.flush()

    data.workflow_state = StudentData.WORKFLOW_APPROVAL_VALIDATED

    return OUTCOME_CREATED


def _get_name(row, current_line) -> str:
    if 'name' not in row:
        print('## skipping row {row} because could not determine student name'.format(row=current_line))
        raise SkipRow

    name = row['name']
    name_parts = [x.strip() for x in name.split(',') if len(x) > 0]

    if len(name_parts) == 0:
        print('## skipping row {row} because name first contained no parts'.format(row=current_line))
        raise SkipRow

    if len(name_parts) >= 2:
        last_name_parts = [x.strip() for x in name_parts[0].split(' ') if len(x) > 0]
        first_name_parts = [x.strip() for x in name_parts[1].split(' ') if len(x) > 0]

        # remove any bracketed nicknames
        last_name_parts = [x for x in last_name_parts if len(x) > 0 and x[0] != '(' and x[-1] != ')']
        first_name_parts = [x for x in first_name_parts if len(x) > 0 and x[0] != '(' and x[-1] != ')']

        if len(last_name_parts) == 0 or len(first_name_parts) == 0:
            print('## skipping row {row} because cannot identify one or both of first and last name'.format(row=current_line))
            raise SkipRow

        last_name = ' '.join(last_name_parts)
        first_name = first_name_parts[0]

        return first_name, last_name

    last_name_parts = [x.strip() for x in name_parts[0].split(' ') if len(x) > 0]

    if len(last_name_parts) == 0:
        print('## skipping row {row} because cannot identify last name'.format(row=current_line))
        raise SkipRow

    last_name = ' '.join(last_name_parts)
    first_name = '<Unknown>'

    return first_name, last_name


def _get_username(row, current_line) -> str:
    if 'username' in row:
        return row['username']

    if 'email' in row:
        email = row['email']
        userid, _, _ = email.partition('@')
        return userid

    if 'email address' in row:
        email = row['email']
        userid, _, _ = email.partition('@')
        return userid

    print('## skipping row {row} because could not extract userid'.format(row=current_line))
    raise SkipRow


def _get_intermitting(row, current_line) -> bool:
    if 'student status' in row:
        return (row['student status'].lower() == 'intermitting')

    if 'status' in row:
        return (row['status'].lower() == 'intermitting')

    return None


def _get_registration_number(row, current_line) -> int:
    if 'registration number' in row:
        return int(row['registration number'])

    if 'registration no.' in row:
        return int(row['registration no.'])

    return None


def _get_exam_number(row, current_line) -> int:
    if 'exam number' in row:
        return int(row['exam number'])

    return None


def _get_email(row, current_line) -> str:
    if 'email address' in row:
        return row['email address']

    if 'email' in row:
        return row['email']

    print('## skipping row {row} because could not extract email address'.format(row=current_line))
    raise SkipRow


def _get_course_year(row, current_line) -> int:
    if 'year of course' in row:
        return int(row['year of course'])

    if 'year' in row:
        return int(row['year'])

    print('## skipping row {row} because could not extract course year'.format(row=current_line))
    raise SkipRow


def _get_cohort(row, current_line) -> int:
    # convert start date string into a Python date object
    if 'start date' in row:
        return parse(row['start date']).year

    if 'cohort' in row:
        return parse(row['cohort']).year

    print('## skipping row {row} because could not extract start date/cohort'.format(row=current_line))
    raise SkipRow


def _get_course_code(row, current_line) -> DegreeProgramme:
    course_map = {'bsc physics': 'F3003U',
                  'bsc physics (with an industrial placement year)': 'M3045U',
                  'bsc physics (ip)': 'M3045U',
                  'bsc physics with astrophysics': 'F3055U',
                  'bsc physics (with a study abroad year)': 'F3067U',
                  'bsc theoretical physics': 'F3016U',
                  'bsc phys and astro (fdn)': 'F3002U',
                  'bsc physics and astronomy (with a foundation year)': 'F3002U',
                  'mphys astrophysics': 'F3029U',
                  'mphys physics': 'F3028U',
                  'mphys physics (rp)': 'F3011U',
                  'mphys physics (research placement)': 'F3011U',
                  'mphys physics (with an industrial placement year)': 'M3044U',
                  'mphys physics with astrophysics': 'F3056U',
                  'mphys theoretical physics': 'F3044U',
                  'mphys astrophysics (research placement)': 'F3010U',
                  'mphys physics with astrophysics (research placement)': 'F3046U',
                  'mphys theoretical physics (research placement)': 'F3062U',
                  'mphys physics (with a study abroad year)': 'F3027U',
                  'mphys physics with astrophysics (with a study abroad year)': 'F3069U',
                  'mphys theoretical physics (with a study abroad year)': 'F3050U'}

    programme = None

    if 'course code' in row:
        course_code = row['course code']
        programme = db.session.query(DegreeProgramme).filter_by(course_code=course_code).first()

    elif 'course' in row:
        course_name = row['course'].lower()

        if course_name in course_map:
            course_code = course_map[course_name]
            programme = db.session.query(DegreeProgramme).filter_by(course_code=course_code).first()
        else:
            print('## course name "{name}" not found in look-up table at row {row}'.format(name=course_name,
                                                                                           row=current_line))

    # ignore lines where we cannot determine the programme -- they're probably V&E students
    if programme is not None:
        return programme

    print('## skipping row {row} because cannot identify degree programme'.format(row=current_line))
    raise SkipRow


def _guess_year_data(cohort: int, year_of_course: int, current_year: int, programme: DegreeProgramme,
                     fyear_hint: bool = None) -> (bool, int):
    """
    :param programme:
    :param cohort: read (or previously stored) cohort for this student
    :param year_of_course: read (or previously stored) year of course for this student
    :param current_year: current academic year
    :param fyear_hint: hint whether foundation year was taken, or not
    :return:
    """
    # try to guess whether a given student has done foundation year or some number of
    # repeat years
    # of course, we don't really have enough information to work this out; what's here
    # is a simple minded guess
    #
    # return value: foundation_year(bool), repeat_years(int)

    # validate input types
    if not isinstance(cohort, int):
        print('!! ERROR: expected cohort to be an integer, but received {type}'.format(type=type(cohort)))
        raise SkipRow

    if not isinstance(year_of_course, int):
        print('!! ERROR: expected year_of_course to be an integer, but received '
              '{type}'.format(type=type(year_of_course)))
        raise SkipRow

    if not isinstance(current_year, int):
        print('!! ERROR: expected current_year to be an integer, but received {type}'.format(type=type(current_year)))
        raise SkipRow

    if fyear_hint is not None and not isinstance(fyear_hint, bool):
        print('!! ERROR: expected fyear to be a bool, but received {type}'.format(type=type(fyear_hint)))
        raise SkipRow

    fyear_shift = 1 if programme.foundation_year else 0
    estimated_year_of_course = current_year - cohort + 1 - fyear_shift

    if programme.year_out:
        if estimated_year_of_course > programme.year_out_value:
            estimated_year_of_course = estimated_year_of_course - 1

    if estimated_year_of_course < 0:
        print('!! ERROR: estimated year of course is negative: current_year={cy}, cohort={ch}, '
              'FY={fy}'.format(cy=current_year, ch=cohort, fy=fyear_shift))
        raise SkipRow

    difference = estimated_year_of_course - year_of_course

    if difference < 0:
        print('## estimated course year was earlier than imported value '
              '(current_year={cy}, cohort={ch}, FY={fs}, '
              'estimated={es}, imported={im}, diff={df}'.format(cy=current_year, ch=cohort, fs=fyear_shift,
                                                                es=estimated_year_of_course, im=year_of_course,
                                                                df=difference))
        raise SkipRow

    if difference >= 1 and fyear_shift == 0 and fyear_hint:
        difference = difference - 1
    else:
        fyear_hint = False

    return fyear_hint, difference


def _match_existing_student(username, email, current_line) -> (bool, StudentData):
    # test whether we can find an existing student record with this email address.
    # if we can, check whether it is a student account.
    # If not, there's not much we can do
    dont_convert = False

    existing_record = db.session.query(User) \
        .filter(or_(func.lower(User.email) == func.lower(email),
                    func.lower(User.username) == func.lower(username))).first()

    if existing_record is not None:
        if not existing_record.has_role('student'):
            print('## skipping row {row} because matched to existing user that is '
                  'not a student'.format(row=current_line))
            raise SkipRow

        if existing_record.email.lower() != email.lower():
            dont_convert = True

    return dont_convert, existing_record.student_data if existing_record is not None else None


def register_batch_create_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def students(self, record_id, asset_id, current_user_id, current_year):
        try:
            record: StudentBatch = db.session.query(StudentBatch).filter_by(id=record_id).first()
            asset: TemporaryAsset = db.session.query(TemporaryAsset).filter_by(id=asset_id).first()
            user: User = db.session.query(User).filter_by(id=current_user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None or asset is None or user is None:
            self.update_state(state='FAILURE', meta='Could not load database records')

            record.celery_finished = True
            record.success = False

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

            raise RuntimeError('Could not load database records')

        progress_update(record.celery_id, TaskRecord.RUNNING, 10, "Inspecting uploaded user list...", autocommit=True)

        with open(canonical_temporary_asset_filename(asset.filename), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            # force column headers to lower case
            reader.fieldnames = [name.lower() for name in reader.fieldnames]

            progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Reading uploaded user list...", autocommit=True)

            current_line = 1
            interpreted_lines = 0

            ignored_lines = []

            for row in reader:
                current_line += 1

                # in Python 3.6, row is an OrderedDict
                first_name = None
                last_name = None
                username = None
                year_of_course = None

                try:
                    # username and email are first things to extract
                    username = _get_username(row, current_line)

                    email = _get_email(row, current_line)
                    # ignore cases where the email address is 'INTERMITTING' or 'RESITTING'
                    if email.lower() == 'intermitting' or email.lower() == 'resitting':
                        print('## skipping row "{user}" because email is "{email}"'.format(user=username, email=email))
                        raise SkipRow

                    # try to match this data to an existing record
                    dont_convert, existing_record = _match_existing_student(username, email, current_line)

                    # get name and break into comma-separated parts
                    first_name, last_name = _get_name(row, current_line)
                    intermitting = _get_intermitting(row, current_line)
                    registration_number = _get_registration_number(row, current_line)
                    exam_number = _get_exam_number(row, current_line)
                    year_of_course = _get_course_year(row, current_line)
                    programme = _get_course_code(row, current_line)

                    if year_of_course == 0 and record.ignore_Y0:
                        print('## skipping row "{user}" because Y0 students are being ignored'.format(user=username))
                        raise SkipRow

                    # attempt to deduce whether a foundation year or repeated years have been involved
                    if existing_record is None:
                        cohort = _get_cohort(row, current_line)
                        fyear_hint = None
                    else:
                        if not record.trust_cohort and existing_record.cohort is not None:
                            cohort = existing_record.cohort
                        else:
                            cohort = _get_cohort(row, current_line)

                        fyear_hint = existing_record.foundation_year

                    foundation_year, repeated_years = \
                        _guess_year_data(cohort, year_of_course, current_year, programme, fyear_hint=fyear_hint)

                    if existing_record is not None:
                        if not record.trust_exams and existing_record.exam_number is not None:
                            exam_number = existing_record.exam_number

                        if not record.trust_registration and existing_record.registration_number is not None:
                            registration_number = existing_record.registration_number

                    item = StudentBatchItem(parent_id=record.id,
                                            existing_id=existing_record.id if existing_record is not None else None,
                                            user_id=username,
                                            first_name=first_name,
                                            last_name=last_name,
                                            email=email,
                                            exam_number=exam_number,
                                            registration_number=registration_number,
                                            cohort=cohort,
                                            programme_id=programme.id if programme is not None else None,
                                            foundation_year=foundation_year,
                                            repeated_years=repeated_years,
                                            intermitting=intermitting,
                                            dont_convert=dont_convert)

                    interpreted_lines += 1

                    try:
                        db.session.add(item)
                    except SQLAlchemyError as e:
                        raise SkipRow

                    if item.academic_year is None:
                        if not item.programme.year_out or year_of_course != item.programme.year_out_value:
                            print('!! ERROR: computed academic year is None, but imported year of course '
                                  'does not match year out value for this programme')
                            raise SkipRow
                    else:
                        if item.academic_year != year_of_course:
                            print('!! ERROR: computed academic year {yr} for {first} {last} does not match imported '
                                  'value {imp} (current_year={cy}, cohort={ch}, FY={fy}, '
                                  'repeated_years={ry})'.format(yr=item.academic_year, first=first_name, last=last_name,
                                                                imp=year_of_course, cy=current_year, ch=cohort,
                                                                fy=1 if item.has_foundation_year else 0,
                                                                ry=repeated_years))
                            raise SkipRow

                except SkipRow:
                    if username is None:
                        skip_info = '<line #{no}>'.format(no=current_line)

                    else:
                        if first_name is not None and last_name is not None:
                            skip_info = '{user} ({first} {last} Y{yr})'.format(user=username, first=first_name,
                                                                               last=last_name, yr=year_of_course)
                        else:
                            skip_info = '{user} Y{yr}'.format(user=username, yr=year_of_course)

                    ignored_lines.append(skip_info)
                    print('>> SUMMARY: skipped line {info}'.format(info=skip_info))

        progress_update(record.celery_id, TaskRecord.RUNNING, 90, "Finalizing import...", autocommit=False)

        if current_line == interpreted_lines:
            user.post_message('Successfully imported batch list "{name}"'.format(name=record.name), 'success',
                              autocommit=False)

        elif interpreted_lines < current_line:
            user.post_message('Imported batch list "{name}", but some records could not be read successfully '
                              'or were inconsistent with existing entries: '
                              '{ignored}'.format(name=record.name, ignored=', '.join(ignored_lines)),
                              'success', autocommit=False)

        else:
            user.post_message('Batch list "{name}" was not correctly imported due to errors'.format(name=record.name),
                              'error', autocommit=False)

        record.total_lines = current_line
        record.interpreted_lines = interpreted_lines
        record.celery_finished = True
        record.success = (interpreted_lines <= current_line)
        db.session.commit()


    @celery.task(bind=True, default_retry_delay=30)
    def import_batch_item(self, item_id, user_id):
        try:
            item: StudentBatchItem = db.session.query(StudentBatchItem).filter_by(id=item_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if item is None:
            self.update_state(state='FAILURE', meta='Could not load database records')
            return OUTCOME_FAILED

        if item.dont_convert:
            return OUTCOME_IGNORED

        try:
            if item.existing_record is not None:
                result = _overwrite_record(item)
            else:
                result = _create_record(item, user_id)

            # delete this item
            item.parent.items.remove(item)
            db.session.delete(item)

            db.session.commit()

        except (SQLAlchemyError, IntegrityError) as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        except ValueError as e:
            # encountered a validation error while merging or creating a record
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return OUTCOME_ERROR

        return result


    @celery.task(bind=True, default_retry_delay=30)
    def import_finalize(self, result_data, record_id, user_id):
        try:
            record: StudentBatch = db.session.query(StudentBatch).filter_by(id=record_id).first()
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None or user is None:
            self.update_state(state='FAILURE', meta='Could not load database records')
            raise Ignore()

        num_created = sum([1 for x in result_data if x == OUTCOME_CREATED])
        num_merged = sum([1 for x in result_data if x == OUTCOME_MERGED])
        num_failed = sum([1 for x in result_data if x == OUTCOME_FAILED])
        num_ignored = sum([1 for x in result_data if x == OUTCOME_IGNORED])
        num_errors = sum([1 for x in result_data if x == OUTCOME_ERROR])

        user.post_message('Batch import is complete: {created} created, {merged} merged, '
                          '{errors} errors, {failed} failed, '
                          '{ignored} ignored'.format(created=num_created, merged=num_merged, failed=num_failed,
                                                     ignored=num_ignored, errors=num_errors),
                          'info' if num_failed == 0 and num_errors == 0 else 'error', autocommit=False)

        if num_errors == 0 and num_failed == 0:
            record.converted = True

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def import_error(self, user_id):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta='Could not load database records')
            raise Ignore()

        user.post_message('Errors occurred during batch import', 'error', autocommit=True)

        # raise new exception; will be caught by error handler on mark_user_task_failed()
        raise RuntimeError('Import process failed with an error')


    @celery.task(bind=True, default_retry_delay=30)
    def garbage_collection(self):
        try:
            records = db.session.query(StudentBatch).filter_by(celery_finished=True).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        expiry = group(check_expiry.si(r.id) for r in records)
        expiry.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def check_expiry(self, record_id):
        try:
            record = db.session.query(StudentBatch).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta='Could not load database records')
            raise Ignore()

        # if imported successfully and not yet converted, don't expire
        if record.success and not record.converted:
            return

        now = datetime.now()
        age = now - record.timestamp

        if age.total_seconds() > BATCH_IMPORT_LIFETIME_SECONDS:
            try:
                # cascade is set to delete all items, but do it by hand anwyay
                db.session.query(StudentBatchItem).filter_by(parent_id=record.id).delete()
                db.session.delete(record)
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()
