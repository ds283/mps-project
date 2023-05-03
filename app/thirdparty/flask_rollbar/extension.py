# -*- coding: utf-8 -*-
"""
Flask-Rollbar
=============

Sets up a sane/reasonable Rollbar configuration for Flask apps, based
upon Rollbar's suggestions and personal experience.  Ignores some
400-level exceptions by default but can be customized.

Flask-Rollbar expects there to be two values defined on the Flask app's config:
``ROLLBAR_TOKEN`` and ``ROLLBAR_ENV``.  The ``ROLLBAR_TOKEN`` is your app's
server-side POST token, and the environment is the Rollbar environment to which
your events will be posted.  Flask-Rollbar defaults to an environment of "dev".

Here's a quick example of initializing this plugin:

    from flask import Flask
    from flask.ext.rollbar import Rollbar

    app = Flask(__name__)
    app.config['ROLLBAR_TOKEN'] = 'mytoken'
    app.config['ROLLBAR_ENV'] = 'testing'

    Rollbar(app)

    @app.route('/')
    def this_will_fail():
        1/0
"""
import os

import rollbar
from flask import got_request_exception
from rollbar.contrib.flask import report_exception
from werkzeug.exceptions import Unauthorized, Forbidden, NotFound, BadRequest


class Rollbar(object):
    def __init__(self, app=None,
                 ignore_exc=[BadRequest, Unauthorized, Forbidden, NotFound],
                 **kwargs):
        """ By default, it ignores the following Werkzeug exceptions:
        BadRequest (400), Unauthorized (401),  Forbidden (403), and
        NotFound(404).

        :param app: Flask app instance
        :param ignore_exc: Exception classes to prevent form being sent to
            Rollbar. By default, ignore 400, 401, 403, 404
        :param kwargs: Remaining keyword arguments to be passed directly into
        ``rollbar.init``.
        :return: None
        """
        self.app = app
        self.ignore_exc = ignore_exc
        self.init_kwargs = kwargs
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        app.extensions['rollbar'] = self
        ignored = [(exc, 'ignored') for exc in self.ignore_exc]
        rollbar.init(
            app.config['ROLLBAR_TOKEN'],
            environment=app.config.get('ROLLBAR_ENV', 'dev'),
            root=os.path.dirname(os.path.realpath(__file__)),
            allow_logging_basic_config=False,
            exception_level_filters=ignored,
            **self.init_kwargs
        )

        # send exceptions from `app` to rollbar using flask's signal system.
        got_request_exception.connect(report_exception)
