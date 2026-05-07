#
# Created by David Seery on 07/05/2026.
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


class SimilarityOrchestrationJob(db.Model):
    """
    Track a standalone similarity-analysis rebuild job.

    Used exclusively for admin-triggered re-indexing of existing records
    without re-running the full language analysis pipeline.  The normal
    similarity pipeline (extract_chunks → compute_minhash → run_similarity_check)
    runs as part of the per-record chain controlled by LLMOrchestrationJob.
    """

    __tablename__ = "similarity_orchestration_job"

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
    # Scope constants
    # ------------------------------------------------------------------

    SCOPE_PERIOD = "period"
    SCOPE_PCLASS = "pclass"
    SCOPE_CYCLE = "cycle"
    SCOPE_GLOBAL = "global"

    ALL_SCOPES = [SCOPE_PERIOD, SCOPE_PCLASS, SCOPE_CYCLE, SCOPE_GLOBAL]

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id = db.Column(db.Integer(), primary_key=True)

    uuid = db.Column(
        db.String(36, collation="utf8_bin"),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: str(uuid4()),
    )

    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True, index=True)
    owner = db.relationship("User", foreign_keys=[owner_id], uselist=False)

    created_at = db.Column(db.DateTime(), index=True, nullable=False, default=datetime.now)
    started_at = db.Column(db.DateTime(), nullable=True)
    finished_at = db.Column(db.DateTime(), nullable=True)

    status = db.Column(
        db.String(20, collation="utf8_bin"),
        nullable=False,
        default=STATUS_PENDING,
        index=True,
    )

    scope = db.Column(db.String(20, collation="utf8_bin"), nullable=False)
    scope_id = db.Column(db.Integer(), nullable=True, index=True)

    clear_existing = db.Column(db.Boolean(), nullable=False, default=False)
    paused = db.Column(db.Boolean(), nullable=False, default=False)

    total_count = db.Column(db.Integer(), nullable=False, default=0)
    completed_count = db.Column(db.Integer(), nullable=False, default=0)
    failed_count = db.Column(db.Integer(), nullable=False, default=0)

    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True)

    # True = standalone rebuild (similarity only).
    rebuild_mode = db.Column(db.Boolean(), nullable=False, default=False)

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
        rebuild_mode: bool = True,
        owner=None,
        description: Optional[str] = None,
    ) -> "SimilarityOrchestrationJob":
        """Factory: create and return (but do not add/commit) a new job instance."""
        job = cls(
            uuid=str(uuid4()),
            scope=scope,
            scope_id=scope_id,
            total_count=total_count,
            clear_existing=clear_existing,
            rebuild_mode=rebuild_mode,
            owner=owner,
            description=description,
            created_at=datetime.now(),
            status=cls.STATUS_PENDING,
            completed_count=0,
            failed_count=0,
            paused=False,
        )
        return job

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    @property
    def redis_queue_key(self) -> str:
        return f"similarity_queue:{self.uuid}"

    @property
    def redis_inflight_key(self) -> str:
        return f"similarity_inflight:{self.uuid}"

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

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else datetime.now()
        return (end - self.started_at).total_seconds()


class SimilarityConcern(db.Model):
    """
    Record a detected similarity concern between two SubmissionRecords for a
    specific chunk type (abstract, introduction, etc.).

    Always stored with record_a_id < record_b_id (canonical ordering).
    Upsert semantics: minhash_jaccard, transformer_cosine, and created_at are
    updated on conflict; reviewer workflow fields are never reset.
    """

    __tablename__ = "similarity_concerns"

    __table_args__ = (
        db.UniqueConstraint("record_a_id", "record_b_id", "chunk_type", name="uq_similarity_concern"),
    )

    id = db.Column(db.Integer(), primary_key=True)

    record_a_id = db.Column(
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        index=True,
        nullable=False,
    )
    record_b_id = db.Column(
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        index=True,
        nullable=False,
    )

    chunk_type = db.Column(db.String(40, collation="utf8_bin"), nullable=False)

    minhash_jaccard = db.Column(db.Float(), nullable=True)
    transformer_cosine = db.Column(db.Float(), nullable=True)

    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.now)

    reviewed = db.Column(db.Boolean(), nullable=False, default=False)
    reviewed_by_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime(), nullable=True)

    resolution = db.Column(db.String(20, collation="utf8_bin"), nullable=True)
    resolution_note = db.Column(db.Text(collation="utf8_bin"), nullable=True)

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    record_a = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_a_id],
        uselist=False,
        backref=db.backref("similarity_concerns_as_a", lazy="dynamic"),
    )
    record_b = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_b_id],
        uselist=False,
        backref=db.backref("similarity_concerns_as_b", lazy="dynamic"),
    )
    reviewed_by = db.relationship(
        "User",
        foreign_keys=[reviewed_by_id],
        uselist=False,
    )
