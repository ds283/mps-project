#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from datetime import datetime
from os import path
from time import time as current_seconds_since_epoch
from typing import TYPE_CHECKING
from urllib.parse import urljoin
from uuid import uuid4

if TYPE_CHECKING:
    from .faculty import EnrollmentRecord
    from .live_projects import LiveProject, MatchingRecord, SelectingStudent
    from .project_class import ProjectClassConfig

from flask import current_app
from sqlalchemy import and_, or_, orm
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import validates
from sqlalchemy.sql import func
from url_normalize import url_normalize

import app.shared.cloud_object_store.bucket_types as buckets
import app.shared.cloud_object_store.encryption_types as encryptions

from ..cache import cache
from ..database import db
from ..shared.formatters import format_size
from ..shared.sqlalchemy import get_count
from .associations import (
    backup_record_to_labels,
    convenor_group_filter_table,
    convenor_skill_filter_table,
    message_dismissals,
    pclass_message_associations,
    recipient_list,
)
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import (
    BackupTypesMixin,
    ColouredLabelMixin,
    EditingMetadataMixin,
    EmailNotificationsMixin,
    MatchingEnumerationTypesMixin,
    NotificationTypesMixin,
    RepeatIntervalsMixin,
    ScheduleEnumerationTypesMixin,
    TaskWorkflowStatesMixin,
)
from .users import User


class MainConfig(db.Model):
    """
    Main application configuration table; generally, there should only
    be one row giving the current configuration
    """

    # year is the main configuration variable
    year = db.Column(db.Integer(), primary_key=True)

    # URL for Canvas instance used to sync (if enabled)
    canvas_url = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # enable 2026 ATAS campaign landing page
    enable_2026_ATAS_campaign = db.Column(db.Boolean(), default=False)

    @validates("canvas_url")
    def _validate_canvas_url(self, key, value):
        self._canvas_root_API = None
        self._canvas_root_URL = None

        return value

    # globally enable Canvas sync
    enable_canvas_sync = db.Column(db.Boolean(), default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._canvas_root_API = None
        self._canvas_root_URL = None

    @orm.reconstructor
    def _reconstruct(self):
        self._canvas_root_API = None
        self._canvas_root_URL = None

    # get Canvas API root
    @property
    def canvas_root_API(self):
        if not self.enable_canvas_sync:
            return None

        if self._canvas_root_API is not None:
            return self._canvas_root_API

        API_url = urljoin(self.canvas_url, "api/v1/")
        self._canvas_root_API = url_normalize(API_url)

        return self._canvas_root_API

    # get Canvas URL root
    @property
    def canvas_root_URL(self):
        if not self.enable_canvas_sync:
            return None

        if self._canvas_root_URL is not None:
            return self._canvas_root_URL

        self._canvas_root_URL = url_normalize(self.canvas_url)

        return self._canvas_root_URL


class ConvenorTask(db.Model, EditingMetadataMixin):
    """
    Record a to-do item for the convenor. Derived classes represent specific types of task, eg.,
    associated with a specific selecting or submitting student, or a given project configuration
    """

    __tablename__ = "convenor_tasks"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # polymorphic identifier
    type = db.Column(db.Integer(), default=0, nullable=False)

    # task description
    description = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False
    )

    # task notes
    notes = db.Column(db.Text())

    # blocks movement to next lifecycle stage?
    blocking = db.Column(db.Boolean(), default=False)

    # completed?
    complete = db.Column(db.Boolean(), default=False)

    # dropped?
    dropped = db.Column(db.Boolean(), default=False)

    # defer date
    defer_date = db.Column(db.DateTime(), index=True)

    # due date
    due_date = db.Column(db.DateTime(), index=True)

    __mapper_args__ = {"polymorphic_identity": 0, "polymorphic_on": "type"}

    @property
    def is_overdue(self):
        if self.complete or self.dropped:
            return False

        if self.due_date is None:
            return False

        now = datetime.now()
        return self.due_date < now

    @property
    def is_available(self):
        if self.complete or self.dropped:
            return False

        if self.defer_date is None:
            return True

        now = datetime.now()
        return self.defer_date <= now


class ConvenorSelectorTask(ConvenorTask):
    """
    Derived from ConvenorTask. Represents a task record attached to a specific SelectingStudent
    """

    __tablename__ = "convenor_selector_tasks"

    # primary key links to base table
    id = db.Column(db.Integer(), db.ForeignKey("convenor_tasks.id"), primary_key=True)

    # owner SelectingStudent
    owner_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"))

    __mapper_args__ = {"polymorphic_identity": 1}


class ConvenorSubmitterTask(ConvenorTask):
    """
    Derived from ConvenorTask. Represents a task record attached to a specific SubmittingStudent
    """

    __tablename__ = "convenor_submitter_tasks"

    # primary key links to base table
    id = db.Column(db.Integer(), db.ForeignKey("convenor_tasks.id"), primary_key=True)

    # owner SelectingStudent
    owner_id = db.Column(db.Integer(), db.ForeignKey("submitting_students.id"))

    __mapper_args__ = {"polymorphic_identity": 2}


