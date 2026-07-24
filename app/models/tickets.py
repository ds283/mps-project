#
# Created by David Seery on 21/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from ..database import db
from .config import get_AES_key
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin


# ############################
# INT-CONSTANT MIXINS
#
# The project convention (see app/models/model_mixins.py) is to model discrete states as integer
# constants carried on a namespace mixin, together with a _labels map, rather than Python or DB
# enums. The ticket system follows the same pattern.


class TicketWorkflowStatesMixin:
    """
    Ticket lifecycle: open -> in_progress -> resolved -> closed. The transition graph is linear
    but any transition is permitted (each recorded as a TicketEvent). resolved = fixed, awaiting
    confirmation; closed = done/won't-do and drops out of the default "open" views.
    """

    OPEN = 0
    IN_PROGRESS = 1
    RESOLVED = 2
    CLOSED = 3

    _labels = {
        OPEN: "Open",
        IN_PROGRESS: "In progress",
        RESOLVED: "Resolved",
        CLOSED: "Closed",
    }

    # statuses that count as "still needing attention" for the default open views
    OPEN_STATES = (OPEN, IN_PROGRESS, RESOLVED)


class TicketSubjectKindMixin:
    """
    The polymorphic target kind of a TicketSubject. Exactly one of the three FK columns on
    TicketSubject is non-null, matching the kind (enforced by a DB check constraint).
    """

    SUBMITTING_STUDENT = 0
    SELECTING_STUDENT = 1
    PROJECT_CLASS = 2

    _labels = {
        SUBMITTING_STUDENT: "Submitting student",
        SELECTING_STUDENT: "Selecting student",
        PROJECT_CLASS: "Project class",
    }


class TicketEventKindMixin:
    """
    Append-only audit event kinds. payload_json carries the before/after detail
    (e.g. {"from": 0, "to": 1} for a status change, or {"from": <id>, "to": <id>} for reassignment).
    """

    OPENED = 0
    STATUS_CHANGED = 1
    ASSIGNED = 2
    UNASSIGNED = 3
    LABEL_ADDED = 4
    LABEL_REMOVED = 5
    SUBSCRIBED = 6
    UNSUBSCRIBED = 7
    COMMENT_ADDED = 8
    EMAIL_LOGGED = 9
    SUBJECT_ADDED = 10
    SUBJECT_REMOVED = 11
    SUBJECT_TOMBSTONED = 12
    TITLE_CHANGED = 13

    _labels = {
        OPENED: "Opened",
        STATUS_CHANGED: "Status changed",
        ASSIGNED: "Assigned",
        UNASSIGNED: "Unassigned",
        LABEL_ADDED: "Label added",
        LABEL_REMOVED: "Label removed",
        SUBSCRIBED: "Subscribed",
        UNSUBSCRIBED: "Unsubscribed",
        COMMENT_ADDED: "Comment added",
        EMAIL_LOGGED: "Email logged",
        SUBJECT_ADDED: "Subject added",
        SUBJECT_REMOVED: "Subject removed",
        SUBJECT_TOMBSTONED: "Subject link deleted",
        TITLE_CHANGED: "Title changed",
    }


class TicketEmailDirectionMixin:
    """
    Direction of a logged email. There is currently no inbound-email path (no readable mailbox);
    TicketEmail is used for outbound sends and manually-logged mail. INBOUND is reserved for a
    future feature.
    """

    INBOUND = 0
    OUTBOUND = 1

    _labels = {
        INBOUND: "Inbound",
        OUTBOUND: "Outbound",
    }


class TicketSubscriptionReasonMixin:
    """
    Why a user is subscribed (watching) a ticket. Drives the "Watching" view and email fan-out.
    """

    OPENER = 0
    ASSIGNEE = 1
    MANUAL = 2
    CONVENOR = 3

    _labels = {
        OPENER: "Opener",
        ASSIGNEE: "Assignee",
        MANUAL: "Manual",
        CONVENOR: "Convenor",
    }


# ############################
# ASSOCIATION TABLES

# derived class scope, cached and refreshed on subject change (see Phase 2 service layer)
ticket_class_scope = db.Table(
    "ticket_class_scope",
    db.Column("ticket_id", db.Integer(), db.ForeignKey("tickets.id"), primary_key=True),
    db.Column("project_class_id", db.Integer(), db.ForeignKey("project_classes.id"), primary_key=True),
)

# ticket <-> label many-to-many
ticket_labels = db.Table(
    "ticket_labels",
    db.Column("ticket_id", db.Integer(), db.ForeignKey("tickets.id"), primary_key=True),
    db.Column("label_id", db.Integer(), db.ForeignKey("ticket_label_defs.id"), primary_key=True),
)


