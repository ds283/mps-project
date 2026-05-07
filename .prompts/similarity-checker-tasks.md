# Claude Code Prompt: Similarity Analysis Pipeline

## Context

This is a Flask/Celery/SQLAlchemy academic project management platform. You are adding a
**plagiarism / similarity detection pipeline** that runs alongside the existing language
analysis pipeline.

The existing language analysis pipeline in `language_analysis.py` is the primary reference
for all conventions, patterns, and style. Read it carefully before writing any code.

Key files to read first:

- `language_analysis.py` — primary reference: task registration factory, chain structure,
  `_call_llm`, `_split_document`, `_strip_math_lines`, scraped-text cache usage, error
  handling, DB session lifecycle, `llm_tasks` queue, `default_retry_delay`,
  `soft_time_limit`/`time_limit` guards, coordinator pattern via `recalculate_ai_concern`
- `llm_orchestration.py` — `LLMOrchestrationJob` model: Redis queue/inflight keys, scope
  constants, status constants, `build()` factory, counter helpers
- `feedback_orchestration.py` — second orchestration model reference (same pattern,
  simpler scope)
- `scraped_text_store.py` — `get_scraped_text()`, `store_scraped_text()`, MongoDB
  collection access pattern (open/close client per call, config keys)
- `canvas.py` — how `pull_report_finalize_batch` deliberately defers `LLMOrchestrationJob`
  creation to `pull_all_reports_summary`, so that a batch of records shares a single job;
  how `enqueue_single_record` and `enqueue_record_list` are called as the sole entry points
  for dispatching the LLM pipeline

---

## Architectural overview

### LLM serialisation constraint

The LLM server is low-resource and can handle only one document at a time.
`LLMOrchestrationJob` exists to enforce this by serialising all LLM submissions through a
Redis queue. **Any task that submits text to the LLM must be dispatched through this
mechanism, not fired independently.**

### How the similarity pipeline fits into the existing chain

The similarity pipeline has one LLM stage (`extract_chunks`) and two CPU stages
(`compute_minhash`, `run_similarity_check`). The LLM stage must be serialised through the
same `llm_tasks` queue as the existing language analysis stages.

The correct approach is to **extend the existing per-record chain** rather than dispatch a
separate pipeline from `language_analysis.finalize`. The full per-record sequence becomes:

```
[llm_tasks]   download_and_extract          ← existing
[default]     compute_statistics            ← existing
[llm_tasks]   submit_to_llm                 ← existing
[llm_tasks]   submit_to_llm_feedback        ← existing
[default]     finalize                      ← existing (no longer dispatches anything)
[llm_tasks]   extract_chunks                ← NEW
[default]     compute_minhash               ← NEW
[default]     run_similarity_check          ← NEW
```

The chain is assembled in `enqueue_single_record` and `enqueue_record_list` (in
`app/tasks/llm_orchestration.py`). These are the **only** places where the per-record
chain is built. Both must be updated to append the three new stages.

`language_analysis.finalize` must **not** dispatch anything for the similarity pipeline.
Remove any `_dispatch_similarity_analysis` call from `finalize` — the chain continuation
handles it automatically.

### Standalone rebuild

`SimilarityOrchestrationJob` is used exclusively for standalone similarity rebuild jobs
(re-indexing existing records without re-running language analysis). It drives its own
coordinator task that dispatches only the three-task similarity sub-chain
(`extract_chunks → compute_minhash → run_similarity_check`) for each record. Because
`extract_chunks` is pinned to `llm_tasks`, rebuild LLM calls are naturally serialised
alongside live submissions through the same queue.

---

## What to build

### 1. Refactor shared LLM and text-processing helpers

`language_analysis.py` currently contains `_call_llm`, `_split_document`, and
`_strip_math_lines` as module-level functions. `similarity_analysis.py` needs all three.
To avoid duplication or circular imports, **move these functions** to a new shared module:

```
app/shared/llm_services.py    ← _call_llm
app/shared/text_utils.py      ← _split_document, _strip_math_lines
                                 (and any other pure text helpers needed by both files)
```

Update `language_analysis.py` to import from these new locations. The functions themselves
are unchanged — this is purely a relocation. Confirm there are no circular imports after
the move.

---

### 2. New SQL models

Add to `models.py` or a new `similarity_models.py`.

#### `SimilarityOrchestrationJob`

Modelled exactly on `LLMOrchestrationJob`. Differences from that model:

