#
# Created by David Seery on 26/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH

# Association table linking WorkflowLogEntry to ProjectClass (many-to-many)
workflow_log_to_pclass = db.Table(
    "workflow_log_to_pclass",
    db.Column(
        "workflow_log_id",
        db.Integer(),
        db.ForeignKey("workflow_log.id"),
        primary_key=True,
    ),
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
)


class WorkflowLogEntry(db.Model):
    """
    Records a single database commit event for the workflow log.

    Each entry captures:
    - The time of the commit
    - The Flask route or Celery task that triggered the commit
    - An optional link to the logged-in user who initiated the action
    - A human-readable summary of what took place
    - The set of ProjectClass instances the action applies to (if any)
    """

    __tablename__ = "workflow_log"

    # Primary key
    id = db.Column(db.Integer(), primary_key=True)

    # Timestamp of the commit
    timestamp = db.Column(db.DateTime(), index=True, default=datetime.now)

    # The logged-in user who initiated the action, if any (nullable for background tasks)
    initiator_id = db.Column(
        db.Integer(), db.ForeignKey("users.id"), default=None, nullable=True
    )
    initiator = db.relationship(
        "User",
        foreign_keys=[initiator_id],
        uselist=False,
        backref=db.backref("workflow_log_entries", lazy="dynamic"),
    )

    # Student this transaction applies to, if present
    student_id = db.Column(
        db.Integer(), db.ForeignKey("student_data.id"), default=None, nullable=True
    )
    student = db.relationship(
        "StudentData",
        foreign_keys=[student_id],
        uselist=False,
        backref=db.backref("workflow_log_entries", lazy="dynamic"),
    )

    # Name of the Flask route or Celery task that performed the commit
    endpoint = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
        index=True,
        default=None,
        nullable=True,
    )

    # Human-readable description of the event
    summary = db.Column(db.Text(), default=None, nullable=True)

    # Project classes to which this event applies
    project_classes = db.relationship(
        "ProjectClass",
        secondary=workflow_log_to_pclass,
        lazy="dynamic",
        backref=db.backref("workflow_log_entries", lazy="dynamic"),
    )
