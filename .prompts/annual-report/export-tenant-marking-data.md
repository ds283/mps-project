# Claude Code Prompt: `app/tasks/data_export.py`

## Overview

Create a new Celery task file at `app/tasks/data_export.py`. This file should register a
single Celery task `export_analytical_data_xlsx` using the **same registration pattern** as
`export_ai_dashboard_xlsx` in `app/tasks/ai_dashboard_export.py`. **Read that file carefully
before writing anything.** Follow its patterns exactly for:

- Task registration within a `register_*` factory function
- Progress reporting via `progress_update`
- Object storage upload (use the same helper/adapter that `export_ai_dashboard_xlsx` uses)
- Linking the completed file to the requesting user's Download Centre

Do **not** import or call anything from `ai_dashboard_export.py` — follow its patterns but
write independent code.

---

## Task signature

```python
def export_tenant_marking_data_xlsx(self, task_id: int, tenant_id: int, user_id: int):
```

---

## Scoping: which MarkingEvents to include

The `Tenant` → `MarkingEvent` relationship is indirect:

```
Tenant → ProjectClass (ProjectClass.tenant_id)
       → ProjectClassConfig
       → SubmissionPeriodRecord
       → MarkingEvent
```

Only include `MarkingEvent` instances where:

```python
event.workflow_state >= MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK  # >= 30
```

This guarantees that conflation has been run and `ConflationReport` instances exist for
every included event.

---

## Submission token map

Before iterating over events, build a token map:

```python
token_map: dict[int, str] = {}  # SubmissionRecord.id -> uuid hex token
```

Assign each `SubmissionRecord` encountered a fresh `uuid.uuid4().hex` token. This token is
used as `submission_token` throughout **both** worksheets. It is stable within a single
export run but intentionally not stable across runs (re-running the export produces new
tokens).

---

## Output filename

```
analytical_export_{min_year}_{max_year}.xlsx
```

where `min_year` and `max_year` are derived from the minimum and maximum `academic_year`
values found across all exported rows. Example: `analytical_export_2022_2026.xlsx`.

---

## Worksheet 1: `submissions`

One row per `SubmissionRecord` per `MarkingEvent`. Iterate over each included
`MarkingEvent`, then over its `ConflationReport` instances (one per `SubmissionRecord`).
Access the `SubmissionRecord` via `conflation_report.submission_record`.

### Column order and derivation

#### Identity

| Column                | Derivation                                  |
|-----------------------|---------------------------------------------|
| `submission_token`    | Token map lookup for `submission_record.id` |
| `academic_year`       | `event.period.config.year`                  |
| `marking_event_name`  | `event.name`                                |
| `pclass_abbreviation` | `event.pclass.abbreviation`                 |

#### Module type flags

Inspect `event.targets_as_dict` (a `dict` parsed from `MarkingEvent.targets`):

| Column             | Derivation                                |
|--------------------|-------------------------------------------|
| `has_report`       | `"report" in event.targets_as_dict`       |
| `has_supervisor`   | `"supervisor" in event.targets_as_dict`   |
| `has_presentation` | `"presentation" in event.targets_as_dict` |

#### Conflated grades

From `conflation_report.conflation_report_as_dict` (a `dict`):

| Column               | Derivation                            |
|----------------------|---------------------------------------|
| `grade_report`       | `conflation_dict.get("report")`       |
| `grade_supervisor`   | `conflation_dict.get("supervisor")`   |
| `grade_presentation` | `conflation_dict.get("presentation")` |

#### Per-marker grades

Join through `MarkingWorkflow` → `SubmitterReport` → `MarkingReport`. For each
`MarkingEvent`, iterate `event.workflows`. Classify each workflow by `workflow.role`
(constants from `SubmissionRoleTypesMixin`):

**`ROLE_MARKER` workflows**
Find the `SubmitterReport` for this record: `sr` where `sr.record_id == record.id`.
Collect its `MarkingReport` instances. Sort by `MarkingReport.id` ascending to get a
stable A/B assignment. The assessor identity is `marking_report.role.user.uuid`.

> **Note:** The anonymous identifier for a user is `User.uuid`. Verify the exact field
> name in the `User` model before generating code — it may be `uuid`, `fs_uniquifier`,
> or similar. Use whichever field holds the stable, non-PK anonymous UUID.
> Prefer `uuid` to `fs_uniquifier` if both exist.

