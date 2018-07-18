#
# Created by David Seery on 28/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import redirect, url_for, flash
from flask_security import current_user

from app.models import db, MainConfig, ProjectClass, ProjectClassConfig


def get_main_config():

    return db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()


def get_current_year():

    return get_main_config().year


def home_dashboard():

    if current_user.has_role('faculty'):

        return redirect(url_for('faculty.dashboard'))

    elif current_user.has_role('student'):

        return redirect(url_for('student.dashboard'))

    elif current_user.has_role('office'):

        return redirect(url_for('office.dashboard'))

    else:

        flash('Your role could not be identified. Please contact the system administrator.')
        return redirect(url_for('auth.logged_out'))


def get_root_dashboard_data():

    current_year = get_current_year()

    pclass_ids = db.session.query(ProjectClass.id).filter_by(active=True).all()

    config_list = []

    rollover_ready = True

    for id in pclass_ids:

        config = db.session.query(ProjectClassConfig) \
            .filter_by(pclass_id=id[0]) \
            .order_by(ProjectClassConfig.year.desc()).first()

        if config is not None:
            config_list.append(config)
            if not config.closed:
                rollover_ready = False

    return config_list, current_year, rollover_ready
