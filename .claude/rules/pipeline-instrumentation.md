---
paths:
  - app/tasks/**
---

# Pipeline step instrumentation

## Overview

The language-analysis and similarity-analysis pipeline is managed by `LLMOrchestrationJob`
(`app/models/llm_orchestration.py`). Per-record step timing is captured in Redis during
execution and serialised into `recent_workflows` on the job at completion.

The canonical list of instrumented steps lives in `app/tasks/pipeline_tracking.py`:

```python
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
```

Each step corresponds to a Celery task function in `app/tasks/language_analysis.py` or
`app/tasks/similarity_analysis.py`.

## Rule

**Whenever you add, remove, rename, or reorder a pipeline task** (i.e. any Celery task
that runs as part of the per-record chain dispatched by `LLMOrchestrationJob`), you must
also:

1. **Update `PIPELINE_STEPS`** in `app/tasks/pipeline_tracking.py` to reflect the change.
   The list controls which steps are displayed in the workflow viewer and in what order.

2. **Add/remove step instrumentation** in the affected task function using the pattern:

   ```python
   from .pipeline_tracking import get_pipeline_redis, record_step_start, record_step_end

   _r = None
   try:
       _r = get_pipeline_redis()
   except Exception:
       pass
   _t0 = record_step_start(_r, record_id, "step_name")
   try:
       # ... task body ...
       record_step_end(_r, record_id, "step_name", _t0)
   except Exception as exc:
       record_step_end(_r, record_id, "step_name", _t0, error=repr(exc))
       raise
   ```

   Instrumentation calls are best-effort: a `None` Redis client is silently ignored,
   so Redis unavailability cannot block pipeline execution.

3. **Consider error reporting** — if the new task is a site where a `SubmissionRecord`
   can fail in a way that should be surfaced in the job error log, call
   `job.append_error(record, stage="step_name", exc_type=..., message=...)` at the
   appropriate failure site in `app/tasks/llm_orchestration.py`.

## Files to check on pipeline changes

| File | What to check |
|---|---|
| `app/tasks/pipeline_tracking.py` | `PIPELINE_STEPS` list |
| `app/tasks/language_analysis.py` | `record_step_start` / `record_step_end` calls |
| `app/tasks/similarity_analysis.py` | `record_step_start` / `record_step_end` calls |
| `app/tasks/llm_orchestration.py` | `job.append_error()` calls at failure sites |
