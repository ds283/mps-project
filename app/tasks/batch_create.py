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
from typing import Optional, Tuple
from functools import total_ordering

from celery import group
from celery.exceptions import Ignore
from dateutil.parser import parse
from flask import current_app, render_template_string
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.sql.functions import func

from app.manage_users.actions import register_user
from ..database import db
from ..models import TemporaryAsset, TaskRecord, User, StudentBatch, StudentBatchItem, DegreeProgramme, StudentData, \
    AssetLicense
from ..shared.asset_tools import AssetCloudAdapter
from ..task_queue import progress_update

OUTCOME_CREATED = 0
OUTCOME_MERGED = 1
OUTCOME_FAILED = 3
OUTCOME_IGNORED = 4
OUTCOME_ERROR = 5

BATCH_IMPORT_LIFETIME_SECONDS = 24*60*60

# language=jinja2
template = \
"""
<div class="mb-1"><strong>Some student entries did not import correctly.</strong></div>
<div class="mb-2">Please review these entries and re-import the batch list if needed, after making any necessary changes.</div>
<div class="small">
    <ul>
        {% if yearNone|length > 0 %}
            <li>
                <strong>Unknown year of course (could not be read from the uploaded list)</strong>
                <ul>
                    {% for item in yearNone %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
        {% if year0|length > 0 %}
            <li>
                <strong>Year 0</strong>
                <ul>
                    {% for item in year0 %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
        {% if year1|length > 0 %}
            <li>
                <strong>Year 1</strong>
                <ul>
                    {% for item in year1 %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
        {% if year2|length > 0 %}
            <li>
                <strong>Year 2</strong>
                <ul>
                    {% for item in year2 %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
        {% if year3|length > 0 %}
            <li>
                <strong>Year 3</strong>
                <ul>
                    {% for item in year3 %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
        {% if year4|length > 0 %}
            <li>
                <strong>Year 4</strong>
                <ul>
                    {% for item in year4 %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
        {% if yearN|length > 0 %}
            <li>
                <strong>Years 5 and above</strong>
                <ul>
                    {% for item in yearN %}
                        <li>{{ item|string }}</li>
                    {% endfor %}
                </ul>
            </li>        
        {% endif %}
    </ul>
</div>
"""

@total_ordering
class SkipRow(Exception):
    """Report an exception associated with processing a single row"""

    def __init__(self, line_number: int, user: str=None, first_name: str=None, last_name: str=None, email: str=None,
                 year: int=None, reason: str=None):
        self.line_number = line_number
        self.user = user
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.year = year
        self.reason = reason

    def __str__(self):
        value = ''

        if self.last_name is not None:
            if self.first_name is not None:
                value += f'{self.first_name} {self.last_name}'
            else:
                value += f'{self.last_name}'

        if self.email is not None:
            if len(value) == 0:
                value = f'<{self.email}>'
            else:
                value += f' <{self.email}>'
        elif self.user is not None:
            if len(value) == 0:
                value = f'<{self.user}>'
            else:
                value += f' <{self.user}>'

        if self.reason is not None:
            if len(value) == 0:
                value = f'<line #{self.line_number}>: {self.reason}'
            else:
                value += f': {self.reason}'

        if len(value) == 0:
            value = f'<line #{self.line_number}>: no further details'

        return value


    def __eq__(self, other):
        return self.line_number == other.line_number

    def __lt__(self, other):
        if self.year is None:
            return True

        if other.year is None:
            return False

        if self.year < other.year:
            return True

        if self.last_name is None:
            return True

        if other.last_name is None:
            return False

        if self.last_name < other.last_name:
            return True

        if self.first_name is None:
            return True

        if other.first_name is None:
            return False

        if self.first_name < other.first_name:
            return True

        if self.user is None:
            return True

        if other.user is None:
            return False

        if self.user < other.user:
            return True



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
    student_lic = current_app.config['STUDENT_DEFAULT_LICENSE']
    student_default = db.session.query(AssetLicense) \
        .filter_by(abbreviation=student_lic).first()

    user: User = register_user(first_name=item.first_name,
                               last_name=item.last_name,
                               username=item.user_id,
                               email=item.email,
                               roles=['student'],
                               random_password=True,
                               ask_confirm=False,
                               default_license=student_default)

    # create new student record and mark it as automatically validated
    data = StudentData(id=user.id,
                       exam_number=None,
                       registration_number=item.registration_number,
                       intermitting=item.intermitting,
                       cohort=item.cohort,
                       programme_id=item.programme_id,
                       foundation_year=item.foundation_year,
                       repeated_years=item.repeated_years,
                       creator_id=user_id,
                       creation_timestamp=datetime.now(),
                       dyspraxia_sticker=False,
                       dyslexia_sticker=False)

    # exceptions will be caught in parent
    db.session.add(data)
    db.session.flush()

    data.workflow_state = StudentData.WORKFLOW_APPROVAL_VALIDATED

    return OUTCOME_CREATED


