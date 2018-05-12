#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security import UserMixin, RoleMixin
from flask_sqlalchemy import SQLAlchemy

# make db available as a static variable, so we can import into other parts of the code
db = SQLAlchemy()


# length of database string for typical fields, if used
DEFAULT_STRING_LENGTH = 255

# length of database string used for IP addresses
IP_LENGTH = 60

# length of database string for a "year" column
YEAR_LENGTH = 4

# length of database string for password hash field, if used
PASSWORD_HASH_LENGTH = 255


class MainConfig(db.Model):
    """
    Main application configuration table; generally, there should only
    be one row giving the current configuration
    """
    year = db.Column(db.String(YEAR_LENGTH), primary_key=True)


# auxiliary table holding mapping from roles to users
roles_to_users = db.Table('roles_users',
                          db.Column('user_id', db.Integer(), db.ForeignKey('users.id'), primary_key=True),
                          db.Column('role_id', db.Integer(), db.ForeignKey('roles.id'), primary_key=True)
                          )


class Role(db.Model, RoleMixin):
    """
    Model a row from the roles table in the application database
    """

    # make table name plural
    __tablename__ = 'roles'

    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True)
    description = db.Column(db.String(DEFAULT_STRING_LENGTH))


class User(db.Model, UserMixin):
    """
    Model a row from the user table in the application database
    """

    # make table name plural
    __tablename__ = 'users'

    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True, unique=True)

    username = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True, unique=True)
    password = db.Column(db.String(PASSWORD_HASH_LENGTH))

    first_name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)
    last_name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

    active = db.Column(db.Boolean())

    confirmed_at = db.Column(db.DateTime())
    last_login_at = db.Column(db.DateTime())
    current_login_at = db.Column(db.DateTime())
    last_login_ip = db.Column(db.String(IP_LENGTH))
    current_login_ip = db.Column(db.String(IP_LENGTH))
    login_count = db.Column(db.Integer())

    roles = db.relationship('Role', secondary=roles_to_users,
                            backref=db.backref('users', lazy='dynamic'))
