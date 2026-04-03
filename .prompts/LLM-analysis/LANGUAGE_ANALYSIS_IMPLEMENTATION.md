# Language Analysis Implementation

## Completed

- **Database model** (`app/models/submissions.py`): Added `language_analysis` (Text/JSON), `language_analysis_started`, `language_analysis_complete`, `llm_analysis_failed`, `llm_failure_reason` columns to `SubmissionRecord`. Added `language_analysis_data` property and `set_language_analysis_data()` helper method.
- **Migration** (`migrations/versions/c2e4f6a8d0b1_add_language_analysis_fields.py`): Hand-crafted Alembic migration using `batch_alter_table` for MariaDB compatibility.
- **Dependencies** (`requirements.txt`): Added `lexicalrichness`, `python-docx`, `ollama`.
- **Dockerfile**: Added two `RUN` layers for spaCy and `en_core_web_sm` model (separate layers for Docker layer caching).
- **Configuration** (`app/instance/llm.py`): New instance config file reading `OLLAMA_BASE_URL` and `OLLAMA_MODEL` from environment variables. Loaded in `app/__init__.py`.
- **Docker Compose** (`docker-compose.yml`): Added `OLLAMA_BASE_URL` and `OLLAMA_MODEL` to `common-env`. Added `llm_worker` service processing `llm_tasks` queue only.
- **Celery tasks** (`app/tasks/language_analysis.py`): Full 5-task chain implemented and registered.
- **Routes** (`app/documents/views.py`): Added `launch_language_analysis`, `clear_language_analysis`, and `clear_llm_failure` routes.
- **UI — submitter manager** (`app/templates/documents/submitter_manager.html`): Language analysis card with metrics table, AI concern flag, pattern counts, cross-reference issues, LLM grade band, offcanvas full report, and admin action buttons.
- **UI — project_tag macro** (`app/templates/convenor/submitters_macros.html`): Condensed metrics row (MATTR, MTLD, burstiness, AI concern badge, LLM band) and "Analyse" button for unanalysed reports.

## In Progress

*(nothing currently in progress)*

## Pending

- **Word document support**: Currently a basic stub using `python-docx`. Extracts paragraph and table text; does not handle headers/footers, styles, or complex formatting. Should be reviewed if Word submission is common.
- **ProjectClass-level rubric configuration**: Grade band criteria are currently a module-level constant in `app/tasks/language_analysis.py`. The plan allows for future per-ProjectClass customisation via a database-stored config, but this has not yet been implemented.
- **Configurable thresholds**: MATTR/MTLD/burstiness fiducial thresholds are module-level constants. Future work could make these configurable per ProjectClass.
- **LLM task re-trigger after clearing failure**: After `clear_llm_failure`, the `submit_to_llm` task is not automatically re-queued. The user must click "Re-run analysis" to restart the full workflow, or a targeted "retry LLM only" route could be added.
- **NLTK-free lemmatisation testing**: The spaCy lemmatiser should be tested against the specific burstiness word groups to verify expected lemma forms.

## Decisions Made

- **JSON storage format**: `language_analysis` column uses `db.Text()` with `json.loads()/json.dumps()`, consistent with existing project pattern (`emails.py`, `markingevent.py`). Not a native SQL JSON column.
- **Intermediate text storage**: Extracted text is stored under `_extracted_text` key in the JSON blob between task stages (since `.si()` immutable signatures do not pass results between tasks). The key is removed after the LLM submission step to prevent the column from growing unboundedly.
- **spaCy over NLTK**: spaCy `en_core_web_sm` is used for lemmatisation (burstiness computation). Installed via Dockerfile `RUN` layers (not `requirements.txt`) to avoid runtime downloads and to benefit from Docker layer caching.
- **Separate `llm_worker` service**: A dedicated `llm_worker` Docker service processes only the `llm_tasks` queue, preventing long LLM inference jobs from blocking the main `default` queue workers.
- **Rubric as module-level constant**: Grade band criteria defined in `GRADE_BANDS` list in `language_analysis.py`. Easy to edit; ProjectClass-level customisation deferred.
- **Word document support as stub**: `python-docx` extraction is basic; accepted as a stub per spec guidance.
- **Error isolation**: Statistical computation errors are caught per-step and recorded in `language_analysis['errors']` without aborting the workflow. LLM errors set `llm_analysis_failed` and `llm_failure_reason`. Unhandled workflow errors reset `language_analysis_started` to allow re-triggering.
- **`clear_llm_failure` restricted to admins**: Unlike the general `clear_language_analysis` route (which uses `is_deletable`), clearing only the LLM failure flag requires `is_admin` because it implies the admin has reviewed the raw LLM response.

## Known Issues

- Header/footer stripping in PDF extraction uses a fixed 8% margin heuristic. Documents with unusually tall running headers (e.g., institution logos spanning >8% of page height) may retain some header text. This is noted as an approximation.
- The bibliography entry heuristic for author-year styles (counting non-blank lines) is approximate and may over-count or under-count. Numbered (`[N]` or `N.`) reference styles are handled more accurately.
- The burstiness computation requires at least 8 occurrences per word group; for short documents or documents that do not use the target vocabulary, many groups will be excluded and the aggregate may be based on very few groups.
- The spaCy `en_core_web_sm` model should be pinned to a specific version in the Dockerfile if reproducibility is required; the URL currently references `3.7.1` explicitly.
- The LLM submission uses the `ollama` Python library's streaming API. If the ollama service is not running, `ConnectionRefusedError` will be raised; this is treated as a retryable error.
