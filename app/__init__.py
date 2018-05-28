#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

from flask import Flask, flash
from flask_migrate import Migrate
from flask_security import SQLAlchemyUserDatastore, Security
from flask_bootstrap import Bootstrap
from flask_mail import Mail
from flask_assets import Environment
from app.flask_bleach import Bleach
from flaskext.markdown import Markdown

from config import app_config
from .models import db, User, EmailLog
from .tasks import make_celery

from mdx_smartypants import makeExtension

from bleach_whitelist.bleach_whitelist import markdown_tags, markdown_attrs

from datetime import datetime


def create_app():

    # get current configuration, or default to production for safety
    config_name = os.environ.get('FLASK_ENV') or 'production'

    app = Flask(__name__, instance_relative_config=True)        # load configuration files from 'instance'
    app.config.from_object(app_config[config_name])
    app.config.from_pyfile('config.py')
    app.config.from_pyfile('mail.py')

    db.init_app(app)
    migrate = Migrate(app, db)
    bootstrap = Bootstrap(app)
    mail = Mail(app)
    bleach = Bleach(app)
    md = Markdown(app, extensions=[makeExtension(configs={'entities': 'named'})])

    app.config['BLEACH_ALLOWED_TAGS'] = markdown_tags
    app.config['BLEACH_ALLOWED_ATTRS'] = markdown_attrs

    # set up CSS and javascript assets
    env = Environment(app)

    from app import models

    user_datastore = SQLAlchemyUserDatastore(db, models.User, models.Role)

    # we don't override any of Security's internal forms, but we do replace its create user funciton
    # that automatically uses our own replacements
    security = Security(app, user_datastore)

    # set up  celery
    celery = make_celery(app)

    # set up deferred email sender for Flask-Email; note that Flask-Email's Message object is not
    # JSON-serializable so we have to pickle instead
    @celery.task(serializer='pickle')
    def send_flask_mail(msg):
        mail.send(msg)

        # store message in email log
        user = User.query.filter_by(email=msg.recipients[0]).first()
        if user is not None:

            log = EmailLog(user_id=user.id,
                           send_date=datetime.now(),
                           subject=msg.subject,
                           body=msg.body,
                           html=msg.html)
            db.session.add(log)
            db.session.commit()

        else:

            flash('Failed to log email message. Please report this error to the system administrator', 'error')


    # make Flask-Security use deferred email sender
    @security.send_mail_task
    def delay_flask_security_mail(msg):
        send_flask_mail.delay(msg)


    # IMPORT BLUEPRINTS

    from .home import home as home_blueprint
    app.register_blueprint(home_blueprint, url_prefix='/')

    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint, url_prefix='/auth')

    from .admin import admin as admin_blueprint
    app.register_blueprint(admin_blueprint, url_prefix='/admin')

    from .faculty import faculty as faculty_blueprint
    app.register_blueprint(faculty_blueprint, url_prefix='/faculty')

    from .convenor import convenor as convenor_blueprint
    app.register_blueprint(convenor_blueprint, url_prefix='/convenor')

    from .student import student as student_blueprint
    app.register_blueprint(student_blueprint, url_prefix='/student')

    from .office import office as office_blueprint
    app.register_blueprint(office_blueprint, url_prefix='/office')

    return app, celery

