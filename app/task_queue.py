#
# Created by David Seery on 25/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
# Adapted from: Flask design patterns, http://flask.pocoo.org/docs/0.12/patterns/celery/
#

from celery import Celery

from flask import current_app

from .models import db, User, EmailLog

from datetime import datetime


def make_celery(app):

    celery = Celery(app.import_name, backend=app.config['CELERY_RESULT_BACKEND'],
                    broker=app.config['CELERY_BROKER_URL'],
                    accept_content=app.config['CELERY_ACCEPT_CONTENT'],
                    beat_scheduler='app.sqlalchemy_scheduler:DatabaseScheduler')

    celery.conf.update(app.config)

    class ContextTask(celery.Task):

        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    return celery
