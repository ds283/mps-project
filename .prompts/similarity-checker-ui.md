# Claude Code Prompt: Similarity Dashboard UI

## Context

This is a Flask/SQLAlchemy academic project management platform. You are implementing the
**Similarity Dashboard** — a new dashboard within the existing `dashboards` blueprint,
alongside the existing AI Risk Dashboard and Marking Dashboard.

Read these files carefully before writing any code:

### Primary references (read first)

- `app/templates/dashboards/views.py` — **primary reference** for all view function
  patterns: access gating, tenant/pclass/cycle filter resolution, `render_template_context`,
  `request.args` parsing, the `_can_launch_orchestration` helper, and every action route
  pattern (`launch_period`, `clear_period`, etc.). Replicate these patterns exactly.
- `app/templates/dashboards/ai_dashboard.html` — primary reference template: extend
  conventions, macro definitions, Bootstrap usage, `--db-*` token usage, collapsible
  period subsections, job polling script, `export_buttons` macro.
- `app/templates/dashboards/marking_dashboard.html` — secondary reference template:
  filter bar without multi-select, `px-0` container, page-header band style.
- `app/templates/dashboards/overview.html` — landing page to update with the new card.
- `app/templates/dashboards/dashboard-colours.md` — **colour token rules**. Read and
  follow exactly. Never use hardcoded hex values for dashboard identity colours.

### DataTables server-side references (read before implementing the concern table)

- `app/shared/utils/ServerSideProcessing.py` — `ServerSideSQLHandler` and
  `ServerSideInMemoryHandler` context managers. The concern table uses
  `ServerSideSQLHandler` (all filtering and sorting can be expressed in SQL).
- `app/templates/convenor/submitter_reports_inspector.html` — canonical example of a
  DataTables server-side table: `import_datatables()` macro import, `$SCRIPT_ROOT`,
  jQuery `DataTable(...)` initialisation with `serverSide: true`, `processing: true`,
  `ajax` POST with `JSON.stringify(args)`, `fnDrawCallback` for tooltip/popover
  reinitialisation, and `columns` array.
- `app/ajax/convenor/markingevent.py` — canonical example of a row-formatter module:
  Jinja2 string templates compiled with `env.from_string(...)`, `render_template(...)`
  called per row, and a public formatter function (e.g. `submitter_report_data`) that
  returns a list of column-keyed dicts. Study `submitter_report_data()` and
  `conflation_report_data()` as style models.

### Mockup files (use as scaffolding — do not copy verbatim)

These are in the `mockups/` directory at the repository root.
They are design references, not production code. Adapt them to follow the conventions
of the files above; do not use them as-is.

- `mockups/similarity_dashboard.html`
- `mockups/similarity_concern_detail.html`
- `mockups/_similarity_risk_factor_card.html`

### Backend models and tasks

- `app/models/similarity_models.py` (or wherever `SimilarityConcern` and
  `SimilarityOrchestrationJob` are defined after the backend task is implemented)
- `app/tasks/similarity_analysis.py` — `CHUNK_TYPES`, `CHUNK_SIMILARITY_THRESHOLD`,
  `launch_similarity_rebuild` entry point
- `app/shared/scraped_text_store.py` — `get_similarity_chunks()` for retrieving chunk
  text to display on the concern detail view

---

## Access gating rules

Implement a `_can_access_similarity_dashboard()` helper and a
`_get_accessible_pclasses_for_similarity(tenant_id)` helper following the exact same
patterns as `_can_access_marking_dashboard()` and `_get_accessible_pclasses()` in
`views.py`.

### Who can access what

| Role / condition                                   | Scope                                                                                                                                                                        |
|----------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `root`                                             | All `SimilarityConcern` rows globally                                                                                                                                        |
| `admin`                                            | All concerns for all `ProjectClass` instances belonging to tenants the user is a member of                                                                                   |
| `data_dashboard_similarity`                        | Same as `admin` — all concerns for tenants the user is a member of                                                                                                           |
| Convenor (faculty user with `is_convenor == True`) | Concerns where **at least one** of `record_a` or `record_b` belongs to a `ProjectClass` that the user convenes or co-convenes (i.e. appears in `faculty_data.convenor_list`) |

