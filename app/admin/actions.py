#
# Created by David Seery on 09/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app, render_template, redirect, url_for, flash
from werkzeug.local import LocalProxy
from flask_security.utils import hash_password, do_flash, config_value, send_mail, get_message
from flask_security.signals import user_registered
from flask_security.confirmable import generate_confirmation_link

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
