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

Architecture (Global coordinator with reliable Redis queue):

  When any submission path triggers LLM analysis (bulk dashboard actions,
  ad-hoc single-record submission, or Canvas pull_report), it calls one of
  the launch_*_pipeline() helpers or enqueue_single_record().  These helpers:

  1. Create a LLMOrchestrationJob DB row to track progress.
  2. Push the selected SubmissionRecord IDs into a Redis list keyed by the
     job's UUID (the "pending queue").
  3. Dispatch global_orchestration_step.

  global_orchestration_step is the single coordinator for ALL active
  LLMOrchestrationJob instances.  It:

  a. Loads every PENDING/RUNNING job from the DB.
  b. Computes the number of currently in-flight records by summing the length
     of each job's inflight Redis list (llm_inflight:{uuid}).
  c. Fills available slots (up to OLLAMA_BATCH_SIZE) by round-robin across
     active job queues, using RPOPLPUSH to atomically move each record ID from
     the pending queue (llm_queue:{uuid}) to the inflight list
     (llm_inflight:{uuid}).
  d. Dispatches an analysis chain for each record.

  Because a single coordinator manages all jobs, parallel submissions from
  multiple LLMOrchestrationJob instances are serialised under the configured
  batch limit — no per-job coordinator tasks, no hidden bypass paths.

  Reliable queue (crash safety):

  RPOPLPUSH moves record IDs atomically from the pending queue to the inflight
  list.  If a Celery worker crashes mid-chain the record ID stays in the
  inflight list and is not lost.  On worker restart the worker_ready signal
  handler calls _recover_active_jobs(), which moves any inflight items back to
  the pending queue before re-dispatching the coordinator.

  Double-processing race (accepted limitation):

  If worker A is processing record X (X is in llm_inflight:{uuid}) and worker
  B restarts, the recovery handler on B sees X in the inflight list, moves it
  back to the pending queue, and the coordinator dispatches a second chain for
  X.  Both chains then run concurrently on workers A and B.

  This is safe but wasteful:
    - Both chains write to the same language_analysis JSON blob; the last
      writer wins.  Both start from scratch and produce a complete, valid
      result, so the final stored state is correct.
    - completed_count is incremented twice.  The completion check therefore
      uses >= rather than == and guards against marking an already-complete
      job complete a second time.
    - Two LLM calls are made for the same report, wasting server time.
    - _dispatch_process_report() is called twice from finalize(); the second
      run overwrites the first processed report, which is harmless.

  This race can only occur after a worker crash and restart, which is rare in
  practice.  The alternative (a per-record Redis lock) adds meaningful
  complexity for negligible benefit.
"""

from typing import List, Optional

from celery import chain
from celery.signals import worker_ready
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

import redis as redis_lib

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
        raise RuntimeError(
            "ORCHESTRATION_REDIS_URL is not set in the Flask configuration"
        )
    return redis_lib.Redis.from_url(url, decode_responses=False)


def _cleanup_redis(job: LLMOrchestrationJob) -> None:
    """Delete both Redis keys for a job (best-effort)."""
    try:
        r = _get_orchestration_redis()
        r.delete(job.redis_queue_key, job.redis_inflight_key)
    except Exception as exc:
        current_app.logger.warning(
            f"llm_orchestration: could not clean up Redis keys for job {job.uuid}: {exc}"
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
    record.llm_feedback_failed = None  # None = feedback not yet attempted on this run
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
                object_store.delete(
                    old_asset.unique_name,
                    audit_data="llm_orchestration._clear_record_state",
                )
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


def _collect_error_record_ids(period_ids: List[int]) -> List[int]:
    """
    Return a list of SubmissionRecord IDs from the given periods that have at
    least one LLM error flag set (``llm_analysis_failed`` or
    ``llm_feedback_failed``).
    """
    return [
        row[0]
        for row in (
            db.session.query(SubmissionRecord.id)
            .filter(SubmissionRecord.period_id.in_(period_ids))
            .filter(SubmissionRecord.report_id.isnot(None))
            .filter(
                db.or_(
                    SubmissionRecord.llm_analysis_failed.is_(True),
                    SubmissionRecord.llm_feedback_failed.is_(True),
                )
            )
            .all()
        )
    ]


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
        .filter(SubmissionRecord.report_id.isnot(None))
    )
    if skip_complete:
        q = q.filter(
            SubmissionRecord.language_analysis_started.is_(False),
            SubmissionRecord.language_analysis_complete.is_(False),
        )
    return [row[0] for row in q.all()]


def _populate_redis_queue(job: LLMOrchestrationJob, record_ids: List[int]) -> None:
    """Push *record_ids* into the job's Redis pending queue (left push → right pop = FIFO)."""
    if not record_ids:
        return
    r = _get_orchestration_redis()
    key = job.redis_queue_key
    pipe = r.pipeline()
    for rid in record_ids:
        pipe.lpush(key, rid)
    pipe.execute()


