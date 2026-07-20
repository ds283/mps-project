#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from ..database import db
from . import DEFAULT_STRING_LENGTH
from .config import get_AES_key
from .model_mixins import JournalEntryTypesMixin

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


class StudentJournalEntry(db.Model, JournalEntryTypesMixin):
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
    config_year = db.Column(db.Integer(), db.ForeignKey("main_config.year"), default=None, nullable=True)
    main_config = db.relationship(
        "MainConfig",
        foreign_keys=[config_year],
        uselist=False,
        backref=db.backref("journal_entries", lazy="dynamic"),
    )

    # Timestamp when the entry was created
    created_timestamp = db.Column(db.DateTime(), index=True, default=datetime.now)

    # Timestamp for the last edit
    last_edit_timestamp = db.Column(db.DateTime(), index=True, default=None, nullable=True)

    # The user who created this entry (nullable for auto-created entries)
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"), default=None, nullable=True)
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
    # see JournalEntryTypesMixin for the JOURNAL_TYPE_* constants and JOURNAL_TYPE_DISPLAY.
    entry_type = db.Column(db.Integer(), default=JournalEntryTypesMixin.JOURNAL_TYPE_NOTE, nullable=False)

    # Restricted entries are visible only to their owner and to convenors/admins
    # of the entry's linked project class(es); see is_visible_to() below.
    restricted = db.Column(db.Boolean(), default=False, nullable=False)

    @property
    def type_display(self) -> dict:
        """
        Icon/colour/label metadata for this entry's type.
        """
        return self.JOURNAL_TYPE_DISPLAY.get(self.entry_type, self.JOURNAL_TYPE_DISPLAY[self.JOURNAL_TYPE_NOTE])

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


def _convenor_visibility_scope(user, student_ids):
    """
    Resolve the "visible to `user`" scope for a set of candidate student ids, encoding
    the same visibility rule as StudentJournalEntry.is_visible_to() as bulk SQL.

    Returns (visibility_filter, scoped_student_ids):
      - scoped_student_ids: the subset of `student_ids` the user may see entries for at
        all (narrowed for admin/office by tenant; empty if the user has no access).
      - visibility_filter: an additional SQLAlchemy filter to apply on StudentJournalEntry
        (None for root/admin/office, where no further per-entry restriction applies).

    Shared by batch_journal_counts() and journal_activity_summary().
    """
    student_ids = list({sid for sid in student_ids if sid is not None})

    if not student_ids or user is None or not getattr(user, "is_authenticated", False):
        return None, []

    if user.has_role("root"):
        return None, student_ids

    if user.has_role("admin") or user.has_role("office"):
        from .associations import tenant_to_users
        from .students import StudentData
        from .users import User

        user_tenant_ids = [t.id for t in user.tenants]
        if not user_tenant_ids:
            return None, []

        student_ids = [
            sid
            for (sid,) in db.session.query(StudentData.id)
            .join(User, User.id == StudentData.id)
            .join(tenant_to_users, tenant_to_users.c.user_id == User.id)
            .filter(StudentData.id.in_(student_ids), tenant_to_users.c.tenant_id.in_(user_tenant_ids))
            .distinct()
            .all()
        ]
        return None, student_ids

    faculty_data = getattr(user, "faculty_data", None)
    if faculty_data is None or not faculty_data.is_convenor:
        return None, []

    convenor_pclass_ids = [pc.id for pc in faculty_data.convenor_list]

    restricted_visible_ids = db.session.query(journal_entry_to_pclass_config.c.entry_id)
    if convenor_pclass_ids:
        from .project_class import ProjectClassConfig

        restricted_visible_ids = restricted_visible_ids.join(
            ProjectClassConfig, ProjectClassConfig.id == journal_entry_to_pclass_config.c.config_id
        ).filter(ProjectClassConfig.pclass_id.in_(convenor_pclass_ids))
    else:
        restricted_visible_ids = restricted_visible_ids.filter(False)

    visibility = db.or_(
        StudentJournalEntry.restricted.is_(False),
        StudentJournalEntry.owner_id == user.id,
        StudentJournalEntry.id.in_(restricted_visible_ids),
    )
    return visibility, student_ids


