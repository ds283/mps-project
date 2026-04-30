You are working in the MPS-Project Flask/SQLAlchemy/Celery application. This task has two parts: (1) add new SQLAlchemy
models for a grading rubric hierarchy, and (2) refactor `app/tasks/language_analysis.py` to use those models instead of
the module-level constants `GRADE_BANDS`, `_NEGATIVE_CRITERIA`, and `_POSITIVE_FLOOR_CRITERIA`.

Read the full contents of `app/tasks/language_analysis.py` before making any changes.

---

## Part 1 — SQLAlchemy models

Add the following models to a new models file`app/models/language_pipeline.py`.

```python
PROMPT_VERSION = 1
```

Define this constant at the top of `app/tasks/language_analysis.py` (see Part 2).

### GradingRubric

- `id` — integer primary key
- `project_class_id` — FK to `ProjectClass`, non-nullable
- `label` — `db.String(255)`, non-nullable; unique per `ProjectClass` (unique_together constraint on
  `(project_class_id, label)`)
- `created_at`, `updated_at` — timestamps (auto-populated)
- Relationship: `bands` — one-to-many to `RubricBand`, ordered by `RubricBand.position`, cascade delete-orphan
- Method: `clone_to(self, target_project_class)` — creates a deep copy of this rubric (all bands and criteria) attached
  to `target_project_class`. Does not commit. Returns the new `GradingRubric`.
- Method: `to_prompt_bands(self)` — returns a list of dicts in the same shape as the existing `GRADE_BANDS` constant,
  i.e. `[{"band": band.label, "criteria": [c.text for c in band.criteria]}, ...]`, ordered by `RubricBand.position` and
  `RubricCriterion.position`. This is the adapter that lets the existing prompt-building functions consume the ORM data
  without large rewrites.
- Method: `negative_criteria(self)` — returns a `frozenset` of criterion texts tagged `"negative"`.
- Method: `positive_floor_criteria(self)` — returns a `frozenset` of criterion texts tagged `"positive_floor"`.

### RubricBand

- `id` — integer primary key
- `rubric_id` — FK to `GradingRubric`, non-nullable
- `label` — `db.String(255)`, non-nullable
- `position` — `db.Integer`, non-nullable; application-level ordering only, no unique constraint
- Relationship: `criteria` — one-to-many to `RubricCriterion`, ordered by `RubricCriterion.position`, cascade
  delete-orphan
- Method: `clone_to(self, target_rubric)` — deep copy attached to `target_rubric`. Does not commit. Returns new
  `RubricBand`.

### RubricCriterion

- `id` — integer primary key
- `band_id` — FK to `RubricBand`, non-nullable
- `text` — `db.Text`, non-nullable
- `tag` — `db.String(20)`, non-nullable, default `"plain"`; valid values are `"plain"`, `"negative"`, `"positive_floor"`
- `position` — `db.Integer`, non-nullable; application-level ordering only, no unique constraint
- Method: `clone_to(self, target_band)` — shallow copy attached to `target_band`. Does not commit. Returns new
  `RubricCriterion`.

### ProjectClassConfig changes

In the existing `ProjectClassConfig` model, add:

- `grading_rubric_id` — nullable FK to `GradingRubric`
- `grading_rubric` — `db.relationship("GradingRubric", uselist=False, foreign_keys=[grading_rubric_id])`

Generate an Alembic migration for all of the above. The migration must not seed any data — tables and columns only.

---

## Part 2 — language_analysis.py refactor

Add at the top of `app/tasks/language_analysis.py`:

```python
PROMPT_VERSION = 1
```

The prompt hash (see below) is a SHA-256 of the final assembled system prompt string, truncated to 12 hex characters.
Compute it immediately before the `_call_llm` invocation in `submit_to_llm` and store it alongside the result.

### Rubric resolution

Replace all references to `GRADE_BANDS`, `_NEGATIVE_CRITERIA`, `_POSITIVE_FLOOR_CRITERIA`, and `_ALL_CRITERION_CODES`
with equivalents derived from the `GradingRubric` attached to the `ProjectClassConfig` reachable via:

