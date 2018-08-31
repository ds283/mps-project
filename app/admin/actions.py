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

from ..models import db, ProjectClass, ProjectClassConfig, EnrollmentRecord, FacultyData, SelectingStudent, User
from ..shared.utils import get_current_year

from sqlalchemy import func

from datetime import datetime
import string
import random


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

    supervising_faculty = set()
    marking_faculty = set()

    for pclass in pclasses:

        # get ProjectClassConfig for the current year
        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=pclass.id, year=year) \
            .order_by(ProjectClassConfig.year.desc()).first()

        if config is None:
            raise RuntimeError('Configuration record for "{name}" '
                               'and year={yr} is missing'.format(name=pclass.name, yr=year))

        # find number of selectors for this project class
        num_selectors = db.session.query(func.count(SelectingStudent.id)) \
            .filter_by(retired=False, config_id=config.id).scalar()

        if config.CATS_supervision is not None and config.CATS_supervision > 0:
            supervising_CATS += config.CATS_supervision * num_selectors

        if config.CATS_marking is not None and config.CATS_marking > 0:
            marking_CATS += config.CATS_marking * num_selectors

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

    return supervising_CATS, marking_CATS, len(supervising_faculty), len(marking_faculty)