def _get_already_queued_record_ids(r, active_jobs: List[LLMOrchestrationJob]) -> set:
    """
    Return the set of SubmissionRecord IDs currently sitting in any active
    job's Redis pending or inflight queue.
    """
    queued: set = set()
    for job in active_jobs:
        try:
            for raw in r.lrange(job.redis_queue_key, 0, -1):
                queued.add(int(raw))
            for raw in r.lrange(job.redis_inflight_key, 0, -1):
                queued.add(int(raw))
        except Exception as exc:
            current_app.logger.warning(
                f"_get_already_queued_record_ids: Redis error reading job {job.uuid}: {exc}"
            )
    return queued


def _filter_already_queued(record_ids: List[int], caller: str) -> List[int]:
    """
    Remove any record IDs already sitting in an active job's Redis pending or
    inflight queue.  Returns the filtered list.  Falls back to the original
    list on any error so that a Redis connectivity problem never blocks a
    submission.
    """
    try:
        active_jobs = (
            db.session.query(LLMOrchestrationJob)
            .filter(LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES))
            .all()
        )
        if not active_jobs:
            return record_ids
        r = _get_orchestration_redis()
        already_queued = _get_already_queued_record_ids(r, active_jobs)
        if not already_queued:
            return record_ids
        filtered = [rid for rid in record_ids if rid not in already_queued]
        skipped = len(record_ids) - len(filtered)
        if skipped:
            current_app.logger.info(
                f"{caller}: skipped {skipped} record(s) already queued in an active job"
            )
        return filtered
    except Exception as exc:
        current_app.logger.warning(
            f"{caller}: could not check for already-queued records: {exc} "
            f"— proceeding without deduplication"
        )
        return record_ids


def _create_and_dispatch_job(
    scope: str,
    scope_id: Optional[int],
    record_ids: List[int],
    clear_existing: bool,
    user: Optional[User],
    description: str,
    log_message: str,
    **log_db_commit_kwargs,
) -> LLMOrchestrationJob:
    """
    Build, persist, enqueue, and dispatch a single LLMOrchestrationJob.
    Raises SQLAlchemyError (after rollback) on commit failure.
    """
    job = LLMOrchestrationJob.build(
        scope=scope,
        scope_id=scope_id,
        total_count=len(record_ids),
        clear_existing=clear_existing,
        owner=user,
        description=description,
    )
    db.session.add(job)
    db.session.flush()
    _populate_redis_queue(job, record_ids)
    try:
        log_db_commit(log_message, **log_db_commit_kwargs)
    except SQLAlchemyError:
        db.session.rollback()
        raise
    _dispatch_global_coordinator()
    return job


def _dispatch_global_coordinator() -> None:
    """Dispatch global_orchestration_step."""
    celery = current_app.extensions["celery"]
    t = celery.tasks["app.tasks.llm_orchestration.global_orchestration_step"]
    t.apply_async(queue="default")