**`ROLE_SUPERVISOR` workflow**
Find the `SubmitterReport` for this record in the supervisor workflow. Grade is
`submitter_report.grade`. Supervisor identity: find the `SubmissionRole` on
`submission_record.roles` where `role.role == ROLE_SUPERVISOR`, then `role.user.uuid`.

**`ROLE_PRESENTATION_ASSESSOR` workflows**
Same pattern as `ROLE_MARKER`, assigning assessor A (first by `MarkingReport.id`) and
assessor B (second).

| Column                              | Derivation                                                                                                             |
|-------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| `marker_a_uuid`                     | `User.uuid` of first `ROLE_MARKER` `MarkingReport` assessor (null if none)                                             |
| `marker_a_grade`                    | `MarkingReport.grade` for marker A                                                                                     |
| `marker_b_uuid`                     | `User.uuid` of second `ROLE_MARKER` assessor (null if none)                                                            |
| `marker_b_grade`                    | `MarkingReport.grade` for marker B                                                                                     |
| `supervisor_marker_uuid`            | `User.uuid` of `ROLE_SUPERVISOR` `SubmissionRole` on the record                                                        |
| `supervisor_marker_grade`           | `SubmitterReport.grade` from supervisor workflow for this record                                                       |
| `report_moderation_triggered`       | `SubmitterReport.out_of_tolerance` for the report workflow                                                             |
| `report_moderator_uuid`             | `SubmitterReport.moderator_accepted_by.user.uuid` if present, else null                                                |
| `report_moderator_grade`            | `SubmitterReport.accepted_moderator_report.grade` if present, else null                                                |
| `presentation_assessor_a_uuid`      | First `ROLE_PRESENTATION_ASSESSOR` assessor `User.uuid` (null if none)                                                 |
| `presentation_assessor_a_grade`     |                                                                                                                        |
| `presentation_assessor_b_uuid`      |                                                                                                                        |
| `presentation_assessor_b_grade`     |                                                                                                                        |
| `presentation_moderation_triggered` | `out_of_tolerance` on the presentation workflow `SubmitterReport`                                                      |
| `presentation_moderator_uuid`       | As per `report_moderator_uuid` but for presentation workflow                                                           |
| `presentation_moderator_grade`      | As per `report_moderator_grade` but for presentation workflow                                                          |
| `convenor_intervention`             | `True` if `out_of_tolerance` is `True` on **any** `SubmitterReport` for this record across all workflows of this event |

#### Risk flags

Deserialise `submission_record.risk_factors_data` (the property returns a `dict`):

| Column                        | Derivation                                                             |
|-------------------------------|------------------------------------------------------------------------|
| `flag_turnitin`               | `risk_factors.get("turnitin", {}).get("present", False)`               |
| `flag_ai_compliance`          | `risk_factors.get("ai_compliance", {}).get("present", False)`          |
| `flag_ai_use`                 | `risk_factors.get("ai_use", {}).get("present", False)`                 |
| `flag_document_length`        | `risk_factors.get("document_length", {}).get("present", False)`        |
| `flag_word_count_discrepancy` | `risk_factors.get("word_count_discrepancy", {}).get("present", False)` |

#### Turnitin scores

Direct columns on `SubmissionRecord` (all nullable):

| Column                         | Derivation                            |
|--------------------------------|---------------------------------------|
| `turnitin_score`               | `record.turnitin_score`               |
| `turnitin_web_overlap`         | `record.turnitin_web_overlap`         |
| `turnitin_publication_overlap` | `record.turnitin_publication_overlap` |
| `turnitin_student_overlap`     | `record.turnitin_student_overlap`     |

#### Language analysis metrics

Deserialise `submission_record.language_analysis_data` (the property returns a `dict`).
All nullable — do not raise if absent.

