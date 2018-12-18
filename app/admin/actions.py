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

    confirmation_link, token = None, None

    if ('random_password' in kwargs and kwargs['random_password']) or len(kwargs['password']) == 0:

        kwargs['password'] = _randompassword()

    # hash password so that we never store the original
    kwargs['password'] = hash_password(kwargs['password'])

    # generate a User record and commit it
    user = _datastore.create_user(**kwargs)
    _datastore.commit()

    # send confirmation email if we have been asked to
    if _security.confirmable:

        if 'ask_confirm' in kwargs and kwargs['ask_confirm']:

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


def _exact_match(item1, item2):
    if item1.session_id != item2.session_id:
        return False

    if item1.room_id != item2.room_id:
        return False

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


def _same_slot(item1, item2):
    return (item1.session_id == item2.session_id) and (item1.room_id == item2.room_id)


def pair_slots(s1, s2, flag, pclass_value):
    slots1 = deque(s1)
    slots2 = deque(s2)

    pairs = []

    while len(slots1) > 0 and len(slots2) > 0:
        item = slots1.popleft()

        if flag:
            if item.pclass.id != pclass_value:
                continue

        # iterate thorugh slots2, assigning a 'score' to each slot.
        # the highest-scoring slot is the closest match
        scores = {}
        lookup = {}
        for candidate in slots2:
            scores[candidate.id] = _score_similarities(item, candidate)
            lookup[candidate.id] = candidate

        score_list = sorted(list(scores.items()), key=lambda x: x[1], reverse=True)
        best_match = score_list[0]
        match_slot = lookup[best_match[0]]

        if _exact_match(item, match_slot):
            slots2.remove(match_slot)

        elif best_match[1] > 1:
            slots2.remove(match_slot)

            if _same_slot(item, match_slot):
                pairs.append(('edit', item, match_slot))
            else:
                pairs.append(('move', item, match_slot))

        else:
            pairs.append(('delete', item, None))

    while len(slots1) > 0:
        item = slots1.popleft()
        if flag:
            if item.pclass.id != pclass_value:
                continue

        pairs.append(('delete', item, None))

    while len(slots2) > 0:
        item = slots2.popleft()
        if flag:
            if item.pclass.id != pclass_value:
                continue

        pairs.append(('add', item, None))

    return pairs
