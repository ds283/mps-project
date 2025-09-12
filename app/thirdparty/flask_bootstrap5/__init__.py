# -*- coding: utf-8 -*-
"""
flask_bootstrap
~~~~~~~~~~~~~~
:copyright: (c) 2017 by Grey Li.
:license: MIT, see LICENSE for more details.
"""
from flask import current_app, Blueprint, url_for
from markupsafe import Markup

try:
    from wtforms.fields import HiddenField
except ImportError:

    def is_hidden_field_filter(field):
        raise RuntimeError("WTForms is not installed.")

else:

    def is_hidden_field_filter(field):
        return isinstance(field, HiddenField)


# central definition of used versions
VERSION_BOOTSTRAP = "5.2.3"
VERSION_JQUERY = "3.7.1"
VERSION_POPPER = "2.11.6"

BOOTSTRAP_JS_SHA = "sha384-kenU1KFdBIe4zVF0s0G1M5b4hcpxyD9F7jL+jjXkk+Q2h455rYXK/7HAuoJl+0I4"
BOOTSTRAP_CSS_SHA = "sha384-rbsA2VBKQhggwzxH7pPCaAqO46MgnOM80zW1RWuH61DGLwZJEdK2Kadq2F9CUG65"
POPPER_JS_SHA = "sha384-oBqDVmMz9ATKxIep9tiCxS/Z9fNfEXiDAYTujMAeBAsjFuCZSmKbSSUnQlmh/jp3"


def get_table_titles(data, primary_key, primary_key_title):
    """Detect and build the table titles tuple from ORM object, currently only support SQLAlchemy.

    .. versionadded:: 1.4.0
    """
    if not data:
        return []
    titles = []
    for k in data[0].__table__.columns._data.keys():
        if not k.startswith("_"):
            titles.append((k, k.replace("_", " ").title()))
    titles[0] = (primary_key, primary_key_title)
    return titles


class Bootstrap(object):
    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not hasattr(app, "extensions"):
            app.extensions = {}
        app.extensions["bootstrap"] = self

        blueprint = Blueprint(
            "bootstrap", __name__, template_folder="templates", static_folder="static", static_url_path="/bootstrap" + app.static_url_path
        )
        app.register_blueprint(blueprint)

        app.jinja_env.globals["bootstrap"] = self
        app.jinja_env.globals["bootstrap_is_hidden_field"] = is_hidden_field_filter
        app.jinja_env.globals["get_table_titles"] = get_table_titles
        app.jinja_env.add_extension("jinja2.ext.do")
        # default settings
        app.config.setdefault("BOOTSTRAP_BTN_STYLE", "secondary")
        app.config.setdefault("BOOTSTRAP_BTN_SIZE", "md")

    @staticmethod
    def load_css(version=VERSION_BOOTSTRAP):
        """Load Bootstrap's css resources with given version.

        .. versionadded:: 0.1.0

        :param version: The version of Bootstrap.
        """

        bootstrap_css_cdn_filename = "bootstrap.min.css"

        css = f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@{version}/dist/css/{bootstrap_css_cdn_filename}" type="text/css" integrity="{BOOTSTRAP_CSS_SHA}" crossorigin="anonymous">'
        return Markup(css)

    @staticmethod
    def load_js(version=VERSION_BOOTSTRAP, jquery_version=VERSION_JQUERY, popper_version=VERSION_POPPER, with_jquery=True, with_popper=True):
        """Load Bootstrap and related library's js resources with given version.

        .. versionadded:: 0.1.0

        :param version: The version of Bootstrap.
        :param jquery_version: The version of jQuery.
        :param popper_version: The version of Popper.js.
        :param with_jquery: Include jQuery or not.
        :param with_popper: Include Popper.js or not.
        """

        bootstrap_js_cdn_filename = "bootstrap.bundle.min.js"
        jquery_cdn_filename = "jquery.min.js"
        popper_cdn_filename = "popper.min.js"

        js = f'<script src="https://cdn.jsdelivr.net/npm/bootstrap@{version}/dist/js/{bootstrap_js_cdn_filename}" integrity="{BOOTSTRAP_JS_SHA}" crossorigin="anonymous"></script>'

        if with_jquery:
            jquery = f'<script src="https://cdn.jsdelivr.net/npm/jquery@{jquery_version}/dist/{jquery_cdn_filename}"></script>'
        else:
            jquery = ""

        if with_popper:
            popper = f'<script src="https://cdn.jsdelivr.net/npm/@popperjs/core@{popper_version}/dist/umd/{popper_cdn_filename}" integrity="{POPPER_JS_SHA}" crossorigin="anonymous"></script>'
        else:
            popper = ""
        return Markup(
            """%s
    %s
    %s"""
            % (jquery, popper, js)
        )
