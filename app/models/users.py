#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from flask_security import AsaList, RoleMixin, UserMixin
from sqlalchemy import or_
from sqlalchemy.event import listens_for
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesGcmEngine

from ..database import db
from ..shared.sqlalchemy import get_count
from .associations import roles_to_users, mask_roles_to_users, tenant_to_users
from .choices import short_academic_titles_dict
from .config import get_AES_key
from .defaults import DEFAULT_STRING_LENGTH, IP_LENGTH, PASSWORD_HASH_LENGTH
from .model_mixins import ColouredLabelMixin


class Role(db.Model, RoleMixin, ColouredLabelMixin):
    """
    Model a row from the roles table in the application database
    """

    # make table name plural
    __tablename__ = "roles"

    # unique id
    id = db.Column(db.Integer(), primary_key=True)

    # role name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # role description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # permissions list
    permissions = db.Column(MutableList.as_mutable(AsaList()), nullable=True)

    def make_label(self, text=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """
        if text is None:
            text = self.name

        return self._make_label(text)


class User(db.Model, UserMixin):
    """
    Model a row from the user table in the application database
    """

    # make table name plural
    __tablename__ = "users"

    id = db.Column(db.Integer(), primary_key=True)

    # tenants to which this user belongs
    tenants = db.relationship(
        "Tenant",
        secondary=tenant_to_users,
        lazy="dynamic",
        backref=db.backref("users", lazy="dynamic"),
    )

    # primary email address
    email = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # username
    username = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # password
    password = db.Column(
        db.String(PASSWORD_HASH_LENGTH, collation="utf8_bin"), nullable=False
    )

    # first name
    first_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True
    )

    # last (family) name
    last_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True
    )

    # active flag
    active = db.Column(db.Boolean(), nullable=False)

    # FLASK-SECURITY USER MODEL: TRACKING FIELDS

    confirmed_at = db.Column(db.DateTime())

    last_login_at = db.Column(db.DateTime())

    current_login_at = db.Column(db.DateTime())

    last_login_ip = db.Column(db.String(IP_LENGTH))

    current_login_ip = db.Column(db.String(IP_LENGTH))

    login_count = db.Column(db.Integer())

    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False)

    fs_webauthn_user_handle = db.Column(db.String(64), unique=True, nullable=True)

    # ROLES

    # assigned roles
    roles = db.relationship(
        "Role", secondary=roles_to_users, backref=db.backref("users", lazy="dynamic")
    )

    # masked roles (currently available only to 'root' users)
    mask_roles = db.relationship("Role", secondary=mask_roles_to_users, lazy="dynamic")

    # EMAIL PREFERENCES

    # time last summary email was sent
    last_email = db.Column(db.DateTime(), default=None)

    # group email notifications into summaries?
    group_summaries = db.Column(db.Boolean(), default=True, nullable=False)

    # how frequently to send summaries, in days
    summary_frequency = db.Column(db.Integer(), default=1, nullable=False)

    # DEFAULT CONTENT LICENSE

    # default license id
    default_license_id = db.Column(
        db.Integer(), db.ForeignKey("asset_licenses.id", use_alter=True)
    )
    default_license = db.relationship(
        "AssetLicense",
        foreign_keys=[default_license_id],
        uselist=False,
        post_update=True,
        backref=db.backref("users", lazy="dynamic"),
    )

    # ONLINE SERVICE CREDENTIALS

    # Canvas LMS API access token; AesGcmEngine cannot be queried against,
    # but that is acceptable here because we never need to filter by token value.
    canvas_API_token = db.Column(
        EncryptedType(
            db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
            get_AES_key,
            AesGcmEngine,
            "pkcs5",
        ),
        default=None,
        nullable=True,
    )

    # Box OAuth2 access token; AesGcmEngine cannot be queried against,
    # but that is acceptable here because we never need to filter by token value.
    box_access_token = db.Column(
        EncryptedType(
            db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
            get_AES_key,
            AesGcmEngine,
            "pkcs5",
        ),
        default=None,
        nullable=True,
    )

    # Box OAuth2 refresh token; encrypted as above.
    box_refresh_token = db.Column(
        EncryptedType(
            db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
            get_AES_key,
            AesGcmEngine,
            "pkcs5",
        ),
        default=None,
        nullable=True,
    )

    # True if the Box refresh token is still valid (can be used to re-acquire the access token).
    box_token_valid = db.Column(db.Boolean(), default=False, nullable=False)

    # Timestamp of last Box token update.
    box_updated_at = db.Column(db.DateTime(), default=datetime.now, onupdate=datetime.now, nullable=True)

    # KEEP-ALIVE TRACKING

    # keep track of when this user was last active on the site
    last_active = db.Column(db.DateTime(), default=None)

    # override inherited has_role method
    def has_role(self, role, skip_mask=False):
        if not skip_mask:
            if isinstance(role, str):
                role_name = role
            elif isinstance(role, Role):
                role_name = role.name
            else:
                raise RuntimeError("Unknown role type passed to has_role()")

            if self.mask_roles.filter_by(name=role_name).first() is not None:
                return False

        return super().has_role(role)

    # check whether user has one of a list of roles
    def allow_roles(self, role_list):
        if not isinstance(role_list, Iterable):
            raise RuntimeError("Unknown role iterable passed to allow_roles()")

        # apply any using generator comprehension
        return any(self.has_role(r) for r in role_list)

    # build a name for this user
    @property
    def name(self):
        prefix = ""

        if self.faculty_data is not None and self.faculty_data.use_academic_title:
            try:
                value = short_academic_titles_dict[self.faculty_data.academic_title]
                prefix = value + " "
            except KeyError:
                pass

        return prefix + self.first_name + " " + self.last_name

    # build a simplified name without prefixes
    @property
    def simple_name(self):
        return self.first_name + " " + self.last_name

    @property
    def name_and_username(self):
        return self.name + " (" + self.username + ")"

    @property
    def active_label(self):
        if self.active:
            return {"label": "Active", "type": "success"}

        return {"label": "Inactive", "type": "secondary"}

    def post_task_update(self, uuid, payload, remove_on_load=False, autocommit=False):
        """
        Add a notification to this user
        :param payload:
        :return:
        """
        from .utilities import Notification

        # remove any previous notifications intended for this user with this uuid
        self.notifications.filter_by(uuid=uuid).delete()

        data = Notification(
            user_id=self.id,
            type=Notification.TASK_PROGRESS,
            uuid=uuid,
            payload=payload,
            remove_on_pageload=remove_on_load,
        )
        db.session.add(data)

        if autocommit:
            db.session.commit()

    CLASSES = {
        "success": "alert-success",
        "info": "alert-info",
        "warning": "alert-warning",
        "danger": "alert-danger",
        "error": "alert-danger",
    }

    def post_message(self, message, cls, remove_on_load=False, autocommit=False):
        """
        Add a notification to this user
        :param user_id:
        :param payload:
        :return:
        """
        from .utilities import Notification

        if cls in self.CLASSES:
            cls = self.CLASSES[cls]
        else:
            cls = None

        data = Notification(
            user_id=self.id,
            type=Notification.USER_MESSAGE,
            uuid=str(uuid4()),
            payload={"message": message, "type": cls},
            remove_on_pageload=remove_on_load,
        )
        db.session.add(data)

        if autocommit:
            db.session.commit()

    def send_showhide(self, html_id, action, autocommit=False):
        """
        Send a show/hide request for a specific HTML node
        :param html_id:
        :param action:
        :param autocommit:
        :return:
        """
        from .utilities import Notification

        data = Notification(
            user_id=self.id,
            type=Notification.SHOW_HIDE_REQUEST,
            uuid=str(uuid4()),
            payload={"html_id": html_id, "action": action},
            remove_on_pageload=False,
        )
        db.session.add(data)

        if autocommit:
            db.session.commit()

    def send_replacetext(self, html_id, new_text, autocommit=False):
        """
        Send an instruction to replace the text in a specific HTML node
        :param html_id:
        :param new_text:
        :param autocommit:
        :return:
        """
        from .utilities import Notification

        data = Notification(
            user_id=self.id,
            type=Notification.REPLACE_TEXT_REQUEST,
            uuid=str(uuid4()),
            payload={"html_id": html_id, "text": new_text},
            remove_on_pageload=False,
        )
        db.session.add(data)

        if autocommit:
            db.session.commit()

    def send_reload_request(self, autocommit=False):
        """
        Send an instruction to the user's web browser to reload the page
        :param html_id:
        :param new_text:
        :param autocommit:
        :return:
        """
        from .utilities import Notification

        data = Notification(
            user_id=self.id,
            type=Notification.RELOAD_PAGE_REQUEST,
            uuid=str(uuid4()),
            payload=None,
            remove_on_pageload=True,
        )
        db.session.add(data)

        if autocommit:
            db.session.commit()

    @property
    def currently_active(self):
        if self.last_active is None:
            return False

        now = datetime.now()
        delta = now - self.last_active

        # define 'active' to mean that we have received a ping within the last 2 minutes
        if delta.total_seconds() < 120:
            return True

        return False

    @property
    def unheld_email_notifications(self):
        from .utilities import EmailNotification

        return self.email_notifications.filter(
            or_(EmailNotification.held.is_(False), EmailNotification.held == None)
        ).order_by(EmailNotification.timestamp)

    @property
    def number_download_items(self) -> int:
        return get_count(self.download_centre_items)


@listens_for(User.roles, "remove")
def _User_role_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        if value in target.mask_roles:
            target.mask_roles.remove(value)
