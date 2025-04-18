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
from datetime import datetime
from sys import stderr
from urllib import parse

import latex2markdown
import redis
from dozer import Dozer
from flask import Flask, g, make_response
from flask import current_app, request
from flask_assets import Environment
from flask_babel import Babel
from flask_debugtoolbar import DebugToolbarExtension
from flask_healthz import Healthz
from flask_login.signals import user_logged_in
from flask_mailman import Mail, EmailMultiAlternatives
from flask_migrate import Migrate
from flask_security import current_user, SQLAlchemyUserDatastore, Security, LoginForm, MailUtil
from flask_sqlalchemy.record_queries import get_recorded_queries
from pyinstrument import Profiler as PyInstrumentProfiler
from pymongo import MongoClient
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.profiler import ProfilerMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix

from .cache import cache
from .database import db
from .instance.version import site_revision, site_copyright_dates
from .limiter import limiter
from .models import User, MessageOfTheDay, Notification
from .shared.context.global_context import get_global_context_data, build_static_context_data, render_template_context
from .shared.utils import home_dashboard_url
from .task_queue import make_celery, register_task, background_task
from .thirdparty.flask_bleach import Bleach
from .thirdparty.flask_bootstrap5 import Bootstrap
from .thirdparty.flask_markdown import Markdown
from .thirdparty.flask_rollbar import Rollbar
from .thirdparty.flask_sessionstore import Session


class PatchedLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.email.description = "Your login name is your email address. Normally this will be your university @sussex.ac.uk address."


class PatchedMailUtil(MailUtil):
    # make Flask-Security use Celery deferred email sender
    def send_mail(self, template, subject, recipient, sender, body, html, user, **kwargs):
        # get send-log-email celery task
        celery = current_app.extensions["celery"]
        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

        msg = EmailMultiAlternatives(subject=subject, from_email=sender, to=[recipient], body=body)
        if html:
            msg.attach_alternative(html, "text/html")

        # register a new task in the database
        task_id = register_task(msg.subject, description="Email to {r}".format(r=", ".join(msg.to)))

        # queue Celery task to send the email
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)


def read_configuration(app: Flask, config_name: str):
    app.config.from_pyfile("flask.py")
    if config_name == "production":
        app.config.from_pyfile("flask_prod.py")
    elif config_name == "development":
        app.config.from_pyfile("flask_dev.py")

    app.config.from_pyfile("locations.py")
    app.config.from_pyfile("celery.py")
    app.config.from_pyfile("security.py")
    app.config.from_pyfile("sqlalchemy.py")
    app.config.from_pyfile("sessionstore.py")
    app.config.from_pyfile("caching.py")
    app.config.from_pyfile("logging.py")
    app.config.from_pyfile("healthz.py")
    app.config.from_pyfile("bleach.py")
    app.config.from_pyfile("rollbar.py")
    app.config.from_pyfile("ratelimit.py")
    app.config.from_pyfile("database.py")
    app.config.from_pyfile("defaults.py")
    app.config.from_pyfile("mail.py")
    app.config.from_pyfile("profiling.py")
    app.config.from_pyfile("config.py")

    app.config.from_pyfile("local.py")


def configure_logging(app: Flask):
    from logging import INFO, Formatter, basicConfig
    from logging.handlers import RotatingFileHandler

    basicConfig(level=INFO)

    log_file = app.config.get("LOG_FILE")
    if log_file is not None:
        file_handler = RotatingFileHandler(app.config["LOG_FILE"], "a", 1 * 1024 * 1024, 10)
        file_handler.setFormatter(Formatter("%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"))
        app.logger.setLevel(INFO)
        file_handler.setLevel(INFO)
        app.logger.addHandler(file_handler)


