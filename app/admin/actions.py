#
# Created by David Seery on 09/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app
from werkzeug.local import LocalProxy
from flask_security.utils import hash_password, do_flash, config_value, send_mail, get_message
from flask_security.signals import user_registered
from flask_security.confirmable import generate_confirmation_link

from ..database import db
from ..models import ProjectClass, ProjectClassConfig, EnrollmentRecord, FacultyData, SelectingStudent, User, \
    AssessorAttendanceData
from ..shared.utils import get_current_year
from ..shared.sqlalchemy import get_count

import csv
from io import StringIO

from sqlalchemy import func

from datetime import datetime
import string
import random
from collections import deque


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


def _randompassword():
  chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
  size = random.randint(8, 12)

  return ''.join(random.choice(chars) for x in range(size))


def register_user(**kwargs):
    if kwargs.pop('random_password', False) or len(kwargs['password']) == 0:
        kwargs['password'] = _randompassword()

    # hash password so that we never store the original
    start_time = datetime.now()
    kwargs['password'] = hash_password(kwargs['password'])
    end_time = datetime.now()
    delta = end_time - start_time
    print('## Password hashing took {total} secs'.format(total=delta.total_seconds()))

    # pop ask_confirm value before kwargs is presented to create_user()
    ask_confirm = kwargs.pop('ask_confirm', False)

    # generate a User record and commit it
    user = _datastore.create_user(**kwargs)
    _datastore.commit()

    # send confirmation email if we have been asked to
    if _security.confirmable:
        if ask_confirm:
            confirmation_link, token = generate_confirmation_link(user)
            do_flash(*get_message('CONFIRM_REGISTRATION', email=user.email))

            user_registered.send(current_app._get_current_object(),
                                 user=user, confirm_token=token)

            if config_value('SEND_REGISTER_EMAIL'):
                send_mail(config_value('EMAIL_SUBJECT_REGISTER'), user.email,
                          'welcome', user=user, confirmation_link=confirmation_link)

        else:
            user.confirmed_at = datetime.now()
            _datastore.commit()

    return user


def estimate_CATS_load():
    year = get_current_year()

    # get list of project classes that participate in automatic matching
    pclasses = db.session.query(ProjectClass).filter_by(active=True, do_matching=True).all()

    supervising_CATS = 0
    marking_CATS = 0
    presentation_CATS = 0

    supervising_faculty = set()
    marking_faculty = set()
    presentation_faculty = set()

    for pclass in pclasses:

        # get ProjectClassConfig for the current year
        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=pclass.id, year=year) \
            .order_by(ProjectClassConfig.year.desc()).first()

        if config is None:
            raise RuntimeError('Configuration record for "{name}" '
                               'and year={yr} is missing'.format(name=pclass.name, yr=year))

        # find number of selectors for this project class
        num_selectors = get_count(db.session.query(SelectingStudent).filter_by(retired=False,
                                                                               config_id=config.id))

        if config.CATS_supervision is not None and config.CATS_supervision > 0:
            supervising_CATS += config.CATS_supervision * num_selectors

        if config.CATS_marking is not None and config.CATS_marking > 0:
            marking_CATS += config.CATS_marking * num_selectors

        if pclass.uses_supervisor:
            # find supervising faculty enrolled for this project
            supervisors = db.session.query(EnrollmentRecord) \
                .filter_by(pclass_id=pclass.id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED) \
                .join(User, User.id==EnrollmentRecord.owner_id) \
                .filter(User.active).all()

            for item in supervisors:
                supervising_faculty.add(item.owner_id)

        if pclass.uses_marker:
            # find marking faculty enrolled for this project
            markers = db.session.query(EnrollmentRecord) \
                .filter_by(pclass_id=pclass.id, marker_state=EnrollmentRecord.MARKER_ENROLLED) \
                .join(User, User.id == EnrollmentRecord.owner_id) \
                .filter(User.active).all()

            for item in markers:
                marking_faculty.add(item.owner_id)

        if pclass.uses_presentations:
            # find assessor faculty enrolled for this project
            markers = db.session.query(EnrollmentRecord) \
                .filter_by(pclass_id=pclass.id, presentations_state=EnrollmentRecord.PRESENTATIONS_ENROLLED) \
                .join(User, User.id == EnrollmentRecord.owner_id) \
                .filter(User.active).all()

            for item in markers:
                presentation_faculty.add(item.owner_id)

    return supervising_CATS, marking_CATS, presentation_CATS, \
           len(supervising_faculty), len(marking_faculty), len(presentation_faculty)


def availability_CSV_generator(assessment):
    data = StringIO()
    w = csv.writer(data, quoting=csv.QUOTE_NONNUMERIC)

    sessions = assessment.ordered_sessions.all()

    headings = ['Name', 'Confirmed']
    for s in sessions:
        headings.append(s.short_date_as_string + ' ' + s.session_type_string)
    headings.append('Comment')

    w.writerow(headings)
    yield data.getvalue()
    data.seek(0)
    data.truncate(0)

    assessors = assessment.assessor_list.subquery()

    faculty = db.session.query(AssessorAttendanceData) \
        .join(assessors, assessors.c.id == AssessorAttendanceData.id) \
        .join(User, User.id == AssessorAttendanceData.faculty_id) \
        .order_by(User.last_name.asc(), User.first_name.asc()).all()

    for item in faculty:
        fac_id = item.faculty.id

        row = [item.faculty.user.name, item.confirmed]
        for s in sessions:
            if s.faculty_available(fac_id):
                row.append('Yes')
            elif s.faculty_ifneeded(fac_id):
                row.append('If needed')
            elif s.faculty_unavailable(fac_id):
                row.append('No')
            else:
                row.append('Unknown')
        row.append(item.comment)

        w.writerow(row)
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)


