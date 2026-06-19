# Phase 2 recon output

Status: investigation complete, no code changes made yet. Verified against current
source on `master` (HEAD `71f4eb8c`, which only added the two prompt files — Phase 1's
actual code landed in `995be605`/`d944fe09` earlier in the history; the route/template
it produced are exactly as described in `phase1-recon-output.md`). This is the plan to
review before Step 1 proceeds.

## 0.1 — Embargo logic

**Found in `app/ajax/archive/reports.py`** (`_records` Jinja string, lines 170-195),
which is *not* legacy/dead code — Phase 1 imports and calls it directly
(`from ..ajax.archive import retired_reports` in `app/dashboards/views.py:29`, called
at `avd_dashboard_ajax()`'s `handler.build_payload(retired_reports)`). This is the
live row content for the AVD dashboard's "Submissions" column today.

Exact code:

```jinja2
{% if r.report_secret %}
    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Report restricted</span>
{% elif r.report_embargo %}
    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Embargoed until {{ r.report.embargo.strftime("%a %d %b %Y %H:%M") }}</span>
{% else %}
    {# Original / Processed download buttons, or "No report" badge #}
{% endif %}
```

Three findings, none of which match the brief's example comparison:

1. **The "Report restricted" text belongs to `report_secret`, a separate boolean
   column, not to `report_embargo`.** `report_embargo` truthy produces a *different*
   message, "Embargoed until {date}". The brief's Step 1 framed the search target as
   "Report restricted text" but that text is gated on `report_secret`. I've confirmed
   this is intentional on the brief's part, not a wrong steer — Step 3 of the brief
   asks for a *new*, distinctly-worded indicator ("Restricted until {date}") rather
   than reusing "Report restricted" verbatim, which lines up with these being two
   independent concepts. **`report_secret` is out of scope for this phase** — see
   §0.1.4 below.
2. **The comparison is a bare truthiness check, not `report_embargo > datetime.now()`.**
   There is no date comparison anywhere in the codebase for this field. The same
   plain-truthy pattern (`{% if record.report_embargo %}`) appears in the only other
   call site, `app/templates/documents/submitter_manager.html:251` (an admin-only
   informational badge, not gating anything there). So a report stays "embargoed" in
   the UI forever once the field is set, regardless of whether the stored date has
   passed — staff must explicitly clear the field. This is the established,
   consistent convention across the codebase (two independent call sites agree), not
   a one-off bug, so I'm treating it as confirmed intended behaviour: **the helper
   should be `report_embargo is not None`, not a date comparison.**
3. **`r.report.embargo.strftime(...)` is a latent bug.** `report` is the
   `SubmittedAsset` relationship; it has no `.embargo` attribute (only
   `SubmissionRecord.report_embargo` exists — confirmed via
   `grep -rn "embargo" app/models/ app/documents/`). With Flask's default `Undefined`,
   calling `.strftime()` on the result would raise `UndefinedError` if this branch is
   ever actually hit at render time. I don't have a way to confirm whether any
   embargoed record currently exists in a live dataset to know whether this has ever
   fired — either way, the new helper must use `r.report_embargo.strftime(...)`, not
   reproduce this typo.
4. **UI elements suppressed**: the Original/Processed download-button block only
   (replaced by the text). There is no thumbnail in this template today — thumbnails
   are new in this phase (§0.2). `report_secret` is checked first and takes
   precedence; I'm leaving that branch untouched and layering the new
   `report_embargo` check into the same `{% elif %}` chain so the two stay mutually
   exclusive exactly as today, with `report_secret`'s existing message/behaviour
   unchanged.

## 0.2 — Thumbnail mechanism

`serve_thumbnail(asset_type, asset_id, size)` — `app/documents/views.py:1816-1866`.
Signature confirmed: `asset_type` is a literal `"SubmittedAsset"` or `"GeneratedAsset"`
string (looked up in `_THUMBNAIL_ASSET_TYPES`), `asset_id` the asset's own id, `size`
`"small"` or `"medium"`. Access control is `parent.has_access(current_user)` —
`AssetMixin.has_access` → `has_role_access` (root/admin always; else any role in
`asset.access_control_roles`) → falls back to `in_user_acl`. Per
`phase1-recon-output.md`'s tracing, `maintenance()` in `app/models/submissions.py`
already grants the (renamed) `data_dashboard_reports` role onto both the report and
processed-report assets, so `data_dashboard_reports`-only viewers will pass this
check without any extra ACL work in this phase.

Hardening already in place (confirmed, not re-implemented): on connection failure to
the object store, returns a 503 with an inline placeholder SVG
(`_THUMBNAIL_UNAVAILABLE_SVG`) rather than blocking/crashing; `timeout=(3.05, 10)` on
the outbound `requests.get`. Templates additionally pre-check
`asset.small_thumbnail and not asset.small_thumbnail.lost` before even constructing
the `<img src>`, so a known-absent thumbnail never issues a request at all.

**Closest existing call-site precedent**: `app/templates/faculty/dashboard/my_students.html:288-304`
— prefers the processed report (`GeneratedAsset`), falls back to the raw report
(`SubmittedAsset`), falls back further to a static 64×64 placeholder div with a
`fa-file-alt` icon when neither has a usable thumbnail:

```jinja2
{%- if record.processed_report and record.processed_report.small_thumbnail
        and not record.processed_report.small_thumbnail.lost %}
    <img src="{{ url_for('documents.serve_thumbnail', asset_type='GeneratedAsset', asset_id=record.processed_report.id, size='small') }}"
         alt="Report thumbnail" width="64" height="64"
         style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color); flex-shrink: 0">
{%- elif record.report and record.report.small_thumbnail and not record.report.small_thumbnail.lost %}
    <img src="{{ url_for('documents.serve_thumbnail', asset_type='SubmittedAsset', asset_id=record.report_id, size='small') }}"
         alt="Report thumbnail" width="64" height="64"
         style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color); flex-shrink: 0">
{%- else %}
    <div style="width:64px; height:64px; border-radius:6px; border:0.5px solid var(--bs-border-color);
                background:var(--bs-tertiary-bg); display:flex; align-items:center; justify-content:center; flex-shrink:0">
        <i class="fas fa-file-alt fa-lg" style="color: var(--bs-secondary-color)"></i>
    </div>
{%- endif %}
```

I'll reuse this exact pattern verbatim (literal asset-type strings, same fallback
chain, same 64px sizing) rather than `.get_type()`-style calls used elsewhere, since
this is the closest existing "report thumbnail inside a list of student rows" case.
Under embargo, this whole block is replaced by the "Restricted until {date}"
indicator in the same slot (per brief Step 3) — not rendered alongside it.

