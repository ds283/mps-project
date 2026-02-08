#
# Created by David Seery on 09/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


import csv
from collections import deque
from io import StringIO

from ..database import db
from ..models import (
    ProjectClass,
    ProjectClassConfig,
    EnrollmentRecord,
    SelectingStudent,
    User,
    AssessorAttendanceData,
    SubmissionPeriodDefinition,
)
from ..shared.sqlalchemy import get_count
from ..shared.utils import get_current_year


def estimate_CATS_load():
    year = get_current_year()

    # get list of project classes that participate in automatic matching
    pclasses = db.session.query(ProjectClass).filter_by(active=True, publish=True, do_matching=True).all()

    supervision_CATS = 0
    marking_CATS = 0
    moderation_CATS = 0
    presentation_CATS = 0

    supervision_faculty = set()
    marking_faculty = set()
    moderation_faculty = set()
    presentation_faculty = set()

    for pclass in pclasses:
        pclass: ProjectClass

        # get ProjectClassConfig for the current year
        config: ProjectClassConfig = pclass.get_config(year)

        if config is None:
            raise RuntimeError('Configuration record for "{name}" and year={yr} is missing'.format(name=pclass.name, yr=year))

        # find number of selectors for this project class
        num_selectors = get_count(db.session.query(SelectingStudent).filter_by(retired=False, convert_to_submitter=True, config_id=config.id))

        if pclass.uses_supervisor:
            if pclass.CATS_supervision is not None and pclass.CATS_supervision > 0:
                supervision_CATS += pclass.CATS_supervision * num_selectors

            # find supervising faculty enrolled for this project
            supervisors = (
                db.session.query(EnrollmentRecord)
                .filter_by(pclass_id=pclass.id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED)
                .join(User, User.id == EnrollmentRecord.owner_id)
                .filter(User.active)
                .all()
            )

            for item in supervisors:
                supervision_faculty.add(item.owner_id)

        if pclass.uses_marker:
            if pclass.CATS_marking is not None and pclass.CATS_marking > 0:
                for period in pclass.periods:
                    period: SubmissionPeriodDefinition
                    marking_CATS += pclass.CATS_marking * num_selectors * period.number_markers

            # find marking faculty enrolled for this project
            markers = (
                db.session.query(EnrollmentRecord)
                .filter_by(pclass_id=pclass.id, marker_state=EnrollmentRecord.MARKER_ENROLLED)
                .join(User, User.id == EnrollmentRecord.owner_id)
                .filter(User.active)
                .all()
            )

            for item in markers:
                marking_faculty.add(item.owner_id)

        if pclass.uses_moderator:
            if pclass.CATS_moderation is not None and pclass.CATS_moderation > 0:
                for period in pclass.periods:
                    period: SubmissionPeriodDefinition
                    moderation_CATS += pclass.CATS_moderation * num_selectors * period.number_moderators

            # find moderating faculty enrolled for this project
            moderators = (
                db.session.query(EnrollmentRecord)
                .filter_by(pclass_id=pclass.id, moderator_state=EnrollmentRecord.MODERATOR_ENROLLED)
                .join(User, User.id == EnrollmentRecord.owner_id)
                .filter(User.active)
                .all()
            )

            for item in moderators:
                moderation_faculty.add(item.owner_id)

        if pclass.uses_presentations:
            if pclass.CATS_presentation is not None and pclass.CATS_presentation > 0:
                for period in pclass.periods:
                    period: SubmissionPeriodDefinition
                    if period.has_presentation:
                        presentation_CATS += pclass.CATS_presentation * num_selectors * period.number_assessors

            # find assessor faculty enrolled for this project
            markers = (
                db.session.query(EnrollmentRecord)
                .filter_by(pclass_id=pclass.id, presentations_state=EnrollmentRecord.PRESENTATIONS_ENROLLED)
                .join(User, User.id == EnrollmentRecord.owner_id)
                .filter(User.active)
                .all()
            )

            for item in markers:
                presentation_faculty.add(item.owner_id)

    num_supervision_faculty = len(supervision_faculty)
    num_marking_faculty = len(marking_faculty)
    num_moderation_faculty = len(moderation_faculty)
    num_presentation_faculty = len(presentation_faculty)

    return {
        "supervision_CATS": supervision_CATS,
        "marking_CATS": marking_CATS,
        "moderation_CATS": moderation_CATS,
        "presentation_CATS": presentation_CATS,
        "supervision_faculty": num_supervision_faculty,
        "marking_faculty": num_marking_faculty,
        "moderation_faculty": num_moderation_faculty,
        "presentation_faculty": num_presentation_faculty,
        "supervision_workload": supervision_CATS / num_supervision_faculty if num_supervision_faculty > 0 else 0,
        "marking_workload": marking_CATS / num_marking_faculty if num_marking_faculty > 0 else 0,
        "moderation_workload": moderation_CATS / num_moderation_faculty if num_moderation_faculty > 0 else 0,
        "presentation_owrkload": presentation_CATS / num_presentation_faculty if num_presentation_faculty > 0 else 0,
    }