A concern is accessible to a convenor if either `record_a.period.config.pclass_id` OR
`record_b.period.config.pclass_id` is in the convenor's `convenor_list`. Both sides of
the pair must be checked; a concern is not hidden simply because one side belongs to a
different pclass.

### Tenant selector visibility

Show the `Tenant` selector in filter forms **only** when the user can access more than
one tenant. This matches the behaviour in `ai_dashboard` (see the
`{% if accessible_tenants|length > 1 %}` pattern and the corresponding hidden input for
single-tenant users in `views.py`).

### Access gate guard

Every view function in this section must begin with the same guard pattern as
`ai_dashboard()`:

```python
if not _can_access_similarity_dashboard():
    flash("You do not have permission to access the Similarity Dashboard.", "error")
    return redirect(url_for("home.homepage"))
```

`_can_access_similarity_dashboard()` returns `True` for root, admin,
`data_dashboard_similarity`, and faculty convenors.

---

## Colour tokens

The similarity dashboard uses the `--db-orange-*` ramp. All six stops must be defined
in the same token block as the existing `--db-blue-*` and `--db-green-*` ramps (wherever
that block lives — base template or shared stylesheet). Follow `dashboard-colours.md`
exactly.

```css
--db-orange-50: /* panel/card background fills */
--db-orange-100: /* section header background fills */
--db-orange-200: /* borders and dividers */
--db-orange-400: /* interactive elements, progress bars, buttons */
--db-orange-600: /* secondary text, labels */
--db-orange-800:

/* heading text on light backgrounds */
```

Also define:

```css
.btn-db-orange {
    background-color: var(--db-orange-400);
    border-color: var(--db-orange-400);
    color: #fff;
}

.btn-db-orange:hover {
    background-color: var(--db-orange-600);
    border-color: var(--db-orange-600);
    color: #fff;
}
```

---

## What to implement

### 1. Access-control helpers (add to `views.py`)

```python
def _can_access_similarity_dashboard() -> bool:
    """Return True if the current user may view the similarity dashboard."""


def _get_accessible_pclasses_for_similarity(
        tenant_id: Optional[int] = None,
) -> List[ProjectClass]:
    """
    Return ProjectClass instances the current user may view on the similarity
    dashboard. A class is included only when it has at least one SimilarityConcern
    where record_a or record_b belongs to a SubmissionPeriodRecord under this class.
    Follow the same exists-subquery pattern as _get_accessible_pclasses().
    """


def _can_launch_similarity_rebuild(pclass: Optional[ProjectClass] = None) -> bool:
    """
    Return True if the current user may trigger similarity rebuild tasks.
    root / admin: always.
    Convenors: for pclasses they convene.
    data_dashboard_similarity: read-only, cannot launch.
    Pattern identical to _can_launch_orchestration().
    """


def _base_concern_query(
        pclass_ids: List[int],
        years: Optional[List[int]],
        status_filter: str,  # "open" | "resolved" | "all"
        chunk_type: Optional[str],
) -> "Query":
    """
    Return a SQLAlchemy query for SimilarityConcern rows visible under the
    given filters. Does NOT apply ordering or pagination — callers do that.

    Access control: a concern is included when at least one of its two
    SubmissionRecord sides belongs to a pclass in pclass_ids. Use an OR of
    two EXISTS subqueries (one for record_a, one for record_b) keyed on
    the pclass_ids list. Do not require BOTH sides to be in scope.

    status_filter:
      "open"     → reviewed == False
      "resolved" → reviewed == True
      "all"      → no filter on reviewed

    year filter: restrict to concerns where the later of the two records'
    academic years (max(record_a.period.config.year, record_b.period.config.year))
    falls within the selected years list. If years is None or empty, no year filter.

    chunk_type: if non-empty, restrict to that chunk type.
    """


def _similarity_dashboard_summary() -> Dict:
    """
    Return summary counts for the overview page card:
      n_open:     open SimilarityConcern rows visible to the current user
      n_resolved: resolved concerns visible to the current user
      n_indexed:  SubmissionRecord rows with similarity_chunks in MongoDB
                  (approximate — query count from SQL where
                  language_analysis_complete == True; exact MongoDB count
                  is too expensive for a card badge)
    """
```