## 0.3 — Current `avd_dashboard_ajax()` columns dict

Copied verbatim from `app/dashboards/views.py:2868-2884`:

```python
    # Define columns for ServerSideSQLHandler
    name_col = {
        "search": func.concat(UserModel.first_name, " ", UserModel.last_name),
        "order": [UserModel.last_name, UserModel.first_name],
        "search_collation": "utf8_general_ci",
    }
    year_col = {
        "search": ProjectClassConfig.year,
        "order": ProjectClassConfig.year,
    }

    columns = {
        "name": name_col,
        "year": year_col,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(retired_reports)
```

`base_query` (lines 2824-2842) is rooted on `SubmittingStudent`, joined to
`ProjectClassConfig` → `ProjectClass` → `StudentData` → `UserModel` → `DegreeProgramme`
(outer). **`SubmissionRecord` is only joined conditionally**, inside the `group_filter`
branch (lines 2856-2865), and that branch adds `.distinct()` specifically because the
join is one-to-many and would otherwise duplicate student rows.

`ServerSideSQLHandler.__init__` (`app/tools/ServerSideProcessing.py:150-177`) calls
`order_col.asc()`/`.desc()` directly on whatever `columns[...]["order"]` holds, then
applies that `order_by` straight onto `base_query` before `.limit()`/`.offset()`. So
whatever expression `report_grade`'s `order` key points to must already be a valid,
unambiguous column expression against the *current* `base_query`'s FROM-clause shape
— see §0.3.1, this is not a small detail for this column.

`report_grade` is confirmed `Numeric(8, 3)` on `SubmissionRecord`
(`app/models/submissions.py`, `recon.md` §5). No `cast()` is needed for ordering a
`Numeric` column directly. Per the brief, this column isn't searchable as free text,
so no `search`/`search_collation` key is needed at all — only `order`.

### 0.3.1 (RESOLVED by user decision, superseding the analysis below) — row granularity and eligibility basis

Two decisions from you, while this was in scope:

1. **Each table row becomes one `SubmissionRecord`**, not one `SubmittingStudent`.
   Students with multiple periods in the same cycle simply produce multiple rows —
   expected, not a bug. This removes the report_grade aggregation ambiguity
   entirely: `report_grade`'s `order` key becomes a direct column reference
   (`SubmissionRecord.report_grade`), no correlated subquery needed.