def _get_name(row, current_line) -> Tuple[str, str]:
    if 'name' not in row:
        print('## skipping row {row} because could not determine student name'.format(row=current_line))
        raise SkipRow(current_line, reason="could not determine student's name")

    name = row['name']
    name_parts = [x.strip() for x in name.split(',') if len(x) > 0]

    if len(name_parts) == 0:
        print('## skipping row {row} because name contained no parts'.format(row=current_line))
        raise SkipRow(current_line, reason="could not process parts of student's name")

    if len(name_parts) >= 2:
        last_name_parts = [x.strip() for x in name_parts[0].split(' ') if len(x) > 0]
        first_name_parts = [x.strip() for x in name_parts[1].split(' ') if len(x) > 0]

        # remove any bracketed nicknames
        last_name_parts = [x for x in last_name_parts if len(x) > 0 and x[0] != '(' and x[-1] != ')']
        first_name_parts = [x for x in first_name_parts if len(x) > 0 and x[0] != '(' and x[-1] != ')']

        if len(last_name_parts) == 0 or len(first_name_parts) == 0:
            print('## skipping row {row} because cannot identify one or both of first and last name'.format(row=current_line))
            raise SkipRow(current_line, reason="could not identify one or both of student's first and last name")

        last_name = ' '.join(last_name_parts)
        first_name = first_name_parts[0]

        return first_name, last_name

    last_name_parts = [x.strip() for x in name_parts[0].split(' ') if len(x) > 0]

    if len(last_name_parts) == 0:
        print('## skipping row {row} because cannot identify last name'.format(row=current_line))
        raise SkipRow(current_line, reason=f"could not identify student's last name (imported name='{name}')")

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
    raise SkipRow(current_line, reason="could not extract student's userid")


def _get_intermitting(row, current_line) -> Optional[bool]:
    if 'student status' in row:
        return row['student status'].lower() == 'intermitting'

    if 'status' in row:
        return row['status'].lower() == 'intermitting'

    return None


def _get_registration_number(row, current_line) -> Optional[int]:
    if 'registration number' in row:
        return int(row['registration number'])

    if 'registration no.' in row:
        return int(row['registration no.'])

    return None


def _get_email(row, current_line) -> str:
    if 'email address' in row:
        return row['email address']

    if 'email' in row:
        return row['email']

    print('## skipping row {row} because could not extract email address'.format(row=current_line))
    raise SkipRow(current_line, reason="could not extract student's email address")


def _get_course_year(row, current_line) -> int:
    if 'year of course' in row:
        return int(row['year of course'])

    if 'year' in row:
        return int(row['year'])

    print('## skipping row {row} because could not extract course year'.format(row=current_line))
    raise SkipRow(current_line, reason="could not extract student's year-of-course")


def _get_cohort(row, current_line) -> int:
    # convert start date string into a Python date object
    if 'start date' in row:
        return parse(row['start date']).year

    if 'cohort' in row:
        return parse(row['cohort']).year

    print('## skipping row {row} because could not extract start date/cohort'.format(row=current_line))
    raise SkipRow(current_line, reason="could not extract student's start date or cohort")