### 2. View functions (add to `views.py`)

All routes go in the existing `dashboards` blueprint. Route prefix: `/similarity`.

---

#### `similarity_dashboard` — `GET /similarity`

Access: `_can_access_similarity_dashboard()`.

This view renders the dashboard shell only. The concern table itself is populated
by a separate AJAX endpoint (`similarity_concerns_ajax`) using DataTables server-side
processing. The view does **not** query `SimilarityConcern` rows directly — it only
resolves filter state and passes it to the template so the DataTables initialisation
script can thread the current filter values into the AJAX POST URL as query parameters.

Filter parameters (all via `request.args`):

- `tenant_id` — integer; single-tenant users have it hidden
- `pclass_id` — list (multi-select), same as `ai_dashboard`
- `year` — list (multi-select), same as `ai_dashboard`
- `status` — one of `"open"`, `"resolved"`, `"all"`; default `"open"`
- `chunk_type` — one of `CHUNK_TYPES` or empty string; default empty (all)

Active jobs: query `SimilarityOrchestrationJob` rows in `ACTIVE_STATUSES`, limit 10,
ordered by `created_at DESC`. Same pattern as the `LLMOrchestrationJob` query in
`ai_dashboard()`.

Rolling average seconds per record: same pattern as `ai_dashboard()` but over
`SimilarityOrchestrationJob`.

Summary stat cards: call `_similarity_dashboard_summary()`.

Context passed to template:

```python
render_template_context(
    "dashboards/similarity_dashboard.html",
    accessible_tenants=accessible_tenants,
    selected_tenant=selected_tenant,
    accessible_pclasses=accessible_pclasses,
    selected_pclass_ids=selected_pclass_ids,
    accessible_cycles=accessible_cycles,
    selected_years=selected_years,
    status_filter=status_filter,
    selected_chunk_type=selected_chunk_type,
    chunk_types=CHUNK_TYPES,  # from similarity_analysis.py
    summary=summary,
    active_jobs=active_jobs,
    avg_seconds_per_record=avg_seconds_per_record,
    can_launch=_can_launch_similarity_rebuild(),
    is_root=current_user.has_role("root"),
    is_admin=current_user.has_role("admin"),
)
```

---

#### `similarity_concerns_ajax` — `POST /similarity/concerns_ajax`

This is the DataTables server-side AJAX endpoint. It follows the identical pattern
as `submitter_reports_ajax` in the convenor blueprint.

Access: same gate as `similarity_dashboard`. Return HTTP 403 JSON on failure rather
than a redirect (this is an AJAX endpoint).

Implementation:

```python
@dashboards.route("/similarity/concerns_ajax", methods=["POST"])
@login_required
def similarity_concerns_ajax():
    if not _can_access_similarity_dashboard():
        return jsonify({"error": "Permission denied"}), 403

    # Resolve filter state from request.form or request.args — these are
    # passed as URL query parameters by the DataTables ajax.url construction
    # in the template (see below). Parse with the same guard pattern as the
    # main view.
    tenant_id = ...  # from request.args, same resolution logic
    pclass_ids = ...  # from request.args
    years = ...  # from request.args
    status_filter = ...  # from request.args, default "open"
    chunk_type = ...  # from request.args, default ""

    base_query = _base_concern_query(pclass_ids, years, status_filter, chunk_type)

    data = {
        "student_a": {
                         "search": < StudentData.user.name or similar searchable column >,
    },
    "student_b": {
                     "search": < StudentData.user.name or similar
    searchable
    column >,
    },
    "cosine": {
        "order": SimilarityConcern.transformer_cosine,
    },
    "created": {
        "order": SimilarityConcern.created_at,
    },
    }

    with ServerSideSQLHandler(request, base_query, data) as handler:
        return handler.build_payload(
            lambda concerns: similarity_concern_data(concerns)
        )
```