2. **Eligibility switches from `SubmittingStudent.retired.is_(True)` to
   `SubmissionPeriodRecord.closed.is_(True)`.** Confirmed via
   `app/convenor/marking_feedback.py:357` (`do_close_period`) that `period.closed`
   is set by a convenor action well before the year's full rollover — a
   multi-period pclass can have its Part A period closed (and thus AVD-eligible)
   while Part B is still in progress and the whole `ProjectClassConfig`/
   `SubmittingStudent`/`SubmissionRecord.retired` flags stay `False` until the
   *next* rollover (`app/tasks/rollover.py:484-485` dispatches `retire_submitter`/
   `retire_selector` for every student in a config only when that config itself
   rolls over). The previous `retired`-based filter was therefore withholding
   already-finalized, already-marked reports for months longer than necessary.

**Revised `base_query`** (replacing `app/dashboards/views.py:2824-2865`):

```python
base_query = (
    db.session.query(SubmissionRecord)
    .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
    .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
    .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
    .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
    .join(StudentData, StudentData.id == SubmittingStudent.student_id)
    .join(UserModel, UserModel.id == StudentData.id)
    .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id, isouter=True)
    .filter(
        ProjectClass.uses_submission.is_(True),
        ProjectClass.active.is_(True),
        ProjectClass.publish.is_(True),
        ProjectClass.tenant_id == tenant_id,
        SubmissionPeriodRecord.closed.is_(True),
    )
)
```

Confirmed relationship names for this join chain: `SubmissionRecord.owner`
(→ `SubmittingStudent`, FK `owner_id`), `SubmissionRecord.period`
(→ `SubmissionPeriodRecord`, FK `period_id`), `SubmissionPeriodRecord.config`
(→ `ProjectClassConfig`, FK `config_id`) — all confirmed in
`app/models/submissions.py` / `app/models/project_class.py`.

The `group_filter` branch simplifies: `SubmissionRecord`/`LiveProject` are now
joined unconditionally already, so it becomes a plain
`.filter(LiveProject.group_id == value)` with no extra join and no `.distinct()`
(no fan-out risk any more — one row really is one record).

`_get_accessible_years_for_avd()` and `_avd_dashboard_summary_for_user()`
(`app/dashboards/views.py:2613-2675`) both currently filter on
`SubmittingStudent.retired.is_(True)`; both need the same swap to
`SubmissionPeriodRecord.closed.is_(True)` (joined via `SubmissionPeriodRecord.config_id
== ProjectClassConfig.id`) so the year-filter list and landing-page counts stay
consistent with what the table itself now surfaces.

