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
  `soft_time_limit`/`time_limit` guards, coordinator pattern via `recalculate_ai_concern`;
  also study the existing heading-detection regexes `_BIBLIO_HEADING`, `_APPENDIX_HEADING`
  as style references for the new heading detector
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
The chain continuation handles it automatically.

### Standalone rebuild

`SimilarityOrchestrationJob` is used exclusively for standalone similarity rebuild jobs
(re-indexing existing records without re-running language analysis). It drives its own
coordinator task that dispatches only the three-task similarity sub-chain
(`extract_chunks → compute_minhash → run_similarity_check`) for each record. Because
`extract_chunks` is pinned to `llm_tasks`, rebuild LLM calls are naturally serialised
alongside live submissions through the same queue.

### Context window strategy for chunk extraction

The LLM server runs `qwen2.5:32b` on a 32 GB Mac Studio. At 12,288 tokens context the
model fits on the GPU; larger contexts force offloading and become unusably slow. The
context window for chunk extraction is therefore fixed at 12,288 tokens, configured via
`OLLAMA_CHUNK_EXTRACTION_CONTEXT_SIZE` (default 12288) so it can be raised independently
if the hardware is upgraded.

A typical physics project report is 8,000–12,000 words. At 1.6 tokens/word (the
conservative estimate used in `language_analysis.py`) the document content alone can
reach 19,200 tokens — far exceeding the budget once prompt and response overhead are
included. **Submitting full document text to the LLM for section extraction is therefore
not viable**, and multi-pass chunking over body text is also not viable because a logical
section that straddles a chunk boundary will be split across passes with no reliable way
to reassemble it.

The solution is a **two-phase approach** that keeps the LLM call small regardless of
document length:

**Phase 1 — CPU: heading detection and hierarchy resolution.**
Parse `_core` to identify structural headings, determine their hierarchy level, and build
a tree mapping each top-level section to all its content (body text plus any subsections).
This is pure CPU work with no LLM involvement. Full details in the heading detection
section below.

**Phase 2 — LLM: classify top-level headings only.**
Submit only the list of top-level heading strings (typically 5–12 short strings) to the
LLM and ask it to classify each one into a `CHUNK_TYPES` category. This prompt is tiny —
a numbered list of headings — and fits within 12,288 tokens regardless of report length.

**Phase 3 — CPU: merge bodies by classification.**
Using the LLM's classification, concatenate the full content trees (body + all
subsections) of all top-level headings assigned to each chunk type. The LLM never sees
body text; body text is never split by a context window limit.