class ConvenorGenericTask(ConvenorTask, RepeatIntervalsMixin):
    """
    Derived from ConvenorTask. Represents a task record attached to a specific ProjectClassConfig
    """

    __tablename__ = "convenor_generic_tasks"

    # primary key links to base table
    id = db.Column(db.Integer(), db.ForeignKey("convenor_tasks.id"), primary_key=True)

    # owner SelectingStudent
    owner_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))

    # is this task repeating, ie. does it recur every year?
    repeat = db.Column(db.Boolean(), default=False)

    # repeat period
    repeat_options = [
        (RepeatIntervalsMixin.REPEAT_DAILY, "Daily"),
        (RepeatIntervalsMixin.REPEAT_MONTHLY, "Monthly"),
        (RepeatIntervalsMixin.REPEAT_YEARLY, "Yearly"),
    ]
    repeat_interval = db.Column(db.Integer(), default=RepeatIntervalsMixin.REPEAT_DAILY)

    # repeat frequency
    repeat_frequency = db.Column(db.Integer())

    # repeat from due date or real completion date?
    repeat_from_due_date = db.Column(db.Integer(), default=True)

    # roll over this task? ie., does this task repeat every cycle?
    rollover = db.Column(db.Boolean(), default=False)

    __mapper_args__ = {"polymorphic_identity": 3}


def ConvenorTasksMixinFactory(subclass):
    class ConvenorTasksMixin:
        @declared_attr
        def tasks(cls):
            return db.relationship(
                subclass.__name__,
                primaryjoin=lambda: subclass.owner_id == cls.id,
                lazy="dynamic",
                backref=db.backref("parent", uselist=False),
            )

        @property
        def available_tasks(self):
            return self.tasks.filter(
                ~subclass.complete,
                ~subclass.dropped,
                or_(
                    subclass.defer_date.is_(None),
                    and_(
                        subclass.defer_date.is_not(None),
                        subclass.defer_date <= func.curdate(),
                    ),
                ),
            )

        @property
        def overdue_tasks(self):
            return self.tasks.filter(
                ~subclass.complete,
                ~subclass.dropped,
                subclass.due_date.is_not(None),
                subclass.due_date < func.curdate(),
            )

        @property
        def number_tasks(self):
            return get_count(self.tasks)

        @property
        def number_available_tasks(self):
            # for a reason that isn't very clear, get_count() does not seem to work with the query
            # generated by self.available_tasks or self.overdue_tasks. Instead, the join turns into a
            # Cartesian product, which means that we get a meaningless figure from the count operation.
            # Instead, we have to use SQLAlchemy's plain .count() method
            # TODO: fix this later, if possible
            return self.available_tasks.count()

        @property
        def number_overdue_tasks(self):
            # for a reason that isn't very clear, get_count() does not seem to work with the query
            # generated by self.available_tasks or self.overdue_tasks. Instead, the join turns into a
            # Cartesian product, which means that we get a meaningless figure from the count operation.
            # Instead, we have to use SQLAlchemy's plain .count() method
            # TODO: fix this later, if possible
            return self.overdue_tasks.count()

        @staticmethod
        def TaskObjectFactory(**kwargs):
            return subclass(**kwargs)

        @staticmethod
        def polymorphic_identity():
            return subclass.__mapper_args__["polymorphic_identity"]

    return ConvenorTasksMixin