def _score_similarities(item1, item2):
    score = 0

    if item1.session_id == item2.session_id:
        score += 1

    if item1.room_id == item2.session_id:
        score += 1

    item1_assessors = [a.id for a in item1.assessors]
    item2_assessors = [a.id for a in item2.assessors]
    for assessor in item1_assessors:
        if assessor in item2_assessors:
            score += 1

    item1_talks = [t.id for t in item1.talks]
    item2_talks = [t.id for t in item2.talks]
    for talk in item1_talks:
        if talk in item2_talks:
            score += 1

    return score


def _find_match(slot, search_list):
    max_score = get_count(slot.assessors) + get_count(slot.talks)

    score_list = [(_score_similarities(slot, s), s) for s in search_list]
    filter_list = [p for p in score_list if p[0] > max_score/2]

    sorted_list = sorted(filter_list, key=lambda x: x[0])

    if len(sorted_list) == 0:
        return None

    return (sorted_list[0])[1]


def _exact_match(item1, item2):
    # can assume that item1 and item2 are matching slots
    if item1.session_id != item2.session_id or item1.room_id != item2.room_id:
        raise RuntimeError('Incorrect matching of shared slots in _exact_match()')

    # determine whether item1 and item2 have matching assessors and talks,
    # as efficiently as possible

    item1_assessors = sorted([a.id for a in item1.assessors])
    item2_assessors = sorted([a.id for a in item2.assessors])
    if len(item1_assessors) != len(item2_assessors):
        return False

    for i in range(len(item1_assessors)):
        if item1_assessors[i] != item2_assessors[i]:
            return False

    item1_talks = sorted([t.id for t in item1.talks])
    item2_talks = sorted([t.id for t in item2.talks])
    if len(item1_talks) != len(item2_talks):
        return False

    for i in range(len(item1_talks)):
        if item1_talks[i] != item2_talks[i]:
            return False

    return True


def _slot_exists(slot, slot_list):
    """
    Determines whether a counterpart for 'slot' is present in slot_list
    :param slot:
    :param slot_list:
    :return:
    """
    sublist = [s for s in slot_list if s.session_id == slot.session_id and s.room_id == slot.room_id]

    if len(sublist) > 1:
        raise RuntimeError('Multiple slots present in _slot_exists')

    return len(sublist) > 0


def pair_slots(s1, s2, flag=False, pclass_value=None):
    """
    Computes the changes needed to convert the schedule represented by slot list s1
    into the schedule represented by slot list s2
    """
    if flag:
        assert(pclass_value is not None)

    # break slots1 into slots that have been deleted in slots2, and those that are still present
    slots1_deleted = deque(sorted([s for s in s1 if not _slot_exists(s, s2)], key=lambda x: (x.session_id, x.room_id)))
    slots1_shared  = deque(sorted([s for s in s1 if _slot_exists(s, s2)], key=lambda x: (x.session_id, x.room_id)))

    # break slots2 into slots that are new compared to slots1, and those that are shared
    slots2_new = deque(sorted([s for s in s2 if not _slot_exists(s, s1)], key=lambda x: (x.session_id, x.room_id)))
    slots2_shared = deque(sorted([s for s in s2 if _slot_exists(s, s1)], key=lambda x: (x.session_id, x.room_id)))

    # pairs is a list of (op, source, target), where op is one of 'add', 'delete', 'move' or 'edit'
    pairs = []

    # slots removed from slots1 could have been moved to a new location (session, room) in slots2.
    # in that case, their counterparts should show up in slots2_new.
    # this makes moves 'atomic', ie. we don't get long chains where if we move A -> B then we have to displace
    # the original B -> C, and displace the original C to ... etc.
    delete_list = []
    for s in slots1_deleted:
        m = _find_match(s, slots2_new)

        if m is not None:
            pairs.append(('move', s, m))
            delete_list.append(s)
            slots2_new.remove(m)

    for s in delete_list:
        slots1_deleted.remove(s)

    # remaining elements in slots1_deleted are removed
    while len(slots1_deleted) > 0:
        s = slots1_deleted.popleft()
        pairs.append(('delete', s, None))

    # remaining elements in slots2_new are added
    while len(slots2_new) > 0:
        s = slots2_new.popleft()
        pairs.append(('add', None, s))

    # elements in slots1_shared and slots2_shared just require edits
    # since they are sorted in order, we can just peel off slots from the left hand side of each deque
    while len(slots1_shared) > 0 and len(slots2_shared) > 0:
        l = slots1_shared.popleft()
        r = slots2_shared.popleft()

        if not _exact_match(l, r):
            pairs.append(('edit', l, r))

    return pairs