```
SubmissionRecord -> SubmissionPeriodRecord -> ProjectClassConfig -> grading_rubric
```

Load the rubric once at the start of `submit_to_llm` and pass it explicitly into every helper function that currently
consumes `GRADE_BANDS` or the two frozensets. Do not use global state. The module-level constants `GRADE_BANDS`,
`_NEGATIVE_CRITERIA`, `_POSITIVE_FLOOR_CRITERIA`, and `_ALL_CRITERION_CODES` should be removed once all call sites are
updated.

Use `GradingRubric.to_prompt_bands()`, `GradingRubric.negative_criteria()`, and
`GradingRubric.positive_floor_criteria()` as the adapters so that `_build_system_prompt`, `_build_chunk_system_prompt`,
`_make_band_schema`, and related helpers require minimal changes — add a `rubric` parameter to each and substitute the
local variable for the constant, but do not otherwise restructure them.

### No-rubric code path

If `ProjectClassConfig.grading_rubric` is `None`, the pipeline must still run but skip the grading component entirely.
Specifically:

- Skip the LLM grading pass (single-pass or map-reduce) and do not write `llm_result`, `criterion_map`, or `bands` to
  `language_analysis_data`.
- Still perform metadata extraction (stated word count, AI statement, personal contribution statement) using the
  existing `_build_metadata_system_prompt` / `_build_metadata_user_prompt` / `_call_llm` path. This extraction is
  independent of the rubric and must always run.
- Set a key `"grading_skipped": true` in `language_analysis_data` so the UI can distinguish "not yet run" from "run
  without a rubric".
- Do not set `llm_analysis_failed` — skipping grading because no rubric is configured is not a failure.

This separation also applies when a rubric *is* present: the metadata extraction call and the grading call are already
logically distinct in the code. Keep them as separate `_call_llm` invocations. Do not merge them. (See the existing
`_METADATA_OVERHEAD_TOKENS` constant and `_build_metadata_system_prompt` — this separation is already partially
anticipated in the code.)

### criterion_map extension

When writing `criterion_map`, extend each entry to include the rubric PK and criterion PK alongside the existing text:

```python
data["criterion_map"] = {
    f"{band_idx}.{crit_idx}": {
        "text": criterion.text,
        "criterion_id": criterion.id,
        "band_id": band.id,
        "rubric_id": rubric.id,
        "rubric_label": rubric.label,
    }
    for band_idx, band in enumerate(rubric.bands, start=1)
    for crit_idx, criterion in enumerate(band.criteria, start=1)
}
```

This is a breaking change for `criterion_map`. You will need to update existing front end templates and views that
consume that field.

### Prompt versioning

When a grading run completes successfully, store the following in `language_analysis_data` alongside `llm_result`:

```python
data["prompt_version"] = PROMPT_VERSION
data["prompt_hash"] = _prompt_hash(system_prompt_string)  # 12-char hex SHA-256 prefix
```

Add a small helper:

```python
import hashlib


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]
```

---

## Constraints

- Do not change `_build_system_prompt`, `_build_chunk_system_prompt`, or any prompt text beyond adding a `rubric`
  parameter and substituting the constant references. Prompt content must remain identical to the current version — this
  is important for consistency with existing stored results.
- Do not change the map-reduce chunking logic, retry logic, or Celery task structure.
- Do not change `_build_metadata_system_prompt` or `_build_metadata_user_prompt`.
- Preserve all existing keys in `language_analysis_data` — only add new keys, never rename or remove existing ones.
- All new code should follow the conventions (imports, naming, error handling, logging) already established in
  `language_analysis.py`.

## Verification

After making all changes:

1. Confirm that `GRADE_BANDS`, `_NEGATIVE_CRITERIA`, `_POSITIVE_FLOOR_CRITERIA`, and `_ALL_CRITERION_CODES` no longer
   appear anywhere in `language_analysis.py`.
2. Confirm that every call site that previously passed these constants now passes the `rubric` object or a derived value
   from it.
3. Confirm that the no-rubric code path exits without setting `llm_analysis_failed`.
4. Confirm that the Alembic migration does not include any `INSERT` or seed statements.