class EmailNotification(db.Model, EmailNotificationsMixin):
    """
    Represent an event for which the user should be notified by email
    """

    __tablename__ = "email_notifications"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # user to whom this notification applies
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    owner = db.relationship(
        "User",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "email_notifications", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # notification type
    event_type = db.Column(db.Integer())

    @property
    def event_label(self):
        if self.event_type in self._events:
            type, label = self._events[self.event_type]
            return {"label": label, "type": type}

        return {"label": "Unknown", "type": "danger"}

    # index
    # the meaning of these fields varies depending on the notification type
    # it's usually the primary key, but the record type associated with it varies
    data_1 = db.Column(db.Integer())
    data_2 = db.Column(db.Integer())

    # timestamp
    timestamp = db.Column(db.DateTime())

    # is this notification marked has held?
    held = db.Column(db.Boolean(), default=False)

    # set up dispatch table of methods to handle each notification type

    # dispatch table for __str__
    str_operations = {}

    # dispatch table for subject()
    subject_operations = {}

    # define utility decorator to insert into dispatch table
    def assign(table, key):
        def decorator(f):
            return table.setdefault(key, f)

        return decorator

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_REQUEST_CREATED)
    def _request_created(self):
        from .live_projects import ConfirmRequest

        req = db.session.query(ConfirmRequest).filter_by(id=self.data_1).first()
        if req is None:
            return "<missing database row>"

        return (
            '{student} requested a meeting confirmation for project "{proj}" ({pclass}, requested at '
            "{time}).".format(
                student=req.owner.student.user.name,
                proj=req.project.name,
                pclass=req.project.config.project_class.name,
                time=req.request_timestamp.strftime("%a %d %b %Y %H:%M:%S"),
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_REQUEST_CANCELLED)
    def _request_cancelled(self):
        from .live_projects import LiveProject

        user = db.session.query(User).filter_by(id=self.data_1).first()
        proj = db.session.query(LiveProject).filter_by(id=self.data_2).first()
        if user is None or proj is None:
            return "<missing database row>"

        return (
            "{student} cancelled their confirmation request for project "
            '"{proj}" ({pclass}).'.format(
                student=user.name, proj=proj.name, pclass=proj.config.project_class.name
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_REQUEST_DELETED)
    def _request_deleted(self):
        from .live_projects import LiveProject

        proj = db.session.query(LiveProject).filter_by(id=self.data_1).first()
        if proj is None:
            return "<missing database row>"

        return (
            "{supervisor} deleted your confirmation request for project "
            '"{proj}" (in {pclass}). If you were not expecting this to happen, please contact the supervisor '
            "directly.".format(
                supervisor=proj.owner.user.name,
                proj=proj.name,
                pclass=proj.config.project_class.name,
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_GRANT_DELETED)
    def _grant_deleted(self):
        from .live_projects import LiveProject

        proj = db.session.query(LiveProject).filter_by(id=self.data_1).first()
        if proj is None:
            return "<missing database row>"

        return (
            "{supervisor} removed your meeting confirmation for project "
            '"{proj}" (in {pclass}). If you were not expecting this to happen, please contact the supervisor '
            "directly.".format(
                supervisor=proj.owner.user.name,
                proj=proj.name,
                pclass=proj.config.project_class.name,
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_DECLINE_DELETED)
    def _decline_deleted(self):
        from .live_projects import LiveProject

        proj = db.session.query(LiveProject).filter_by(id=self.data_1).first()
        if proj is None:
            return "<missing database row>"

        return (
            "{supervisor} removed your declined request for meeting confirmation for project "
            '"{proj}" (in {pclass}). If you were not expecting this to happen, please contact the supervisor '
            "directly. Should you be interested in applying for this project, you are now able "
            "to generate a new confirmation request.".format(
                supervisor=proj.owner.user.name,
                proj=proj.name,
                pclass=proj.config.project_class.name,
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_GRANTED)
    def _request_granted(self):
        from .live_projects import ConfirmRequest

        req = db.session.query(ConfirmRequest).filter_by(id=self.data_1).first()
        if req is None:
            return "<missing database row>"

        return (
            "{supervisor} confirmed your request to sign-off on project "
            '"{proj}" (in {pclass}). If you are interested in applying for this project, you are now able '
            "to include it when submitting your list of ranked "
            "choices.".format(
                supervisor=req.project.owner.user.name,
                proj=req.project.name,
                pclass=req.project.config.project_class.name,
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_DECLINED)
    def _request_declined(self):
        from .live_projects import ConfirmRequest

        req = db.session.query(ConfirmRequest).filter_by(id=self.data_1).first()
        if req is None:
            return "<missing database row>"

        return (
            "{supervisor} declined your request to sign-off on project "
            '"{proj}" (in {pclass}). If you were not expecting this to happen, please contact the supervisor '
            "directly.".format(
                supervisor=req.project.owner.user.name,
                proj=req.project.name,
                pclass=req.project.config.project_class.name,
            )
        )

    @assign(str_operations, EmailNotificationsMixin.CONFIRMATION_TO_PENDING)
    def _request_to_pending(self):
        from .live_projects import ConfirmRequest

        req = db.session.query(ConfirmRequest).filter_by(id=self.data_1).first()
        if req is None:
            return "<missing database row>"

        return (
            "{supervisor} changed your meeting confirmation request for project "
            '"{proj}" (in {pclass}) to "pending". If you were not expecting this to happen, please contact the supervisor '
            "directly.".format(
                supervisor=req.project.owner.user.name,
                proj=req.project.name,
                pclass=req.project.config.project_class.name,
            )
        )

    @assign(str_operations, EmailNotificationsMixin.FACULTY_REENROLL_SUPERVISOR)
    def _request_reenroll_supervisor(self):
        from .faculty import EnrollmentRecord

        record = db.session.query(EnrollmentRecord).filter_by(id=self.data_1).first()
        if record is None:
            return "<missing database row>"

        return (
            'You have been automatically re-enrolled as a supervisor for the project class "{proj}". '
            "This has occurred because you previously had a buyout or sabbatical arrangement, "
            "but according to our records it is expected that you will become available for normal "
            "activities in the *next* academic year. If you wish to offer projects, "
            "you will need to do so in the next selection cycle.".format(
                proj=record.pclass.name
            )
        )

    @assign(str_operations, EmailNotificationsMixin.FACULTY_REENROLL_MARKER)
    def _request_reenroll_marker(self):
        from .faculty import EnrollmentRecord

        record = db.session.query(EnrollmentRecord).filter_by(id=self.data_1).first()
        if record is None:
            return "<missing database row>"

        return (
            'You have been automatically re-enrolled as a marker for the project class "{proj}". '
            "This has occurred because you previously had a buyout or sabbatical arrangement, "
            "but according to our records it is expected that you will become available for normal "
            "activities in the *next* academic year.".format(proj=record.pclass.name)
        )

    @assign(str_operations, EmailNotificationsMixin.FACULTY_REENROLL_MODERATOR)
    def _request_reenroll_moderator(self):
        from .faculty import EnrollmentRecord

        record = db.session.query(EnrollmentRecord).filter_by(id=self.data_1).first()
        if record is None:
            return "<missing database row>"

        return (
            'You have been automatically re-enrolled as a moderator for the project class "{proj}". '
            "This has occurred because you previously had a buyout or sabbatical arrangement, "
            "but according to our records it is expected that you will become available for normal "
            "activities in the *next* academic year.".format(proj=record.pclass.name)
        )

    @assign(str_operations, EmailNotificationsMixin.FACULTY_REENROLL_PRESENTATIONS)
    def _request_reenroll_presentations(self):
        from .faculty import EnrollmentRecord

        record = db.session.query(EnrollmentRecord).filter_by(id=self.data_1).first()
        if record is None:
            return "<missing database row>"

        return (
            'You have been automatically re-enrolled as a presentation assessor for the project class "{proj}". '
            "This has occurred because you previously had a buyout or sabbatical arrangement, "
            "but according to our records it is expected that you will become available for normal "
            "activities in the *next* academic year.".format(proj=record.pclass.name)
        )

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_REQUEST_CREATED)
    def _subj_request_created(self):
        return "New meeting confirmation request"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_REQUEST_CANCELLED)
    def _subj_request_cancelled(self):
        return "Meeting confirmation request cancelled"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_REQUEST_DELETED)
    def _subj_request_deleted(self):
        return "Meeting confirmation request deleted"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_GRANT_DELETED)
    def _subj_grant_deleted(self):
        return "Meeting confirmation deleted"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_DECLINE_DELETED)
    def _subj_decline_deleted(self):
        return "Declined meeting confirmation deleted"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_GRANTED)
    def _subj_granted(self):
        return "Meeting confirmation signed off"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_DECLINED)
    def _subj_declined(self):
        return "Meeting confirmation declined"

    @assign(subject_operations, EmailNotificationsMixin.CONFIRMATION_TO_PENDING)
    def _subj_to_pending(self):
        return 'Meeting confirmation changed to "pending"'

    @assign(subject_operations, EmailNotificationsMixin.FACULTY_REENROLL_SUPERVISOR)
    def _subj_reenroll_supervisor(self):
        return "You have been re-enrolled as a project supervisor"

    @assign(subject_operations, EmailNotificationsMixin.FACULTY_REENROLL_MARKER)
    def _subj_reenroll_marker(self):
        return "You have been re-enrolled as a marker"

    @assign(subject_operations, EmailNotificationsMixin.FACULTY_REENROLL_MODERATOR)
    def _subj_reenroll_marker(self):
        return "You have been re-enrolled as a moderator"

    @assign(subject_operations, EmailNotificationsMixin.FACULTY_REENROLL_PRESENTATIONS)
    def _subj_reenroll_presentations(self):
        return "You have been re-enrolled as a presentation assessor"

    def __str__(self):
        try:
            method = self.str_operations[self.event_type].__get__(self, type(self))
        except KeyError as k:
            assert self.event_type in self.str_operations, (
                "invalid notification type: " + repr(k)
            )
        return method()

    def msg_subject(self):
        try:
            method = self.subject_operations[self.event_type].__get__(self, type(self))
        except KeyError as k:
            assert self.event_type in self.subject_operations, (
                "invalid notification type: " + repr(k)
            )
        return method()


