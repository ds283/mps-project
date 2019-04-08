#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>, David Turner <dt237@sussex.ac.uk>
#

import os

from flask import current_app, request, session, render_template, has_request_context
from flask_migrate import Migrate
from flask_security import current_user, SQLAlchemyUserDatastore, Security
from flask_login.signals import user_logged_in
from .thirdparty.flask_bootstrap import Bootstrap
from flask_mail import Mail
from flask_assets import Environment
from app.flask_bleach import Bleach
from flaskext.markdown import Markdown
from flask_debugtoolbar import DebugToolbarExtension
from flask_debug_api import DebugAPIExtension
from flask_sessionstore import Session
from flask_uploads import configure_uploads, patch_request_class
from flask import Flask
from werkzeug.contrib.fixers import ProxyFix
from .cache import cache
from .limiter import limiter
from .uploads import solution_files, batch_user_files
from flask_sqlalchemy import get_debug_queries
from flask_profiler import Profiler
from flask_rollbar import Rollbar

from config import app_config, site_revision, site_copyright_dates
from .database import db
from .models import User, EmailLog, MessageOfTheDay, Notification
from .task_queue import make_celery, register_task, background_task
from .shared.utils import home_dashboard_url, get_assessment_data
from .shared.precompute import precompute_at_login
import app.tasks as tasks

from sqlalchemy.exc import SQLAlchemyError

from mdx_smartypants import makeExtension
from bleach_whitelist.bleach_whitelist import markdown_tags, markdown_attrs
import latex2markdown
from urllib import parse

from os import path, makedirs
from datetime import datetime

from pymongo import MongoClient
import redis

from werkzeug.contrib.profiler import ProfilerMiddleware
from dozer import Dozer