The `data` dict defines which columns support search and which support ordering,
following the `ServerSideSQLHandler` convention from `ServerSideProcessing.py`.
For search on student names, join through `SubmissionRecord → SubmittingStudent →
StudentData → User` as needed in `_base_concern_query` so the columns are
available to the handler.

---

#### Row formatter module — `app/ajax/dashboards/similarity.py`

Create this new file following the pattern of `app/ajax/convenor/markingevent.py`.

**Public function:**

```python
def similarity_concern_data(concerns) -> List[Dict]:
    """
    Format SimilarityConcern rows for DataTables.
    Called by similarity_concerns_ajax via ServerSideSQLHandler.build_payload().
    Returns a list of column-keyed dicts, one per concern.
    """
```

**Columns to render** (one Jinja2 string template per column, compiled with
`env.from_string(...)`, rendered per row with `render_template(...)`):

- `student_a` — student name, candidate number, pclass abbreviation, year
- `student_b` — same for the other side of the pair
- `chunk_type` — the `--db-orange-*` styled section badge (same markup as
  `chunk_badge` macro in the mockup)
- `cosine` — cosine similarity pill (danger/warning/secondary based on score,
  same logic as `cosine_badge` macro in the mockup)
- `turnitin` — student overlap percentages for both sides; highlight in danger
  colour when ≥ 20%
- `year_gap` — year gap badge (warning-subtle for 1 year, secondary for 2+)
- `status` — resolution badge (unreviewed / cleared / referred / escalated)
- `actions` — View button linking to `similarity_concern_detail`; Review button
  (linking to `#review` anchor on the detail page) shown only when
  `not concern.reviewed`

Follow the `markingevent.py` style exactly: string templates as module-level
constants with `# language=jinja2` comments, compiled once per call with
`current_app.jinja_env.from_string(...)`.

Include `generate_csrf` in context for any template that needs it (the actions
column does not need CSRF since all actions are GET links; only include it if a
column renders a form).

---

#### `similarity_concern_detail` — `GET /similarity/concern/<int:concern_id>`

Access: `_can_access_similarity_dashboard()`. After loading the concern, verify
that the current user can access at least one of its two pclasses; 404 otherwise.

Load chunk texts from MongoDB:

```python
chunks_a = get_similarity_chunks(concern.record_a_id)
chunks_b = get_similarity_chunks(concern.record_b_id)
chunk_text_a = chunks_a["sections"].get(concern.chunk_type, {}).get("text") if chunks_a else None
chunk_text_b = chunks_b["sections"].get(concern.chunk_type, {}).get("text") if chunks_b else None
```

Pass to template:

```python
render_template_context(
    "dashboards/similarity_concern_detail.html",
    concern=concern,
    concern_chunks={"a": chunk_text_a, "b": chunk_text_b},
    chunk_thresholds=CHUNK_SIMILARITY_THRESHOLD,  # from similarity_analysis.py
    form=ResolveSimilarityConcernForm(),
)
```

---

#### `resolve_similarity_concern` — `POST /similarity/concern/<int:concern_id>/resolve`

Access: same as `similarity_concern_detail`. Convenors may only resolve concerns
where at least one side is in their convenor pclass list.

Accepts: `resolution` (radio: `"cleared"` | `"referred"` | `"escalated"`),
`resolution_note` (textarea, optional).

On valid submission:

1. Set `concern.reviewed = True`, `concern.reviewed_by_id = current_user.id`,
   `concern.reviewed_at = datetime.now()`, `concern.resolution = resolution`,
   `concern.resolution_note = resolution_note or None`.
2. Call `_recompute_similarity_flag(concern.record_a_id)` and
   `_recompute_similarity_flag(concern.record_b_id)` to clear the risk factor
   on each `SubmissionRecord` if no open concerns remain.
3. Commit. Flash success. Redirect to `similarity_dashboard`.

`_recompute_similarity_flag(record_id)` helper:

