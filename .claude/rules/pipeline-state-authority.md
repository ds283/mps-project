---
paths:
  - app/tasks/**
  - app/models/submissions.py
  - app/dashboards/views.py
  - app/documents/views.py
---

# Pipeline state authority model

## Core principle

`SubmissionRecord` (SQL) is the **sole source of truth** for whether a pipeline output exists
and at what version. MongoDB is a **pure cache**: a document there is valid if and only if
the corresponding SQL presence flags and version columns say it is. Never treat a MongoDB
document's existence or `updated_at` timestamp as authoritative.

## Presence flags and version columns

Eight columns on `SubmissionRecord` track individual pipeline outputs:

| Output             | Presence flag          | Version column                | Code constant                                                |
|--------------------|------------------------|-------------------------------|--------------------------------------------------------------|
| Lexical statistics | `stats_present`        | `stats_algorithm_version`     | `STATS_ALGORITHM_VERSION` (`language_analysis.py`)           |
| LLM grading        | `llm_grading_present`  | `llm_prompt_version`          | `PROMPT_VERSION` (`language_analysis.py`)                    |
| LLM feedback       | `llm_feedback_present` | `llm_feedback_prompt_version` | `PROMPT_VERSION` (same constant)                             |
| Similarity chunks  | `chunks_present`       | `chunks_prompt_version`       | `CHUNK_EXTRACTION_PROMPT_VERSION` (`similarity_analysis.py`) |

`language_analysis_complete` and `similarity_complete` are **kept as aggregated convenience
flags** for backward compatibility and for queries that don't need fine-grained detail:

- `language_analysis_complete` ≡ `stats_present AND llm_grading_present AND llm_feedback_present`
- `similarity_complete` is set by `finalize_risk_flags` after the similarity scan completes

Do **not** replace these with the individual flags — both levels are used by different parts of
the codebase.

## Idempotency pattern for pipeline steps

Every pipeline step must guard itself before running and set its flags on success:

```python
# Before running:
if record.stats_present and record.stats_algorithm_version == STATS_ALGORITHM_VERSION:
    record_step_end(...)
    return  # already done at current version — skip

# ... do the work ...

# On success, before commit:
record.stats_present = True
record.stats_algorithm_version = STATS_ALGORITHM_VERSION
```

**Skip condition**: presence flag is True AND stored version == current code constant.
**Force re-run**: bump the code constant — all records where the stored version no longer
matches will re-run automatically on next dispatch.

## Invalidation rules

When a presence flag is cleared (by `_clear_record_state`, a recovery action, or a version
bump), the corresponding cached data must also be removed or marked stale:

| Flag cleared           | Required cleanup                                                                                                                                       |
|------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| All flags (full reset) | `delete_scraped_text(record.id)` — removes the whole MongoDB document                                                                                  |
| `chunks_present` only  | `delete_similarity_chunks(record.id)` — removes the subdocument; also reset `similarity_complete=False` and delete unreviewed `SimilarityConcern` rows |
| `llm_grading_present`  | Also clear `llm_feedback_present` / `llm_feedback_prompt_version` — feedback is derived from grading output and is stale if grading re-runs            |
| `stats_present`        | No MongoDB cleanup needed (stats live in the SQL JSON blob)                                                                                            |

`_clear_record_state()` in `llm_orchestration.py` handles the full-reset case. Partial resets
(single-step recovery views) must handle their own cleanup.

## Cascade on chunk version bump

When `CHUNK_EXTRACTION_PROMPT_VERSION` is incremented, `extract_chunks` detects
`chunks_prompt_version != CHUNK_EXTRACTION_PROMPT_VERSION` and:

1. Deletes unreviewed `SimilarityConcern` rows for this record (reviewed concerns are preserved)
2. Resets `similarity_complete = False`, `chunks_present = False`, `chunks_prompt_version = None`
3. Re-extracts chunks and sets the new version on success

`compute_minhash` and `run_similarity_check` follow automatically from the updated chunks.

## Recovery paths

Two recovery paths are offered wherever an error state can be cleared:

**"Retry with cached data"** — clears error flags and the presence flags for the failed step
only; leaves scraped text in MongoDB intact.  `download_and_extract` will skip (asset_id
guard) and successfully-completed steps will skip via their presence-flag guards. Use when
the underlying report is probably fine and only the processing step failed.

**"Full reset and resubmit"** — calls `_clear_record_state()`, which resets all SQL flags and
deletes the MongoDB document. The pipeline re-runs from scratch. Use when the asset itself
may be problematic or a clean slate is required.

The choice of path is left to the administrator. The code cannot reliably classify errors as
"input" vs "algorithm" at the point they surface — the same failure mode (e.g. LLM stalling
on repeated "..." sequences from a contents page) can arise from both.

## Chunking errors vs LLM errors

These are handled by different routes and displayed separately in the UI:

- **LLM analysis/feedback errors** (`llm_analysis_failed`, `llm_feedback_failed`): managed by
  the AI dashboard's error-recovery buttons (`clear_errors_*`, `retry_errors_*`,
  `resubmit_errors_*`).
- **Chunking errors** (`llm_chunking_failed`): managed by the Similarity dashboard
  (`clear_chunking_errors_global`, `resubmit_chunking_errors_global`).

Do not mix these into a single bulk action — a record with `language_analysis_complete=True`
and only `llm_chunking_failed=True` should not have its language analysis wiped by an
LLM-error bulk action.

## Adding a new pipeline step

1. Add a presence flag + version column to `SubmissionRecord` (Boolean NOT NULL DEFAULT FALSE,
   Integer nullable) and write a hand-crafted Alembic migration.
2. Add a code constant for the algorithm/prompt version in the relevant task file.
3. Apply the idempotency pattern (skip if flag + version match; set on success).
4. Add the flag to `_clear_record_state()` (reset to False/None).
5. Add the flag to `_retry_clear_error_flags()` in `llm_orchestration.py` if the step can fail.
6. Update `_aggregate_records()` in `dashboards/views.py` to count missing outputs.
7. Follow the pipeline instrumentation rules (`pipeline-instrumentation.md`) to add step
   timing via `record_step_start` / `record_step_end`.
