#
# Created by David Seery on 08/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import time
from datetime import datetime

import redis as redis_lib
from flask import current_app

_STEP_KEY_PREFIX = "llm_step"
_STEP_TTL = 86400  # 24 h safety expiry on Redis hashes


def get_pipeline_redis() -> redis_lib.Redis:
    """Return a Redis client for pipeline step tracking (same DB as orchestration)."""
    url = current_app.config.get("ORCHESTRATION_REDIS_URL")
    if not url:
        raise RuntimeError("ORCHESTRATION_REDIS_URL is not set in the Flask configuration")
    return redis_lib.Redis.from_url(url, decode_responses=False)


def step_key(record_id: int) -> str:
    return f"{_STEP_KEY_PREFIX}:{record_id}"


def record_step_start(redis_client, record_id: int, step: str) -> float:
    """
    Mark *step* as started for *record_id*.

    Sets ``_record_started_at`` on the first call for this record (idempotent
    via HSETNX so a retry does not overwrite the original start time).
    Returns the monotonic clock value at start so the caller can compute
    elapsed time via :func:`record_step_end`.

    If *redis_client* is ``None`` the call is a silent no-op (step tracking
    is best-effort and must never block task execution).
    """
    t0 = time.monotonic()
    if redis_client is None:
        return t0
    try:
        ts = datetime.now().isoformat(timespec="milliseconds")
        redis_client.hsetnx(step_key(record_id), "_record_started_at", ts)
        redis_client.hset(step_key(record_id), f"{step}:started_at", ts)
        redis_client.expire(step_key(record_id), _STEP_TTL)
    except Exception:
        pass
    return t0


def record_step_end(
    redis_client,
    record_id: int,
    step: str,
    t0: float,
    error: str | None = None,
) -> None:
    """
    Record that *step* has finished for *record_id*.

    *t0* must be the value returned by the matching :func:`record_step_start`
    call so that elapsed time can be computed accurately.

    If *redis_client* is ``None`` the call is a silent no-op.
    """
    if redis_client is None:
        return
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    try:
        redis_client.hset(step_key(record_id), f"{step}:elapsed_ms", elapsed_ms)
        if error:
            redis_client.hset(step_key(record_id), f"{step}:error", error)
    except Exception:
        pass


# Ordered list of all pipeline step names, used when reconstructing
# a workflow summary from a Redis hash.
PIPELINE_STEPS = [
    "download_and_extract",
    "compute_statistics",
    "submit_to_llm",
    "submit_to_llm_feedback",
    "finalize_language_step",
    "extract_chunks",
    "compute_minhash",
    "run_similarity_check",
    "finalize_risk_flags",
]


def read_workflow_entry(redis_client, record_id: int) -> dict:
    """
    Read the Redis hash for *record_id* and return a workflow-summary dict
    suitable for storing in ``LLMOrchestrationJob.recent_workflows``.

    The returned dict has the shape::

        {
          "record_id":   int,
          "started_at":  str | None,   # ISO timestamp of first step
          "steps": [
            {"name": str, "started_at": str | None,
             "elapsed_ms": int | None, "error": str | None},
            ...
          ]
        }

    Only steps that have a ``started_at`` entry in the hash are included.
    """
    raw: dict = redis_client.hgetall(step_key(record_id))
    if not raw:
        return {"record_id": record_id, "started_at": None, "steps": []}

    def _decode(v) -> str:
        return v.decode() if isinstance(v, bytes) else v

    fields = {_decode(k): _decode(v) for k, v in raw.items()}

    steps = []
    for name in PIPELINE_STEPS:
        started = fields.get(f"{name}:started_at")
        if started is None:
            continue
        elapsed_raw = fields.get(f"{name}:elapsed_ms")
        steps.append(
            {
                "name": name,
                "started_at": started,
                "elapsed_ms": int(elapsed_raw) if elapsed_raw is not None else None,
                "error": fields.get(f"{name}:error"),
            }
        )

    return {
        "record_id": record_id,
        "started_at": fields.get("_record_started_at"),
        "steps": steps,
    }


def delete_workflow_hash(redis_client, record_id: int) -> None:
    redis_client.delete(step_key(record_id))
