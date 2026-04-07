# AI Dashboard Implementation Status

## Completed

### Phase 1 — Role & Global Context
- [x] Added `data_dashboard_AI` role to `initdb.py` via new `ensure_roles(app)` startup function
  - `ensure_roles()` is idempotent; called unconditionally from `serve.py` on every startup
  - Also added `Role` to the `initdb.py` model imports
- [x] Added `is_data_dashboard_AI` and `can_view_dashboards` flags to `_build_global_context()` in
  `app/shared/context/global_context.py`
  - `can_view_dashboards` is True for root, admin, convenors, or data_dashboard_AI role holders
- [x] Added "Dashboards" navbar item to `app/templates/base.html` between "Reports" and "Archive"
  - Visible when `can_view_dashboards` is True
  - Highlights active when `request.blueprint == 'dashboards'`

### Phase 2 — `LLMOrchestrationJob` model
- [x] Created `app/models/llm_orchestration.py` with the `LLMOrchestrationJob` model
  - Status constants: PENDING / RUNNING / COMPLETE / FAILED
  - Scope constants: SCOPE_PERIOD / SCOPE_PCLASS / SCOPE_CYCLE / SCOPE_GLOBAL
  - `redis_queue_key` property returns `"llm_queue:{uuid}"`
  - Helper methods: `mark_started()`, `mark_complete()`, `mark_failed()`,
    `increment_completed()`, `increment_failed()`, `progress_pct`, `elapsed_seconds`
  - Display properties: `status_label`, `status_colour`, `scope_label`
  - `LLMOrchestrationJob.build()` factory classmethod
- [x] Exported from `app/models/__init__.py` via `from .llm_orchestration import *`
- [ ] **Hand-written Alembic migration required** (table: `llm_orchestration_job`)

### Phase 3 — Orchestration tasks
- [x] Created `app/tasks/llm_orchestration.py`
  - `register_llm_orchestration_tasks(celery)` registers three Celery tasks:
    - `orchestration_step(job_uuid)` — coordinator; pops record from Redis, launches chain
    - `orchestration_record_done(job_uuid, record_id)` — success callback; increments
      `completed_count` and re-dispatches coordinator
    - `orchestration_record_error(job_uuid, record_id)` — error callback; resets record
      flags, increments `failed_count`, re-dispatches coordinator
  - Four entry-point helper functions (called directly from views):
    - `launch_period_pipeline(period_id, clear_existing, user)`
    - `launch_pclass_pipeline(pclass_config_id, clear_existing, user)`
    - `launch_cycle_pipeline(year, clear_existing, user)`
    - `launch_global_pipeline(clear_existing, user)`
  - Each entry-point: queries eligible records, creates `LLMOrchestrationJob`, pushes
    IDs to Redis via pipeline, commits, then dispatches `orchestration_step`
  - ORCHESTRATION_REDIS_URL config variable used for the Redis connection
- [x] Registered in `app/tasks/__init__.py` and called in `app/__init__.py`

### Phase 3b — Submitters inspector buttons
- [x] Added `submit_missing_llm(configid)` and `clear_and_resubmit_llm(configid)` GET routes
  to `app/convenor/submitters.py` — both call `launch_pclass_pipeline()`
- [x] Added "Submit missing to pipeline" and "Clear & resubmit all" buttons to
  `app/templates/convenor/dashboard/submitters.html` next to "Email using local client"
  - "Clear & resubmit" shows a `confirm()` dialog before proceeding

### Phase 4 — Dashboards Blueprint
- [x] Created `app/dashboards/__init__.py` blueprint
- [x] Created `app/dashboards/views.py` with:
  - Access-control helpers (`_can_launch_orchestration`, `_get_accessible_tenants`,
    `_get_accessible_pclasses`, `_get_accessible_cycles`)
  - Aggregation helper `_aggregate_records()` — mean/SD/IQR/min/max for all 7 metrics
  - Bokeh histogram helper `_build_histogram()` — triggers at N ≥ 25
  - `overview` view (landing page) and `ai_dashboard` view (full dashboard)
  - Action routes for period/pclass/cycle/global launch and clear-and-resubmit
  - AJAX endpoint `active_jobs_status` for auto-reload polling
- [x] Registered blueprint in `app/__init__.py` at url_prefix="/dashboards"
- [x] Created `app/templates/dashboards/overview.html` — card grid landing page
- [x] Created `app/templates/dashboards/ai_dashboard.html` — full dashboard with:
  - Filter controls (tenant, pclass multi-select, cycle multi-select, sort order)
  - Active orchestration jobs panel with progress bars
  - Per-cycle sections with per-period subsections
  - Statistics tables (mean/SD/IQR/min/max for all 7 metrics)
  - Bokeh histogram grids
  - Coverage badges and launch/clear buttons (role-gated)
  - Global action buttons in filter bar
  - Auto-reload poller (15 s interval while jobs are active)
  - Manual "Reload" button

