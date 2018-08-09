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

from flask import Flask, current_app, request
from flask_migrate import Migrate
from flask_security import current_user, SQLAlchemyUserDatastore, Security
from flask_bootstrap import Bootstrap
from flask_mail import Mail
from flask_assets import Environment
from app.flask_bleach import Bleach
from flaskext.markdown import Markdown

from config import app_config
from .models import db, User, EmailLog, MessageOfTheDay, Notification
from .task_queue import make_celery, register_task
from app.task_queue import background_task
import app.tasks as tasks

from mdx_smartypants import makeExtension

from bleach_whitelist.bleach_whitelist import markdown_tags, markdown_attrs


def create_app():

    # get current configuration, or default to 'production' for safety
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

    # set up celery and store in extensions dictionary
    celery = make_celery(app)
    app.extensions['celery'] = celery

    # register celery tasks
    # there doesn't seem a good way of doing this using factory functions! Here I compromise by passing hte
    # celery application instance to a collection of register_*() functions, which use an @celery decorator
    # to register callables. Then we write the callable into the app, in the 'tasks' dictionary
    app.tasks = {}
    tasks.register_send_log_email(celery, mail)
    tasks.register_prune_email(celery)
    tasks.register_backup_tasks(celery)
    tasks.register_rollover_tasks(celery)
    tasks.register_golive_tasks(celery)
    tasks.register_user_launch_tasks(celery)
    tasks.register_popularity_tasks(celery)
    tasks.register_test_tasks(celery)


    # make Flask-Security use deferred email sender
    @security.send_mail_task
    def delay_flask_security_mail(msg):

        # get send-log-email celery task
        celery = current_app.extensions['celery']
        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']

        # register a new task in the database
        task_id = register_task(msg.subject, description='Email to {r}'.format(r=', '.join(msg.recipients)))

        # queue Celery task to send the email
        task = send_log_email.delay(task_id, msg)


    @security.login_context_processor
    def login_context_processor():

        # build list of system messages to consider displaying on login screen
        messages = []
        for message in MessageOfTheDay.query.filter_by(show_login=True).all():

            if message.project_classes.first() is None:

                messages.append(message)

        return dict(messages=messages)


    @app.before_request
    def remove_stale_notifications():

        if current_user.is_authenticated and request.endpoint is not None and 'ajax' not in request.endpoint:
            Notification.query.filter_by(remove_on_pageload=True).delete()
            db.session.commit()


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