def _dispatch_analysis_chain(celery, job_uuid: str, record_id: int) -> None:
    """Build and dispatch the full language-analysis chain for *record_id*."""
    t_extract = celery.tasks["app.tasks.language_analysis.download_and_extract"]
    t_stats = celery.tasks["app.tasks.language_analysis.compute_statistics"]
    t_llm = celery.tasks["app.tasks.language_analysis.submit_to_llm"]
    t_feedback = celery.tasks["app.tasks.language_analysis.submit_to_llm_feedback"]
    t_finalize = celery.tasks["app.tasks.language_analysis.finalize"]
    t_done = celery.tasks["app.tasks.llm_orchestration.orchestration_record_done"]
    t_err = celery.tasks["app.tasks.llm_orchestration.orchestration_record_error"]

    work = chain(
        t_extract.si(record_id).set(queue="llm_tasks"),
        t_stats.si(record_id).set(queue="default"),
        t_llm.si(record_id).set(queue="llm_tasks"),
        t_feedback.si(record_id).set(queue="llm_tasks"),
        t_finalize.si(record_id).set(queue="default"),
        t_done.si(job_uuid, record_id).set(queue="default"),
    ).on_error(t_err.si(job_uuid, record_id).set(queue="default"))

    work.apply_async()


def _recover_active_jobs() -> None:
    """
    Called on worker startup to resume any jobs that were active when the
    worker last stopped.

    For each PENDING or RUNNING LLMOrchestrationJob:
      - Any record IDs in the inflight list (llm_inflight:{uuid}) are moved
        back to the pending queue (llm_queue:{uuid}) using RPOPLPUSH so they
        will be re-processed.  See the module-level docstring for the
        double-processing race condition that can arise when a record was
        genuinely in-flight on another worker at the time of this recovery.
      - If the pending queue (after re-queuing) is non-empty, the global
        coordinator is dispatched once to resume processing.

    Jobs whose pending and inflight queues are both empty but whose counters
    have not yet reached total_count are left in RUNNING state; they will be
    cleaned up when their last in-flight chain completes normally.
    """
    try:
        r = _get_orchestration_redis()
    except Exception as exc:
        current_app.logger.error(
            f"!! llm_orchestration._recover_active_jobs: cannot connect to Redis: {exc}"
        )
        return

    try:
        active_jobs: List[LLMOrchestrationJob] = (
            db.session.query(LLMOrchestrationJob)
            .filter(LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES))
            .all()
        )
    except SQLAlchemyError as exc:
        current_app.logger.exception(
            "!! llm_orchestration._recover_active_jobs: SQLAlchemyError loading active jobs",
            exc_info=exc,
        )
        return

    if not active_jobs:
        current_app.logger.info('** llm_orchestration._recover_active_jobs: no active jobs found')
        return

    needs_coordinator = False
    for job in active_jobs:
        current_app.logger.info(f'** llm_orchestration._recover_active_jobs: recovering job {job.uuid} ({job.description})')
        # Move any inflight records back to the pending queue.
        recovered = 0
        try:
            while r.rpoplpush(job.redis_inflight_key, job.redis_queue_key):
                recovered += 1
        except Exception as exc:
            current_app.logger.warning(
                f"!! llm_orchestration._recover_active_jobs: Redis error recovering "
                f"inflight items for job {job.uuid}: {exc}"
            )

        if recovered:
            current_app.logger.info(
                f"@@ llm_orchestration._recover_active_jobs: re-queued {recovered} "
                f"inflight record(s) for job {job.uuid}"
            )
        else:
            current_app.logger.info(
                f"@@ llm_orchestration._recover_active_jobs: did not discover any inflight records for job {job.uuid}"
            )

        # Dispatch the coordinator if this job has pending work.
        try:
            if r.llen(job.redis_queue_key) > 0:
                needs_coordinator = True
        except Exception as exc:
            current_app.logger.warning(
                f"!! llm_orchestration._recover_active_jobs: Redis error checking queue "
                f"length for job {job.uuid}: {exc}"
            )

    if needs_coordinator:
        try:
            _dispatch_global_coordinator()
            current_app.logger.info(
                "@@ llm_orchestration._recover_active_jobs: dispatched global coordinator"
            )
        except Exception as exc:
            current_app.logger.error(
                f"!! llm_orchestration._recover_active_jobs: could not dispatch coordinator: {exc}"
            )
    else:
        current_app.logger.info(f"@@ llm_orchestration._recover_active_jobs: no pending work for job {job.uuid}")


