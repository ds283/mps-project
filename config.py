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
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI') or \
        'sqlite:///' + os.path.join(basedir, 'MPS-Project.sqlite')

    SQLALCHEMY_TRACK_MODIFICATIONS = False         # suppress notifications on database changes

    # Flask-Security features
    SECURITY_CONFIRMABLE = True
    SECURITY_RECOVERABLE = True
    SECURITY_TRACKABLE = True
    SECURITY_CHANGEABLE = True
    SECURITY_REGISTERABLE = False

    SECURITY_USER_IDENTITY_ATTRIBUTES = ['email', 'username']


class DevelopmentConfig(Config):
    """
    Options used only during development
    """

    DEBUG = True                    # enable Flask debugger
    SQLALCHEMY_ECHO = True          # enable SQLAlchemy logging

    SECURITY_EMAIL_SUBJECT_REGISTER = False
    SECURITY_EMAIL_SUBJECT_PASSWORDLESS = False
    SECURITY_EMAIL_SUBJECT_PASSWORD_NOTICE = False
    SECURITY_EMAIL_SUBJECT_PASSWORD_RESET = False
    SECURITY_EMAIL_SUBJECT_PASSWORD_CHANGE_NOTICE = False
    SECURITY_EMAIL_SUBJECT_CONFIRM = False


class ProductionConfig(Config):
    """
    Options used during production deployment
    """

    DEBUG = False


app_config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}