| Column                  | Derivation                                                                                            |
|-------------------------|-------------------------------------------------------------------------------------------------------|
| `measured_word_count`   | `data.get("metrics", {}).get("word_count")`                                                           |
| `appendix_word_count`   | `data.get("metrics", {}).get("appendix_word_count")`                                                  |
| `reference_count`       | `data.get("metrics", {}).get("reference_count")`                                                      |
| `mattr`                 | `data.get("metrics", {}).get("mattr")`                                                                |
| `mtld`                  | `data.get("metrics", {}).get("mtld")`                                                                 |
| `burstiness`            | `data.get("metrics", {}).get("burstiness")`                                                           |
| `sentence_cv`           | `data.get("metrics", {}).get("sentence_cv")`                                                          |
| `mean_nll`              | `data.get("metrics", {}).get("mean_nll")`                                                             |
| `nll_cv`                | `data.get("metrics", {}).get("nll_cv")`                                                               |
| `stated_word_count`     | `data.get("llm_result", {}).get("stated_word_count")` if `"llm_result"` key is present, else null     |
| `genai_statement_found` | `data.get("llm_result", {}).get("genai_statement_found")` if `"llm_result"` key is present, else null |

#### AI concern — lexical calibration only

Filter `data.get("flags", {}).get("calibration_results", [])` to entries where
`entry["feature_set"] == "lexical"`. Take the first such entry if one exists; if none
exists, all columns below are null. **Do not fall back to the top-level
`flags["mahalanobis_sigma"]` / `flags["mahalanobis_pvalue"]` values**, as those reflect
the most significant result across all calibration types and would silently change meaning
if a `"full"` calibration is ever added.

| Column                    | Derivation                                             |
|---------------------------|--------------------------------------------------------|
| `ai_concern`              | `lexical_entry["concern"]`                             |
| `mahalanobis_sigma`       | `lexical_entry["sigma"]`                               |
| `mahalanobis_pvalue`      | `lexical_entry["p_value"]`                             |
| `bonferroni_k`            | `data.get("flags", {}).get("bonferroni_k")`            |
| `bonferroni_alpha_medium` | `data.get("flags", {}).get("bonferroni_alpha_medium")` |
| `bonferroni_alpha_high`   | `data.get("flags", {}).get("bonferroni_alpha_high")`   |

#### Completeness flags

| Column                  | Derivation                          |
|-------------------------|-------------------------------------|
| `has_language_analysis` | `record.language_analysis_complete` |
| `has_turnitin`          | `record.turnitin_score is not None` |

---

## Worksheet 2: `similarity_concerns`

One row per `SimilarityConcern` that involves at least one `SubmissionRecord` present in
the token map. Collect concerns via the backref relationships
`record.similarity_concerns_as_a` and `record.similarity_concerns_as_b` for each record
in the token map. Deduplicate by `SimilarityConcern.id` before writing rows.

Do **not** include `resolution_note` (may contain identifiable text).

`submission_token_a` or `submission_token_b` may be null if the partner record belongs to
a different tenant and was not included in the export. Handle this gracefully — emit null
rather than raising a `KeyError`.

| Column                  | Derivation                                                  |
|-------------------------|-------------------------------------------------------------|
| `concern_token`         | Fresh `uuid.uuid4().hex` per row                            |
| `submission_token_a`    | `token_map.get(concern.record_a_id)`                        |
| `submission_token_b`    | `token_map.get(concern.record_b_id)`                        |
| `academic_year_a`       | `concern.record_a.period.config.year`                       |
| `academic_year_b`       | `concern.record_b.period.config.year`                       |
| `year_gap`              | `abs(academic_year_a - academic_year_b)`                    |
| `pclass_abbreviation_a` | `concern.record_a.period.config.project_class.abbreviation` |
| `pclass_abbreviation_b` | `concern.record_b.period.config.project_class.abbreviation` |
| `chunk_type`            | `concern.chunk_type`                                        |
| `minhash_jaccard`       | `concern.minhash_jaccard`                                   |
| `transformer_cosine`    | `concern.transformer_cosine`                                |
| `jaccard_triggered`     | `concern.jaccard_triggered`                                 |
| `cosine_triggered`      | `concern.cosine_triggered`                                  |
| `reviewed`              | `concern.reviewed`                                          |
| `resolution`            | `concern.resolution` (null if unreviewed)                   |

---

## General implementation notes

- Use `openpyxl` to build the workbook.
- Report progress via `progress_update` after each `MarkingEvent` is processed.
- Wrap the entire build in a try/except; on unhandled exception report failure via
  `progress_update` with `TaskRecord.FAILURE`, consistent with `export_ai_dashboard_xlsx`.
- All user identity values written to the spreadsheet use `User.uuid` (the stable
  anonymous UUID), never `User.id` (the integer primary key).
- Do not add any UI route or form for triggering this task — that is out of scope for
  this ticket.