#
# Created by David Seery on 2019-04-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import random
import string
from datetime import datetime

from flask import current_app
from flask_security import user_registered
from flask_security.confirmable import generate_confirmation_link
from flask_security.utils import hash_password, do_flash, get_message, config_value, send_mail

from app import db, User
from app.models import Role


def _randompassword():
  chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
  size = random.randint(8, 12)

  return ''.join(random.choice(chars) for x in range(size))


def register_user(**kwargs):
    if kwargs.pop('random_password', False) or len(kwargs['password']) == 0:
        kwargs['password'] = _randompassword()

    # hash password so that we never store the original
    kwargs['password'] = hash_password(kwargs['password'])

    # pop ask_confirm value before kwargs is presented to create_user()
    ask_confirm = kwargs.pop('ask_confirm', False)

    # generate a User record and commit it
    kwargs['active'] = True
    roles = kwargs.get('roles', [])
    roles_step1 = [db.session.query(Role).filter_by(name=r).first() for r in roles]
    roles_step2 = [x for x in roles_step1 if x is not None]
    kwargs['roles'] = roles_step2

    user = User(**kwargs)
    db.session.add(user)

    db.session.commit()

    # send confirmation email if we have been asked to
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
        db.session.commit()

    return user