# ############################
# CORE ENTITIES


class Ticket(db.Model, TicketWorkflowStatesMixin, EditingMetadataMixin):
    """
    A trouble ticket. Not owned by a single ProjectClass column: its class scope is *derived* from
    its subjects (see TicketSubject / ticket_class_scope) so that a ticket can legitimately span
    more than one class.
    """

    __tablename__ = "tickets"

    # unique ID for this record; surfaced in the UI as "#412"
    id = db.Column(db.Integer(), primary_key=True)

    # ticket title (required). Encrypted at rest (AesEngine) since it may name a student or carry
    # sensitive detail; consequently it is not SQL-searchable/sortable in the ledger. Uses the same
    # queryable-but-less-secure AesEngine as journal titles / exam numbers, keyed by SQLALCHEMY_AES_KEY.
    title = db.Column(
        EncryptedType(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), get_AES_key, AesEngine, "oneandzeroes"),
        nullable=False,
    )

    # opening post of the thread (markdown). Encrypted at rest — free-form, potentially sensitive.
    description = db.Column(
        EncryptedType(db.Text(), get_AES_key, AesEngine, "oneandzeroes"),
        default=None,
        nullable=True,
    )

    # lifecycle status
    status = db.Column(db.Integer(), default=TicketWorkflowStatesMixin.OPEN, nullable=False, index=True)

    # the opener is EditingMetadataMixin.created_by (creator_id); auto-subscribed on creation.

    # assignee (nullable = unassigned but still routable; see the Phase 2 routing rules)
    assignee_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True, index=True)
    assignee = db.relationship("User", foreign_keys=[assignee_id], uselist=False)

    # optional due date
    due_date = db.Column(db.DateTime(), nullable=True, index=True)

    # cached tenant (derived from scope) for query efficiency and office cross-tenant filtering
    tenant_id = db.Column(db.Integer(), db.ForeignKey("tenants.id"), nullable=True, index=True)
    tenant = db.relationship("Tenant", foreign_keys=[tenant_id], backref=db.backref("tickets", lazy="dynamic"))

    # provenance: the ConvenorTask id this ticket was migrated from (Phase 8 data migration), if any.
    # Deliberately not a foreign key — the convenor_tasks tables are dropped at teardown.
    source_task_id = db.Column(db.Integer(), nullable=True, index=True)

    # Activity recency uses EditingMetadataMixin.last_edit_timestamp (paired with last_edit_id):
    # the service layer bumps both on every event (see app/shared/tickets/events.py touch()), and
    # it drives the "Recently updated" sort. creation_timestamp records the original creation.
    __table_args__ = (db.Index("ix_tickets_last_edit_timestamp", "last_edit_timestamp"),)

    # derived class scope (cached; refreshed by the Phase 2 service layer on subject change)
    scope_classes = db.relationship(
        "ProjectClass",
        secondary=ticket_class_scope,
        lazy="dynamic",
        backref=db.backref("scope_tickets", lazy="dynamic"),
    )

    # labels
    labels = db.relationship(
        "Label",
        secondary=ticket_labels,
        lazy="dynamic",
        backref=db.backref("tickets", lazy="dynamic"),
    )

    @property
    def status_label(self) -> str:
        return Ticket._labels.get(self.status, "Unknown")

    @property
    def is_open(self) -> bool:
        return self.status in Ticket.OPEN_STATES

    @property
    def is_closed(self) -> bool:
        return self.status == Ticket.CLOSED


class TicketComment(db.Model):
    """
    A thread entry authored by a user.
    """

    __tablename__ = "ticket_comments"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("comments", lazy="dynamic"))

    author_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    author = db.relationship("User", foreign_keys=[author_id], uselist=False)

    # thread body. Encrypted at rest — free-form, potentially sensitive student detail.
    body = db.Column(
        EncryptedType(db.Text(), get_AES_key, AesEngine, "oneandzeroes"),
        default=None,
        nullable=True,
    )

    created_at = db.Column(db.DateTime(), default=datetime.now, index=True)


class TicketEmail(db.Model, TicketEmailDirectionMixin):
    """
    A logged email associated with a ticket. Rendered inline in the thread as a distinct
    "Email logged" event. Outbound + manual-log only for now (no inbound path).
    """

    __tablename__ = "ticket_emails"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("emails", lazy="dynamic"))

    # who logged this record into the system (may differ from the email's from_addr)
    logged_by_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    logged_by = db.relationship("User", foreign_keys=[logged_by_id], uselist=False)

    direction = db.Column(db.Integer(), default=TicketEmailDirectionMixin.OUTBOUND, nullable=False)

    from_addr = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))
    to_addrs = db.Column(db.Text(collation="utf8_bin"))
    subject = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))
    body = db.Column(db.Text(collation="utf8_bin"))
    message_id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    logged_at = db.Column(db.DateTime(), default=datetime.now, index=True)