def _get_course_code(row, current_line) -> DegreeProgramme:
    course_map = {
        'bsc physics': 'F3003U',
        'bsc physics (with an industrial placement year)': 'M3045U',
        'bsc physics (ip)': 'M3045U',
        'bsc physics with astrophysics': 'F3055U',
        'bsc physics with astrophysics (with a study abroad year)': 'F3068U',
        'bsc physics (with a study abroad year)': 'F3067U',
        'bsc theoretical physics': 'F3016U',
        'bsc phys and astro (fdn)': 'F3002U',
        'bsc physics and astronomy (with a foundation year)': 'F3002U',
        'mphys astrophysics': 'F3029U',
        'mphys astrophysics (with an industrial placement year)': 'F3030U',
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
        'mphys theoretical physics (with a study abroad year)': 'F3050U',
        'mphys theoretical physics (yab)': 'F3050U',
        'msc data science': 'F5063T',
        'msc data science (with an industrial placement year)': 'F5065T',
        'msc human and social data science': 'F5064T',
        'msc data science (p/t)': 'F5063T p/t',
        'msc data science (with an industrial placement year) (p/t)': 'F5065T p/t',
        'msc human and social data science (p/t)': 'F5064T p/t'
    }

    programme = None

    if 'course code' in row:
        course_code = row['course code']
        programme = db.session.query(DegreeProgramme).filter_by(course_code=course_code).first()

    elif 'course' in row:
        course_name: str = row['course'].lower()

        if course_name.endswith(' (direct entry)'):
            course_name = course_name.removesuffix(' (direct entry)')

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
    reason = "could not identify student's degree programme"
    if 'course' in row:
        reason += f" (imported course label = '{row['course']}'"
        if 'course code' in row:
            reason += f", course code = '{row['course code']}'"
        reason += ")"
    elif 'course code' in row:
        reason += f" (imported course code = '{row['course code']})"

    raise SkipRow(current_line, reason=reason)