`app/ajax/archive/reports.py`'s `retired_reports(students: List[SubmittingStudent])`
needs restructuring to take `records: List[SubmissionRecord]` directly and render
**exactly one card per row** (dropping the `{% for r in recs %}` loop — there's
only ever one `r` now, the row's own record). I'll rename it to
`avd_dashboard_rows()` to reflect the new input shape, and add a `report_grade`
field to its per-row dict (`display` formatted `"%.1f"|format(value) + "%"` or
`—`, `order`/`sortvalue` the raw `float|None`).

<details>
<summary>Original analysis before this was resolved (kept for context)</summary>

### 0.3.1 (superseded) — The structural problem: one table row is one `SubmittingStudent`, not one `SubmissionRecord`

`recon.md` §10 designs the eventual "Report" column around **one row = one report**.
The actual Phase 1 implementation kept the **original legacy shape**: one row = one
student, and `SubmittingStudent.ordered_assignments` (`app/models/live_projects.py:1978-1985`)
— a *dynamic, one-to-many* relationship — supplies however many `SubmissionRecord`s
that student has within this `ProjectClassConfig` (one per `SubmissionPeriodRecord`,
i.e. one per submission period within the same academic year — e.g. Part A / Part B
reports for the same pclass+year). Today these render as a stack of independent cards
inside the third ("Submissions") column; `retired_reports()` iterates `recs` and
renders one card per `SubmissionRecord` with its own grades/roles/Turnitin
info/download buttons.

This matters because of where each Phase 2 feature actually lands:

- **Thumbnail, embargo handling, supervision/presentation grade text** (Steps 2 and 3)
  all attach naturally to the **existing per-submission card**, one card per
  `SubmissionRecord`, exactly where Turnitin info and download buttons already live.
  There is no ambiguity here — each card already represents exactly one
  `SubmissionRecord`, so each gets its own thumbnail/restriction state/grade text
  independent of how many other cards the same student row has. (Note: the brief's
  wording — "existing identity block… student name / project title / programme /
  year… panel cell that already exists from Phase 1" — describes the *eventual*
  unified Report panel from `recon.md` §10, which Phase 3 builds. Today student
  name/programme and year/pclass are two separate `<td>`s, and project title lives
  inside each per-submission card, not in a combined identity block. I'm treating
  "the panel cell that already exists" as **the per-submission card inside the
  Submissions column** — the closest thing that already exists — rather than
  inventing a new combined block ahead of Phase 3. This produces the same visible
  outcome the brief asks for without restructuring the table.)

- **`report_grade` as a sortable, default-sort *table column*** (Step 1) is the one
  feature that's promoted to row level, and a `SubmittingStudent` row can have **more
  than one `report_grade`** when `number_submissions > 1` for the relevant pclass. An
  unconditional `.join(SubmissionRecord, SubmissionRecord.owner_id == SubmittingStudent.id)`
  would multiply each such student into N result rows before `ServerSideSQLHandler`'s
  `.limit()/.offset()` pagination — silently breaking "one row per student" and
  `recordsTotal`/`recordsFiltered` counts (the existing `group_filter` branch only
  gets away with joining `SubmissionRecord` because it then `.distinct()`s on
  `SubmittingStudent.*` columns only, with no per-record column in the `SELECT`/`ORDER
  BY`; `report_grade` ordering can't reuse that trick, because `DISTINCT` collapsing
  by the *non*-`SubmissionRecord` columns wouldn't determine *which* of the
  duplicated rows' `report_grade` survives for sort purposes — that becomes
  database-plan-dependent, i.e. non-deterministic row order on ties).

  **This needs a decision before I touch Step 1**, since it's a real design choice,
  not a bug to fix: what is "the" `report_grade` for a student-row when more than one
  `SubmissionRecord` exists? I see three options, and recommend (a):

  **(a) `MAX(report_grade)` via a correlated scalar subquery** — "the best report this
  student ever submitted in this scope," which matches the dashboard's stated purpose
  (`recon.md`: "report grade is the primary sort key for AVD selection" — you're
  browsing for good examples, so the best one is the relevant one). Deterministic,
  cheap, one extra correlated subquery in the `order` key only (no join, no `SELECT`
  change, no `.distinct()` needed since the base query's row identity is untouched).

  **(b) The *latest* period's `report_grade`** — "the final/most complete
  submission," via `ORDER BY submission_period DESC LIMIT 1` as a correlated scalar
  subquery. Matches a "most recent state" reading rather than "best ever."

  **(c) Leave multi-period students out of scope / accept non-deterministic ordering
  for them** — not recommended; silently wrong sort order for an unknown subset of
  rows is the kind of thing that erodes trust in the sort once someone notices it.

  Note this only affects the **sort key**; the per-card display in the Submissions
  column already shows every period's own `report_grade` individually and is
  unaffected by whichever option is chosen here.

</details>

## 0.4 — Current row template

`app/templates/dashboards/avd_dashboard.html` (Phase 1 output, full file read) defines
three DataTables columns: `name` (data: `'display'`/sort `'sortstring'`), `year`
(data: `'display'`/sort `'sortvalue'`/type `'sortvalue'`), `records`
(`orderable: false`). Default `order: [[1, 'desc'], [0, 'asc']]` (year desc, then
name asc). Table header (lines 179-187):

```html
<table id="reports-table" class="table table-striped table-bordered">
    <thead>
    <tr>
        <th width="20%">Student</th>
        <th width="15%">Year and project class</th>
        <th width="65%">Submissions</th>
    </tr>
    </thead>
</table>
```

The actual per-card row content lives server-side in `app/ajax/archive/reports.py`'s
`_records` Jinja string (quoted in full at §0.1) — this is what Steps 2/3 edit. Given
§0.3.1's resolution, this string drops its outer `{% for r in recs %}` loop entirely
and renders the row's single `record` directly; `_name`/`_year` similarly drop their
`sub.student`/`sub.config` indirection in favour of `record.owner.student`/
`record.period.config`. Step 1's new `report_grade` column is a genuine 4th column,
needing a 4th `<th>`, a 4th `columns: [...]` entry, and a `report_grade` field added
to the per-row dict emitted by the renamed `avd_dashboard_rows()`.

## Plan for Steps 1-4 (revised for one-row-per-`SubmissionRecord`)

### Step 1 — `report_grade` column
- `report_grade_col = {"order": SubmissionRecord.report_grade}` — direct column
  reference, no subquery, no search key (not free-text searchable per the brief).
- Add a 4th `<th>Report grade</th>` and a 4th `columns:` entry (`data: 'report_grade'`,
  right-aligned — checking the exact existing convention for right-aligned numeric
  DataTables columns elsewhere before picking the literal column option) to
  `avd_dashboard.html`.
- Default sort becomes `report_grade` desc; keep `year`/`name` as secondary
  tie-breakers (`order: [[3, 'desc'], [1, 'desc'], [0, 'asc']]`).
- Display value formatted `"%.1f"|format(value)` + literal `%`, or `—` when `None`
  (confirmed convention below).
- "Has grade" tri-state filter: a button-row entry styled like the existing
  pclass/year/group `<a href>` `btn-sm btn-primary`/`btn-outline-secondary` buttons
  (matching `.claude/rules/dashboard-colours.md`'s note that AVD's filter chrome
  hasn't been restyled yet). Tests `SubmissionRecord.report_grade.isnot(None)` /
  `.is_(None)` directly — no aggregation ambiguity now that each row is one record.

### Step 2 — Supervision / presentation grades as panel text
- Use `SubmissionRecord.grade_display_data()` (`app/models/submissions.py:2266-2296`)
  rather than reading `supervision_grade`/`presentation_grade` columns directly — it
  already filters by `period.supervision_grade_available`/`presentation_grade_available`
  and returns plain floats. Filter its result to the `"Supervision"`/`"Presentation"`
  labels only (excluding `"Report"`, now the dedicated column) and render
  `Supervision {x} · Presentation {y}` with `—` for `None`, inside the row's single
  card — replacing today's Supervision/Report metric-box pair
  (`app/ajax/archive/reports.py:139-154`).
- Format: confirmed via `app/templates/convenor/dashboard/submitters_v2.html:877`
  (`"%.1f"|format(g.grade)` + literal `%`) and the legacy code's own
  `{{ r.supervision_grade|round(1) }}%` — **both existing conventions already append
  `%`**. I'll use `"%.1f"|format(value)` + `%` for `report_grade`,
  `supervision_grade`, and `presentation_grade` uniformly.

### Step 3 — Thumbnails, with embargo handling
- One thumbnail per row, using the exact `my_students.html` fallback chain from §0.2
  (processed → raw → placeholder icon).
- New `SubmissionRecord.is_report_restricted` property (placed next to
  `report_embargo`/`report_secret`, `app/models/submissions.py` around line 850):
  `return self.report_embargo is not None`. Deliberately *not* a date comparison —
  see §0.1 finding 2.
- When `is_report_restricted`, replace the thumbnail slot with a "Restricted until
  {report_embargo:%a %d %b %Y %H:%M}" indicator (same slot, so rows don't jump
  around) and replace the Original/Processed download-button block the same way.
  `report_secret`'s existing, separately-worded "Report restricted" branch is left
  untouched and still takes precedence, per brief scoping (§0.1 finding 1).
- Forward dependency note for Phase 5 (not implemented now): `is_report_restricted`
  should also gate the feedback-document link and arguably the
  AI-declaration/LLM-summary details-panel content once those exist.

### Step 4 — Verification
- `grep -rn "report_embargo"` after the edit — expect every truthy-check call site
  (the new helper's own definition, plus the pre-existing, untouched
  `submitter_manager.html` informational badge) and zero remaining ad hoc
  `if r.report_embargo` duplicates in `reports.py`.
- `grep -rn "report_grade\|SubmissionPeriodRecord.closed\|SubmittingStudent.retired"`
  around `app/dashboards/views.py`'s AVD section — confirm `avd_dashboard_ajax()`,
  `_get_accessible_years_for_avd()`, and `_avd_dashboard_summary_for_user()` all agree
  on the `closed`-based eligibility basis, with no stray `retired`-based filter left
  behind in any of the three.
- MySQL/MariaDB NULL-ordering check (this project's primary DB, per `CLAUDE.md`):
  **MySQL sorts `NULL` as the smallest possible value** — opposite of "most DBs sort
  nulls last by default" (true for Postgres/Oracle, not MySQL). For the chosen
  default sort (`report_grade DESC`), ungraded rows already sort **last** with no
  extra `NULLS LAST` clause needed. Ascending sort puts them **first** instead —
  flagging as expected MySQL behaviour, not a bug.
- Manual checks as specified in the brief: a multi-period student now appears as
  multiple distinct rows (confirm this looks intentional, not like a duplicate-row
  bug, in the rendered table); a period that's `closed=True` within the *current*,
  not-yet-fully-retired academic year now appears in the table.

## Out-of-scope confirmation

- `report_secret` — separate field, separate "Report restricted" message, left
  exactly as-is (§0.1 finding 1).
- No consent badges, staff-roles block, details child-row, or feedback-document
  link — confirmed not touched; these stay Phase 3-5 per `recon.md`.

## Resolved decisions (were open questions, now settled by you)

- One row per `SubmissionRecord`, eligibility basis is `SubmissionPeriodRecord.closed`
  — see §0.3.1.