def create_app():
    # get current configuration, or default to 'production' for safety
    config_name = os.environ.get("FLASK_ENV") or "production"

    # load configuration files from 'instance' folder
    instance_folder = os.environ.get("INSTANCE_FOLDER")
    print(f'-- using instance folder "{instance_folder}"', file=stderr)
    app = Flask(__name__, instance_relative_config=True, instance_path=str(instance_folder))

    read_configuration(app, config_name)
    configure_logging(app)

    app_name = app.config.get("APP_NAME", "mpsprojects")
    app.logger.info(f"{app_name} projects management web app starting (version {site_revision})...")
    app.logger.info(f"Copyright University of Sussex {site_copyright_dates}")

    # create a long-lived Redis connection for Flask-Caching
    app.logger.info("-- creating Redis session for Flask-Caching")
    app.config["REDIS_SESSION"] = redis.Redis.from_url(url=app.config["CACHE_REDIS_URL"])

    # create long-lived Mongo connection for Flask-Sessionstore
    app.logger.info("-- creating MongoDB session for Flask-Sessionstore")
    app.config["SESSION_MONGODB"] = MongoClient(host=app.config["SESSION_MONGO_URL"])

    # we have two proxies -- we're behind both gunicorn and nginx
    proxyfix_for = app.config.get("PROXYFIX_FOR", 0)
    app.logger.info(f"-- patching Werkzeug to allow for {proxyfix_for}-level proxying")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxyfix_for)

    if app.config.get("PROFILE_MEMORY", False):
        app.wsgi_app = Dozer(app.wsgi_app)

    app.logger.info("-- intitializing SQLAlchemy ORM")
    db.init_app(app)

    app.logger.info("-- configuring application and Flask extensions")
    migrate = Migrate(app, db)
    bootstrap = Bootstrap(app)
    mail = Mail(app)
    bleach = Bleach(app)
    md = Markdown(app, extensions=["smarty"])
    rb = Rollbar(app)
    # qr = QRcode(app)
    bbl = Babel(app)
    healthz = Healthz(app)

    session_store = Session(app)

    cache.init_app(app)

    # set up CSS and javascript assets
    env = Environment(app)

    # use Werkzeug built-in profiler if profile-to-disk is enabled
    if app.config.get("PROFILE_TO_DISK", False):
        app.logger.info("-- configuring Werkzeug profiling")
        app.config["PROFILE"] = True

        profile_dir = app.config.get("PROFILE_DIRECTORY")
        restrictions = app.config.get("PROFILE_RESTRICTIONS")
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, profile_dir=profile_dir, restrictions=restrictions)

        app.logger.info("** Profiling to disk enabled (directory = {dir})".format(dir=profile_dir))

    # configure Flask-Security, which needs access to the database models for User and Role
    app.logger.info("-- importing ORM models")
    from app import models

    user_datastore = SQLAlchemyUserDatastore(db, models.User, models.Role)

    app.logger.info("-- patching Flask-Security-Too assets")
    # patch Flask-Security's login form to include some descriptive text on the email field
    security = Security(app, user_datastore, login_form=PatchedLoginForm, mail_util_cls=PatchedMailUtil)
    if config_name == "production":
        # set up more stringent limits for login view and forgot-password view
        # add to a particular view function.
        login = app.view_functions["security.login"]
        forgot = app.view_functions["security.forgot_password"]

        app.logger.info("-- setting Flask-Limiter default limits")
        limiter.limit("50/day;5/minute")(login)
        limiter.limit("50/day;5/minute")(forgot)

    # set up celery and store in extensions dictionary
    app.logger.info("-- initializing Celery and queues")
    celery = make_celery(app)
    app.extensions["celery"] = celery

    # register celery tasks
    # there doesn't seem a good way of doing this using factory functions! Here I compromise by passing the
    # celery application instance to a collection of register_*() functions, which use an @celery decorator
    # to register callables. Then we write the callable into the app, in the 'tasks' dictionary
    app.tasks = {}

    import app.tasks as tasks

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
    tasks.register_matching_email_tasks(celery)
    tasks.register_availability_tasks(celery)
    tasks.register_scheduling_tasks(celery)
    tasks.register_maintenance_tasks(celery)
    tasks.register_assessment_tasks(celery)
    tasks.register_assessor_tasks(celery)
    tasks.register_email_notification_tasks(celery)
    tasks.register_push_feedback_tasks(celery)
    tasks.register_system_tasks(celery)
    tasks.register_batch_create_tasks(celery)
    tasks.register_selecting_tasks(celery)
    tasks.register_session_tasks(celery)
    tasks.register_marking_tasks(celery)
    tasks.register_services_tasks(celery)
    tasks.register_process_report_tasks(celery)
    tasks.register_canvas_tasks(celery)
    tasks.register_background_tasks(celery)
    tasks.register_test_tasks(celery)
    tasks.register_cloud_api_audit_tasks(celery)

    use_pyinstrument = app.config.get("PROFILE_PYINSTRUMENT")
    if use_pyinstrument:
        app.logger.info("-- endpoint profiling using PyInstrument enabled")

    # cache static context data needed for rendering templates
    static_ctx = build_static_context_data(app)

    @security.login_context_processor
    def login_context_processor():
        # build list of system messages to consider displaying on login screen
        # we only include those labelled as "show_login"
        messages = []
        for message in (
                db.session.query(MessageOfTheDay)
                        .filter(MessageOfTheDay.show_login == True)
                        .order_by(MessageOfTheDay.issue_date.desc())
                        .all()
        ):
            if message.project_classes.first() is None:
                messages.append(message)

        return dict(messages=messages) | static_ctx

    @app.before_request
    def before_request_handler():
        if use_pyinstrument and "profile" in request.args:
            g.profiler = PyInstrumentProfiler()
            g.profiler.start()

        if current_user.is_authenticated:
            if request.endpoint is not None and "ajax" not in request.endpoint:
                try:
                    Notification.query.filter_by(remove_on_pageload=True).delete()
                    db.session.commit()
                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    if use_pyinstrument:

        @app.after_request
        def after_request_handler(response):
            if not hasattr(g, "profiler"):
                return response

            g.profiler.stop()
            output_html = g.profiler.output_html()
            return make_response(output_html)

    @app.template_filter("latextomarkdown")
    def latextomarkdown(latex_string):
        if latex_string is None:
            return r'<div class="alert alert-danger">An empty string was supplied. ' r"Please check your project description.</div>"

        l2m_obj = latex2markdown.LaTeX2Markdown(latex_string)
        return l2m_obj.to_markdown()

    @app.template_filter("urlencode")
    def urlencode_filter(s):
        if s is None:
            return None

        try:
            s = s.encode("utf8")
        except AttributeError as e:
            print("urlencode_filter: s = {s}".format(s=s))
            raise e

        s = parse.quote_plus(s)
        return bleach.clean(s)

    @app.template_filter("wrap_list")
    def wrap_list(s, prefix: str = "", suffix: str = ""):
        if prefix is None:
            prefix = ""
        if suffix is None:
            suffix = ""

        return [f"{prefix}{item}{suffix}" for item in s]

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template_context("errors/404.html"), 404

    @app.errorhandler(429)
    def rate_limit_error(error):
        return render_template_context("errors/429.html"), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template_context("errors/500.html"), 500

    if not app.debug:

        @app.after_request
        def after_request(response):
            timeout = app.config["DATABASE_QUERY_TIMEOUT"]

            for query in get_recorded_queries():
                if query.duration >= timeout:
                    app.logger.warning(
                        "SLOW QUERY: %s\nParameters: %s\nDuration: %fs\nLocation: %s\n"
                        % (query.statement, query.parameters, query.duration, query.location)
                    )
            return response

    @user_logged_in.connect_via(app)
    def login_callback(self, user):
        # DS 3 Feb 2019 - why did we want to clear notifications?
        # disabled this for now

        # # clear notifications for the user who has just logged in
        # Notification.query.filter_by(user_id=user.id).delete()

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
            return {"id": str(current_user.id), "username": str(current_user.username), "email": str(current_user.email)}

    app.request_class = CustomRequest

    # IMPORT BLUEPRINTS

    app.logger.info("-- importing Flask routes")

    from .home import home as home_blueprint

    app.register_blueprint(home_blueprint, url_prefix="/")

    from .auth import auth as auth_blueprint

    app.register_blueprint(auth_blueprint, url_prefix="/auth")

    from .admin import admin as admin_blueprint

    app.register_blueprint(admin_blueprint, url_prefix="/admin")

    from .faculty import faculty as faculty_blueprint

    app.register_blueprint(faculty_blueprint, url_prefix="/faculty")

    from .convenor import convenor as convenor_blueprint

    app.register_blueprint(convenor_blueprint, url_prefix="/convenor")

    from .student import student as student_blueprint

    app.register_blueprint(student_blueprint, url_prefix="/student")

    from .office import office as office_blueprint

    app.register_blueprint(office_blueprint, url_prefix="/office")

    from .reports import reports as reports_blueprint

    app.register_blueprint(reports_blueprint, url_prefix="/reports")

    from .user_approver import user_approver as user_approver_blueprint

    app.register_blueprint(user_approver_blueprint, url_prefix="/user_approver")

    from .project_approver import project_approver as project_approver_blueprint

    app.register_blueprint(project_approver_blueprint, url_prefix="/project_approver")

    from .manage_users import manage_users as manage_users_blueprint

    app.register_blueprint(manage_users_blueprint, url_prefix="/manage_users")

    from .documents import documents as documents_blueprint

    app.register_blueprint(documents_blueprint, url_prefix="/documents")

    from .services import services as services_blueprint

    app.register_blueprint(services_blueprint, url_prefix="/services")

    from .projecthub import projecthub as projecthub_blueprint

    app.register_blueprint(projecthub_blueprint, url_prefix="/projecthub")

    if app.config.get("ENABLE_PUBLIC_BROWSER", False):
        from .public_browser import public_browser as public_browser_blueprint

        app.register_blueprint(public_browser_blueprint, url_prefix="/public")

    # add endpoint profiler Flask-Profiler and rate limiter in production mode
    if config_name == "production":
        # set up Flask-Limiter
        limiter.init_app(app)

    # add debug toolbar if in debug mode
    if config_name == "development":
        toolbar = DebugToolbarExtension(app)
        # api_toolbar = DebugAPIExtension(app)

        # panels = list(app.config['DEBUG_TB_PANELS'])
        # panels.append('flask_debug_api.BrowseAPIPanel')
        # panels.append('flask_debugtoolbar_lineprofilerpanel.panels.LineProfilerPanel')
        # app.config['DEBUG_TB_PANELS'] = panels

    app.logger.info("** Initialization complete")

    return app
