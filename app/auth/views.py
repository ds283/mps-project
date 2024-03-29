#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import redirect, url_for, flash, session, current_app
from flask_security import current_user, logout_user, login_user
from sqlalchemy.exc import NoResultFound, MultipleResultsFound

from . import auth
from ..database import db
from ..models import User
from ..shared.context.global_context import render_template_context


@auth.route("/logout")
def logout():
    """
    Log out the current user
    """

    prev_id = session.pop("previous_login", None)

    if prev_id is not None and isinstance(prev_id, int):
        try:
            user = db.session.query(User).filter_by(id=prev_id).one()

            current_app.logger.info(
                "{real} reverted to viewing the site as themselves (previously viewing as "
                "alternative user {fake})".format(real=user.name, fake=current_user.name)
            )

            login_user(user)
            return redirect(url_for("manage_users.edit_users"))
        except NoResultFound:
            pass
        except MultipleResultsFound:
            pass

    logout_user()
    flash("You have been logged out")
    return redirect(url_for("security.login"))


@auth.route("/logged_out")
def logged_out():
    """
    Inform the user that an unrecoverable error has occurred, and they have been logged out.
    Assume any error message has already been posted via flash.
    :return: HTML string
    """

    logout_user()
    return render_template_context("auth/error_logout.html")
