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
