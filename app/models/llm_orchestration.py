#
# Created by David Seery on 07/04/2026.
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


class LLMOrchestrationJob(db.Model):
    """
    Track a batch LLM-pipeline orchestration job.

    When a convenor or admin triggers bulk submission (or clear-and-resubmit) of
    SubmissionRecords to the language-analysis pipeline, one of these rows is
    created.  A Celery coordinator task uses a Redis list keyed by ``uuid`` to
    serialise individual submissions, and updates the counters here as each one
    finishes so the dashboard can display live progress without querying Celery.
    """

    __tablename__ = "llm_orchestration_job"

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
    # Scope constants – what set of SubmissionRecords is being processed
    # ------------------------------------------------------------------

    SCOPE_PERIOD = "period"    # single SubmissionPeriodRecord
    SCOPE_PCLASS = "pclass"    # all periods in a ProjectClassConfig
    SCOPE_CYCLE = "cycle"      # all periods in a MainConfig year
    SCOPE_GLOBAL = "global"    # every period in the database

    ALL_SCOPES = [SCOPE_PERIOD, SCOPE_PCLASS, SCOPE_CYCLE, SCOPE_GLOBAL]

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

    # What this job is processing.
    scope = db.Column(db.String(20, collation="utf8_bin"), nullable=False)

    # ID of the primary scope object (period_id, pclass_id, or year for cycle).
    # NULL for SCOPE_GLOBAL.
    scope_id = db.Column(db.Integer(), nullable=True, index=True)

    # Whether existing analysis results were cleared before re-submission.
    clear_existing = db.Column(db.Boolean(), nullable=False, default=False)

    # Progress counters.  updated atomically by the coordinator task.
    total_count = db.Column(db.Integer(), nullable=False, default=0)
    completed_count = db.Column(db.Integer(), nullable=False, default=0)
    failed_count = db.Column(db.Integer(), nullable=False, default=0)

    # Short human-readable description shown in the dashboard status panel.
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True)

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        scope: str,
        scope_id: Optional[int],
        total_count: int,
        clear_existing: bool = False,
        owner=None,
        description: Optional[str] = None,
    ) -> "LLMOrchestrationJob":
        """
        Factory: create and return (but do not add/commit) a new job instance.
        """
        job = cls(
            uuid=str(uuid4()),
            scope=scope,
            scope_id=scope_id,
            total_count=total_count,
            clear_existing=clear_existing,
            owner=owner,
            description=description,
            created_at=datetime.now(),
            status=cls.STATUS_PENDING,
            completed_count=0,
            failed_count=0,
        )
        return job

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    @property
    def redis_queue_key(self) -> str:
        """Redis list key used to store the pending SubmissionRecord IDs."""
        return f"llm_queue:{self.uuid}"

    @property
    def is_active(self) -> bool:
        """True while the job is pending or running (i.e. has not yet terminated)."""
        return self.status in self.ACTIVE_STATUSES

    @property
    def progress_pct(self) -> int:
        """Integer percentage of records processed (completed + failed)."""
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
        labels = {
            self.SCOPE_PERIOD: "submission period",
            self.SCOPE_PCLASS: "project class",
            self.SCOPE_CYCLE: "academic cycle",
            self.SCOPE_GLOBAL: "all submissions",
        }
        return labels.get(self.scope, self.scope)

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
        """Bootstrap colour name for badge/indicator."""
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

    @property
    def elapsed_seconds(self) -> Optional[float]:
        """Wall-clock seconds from started_at to finished_at (or now if still running)."""
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else datetime.now()
        return (end - self.started_at).total_seconds()
