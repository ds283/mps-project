#
# Created by David Seery on 28/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from typing import Optional
from uuid import uuid4

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH


class FeedbackOrchestrationJob(db.Model):
    """
    Track a batch feedback-PDF orchestration job.

    When a convenor triggers generation of feedback PDFs for a MarkingEvent,
    one of these rows is created.  A Celery coordinator task uses a Redis list
    keyed by ``uuid`` to serialise individual ConflationReport submissions, and
    updates the counters here as each one finishes so the inspector page can
    display live progress without querying Celery.
    """

    __tablename__ = "feedback_orchestration_job"

    # ------------------------------------------------------------------
    # Status constants
    # ------------------------------------------------------------------

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"

    ALL_STATUSES = [STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETE, STATUS_FAILED]
    ACTIVE_STATUSES = [STATUS_PENDING, STATUS_RUNNING]

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id = db.Column(db.Integer(), primary_key=True)

    # Stable UUID used as the Redis key suffix and as a public identifier.
    uuid = db.Column(
        db.String(36, collation="utf8_bin"),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: str(uuid4()),
    )

    # User who initiated the job.
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True, index=True)
    owner = db.relationship("User", foreign_keys=[owner_id], uselist=False)

    # Convenor to notify on completion (may differ from owner in scheduled runs).
    convenor_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    convenor = db.relationship("User", foreign_keys=[convenor_id], uselist=False)

    # Scope: a single (MarkingEvent, FeedbackRecipe) pair.
    event_id = db.Column(db.Integer(), db.ForeignKey("marking_events.id"), nullable=True, index=True)
    event = db.relationship("MarkingEvent", foreign_keys=[event_id], uselist=False)

    recipe_id = db.Column(db.Integer(), db.ForeignKey("feedback_recipes.id"), nullable=True, index=True)
    recipe = db.relationship("FeedbackRecipe", foreign_keys=[recipe_id], uselist=False)

    # Timestamps.
    created_at = db.Column(db.DateTime(), index=True, nullable=False, default=datetime.now)
    started_at = db.Column(db.DateTime(), nullable=True)
    finished_at = db.Column(db.DateTime(), nullable=True)

    # Job lifecycle state.
    status = db.Column(
        db.String(20, collation="utf8_bin"),
        nullable=False,
        default=STATUS_PENDING,
        index=True,
    )

    # Whether this job is paused (no new records dispatched until resumed).
    # In-flight records continue to completion.
    paused = db.Column(db.Boolean(), nullable=False, default=False)

    # Progress counters, updated atomically by the coordinator task.
    total_count = db.Column(db.Integer(), nullable=False, default=0)
    completed_count = db.Column(db.Integer(), nullable=False, default=0)
    failed_count = db.Column(db.Integer(), nullable=False, default=0)

    # Short human-readable description shown in the inspector status panel.
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True)

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        event,
        recipe,
        total_count: int,
        owner=None,
        convenor=None,
        convenor_id: Optional[int] = None,
        description: Optional[str] = None,
    ) -> "FeedbackOrchestrationJob":
        """Factory: create and return (but do not add/commit) a new job instance."""
        job = cls(
            uuid=str(uuid4()),
            event=event,
            recipe=recipe,
            total_count=total_count,
            owner=owner,
            convenor_id=convenor_id,
            description=description,
            created_at=datetime.now(),
            status=cls.STATUS_PENDING,
            completed_count=0,
            failed_count=0,
            paused=False,
        )
        return job

    # ------------------------------------------------------------------
    # Redis key helpers
    # ------------------------------------------------------------------

    @property
    def redis_queue_key(self) -> str:
        """Redis list key storing pending ConflationReport IDs."""
        return f"feedback_queue:{self.uuid}"

    @property
    def redis_inflight_key(self) -> str:
        """Redis list key tracking ConflationReport IDs currently being processed."""
        return f"feedback_inflight:{self.uuid}"

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def progress_pct(self) -> int:
        if self.total_count == 0:
            return 100
        done = (self.completed_count or 0) + (self.failed_count or 0)
        return min(100, int(done * 100 / self.total_count))

    @property
    def remaining_count(self) -> int:
        done = (self.completed_count or 0) + (self.failed_count or 0)
        return max(0, (self.total_count or 0) - done)

    @property
    def scope_label(self) -> str:
        return "marking event"

    @property
    def status_label(self) -> str:
        labels = {
            self.STATUS_PENDING: "Pending",
            self.STATUS_RUNNING: "Running",
            self.STATUS_COMPLETE: "Complete",
            self.STATUS_FAILED: "Failed",
        }
        return labels.get(self.status, self.status.title())

    @property
    def status_colour(self) -> str:
        colours = {
            self.STATUS_PENDING: "secondary",
            self.STATUS_RUNNING: "primary",
            self.STATUS_COMPLETE: "success",
            self.STATUS_FAILED: "danger",
        }
        return colours.get(self.status, "secondary")

    def mark_started(self) -> None:
        self.status = self.STATUS_RUNNING
        self.started_at = datetime.now()

    def mark_complete(self) -> None:
        self.status = self.STATUS_COMPLETE
        self.finished_at = datetime.now()

    def mark_failed(self) -> None:
        self.status = self.STATUS_FAILED
        self.finished_at = datetime.now()

    def increment_completed(self) -> None:
        self.completed_count = (self.completed_count or 0) + 1

    def increment_failed(self) -> None:
        self.failed_count = (self.failed_count or 0) + 1

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def avg_seconds_per_record(self) -> Optional[float]:
        if self.status != self.STATUS_COMPLETE:
            return None
        done = (self.completed_count or 0) + (self.failed_count or 0)
        if done == 0:
            return None
        elapsed = self.elapsed_seconds
        if elapsed is None:
            return None
        return elapsed / done