def batch_journal_counts(user, student_ids) -> dict:
    """
    Batched equivalent of StudentData.journal_counts() for a set of students at once:
    two grouped queries cover the whole batch instead of a pair of per-student queries,
    for use by list views (e.g. the selectors table) that need a chip per row.

    Returns {student_id: {"visible": n, "unread": n}}, scoped to entries visible to
    `user`, encoding the same visibility rule as StudentData.visible_journal_entries().
    """
    requested_ids = list({sid for sid in student_ids if sid is not None})
    result = {sid: {"visible": 0, "unread": 0} for sid in requested_ids}

    visibility, scoped_ids = _convenor_visibility_scope(user, requested_ids)
    if not scoped_ids:
        return result

    entry = StudentJournalEntry

    def _counted(*extra_filters):
        query = db.session.query(entry.student_id, func.count(entry.id)).filter(entry.student_id.in_(scoped_ids), *extra_filters)
        if visibility is not None:
            query = query.filter(visibility)
        return query.group_by(entry.student_id).all()

    for sid, count in _counted():
        result[sid]["visible"] = count

    read_entry_ids = db.session.query(student_journal_entry_read.c.entry_id).filter(student_journal_entry_read.c.user_id == user.id)

    for sid, count in _counted(~entry.id.in_(read_entry_ids)):
        result[sid]["unread"] = count

    return result


def journal_activity_summary(user, student_ids, recent_days=30, recent_limit=3) -> dict:
    """
    Aggregate "visible to `user`" journal activity across a set of students, for compact
    dashboard summaries (e.g. the convenor overview "Journal activity" card, the Journal tab
    stat chips): total visible entries, unread count, count created within the last
    `recent_days`, count of auto-generated (ownerless) entries, and the most recent
    `recent_limit` visible entries. A single bounded set of count/limit queries, not a
    per-student loop.

    Returns {"visible": n, "unread": n, "recent": n, "auto": n, "recent_entries": [StudentJournalEntry, ...]}.
    """
    empty = {"visible": 0, "unread": 0, "recent": 0, "auto": 0, "recent_entries": []}

    visibility, scoped_ids = _convenor_visibility_scope(user, student_ids)
    if not scoped_ids:
        return empty

    entry = StudentJournalEntry
    base_query = db.session.query(entry).filter(entry.student_id.in_(scoped_ids))
    if visibility is not None:
        base_query = base_query.filter(visibility)

    visible_count = base_query.count()
    if visible_count == 0:
        return empty

    cutoff = datetime.now() - timedelta(days=recent_days)
    recent_count = base_query.filter(entry.created_timestamp >= cutoff).count()

    read_entry_ids = db.session.query(student_journal_entry_read.c.entry_id).filter(student_journal_entry_read.c.user_id == user.id)
    unread_count = base_query.filter(~entry.id.in_(read_entry_ids)).count()

    auto_count = base_query.filter(entry.owner_id.is_(None)).count()

    recent_entries = base_query.order_by(entry.created_timestamp.desc()).limit(recent_limit).all()

    return {
        "visible": visible_count,
        "unread": unread_count,
        "recent": recent_count,
        "auto": auto_count,
        "recent_entries": recent_entries,
    }


def journal_unread_count(user, student_ids) -> int:
    """
    Lightweight unread count across a set of students, scoped to entries visible to `user`.
    Used by the per-project-class nav pill badge, where only the count is needed —
    cheaper than journal_activity_summary(), which also computes visible/recent/auto.
    """
    visibility, scoped_ids = _convenor_visibility_scope(user, student_ids)
    if not scoped_ids:
        return 0

    entry = StudentJournalEntry
    query = db.session.query(entry.id).filter(entry.student_id.in_(scoped_ids))
    if visibility is not None:
        query = query.filter(visibility)

    read_entry_ids = db.session.query(student_journal_entry_read.c.entry_id).filter(student_journal_entry_read.c.user_id == user.id)
    return query.filter(~entry.id.in_(read_entry_ids)).count()


def visible_entries_query(user, student_ids):
    """
    Base query of StudentJournalEntry, filtered to entries visible to `user` across the
    given candidate student_ids. Unlike journal_activity_summary()/batch_journal_counts()
    (which only need counts), the Journal tab AJAX endpoint needs a query object it can
    layer further joins, filter chips and DataTables search/sort/pagination onto.
    """
    visibility, scoped_ids = _convenor_visibility_scope(user, student_ids)
    if not scoped_ids:
        return db.session.query(StudentJournalEntry).filter(False)

    query = db.session.query(StudentJournalEntry).filter(StudentJournalEntry.student_id.in_(scoped_ids))
    if visibility is not None:
        query = query.filter(visibility)

    return query