### Phase 5 — Export Tasks (CSV & Excel)
- [x] Created `app/tasks/ai_dashboard_export.py`
  - `export_ai_dashboard_xlsx` Celery task: builds DataFrame → Excel → MinIO → DownloadCentreItem → notification
  - `export_ai_dashboard_csv` Celery task: builds DataFrame → CSV → MinIO → DownloadCentreItem → notification
  - Exports: Record ID, Academic Year, Project Class, Period, Analysis Complete,
    MATTR/MTLD/Burstiness/CV/Pages/Words/References, all flag values, AI Concern,
    active risk factor keys, Supervision/Report/Presentation grades
- [x] Registered in `app/tasks/__init__.py` and called in `app/__init__.py`
- [x] Export trigger routes added to `app/dashboards/views.py`:
  - `export_period(period_id)`, `export_pclass(config_id)`, `export_cycle(year)`, `export_global()`
  - All accept `fmt` query param (xlsx/csv, default xlsx)
  - All dispatch via Celery task name lookup (`celery.tasks[task_name]`)
- [x] Export buttons in `app/templates/dashboards/ai_dashboard.html`:
  - Global-level: Excel + CSV in filter bar
  - Cycle-level: Excel + CSV in cycle header
  - Period-level: Excel + CSV directly; Project class-level via Bootstrap dropdown
  - All role-gated (data_dashboard_AI can export, convenors can export their pclasses)

### Phase 6 — Higher-level Orchestration Buttons
- [x] Per-cycle launch/clear buttons in cycle section headers (root/admin only)
- [x] Global launch/clear buttons in filter bar (root/admin only)
- [x] Per-ProjectClassConfig export (via dropdown in period subsection headers)
- [x] Per-period launch/clear buttons (convenors + root/admin for their pclasses)

---

## Pending

_(none — all phases complete)_

---

## Decisions Made

### Orchestration architecture: Option B (Redis-backed coordinator)

**Recommendation: Option B** — a dedicated Celery coordinator task that self-schedules.

**Rationale:**

- With a 24B/70B LLM running on a single Mac Studio, only ONE LLM chain can run at a time.
  A Celery chain of N submissions creates N chain links that Celery must materialise
  (chord/group serialisation, Redis round-trips per link). With many submissions this is
  fragile and hard to introspect.
- Option B serialises submissions via a Redis list (LPUSH/BRPOP). The coordinator:
  1. Receives the full list of `SubmissionRecord` IDs to process.
  2. Stores them in a Redis key, e.g. `llm_queue:<orchestration_uuid>`.
  3. Pops one ID, launches its Celery chain (existing `download_and_extract → … → finalize`),
     and attaches a `link_error` + a `link` callback that re-invokes the coordinator.
  4. The callback pops the next ID and repeats.
  5. When the list is empty, the coordinator marks itself `SUCCESS` and cleans up Redis.
- A `LLMOrchestrationJob` model (small DB table) tracks: initiating user, target scope,
  total_count, completed_count, failed_count, started_at, status. This enables the
  dashboard status panel to render current state without querying Celery directly.
- If the LLM is later upgraded to serve ≥ 2 requests in parallel, change the coordinator
  to pop up to `batch_size` IDs at once and launch them with a Celery group; no other
  logic changes.

### Data model for LLMOrchestrationJob

New table `llm_orchestration_job`:
- `id` (Integer PK)
- `uuid` (String, unique, indexed) — Redis key suffix
- `owner_id` (FK → User)
- `created_at` (DateTime)
- `status` (String: pending / running / complete / failed)
- `scope` (String: period / pclass / cycle / global)
- `scope_id` (Integer, nullable) — e.g. period or cycle id
- `total_count` (Integer)
- `completed_count` (Integer)
- `failed_count` (Integer)
- `started_at` (DateTime, nullable)
- `finished_at` (DateTime, nullable)
- `clear_existing` (Boolean)
- `description` (String, nullable)

The dashboard status panel queries `LLMOrchestrationJob` rows where `status in (pending, running)`.

### Metrics extracted from language_analysis JSON

The `language_analysis_data` JSON blob contains a `metrics` sub-dict with:
- `mattr`, `mtld`, `burstiness` (aggregate), `sentence_cv`
- `word_count`, `reference_count`

Page count is stored at top level under `_page_count`. All keys exist only after
`language_analysis_complete` is True.

Grade data is on `SubmissionRecord` directly: `supervision_grade`, `report_grade`,
`presentation_grade` (Numeric columns).

### Dashboard access control

| Role/condition | View dashboard | Launch orchestration tasks | Export |
|---|---|---|---|
| `root` | All tenants, all cycles, all pclasses | Yes | Yes |
| `admin` | Tenants in `current_user.tenants` | Yes (their tenants) | Yes |
| Convenor | Pclasses they convene/co-convene | Yes (their pclasses) | Yes |
| `data_dashboard_AI` | Same as admin (their tenants) | No (read-only) | Yes |

### Export filename scheme

```
AI_Dashboard_<identifier>.{csv,xlsx}
```

### Bokeh histogram threshold

Display Bokeh histograms only when ≥ 25 `SubmissionRecord` instances are in the set.

---

## Known Issues

- No migration tooling in the shell: the `LLMOrchestrationJob` table must be added to a
  hand-written Alembic migration file. This will be noted in the implementation instructions.
- The `_page_count` key in `language_analysis_data` is set only when the PDF/DOCX is
  parsed; old records processed before this field was introduced will not have it.
  The aggregation query must handle NULL/missing gracefully.