def create_app():
    # get current configuration, or default to 'production' for safety
    config_name = os.environ.get('FLASK_ENV') or 'production'

    app = Flask(__name__, instance_relative_config=True)        # load configuration files from 'instance'
    app.config.from_object(app_config[config_name])
    app.config.from_pyfile('secrets.py')
    app.config.from_pyfile('mail.py')
    app.config.from_pyfile('rollbar.py')
    app.config.from_pyfile('scout.py')
    app.config.from_pyfile('local.py')

    # create a long-lived Redis connection
    app.config['REDIS_SESSION'] = redis.Redis.from_url(url=app.config['CACHE_REDIS_URL'])

    # create long-lived Mongo connection for Flask-Sessionstore
    app.config['SESSION_MONGODB'] = MongoClient(host=app.config['SESSION_MONGO_URL'])

    app.wsgi_app = ProxyFix(app.wsgi_app, num_proxies=1)

    if app.config.get('PROFILE_MEMORY', False):
        app.wsgi_app = Dozer(app.wsgi_app)

    db.init_app(app)

    migrate = Migrate(app, db)
    bootstrap = Bootstrap(app)
    mail = Mail(app)
    bleach = Bleach(app)
    md = Markdown(app, extensions=[makeExtension(configs={'entities': 'named'})])
    rb = Rollbar(app)

    session_store = Session(app)

    cache.init_app(app)

    # add endpoint profiler and rate limiter in production mode
    # also add handler to direct Waitress logging output to the console
    if config_name == 'production':
        profiler = Profiler(app)

        # set up Flask-Limiter
        limiter.init_app(app)

    # add debug toolbar if in debug mode
    if config_name == 'development':
        toolbar = DebugToolbarExtension(app)
        api_toolbar = DebugAPIExtension(app)

        panels = list(app.config['DEBUG_TB_PANELS'])
        panels.append('flask_debug_api.BrowseAPIPanel')
        # panels.append('flask_debugtoolbar_lineprofilerpanel.panels.LineProfilerPanel')
        app.config['DEBUG_TB_PANELS'] = panels

    # app.config['BLEACH_ALLOWED_TAGS'] = markdown_tags
    # app.config['BLEACH_ALLOWED_ATTRS'] = markdown_attrs

    # set up CSS and javascript assets
    env = Environment(app)

    if not app.debug:
        from logging import ERROR, DEBUG, INFO, Formatter, basicConfig
        from logging.handlers import SMTPHandler, RotatingFileHandler

        basicConfig(level=INFO)

        # disable email notification of exceptions for now; this seems to be
        # better handled through rollbar.com

        # mail_handler = SMTPHandler(mailhost=(app.config['MAIL_SERVER'], app.config['MAIL_PORT']),
        #                            fromaddr=app.config['MAIL_DEFAULT_SENDER'],
        #                            toaddrs=app.config['ADMIN_EMAIL'],
        #                            subject='MPS Project Manager live exception reported',
        #                            credentials=(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD']),
        #                            secure=())
        # mail_handler.setLevel(ERROR)
        # app.logger.addHandler(mail_handler)

        file_handler = RotatingFileHandler(app.config['LOG_FILE'], 'a', 1 * 1024 * 1024, 10)
        file_handler.setFormatter(Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
        app.logger.setLevel(INFO)
        file_handler.setLevel(INFO)
        app.logger.addHandler(file_handler)
        app.logger.info('MPS Project Manager starting')

    # use Werkzeug built-in profiler if profile-to-disk is enabled
    if app.config.get('PROFILE_TO_DISK', False):
        app.config['PROFILE'] = True
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, profile_dir=app.config.get('PROFILE_DIRECTORY'))

        app.logger.info('Profiling to disk enabled')

    # configure behaviour for uploaded files
    asset_folder = app.config.get('ASSETS_FOLDER')
    uploaded_subfolder = app.config.get('ASSETS_UPLOADED_SUBFOLDER')
    abs_uploaded_path = path.join(asset_folder, uploaded_subfolder)
    makedirs(abs_uploaded_path, exist_ok=True)

    app.config['UPLOADED_SOLUTIONS_DEST'] = abs_uploaded_path
    app.config['UPLOADED_BATCHUSERLIST_DEST'] = abs_uploaded_path
    configure_uploads(app, [solution_files, batch_user_files])

    # set max upload size = 64 Mb, optimizer solution files shouldn't be larger than this
    # (though MPS files can be quite large if those are being used)
    patch_request_class(app, 64*1024*1024)


    # configure Flask-Security, which needs access to the database models for User and Role
    from app import models

    user_datastore = SQLAlchemyUserDatastore(db, models.User, models.Role)

    # we don't override any of Security's internal forms, but we do replace its create user function
    # that automatically uses our own replacements
    security = Security(app, user_datastore)
    if config_name == 'production':
        # set up more stringent limits for login view and forgot-password view
        # add to a particular view function.
        login = app.view_functions['security.login']
        forgot = app.view_functions['security.forgot_password']
        limiter.limit("50/day;5/minute")(login)
        limiter.limit("50/day;5/minute")(forgot)


    # set up celery and store in extensions dictionary
    celery = make_celery(app)
    app.extensions['celery'] = celery

    # register celery tasks
    # there doesn't seem a good way of doing this using factory functions! Here I compromise by passing the
    # celery application instance to a collection of register_*() functions, which use an @celery decorator
    # to register callables. Then we write the callable into the app, in the 'tasks' dictionary
    app.tasks = {}
    tasks.register_send_log_email(celery, mail)
    tasks.register_utility_tasks(celery)
    tasks.register_prune_email(celery)
    tasks.register_backup_tasks(celery)
    tasks.register_rollover_tasks(celery)
    tasks.register_issue_confirm_tasks(celery)
    tasks.register_golive_tasks(celery)
    tasks.register_close_selection_tasks(celery)
    tasks.register_user_launch_tasks(celery)
    tasks.register_popularity_tasks(celery)
    tasks.register_matching_tasks(celery)
    tasks.register_availability_tasks(celery)
    tasks.register_scheduling_tasks(celery)
    tasks.register_maintenance_tasks(celery)
    tasks.register_assessment_tasks(celery)
    tasks.register_assessor_tasks(celery)
    tasks.register_email_notification_tasks(celery)
    tasks.register_precompute_tasks(celery)
    tasks.register_push_feedback_tasks(celery)
    tasks.register_system_tasks(celery)
    tasks.register_batch_create_tasks(celery)
    tasks.register_selecting_tasks(celery)
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
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


    @security.login_context_processor
    def login_context_processor():
        # build list of system messages to consider displaying on login screen
        messages = []
        for message in MessageOfTheDay.query.filter_by(show_login=True).all():
            if message.project_classes.first() is None:
                messages.append(message)

        return dict(messages=messages)


    @app.before_request
    def before_request_handler():
        if current_user.is_authenticated:
            if request.endpoint is not None and 'ajax' not in request.endpoint:
                try:
                    Notification.query.filter_by(remove_on_pageload=True).delete()
                    db.session.commit()
                except SQLAlchemyError:
                    pass


    @app.template_filter('dealingwithdollars')
    def dealingwithdollars(latex_string):
        if latex_string is None:
            return r'<div class="alert alert-danger">An empty string was supplied. ' \
                   r'Please check your project description.</div>'

        splat = list(latex_string)  # Splits string into list of characters
        dollar_inds = [i for i in range(0, len(splat)) if splat[i] == "$"]  # Finds indices of all dollar signs
        display_inds = []  # Less pythonic than list comprehension, but now inline_inds can exclude double dollar signs
        for elem in dollar_inds:
            if elem != len(splat) - 1:
                if splat[elem + 1] == r"$":
                    display_inds.append(elem)
                    display_inds.append(elem + 1)
        inline_inds = [elem for elem in dollar_inds if splat[elem - 1] != "\\" and elem not in display_inds]  # \$ is allowed in LaTeX, $ is not.
        just_dollar = [elem for elem in dollar_inds if elem not in inline_inds and elem not in display_inds]

        if len(inline_inds) % 2 != 0:  # Checks for lonely dollar signs
            latex_string = r'<div class="alert alert-danger">Failed to match LaTeX dollar delimiters. ' \
                           r'Please check the markup in your project description.</div>' + latex_string

        else:  # Only converts inline math delimiters, as latex2markdown seems to convert display math delimiters
            for i in range(0, len(inline_inds)):
                if i % 2 == 0:
                    splat[inline_inds[i]] = r"\\("
                else:
                    splat[inline_inds[i]] = r"\\)"

            for elem in just_dollar:
                splat.pop(elem - 1)

            latex_string = ''.join(splat)

        l2m_obj = latex2markdown.LaTeX2Markdown(latex_string)
        mathjax_string = l2m_obj.to_markdown()
        return mathjax_string


    @app.template_filter('urlencode')
    def urlencode_filter(s):
        if s is None:
            return None

        s = s.encode('utf8')
        s = parse.quote_plus(s)
        return bleach.clean(s)


    @app.context_processor
    def global_context():
        if not has_request_context():
            return {}

        if session.get('previous_login', None) is not None:
            real_id = session['previous_login']
            real_user = db.session.query(User).filter_by(id=real_id).first()
        else:
            real_user = None

        ctx = {'real_user': real_user,
               'website_revision': site_revision,
               'website_copyright_dates': site_copyright_dates}

        if current_user is not None and current_user.has_role('root'):
            assessment_data = get_assessment_data()
            ctx.update(assessment_data)

        return ctx


    @app.context_processor
    def inject_home_dashboard_url():
        if not has_request_context():
            return {}

        return {'home_dashboard_url': home_dashboard_url()}


    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404


    @app.errorhandler(429)
    def rate_limit_error(error):
        return render_template('errors/429.html'), 429


    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500


    if not app.debug:
        @app.after_request
        def after_request(response):
            timeout = app.config['DATABASE_QUERY_TIMEOUT']

            for query in get_debug_queries():
                if query.duration >= timeout:
                    app.logger.warning("SLOW QUERY: %s\nParameters: %s\nDuration: %fs\nContext: %s\n" % (
                    query.statement, query.parameters, query.duration, query.context))
            return response


    @user_logged_in.connect_via(app)
    def login_callback(self, user):
        # DS 3 Feb 2019 - why did we want to clear notifications?
        # disabled this for now

        # # clear notifications for the user who has just logged in
        # Notification.query.filter_by(user_id=user.id).delete()

        # force precompute of expensive views
        celery = current_app.extensions['celery']
        precompute_at_login(user, celery, autocommit=False)

        user.last_active = datetime.now()
        db.session.commit()


    from flask import Request
    class CustomRequest(Request):
        @property
        def rollbar_person(self):
            db.session.rollback()

            if current_user is None:
                return None

            # 'id' is required, 'username' and 'email' are indexed but optional.
            # all values are strings.
            return {'id': str(current_user.id),
                    'username': str(current_user.username),
                    'email': str(current_user.email)}

    app.request_class = CustomRequest


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

    from .reports import reports as reports_blueprint
    app.register_blueprint(reports_blueprint, url_prefix='/reports')

    from .user_approver import user_approver as user_approver_blueprint
    app.register_blueprint(user_approver_blueprint, url_prefix='/user_approver')

    from .project_approver import project_approver as project_approver_blueprint
    app.register_blueprint(project_approver_blueprint, url_prefix='/project_approver')

    from .loadbalancer import alb as alb_blueprint
    app.register_blueprint(alb_blueprint, url_prefix='/alb')

    return app, celery