def _get_object_id(obj):
    if obj is None:
        return None

    if isinstance(obj, int):
        return obj

    return obj.id


def add_notification(
    user, event, object_1, object_2=None, autocommit=True, notification_id=None
):
    from .models import FacultyData, StudentData

    if (
        isinstance(user, User)
        or isinstance(user, FacultyData)
        or isinstance(user, StudentData)
    ):
        user_id = user.id
    else:
        user_id = user

    object_1_id = _get_object_id(object_1)
    object_2_id = _get_object_id(object_2)

    check_list = []

    # check whether we can collapse with any existing messages
    if event == EmailNotification.CONFIRMATION_REQUEST_CREATED:
        # object_1 = ConfirmRequest, object2 = None
        check_list.append(
            (
                EmailNotification.CONFIRMATION_REQUEST_CANCELLED,
                object_1.owner_id,
                object_1.project_id,
            )
        )

    if event == EmailNotification.CONFIRMATION_REQUEST_CANCELLED:
        # object_1 = SelectingStudent, object_2 = LiveProject
        # this one has to be done by hand; we want to search for an EmailNotification with the given particulars
        if notification_id is not None and isinstance(notification_id, int):
            check_list.append(
                (EmailNotification.CONFIRMATION_REQUEST_CREATED, notification_id, None)
            )

    if event == EmailNotification.CONFIRMATION_GRANT_DELETED:
        # object_1 = ConfirmRequest, object2 = None
        # this one has to be done by hand; we want to search for an EmailNotification with the given particulars
        if notification_id is not None and isinstance(notification_id, int):
            check_list.append(
                (EmailNotification.CONFIRMATION_GRANTED, notification_id, None)
            )

    if event == EmailNotification.CONFIRMATION_GRANTED:
        # object_1 = ConfirmRequest, object2 = None
        check_list.append(
            (EmailNotification.CONFIRMATION_GRANT_DELETED, object_1.project_id, None)
        )
        check_list.append(
            (EmailNotification.CONFIRMATION_TO_PENDING, object_1.project_id, None)
        )

    if event == EmailNotification.CONFIRMATION_DECLINE_DELETED:
        # object_1 = ConfirmRequest, object2 = None
        # this one has to be done by hand; we want to search for an EmailNotification with the given particulars
        if notification_id is not None and isinstance(notification_id, int):
            check_list.append(
                (EmailNotification.CONFIRMATION_DECLINED, notification_id, None)
            )

    if event == EmailNotification.CONFIRMATION_DECLINED:
        # object_1 = ConfirmRequest, object2 = None
        check_list.append(
            (EmailNotification.CONFIRMATION_DECLINE_DELETED, object_1.project_id, None)
        )

    if event == EmailNotification.CONFIRMATION_TO_PENDING:
        # object_1 = ConfirmRequest, object2 = None
        check_list.append(
            (EmailNotification.CONFIRMATION_GRANTED, object_1.project_id, None)
        )
        check_list.append(
            (EmailNotification.CONFIRMATION_DECLINED, object_1.project_id, None)
        )

    dont_save = False
    for t, obj1_id, obj2_id in check_list:
        q = db.session.query(EmailNotification).filter_by(
            owner_id=user_id, data_1=obj1_id, data_2=obj2_id, event_type=t
        )

        if get_count(q) > 0:
            q.delete()
            dont_save = True

    if dont_save:
        db.session.commit()
        return

    # check whether an existing message with the same content already exists
    q = db.session.query(EmailNotification).filter_by(
        owner_id=user_id, data_1=object_1_id, data_2=object_2_id, event_type=event
    )
    if get_count(q) > 0:
        return

    # insert new notification
    obj = EmailNotification(
        owner_id=user_id,
        data_1=object_1_id,
        data_2=object_2_id,
        event_type=event,
        timestamp=datetime.now(),
        held=False,
    )
    db.session.add(obj)

    # send immediately if we are not grouping notifications into summaries
    if isinstance(user, User):
        user_obj = user
    elif isinstance(user, (FacultyData, StudentData)):
        user_obj = user.user
    else:
        user_obj = db.session.query(User).filter_by(id=user_id).first()

    # trigger immediate send if notifications are not being grouped into summaries
    if user_obj is not None and not user_obj.group_summaries:
        celery = current_app.extensions["celery"]
        send_notify = celery.tasks["app.tasks.email_notifications.notify_user"]

        task_id = str(uuid4())

        data = TaskRecord(
            id=task_id,
            name="Generate notification email",
            owner_id=None,
            description="Automatically triggered notification email to {r}".format(
                r=user_obj.name
            ),
            start_date=datetime.now(),
            status=TaskRecord.PENDING,
            progress=None,
            message=None,
        )
        db.session.add(data)
        db.session.flush()

        # queue Celery task to send the email, deferred 10 seconds into the future to allow time for
        # all database records to be synced
        send_notify.apply_async(args=(task_id, user_id), task_id=task_id, countdown=10)

    if autocommit:
        db.session.commit()


