#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from ..database import db
from . import DEFAULT_STRING_LENGTH
from .config import get_AES_key

# Entry type codes
JOURNAL_TYPE_NOTE = 0
JOURNAL_TYPE_COMMUNICATION = 1
JOURNAL_TYPE_STATUS_CHANGE = 2
JOURNAL_TYPE_ENROLMENT = 3
JOURNAL_TYPE_DELETION = 4

# Icon + colour metadata for each entry type, keyed by the integer code above.
# 'colour' is the foreground/icon colour; 'background' is the subtle badge background.
JOURNAL_TYPE_DISPLAY = {
    JOURNAL_TYPE_NOTE: {
        "label": "Note",
        "icon": "fa-sticky-note",
        "colour": "#555a61",
        "background": "#e9ebee",
    },
    JOURNAL_TYPE_COMMUNICATION: {
        "label": "Communication",
        "icon": "fa-envelope",
        "colour": "#3f51d6",
        "background": "#e7ecff",
    },
    JOURNAL_TYPE_STATUS_CHANGE: {
        "label": "Status change",
        "icon": "fa-exchange-alt",
        "colour": "#b5730d",
        "background": "#fdeccf",
    },
    JOURNAL_TYPE_ENROLMENT: {
        "label": "Enrolment",
        "icon": "fa-user-plus",
        "colour": "#0b8794",
        "background": "#d8f3f5",
    },
    JOURNAL_TYPE_DELETION: {
        "label": "Deletion",
        "icon": "fa-trash",
        "colour": "#c23b2c",
        "background": "#fbe0dd",
    },
}

# Association table linking StudentJournalEntry to ProjectClassConfig (many-to-many)
journal_entry_to_pclass_config = db.Table(
    "journal_entry_to_pclass_config",
    db.Column(
        "entry_id",
        db.Integer(),
        db.ForeignKey("student_journal_entries.id"),
        primary_key=True,
    ),
    db.Column(
        "config_id",
        db.Integer(),
        db.ForeignKey("project_class_config.id"),
        primary_key=True,
    ),
)

# Association table recording which users have read which journal entries
student_journal_entry_read = db.Table(
    "student_journal_entry_read",
    db.Column(
        "entry_id",
        db.Integer(),
        db.ForeignKey("student_journal_entries.id"),
        primary_key=True,
    ),
    db.Column(
        "user_id",
        db.Integer(),
        db.ForeignKey("users.id"),
        primary_key=True,
    ),
    db.Column("read_timestamp", db.DateTime(), nullable=False, default=datetime.now),
)