```python
def _recompute_similarity_flag(record_id: int) -> None:
    """
    Clear the similarity_flagged risk factor on a SubmissionRecord when no
    open (unreviewed) SimilarityConcern rows reference it as either
    record_a or record_b.

    Called after every concern resolution save.
    """
    from sqlalchemy import or_
    open_count = (
        db.session.query(SimilarityConcern.id)
        .filter(
            or_(
                SimilarityConcern.record_a_id == record_id,
                SimilarityConcern.record_b_id == record_id,
            ),
            SimilarityConcern.reviewed == False,
        )
        .count()
    )
    record = db.session.get(SubmissionRecord, record_id)
    if record is None:
        return
    rf = record.risk_factors_data or {}
    if open_count == 0 and "similarity_flagged" in rf:
        rf["similarity_flagged"]["resolved"] = True
        rf["similarity_flagged"]["resolved_by_id"] = current_user.id
        rf["similarity_flagged"]["resolved_at"] = datetime.now().isoformat()
        record.risk_factors = json.dumps(rf)
```

---

#### Rebuild action routes

Follow the exact same pattern as `launch_period`, `launch_cycle`, `launch_global` in
`views.py`. Each route:

1. Checks `_can_launch_similarity_rebuild(pclass)`.
2. Calls the appropriate `launch_similarity_rebuild` entry point from
   `app/tasks/similarity_analysis.py`.
3. Flashes success/error and redirects to `similarity_dashboard`.

Routes to implement:

```
GET /similarity/launch_global       → launch_similarity_rebuild_global
GET /similarity/launch_cycle/<year> → launch_similarity_rebuild_cycle
GET /similarity/launch_period/<int:period_id> → launch_similarity_rebuild_period
```

#### Job status polling endpoint

```
GET /similarity/active_jobs_status  → active_similarity_jobs_status
```

Same implementation as `active_jobs_status` in `views.py`, but queries
`SimilarityOrchestrationJob` instead of `LLMOrchestrationJob`. Returns identical
JSON shape so the same polling script works with a different URL.

#### Cancel job route

```
GET /similarity/cancel_job/<uuid>   → cancel_similarity_job
```

Pattern identical to `cancel_job` in `views.py`.

---

### 3. WTForms form class (add to `forms.py`)

```python
class ResolveSimilarityConcernForm(Form):
    """
    CSRF-bearing form for the similarity concern resolution POST.
    Carries no user-editable fields — resolution data arrives as plain
    POST parameters validated manually in the view. Sole purpose is CSRF
    protection via {{ form.hidden_tag() }}.
    Pattern identical to MarkingExportForm.
    """
    pass
```

---

### 4. Template files

Copy the three mockup files from `mockups/` into `app/templates/dashboards/` with
the following leafnames:

- `similarity_dashboard.html`
- `similarity_concern_detail.html`
- `_similarity_risk_factor_card.html`

Then adapt each file to match production conventions exactly:

**`similarity_dashboard.html`**

- `{% extends "base_app.html" %}`
- `{% from "datatables.html" import import_datatables, bootstrap_spinner %}` at the
  top of the file (same import as `submitter_reports_inspector.html`).
- In `{% block scripts %}`, call `{{ import_datatables() }}` and initialise the
  concern table with `serverSide: true`, `processing: true`, and the following
  `ajax` configuration:

  ```javascript
  $SCRIPT_ROOT = {{ request.script_root | tojson | safe }};

  $('#similarity-concerns-table').DataTable({
      responsive: true,
      bAutoWidth: false,
      colReorder: true,
      dom: 'lftipr',
      stateSave: false,   // filter state is managed by the Flask form, not DataTables
      serverSide: true,
      processing: true,
      language: {{ bootstrap_spinner() }},
      ajax: {
          url: $SCRIPT_ROOT + '/dashboards/similarity/concerns_ajax'
              + '?tenant_id={{ selected_tenant.id }}'
              + '{{ "&pclass_id=" + selected_pclass_ids | join("&pclass_id=") if selected_pclass_ids else "" }}'
              + '{{ ("&year=" + selected_years | join("&year=")) if selected_years else "" }}'
              + '&status={{ status_filter }}'
              + '{{ ("&chunk_type=" + selected_chunk_type) if selected_chunk_type else "" }}',
          type: 'POST',
          data: function (args) { return {"args": JSON.stringify(args)}; }
      },
      "fnDrawCallback": function () {
          $('body').tooltip({selector: '[data-bs-toggle="tooltip"]'});
          $('body').popover({selector: '[data-bs-toggle="popover"]', html: true, trigger: 'focus'});
      },
      columns: [
          {data: 'student_a',  orderable: false, searchable: true},
          {data: 'student_b',  orderable: false, searchable: true},
          {data: 'chunk_type', orderable: false, searchable: false},
          {data: 'cosine',     orderable: true,  searchable: false},
          {data: 'turnitin',   orderable: false, searchable: false},
          {data: 'year_gap',   orderable: false, searchable: false},
          {data: 'status',     orderable: false, searchable: false},
          {data: 'actions',    orderable: false, searchable: false},
      ],
      order: [[3, 'desc']]   // default: highest cosine first
  });
  ```

  Note that the filter state (tenant, pclass, year, status, chunk_type) is baked
  into the AJAX URL as query parameters using Jinja2 at render time. This means
  changing the filter form reloads the page (standard GET form submit), which
  re-renders the shell with a new AJAX URL. DataTables then fetches from that URL.
  This is consistent with how the other dashboards handle filter state — the form
  drives the page, not DataTables state.