class TicketEvent(db.Model, TicketEventKindMixin):
    """
    Append-only audit entry. Renders both in the side-panel "Actions log" and inline in the thread.
    payload_json carries the before/after detail as a JSON string.
    """

    __tablename__ = "ticket_events"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("events", lazy="dynamic"))

    actor_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    actor = db.relationship("User", foreign_keys=[actor_id], uselist=False)

    kind = db.Column(db.Integer(), nullable=False)

    # JSON-encoded before/after payload (decode via the .payload property)
    payload_json = db.Column(db.Text(collation="utf8_bin"), nullable=True)

    created_at = db.Column(db.DateTime(), default=datetime.now, index=True)

    @property
    def kind_label(self) -> str:
        return TicketEvent._labels.get(self.kind, "Unknown")

    @property
    def payload(self) -> Optional[dict]:
        if self.payload_json is None:
            return None
        try:
            return json.loads(self.payload_json)
        except (ValueError, TypeError):
            return None


@dataclass(frozen=True)
class TicketSubjectTombstone:
    """
    The well-defined value `TicketSubject.target` resolves to once its linked SubmittingStudent /
    SelectingStudent has been deleted. `kind` is the TicketSubjectKindMixin value the subject used
    to carry (still available from the subject itself, but repeated here for a self-contained
    value); `label` is the student's display name captured at deletion time.
    """

    kind: int
    label: str
    deleted_at: datetime

    @property
    def kind_label(self) -> str:
        return TicketSubjectKindMixin._labels.get(self.kind, "Unknown")


class TicketSubject(db.Model, TicketSubjectKindMixin):
    """
    What a ticket is "about". A ticket has zero or more subjects, each pointing at exactly one
    target (a submitting student, a selecting student, or a pinned project class). A ticket with no
    subjects is a "General" ticket with empty class scope.

    Exactly one of the three FK columns is non-null, matching kind — UNLESS the subject has been
    tombstoned (see `deleted_at`), in which case all three are null: its target student was deleted
    while still referenced by this subject, so the FK was cleared rather than blocking the deletion
    or cascading it into the ticket. `kind` is left unchanged so the subject still identifies what
    *kind* of link was lost. Client code should not inspect the FK columns directly to tell live
    from tombstoned — use the `target` property, which resolves to either the live object or a
    `TicketSubjectTombstone`.
    """

    __tablename__ = "ticket_subjects"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("subjects", lazy="dynamic"))

    kind = db.Column(db.Integer(), nullable=False)

    # exactly one of the following three is set, matching kind — unless tombstoned (see class
    # docstring), in which case all three are null.
    submitting_student_id = db.Column(db.Integer(), db.ForeignKey("submitting_students.id"), nullable=True, index=True)
    submitting_student = db.relationship(
        "SubmittingStudent", foreign_keys=[submitting_student_id], backref=db.backref("ticket_subjects", lazy="dynamic")
    )

    selecting_student_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"), nullable=True, index=True)
    selecting_student = db.relationship(
        "SelectingStudent", foreign_keys=[selecting_student_id], backref=db.backref("ticket_subjects", lazy="dynamic")
    )

    project_class_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"), nullable=True, index=True)
    project_class = db.relationship("ProjectClass", foreign_keys=[project_class_id], backref=db.backref("ticket_subjects", lazy="dynamic"))

    # TOMBSTONE — set together when a linked SubmittingStudent/SelectingStudent is deleted (see
    # app.shared.tickets.subjects.tombstone_subjects_for_student). deleted_at is None for a live
    # subject; once set, the FK columns above are null and deleted_snapshot_label carries the
    # student's display name at the time of deletion, for the "target" property / UI to fall back on.
    deleted_snapshot_label = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True)
    deleted_at = db.Column(db.DateTime(), nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "(((submitting_student_id IS NOT NULL) + (selecting_student_id IS NOT NULL) + (project_class_id IS NOT NULL)) = 1)"
            " OR "
            "(submitting_student_id IS NULL AND selecting_student_id IS NULL AND project_class_id IS NULL AND deleted_at IS NOT NULL)",
            name="ck_ticket_subject_exactly_one_target",
        ),
    )

    @property
    def is_tombstoned(self) -> bool:
        return self.deleted_at is not None

    @property
    def target(self) -> Union["TicketSubjectTombstone", object, None]:
        """
        Resolve this subject to its live target object, or to a `TicketSubjectTombstone` if the
        linked record has been deleted. Client code must go through this property rather than
        reading the FK/relationship columns directly, so it never needs to know that a null FK
        means "deleted" as opposed to some other absence.
        """
        if self.kind == TicketSubject.SUBMITTING_STUDENT and self.submitting_student is not None:
            return self.submitting_student
        if self.kind == TicketSubject.SELECTING_STUDENT and self.selecting_student is not None:
            return self.selecting_student
        if self.kind == TicketSubject.PROJECT_CLASS:
            return self.project_class

        if self.is_tombstoned:
            return TicketSubjectTombstone(kind=self.kind, label=self.deleted_snapshot_label, deleted_at=self.deleted_at)
        return None