class StudentJournalEntry(db.Model):
    """
    Records a single journal entry associated with a student.

    Each entry captures:
    - The student the entry relates to
    - The academic year (via MainConfig) at the time of creation
    - An optional link to the user who created the entry (null for auto-created entries)
    - An encrypted free-form HTML body
    - Optional links to one or more ProjectClassConfig instances
    """

    __tablename__ = "student_journal_entries"

    # Primary key
    id = db.Column(db.Integer(), primary_key=True)

    # The student this entry relates to
    student_id = db.Column(db.Integer(), db.ForeignKey("student_data.id"), index=True)
    student = db.relationship(
        "StudentData",
        foreign_keys=[student_id],
        uselist=False,
        backref=db.backref("journal_entries", lazy="dynamic"),
    )

    # Academic year at the time of creation, via MainConfig
    config_year = db.Column(
        db.Integer(), db.ForeignKey("main_config.year"), default=None, nullable=True
    )
    main_config = db.relationship(
        "MainConfig",
        foreign_keys=[config_year],
        uselist=False,
        backref=db.backref("journal_entries", lazy="dynamic"),
    )

    # Timestamp when the entry was created
    created_timestamp = db.Column(db.DateTime(), index=True, default=datetime.now)

    # Timestamp for the last edit
    last_edit_timestamp = db.Column(
        db.DateTime(), index=True, default=None, nullable=True
    )

    # The user who created this entry (nullable for auto-created entries)
    owner_id = db.Column(
        db.Integer(), db.ForeignKey("users.id"), default=None, nullable=True
    )
    owner = db.relationship(
        "User",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref("journal_entries", lazy="dynamic"),
    )

    # title for this journal entry
    title = db.Column(
        EncryptedType(
            db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
            get_AES_key,
            AesEngine,
            "oneandzeroes",
        ),
        default=None,
        nullable=True,
    )

    # Encrypted HTML body of the journal entry.
    # Uses AesEngine (the queryable but less secure variant) for consistency with exam_number in StudentData.
    entry = db.Column(
        EncryptedType(db.Text(), get_AES_key, AesEngine, "oneandzeroes"),
        default=None,
        nullable=True,
    )

    # Optional links to ProjectClassConfig instances (many-to-many)
    project_classes = db.relationship(
        "ProjectClassConfig",
        secondary=journal_entry_to_pclass_config,
        lazy="dynamic",
        backref=db.backref("journal_entries", lazy="dynamic"),
    )

    # Type of entry (note, communication, status change, enrolment, deletion) --
    # see JOURNAL_TYPE_* constants and JOURNAL_TYPE_DISPLAY above.
    entry_type = db.Column(db.Integer(), default=JOURNAL_TYPE_NOTE, nullable=False)

    # Restricted entries are visible only to their owner and to convenors/admins
    # of the entry's linked project class(es); see is_visible_to() below.
    restricted = db.Column(db.Boolean(), default=False, nullable=False)

    @property
    def type_display(self) -> dict:
        """
        Icon/colour/label metadata for this entry's type.
        """
        return JOURNAL_TYPE_DISPLAY.get(self.entry_type, JOURNAL_TYPE_DISPLAY[JOURNAL_TYPE_NOTE])

    @property
    def type_label(self) -> str:
        return self.type_display["label"]

    @property
    def type_icon(self) -> str:
        return self.type_display["icon"]

    @property
    def type_colour(self) -> str:
        return self.type_display["colour"]

    @property
    def type_background(self) -> str:
        return self.type_display["background"]

    def is_visible_to(self, user) -> bool:
        """
        Determine whether this entry is visible to `user`.

        Unrestricted entries are visible to any convenor/admin/root/office user who can
        see the student. Restricted entries are visible only to the owner and to
        convenors/admins of one of the entry's linked project class(es).
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return False

        if user.has_role("root"):
            return True

        if self.owner_id is not None and user.id == self.owner_id:
            return True

        if user.has_role("admin") or user.has_role("office"):
            student = self.student
            if student is not None and student.user is not None:
                student_tenant_ids = {t.id for t in student.user.tenants}
                user_tenant_ids = {t.id for t in user.tenants}
                if not student_tenant_ids.intersection(user_tenant_ids):
                    return False
            return True

        faculty_data = getattr(user, "faculty_data", None)
        if faculty_data is None or not faculty_data.is_convenor:
            return False

        if not self.restricted:
            return True

        pclasses = {pcc.project_class for pcc in self.project_classes if pcc.project_class is not None}
        if not pclasses:
            return False

        return any(faculty_data.is_convenor_for(pclass) for pclass in pclasses)

    def is_read_by(self, user) -> bool:
        if user is None or getattr(user, "id", None) is None:
            return False

        return (
            db.session.query(student_journal_entry_read)
            .filter(
                student_journal_entry_read.c.entry_id == self.id,
                student_journal_entry_read.c.user_id == user.id,
            )
            .first()
            is not None
        )

    def mark_read(self, user) -> None:
        if user is None or getattr(user, "id", None) is None:
            return

        if self.is_read_by(user):
            return

        db.session.execute(student_journal_entry_read.insert().values(entry_id=self.id, user_id=user.id, read_timestamp=datetime.now()))

    def mark_unread(self, user) -> None:
        if user is None or getattr(user, "id", None) is None:
            return

        db.session.execute(
            student_journal_entry_read.delete().where(
                db.and_(
                    student_journal_entry_read.c.entry_id == self.id,
                    student_journal_entry_read.c.user_id == user.id,
                )
            )
        )