def delete_notification(user, event, object_1, object_2=None):
    from .models import FacultyData, StudentData

    if (
        isinstance(user, User)
        or isinstance(user, FacultyData)
        or isinstance(user, StudentData)
    ):
        user_id = user.id
    else:
        user_id = user

    q = db.session.query(EmailNotification).filter_by(
        owner_id=user_id,
        data_1=object_1.id if object_1 is not None else None,
        data_2=object_2.id if object_2 is not None else None,
        event_type=event,
    )

    q.delete()
    db.session.commit()


class EmailLog(db.Model):
    """
    Model a logged email
    """

    __tablename__ = "email_log"

    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # list of recipients of this email
    recipients = db.relationship(
        "User",
        secondary=recipient_list,
        lazy="dynamic",
        backref=db.backref("received_emails", lazy="dynamic"),
    )

    # date of sending attempt
    send_date = db.Column(db.DateTime(), index=True)

    # subject
    subject = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # message body (text)
    body = db.Column(db.Text())

    # message body (HTML)
    html = db.Column(db.Text())


class MessageOfTheDay(db.Model):
    """
    Model a message broadcast to all users, or a specific subset of users
    """

    __tablename__ = "messages"

    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # id of issuing user
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    user = db.relationship(
        "User", uselist=False, backref=db.backref("messages", lazy="dynamic")
    )

    # date of issue
    issue_date = db.Column(db.DateTime(), index=True)

    # show to students?
    show_students = db.Column(db.Boolean())

    # show to faculty?
    show_faculty = db.Column(db.Boolean())

    # show to office/professional services?
    show_office = db.Column(db.Boolean())

    # display on login screen?
    show_login = db.Column(db.Boolean())

    # is this message dismissible?
    dismissible = db.Column(db.Boolean())

    # title
    title = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # message text
    body = db.Column(db.Text())

    # associate with which projects?
    project_classes = db.relationship(
        "ProjectClass",
        secondary=pclass_message_associations,
        lazy="dynamic",
        backref=db.backref("messages", lazy="dynamic"),
    )

    # which users have dismissed this message already?
    dismissed_by = db.relationship("User", secondary=message_dismissals, lazy="dynamic")


# class CloudAPIAuditRecord(db.Model):
#     """
#     Record a cloud API call: helps audit which calls are generating costs
#     """
#
#     __tablename__ = 'cloud_api_audit'
#
#     # primary key
#     id = db.Column(db.Integer(), primary_key=True)
#
#     # call type
#     type = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_general_ci'))
#
#     # audit details
#     data = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))
#
#     # driver name
#     driver = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))
#
#     # bucket name
#     bucket = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))
#
#     # host URI, if used
#     uri = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))
#
#     # timestamp
#     timestamp = db.Column(db.DateTime())


class BackupConfiguration(db.Model):
    """
    Set details of the current backup configuration
    """

    __tablename__ = "backup_config"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # how many days to keep hourly backups for
    keep_hourly = db.Column(db.Integer())

    # how many weeks to keep daily backups for
    keep_daily = db.Column(db.Integer())

    # backup limit
    limit = db.Column(db.Integer())

    # backup units
    KEY_MB = 1
    _UNIT_MB = 1024 * 1024

    KEY_GB = 2
    _UNIT_GB = _UNIT_MB * 1024

    KEY_TB = 3
    _UNIT_TB = _UNIT_GB * 1024

    unit_map = {KEY_MB: _UNIT_MB, KEY_GB: _UNIT_GB, KEY_TB: _UNIT_TB}
    units = db.Column(db.Integer(), nullable=False, default=1)

    # last changed
    last_changed = db.Column(db.DateTime())

    @property
    def backup_max(self):
        if self.limit is None or self.limit == 0:
            return None

        return self.limit * self.unit_map[self.units]