def availability_CSV_generator(assessment):
    data = StringIO()
    w = csv.writer(data, quoting=csv.QUOTE_NONNUMERIC)

    sessions = assessment.ordered_sessions.all()

    headings = ["Name", "Confirmed"]
    for s in sessions:
        headings.append(s.label_as_string)
    headings.append("Comment")

    w.writerow(headings)
    yield data.getvalue()
    data.seek(0)
    data.truncate(0)

    assessors = assessment.assessor_list.subquery()

    faculty = (
        db.session.query(AssessorAttendanceData)
        .join(assessors, assessors.c.id == AssessorAttendanceData.id)
        .join(User, User.id == AssessorAttendanceData.faculty_id)
        .order_by(User.last_name.asc(), User.first_name.asc())
        .all()
    )

    for item in faculty:
        fac_id = item.faculty.id

        row = [item.faculty.user.name, item.confirmed]
        for s in sessions:
            if s.faculty_available(fac_id):
                row.append("Yes")
            elif s.faculty_ifneeded(fac_id):
                row.append("If needed")
            elif s.faculty_unavailable(fac_id):
                row.append("No")
            else:
                row.append("Unknown")
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
    filter_list = [p for p in score_list if p[0] > max_score / 2]

    sorted_list = sorted(filter_list, key=lambda x: x[0])

    if len(sorted_list) == 0:
        return None

    return (sorted_list[0])[1]


def _exact_match(item1, item2):
    # can assume that item1 and item2 are matching slots
    if item1.session_id != item2.session_id or item1.room_id != item2.room_id:
        raise RuntimeError("Incorrect matching of shared slots in _exact_match()")

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
        raise RuntimeError("Multiple slots present in _slot_exists")

    return len(sublist) > 0


def pair_slots(s1, s2, flag=False, pclass_value=None):
    """
    Computes the changes needed to convert the schedule represented by slot list s1
    into the schedule represented by slot list s2
    """
    if flag:
        assert pclass_value is not None

    # break slots1 into slots that have been deleted in slots2, and those that are still present
    slots1_deleted = deque(sorted([s for s in s1 if not _slot_exists(s, s2)], key=lambda x: (x.session_id, x.room_id)))
    slots1_shared = deque(sorted([s for s in s1 if _slot_exists(s, s2)], key=lambda x: (x.session_id, x.room_id)))

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
            pairs.append(("move", s, m))
            delete_list.append(s)
            slots2_new.remove(m)

    for s in delete_list:
        slots1_deleted.remove(s)

    # remaining elements in slots1_deleted are removed
    while len(slots1_deleted) > 0:
        s = slots1_deleted.popleft()
        pairs.append(("delete", s, None))

    # remaining elements in slots2_new are added
    while len(slots2_new) > 0:
        s = slots2_new.popleft()
        pairs.append(("add", None, s))

    # elements in slots1_shared and slots2_shared just require edits
    # since they are sorted in order, we can just peel off slots from the left hand side of each deque
    while len(slots1_shared) > 0 and len(slots2_shared) > 0:
        l = slots1_shared.popleft()
        r = slots2_shared.popleft()

        if not _exact_match(l, r):
            pairs.append(("edit", l, r))

    return pairs
