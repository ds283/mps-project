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

# get absolute path of the directory containing this file;
# used to locate a local database if we are using a backend
# for which this is relevant, eg. SQLite
basedir = os.path.abspath(os.path.dirname(__file__))


# website revision number
site_revision = '2019.1'

# website copyright dates
site_copyright_dates = '2018, 2019'


class Config(object):
    """
    Common configuration options
    """
    SERVER_NAME = os.environ.get('SERVER_NAME') or None


    # SQLALCHEMY_DATABASE_URI is set in instance/secrets.py
    SQLALCHEMY_TRACK_MODIFICATIONS = False         # suppress notifications on database changes


    # CELERY_RESULT_BACKEND and CELERY_BROKER_URL are set in instance/secrets.py
    CELERY_ACCEPT_CONTENT = ['json', 'pickle']


    # Flask-Security features
    SECURITY_CONFIRMABLE = True
    SECURITY_RECOVERABLE = True
    SECURITY_TRACKABLE = True
    SECURITY_CHANGEABLE = True
    SECURITY_REGISTERABLE = False

    SECURITY_TOKEN_MAX_AGE = 10800    # tokens expire after 3 * 60 * 60 = 10,800 seconds = 3 hours

    SECURITY_PASSWORDLESS = False     # disable passwordless login

    SECURITY_EMAIL_HTML = False       # disable HTML emails

    SECURITY_USER_IDENTITY_ATTRIBUTES = ['email', 'username']

    SECURITY_UNAUTHORIZED_VIEW = "home.homepage"


    # Flask-Sessionstore
    # SESSION_MONGO_URL is set in instance/secrets.py
    SESSION_TYPE = 'mongodb'
    SESSION_PERMANENT = False


    # Flask-Caching
    # CACHE_REDIS_URL is set in instance/secrets.py
    CACHE_TYPE = 'redis'
    CACHE_DEFAULT_TIMEOUT = 86400                           # default timeout = 86400 seconds = 24 hours


    # logging
    LOG_FILE = os.environ.get('LOG_FILE') or 'logs/mps_project.log'


    # MPS-Project configuration
    BACKUP_FOLDER = os.environ.get('BACKUP_FOLDER') or 'backups'
    ASSETS_FOLDER = os.environ.get('ASSETS_FOLDER') or 'assets'
    ASSETS_GENERATED_SUBFOLDER = os.environ.get('ASSETS_GENERATED_SUBFOLDER') or 'generated'
    ASSETS_UPLOADED_SUBFOLDER = os.environ.get('ASSETS_UPLOADED_SUBFOLDER') or 'uploaded'

    # DATABASE_USER, DATABASE_PASSWORD, DATABASE_ROOT_PASSWORD and DATABASE_HOST are set in instance/secrets.py

    # Bleach configuration
    BLEACH_ALLOWED_TAGS = [
        'a',
        'abbr',
        'acronym',
        'b',
        'blockquote',
        'code',
        'em',
        'i',
        'li',
        'ol',
        'strong',
        'ul',
        'div',
        'span'
    ]

    BLEACH_ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title'],
        'abbr': ['title'],
        'acronym': ['title'],
        'div': ['class']
    }


    # user-facing defaults

    DEFAULT_PROJECT_CAPACITY = 2
    DEFAULT_ASSESSORS = 5

    DEFAULT_SIGN_OFF_STUDENTS = True
    DEFAULT_ENFORCE_CAPACITY = True
    DEFAULT_SHOW_POPULARITY = True
    DEFAULT_DONT_CLASH_PRESENTATIONS = True

    DEFAULT_USE_ACADEMIC_TITLE = True

    # measured in seconds; should match delay used in scheduled job
    PRECOMPUTE_DELAY = 600


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
    RATELIMIT_DEFAULT = "600/day;120/hour"

    # our own, hand-rolled profiler:
    # determine whether to use Werkzeug profiler to write a .prof to disc
    # (from where we can use eg. SnakeViz as a GUI tool)
    PROFILE_TO_DISK = False
    PROFILE_DIRECTORY = os.environ.get('PROFILE_DIRECTORY') or "./profiling"

    # use Dozer to perform memory profiling?
    PROFILE_MEMORY = True

    # get SQLAlchemy to record metadata about query performance, so we can identify very slow queries
    SQLALCHEMY_RECORD_QUERIES = True

    # slow database query threshold (in seconds)
    # queries that take longer than this are logged
    DATABASE_QUERY_TIMEOUT = 0.5


app_config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}