- Table name: `similarity_orchestration_job`
- Redis key prefixes: `similarity_queue:` and `similarity_inflight:`
- Scopes: same four constants (`period`, `pclass`, `cycle`, `global`)
- One additional column:
  ```python
  rebuild_mode = db.Column(db.Boolean(), nullable=False, default=False)
  ```
  When `True`, this job is a standalone rebuild (similarity only, no language analysis
  rerun). When `False`, this job was created as part of a normal submission flow — reserved
  for future use; the normal flow uses `LLMOrchestrationJob` as the controlling job.
- All other columns, constants, properties, and methods identical to `LLMOrchestrationJob`

#### `SimilarityConcern`

```python
__tablename__ = "similarity_concerns"

id
Integer, primary
key
record_a_id
Integer, ForeignKey("submission_records.id"), index = True, not null
record_b_id
Integer, ForeignKey("submission_records.id"), index = True, not null
chunk_type
String(40)  # one of CHUNK_TYPES
minhash_jaccard
Float  # estimated Jaccard similarity from MinHash signatures
transformer_cosine
Float  # sentence-transformers cosine similarity (0.0–1.0)
created_at
DateTime, default = datetime.now, not null
reviewed
Boolean, nullable = False, default = False
reviewed_by_id
Integer, ForeignKey("users.id"), nullable = True
reviewed_at
DateTime, nullable = True
resolution
String(20), nullable = True  # "cleared" | "referred" | "escalated"
resolution_note
Text, nullable = True
```

Constraints:

- Unique constraint on `(record_a_id, record_b_id, chunk_type)`.
- **Always store with `record_a_id < record_b_id`** (lower integer ID first) to avoid
  storing both directions of the same pair.
- `record_a` and `record_b` relationships to `SubmissionRecord`, both `uselist=False`,
  with `foreign_keys` specified explicitly (two FKs to the same table).
- `reviewed_by` relationship to `User`, `uselist=False`.

---

### 3. Extend `scraped_text_store.py`

Add three helpers alongside the existing `store_scraped_text` / `get_scraped_text`.
All three follow the identical open/close-client-per-call pattern.

```python
def store_similarity_chunks(record_id: int, sections: dict, model_name: str) -> bool:
    """
    Upsert chunk extraction results into the scraped-text Mongo document.

    *sections* is a dict keyed by chunk type (one key per entry in CHUNK_TYPES),
    each value being:
        {
          "text":        str,           # extracted prose; empty string if not present
          "present":     bool,
          "embedded_in": str | None,    # e.g. "introduction" if nested inside it
          "contains":    list[str],     # e.g. ["literature_review"] if this section
                                        # contains another as a subsection
        }

    Writes under the key "similarity_chunks" in the existing Mongo document,
    with sub-keys "sections", "extracted_at", "extraction_model", and
    "chunk_prompt_version". Creates the document if it does not yet exist
    (same upsert semantics as store_scraped_text).
    """


def get_similarity_chunks(record_id: int) -> dict | None:
    """
    Retrieve the "similarity_chunks" subdocument for *record_id*.

    Returns the subdocument dict (containing "sections", "extracted_at",
    "extraction_model", "chunk_prompt_version", and optionally
    "minhash_signatures" and "minhash_computed_at"), or None on cache miss
    or if the key is absent from the document.
    """


def store_minhash_signatures(record_id: int, signatures: dict) -> bool:
    """
    Upsert MinHash signatures into the "similarity_chunks" subdocument.

    *signatures* is a dict keyed by chunk type (present chunks only), each
    value being a list of ints (the MinHash signature hashvalues array).

    Writes "similarity_chunks.minhash_signatures" and
    "similarity_chunks.minhash_computed_at" using a targeted $set so that
    the rest of the similarity_chunks subdocument is not overwritten.
    """
```

---

### 4. Update `enqueue_single_record` and `enqueue_record_list`

These functions (in `app/tasks/llm_orchestration.py`) currently build the per-record
Celery chain. Extend each to append the similarity stages at the end:

```python
# After the existing finalize task in the chain:
| extract_chunks.si(record_id)
| compute_minhash.si(record_id)
| run_similarity_check.si(record_id)
```

The chain assembly is the only change needed here. Do not alter the orchestration job
creation logic, the Redis queue/inflight management, or the coordinator task.

---

### 5. New file: `similarity_analysis.py`

Header, prompt versioning, and constants:

