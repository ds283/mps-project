#
# Created by David Seery on 07/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery-based orchestration for bulk LLM pipeline submissions.

Architecture (Option B — Redis-backed serial coordinator):

  When a convenor/admin triggers bulk analysis submission, a helper function
  (e.g. ``launch_period_pipeline``) is called directly from the view.  It:

  1. Creates a ``LLMOrchestrationJob`` DB row to track progress.
  2. Pushes the selected ``SubmissionRecord`` IDs into a Redis list keyed by
     the job's UUID.
  3. Dispatches the ``orchestration_step`` Celery task.

  ``orchestration_step`` pops one record ID from the Redis list, resets the
  record's analysis state, and launches its analysis chain
  (download_and_extract → compute_statistics → submit_to_llm →
   submit_to_llm_feedback → finalize → orchestration_record_done).

  On success, ``orchestration_record_done`` increments the job's
  ``completed_count`` and re-dispatches ``orchestration_step`` for the next
  record.  On failure, ``orchestration_record_error`` does the same after
  resetting the record flags and incrementing ``failed_count``.

  This pattern serialises all LLM-queue tasks (only one analysis chain runs
  at a time) without building a fragile chain-of-chains.  Scaling to a
  batch_size > 1 requires only a trivial change to ``orchestration_step``.
"""

from datetime import datetime
from typing import List, Optional

import redis as redis_lib
from celery import chain
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    LLMOrchestrationJob,
    ProjectClassConfig,
    SubmissionPeriodRecord,
    SubmissionRecord,
    User,
)
from ..shared.workflow_logging import log_db_commit


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_orchestration_redis() -> redis_lib.Redis:
    """Return a Redis client connected to the orchestration Redis database."""
    url = current_app.config.get("ORCHESTRATION_REDIS_URL")
    if not url:
        raise RuntimeError("ORCHESTRATION_REDIS_URL is not set in the Flask configuration")
    return redis_lib.Redis.from_url(url, decode_responses=False)


def _cleanup_redis(job_uuid: str) -> None:
    """Delete the Redis queue key for a job (best-effort)."""
    try:
        r = _get_orchestration_redis()
        r.delete(f"llm_queue:{job_uuid}")
    except Exception as exc:
        current_app.logger.warning(
            f"llm_orchestration: could not clean up Redis queue for job {job_uuid}: {exc}"
        )


def _clear_record_state(record: SubmissionRecord) -> None:
    """
    Reset all language-analysis state on *record*, including deletion of its
    processed report from the object store.  Does NOT commit the session.
    """
    record.language_analysis = None
    record.language_analysis_started = False
    record.language_analysis_complete = False
    record.llm_analysis_failed = False
    record.llm_failure_reason = None
    record.llm_feedback_failed = False
    record.llm_feedback_failure_reason = None
    record.risk_factors = None

    if record.processed_report is not None:
        old_asset = record.processed_report
        record.processed_report_id = None
        record.celery_finished = False
        record.celery_failed = False
        try:
            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
            if object_store is not None:
                object_store.delete(old_asset.unique_name, audit_data="llm_orchestration._clear_record_state")
        except Exception as exc:
            current_app.logger.warning(
                f"llm_orchestration: could not delete processed report asset "
                f"for SubmissionRecord #{record.id}: {exc}"
            )
        db.session.delete(old_asset)


def _reset_record_flags_only(record: SubmissionRecord) -> None:
    """
    Reset only the language-analysis *progress* flags so the record can be
    retried, without touching the stored analysis data or processed report.
    """
    record.language_analysis_started = False
    record.language_analysis_complete = False


def _collect_record_ids(
    period_ids: List[int],
    skip_complete: bool,
) -> List[int]:
    """
    Return a list of SubmissionRecord IDs from the given periods.

    If *skip_complete* is True, only records where both
    ``language_analysis_started`` and ``language_analysis_complete`` are
    False are included (i.e. records that have not yet been submitted).
    """
    q = (
        db.session.query(SubmissionRecord.id)
        .filter(SubmissionRecord.period_id.in_(period_ids))
        .filter(SubmissionRecord.report != None)  # noqa: E711
    )
    if skip_complete:
        q = q.filter(
            SubmissionRecord.language_analysis_started.is_(False),
            SubmissionRecord.language_analysis_complete.is_(False),
        )
    return [row[0] for row in q.all()]


def _populate_redis_queue(job: LLMOrchestrationJob, record_ids: List[int]) -> None:
    """Push *record_ids* into the job's Redis queue (left push → right pop = FIFO)."""
    if not record_ids:
        return
    r = _get_orchestration_redis()
    key = job.redis_queue_key
    # Use a pipeline for efficiency
    pipe = r.pipeline()
    for rid in record_ids:
        pipe.lpush(key, rid)
    pipe.execute()