- The concern table itself is an empty `<table id="similarity-concerns-table">` with
  a `<thead>` row. DataTables populates the body via AJAX. There is no Jinja2 loop
  over concerns in this template.
- The per-cycle collapsible section structure from the mockup is **removed**. With
  DataTables handling pagination and search globally, the cycle/period grouping adds
  complexity without benefit. Replace it with a single flat table card below the
  filter form. The cycle/period of each concern is visible in the `student_a` and
  `student_b` columns.
- All `url_for(...)` calls must use real endpoint names from the routes above.
- Job polling script: change the polling URL to
  `url_for("dashboards.active_similarity_jobs_status")`.
- Progress bar fill: `style="... background-color: var(--db-orange-400);"`.
- `{% macro export_buttons(...) %}` — copy verbatim from `ai_dashboard.html`.
- The `can_launch` context variable gates all rebuild action links.

**`similarity_concern_detail.html`**

- `{% extends "base_app.html" %}`
- The resolution form must have `{{ form.hidden_tag() }}` for CSRF protection.
- Section text is rendered with `{{ chunk_text | e }}` — escape HTML entities since
  this is raw extracted text from PDFs.
- The `#review` anchor on the page allows direct-linking from the dashboard and from
  the risk factor card.
- `chunk_thresholds` is passed as a dict; use
  `chunk_thresholds[concern.chunk_type]` to show the threshold value beneath the
  cosine score.

**`_similarity_risk_factor_card.html`**

- This is an include partial, not a standalone template. No `{% extends %}`.
- It is included by the existing resolve risk factors view using
  `{% include 'dashboards/_similarity_risk_factor_card.html' %}` when iterating risk
  factors and encountering the `similarity_flagged` key.
- The including view must pass `open_concerns`, `record`, and `risk_data` in context
  (or via `{% with %}`).
- The partial must not assume `current_user` is available directly — all user-identity
  logic stays in the view; the partial only renders what is passed in context.

---

### 5. Overview page update (`overview.html`)

Add the similarity card to the dashboard grid alongside the existing AI Risk and
Marking cards. Follow the `dashboard_card` macro call pattern exactly:

```jinja
{% call(slot) dashboard_card(
    icon_class="fas fa-search fa-2x",
    icon_bg_style="background-color: var(--db-orange-50);",
    title="Similarity Dashboard",
    description="Cross-cohort section-level plagiarism detection. Similarity concerns, Turnitin overlap, and reviewer workflow across all cohorts.",
    open_url=url_for('dashboards.similarity_dashboard'),
    open_label="Open dashboard",
    open_btn_class="btn-db-orange"
) %}
    {% if slot == 'badges' %}
        {# Show open concern count if non-zero; follow the existing badge pattern #}
        {% if similarity_summary.n_open > 0 %}
            <span class="badge"
                  style="background-color: var(--db-orange-100); color: var(--db-orange-800);">
                <i class="fas fa-exclamation-triangle me-1"></i>{{ similarity_summary.n_open }} open
                concern{{ 's' if similarity_summary.n_open != 1 else '' }}
            </span>
        {% endif %}
        {% if similarity_summary.n_open == 0 %}
            <span class="badge bg-secondary">No open concerns</span>
        {% endif %}
    {% endif %}
{% endcall %}
```