```python
# Created by ... (same header style as all other files)

CHUNK_EXTRACTION_PROMPT_VERSION = 1


def _chunk_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


CHUNK_TYPES = [
    "introduction",
    "literature_review",
    "methodology",
    "results",
    "discussion",
]

# Per-chunk cosine similarity thresholds for raising a SimilarityConcern.
# Higher value = flag only at higher similarity (more conservative).
# Lower value = flag at lower similarity (more sensitive).
# Results and discussion sections are held to a higher standard because shared
# content there is least explainable by coincidence.
CHUNK_SIMILARITY_THRESHOLD = {
    "introduction": 0.80,
    "literature_review": 0.82,
    "methodology": 0.78,
    "results": 0.88,
    "discussion": 0.85,
}

# LSH first-pass threshold. Deliberately permissive: its only job is to prune
# the O(n²) comparison space. False negatives here are unrecoverable; false
# positives are cheap (just an extra sentence-transformer call).
MINHASH_LSH_THRESHOLD = 0.15
MINHASH_NUM_PERM = 128
```

Register all tasks inside the factory function:

```python
def register_similarity_analysis_tasks(celery):
    ...
```

#### Lazy model loader

```python
_st_model = None


def _get_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model
```

Same pattern as `_get_nlp()` in `language_analysis.py` — loaded once per worker process
on first use.

#### LLM prompt for chunk extraction

Build a `_build_chunk_extraction_system_prompt()` function that returns a system prompt
instructing the LLM to:

1. Identify each of the five logical sections by **content**, not by heading text. The
   section may have a non-standard name or no heading at all.
2. For the literature review specifically: if it is embedded inside the introduction (or
   another section) rather than standing alone, still extract its text separately, set
   `embedded_in` to the name of the containing section, and add `"literature_review"` to
   the `contains` list of the parent.
3. Return a JSON object with **exactly one key per chunk type** in `CHUNK_TYPES`.
   Each value must conform to:
   ```json
   {
     "present":     true | false,
     "text":        "extracted prose (empty string if not present)",
     "embedded_in": null | "<parent_chunk_type>",
     "contains":    [] | ["literature_review"]
   }
   ```
4. If a section is genuinely absent, set `present: false` and `text: ""`. Do not
   fabricate content.
5. The reference list has already been stripped and is not present in the submitted text.

Enforce the response schema via `response_format` / `json_schema` exactly as `_call_llm`
does in `language_analysis.py`. Build the JSON schema programmatically from `CHUNK_TYPES`
so that adding a new chunk type automatically extends the schema.

#### Tasks inside `register_similarity_analysis_tasks`

---

**Task 1: `extract_chunks`** — queue: `llm_tasks`
`soft_time_limit=3600, time_limit=3660, bind=True, default_retry_delay=30`

This task is the LLM stage. It runs as part of the main per-record chain (appended by
`enqueue_single_record` / `enqueue_record_list`) and also as part of the standalone rebuild
chain dispatched by the `SimilarityOrchestrationJob` coordinator.

Steps:

1. Load `SubmissionRecord` from DB. If `language_analysis_complete` is `False`, log a
   warning and return without error — this is a guard, not the primary sequencing
   mechanism (chain ordering guarantees the language analysis finishes first in normal
   operation).
2. Check `get_similarity_chunks(record_id)`. If a result is already present and
   `chunk_prompt_version` matches `CHUNK_EXTRACTION_PROMPT_VERSION`, log at `info` and
   return (idempotent — avoids redundant LLM calls on rebuild).
3. Retrieve scraped text via `get_scraped_text(record_id)`. If `None`, log a warning
   and return (non-fatal cache miss).
4. Call `_split_document(raw_text)` (imported from `app/shared/text_utils.py`) to strip
   the reference list. Submit `_core` only.
5. Apply `_strip_math_lines(_core)` (same import).
6. Read `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_CONTEXT_SIZE` from `current_app.config`.
7. Close the DB session before the LLM call (same pattern as `submit_to_llm` in
   `language_analysis.py` — prevents connection staleness during a long inference).
8. Call `_call_llm` (imported from `app/shared/llm_services.py`) with:
    - the chunk extraction system prompt
    - a user prompt wrapping the cleaned core text
    - the programmatically built JSON schema
    - `label=f"extract_chunks (record #{record_id})"`
9. On LLM success: call
   `store_similarity_chunks(record_id, parsed_result, model)`.
   Also store `CHUNK_EXTRACTION_PROMPT_VERSION` in the subdocument.
10. On LLM failure: log with `current_app.logger.error`. Do not raise — this is
    non-fatal. The record will be retried on the next rebuild pass.
11. Reload the DB session. Raise `self.retry()` only on `SQLAlchemyError`.

---

**Task 2: `compute_minhash`** — queue: `default`
`bind=True, default_retry_delay=30`

1. Call `get_similarity_chunks(record_id)`. If `None` or no sections present, log at
   `warning` and return.
2. If `minhash_signatures` is already present in the returned subdocument and
   `minhash_computed_at` is newer than `extracted_at`, return (idempotent).