def _guess_year_data(current_line, cohort: int, year_of_course: int, current_year: int, programme: DegreeProgramme,
                     fyear_hint: bool = None) -> (bool, int):
    """
    :param current_line:
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
    # is a relatively simple-minded guess based on some heuristics
    #
    # return value: foundation_year(bool), repeat_years(int)

    # validate input types
    if not isinstance(cohort, int):
        print('!! ERROR: expected cohort to be an integer, but received {type}'.format(type=type(cohort)))
        raise SkipRow(current_line, reason="student's cohort value did not decode to an integer")

    if not isinstance(year_of_course, int):
        print('!! ERROR: expected year_of_course to be an integer, but received '
              '{type}'.format(type=type(year_of_course)))
        raise SkipRow(current_line, reason="student's year-of-course value did not decode to an integer")

    if not isinstance(current_year, int):
        print('!! ERROR: expected current_year to be an integer, but received {type}'.format(type=type(current_year)))
        raise SkipRow(current_line, reason="student's computed current year did not decode to an integer")

    if fyear_hint is not None and not isinstance(fyear_hint, bool):
        print('!! ERROR: expected fyear to be a bool, but received {type}'.format(type=type(fyear_hint)))
        raise SkipRow(current_line, reason="student's foundation year flag had a value that could not be interpreted")

    fyear_shift = 1 if programme.foundation_year else 0
    estimated_year_of_course = current_year - cohort + 1 - fyear_shift

    # if the programme has a year out, and our estimated year is greater than the year-out year,
    # then we should subtract one to account for it
    if programme.year_out:
        if estimated_year_of_course > programme.year_out_value:
            estimated_year_of_course = estimated_year_of_course - 1

    if estimated_year_of_course < 0:
        print('!! ERROR: estimated year of course is negative: current_year={cy}, cohort={ch}, '
              'FY={fy}'.format(cy=current_year, ch=cohort, fy=fyear_shift))
        raise SkipRow(current_line, reason="student's estimated year of course was negative")

    # set up empty dictionary return object
    rval = {}

    difference = estimated_year_of_course - year_of_course

    if difference < 0:
        # We guessed the student to be in an earlier year than the one actually supplied to us
        # as year_of_course (whatever its provenance may be).
        # In theory this shouldn't happen, but in reality Sussex Direct seems to muck around with
        # a student's cohort: in particular, a student who arrived in year N for a foundation year
        # (and whose cohort should therefore be N) will often have their cohort reassigned
        # to N+1 when they progress to Y1, *even though* their degree programme is not changed
        # from "with foundation year".

        # if this seems to be what has happened, adjust the cohort
        if programme.foundation_year and difference == -1:
            cohort -= 1
            estimated_year_of_course += 1
            difference = 0

            rval |= {'new_cohort': cohort}

        else:
            print('## estimated course year was earlier than imported value '
                  '(current_year={cy}, cohort={ch}, FY={fs}, '
                  'estimated={es}, imported={im}, diff={df}'.format(cy=current_year, ch=cohort, fs=fyear_shift,
                                                                    es=estimated_year_of_course, im=year_of_course,
                                                                    df=difference))
            reason = f"student's estimated year of course Y{estimated_year_of_course} was earlier than the " \
                     f"imported value = Y{year_of_course}"
            if programme.year_out:
                reason += f" (note: this student belongs to programme '{programme.full_name}' which has a year out " \
                          f"in Y{programme.year_out_value})"
            raise SkipRow(current_line, reason=reason)

    if difference >= 1 and fyear_shift == 0 and fyear_hint:
        difference = difference - 1
    else:
        fyear_hint = False

    rval |= {'fdn_year': fyear_hint,
             'repeated': difference}
    return rval


def _match_existing_student(current_line, username, email) -> (bool, StudentData):
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
            raise SkipRow(current_line, reason=f"imported values matched to an existing user "
                                               f"'{existing_record.name}' that is not a student")

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
            self.update_state(state='FAILURE', meta={'msg': 'Could not load database records'})

            record.celery_finished = True
            record.success = False

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

            raise RuntimeError('Could not load database records')

        progress_update(record.celery_id, TaskRecord.RUNNING, 10, "Inspecting uploaded user list...", autocommit=True)

        object_store = current_app.config.get('OBJECT_STORAGE_ASSETS')
        storage = AssetCloudAdapter(asset, object_store)
        with storage.download_to_scratch() as scratch_path:
            with open(scratch_path.path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                # force column headers to lower case
                reader.fieldnames = [name.lower() for name in reader.fieldnames]

                progress_update(record.celery_id, TaskRecord.RUNNING, 50, "Reading uploaded user list...", autocommit=True)

                current_line = 1
                interpreted_lines = 0

                ignored_lines = []

                # in Python >= 3.6, row is an OrderedDict
                for row in reader:
                    current_line += 1

                    try:
                        # username and email are first things to extract
                        username = _get_username(row, current_line)

                        email = _get_email(row, current_line)
                        # ignore cases where the email address is 'INTERMITTING' or 'RESITTING'
                        if email.lower() == 'intermitting' or email.lower() == 'resitting':
                            print('## skipping row "{user}" because email is "{email}"'.format(user=username, email=email))
                            raise SkipRow(current_line, user=username, reason=f'email labelled as "{email}"')

                        # try to match this data to an existing record
                        dont_convert, existing_record = _match_existing_student(current_line, username, email)

                        # get name and break into comma-separated parts
                        first_name, last_name = _get_name(row, current_line)
                        intermitting = _get_intermitting(row, current_line)
                        registration_number = _get_registration_number(row, current_line)
                        year_of_course = _get_course_year(row, current_line)

                        try:
                            programme = _get_course_code(row, current_line)

                            if year_of_course == 0 and record.ignore_Y0:
                                print('## skipping row "{user}" because Y0 students are being ignored'.format(user=username))
                                raise SkipRow(current_line, reason='Ignoring Y0 students in this batch')

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

                            year_data = _guess_year_data(current_line, cohort, year_of_course, current_year, programme,
                                                         fyear_hint=fyear_hint)
                            foundation_year = year_data['fdn_year']
                            repeated_years = year_data['repeated']

                            # sometimes the cohort will need adjustment based on what we could guess about the
                            # students current academic year; see discussion in _guess_year_data()
                            if 'new_cohort' in year_data:
                                cohort = year_data['new_cohort']

                            if existing_record is not None:
                                if not record.trust_registration and existing_record.registration_number is not None:
                                    registration_number = existing_record.registration_number

                            item = StudentBatchItem(parent_id=record.id,
                                                    existing_id=existing_record.id if existing_record is not None else None,
                                                    user_id=username,
                                                    first_name=first_name,
                                                    last_name=last_name,
                                                    email=email,
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
                                raise SkipRow(current_line, reason='Internal database error')

                            if item.academic_year is None:
                                if not item.programme.year_out or year_of_course != item.programme.year_out_value:
                                    print('!! ERROR: computed academic year is None, but imported year of course '
                                          'does not match the specified year-out value for this programme')
                                    raise SkipRow(current_line,
                                                  reason='This student is expected to be on a year out, but the imported'
                                                         'year-of-course data does not match the specified year-out'
                                                         'value for their programme')
                            else:
                                if item.academic_year != year_of_course:
                                    print('!! ERROR: computed academic year {yr} for {first} {last} does not match imported '
                                          'value {imp} (current_year={cy}, cohort={ch}, FY={fy}, '
                                          'repeated_years={ry})'.format(yr=item.academic_year, first=first_name, last=last_name,
                                                                        imp=year_of_course, cy=current_year, ch=cohort,
                                                                        fy=1 if item.has_foundation_year else 0,
                                                                        ry=repeated_years))
                                    raise SkipRow(current_line,
                                                  reason=f'Computed academic year Y{item.academic_year} does not match '
                                                         f'the imported year-of-course value Y{year_of_course}')
                        except SkipRow as e:
                            # populate with values extracted from list
                            if e.user is None:
                                e.user = username

                            if e.first_name is None:
                                e.first_name = first_name

                            if e.last_name is None:
                                e.last_name = last_name

                            if e.email is None:
                                e.email = email

                            if e.year is None:
                                e.year = year_of_course

                            raise e

                    except SkipRow as e:
                        ignored_lines.append(e)
                        print(f'>> SUMMARY: skipped line {str(e)}')

        progress_update(record.celery_id, TaskRecord.RUNNING, 90, "Finalizing import...", autocommit=False)

        record.total_lines = current_line
        record.interpreted_lines = interpreted_lines
        record.celery_finished = True
        record.success = (interpreted_lines <= current_line)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        user.send_reload_request(autocommit=True)

        if len(ignored_lines) > 0:
            yearNone = []
            year0 = []
            year1 = []
            year2 = []
            year3 = []
            year4 = []
            yearN = []

            for item in ignored_lines:
                if item.year is None:
                    yearNone.append(item)
                elif item.year == 0:
                    if not record.ignore_Y0:
                        year0.append(item)
                elif item.year == 1:
                    year1.append(item)
                elif item.year == 2:
                    year2.append(item)
                elif item.year == 3:
                    year3.append(item)
                elif item.year == 4:
                    year4.append(item)
                else:
                    yearN.append(item)

            yearNone.sort()
            year0.sort()
            year1.sort()
            year2.sort()
            year3.sort()
            year4.sort()
            yearN.sort()

            user.post_message(render_template_string(template, yearNone=yearNone, year1=year1, year2=year2,
                                                     year3=year3, year4=year4, yearN=yearN),
                              'warning', autocommit=True)

        elif current_line == interpreted_lines:
            user.post_message('Successfully imported batch list "{name}"'.format(name=record.name), 'success',
                              autocommit=True)
        else:
            user.post_message('Batch list "{name}" was not correctly imported due to errors'.format(name=record.name),
                              'error', autocommit=True)


    @celery.task(bind=True, default_retry_delay=30)
    def import_batch_item(self, item_id, user_id):
        try:
            item: StudentBatchItem = db.session.query(StudentBatchItem).filter_by(id=item_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if item is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load database records'})
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
            self.update_state(state='FAILURE', meta={'msg': 'Could not load database records'})
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
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load database records'})
            raise Ignore()

        user.post_message('Errors occurred during batch import', 'error', autocommit=True)

        # raise new exception; will be caught by error handler on mark_user_task_failed()
        raise RuntimeError('Import process failed with an error')


    @celery.task(bind=True, default_retry_delay=30)
    def garbage_collection(self):
        try:
            records: StudentBatch = db.session.query(StudentBatch).filter_by(celery_finished=True).all()
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
            self.update_state(state='FAILURE', meta={'msg': 'Could not load database records'})
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