The `overview()` view function must be updated to compute and pass `similarity_summary`
by calling `_similarity_dashboard_summary()`. Guard the call: if the current user
cannot access the similarity dashboard, pass `similarity_summary=None` and suppress
the card with `{% if similarity_summary is not none %}`.

---

### 6. Resolve risk factors view integration

The existing resolve risk factors view (in the convenor blueprint, not this file)
renders one card per risk factor from `record.risk_factors_data`. It must be updated
to handle the `similarity_flagged` key specially:

When iterating risk factors, if the key is `"similarity_flagged"`:

1. Query open concerns for this record:
   ```python
   from sqlalchemy import or_
   open_concerns = (
       db.session.query(SimilarityConcern)
       .filter(
           or_(
               SimilarityConcern.record_a_id == record.id,
               SimilarityConcern.record_b_id == record.id,
           ),
           SimilarityConcern.reviewed == False,
       )
       .order_by(SimilarityConcern.transformer_cosine.desc())
       .all()
   )
   ```
2. Include the partial:
   ```jinja
   {% with open_concerns=open_concerns, record=record, risk_data=risk_data %}
       {% include 'dashboards/_similarity_risk_factor_card.html' %}
   {% endwith %}
   ```
   instead of rendering the standard checkbox card.

This change is in the convenor blueprint, not `dashboards/views.py`. Locate the
resolve risk factors view and template and make the minimum changes needed.

---

## Conventions to follow (non-negotiable)

- **`ServerSideSQLHandler`** — always use this (not `ServerSideInMemoryHandler`)
  for the concern table. All filtering and ordering can be expressed in SQL via
  `_base_concern_query`. Do not load concerns into Python memory for pagination.
- **Row formatter module** — `app/ajax/dashboards/similarity.py` must follow the
  `markingevent.py` pattern exactly: module-level Jinja2 string constants with
  `# language=jinja2` comments, compiled with `env.from_string(...)` inside the
  formatter function, rendered per row with `render_template(...)`. Do not use
  f-strings or manual HTML concatenation to build cell content.
- **`render_template_context`** — always use this instead of `render_template`.
  It is the project's standard wrapper (see every existing view function).
- **`request.args` parsing** — always guard against `ValueError`/`TypeError` on
  int conversions; fall back to defaults. See `ai_dashboard()` for the exact pattern.
- **Tenant validation** — after resolving `selected_tenant_id` from query args,
  always verify it is in `accessible_tenant_ids` and fall back to the first
  accessible tenant if not. Same pattern as `ai_dashboard()`.
- **`url_for` only** — never hardcode URLs. All `href` attributes use `url_for(...)`.
- **`--db-orange-*` tokens only** — never use hex values for dashboard identity
  colours. All orange appearances in templates use these CSS custom properties.
- **`btn-db-orange`** — use this class for all primary action buttons in the
  similarity dashboard templates. Do not use `btn-primary` for dashboard identity.
- **No new dependencies** — do not introduce any Python packages not already in
  `requirements.txt`. `sqlalchemy`, `flask`, `flask_security` are all available.
- **Bootstrap 5.3** — the compiled (non-Sass) build is in use. Use only standard
  Bootstrap utility classes and the project's custom tokens.
- **Font Awesome** — icons use `<i class="fas fa-...">`. Use the same icons as the
  mockups: `fa-search` for the dashboard identity, `fa-clock` for unreviewed status,
  `fa-check` for cleared, `fa-share` for referred, `fa-exclamation-circle` for
  escalated.
- **Copyright header** — every new Python file must carry the same
  `# Created by ...` header style as existing files.

---

## Out of scope for this task

- Export to Excel/CSV endpoints (stubs are sufficient — route exists, returns a
  flash + redirect with "not yet implemented")
- The similarity rebuild task implementation (already implemented in
  `app/tasks/similarity_analysis.py`)
- Any changes to the language analysis pipeline or its dashboard