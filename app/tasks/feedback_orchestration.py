#
# Created by David Seery on 28/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery-based orchestration for bulk feedback PDF generation.

Architecture mirrors LLMOrchestrationJob / llm_orchestration.py exactly:

  When a convenor triggers feedback PDF generation for a MarkingEvent,
  generate_feedback_reports() in app/tasks/marking.py:
    1. Creates a FeedbackOrchestrationJob DB row to track progress.
    2. Pushes the selected ConflationReport IDs into a Redis list keyed by
       the job's UUID (the "pending queue": feedback_queue:{uuid}).
    3. Dispatches global_feedback_orchestration_step.

  global_feedback_orchestration_step is the single coordinator for ALL active
  FeedbackOrchestrationJob instances.  It:
    a. Loads every PENDING/RUNNING job from the DB.
    b. Computes the number of currently in-flight records by summing the
       length of each job's inflight Redis list (feedback_inflight:{uuid}).
    c. Fills available slots (up to PDF_BATCH_SIZE, default 5) by round-robin
       across active job queues, using RPOPLPUSH to atomically move each
       ConflationReport ID from the pending queue to the inflight list.
    d. Dispatches a PDF generation chain for each record.

  Crash safety and recovery follow the same pattern as llm_orchestration:
  inflight IDs are moved back to the pending queue on worker restart by the
  worker_ready signal handler and the periodic feedback_watchdog task.

  The same double-processing race applies: if a record is genuinely in-flight
  on another worker at recovery time, it may be processed twice.  This is
  safe (later write wins; the completion guard uses >=) but wasteful.