This approach is robust to unusual section names (the LLM's strength), produces complete
section texts, and degrades gracefully: a subsection heading misidentified as top-level
will simply be classified individually and its text merged into the correct chunk type
anyway.

---

## Heading detection specification

Implement `_detect_top_level_sections(text: str) -> list[dict]` in
`app/shared/text_utils.py`. This function is the core of Phase 1 and must handle the
heading styles found in physics project reports produced by LaTeX.

### Heading patterns to detect

In order of priority (earlier patterns take precedence):

**1. Chapter headings** — always top-level, regardless of what else is present.

Match lines of the form:

```
Chapter 1
Chapter 2  The Standard Model
Chapter 1: Introduction
CHAPTER 1
```

Pattern: `^\s*chapter\s+\d+[\s:.\-–—]*(.*)?$` (case-insensitive).
The optional trailing text is the chapter title (may be on the same line or the
immediately following non-blank line — handle both).

**2. Numbered top-level sections** — lines matching `^\s*\d+\.?\s+\S` where the
numeric prefix contains exactly one dot-separated component (i.e. `1.`, `2`, `3.` but
not `1.1`, `2.3`). These are top-level only when no chapter headings are present in the
document; if chapter headings are detected, single-number headings are subordinate.

**3. Numbered subsections** — `^\d+\.\d+` and deeper (`^\d+\.\d+\.\d+` etc.). These
are never top-level. They are subordinate to the nearest preceding top-level heading.

**4. Unnumbered short headings** — lines that:

- are 60 characters or fewer after stripping whitespace,
- are preceded and followed by at least one blank line (or appear at the start/end of
  the text),
- contain no sentence-ending punctuation (`.`, `?`, `!`) except a possible trailing
  period,
- are not captured by patterns 1–3.

These are treated as top-level only when no chapter or numbered top-level headings are
detected in the document. If numbered headings are present, short unnumbered lines are
likely subsection titles or captions and should be ignored.

### Hierarchy resolution algorithm

```
1. Scan the document for all candidate headings using the patterns above.
2. Detect the document's heading style:
     - If any chapter headings are found → chapter style.
       Top-level = chapter headings only.
       Single-number headings (1., 2.) are subordinate.
     - Else if any single-number headings are found → numbered style.
       Top-level = single-number headings.
       Unnumbered short lines are ignored.
     - Else → unnumbered style.
       Top-level = all detected unnumbered short headings.
3. Build a list of top-level sections in document order. Each section owns all
   text from its heading line to the line immediately before the next top-level
   heading (or the end of the document). This owned text includes any subordinate
   headings and their bodies verbatim.
4. Return a list of dicts, one per top-level section:
     {
       "heading":  str,   # heading text, stripped of numbering prefix and whitespace
       "full_text": str,  # complete owned text including the heading line itself
     }
```

### Stripping the numbering prefix from heading text

Before submitting heading strings to the LLM for classification, strip leading numeric
prefixes and common punctuation so the LLM sees clean title text:

- `1.` → `""`  (if nothing follows, skip this section — it's a bare number)
- `2. Introduction` → `"Introduction"`
- `Chapter 3  Results` → `"Results"`
- `1.1 Background` → skip (subordinate, never submitted)

### Edge cases

- The document may have no detectable headings at all (e.g. a continuous-prose report).
  In this case `_detect_top_level_sections` returns an empty list and `extract_chunks`
  stores all chunk types as `present: false`. Log a warning.
- A heading line immediately following a `_BIBLIO_HEADING` match (already stripped by
  `_split_document`) should never appear in the input — `_core` has already had the
  reference list removed. No special handling needed.
- The existing `_APPENDIX_HEADING` pattern in `language_analysis.py` already strips
  appendices from `_core` via `_split_document`. No special handling needed.

---

## LLM classification prompt specification

Build `_build_heading_classification_system_prompt()` and
`_build_heading_classification_user_prompt(headings: list[str])` in
`similarity_analysis.py`.

### System prompt

Instruct the LLM to:

1. Classify each top-level section heading from an undergraduate or postgraduate physics
   project report into exactly one of the following categories, or `null` if none fits:
    - `abstract` — a short summary at the very start of the report
    - `introduction` — motivation, context, research questions, aims
    - `literature_review` — survey and critical discussion of prior work
    - `methodology` — methods, instruments, theoretical framework, data collection
    - `results` — presentation of findings, measurements, or derived quantities
    - `discussion` — interpretation of results, comparison with literature, implications
    - `conclusions` — summary of findings, limitations, future directions
2. Notes for ambiguous cases:
    - A section titled "Background and Motivation" is `introduction`.
    - A section titled "Theory" or "Theoretical Framework" is `methodology` unless it is
      clearly a literature survey, in which case `literature_review`.
    - "Analysis" is typically `results` if it presents findings, or `methodology` if it
      describes an analytical approach.
    - "Summary" at the end of the document is `conclusions`.
    - Combined "Results and Discussion" → use `results` (the body text will serve both).
    - Combined "Discussion and Conclusions" → use `conclusions`.
    - Preface, Acknowledgements, Notation, Abbreviations, List of Figures → `null`.
3. Return a JSON object with one key per heading (using the exact heading string as the
   key) and the category string (or `null`) as the value.
4. Do not invent categories. Do not merge or rename headings. Return exactly as many
   keys as headings supplied.

### User prompt

```
The following are the top-level section headings from a physics project report.
Classify each one.

{numbered list of heading strings, one per line}
```

### JSON schema

Build programmatically from the heading list so the schema enforces exactly the supplied
keys. Each property value is:

```json
{
  "type": [
    "string",
    "null"
  ],
  "enum": [
    "abstract",
    "introduction",
    "literature_review",
    "methodology",
    "results",
    "discussion",
    "conclusions",
    null
  ]
}
```

Enforce via `response_format` / `json_schema` exactly as `_call_llm` does in
`language_analysis.py`.

---

## What to build

### 1. Refactor shared LLM and text-processing helpers

`language_analysis.py` currently contains `_call_llm`, `_split_document`, and
`_strip_math_lines` as module-level functions. `similarity_analysis.py` needs all three.
To avoid duplication or circular imports, **move these functions** to new shared modules:

```
app/shared/llm_services.py    ← _call_llm, _truncate_text, _TOKENS_PER_WORD,
                                  _TRUNCATION_* constants
app/shared/text_utils.py      ← _split_document, _strip_math_lines,
                                  _detect_top_level_sections  (NEW — see above)
```

Update `language_analysis.py` to import from these new locations. The functions
themselves are unchanged — this is purely a relocation plus the addition of the new
`_detect_top_level_sections` function. Confirm there are no circular imports after the
move.

---

### 2. New SQL models

Add to `models.py` or a new `similarity_models.py`.

#### `SimilarityOrchestrationJob`

Modelled exactly on `LLMOrchestrationJob`. Differences:

- Table name: `similarity_orchestration_job`
- Redis key prefixes: `similarity_queue:` and `similarity_inflight:`
- Scopes: same four constants (`period`, `pclass`, `cycle`, `global`)
- One additional column:
  ```python
  rebuild_mode = db.Column(db.Boolean(), nullable=False, default=False)
  ```
  `True` = standalone rebuild (similarity only). `False` = reserved for future use;
  normal flow uses `LLMOrchestrationJob` as the controlling job.
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
- **Always store with `record_a_id < record_b_id`** (lower integer ID first).
- `record_a` and `record_b` relationships to `SubmissionRecord`, both `uselist=False`,
  `foreign_keys` specified explicitly.
- `reviewed_by` relationship to `User`, `uselist=False`.

---

### 3. Extend `scraped_text_store.py`

Add three helpers alongside the existing functions. All follow the identical
open/close-client-per-call pattern.

```python
def store_similarity_chunks(
        record_id: int,
        sections: dict,
        model_name: str,
        prompt_version: int,
        heading_style: str,  # "chapter" | "numbered" | "unnumbered" | "none"
        top_level_heading_count: int,
) -> bool:
    """
    Upsert chunk extraction results into the scraped-text Mongo document.

    *sections* is a dict keyed by chunk type (one key per entry in CHUNK_TYPES),
    each value being:
        {
          "text":    str,    # merged body text; empty string if not present
          "present": bool,
        }

    Additional provenance fields stored alongside sections:
        "extracted_at", "extraction_model", "chunk_prompt_version",
        "heading_style", "top_level_heading_count".

    Writes under the key "similarity_chunks" in the existing Mongo document.
    Creates the document if it does not yet exist.
    """


def get_similarity_chunks(record_id: int) -> dict | None:
    """
    Retrieve the "similarity_chunks" subdocument for *record_id*.

    Returns the full subdocument (including "sections", "extracted_at",
    "extraction_model", "chunk_prompt_version", "heading_style",
    "top_level_heading_count", and optionally "minhash_signatures" and
    "minhash_computed_at"), or None on cache miss or absent key.
    """


def store_minhash_signatures(record_id: int, signatures: dict) -> bool:
    """
    Upsert MinHash signatures into the "similarity_chunks" subdocument.

    *signatures* maps chunk_type → list[int] (MinHash hashvalues).
    Uses a targeted $set to avoid overwriting the rest of the subdocument.
    Also writes "similarity_chunks.minhash_computed_at".
    """
```

---

### 4. Update `enqueue_single_record` and `enqueue_record_list`

Extend each chain to append the similarity stages:

```python
# After the existing finalize task:
| extract_chunks.si(record_id)
| compute_minhash.si(record_id)
| run_similarity_check.si(record_id)
```

No other changes to these functions.

---

### 5. New file: `similarity_analysis.py`

```python
CHUNK_EXTRACTION_PROMPT_VERSION = 1

CHUNK_TYPES = [
    "abstract",
    "introduction",
    "literature_review",
    "methodology",
    "results",
    "discussion",
    "conclusions",
]

# Per-chunk cosine similarity thresholds for raising a SimilarityConcern.
CHUNK_SIMILARITY_THRESHOLD = {
    "abstract": 0.75,
    "introduction": 0.80,
    "literature_review": 0.82,
    "methodology": 0.78,
    "results": 0.88,
    "discussion": 0.85,
    "conclusions": 0.78,
}

MINHASH_LSH_THRESHOLD = 0.15  # permissive — only prunes O(n²) comparisons
MINHASH_NUM_PERM = 128

_CHUNK_EXTRACTION_CTX_KEY = "OLLAMA_CHUNK_EXTRACTION_CONTEXT_SIZE"
_CHUNK_EXTRACTION_CTX_DEFAULT = 12288
```

#### Lazy sentence-transformers loader

```python
_st_model = None


def _get_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model
```

#### Tasks inside `register_similarity_analysis_tasks(celery)`

---

**Task 1: `extract_chunks`** — queue: `llm_tasks`
`soft_time_limit=3600, time_limit=3660, bind=True, default_retry_delay=30`

Steps:

1. Load `SubmissionRecord`. If `language_analysis_complete` is `False`, log warning and
   return (consistency guard — chain ordering already guarantees sequencing in normal
   operation).

2. Idempotency check: call `get_similarity_chunks(record_id)`. If result is present and
   `chunk_prompt_version == CHUNK_EXTRACTION_PROMPT_VERSION`, log at `info` and return.

3. Retrieve scraped text via `get_scraped_text(record_id)`. If `None`, log warning and
   return (non-fatal cache miss).

4. **Phase 1 — CPU heading detection.**
   Call `_split_document(raw_text)` to obtain `_core` (reference list already stripped).
   Apply `_strip_math_lines(_core)` to remove equation fragments.
   Call `_detect_top_level_sections(clean_core)` to obtain the list of
   `{"heading": str, "full_text": str}` dicts.

   If the returned list is empty: store all chunk types as `present: false` with
   `heading_style: "none"` via `store_similarity_chunks`, log a warning, and return.

5. **Phase 2 — LLM heading classification.**
   Extract the list of heading strings from the detected sections. These are the clean
   heading texts (numeric prefix already stripped by `_detect_top_level_sections`).

   Read config: `context_size`, `base_url`, `model` from `OLLAMA_CHUNK_EXTRACTION_
   CONTEXT_SIZE` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL`.

   Close the DB session before the LLM call.

   Build the JSON schema programmatically from the heading list (one required property
   per heading string; each value is the enum of CHUNK_TYPES plus null).

   Call `_call_llm` with:
    - system prompt from `_build_heading_classification_system_prompt()`
    - user prompt from `_build_heading_classification_user_prompt(heading_strings)`
    - the programmatically built schema
    - `options={"num_ctx": context_size}`
    - `label=f"extract_chunks/classify_headings (record #{record_id})"`

   On LLM failure: log error, store all chunk types as `present: false`, and return
   (non-fatal — downstream CPU tasks will find no chunk texts and return cleanly).

6. **Phase 3 — CPU merge.**
   Using the LLM's classification result (a dict mapping heading string → chunk type or
   null), concatenate the `full_text` of all top-level sections that map to each chunk
   type. Sections classified as `null` are discarded.

   Build the `sections` dict:
   ```python
   {
     chunk_type: {
       "text":    "\n\n".join(full_texts assigned to this type),
       "present": bool(any full_texts assigned to this type),
     }
     for chunk_type in CHUNK_TYPES
   }
   ```

7. Retrieve the heading style from `_detect_top_level_sections` return metadata (add a
   `style` field to the return value: `"chapter"`, `"numbered"`, or `"unnumbered"`).

8. Call `store_similarity_chunks(record_id, sections, model,
   CHUNK_EXTRACTION_PROMPT_VERSION, heading_style, len(top_level_sections))`.

9. Reload DB session. Raise `self.retry()` only on `SQLAlchemyError`.

---

**Task 2: `compute_minhash`** — queue: `default`
`bind=True, default_retry_delay=30`

1. Call `get_similarity_chunks(record_id)`. If `None` or no sections, log warning and
   return.
2. Idempotency: if `minhash_signatures` present and `minhash_computed_at` is newer than
   `extracted_at`, return.
3. For each chunk type where `present == True`:
    - Tokenise text into overlapping word trigrams (n=3, sliding window, whitespace
      tokenisation).
    - Compute `datasketch.MinHash(num_perm=MINHASH_NUM_PERM)` from the shingle set.
4. Call `store_minhash_signatures(record_id, {chunk_type: sig.hashvalues.tolist(), ...})`.
5. Per-chunk errors are non-fatal — log warning and continue.
6. Raise `self.retry()` on `SQLAlchemyError`.

---

**Task 3: `run_similarity_check`** — queue: `default`
`bind=True, default_retry_delay=30`

1. Call `get_similarity_chunks(record_id)`. If no `minhash_signatures`, log warning and
   return.
2. Query MongoDB for all other records with `minhash_signatures` populated:
   ```python
   collection.find(
       {"submission_record_id": {"$ne": record_id},
        "similarity_chunks.minhash_signatures": {"$exists": True}},
       projection={"submission_record_id": 1, "similarity_chunks": 1, "_id": 0}
   )
   ```
3. For each chunk type present in the current record:
   a. Build `datasketch.MinHashLSH(threshold=MINHASH_LSH_THRESHOLD,
      num_perm=MINHASH_NUM_PERM)`.
   b. Insert prior records' signatures for this chunk type; skip records without one.
   c. Query LSH with current record's signature → candidate set.
   d. For each candidate: reconstruct `MinHash` objects from stored hashvalue lists,
   call `.jaccard()`.
   e. Retain candidates where Jaccard ≥ `MINHASH_LSH_THRESHOLD`.
4. For each retained candidate: compute cosine similarity via `_get_st_model()`.
   Encode both chunk texts; compute `util.cos_sim()` or equivalent.
5. For each pair where cosine ≥ `CHUNK_SIMILARITY_THRESHOLD[chunk_type]`:
   a. Canonical ordering: `a_id = min(record_id, other_id)`.
   b. Upsert `SimilarityConcern` via `on_conflict_do_update`. On conflict update only
   `minhash_jaccard`, `transformer_cosine`, `created_at`. **Never reset** reviewer
   workflow fields.
   c. Set `similarity_flagged` risk factor on **both** `SubmissionRecord` rows:
      ```python
      {"present": True, "resolved": False, "resolved_by_id": None,
       "resolved_at": None, "annotation": None}
      ```
   Call `record.compute_risk_factors(config)` on each.
6. Single transaction commit after all chunk types processed.
7. Raise `self.retry()` on `SQLAlchemyError`.

---

**Task 4: `similarity_rebuild_coordinator`** — queue: `default`
`bind=True, default_retry_delay=30`

Direct analogue of the LLM coordinator in `llm_orchestration.py`. Follows the same
Redis queue/inflight pattern exactly.

Accepts: `job_id: int`

1. Load `SimilarityOrchestrationJob`. Mark running.
2. Each Redis queue entry is a JSON object `{"record_id": int, "compute_only": bool}`.
   Pop one entry at a time (RPOPLPUSH to inflight key).
3. Dispatch:
    - `compute_only == False` → full three-task chain
    - `compute_only == True` → two-task chain (`compute_minhash | run_similarity_check`)
4. Re-queue coordinator until queue empty, then mark job complete.
5. Increment `completed_count` / `failed_count` via existing counter mechanism.

---

**Task 5: `launch_similarity_rebuild`** — queue: `default`
`bind=True, default_retry_delay=30`

Admin-triggered entry point for standalone rebuild.

Accepts: `task_id: str`, `user_id: int`, `record_ids: list[int] | None = None`,
`scope: str = SimilarityOrchestrationJob.SCOPE_GLOBAL`, `scope_id: int | None = None`

Steps:

1. If `record_ids` is `None`, query all `SubmissionRecord` where
   `language_analysis_complete == True`.
2. Classify each record by calling `get_similarity_chunks`:
    - `None` or `chunk_prompt_version != CHUNK_EXTRACTION_PROMPT_VERSION`
      → `{"record_id": id, "compute_only": false}`
    - chunks present, no `minhash_signatures`
      → `{"record_id": id, "compute_only": true}`
    - chunks and signatures present, matching prompt version
      → `{"record_id": id, "compute_only": true}`
      (`compute_minhash` idempotency check will skip; `run_similarity_check` ensures
      concern table is current)
3. Create `SimilarityOrchestrationJob(rebuild_mode=True, ...)`, push entries onto
   `job.redis_queue_key` as JSON strings.
4. Commit, then dispatch `similarity_rebuild_coordinator.si(job.id).apply_async()`.
5. `progress_update(task_id, ...)` throughout.

Idempotent: upsert semantics in `run_similarity_check` prevent duplicate
`SimilarityConcern` rows.

Note: `recalculate_ai_concern_batch` in `language_analysis.py` may write `scraped_text`
to MongoDB on a cache miss without writing `similarity_chunks`. Step 2 handles this
correctly: such records have `get_similarity_chunks` return `None` and are queued for
the full chain.

---

### 6. Do not modify `language_analysis.finalize`

It must not dispatch the similarity pipeline. Chain continuation handles it
automatically.

---

## Conventions to follow (non-negotiable)

- **DB session lifecycle**: close before any long-running LLM call; reload with
  `db.session.get(SubmissionRecord, record_id)` before final write. Follow
  `submit_to_llm` exactly.
- **Retry on SQLAlchemy errors**: `raise self.retry()` on `SQLAlchemyError`.
  `default_retry_delay=30` on all tasks.
- **Non-fatal LLM failures**: `extract_chunks` logs and returns; downstream tasks find
  no chunk data and return cleanly. Chain is not aborted.
- **`llm_tasks` queue**: `extract_chunks` only. All other similarity tasks on `default`.
- **Lazy model loading**: `_get_st_model()` once per worker process.
- **Logging**: `current_app.logger`. `info` = normal flow; `warning` = non-fatal issues
  (cache miss, no headings detected, chunk absent, idempotent skip); `error` = failures.
- **Copyright header**: same `# Created by ...` style as all other files.
- **Prompt versioning**: `CHUNK_EXTRACTION_PROMPT_VERSION` stored in Mongo subdocument.
  Idempotency check in `extract_chunks` detects stale extractions.
- **Upsert semantics for `SimilarityConcern`**: `on_conflict_do_update`. Never blindly
  `INSERT`. Never reset reviewer workflow fields on conflict.
- **No circular imports**: `_call_llm`, `_truncate_text`, `_TOKENS_PER_WORD`, truncation
  constants → `app/shared/llm_services.py`; `_split_document`, `_strip_math_lines`,
  `_detect_top_level_sections` → `app/shared/text_utils.py`.

---

## Dependencies

Add to requirements if not already present:

- `datasketch` — MinHash and LSH
- `sentence-transformers` — semantic similarity (pulls in `torch`; confirm acceptable
  for the deployment environment)

---

## Out of scope for this task

- Dashboard UI (second pass)
- Admin views for triggering `launch_similarity_rebuild`
- Database migration scripts (describe the new tables; migrations written separately)
- Turnitin score surfacing (dashboard will aggregate it with similarity scores later)