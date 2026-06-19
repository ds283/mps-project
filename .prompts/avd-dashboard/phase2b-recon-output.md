# Phase 2b recon output — submission period surfacing + secondary sort

## 1. Existing join from `SubmissionRecord` to `SubmissionPeriodRecord`

Already present in `avd_dashboard_ajax()` (`app/dashboards/views.py`), in the
`base_query` construction:

```python
base_query = (
    db.session.query(SubmissionRecord)
    .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
    .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
    .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
    ...
)
```

Both `SubmissionPeriodRecord` and `ProjectClassConfig` are already joined
entities in the query (this is the same join Phase 2 added to switch
eligibility to `SubmissionPeriodRecord.closed`). No new join is needed to add
a period-based sort key — `SubmissionPeriodRecord.submission_period` and
`ProjectClassConfig.year` are both already query-level columns.

## 2. `display_name` vs legacy wording — already implemented

`SubmissionPeriodRecord.display_name` (`app/models/project_class.py:2239`)
returns `"Submission Period #{n}"` (or a custom `name` if set) — confirmed
correct.

Checking the legacy `app/templates/archive/reports.html`-era row formatter
(pre-Phase-2 `app/ajax/archive/reports.py`, before it was renamed to
`avd_dashboard_rows`), the per-submission identity line already rendered:

```jinja2
{% if period is not none %}
    <div class="small text-muted">{{ period.display_name }}</div>
{% endif %}
```

The Phase 2 restructure (commit `22227c3e`) carried this line over verbatim
into the new per-record `_report` template's identity line in
`app/ajax/archive/reports.py` (currently lines 150–152), alongside the
project name / group label:

```jinja2
{% if period is not none %}
    <div class="small text-muted">{{ period.display_name }}</div>
{% endif %}
```

**Step 1 of this phase is therefore already satisfied by existing code** —
no template change needed. Verified by reading the current file; nothing
further to add.

## 3. Is `submission_period` globally meaningful, or per-config-relative?

Per-`ProjectClassConfig`-relative, confirmed from the model comment at
`app/models/project_class.py:2087-2091`:

```python
# submission period
# note this does not directly link to SubmissionPeriodDefinition; it's a literal number that refers
# to the numerical position of the SubmissionPeriodDefinition record, but it isn't a link to the
# SubmissionPeriodDefinition primary key
submission_period = db.Column(db.Integer(), index=True)
```

It's just "position N within this config's periods" (1, 2, 3, ...). Since the
AVD dashboard spans years and (when `pclass_filter == "all"`) multiple
project classes at once, sorting by `submission_period` alone would
incorrectly cluster e.g. every "Period #1" from every year together,
treating 2023's period 1 as equivalent to 2024's period 1.

**Decision: secondary sort key is `(ProjectClassConfig.year, SubmissionPeriodRecord.submission_period)`**,
both ascending. This groups rows chronologically by year first, then by
period position within that year — consistent with how period number is
used across the app as a "stage within the year" indicator (e.g. period 1 is
typically an autumn-term submission, period 2 spring, etc., even when
pclasses differ), and matches the recon note's stated reasoning.

Not adding `ProjectClass`/pclass to the tiebreak: the row's own year/pclass
badge (already shown in the `_year` column) makes pclass identity visually
explicit, so two different pclasses' "Period #1, 2024" rows sitting adjacent
under a tied primary sort is not a correctness problem — it's the same
"period 1" stage-of-year grouping the dashboard already wants.

## 4. How `ServerSideSQLHandler` applies sort, and how to append a tiebreak

`app/tools/ServerSideProcessing.py::ServerSideSQLHandler.__init__` parses the
DataTables `order` array and, for each requested sort column found in the
`columns` dict (matched by `data` field name), does:

```python
if dir == "asc":
    self._query = self._query.order_by(order_col.asc())
else:
    self._query = self._query.order_by(order_col.desc())
```

This loop can run multiple times (DataTables sends one entry per active sort
column — e.g. the AVD dashboard's default multi-column initial sort
`order: [[2,'desc'],[1,'desc'],[0,'asc']]` produces three loop iterations).

SQLAlchemy 2.0's `Query.order_by()` **appends** to any pre-existing ORDER BY
criteria (it only resets if you explicitly pass `None`/`False`), so successive
calls — including ones added *after* this loop completes, before the query is
executed — compose rather than replace. This means a tiebreak key can be
appended unconditionally after the existing per-request loop without
disturbing whatever order the request specified, including the case where a
user single-clicks a column header and the request only contains that one
sort column.

**Implementation approach**: add an optional `secondary_order` constructor
parameter to `ServerSideSQLHandler` (default `None`, so all ~50 existing call
sites are unaffected). If supplied, it's a list of SQLAlchemy order-by
expressions appended via one more `self._query.order_by(*secondary_order)`
call, placed after the existing per-request order loop and before
`.limit()`/`.offset()` are applied (call order doesn't actually matter for
the final SQL, since `Query` objects build an immutable clause set, but this
placement keeps the code's reading order matching execution order).

`avd_dashboard_ajax()` then passes:

```python
secondary_order=[ProjectClassConfig.year.asc(), SubmissionPeriodRecord.submission_period.asc()]
```

This composes correctly with every filter already applied to `base_query`
(tenant, pclass, year, group, has-grade) — it's purely an additional
`ORDER BY` clause, not a new filter or join.
