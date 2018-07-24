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

    # MPS-Project configuration
    BACKUP_FOLDER = os.environ.get('BACKUP_FOLDER') or 'backups'
    ASSETS_FOLDER = os.environ.get('ASSETS_FOLDER') or 'assets'

    DATABASE_USER = os.environ.get('DATABASE_USER') or 'mpsproject'
    DATABASE_PASSWORD = os.environ.get('DATABASE_PASSWORD') or None
    DATABASE_ROOT_PASSWORD = os.environ.get('DATABASE_ROOT_PASSWORD') or None
    DATABASE_HOSTNAME = os.environ.get('DATABASE_HOSTNAME') or 'localhost'

    DEFAULT_PROJECT_CAPACITY = 2


class DevelopmentConfig(Config):
    """
    Options used only during development
    """

    DEBUG = True                    # enable Flask debugger
    SQLALCHEMY_ECHO = True          # enable SQLAlchemy logging


class ProductionConfig(Config):
    """
    Options used during production deployment
    """

    DEBUG = False


app_config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}