def _dispatch_coordinator(job_uuid: str) -> None:
    """Dispatch the orchestration_step task for the given job UUID."""
    celery = current_app.extensions["celery"]
    t_step = celery.tasks["app.tasks.llm_orchestration.orchestration_step"]
    t_step.apply_async(args=[job_uuid], queue="default")


# ---------------------------------------------------------------------------
# Entry-point helpers (called from views)
# ---------------------------------------------------------------------------


def launch_period_pipeline(
    period_id: int,
    clear_existing: bool = False,
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job for a single ``SubmissionPeriodRecord``.

    Returns the created ``LLMOrchestrationJob`` (already committed) or None if
    there are no eligible records.
    """
    period: SubmissionPeriodRecord = (
        db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
    )
    if period is None:
        current_app.logger.error(
            f"launch_period_pipeline: SubmissionPeriodRecord #{period_id} not found"
        )
        return None

    record_ids = _collect_record_ids([period_id], skip_complete=not clear_existing)
    if not record_ids:
        return None

    description = f"Period: {period.display_name}"
    job = LLMOrchestrationJob.build(
        scope=LLMOrchestrationJob.SCOPE_PERIOD,
        scope_id=period_id,
        total_count=len(record_ids),
        clear_existing=clear_existing,
        owner=user,
        description=description,
    )
    db.session.add(job)
    db.session.flush()  # get job.id / job.uuid

    _populate_redis_queue(job, record_ids)

    try:
        log_db_commit(
            f"Launched LLM orchestration job (period #{period_id}, "
            f"{len(record_ids)} records, clear={clear_existing})",
        )
    except SQLAlchemyError:
        db.session.rollback()
        raise

    _dispatch_coordinator(job.uuid)
    return job


def launch_pclass_pipeline(
    pclass_config_id: int,
    clear_existing: bool = False,
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job for all periods in a ``ProjectClassConfig``.
    """
    config: ProjectClassConfig = (
        db.session.query(ProjectClassConfig).filter_by(id=pclass_config_id).first()
    )
    if config is None:
        current_app.logger.error(
            f"launch_pclass_pipeline: ProjectClassConfig #{pclass_config_id} not found"
        )
        return None

    period_ids = [p.id for p in config.periods.all()]
    if not period_ids:
        return None

    record_ids = _collect_record_ids(period_ids, skip_complete=not clear_existing)
    if not record_ids:
        return None

    pclass_name = config.project_class.abbreviation if config.project_class else str(pclass_config_id)
    description = f"Project class: {pclass_name} ({config.year}/{config.year + 1})"
    job = LLMOrchestrationJob.build(
        scope=LLMOrchestrationJob.SCOPE_PCLASS,
        scope_id=pclass_config_id,
        total_count=len(record_ids),
        clear_existing=clear_existing,
        owner=user,
        description=description,
    )
    db.session.add(job)
    db.session.flush()

    _populate_redis_queue(job, record_ids)

    try:
        log_db_commit(
            f"Launched LLM orchestration job (pclass config #{pclass_config_id}, "
            f"{len(record_ids)} records, clear={clear_existing})",
        )
    except SQLAlchemyError:
        db.session.rollback()
        raise

    _dispatch_coordinator(job.uuid)
    return job


def launch_cycle_pipeline(
    year: int,
    clear_existing: bool = False,
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job for all periods in a ``MainConfig`` cycle (year).
    """
    period_ids = [
        row[0]
        for row in (
            db.session.query(SubmissionPeriodRecord.id)
            .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
            .filter(ProjectClassConfig.year == year)
            .all()
        )
    ]
    if not period_ids:
        return None

    record_ids = _collect_record_ids(period_ids, skip_complete=not clear_existing)
    if not record_ids:
        return None

    description = f"Cycle: {year}/{year + 1}"
    job = LLMOrchestrationJob.build(
        scope=LLMOrchestrationJob.SCOPE_CYCLE,
        scope_id=year,
        total_count=len(record_ids),
        clear_existing=clear_existing,
        owner=user,
        description=description,
    )
    db.session.add(job)
    db.session.flush()

    _populate_redis_queue(job, record_ids)

    try:
        log_db_commit(
            f"Launched LLM orchestration job (cycle {year}, "
            f"{len(record_ids)} records, clear={clear_existing})",
        )
    except SQLAlchemyError:
        db.session.rollback()
        raise

    _dispatch_coordinator(job.uuid)
    return job


def launch_global_pipeline(
    clear_existing: bool = False,
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job covering every SubmissionRecord in the database.
    """
    period_ids = [row[0] for row in db.session.query(SubmissionPeriodRecord.id).all()]
    if not period_ids:
        return None

    record_ids = _collect_record_ids(period_ids, skip_complete=not clear_existing)
    if not record_ids:
        return None

    description = "Global: all project classes and cycles"
    job = LLMOrchestrationJob.build(
        scope=LLMOrchestrationJob.SCOPE_GLOBAL,
        scope_id=None,
        total_count=len(record_ids),
        clear_existing=clear_existing,
        owner=user,
        description=description,
    )
    db.session.add(job)
    db.session.flush()

    _populate_redis_queue(job, record_ids)

    try:
        log_db_commit(
            f"Launched global LLM orchestration job "
            f"({len(record_ids)} records, clear={clear_existing})",
        )
    except SQLAlchemyError:
        db.session.rollback()
        raise

    _dispatch_coordinator(job.uuid)
    return job


# ---------------------------------------------------------------------------
# Celery task registration
# ---------------------------------------------------------------------------


def register_llm_orchestration_tasks(celery):

    # ------------------------------------------------------------------
    # orchestration_record_done
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=10)
    def orchestration_record_done(self, job_uuid: str, record_id: int):
        """
        Success callback: called as the last step in a single SubmissionRecord's
        analysis chain.  Increments the job's completed_count and triggers the
        next coordinator step.
        """
        try:
            job: LLMOrchestrationJob = (
                db.session.query(LLMOrchestrationJob).filter_by(uuid=job_uuid).first()
            )
            if job is not None:
                job.increment_completed()
                db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"llm_orchestration.orchestration_record_done: SQLAlchemyError "
                f"for job {job_uuid} / record #{record_id}",
                exc_info=exc,
            )

        # Always advance regardless of DB outcome
        orchestration_step.apply_async(args=[job_uuid], queue="default")

    # ------------------------------------------------------------------
    # orchestration_record_error
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=10)
    def orchestration_record_error(self, job_uuid: str, record_id: int):
        """
        Error callback: called when a SubmissionRecord's analysis chain raises an
        unhandled exception.  Resets the record's progress flags, increments the
        job's failed_count, and triggers the next coordinator step.
        """
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
            if record is not None:
                _reset_record_flags_only(record)
                data = record.language_analysis_data
                data.pop("_extracted_text", None)
                data.setdefault("errors", []).append(
                    {
                        "stage": "workflow",
                        "type": "OrchestrationError",
                        "message": (
                            "An unhandled exception occurred during bulk orchestration. "
                            "Check Celery logs."
                        ),
                    }
                )
                record.set_language_analysis_data(data)

            job: LLMOrchestrationJob = (
                db.session.query(LLMOrchestrationJob).filter_by(uuid=job_uuid).first()
            )
            if job is not None:
                job.increment_failed()

            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"llm_orchestration.orchestration_record_error: SQLAlchemyError "
                f"for job {job_uuid} / record #{record_id}",
                exc_info=exc,
            )

        # Always advance regardless of DB outcome
        orchestration_step.apply_async(args=[job_uuid], queue="default")

    # ------------------------------------------------------------------
    # orchestration_step  (main coordinator)
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def orchestration_step(self, job_uuid: str):
        """
        Coordinator: pop one SubmissionRecord ID from the Redis queue and launch
        its language-analysis chain.  When the queue is exhausted, mark the job
        complete.  Each successful/failed completion triggers another call to
        this task, preserving serial LLM execution.
        """
        # ------- load job -------
        try:
            job: LLMOrchestrationJob = (
                db.session.query(LLMOrchestrationJob).filter_by(uuid=job_uuid).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                f"llm_orchestration.orchestration_step: SQLAlchemyError loading "
                f"job {job_uuid}",
                exc_info=exc,
            )
            raise self.retry()

        if job is None:
            current_app.logger.error(
                f"llm_orchestration.orchestration_step: job {job_uuid} not found — stopping"
            )
            return

        # Honour a manual cancellation
        if job.status == LLMOrchestrationJob.STATUS_FAILED:
            current_app.logger.info(
                f"llm_orchestration.orchestration_step: job {job_uuid} cancelled — stopping"
            )
            _cleanup_redis(job_uuid)
            return

        # Mark running on the first invocation
        if job.status == LLMOrchestrationJob.STATUS_PENDING:
            job.mark_started()
            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.exception(
                    f"llm_orchestration.orchestration_step: SQLAlchemyError marking "
                    f"job {job_uuid} as started",
                    exc_info=exc,
                )

        # ------- pop next record -------
        try:
            r = _get_orchestration_redis()
            record_id_bytes = r.rpop(job.redis_queue_key)
        except Exception as exc:
            current_app.logger.exception(
                f"llm_orchestration.orchestration_step: Redis error for job {job_uuid}",
                exc_info=exc,
            )
            raise self.retry()

        if record_id_bytes is None:
            # Queue exhausted — job complete
            try:
                job.mark_complete()
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.exception(
                    f"llm_orchestration.orchestration_step: SQLAlchemyError finalising "
                    f"job {job_uuid}",
                    exc_info=exc,
                )
            return

        record_id = int(record_id_bytes)

        # ------- load and validate record -------
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                f"llm_orchestration.orchestration_step: SQLAlchemyError loading "
                f"SubmissionRecord #{record_id}",
                exc_info=exc,
            )
            try:
                job.increment_failed()
                db.session.commit()
            except Exception:
                db.session.rollback()
            orchestration_step.apply_async(args=[job_uuid], queue="default")
            return

        if record is None or record.report is None:
            current_app.logger.warning(
                f"llm_orchestration.orchestration_step: skipping SubmissionRecord #{record_id} "
                f"(not found or no report)"
            )
            try:
                job.increment_failed()
                db.session.commit()
            except Exception:
                db.session.rollback()
            orchestration_step.apply_async(args=[job_uuid], queue="default")
            return

        # ------- optionally clear existing results -------
        if job.clear_existing:
            _clear_record_state(record)

        # ------- prepare record for (re-)submission -------
        record.language_analysis_started = True
        record.language_analysis_complete = False
        record.llm_analysis_failed = False
        record.llm_failure_reason = None
        record.llm_feedback_failed = False
        record.llm_feedback_failure_reason = None

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"llm_orchestration.orchestration_step: SQLAlchemyError resetting "
                f"SubmissionRecord #{record_id}",
                exc_info=exc,
            )
            try:
                job.increment_failed()
                db.session.commit()
            except Exception:
                db.session.rollback()
            orchestration_step.apply_async(args=[job_uuid], queue="default")
            return

        # ------- build and dispatch the analysis chain -------
        t_extract = celery.tasks["app.tasks.language_analysis.download_and_extract"]
        t_stats = celery.tasks["app.tasks.language_analysis.compute_statistics"]
        t_llm = celery.tasks["app.tasks.language_analysis.submit_to_llm"]
        t_feedback = celery.tasks["app.tasks.language_analysis.submit_to_llm_feedback"]
        t_finalize = celery.tasks["app.tasks.language_analysis.finalize"]
        t_done = orchestration_record_done.si(job_uuid, record_id).set(queue="default")
        t_err = orchestration_record_error.si(job_uuid, record_id).set(queue="default")

        work = chain(
            t_extract.si(record_id).set(queue="llm_tasks"),
            t_stats.si(record_id).set(queue="default"),
            t_llm.si(record_id).set(queue="llm_tasks"),
            t_feedback.si(record_id).set(queue="llm_tasks"),
            t_finalize.si(record_id).set(queue="default"),
            t_done,
        ).on_error(t_err)

        work.apply_async()

    # Return the three task objects so callers can reference them if needed
    return orchestration_step, orchestration_record_done, orchestration_record_error
