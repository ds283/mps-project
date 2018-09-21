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
from redis import StrictRedis
from datetime import timedelta

# get absolute path of the directory containing this file;
# used to locate a local database if we are using a backend
# for which this is relevant, eg. SQLite
basedir = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    """
    Common configuration options
    """

    # read database URI from DATABASE_URI environment variable, or
    # else store locally in this directory
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'mysql+pymysql://mpsproject:Bridle12Way2007@localhost/mpsproject'
    SQLALCHEMY_TRACK_MODIFICATIONS = False         # suppress notifications on database changes

    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or 'redis://localhost:6379'
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379'
    CELERY_ACCEPT_CONTENT = ['json', 'pickle']

    # Flask-Security features
    SECURITY_CONFIRMABLE = True
    SECURITY_RECOVERABLE = True
    SECURITY_TRACKABLE = True
    SECURITY_CHANGEABLE = True
    SECURITY_REGISTERABLE = False

    SECURITY_PASSWORDLESS = False     # disable passwordless login

    SECURITY_EMAIL_HTML = False       # disable HTML emails

    SECURITY_USER_IDENTITY_ATTRIBUTES = ['email', 'username']

    SECURITY_UNAUTHORIZED_VIEW = "/"

    # Flask-KVSession
    SESSION_REDIS_URL = os.environ.get('SESSION_REDIS_URL') or 'redis://localhost:6379'
    SESSION_REDIS = StrictRedis.from_url(SESSION_REDIS_URL)

    SESSION_SET_TTL = True
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=4)      # sessions expire after 20 minutes

    # Flask-Caching
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL') or 'redis://localhost:6379'
    CACHE_DEFAULT_TIMEOUT = 86400                           # default timeout = 86400 seconds = 24 hours

    # Flask-Limiter
    RATELIMIT_DEFAULT = "600/day;120/hour"
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_REDIS_URL') or 'redis://localhost:6379'

    # logging
    LOG_FILE = os.environ.get('LOG_FILE') or 'logs/mps_project.log'

    # MPS-Project configuration
    BACKUP_FOLDER = os.environ.get('BACKUP_FOLDER') or 'backups'
    ASSETS_FOLDER = os.environ.get('ASSETS_FOLDER') or 'assets'

    DATABASE_USER = os.environ.get('DATABASE_USER') or 'mpsproject'
    DATABASE_PASSWORD = os.environ.get('DATABASE_PASSWORD') or None
    DATABASE_ROOT_PASSWORD = os.environ.get('DATABASE_ROOT_PASSWORD') or None
    DATABASE_HOSTNAME = os.environ.get('DATABASE_HOSTNAME') or 'localhost'

    DEFAULT_PROJECT_CAPACITY = 2
    DEFAULT_SECOND_MARKERS = 5

    DEFAULT_SIGN_OFF_STUDENTS = True
    DEFAULT_ENFORCE_CAPACITY = True
    DEFAULT_SHOW_POPULARITY = True

    DEFAULT_USE_ACADEMIC_TITLE = True


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


class ProductionConfig(Config):
    """
    Options used during production deployment
    """

    DEBUG = False

    # determine whether to use Werkzeug profiler to write a .prof to disc
    PROFILE_TO_DISK = False
    PROFILE_DIRECTORY = os.environ.get('PROFILE_DIRECTORY') or "./profiling"

    # get SQLAlchemy to record metadata about query performance, so we can identify very slow queries
    SQLALCHEMY_RECORD_QUERIES = True

    # slow database query threshold (in seconds)
    # queries that take longer than this are logged
    DATABASE_QUERY_TIMEOUT = 0.5


app_config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}