3. For each chunk type where `present == True`:
    - Tokenise the chunk text into overlapping word trigrams (shingles, n=3, sliding
      window). Use whitespace tokenisation.
    - Compute a `datasketch.MinHash(num_perm=MINHASH_NUM_PERM)` from the shingle set.
4. Call `store_minhash_signatures(record_id, {chunk_type: sig.hashvalues.tolist(), ...})`
   for all present chunks.
5. Errors per chunk are non-fatal — log at `warning` and continue.
6. Raise `self.retry()` only on `SQLAlchemyError` (from any DB access needed to look
   up config).

---

**Task 3: `run_similarity_check`** — queue: `default`
`bind=True, default_retry_delay=30`

This task compares the current record's chunks against all prior indexed records.

1. Call `get_similarity_chunks(record_id)`. If no `minhash_signatures` present, log at
   `warning` and return.
2. Query MongoDB for all *other* records' similarity chunk subdocuments that have
   `minhash_signatures` populated:
   ```python
   collection.find(
       {"submission_record_id": {"$ne": record_id},
        "similarity_chunks.minhash_signatures": {"$exists": True}},
       projection={"submission_record_id": 1, "similarity_chunks": 1, "_id": 0}
   )
   ```
3. For each chunk type present in the current record:
   a. Build a fresh `datasketch.MinHashLSH(threshold=MINHASH_LSH_THRESHOLD,
      num_perm=MINHASH_NUM_PERM)`.
   b. Insert each prior record's signature for this chunk type into the LSH index,
   keyed by `submission_record_id`. Skip prior records that lack a signature for
   this chunk type.
   c. Query the LSH index with the current record's signature to get the candidate set.
   d. For each candidate: reconstruct both `datasketch.MinHash` objects from stored
   hashvalue lists and call `.jaccard()` to get the estimated Jaccard similarity.
   e. Retain candidates where Jaccard ≥ `MINHASH_LSH_THRESHOLD`.
4. For each retained candidate pair, compute cosine similarity using the
   sentence-transformers model (`_get_st_model()`):
    - Encode both chunk texts with `.encode()`.
    - Compute cosine similarity with `util.cos_sim()` or equivalent.
5. For each pair where cosine similarity ≥ `CHUNK_SIMILARITY_THRESHOLD[chunk_type]`:
   a. Determine canonical ordering: `a_id = min(record_id, other_id)`,
   `b_id = max(record_id, other_id)`.
   b. Upsert a `SimilarityConcern` row keyed on `(record_a_id, record_b_id,
      chunk_type)` using `on_conflict_do_update`. On conflict, update only
   `minhash_jaccard`, `transformer_cosine`, and `created_at`. **Never reset**
   `reviewed`, `reviewed_by_id`, `reviewed_at`, `resolution`, or `resolution_note`
   — a human may have already acted on this record.
   c. Set the `similarity_flagged` risk factor on **both** `SubmissionRecord` rows.
   Follow the existing risk factor blob schema exactly:
      ```python
      {
          "present": True, "resolved": False,
          "resolved_by_id": None, "resolved_at": None, "annotation": None
      }
      ```
   Call `record.compute_risk_factors(config)` on each record after updating
   the blob.
6. Commit in a single transaction after processing all chunk types.
7. Raise `self.retry()` on `SQLAlchemyError`.

---

**Task 4: `similarity_rebuild_coordinator`** — queue: `default`
`bind=True, default_retry_delay=30`

This is the coordinator for `SimilarityOrchestrationJob`. It is the direct analogue of
the LLM coordinator in `llm_orchestration.py` and follows the same Redis queue/inflight
pattern.

Accepts: `job_id: int`

1. Load the `SimilarityOrchestrationJob` from DB. Mark it as running.
2. Use `job.redis_queue_key` as the Redis list. Pop one `record_id` at a time from the
   right (RPOP) and dispatch the three-task chain:
   ```python
   chain(
       extract_chunks.si(record_id),
       compute_minhash.si(record_id),
       run_similarity_check.si(record_id),
   ).apply_async()
   ```
   Move each dispatched ID to `job.redis_inflight_key` (RPOPLPUSH semantics) exactly as
   the LLM coordinator does.
3. The coordinator re-queues itself (via `self.replace` or `apply_async`) until the Redis
   queue is empty, then marks the job complete.
4. Per-record completion/failure signals are sent back via the same counter mechanism used
   by `LLMOrchestrationJob` (`increment_completed` / `increment_failed`).

---

**Task 5: `launch_similarity_rebuild`** — queue: `default`
`bind=True, default_retry_delay=30`