# ---------------------------------------------------------------------------
# Entry-point helpers (called from views and tasks)
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

    record_ids = _filter_already_queued(record_ids, "launch_period_pipeline")
    if not record_ids:
        return None

    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_PERIOD,
        scope_id=period_id,
        record_ids=record_ids,
        clear_existing=clear_existing,
        user=user,
        description=f"Period: {period.display_name}",
        log_message=f"Launched LLM orchestration job (period #{period_id}, {len(record_ids)} records, clear={clear_existing})",
    )


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

    record_ids = _filter_already_queued(record_ids, "launch_pclass_pipeline")
    if not record_ids:
        return None

    pclass_name = (
        config.project_class.abbreviation
        if config.project_class
        else str(pclass_config_id)
    )
    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_PCLASS,
        scope_id=pclass_config_id,
        record_ids=record_ids,
        clear_existing=clear_existing,
        user=user,
        description=f"Project class: {pclass_name} ({config.year}/{config.year + 1})",
        log_message=f"Launched LLM orchestration job (pclass config #{pclass_config_id}, {len(record_ids)} records, clear={clear_existing})",
    )


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
            .join(
                ProjectClassConfig,
                ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
            )
            .filter(ProjectClassConfig.year == year)
            .all()
        )
    ]
    if not period_ids:
        return None

    record_ids = _collect_record_ids(period_ids, skip_complete=not clear_existing)
    if not record_ids:
        return None

    record_ids = _filter_already_queued(record_ids, "launch_cycle_pipeline")
    if not record_ids:
        return None

    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_CYCLE,
        scope_id=year,
        record_ids=record_ids,
        clear_existing=clear_existing,
        user=user,
        description=f"Cycle: {year}/{year + 1}",
        log_message=f"Launched LLM orchestration job (cycle {year}, {len(record_ids)} records, clear={clear_existing})",
    )


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

    record_ids = _filter_already_queued(record_ids, "launch_global_pipeline")
    if not record_ids:
        return None

    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_GLOBAL,
        scope_id=None,
        record_ids=record_ids,
        clear_existing=clear_existing,
        user=user,
        description="Global: all project classes and cycles",
        log_message=f"Launched global LLM orchestration job ({len(record_ids)} records, clear={clear_existing})",
    )


def launch_error_period_pipeline(
    period_id: int,
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job covering only records in the given
    ``SubmissionPeriodRecord`` that have an LLM error flag set.  Each matched
    record is fully reset before being requeued (equivalent to ``clear_existing=True``).

    Returns the created ``LLMOrchestrationJob`` or None if no error records exist.
    """
    period: SubmissionPeriodRecord = (
        db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
    )
    if period is None:
        current_app.logger.error(
            f"launch_error_period_pipeline: SubmissionPeriodRecord #{period_id} not found"
        )
        return None

    record_ids = _collect_error_record_ids([period_id])
    if not record_ids:
        return None

    record_ids = _filter_already_queued(record_ids, "launch_error_period_pipeline")
    if not record_ids:
        return None

    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_PERIOD,
        scope_id=period_id,
        record_ids=record_ids,
        clear_existing=True,
        user=user,
        description=f"Period (errors only): {period.display_name}",
        log_message=f"Launched LLM orchestration job for error records (period #{period_id}, {len(record_ids)} records)",
    )


def launch_error_cycle_pipeline(
    year: int,
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job covering only records in the given
    academic cycle that have an LLM error flag set.
    """
    period_ids = [
        row[0]
        for row in (
            db.session.query(SubmissionPeriodRecord.id)
            .join(
                ProjectClassConfig,
                ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
            )
            .filter(ProjectClassConfig.year == year)
            .all()
        )
    ]
    if not period_ids:
        return None

    record_ids = _collect_error_record_ids(period_ids)
    if not record_ids:
        return None

    record_ids = _filter_already_queued(record_ids, "launch_error_cycle_pipeline")
    if not record_ids:
        return None

    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_CYCLE,
        scope_id=year,
        record_ids=record_ids,
        clear_existing=True,
        user=user,
        description=f"Cycle (errors only): {year}/{year + 1}",
        log_message=f"Launched LLM orchestration job for error records (cycle {year}, {len(record_ids)} records)",
    )


