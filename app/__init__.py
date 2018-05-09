#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_security import SQLAlchemyUserDatastore, Security
from flask_bootstrap import Bootstrap
from flask_mail import Mail
from flask_assets import Environment

from config import app_config


# make db available as a static variable, so we can import into other parts of the code
db = SQLAlchemy()


def create_app(config_name):

    app = Flask(__name__, instance_relative_config=True)        # load configuration files from 'instance'
    app.config.from_object(app_config[config_name])
    app.config.from_pyfile('config.py')
    app.config.from_pyfile('mail.py')

    db.init_app(app)
    migrate = Migrate(app, db)
    bootstrap = Bootstrap(app)
    mail = Mail(app)

    # set up CSS and javascript assets
    env = Environment(app)

    from app import models

    user_datastore = SQLAlchemyUserDatastore(db, models.User, models.Role)
    security = Security(app, user_datastore)

    from .home import home as home_blueprint
    app.register_blueprint(home_blueprint)

    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from .admin import admin as admin_blueprint
    app.register_blueprint(admin_blueprint, url_prefix='/admin')

    return app