class TicketSubscription(db.Model, TicketSubscriptionReasonMixin):
    """
    A user watching a ticket. Auto-added: opener, assignee, and (on routing) the in-scope
    convenor(s). Drives the "Watching" view and email fan-out.
    """

    __tablename__ = "ticket_subscriptions"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("subscriptions", lazy="dynamic"))

    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=False, index=True)
    user = db.relationship("User", foreign_keys=[user_id], uselist=False)

    reason = db.Column(db.Integer(), default=TicketSubscriptionReasonMixin.MANUAL, nullable=False)

    created_at = db.Column(db.DateTime(), default=datetime.now)

    # who performed the add (None for self-subscribe via watch(), or an automatic reason such as
    # OPENER/ASSIGNEE/CONVENOR). Drives the "added you as a watcher" notification and its
    # adder_name/adder_initials tokens — see app.shared.tickets.subscriptions.subscribe().
    added_by_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True, index=True)
    added_by = db.relationship("User", foreign_keys=[added_by_id], uselist=False)

    # True while this subscription still needs its "you were added as a watcher" email; cleared
    # once app.tasks.ticket_notifications.check_watcher_notifications queues it. Only ever set on
    # newly-created rows (see subscribe()) — never on the idempotent already-subscribed path.
    notify_pending = db.Column(db.Boolean(), nullable=False, default=False)

    __table_args__ = (db.UniqueConstraint("ticket_id", "user_id", name="uq_ticket_subscription_user"),)


class TicketReadState(db.Model):
    """
    Per-(user, ticket) "last read" marker, upserted whenever a user opens a ticket's detail view.
    Absence of a row means "never read". Drives the Unread rail view, unread dots, and the
    "new comments on tickets you watch" tile. A ticket is never unread for its own creator — see
    app.shared.tickets.read_state.is_unread().
    """

    __tablename__ = "ticket_read_states"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("read_states", lazy="dynamic"))

    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=False, index=True)
    user = db.relationship("User", foreign_keys=[user_id], uselist=False)

    last_read_at = db.Column(db.DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (db.UniqueConstraint("ticket_id", "user_id", name="uq_ticket_read_state_user"),)


class TicketInboxVisit(db.Model):
    """
    Tracks when a user last loaded their personal ticket inbox (design screen 2c), to compute the
    "since you last visited" metric tiles and the Activity feed's "N new" badge.
    """

    __tablename__ = "ticket_inbox_visits"

    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"), primary_key=True)
    user = db.relationship("User", foreign_keys=[user_id], uselist=False)

    last_visited_at = db.Column(db.DateTime(), nullable=False, default=datetime.now)


class TicketExternalSubscriber(db.Model):
    """
    An external email address (e.g. the ATAS office) subscribed to a ticket's email thread without
    a User row.
    """

    __tablename__ = "ticket_external_subscribers"

    id = db.Column(db.Integer(), primary_key=True)

    ticket_id = db.Column(db.Integer(), db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], backref=db.backref("external_subscribers", lazy="dynamic"))

    email = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False)

    created_at = db.Column(db.DateTime(), default=datetime.now)

    __table_args__ = (db.UniqueConstraint("ticket_id", "email", name="uq_ticket_external_subscriber_email"),)


class Label(db.Model, ColouredLabelMixin):
    """
    A triage label, scoped per tenant (shared across that tenant's classes). name is unique within
    the tenant; colour is drawn from a fixed palette (auto-assigned = next unused, override by
    swatch in the label editor). Uses ColouredLabelMixin for the `colour` column + label helpers.
    """

    __tablename__ = "ticket_label_defs"

    id = db.Column(db.Integer(), primary_key=True)

    tenant_id = db.Column(db.Integer(), db.ForeignKey("tenants.id"), nullable=False, index=True)
    tenant = db.relationship("Tenant", foreign_keys=[tenant_id], backref=db.backref("ticket_labels", lazy="dynamic"))

    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False)

    __table_args__ = (db.UniqueConstraint("tenant_id", "name", name="uq_ticket_label_tenant_name"),)

    def make_label(self, text=None):
        if text is None:
            text = self.name

        return self._make_label(text)
