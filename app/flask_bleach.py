# -*- coding: utf-8 -*-
"""Easy integration of bleach.

flaskext.bleach
~~~~~~~~~~~~~~~

bleach filter class for Flask.

:copyright: (c) 2014 by Dennis Fink. Update by David Seery for bleach 2.0
:license: BSD, see LICENSE for more details.

"""

from flask import Markup
from jinja2 import pass_eval_context

import bleach


class Bleach(object):

    """Easy integration of bleach.

    This class is used to control the bleach integration to one
    or more Flask applications. Depending on how you initialize the
    object it  is usable right away or will attach as needed to a
    Flask application.

    There are two usage modes which work very similiar. One is binding
    the instance to a very specific Flask application::

        app = Flask(name)
        bleach = Bleach(app)

    The second possibility is to create the object once and configure the
    application later to support it::

        bleach = Bleach()

        def create_app():
            app = Flask(__name__)
            bleach.init_app(app)
            return app

    """

    def __init__(self, app=None):

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        Configure an application.

        This registers two jinja2 filters, and attaches this `Bleach`
        to `app.extensions['bleach']`.

        :param app: The :class:`flask.Flask` object configure.
        :type app: :class:`flask.Flask`

        """

        self.app = app

        if not hasattr(self.app, 'extensions'):
            self.app.extensions = {}

        self.app.config.setdefault('BLEACH_ALLOWED_TAGS',
                                   bleach.ALLOWED_TAGS)
        self.app.config.setdefault('BLEACH_ALLOWED_ATTRIBUTES',
                                   bleach.ALLOWED_ATTRIBUTES)
        self.app.config.setdefault('BLEACH_ALLOWED_PROTOCOLS',
                                   bleach.ALLOWED_PROTOCOLS)
        self.app.config.setdefault('BLEACH_STRIP_MARKUP', False)
        self.app.config.setdefault('BLEACH_STRIP_COMMENTS', True)
        self.app.config.setdefault('BLEACH_AUTO_LINKIFY', False)
        self.app.config.setdefault('BLEACH_CLEAN_BEFORE_LINKIFY', False)
        self.app.config.setdefault('BLEACH_LINKIFY_SKIP_PRE', False)
        self.app.config.setdefault('BLEACH_LINKIFY_PARSE_EMAIL', False)

        self.app.extensions['bleach'] = self
        self.app.add_template_filter(self.__build_clean_filter(),
                                     name='bclean')
        self.app.add_template_filter(self.__build_linkify_filter(),
                                     name='blinkify')

    def __call__(self, stream):

        cleaned = self.clean(stream)

        if self.app.config['BLEACH_AUTO_LINKIFY']:
            cleaned = self.linkify(cleaned)

        return cleaned

    def __build_clean_filter(self):
        def bleach_filter(stream):
            return Markup(self(stream))
        return bleach_filter

    def __build_linkify_filter(self):
        def linkify_filter(stream):
            if self.app.config['BLEACH_CLEAN_BEFORE_LINKIFY']:
                stream = self.clean(stream)

            return Markup(self.linkify(stream))
        return linkify_filter

    def clean(self, stream):
        return bleach.clean(stream,
                            tags=self.app.config['BLEACH_ALLOWED_TAGS'],
                            attributes=self.app.config['BLEACH_ALLOWED_ATTRIBUTES'],
                            protocols=self.app.config['BLEACH_ALLOWED_PROTOCOLS'],
                            strip=self.app.config['BLEACH_STRIP_MARKUP'],
                            strip_comments=self.app.config['BLEACH_STRIP_COMMENTS']
                            )

    def linkify(self, stream):
        return bleach.linkify(stream,
                              parse_email=self.app.config['BLEACH_LINKIFY_PARSE_EMAIL']
                              )