This is the admin-triggered entry point for a standalone rebuild. It creates a
`SimilarityOrchestrationJob`, populates the Redis queue, and starts the coordinator.

Accepts: `task_id: str`, `user_id: int`, `record_ids: list[int] | None = None`,
`scope: str = SimilarityOrchestrationJob.SCOPE_GLOBAL`,
`scope_id: int | None = None`

Steps:

1. If `record_ids` is `None`, query all `SubmissionRecord` rows where
   `language_analysis_complete == True`.
2. Filter to records that need work:
    - Records where `get_similarity_chunks` returns `None` **or** where
      `chunk_prompt_version` does not match `CHUNK_EXTRACTION_PROMPT_VERSION` need
      `extract_chunks` (and the subsequent stages).
    - Records where `similarity_chunks` is present but `minhash_signatures` is absent
      need only `compute_minhash` and `run_similarity_check`. These can be dispatched
      directly as a two-task chain without going through the LLM queue — add a
      `rebuild_compute_only` boolean flag to the Redis queue entries to signal this.
3. Create a `SimilarityOrchestrationJob` with `rebuild_mode=True` and push all target
   record IDs onto `job.redis_queue_key`.
4. Dispatch `similarity_rebuild_coordinator.si(job.id)`.
5. Update progress via `progress_update(task_id, ...)` throughout.

The task is idempotent: re-running creates a new job but the upsert semantics in
`run_similarity_check` prevent duplicate `SimilarityConcern` rows.

Note: `recalculate_ai_concern_batch` in `language_analysis.py` may populate the
scraped-text MongoDB cache as a side effect (on cache miss, it re-downloads and calls
`store_scraped_text`). This leaves the Mongo document with `scraped_text` but no
`similarity_chunks`. Step 2 above correctly handles this case: such records will have
`get_similarity_chunks` return `None` and will be queued for the full three-task chain.

---

### 6. Do not modify `language_analysis.finalize`

`finalize` marks `language_analysis_complete = True`, calls `compute_risk_factors`, and
dispatches `process_report`. It must **not** dispatch the similarity pipeline. The chain
continuation handles that automatically via the stages appended in step 4 above.

---

## Conventions to follow (non-negotiable)

- **DB session lifecycle**: close the session before any long-running LLM or
  CPU-intensive call; reload the record with `db.session.get(SubmissionRecord, record_id)`
  before the final write. Follow `submit_to_llm` in `language_analysis.py` exactly.
- **Retry on SQLAlchemy errors**: `raise self.retry()` on `SQLAlchemyError` in any task
  that touches the DB. `default_retry_delay=30` on all tasks.
- **Non-fatal LLM failures**: `extract_chunks` failure must be logged but must not abort
  the chain. The remaining CPU stages (`compute_minhash`, `run_similarity_check`) will
  simply find no chunk data and return cleanly.
- **`llm_tasks` queue**: `extract_chunks` must be pinned to `llm_tasks`. All other
  similarity tasks use the `default` queue. This is what enforces LLM serialisation.
- **Lazy model loading**: `_get_st_model()` loads the sentence-transformers model once
  per worker process (module-level global). Same pattern as `_get_nlp()`.
- **Logging**: `current_app.logger` throughout. `info` for normal flow, `warning` for
  non-fatal issues (cache miss, chunk absent, idempotent skip), `error` for failures.
- **Copyright header**: same `# Created by ...` style as all other files.
- **Prompt versioning**: store `CHUNK_EXTRACTION_PROMPT_VERSION` in the Mongo subdocument
  alongside the extracted chunks. The idempotency check in `extract_chunks` uses this to
  detect when a re-extraction is needed (prompt changed) vs. when it can be skipped.
- **Upsert semantics for `SimilarityConcern`**: use dialect-level `on_conflict_do_update`.
  Never blindly `INSERT`. Never reset reviewer workflow fields on conflict.
- **No circular imports**: `_call_llm` lives in `app/shared/llm_services.py`;
  `_split_document` and `_strip_math_lines` live in `app/shared/text_utils.py`. Both
  `language_analysis.py` and `similarity_analysis.py` import from these shared locations.

---

## Dependencies

Add to requirements if not already present:

- `datasketch` — MinHash and LSH
- `sentence-transformers` — semantic similarity (pulls in `torch`; confirm this is
  acceptable for the deployment environment)

---

## Out of scope for this task

- Dashboard UI (second pass)
- Admin views for triggering `launch_similarity_rebuild`
- Database migration scripts (describe the new tables; migrations written separately)
- Turnitin score surfacing (already on `SubmissionRecord`; the dashboard will aggregate
  it with similarity scores in a later pass)