"""

from typing import List, Optional

from celery import chain
from celery.signals import worker_ready
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

import redis as redis_lib

from ..database import db
from ..models import ConflationReport, FeedbackOrchestrationJob, User
from .shared.utils import report_info

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PDF_BATCH_SIZE_DEFAULT = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_orchestration_redis() -> redis_lib.Redis:
    """Return a Redis client connected to the orchestration Redis database."""
    url = current_app.config.get("ORCHESTRATION_REDIS_URL")
    if not url:
        raise RuntimeError("ORCHESTRATION_REDIS_URL is not set in the Flask configuration")
    return redis_lib.Redis.from_url(url, decode_responses=False)


def _cleanup_redis(job: FeedbackOrchestrationJob) -> None:
    """Delete both Redis keys for a job (best-effort)."""
    try:
        r = _get_orchestration_redis()
        r.delete(job.redis_queue_key, job.redis_inflight_key)
    except Exception as exc:
        current_app.logger.warning(
            f"feedback_orchestration: could not clean up Redis keys for job {job.uuid}: {exc}"
        )


def _populate_redis_queue(job: FeedbackOrchestrationJob, cr_ids: List[int]) -> None:
    """Push ConflationReport IDs into the pending queue for *job*."""
    if not cr_ids:
        return
    r = _get_orchestration_redis()
    r.lpush(job.redis_queue_key, *[str(cr_id).encode() for cr_id in cr_ids])


def _dispatch_global_coordinator() -> None:
    """Dispatch global_feedback_orchestration_step to the default queue."""
    celery = current_app.extensions["celery"]
    t = celery.tasks["app.tasks.feedback_orchestration.global_feedback_orchestration_step"]
    t.apply_async(queue="default")


def _dispatch_pdf_chain(
    celery,
    job_uuid: str,
    cr_id: int,
    recipe_id: int,
    convenor_id: Optional[int],
) -> None:
    """Build and dispatch the PDF generation chain for *cr_id*."""
    t_generate = celery.tasks["app.tasks.marking.generate_feedback_report"]
    t_done = celery.tasks["app.tasks.feedback_orchestration.feedback_record_done"]
    t_err = celery.tasks["app.tasks.feedback_orchestration.feedback_record_error"]

    work = chain(
        t_generate.si(cr_id, recipe_id, convenor_id).set(queue="llm_tasks"),
        t_done.si(job_uuid, cr_id).set(queue="default"),
    ).on_error(t_err.si(job_uuid, cr_id).set(queue="default"))

    work.apply_async()


def _notify_completion(
    event_name: str,
    recipe_label: str,
    total: int,
    failed: int,
    convenor: Optional[User],
) -> None:
    succeeded = total - failed
    plural = "s" if succeeded != 1 else ""
    msg = f"{event_name}: Generated {succeeded} feedback PDF{plural} using recipe '{recipe_label}'."
    if failed > 0:
        fail_plural = "s" if failed != 1 else ""
        msg += f" {failed} report{fail_plural} failed."
    report_info(msg, "feedback_orchestration", convenor)


def _recover_active_jobs() -> None:
    """
    Called on worker startup (and by the watchdog) to resume any jobs that
    were active when the worker last stopped.

    For each PENDING or RUNNING FeedbackOrchestrationJob:
      - Any ConflationReport IDs in the inflight list are moved back to the
        pending queue via RPOPLPUSH so they will be re-processed.
      - If any queue has pending work, the global coordinator is dispatched.
    """
    try:
        r = _get_orchestration_redis()
    except Exception as exc:
        current_app.logger.error(
            f"!! feedback_orchestration._recover_active_jobs: cannot connect to Redis: {exc}"
        )
        return

    try:
        active_jobs: List[FeedbackOrchestrationJob] = (
            db.session.query(FeedbackOrchestrationJob)
            .filter(FeedbackOrchestrationJob.status.in_(FeedbackOrchestrationJob.ACTIVE_STATUSES))
            .all()
        )
    except SQLAlchemyError as exc:
        current_app.logger.exception(
            "!! feedback_orchestration._recover_active_jobs: SQLAlchemyError loading active jobs",
            exc_info=exc,
        )
        return

    if not active_jobs:
        current_app.logger.info("** feedback_orchestration._recover_active_jobs: no active jobs found")
        return

    needs_coordinator = False
    for job in active_jobs:
        current_app.logger.info(
            f"** feedback_orchestration._recover_active_jobs: recovering job {job.uuid} ({job.description})"
        )
        recovered = 0
        try:
            while r.rpoplpush(job.redis_inflight_key, job.redis_queue_key):
                recovered += 1
        except Exception as exc:
            current_app.logger.warning(
                f"!! feedback_orchestration._recover_active_jobs: Redis error recovering "
                f"inflight items for job {job.uuid}: {exc}"
            )

        if recovered:
            current_app.logger.info(
                f"@@ feedback_orchestration._recover_active_jobs: re-queued {recovered} "
                f"inflight record(s) for job {job.uuid}"
            )
            needs_coordinator = True
        else:
            current_app.logger.info(
                f"@@ feedback_orchestration._recover_active_jobs: no inflight records for job {job.uuid}"
            )

        try:
            pending_count = r.llen(job.redis_queue_key)
        except Exception:
            pending_count = 0

        if pending_count > 0:
            needs_coordinator = True

    if needs_coordinator:
        try:
            _dispatch_global_coordinator()
            current_app.logger.info(
                "** feedback_orchestration._recover_active_jobs: dispatched global coordinator"
            )
        except Exception as exc:
            current_app.logger.warning(
                f"!! feedback_orchestration._recover_active_jobs: could not dispatch coordinator: {exc}"
            )


# ---------------------------------------------------------------------------
# Public helper used by marking.py
# ---------------------------------------------------------------------------


def launch_feedback_job(
    event,
    recipe,
    cr_ids: List[int],
    owner=None,
    convenor_id: Optional[int] = None,
) -> FeedbackOrchestrationJob:
    """
    Create a FeedbackOrchestrationJob, populate its Redis queue, and dispatch
    the global coordinator.  Called from generate_feedback_reports() in marking.py.

    Returns the newly created job.
    """
    description = f"Feedback PDFs: {event.name} / {recipe.label}"
    job = FeedbackOrchestrationJob.build(
        event=event,
        recipe=recipe,
        total_count=len(cr_ids),
        owner=owner,
        convenor_id=convenor_id,
        description=description,
    )
    db.session.add(job)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise

    _populate_redis_queue(job, cr_ids)
    _dispatch_global_coordinator()
    return job


# ---------------------------------------------------------------------------
# Celery task registration
# ---------------------------------------------------------------------------


def register_feedback_orchestration_tasks(celery):

    flask_app = celery.flask_app

    # weak=False prevents the local function from being garbage-collected
    # before worker_ready fires.
    @worker_ready.connect(weak=False)
    def on_worker_ready(sender, **kwargs):
        with flask_app.app_context():
            try:
                _recover_active_jobs()
            except Exception as exc:
                flask_app.logger.exception(
                    "feedback_orchestration.on_worker_ready: recovery failed", exc_info=exc
                )

    # ------------------------------------------------------------------
    # feedback_record_done
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=10)
    def feedback_record_done(self, job_uuid: str, cr_id: int):
        """
        Success callback: called as the last step in a single ConflationReport's
        PDF generation chain.  Removes the record from the inflight list,
        increments the job's completed_count, and triggers the global coordinator.
        """
        try:
            r = _get_orchestration_redis()
            r.lrem(f"feedback_inflight:{job_uuid}", 0, str(cr_id).encode())
        except Exception as exc:
            current_app.logger.warning(
                f"feedback_orchestration.feedback_record_done: Redis LREM failed "
                f"for job {job_uuid} / ConflationReport #{cr_id}: {exc}"
            )

        try:
            job: FeedbackOrchestrationJob = (
                db.session.query(FeedbackOrchestrationJob).filter_by(uuid=job_uuid).first()
            )
            if job is not None:
                job.increment_completed()
                # Use >= (not ==) to correctly handle the double-processing race.
                if (
                    (job.completed_count + job.failed_count) >= job.total_count
                    and job.status == FeedbackOrchestrationJob.STATUS_RUNNING
                ):
                    job.mark_complete()
                    convenor: Optional[User] = job.convenor
                    total = job.completed_count + job.failed_count
                    failed = job.failed_count
                    event_name = job.event.name if job.event else "unknown event"
                    recipe_label = job.recipe.label if job.recipe else "unknown recipe"
                    _notify_completion(event_name, recipe_label, total, failed, convenor)
                db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"feedback_orchestration.feedback_record_done: SQLAlchemyError "
                f"for job {job_uuid} / ConflationReport #{cr_id}",
                exc_info=exc,
            )

        _dispatch_global_coordinator()

    # ------------------------------------------------------------------
    # feedback_record_error
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=10)
    def feedback_record_error(self, job_uuid: str, cr_id: int):
        """
        Error callback: called when a ConflationReport's PDF chain raises an
        unhandled exception.  Removes the record from the inflight list,
        increments the job's failed_count, and triggers the global coordinator.
        """
        try:
            r = _get_orchestration_redis()
            r.lrem(f"feedback_inflight:{job_uuid}", 0, str(cr_id).encode())
        except Exception as exc:
            current_app.logger.warning(
                f"feedback_orchestration.feedback_record_error: Redis LREM failed "
                f"for job {job_uuid} / ConflationReport #{cr_id}: {exc}"
            )

        try:
            job: FeedbackOrchestrationJob = (
                db.session.query(FeedbackOrchestrationJob).filter_by(uuid=job_uuid).first()
            )
            if job is not None:
                job.increment_failed()
                if (
                    (job.completed_count + job.failed_count) >= job.total_count
                    and job.status == FeedbackOrchestrationJob.STATUS_RUNNING
                ):
                    job.mark_complete()
                    convenor: Optional[User] = job.convenor
                    total = job.completed_count + job.failed_count
                    failed = job.failed_count
                    event_name = job.event.name if job.event else "unknown event"
                    recipe_label = job.recipe.label if job.recipe else "unknown recipe"
                    _notify_completion(event_name, recipe_label, total, failed, convenor)
                db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"feedback_orchestration.feedback_record_error: SQLAlchemyError "
                f"for job {job_uuid} / ConflationReport #{cr_id}",
                exc_info=exc,
            )

        _dispatch_global_coordinator()

    # ------------------------------------------------------------------
    # global_feedback_orchestration_step
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def global_feedback_orchestration_step(self):
        """
        Global coordinator: fill up to PDF_BATCH_SIZE slots by popping
        ConflationReport IDs from all active FeedbackOrchestrationJob queues
        (round-robin).
        """
        batch_size: int = current_app.config.get("PDF_BATCH_SIZE", PDF_BATCH_SIZE_DEFAULT)

        # ------- load active jobs -------
        try:
            active_jobs: List[FeedbackOrchestrationJob] = (
                db.session.query(FeedbackOrchestrationJob)
                .filter(FeedbackOrchestrationJob.status.in_(FeedbackOrchestrationJob.ACTIVE_STATUSES))
                .all()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "feedback_orchestration.global_feedback_orchestration_step: SQLAlchemyError loading active jobs",
                exc_info=exc,
            )
            raise self.retry()

        if not active_jobs:
            return

        # ------- connect to Redis -------
        try:
            r = _get_orchestration_redis()
        except Exception as exc:
            current_app.logger.exception(
                "feedback_orchestration.global_feedback_orchestration_step: Redis connection error",
                exc_info=exc,
            )
            raise self.retry()

        # ------- check cancellations and transition PENDING → RUNNING -------
        jobs_to_remove = []
        db_changed = False
        for job in active_jobs:
            if job.status == FeedbackOrchestrationJob.STATUS_FAILED:
                _cleanup_redis(job)
                jobs_to_remove.append(job)
            elif job.status == FeedbackOrchestrationJob.STATUS_PENDING:
                job.mark_started()
                db_changed = True
                if (job.completed_count + job.failed_count) >= job.total_count:
                    job.mark_complete()
                    jobs_to_remove.append(job)

        # Defensive sweep: catch RUNNING jobs whose callbacks raced past the guard.
        for job in active_jobs:
            if (
                job.status == FeedbackOrchestrationJob.STATUS_RUNNING
                and job not in jobs_to_remove
                and (job.completed_count + job.failed_count) >= job.total_count
            ):
                job.mark_complete()
                db_changed = True
                jobs_to_remove.append(job)

        for job in jobs_to_remove:
            active_jobs.remove(job)

        if active_jobs or db_changed:
            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.exception(
                    "feedback_orchestration.global_feedback_orchestration_step: SQLAlchemyError updating job statuses",
                    exc_info=exc,
                )

        if not active_jobs:
            return

        # ------- filter per-job pause state -------
        dispatchable_jobs = [j for j in active_jobs if not j.paused]
        if not dispatchable_jobs:
            current_app.logger.info(
                "feedback_orchestration.global_feedback_orchestration_step: all active jobs are paused"
            )
            return

        # ------- compute available slots -------
        # Sum inflight across ALL active jobs (including paused) since paused
        # jobs may still have records running from before they were paused.
        try:
            inflight = sum(r.llen(job.redis_inflight_key) for job in active_jobs)
        except Exception as exc:
            current_app.logger.exception(
                "feedback_orchestration.global_feedback_orchestration_step: Redis error reading inflight counts",
                exc_info=exc,
            )
            raise self.retry()

        available_slots = max(0, batch_size - inflight)
        if available_slots == 0:
            return

        # ------- round-robin dispatch -------
        dispatched = 0
        max_attempts = len(dispatchable_jobs) * available_slots + len(dispatchable_jobs)
        attempts = 0
        job_idx = 0

        while dispatched < available_slots and attempts < max_attempts:
            job = dispatchable_jobs[job_idx % len(dispatchable_jobs)]
            job_idx += 1
            attempts += 1

            try:
                cr_id_bytes = r.rpoplpush(job.redis_queue_key, job.redis_inflight_key)
            except Exception as exc:
                current_app.logger.exception(
                    f"feedback_orchestration.global_feedback_orchestration_step: Redis RPOPLPUSH error "
                    f"for job {job.uuid}",
                    exc_info=exc,
                )
                continue

            if cr_id_bytes is None:
                continue

            cr_id = int(cr_id_bytes)

            try:
                cr: ConflationReport = db.session.query(ConflationReport).filter_by(id=cr_id).first()
            except SQLAlchemyError as exc:
                current_app.logger.exception(
                    f"feedback_orchestration.global_feedback_orchestration_step: SQLAlchemyError loading "
                    f"ConflationReport #{cr_id}",
                    exc_info=exc,
                )
                r.lrem(job.redis_inflight_key, 0, cr_id_bytes)
                try:
                    job.increment_failed()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                dispatched += 1
                continue

            if cr is None:
                current_app.logger.warning(
                    f"feedback_orchestration.global_feedback_orchestration_step: skipping "
                    f"ConflationReport #{cr_id} (not found)"
                )
                r.lrem(job.redis_inflight_key, 0, cr_id_bytes)
                try:
                    job.increment_failed()
                    if (
                        (job.completed_count + job.failed_count) >= job.total_count
                        and job.status == FeedbackOrchestrationJob.STATUS_RUNNING
                    ):
                        job.mark_complete()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                dispatched += 1
                continue

            _dispatch_pdf_chain(celery, job.uuid, cr_id, job.recipe_id, job.convenor_id)
            dispatched += 1

    # ------------------------------------------------------------------
    # feedback_watchdog
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=60)
    def feedback_watchdog(self):
        """
        Periodic watchdog: recover any stalled FeedbackOrchestrationJob
        instances by moving inflight items back to the pending queue and
        re-dispatching the global coordinator.  Intended to run every ~30
        minutes via the DatabaseScheduler Beat schedule.
        """
        try:
            _recover_active_jobs()
        except Exception as exc:
            current_app.logger.exception(
                "feedback_orchestration.feedback_watchdog: recovery failed", exc_info=exc
            )
            raise self.retry()

    return (
        global_feedback_orchestration_step,
        feedback_record_done,
        feedback_record_error,
        feedback_watchdog,
    )