class BackupRecord(db.Model, BackupTypesMixin):
    """
    Keep details of a website backup
    """

    __tablename__ = "backups"

    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # ID of owner, the user who initiated this backup
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    owner = db.relationship("User", backref=db.backref("backups", lazy="dynamic"))

    # optional text description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # datestamp of backup
    date = db.Column(db.DateTime(), index=True)

    # backup type
    type = db.Column(db.Integer())

    # unique key, used to identify the payload for this backup within a bucket
    unique_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
        nullable=False,
        unique=True,
    )

    # uncompressed database size, in bytes
    db_size = db.Column(db.BigInteger())

    # compressed archive size, in bytes (before encryption, before compression into object store)
    archive_size = db.Column(db.BigInteger())

    # total size of backups at this time, in bytes
    # used only to plot historical trends
    # the actual value in here is unreliable, because intermediate backups may have been thinned
    backup_size = db.Column(db.BigInteger())

    # is this backup locked to prevent deletion?
    locked = db.Column(db.Boolean(), default=False)

    # should this record be auto-unlocked after a given date?
    # this prevents a build-up of un-deletable records
    unlock_date = db.Column(db.Date(), default=None)

    # last time this backup was validated in the object store
    last_validated = db.Column(db.DateTime())

    # applied labels
    labels = db.relationship(
        "BackupLabel",
        secondary=backup_record_to_labels,
        lazy="dynamic",
        backref=db.backref("backups", lazy="dynamic"),
    )

    # bucket associated with this asset
    bucket = db.Column(db.Integer(), nullable=False, default=buckets.BACKUP_BUCKET)

    # optional comment
    comment = db.Column(db.Text())

    # is this record encrypted?
    encryption = db.Column(
        db.Integer(), nullable=False, default=encryptions.ENCRYPTION_NONE
    )

    # file size after encryption
    encrypted_size = db.Column(db.Integer())

    # store nonce, if needed. Ensure it is marked as unique, both because it should be,
    # and also to generate an index (we need to check to ensure nonces are not reused)
    nonce = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=True, unique=True)

    # is this asset compressed?
    # note this is different to the question of whether the backup is stored in a compressed
    # .tar.gz (which it is, with the default implementation). This field is used by
    # AssetUploadManager and AssetCloudAdapter to decide whether transparent compression happens
    # when storing in an object store
    compressed = db.Column(db.Boolean(), nullable=False, default=False)

    # file size after asset compression
    compressed_size = db.Column(db.Integer())

    def type_to_string(self):
        if self.type in self._type_index:
            return self._type_index[self.type]

        return "<Unknown>"

    @property
    def print_filename(self):
        return path.join("...", path.basename(self.filename))

    @property
    def readable_db_size(self):
        return format_size(self.db_size) if self.db_size is not None else "<unset>"

    @property
    def readable_archive_size(self):
        return (
            format_size(self.archive_size)
            if self.archive_size is not None
            else "<unset>"
        )

    @property
    def readable_total_backup_size(self):
        return (
            format_size(self.backup_size) if self.backup_size is not None else "<unset>"
        )


