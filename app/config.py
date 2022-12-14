#
# Created by David Seery on 07/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os
from datetime import timedelta

from flask_security import uia_email_mapper
from bleach import clean


def uia_username_mapper(identity):
    # we allow pretty much anything - but we bleach it.
    return clean(identity, strip=True)


# get absolute path of the directory containing this file;
# used to locate a local database if we are using a backend
# for which this is relevant, eg. SQLite
basedir = os.path.abspath(os.path.dirname(__file__))


# website revision number
site_revision = '2022.3'

# website copyright dates
site_copyright_dates = '2018–2022'


class Config(object):
    """
    Common configuration options
    """
    SERVER_NAME = os.environ.get('SERVER_NAME') or None


    # SQLALCHEMY_DATABASE_URI is set in instance/secrets.py
    SQLALCHEMY_TRACK_MODIFICATIONS = False         # suppress notifications on database changes


    # CELERY_RESULT_BACKEND and CELERY_BROKER_URL are set in instance/secrets.py
    CELERY_ACCEPT_CONTENT = ['json', 'pickle']

    CELERY_CREATE_MISSING_QUEUES = True
    CELERY_DEFAULT_QUEUE = 'default'
    CELERY_ROUTES = {'app.task.ping.ping': {'queue': 'priority'}}


    # Configure maximum upload size
    MAX_CONTENT_LENGTH = 96*1024*1024


    # Flask-Security features
    SECURITY_CONFIRMABLE = True
    SECURITY_RECOVERABLE = True
    SECURITY_TRACKABLE = True
    SECURITY_CHANGEABLE = True
    SECURITY_REGISTERABLE = False

    SECURITY_PASSWORD_LENGTH_MIN = 8
    SECURITY_PASSWORD_COMPLEXITY_CHECKER = 'zxcvbn'
    SECURITY_PASSWORD_CHECK_BREACHED = True
    SECURITY_PASSWORD_BREACHED_COUNT = 1

    SECURITY_TOKEN_MAX_AGE = 10800    # tokens expire after 3 * 60 * 60 = 10,800 seconds = 3 hours

    SECURITY_PASSWORDLESS = False     # disable passwordless login

    SECURITY_EMAIL_HTML = False       # disable HTML emails

    SECURITY_USER_IDENTITY_ATTRIBUTES = [{"email": {"mapper": uia_email_mapper, "case_insensitive": True}},
                                         {"username'": {"mapper": uia_username_mapper}}]

    SECURITY_UNAUTHORIZED_VIEW = "home.homepage"


    # Flask-Sessionstore
    # SESSION_MONGO_URL is set in instance/secrets.py
    SESSION_TYPE = 'mongodb'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    SESSION_MONGODB_DB = 'flask_sessionstore'
    SESSION_MONGODB_COLLECT = 'sessions'
    SESSION_KEY_PREFIX = 'session:'


    # Flask-Caching

    # CACHE_REDIS_URL is set in instance/secrets.py
    CACHE_TYPE = 'redis'

    # default timeout = 86400 seconds = 24 hours
    CACHE_DEFAULT_TIMEOUT = 86400


    # logging
    LOG_FILE = os.environ.get('LOG_FILE') or 'logs/mps_project.log'


    # MPS-Project configuration
    BACKUP_FOLDER = os.environ.get('BACKUP_FOLDER') or 'backups'

    ASSETS_FOLDER = os.environ.get('ASSETS_FOLDER') or 'assets'

    ASSETS_GENERATED_SUBFOLDER = os.environ.get('ASSETS_GENERATED_SUBFOLDER') or 'generated'

    ASSETS_UPLOADED_SUBFOLDER = os.environ.get('ASSETS_UPLOADED_SUBFOLDER') or 'uploaded'

    ASSETS_SUBMITTED_SUBFOLDER = os.environ.get('ASSETS_SUBMITTED_SUBFOLDER') or 'submitted'
    ASSETS_REPORTS_SUBFOLDER = os.environ.get('ASSETS_REPORTS_SUBFOLDER') or 'reports'
    ASSETS_ATTACHMENTS_SUBFOLDER = os.environ.get('ASSETS_ATTACHMENTS_SUBFOLDER') or 'attachments'
    ASSETS_PERIODS_SUBFOLDER = os.environ.get('ASSETS_PERIODS_SUBFOLDER') or 'periods'



    # DEFAULT ASSET LICENSES
    FACULTY_DEFAULT_LICENSE = "Work"
    STUDENT_DEFAULT_LICENSE = "Exam"
    OFFICE_DEFAULT_LICENSE = "Work"


    # DATABASE_USER, DATABASE_PASSWORD, DATABASE_ROOT_PASSWORD and DATABASE_HOST are set in instance/secrets.py

    # Bleach configuration
    BLEACH_ALLOWED_TAGS = [
        'a',
        'abbr',
        'acronym',
        'b',
        'br',
        'blockquote',
        'code',
        'dd',
        'dt',
        'em',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'i',
        'img',
        'li',
        'ol',
        'p',
        'strong',
        'tt',
        'ul',
        'div',
        'span'
    ]

    BLEACH_ALLOWED_ATTRIBUTES = {
        '*': ['style'],
        'a': ['href', 'alt', 'title'],
        'abbr': ['title'],
        'acronym': ['title'],
        'div': ['class'],
        'img': ['src', 'alt', 'title'],
    }

    BLEACH_ALLOWED_STYLES = [
        'color',
        'font-weight'
    ]


    # user-facing defaults

    DEFAULT_PROJECT_CAPACITY = 2
    DEFAULT_ASSESSORS = 5

    DEFAULT_SIGN_OFF_STUDENTS = True
    DEFAULT_ENFORCE_CAPACITY = True
    DEFAULT_SHOW_POPULARITY = True
    DEFAULT_DONT_CLASH_PRESENTATIONS = True

    DEFAULT_USE_ACADEMIC_TITLE = True

    # delay between precompute cycles, measured in seconds
    PRECOMPUTE_DELAY = 1800


class DevelopmentConfig(Config):
    """
    Options used only during development
    """

    DEBUG = True                                # enable Flask debugger
    SQLALCHEMY_ECHO = False                     # disable SQLAlchemy logging (takes a long time to emit all queries)

    DEBUG_TB_PROFILER_ENABLED = False           # enable/disable profiling in the Flask debug toolbar
    DEBUG_API_PREFIX = ''                       # no special prefix for API (=Ajax) endpoints

    PROFILE_TO_DISK = False                     # determine whether to use Werkzeug profiler to write a .prof to disc
    PROFILE_DIRECTORY = "./profiling"           # location of profiling data

    # use Dozer to perform memory profiling?
    PROFILE_MEMORY = True


class ProductionConfig(Config):
    """
    Options used during production deployment
    """

    DEBUG = False

    # Flask-Limiter
    # RATELIMIT_STORAGE_URL is set in instance/secrets.py
    RATELIMIT_DEFAULT = "500/hour;120/minute"

    # our own, hand-rolled profiler:
    # determine whether to use Werkzeug profiler to write a .prof to disc
    # (from where we can use eg. SnakeViz as a GUI tool)
    PROFILE_TO_DISK = True
    PROFILE_DIRECTORY = os.environ.get('PROFILE_DIRECTORY') or "./profiling"

    # use Dozer to perform memory profiling?
    PROFILE_MEMORY = False

    # get SQLAlchemy to record metadata about query performance, so we can identify very slow queries
    SQLALCHEMY_RECORD_QUERIES = True

    # slow database query threshold (in seconds)
    # queries that take longer than this are logged
    DATABASE_QUERY_TIMEOUT = 0.5


app_config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}