def launch_error_global_pipeline(
    user: Optional[User] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a bulk LLM orchestration job covering every SubmissionRecord in the
    database that has an LLM error flag set.
    """
    period_ids = [row[0] for row in db.session.query(SubmissionPeriodRecord.id).all()]
    if not period_ids:
        return None

    record_ids = _collect_error_record_ids(period_ids)
    if not record_ids:
        return None

    record_ids = _filter_already_queued(record_ids, "launch_error_global_pipeline")
    if not record_ids:
        return None

    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_GLOBAL,
        scope_id=None,
        record_ids=record_ids,
        clear_existing=True,
        user=user,
        description="Global (errors only): all project classes and cycles",
        log_message=f"Launched global LLM orchestration job for error records ({len(record_ids)} records)",
    )


def enqueue_single_record(
    record_id: int,
    user: Optional[User] = None,
    clear_existing: bool = False,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a single-record LLMOrchestrationJob and enqueue it through the
    standard orchestration pipeline.

    Used by ad-hoc submission paths (the per-record launch view and the Canvas
    pull_report workflow) to ensure they are subject to the same batch-size
    limit and fault-tolerance guarantees as bulk submissions.

    *clear_existing=True* is appropriate when the caller has already confirmed
    that the user intends to regenerate all analysis data for this record.

    Returns the created LLMOrchestrationJob or None if the record cannot be
    processed (not found, no report attached, or not eligible).
    """
    try:
        record: SubmissionRecord = (
            db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        )
    except SQLAlchemyError as exc:
        current_app.logger.exception(
            f"enqueue_single_record: SQLAlchemyError loading SubmissionRecord #{record_id}",
            exc_info=exc,
        )
        return None

    if record is None:
        current_app.logger.error(
            f"enqueue_single_record: SubmissionRecord #{record_id} not found"
        )
        return None

    if record.report is None:
        current_app.logger.warning(
            f"enqueue_single_record: SubmissionRecord #{record_id} has no report — skipping"
        )
        return None

    period = record.period
    if period is None:
        current_app.logger.error(
            f"enqueue_single_record: SubmissionRecord #{record_id} has no associated period"
        )
        return None

    record_ids = _filter_already_queued([record_id], "enqueue_single_record")
    if not record_ids:
        return None

    description = f"Single record: {record.owner.student.user.name if record.owner and record.owner.student else f'#{record_id}'}"
    return _create_and_dispatch_job(
        scope=LLMOrchestrationJob.SCOPE_PERIOD,
        scope_id=period.id,
        record_ids=record_ids,
        clear_existing=clear_existing,
        user=user,
        description=description,
        log_message=f"Enqueued single-record LLM orchestration job (SubmissionRecord #{record_id}, clear={clear_existing})",
        student=record.owner.student if record.owner else None,
        project_classes=record.owner.config.project_class if record.owner and record.owner.config else None,
    )


def enqueue_record_list(
    record_ids: List[int],
    scope: str,
    scope_id: Optional[int],
    user: Optional[User] = None,
    clear_existing: bool = False,
    description: Optional[str] = None,
) -> Optional[LLMOrchestrationJob]:
    """
    Create a single LLMOrchestrationJob for a caller-supplied list of
    SubmissionRecord IDs and dispatch it through the standard orchestration
    pipeline.

    Records already queued in an active job are filtered out via
    _filter_already_queued before the job is created, so the job's
    total_count reflects only the records that will actually be processed.

    Returns the created LLMOrchestrationJob, or None if the list is empty
    (or becomes empty after deduplication).
    """
    if not record_ids:
        return None
    record_ids = _filter_already_queued(record_ids, "enqueue_record_list")
    if not record_ids:
        return None
    desc = description or f"Batch submission: {len(record_ids)} records"
    return _create_and_dispatch_job(
        scope=scope,
        scope_id=scope_id,
        record_ids=record_ids,
        clear_existing=clear_existing,
        user=user,
        description=desc,
        log_message=f"Enqueued batch LLM orchestration job: {len(record_ids)} records (scope={scope}, scope_id={scope_id}, clear={clear_existing})",
    )


# ---------------------------------------------------------------------------
# Celery task registration
# ---------------------------------------------------------------------------


def register_llm_orchestration_tasks(celery):

    # ------------------------------------------------------------------
    # worker_ready signal: resume any active jobs after a restart.
    # ------------------------------------------------------------------

    # See the module-level docstring for a full description of the
    # double-processing race condition that can occur here.
    flask_app = celery.flask_app

    # weak=False is required: on_worker_ready is a local function with no
    # module-level reference, so the default weak reference would be garbage
    # collected before worker_ready fires, silently dropping the handler.
    @worker_ready.connect(weak=False)
    def on_worker_ready(sender, **kwargs):
        """
        On worker startup, re-queue any records that were in-flight when the
        worker last stopped and dispatch the global coordinator if needed.

        Uses an explicit app context via celery.flask_app rather than
        current_app, because worker_ready may fire in a thread or forked
        context where the app context pushed in celery_node.py is not visible.
        """
        with flask_app.app_context():
            try:
                _recover_active_jobs()
            except Exception as exc:
                flask_app.logger.exception(
                    "llm_orchestration.on_worker_ready: recovery failed", exc_info=exc
                )

    # ------------------------------------------------------------------
    # orchestration_record_done
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=10)
    def orchestration_record_done(self, job_uuid: str, record_id: int):
        """
        Success callback: called as the last step in a single SubmissionRecord's
        analysis chain.  Removes the record from the inflight list, increments
        the job's completed_count, and triggers the global coordinator.
        """
        # Remove from inflight list first (best-effort: don't let Redis errors
        # block the counter update or the next coordinator dispatch).
        try:
            r = _get_orchestration_redis()
            r.lrem(f"llm_inflight:{job_uuid}", 0, str(record_id).encode())
        except Exception as exc:
            current_app.logger.warning(
                f"llm_orchestration.orchestration_record_done: Redis LREM failed "
                f"for job {job_uuid} / record #{record_id}: {exc}"
            )

        try:
            job: LLMOrchestrationJob = (
                db.session.query(LLMOrchestrationJob).filter_by(uuid=job_uuid).first()
            )
            if job is not None:
                job.increment_completed()
                # Use >= (not ==) to correctly handle the double-processing race
                # where a record may be counted twice after crash recovery.
                # Guard against marking an already-complete job complete a second time.
                if (
                    (job.completed_count + job.failed_count) >= job.total_count
                    and job.status == LLMOrchestrationJob.STATUS_RUNNING
                ):
                    job.mark_complete()
                db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"llm_orchestration.orchestration_record_done: SQLAlchemyError "
                f"for job {job_uuid} / record #{record_id}",
                exc_info=exc,
            )

        _dispatch_global_coordinator()

    # ------------------------------------------------------------------
    # orchestration_record_error
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=10)
    def orchestration_record_error(self, job_uuid: str, record_id: int):
        """
        Error callback: called when a SubmissionRecord's analysis chain raises an
        unhandled exception.  Removes the record from the inflight list, resets
        the record's progress flags, increments the job's failed_count, and
        triggers the global coordinator.
        """
        try:
            r = _get_orchestration_redis()
            r.lrem(f"llm_inflight:{job_uuid}", 0, str(record_id).encode())
        except Exception as exc:
            current_app.logger.warning(
                f"llm_orchestration.orchestration_record_error: Redis LREM failed "
                f"for job {job_uuid} / record #{record_id}: {exc}"
            )

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
                if (
                    (job.completed_count + job.failed_count) >= job.total_count
                    and job.status == LLMOrchestrationJob.STATUS_RUNNING
                ):
                    job.mark_complete()

            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                f"llm_orchestration.orchestration_record_error: SQLAlchemyError "
                f"for job {job_uuid} / record #{record_id}",
                exc_info=exc,
            )

        _dispatch_global_coordinator()

    # ------------------------------------------------------------------
    # global_orchestration_step  (single coordinator for all active jobs)
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def global_orchestration_step(self):
        """
        Global coordinator: fill up to OLLAMA_BATCH_SIZE slots by popping
        records from all active LLMOrchestrationJob queues (round-robin).

        Replaces the former per-job orchestration_step.  Because there is a
        single coordinator, parallel submissions from multiple
        LLMOrchestrationJob instances are serialised under the configured
        batch limit.

        Records are atomically moved from the pending queue to the inflight
        list via RPOPLPUSH; the inflight list is the source of truth for
        in-flight count (sum of LLEN across all active jobs' inflight lists).
        """
        batch_size: int = current_app.config.get("OLLAMA_BATCH_SIZE", 1)

        # ------- load active jobs -------
        try:
            active_jobs: List[LLMOrchestrationJob] = (
                db.session.query(LLMOrchestrationJob)
                .filter(
                    LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES)
                )
                .all()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "llm_orchestration.global_orchestration_step: SQLAlchemyError loading active jobs",
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
                "llm_orchestration.global_orchestration_step: Redis connection error",
                exc_info=exc,
            )
            raise self.retry()

        # ------- check cancellations and transition PENDING → RUNNING -------
        jobs_to_remove = []
        db_changed = False
        for job in active_jobs:
            if job.status == LLMOrchestrationJob.STATUS_FAILED:
                # Manually cancelled by an administrator.
                _cleanup_redis(job)
                jobs_to_remove.append(job)
            elif job.status == LLMOrchestrationJob.STATUS_PENDING:
                job.mark_started()
                db_changed = True
                # Guard: all records may have already completed/failed before the
                # coordinator committed PENDING→RUNNING.  Close the job immediately
                # now that it is officially RUNNING.
                if (job.completed_count + job.failed_count) >= job.total_count:
                    job.mark_complete()
                    jobs_to_remove.append(job)

        # Defensive sweep: catch already-RUNNING jobs whose callbacks all raced past
        # the STATUS_RUNNING guard in a prior coordinator cycle.
        for job in active_jobs:
            if (
                job.status == LLMOrchestrationJob.STATUS_RUNNING
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
                    "llm_orchestration.global_orchestration_step: SQLAlchemyError updating job statuses",
                    exc_info=exc,
                )

        if not active_jobs:
            return

        # ------- compute available slots -------
        try:
            inflight = sum(r.llen(job.redis_inflight_key) for job in active_jobs)
        except Exception as exc:
            current_app.logger.exception(
                "llm_orchestration.global_orchestration_step: Redis error reading inflight counts",
                exc_info=exc,
            )
            raise self.retry()

        available_slots = max(0, batch_size - inflight)
        if available_slots == 0:
            # All slots occupied; will be re-triggered when in-flight records complete.
            return

        # ------- round-robin dispatch -------
        dispatched = 0
        # Loop at most len(active_jobs) times per slot to avoid an infinite loop
        # when all queues are empty.
        max_attempts = len(active_jobs) * available_slots + len(active_jobs)
        attempts = 0
        job_idx = 0

        while dispatched < available_slots and attempts < max_attempts:
            job = active_jobs[job_idx % len(active_jobs)]
            job_idx += 1
            attempts += 1

            # Atomically move record ID from pending queue to inflight list.
            try:
                record_id_bytes = r.rpoplpush(
                    job.redis_queue_key, job.redis_inflight_key
                )
            except Exception as exc:
                current_app.logger.exception(
                    f"llm_orchestration.global_orchestration_step: Redis RPOPLPUSH error "
                    f"for job {job.uuid}",
                    exc_info=exc,
                )
                continue

            if record_id_bytes is None:
                continue  # this job's queue is empty; try the next

            record_id = int(record_id_bytes)

            # ------- load and validate record -------
            try:
                record: SubmissionRecord = (
                    db.session.query(SubmissionRecord).filter_by(id=record_id).first()
                )
            except SQLAlchemyError as exc:
                current_app.logger.exception(
                    f"llm_orchestration.global_orchestration_step: SQLAlchemyError loading "
                    f"SubmissionRecord #{record_id}",
                    exc_info=exc,
                )
                r.lrem(job.redis_inflight_key, 0, record_id_bytes)
                try:
                    job.increment_failed()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                dispatched += 1  # consumed a slot even on error to make progress
                continue

            if record is None or record.report is None:
                current_app.logger.warning(
                    f"llm_orchestration.global_orchestration_step: skipping "
                    f"SubmissionRecord #{record_id} (not found or no report)"
                )
                r.lrem(job.redis_inflight_key, 0, record_id_bytes)
                try:
                    job.increment_failed()
                    if (
                        (job.completed_count + job.failed_count) >= job.total_count
                        and job.status == LLMOrchestrationJob.STATUS_RUNNING
                    ):
                        job.mark_complete()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                dispatched += 1
                continue

            # ------- optionally clear existing results -------
            if job.clear_existing:
                _clear_record_state(record)

            # ------- prepare record for (re-)submission -------
            record.language_analysis_started = True
            record.language_analysis_complete = False
            record.llm_analysis_failed = False
            record.llm_failure_reason = None
            record.llm_feedback_failed = None  # None = feedback not yet attempted on this run
            record.llm_feedback_failure_reason = None

            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.exception(
                    f"llm_orchestration.global_orchestration_step: SQLAlchemyError resetting "
                    f"SubmissionRecord #{record_id}",
                    exc_info=exc,
                )
                r.lrem(job.redis_inflight_key, 0, record_id_bytes)
                try:
                    job.increment_failed()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                dispatched += 1
                continue

            # ------- dispatch the analysis chain -------
            _dispatch_analysis_chain(celery, job.uuid, record_id)
            dispatched += 1

    # ------------------------------------------------------------------
    # llm_watchdog
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=60)
    def llm_watchdog(self):
        """
        Periodic watchdog: recover any stalled LLMOrchestrationJob instances.

        Calls _recover_active_jobs(), which moves any records that are stuck in the
        inflight Redis list back to the pending queue and re-dispatches the global
        coordinator.  Intended to run every ~30 minutes via the DatabaseScheduler
        Beat schedule, providing automatic recovery without requiring a manual
        worker restart.

        Accepts the double-processing race documented in the module-level docstring:
        if a record is genuinely in-flight at the time the watchdog fires, it is
        re-queued and may be processed twice.  This is safe but wasteful; the last
        writer wins and orchestration_record_done's >= total_count guard prevents
        double-completion.
        """
        try:
            _recover_active_jobs()
        except Exception as exc:
            current_app.logger.exception(
                "llm_orchestration.llm_watchdog: recovery failed", exc_info=exc
            )
            raise self.retry()

    return (
        global_orchestration_step,
        orchestration_record_done,
        orchestration_record_error,
        llm_watchdog,
    )