class BackupLabel(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Represents a label applied to a backup
    """

    __tablename__ = "backup_labels"

    # unique identifier used as primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name of label
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    def make_label(self, text=None):
        label_text = text if text is not None else self.name
        return self._make_label(text=label_text)

    # backups property points back to backups that use this label


class TaskRecord(db.Model, TaskWorkflowStatesMixin):
    __tablename__ = "tasks"

    # unique identifier used by task queue
    id = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), primary_key=True
    )

    # task owner
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    owner = db.relationship(
        "User", uselist=False, backref=db.backref("tasks", lazy="dynamic")
    )

    # task launch date
    start_date = db.Column(db.DateTime())

    # task name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    # optional task description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # status flag
    status = db.Column(db.Integer())

    # percentage complete (if used)
    progress = db.Column(db.Integer())

    # progress message
    message = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))


class Notification(db.Model, NotificationTypesMixin):
    __tablename__ = "notifications"

    # unique id for this notificatgion
    id = db.Column(db.Integer(), primary_key=True)

    type = db.Column(db.Integer())

    # notifications are identified by the user they are intended for, plus a tag identifying
    # the source of the notification (eg. a task UUID)
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    user = db.relationship(
        "User", uselist=False, backref=db.backref("notifications", lazy="dynamic")
    )

    # uuid identifies a set of notifications (eg. task progress updates for the same task, or messages for the same subject)
    uuid = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    # timestamp
    timestamp = db.Column(db.Integer(), index=True, default=current_seconds_since_epoch)

    # should this notification be removed on the next page request?
    remove_on_pageload = db.Column(db.Boolean())

    # payload as a JSON-serialized string
    payload_json = db.Column(db.Text())

    @property
    def payload(self):
        return json.loads(str(self.payload_json))

    @payload.setter
    def payload(self, obj):
        self.payload_json = json.dumps(obj)


class PopularityRecord(db.Model):
    __tablename__ = "popularity_record"

    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # tag LiveProject to which this record applies
    liveproject_id = db.Column(
        db.Integer(), db.ForeignKey("live_projects.id"), index=True
    )
    liveproject = db.relationship(
        "LiveProject",
        uselist=False,
        backref=db.backref(
            "popularity_data", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # tag ProjectClassConfig to which this record applies
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        uselist=False,
        backref=db.backref(
            "popularity_data", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # date stamp for this calculation
    datestamp = db.Column(db.DateTime(), index=True)

    # UUID identifying all popularity records in a group
    uuid = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    # COMMON DATA

    # total number of LiveProjects included in ranking
    total_number = db.Column(db.Integer())

    # POPULARITY SCORE

    # popularity score
    score = db.Column(db.Integer())

    # rank on popularity score
    score_rank = db.Column(db.Integer())

    # track lowest rank so we have an estimate of whether the popularity score is meaningful
    lowest_score_rank = db.Column(db.Integer())

    # PAGE VIEWS

    # page views
    views = db.Column(db.Integer())

    # rank on page views
    views_rank = db.Column(db.Integer())

    # BOOKMARKS

    # number of bookmarks
    bookmarks = db.Column(db.Integer())

    # rank on bookmarks
    bookmarks_rank = db.Column(db.Integer())

    # SELECTIONS

    # number of selections
    selections = db.Column(db.Integer())

    # rank of number of selections
    selections_rank = db.Column(db.Integer())


class FilterRecord(db.Model):
    __tablename__ = "filters"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # tag with user_id to whom these filters are attached
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    user = db.relationship(User, foreign_keys=[user_id], uselist=False)

    # tag with ProjectClassConfig to which these filters are attached
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        foreign_keys=[config_id],
        uselist=False,
        backref=db.backref("filters", lazy="dynamic"),
    )

    # active research group filters
    group_filters = db.relationship(
        "ResearchGroup", secondary=convenor_group_filter_table, lazy="dynamic"
    )

    # active transferable skill group filters
    skill_filters = db.relationship(
        "TransferableSkill", secondary=convenor_skill_filter_table, lazy="dynamic"
    )


@cache.memoize()
def _MatchingAttempt_current_score(id):
    from .matching import MatchingAttempt

    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    if (
        obj.levelling_bias is None
        or obj.mean_CATS_per_project is None
        or obj.intra_group_tension is None
    ):
        return None

    # build objective function: this is the reward function that measures how well the student
    # allocations match their preferences; corresponds to
    #   objective += X[idx] * W[idx] / R[idx]
    # in app/tasks/matching.py
    scores = [x.current_score for x in obj.records]
    if None in scores:
        scores = [x for x in scores if x is not None]

    return sum(scores)


@cache.memoize()
def _MatchingAttempt_get_faculty_sup_CATS(id, fac_id, pclass_id):
    from .matching import MatchingAttempt

    # obtain MatchingAttempt
    obj: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).one()

    CATS = 0

    for item in obj.get_supervisor_records(fac_id).all():
        item: "MatchingRecord"
        proj: "LiveProject" = item.project
        selector: "SelectingStudent" = item.selector

        if pclass_id is None or selector.config.pclass_id == pclass_id:
            c = proj.CATS_supervision
            if c is not None:
                CATS += c

    return CATS


@cache.memoize()
def _MatchingAttempt_get_faculty_mark_CATS(id, fac_id, pclass_id):
    from .matching import MatchingAttempt

    # obtain MatchingAttempt
    obj: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).one()

    CATS = 0

    for item in obj.get_marker_records(fac_id).all():
        item: "MatchingRecord"
        proj: "LiveProject" = item.project
        selector: "SelectingStudent" = item.selector

        if pclass_id is None or selector.config.pclass_id == pclass_id:
            c = proj.CATS_marking
            if c is not None:
                CATS += c

    return CATS


@cache.memoize()
def _MatchingAttempt_get_faculty_mod_CATS(id, fac_id, pclass_id):
    from .matching import MatchingAttempt

    # obtain MatchingAttempt
    obj: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).one()

    CATS = 0

    for item in obj.get_moderator_records(fac_id).all():
        item: "MatchingRecord"
        proj: "LiveProject" = item.project
        selector: "SelectingStudent" = item.selector

        if pclass_id is None or selector.config.pclass_id == pclass_id:
            c = proj.CATS_moderation
            if c is not None:
                CATS += c

    return CATS


@cache.memoize()
def _MatchingAttempt_get_faculty_CATS(id, fac_id, pclass_id):
    CATS_sup = _MatchingAttempt_get_faculty_sup_CATS(id, fac_id, pclass_id)
    CATS_mark = _MatchingAttempt_get_faculty_mark_CATS(id, fac_id, pclass_id)
    CATS_mod = _MatchingAttempt_get_faculty_mod_CATS(id, fac_id, pclass_id)

    return CATS_sup, CATS_mark, CATS_mod


@cache.memoize()
def _MatchingAttempt_prefer_programme_status(id):
    from .matching import MatchingAttempt

    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    if obj.ignore_programme_prefs:
        return None

    matched = 0
    failed = 0

    for rec in obj.records:
        outcome = rec.project.satisfies_preferences(rec.selector)

        if outcome is None:
            continue

        if outcome:
            matched += 1
        else:
            failed += 1

    return matched, failed


@cache.memoize()
def _MatchingAttempt_hint_status(id):
    from .matching import MatchingAttempt

    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    if not obj.use_hints:
        return None

    satisfied = set()
    violated = set()

    for rec in obj.records:
        s, v = rec.hint_status

        satisfied = satisfied | s
        violated = violated | v

    return len(satisfied), len(violated)


@cache.memoize()
def _MatchingAttempt_number_project_assignments(id, project_id):
    from .matching import MatchingAttempt

    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    return get_count(obj.records.filter_by(project_id=project_id))


@cache.memoize()
def _MatchingAttempt_is_valid(id):
    from .matching import MatchingAttempt

    obj: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=id).one()

    # there are several steps:
    #   1. Validate that each MatchingRecord is valid (marker is not supervisor,
    #      LiveProject is attached to right class).
    #      These errors are fatal
    #   2. Validate that project capacity constraints are not violated.
    #      This is also a fatal error.
    #   3. Validate that faculty CATS limits are respected.
    #      This is a warning, not an error (sometimes supervisors have to take more
    #      students than we would like, but they do all have to be supervised somehow)
    errors = {}
    warnings = {}
    student_issues = False
    faculty_issues = False

    # IF MATCHING CALCULATION IS NOT FINISHED, NOTHING TO VALIDATE
    if not obj.finished:
        return True, student_issues, faculty_issues, errors, warnings

    # 1. EACH MATCHING RECORD SHOULD VALIDATE INDEPENDENTLY ACCORDING TO ITS OWN CRITERIA
    for record in obj.records:
        # check whether each matching record validates independently
        if not record.is_valid:
            record_errors = record.filter_errors(omit=["overassigned"])
            record_warnings = record.filter_warnings(omit=["overassigned"])

            if len(record_errors) == 0 and len(record_warnings) == 0:
                current_app.logger.info(
                    "** Internal inconsistency in response from _MatchingRecord_is_valid: "
                    "record_errors = {x}, record_warnings = {y}".format(
                        x=record_errors, y=record_warnings
                    )
                )

            for n, msg in enumerate(record_errors):
                errors[("basic", (record.id, n))] = "{name}/{abbv}: {msg}".format(
                    msg=msg,
                    name=record.selector.student.user.name,
                    abbv=record.selector.config.project_class.abbreviation,
                )

            for n, msg in enumerate(record_warnings):
                warnings[("basic", (record.id, n))] = "{name}/{abbv}: {msg}".format(
                    msg=msg,
                    name=record.selector.student.user.name,
                    abbv=record.selector.config.project_class.abbreviation,
                )

            if len(record_errors) > 0:
                student_issues = True

    # 2. EACH PARTICIPATING FACULTY MEMBER SHOULD NOT BE OVERASSIGNED, EITHER AS MARKER OR SUPERVISOR
    query = obj.faculty_list_query()
    for fac in query.all():
        data = obj.is_supervisor_overassigned(fac, include_matches=True)
        if data["flag"]:
            errors[("supervising", fac.id)] = data["error_message"]
            faculty_issues = True

        data = obj.is_marker_overassigned(fac, include_matches=True)
        if data["flag"]:
            errors[("marking", fac.id)] = data["error_message"]
            faculty_issues = True

        # 4. FOR EACH INCLUDED PROJECT CLASS, FACULTY ASSIGNMENTS SHOULD RESPECT ANY CUSTOM CATS LIMITS
        for config in obj.config_members:
            config: "ProjectClassConfig"
            rec: "EnrollmentRecord" = fac.get_enrollment_record(config.pclass_id)

            if rec is not None:
                sup, mark, mod = obj.get_faculty_CATS(fac, pclass_id=config.pclass_id)

                if rec.CATS_supervision is not None and sup > rec.CATS_supervision:
                    errors[("custom_sup", fac.id)] = (
                        "{pclass} assignment to {name} violates their custom supervising CATS limit"
                        " = {n}".format(
                            pclass=config.name,
                            name=fac.user.name,
                            n=rec.CATS_supervision,
                        )
                    )
                    faculty_issues = True

                if rec.CATS_marking is not None and mark > rec.CATS_marking:
                    errors[("custom_mark", fac.id)] = (
                        "{pclass} assignment to {name} violates their custom marking CATS limit"
                        " = {n}".format(
                            pclass=config.name, name=fac.user.name, n=rec.CATS_marking
                        )
                    )
                    faculty_issues = True

                # UPDATE MODERATE CATS

    is_valid = (not student_issues) and (not faculty_issues)

    if not is_valid and len(errors) == 0:
        current_app.logger.info(
            "** Internal inconsistency in _MatchingAttempt_is_valid: not valid, but len(errors) == 0"
        )

    return is_valid, student_issues, faculty_issues, errors, warnings


class ScheduleEnumeration(db.Model, ScheduleEnumerationTypesMixin):
    """
    Record mapping of record ids to enumeration values used in scheduling
    """

    __tablename__ = "schedule_enumerations"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # enumeration type
    category = db.Column(db.Integer())

    # enumerated value
    enumeration = db.Column(db.Integer())

    # key value
    key = db.Column(db.Integer())

    # schedule identifier
    schedule_id = db.Column(db.Integer(), db.ForeignKey("scheduling_attempts.id"))
    schedule = db.relationship(
        "ScheduleAttempt",
        foreign_keys=[schedule_id],
        uselist=False,
        backref=db.backref(
            "enumerations", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )


class MatchingEnumeration(db.Model, MatchingEnumerationTypesMixin):
    """
    Record mapping of record ids to enumeration values used in matching
    """

    __tablename__ = "matching_enumerations"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # enumeration type
    category = db.Column(db.Integer())

    # enumerated value
    enumeration = db.Column(db.Integer())

    # key value
    key = db.Column(db.Integer())

    # 2nd key value (used for storing per-ProjectClass CATS limits
    key2 = db.Column(db.Integer())

    # matching attempt
    matching_id = db.Column(db.Integer(), db.ForeignKey("matching_attempts.id"))
    matching = db.relationship(
        "MatchingAttempt",
        foreign_keys=[matching_id],
        uselist=False,
        backref=db.backref(
            "enumerations", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )
