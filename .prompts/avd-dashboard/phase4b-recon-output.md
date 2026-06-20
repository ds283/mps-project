# Phase 4b recon output — row consolidation into two-column panel layout

## 1. Current `columns` dict (`app/dashboards/views.py::avd_dashboard_ajax()`, verbatim before this phase)

```python
name_col = {
    "search": func.concat(UserModel.first_name, " ", UserModel.last_name),
    "order": [UserModel.last_name, UserModel.first_name],
    "search_collation": "utf8_general_ci",
}
year_col = {
    "search": ProjectClassConfig.year,
    "order": ProjectClassConfig.year,
}
report_grade_col = {
    "order": SubmissionRecord.report_grade,
}

def _role_holder_search_filter(search_expr):
    return SubmissionRecord.roles.any(SubmissionRole.user.has(search_expr))

records_col = {
    "search": func.concat(UserModel.first_name, " ", UserModel.last_name),
    "search_collection": _role_holder_search_filter,
    "search_collation": "utf8_general_ci",
}

columns = {
    "name": name_col,
    "year": year_col,
    "report_grade": report_grade_col,
    "records": records_col,
}

secondary_order = [ProjectClassConfig.year.asc(), SubmissionPeriodRecord.submission_period.asc()]
```

Current DataTables column definitions (`app/templates/dashboards/avd_dashboard.html`, verbatim):

```js
columns: [
    { data: 'name', render: { _: 'display', sort: 'sortstring' } },
    { data: 'year', render: { _: 'display', sort: 'sortvalue', type: 'sortvalue' } },
    { data: 'report_grade', className: 'text-end', render: { _: 'display', sort: 'sortvalue', type: 'sortvalue' } },
    { data: 'records', orderable: false }
],
order: [[2, 'desc'], [1, 'desc'], [0, 'asc']],
```

Table header (verbatim):

```html
<th width="18%">Student</th>
<th width="14%">Year and project class</th>
<th width="10%" class="text-end">Report grade</th>
<th width="58%">Submissions</th>
```

So the four logical columns are: **name** ("Student"), **year** ("Year and project class" — despite the key name, this column's template renders both the year badge and the project-class label), **report_grade** ("Report grade"), **records** ("Submissions" — despite the header name, this is already the rich panel: thumbnail, project title, research-group badge, period, consent badges, supervision/presentation grade line, convenor/out-of-tolerance flags, staff roles, Turnitin block, and the download buttons).

## 2. Current row-rendering templates (`app/ajax/archive/reports.py`, verbatim before this phase)

**`_name`** (student/title cell — actually just student + programme badge; no project title here):

```jinja2
{% set student = record.owner.student %}
{% set user = student.user %}
{% set programme = student.programme %}
<div>
    <a class="text-decoration-none" href="mailto:{{ user.email }}">{{ user.name }}</a>
</div>
{% if programme is not none %}
    <div class="mt-1">
        {{ simple_label(programme.label) }}
    </div>
{% endif %}
```

**`_year`** ("Year and project class" cell):

```jinja2
{% set config = record.period.config %}
<div>
    <span class="badge bg-secondary">{{ config.year }}&ndash;{{ config.year + 1 }}</span>
</div>
<div class="mt-1">
    {{ simple_label(config.project_class.make_label()) }}
</div>
```

**Consent badges** (`consent_badges(record)` macro inside `_report`, Phase 3 — unchanged by this phase): renders an AVD pill (solid teal when active, muted text when withdrawn/invited, nothing when never-asked) and an Exemplar line (muted text, shown only when not in the never-asked state). Reproduced in full in the new `_report` string below since this phase only relocates call-site context, not macro internals.

**`staff_roles()` / `report_flags()` macros** (Phase 4 — unchanged by this phase): `staff_roles(roles, moderator_role_id, moderation_outcome)` groups `record.roles.all()` by `role.role`, labels via `role_as_str`, pluralizes naively, and appends the moderation-outcome text inline on the moderator's line. `report_flags(convenor_intervention, out_of_tolerance_unassigned)` renders danger/warning subtle pill badges, shown only when at least one flag is true. Both reproduced unchanged inside the new template, just repositioned and (for `report_flags`) folded into a combined `flags_line` wrapper together with Turnitin chips — see Step 1 below.

**Turnitin block** (`turnitin_info(record)` macro inside `_report`, currently the *last* element in the panel, after staff roles): renders a 5-tier colour-coded similarity score plus web/publication/student overlap percentages, only when `turnitin_score is not none`.

**Supervision/presentation grade line** (currently a standalone `<div class="small text-muted mt-1">`, conditionally rendered only when at least one of the two grades is not None): `Supervision X% · Presentation Y%`.

**Download buttons** (right-hand flex column inside the `records` panel, unchanged structurally by this phase): Original/Processed download links, or a restricted/no-report indicator.

## 3. Search-string-building code, confirmed

The `data: 'name', render: {_: 'display', sort: 'sortstring'}` front-end pattern corresponds, server-side, to `avd_dashboard_rows()` (`app/ajax/archive/reports.py`) returning, per row:

```python
"name": {
    "display": render_template(name_templ, record=record, simple_label=simple_label),
    "sortstring": record.owner.student.user.last_name + record.owner.student.user.first_name,
},
```

`ServerSideSQLHandler` (`app/tools/ServerSideProcessing.py`) treats this `"display"/"sortstring"` split as a pure **client-side display/export concern** — it has no awareness of these keys at all. Its own ordering/search logic operates purely on the **Python `columns` dict** passed to its constructor (SQL `order`/`search` column expressions), not on the JSON payload shape. So the `display`/`sortstring`/`sortvalue` convention exists only for the DataTables front end (type detection, Buttons export value, sort-arrow rendering) and is independent of how the server actually orders/filters rows.

**Search**, confirmed by re-reading `ServerSideSQLHandler.__init__`: it iterates `self._data.values()` (i.e. *every* entry in the Python `columns` dict, regardless of whether that entry's key matches any front-end column's `data` field) and ORs together a `.contains(search_term)` filter for every entry that has a `"search"` key — wrapped in `.any()`/the `search_collection` callable when the entry also declares `"search_collection"`. This means **the `columns` dict can carry search-only entries with no corresponding visible DataTables column at all** — exactly the mechanism Step 2 needs to extend free-text search to programme/research-group/project-class names without adding new visible columns.

**Confirmed, contra recon.md §15's open question**: role-holder search (`records_col`) is *already* wired as a `"search"` + `"search_collection"` entry in the `columns` dict — i.e. it already feeds the DataTables free-text search box, not a separate filter/query-param. There is no separate `roles.any(...)` filter parameter anywhere in `avd_dashboard_ajax()`. Nothing to reconcile here; recon.md's open question was resolved correctly by the time Phase 4 actually shipped.

**Order**, confirmed: `ServerSideSQLHandler` only consults a `columns` dict entry's `"order"` key when the front-end's requested sort column's `data` field matches that dict key *and* DataTables actually sent an order request for it (which only happens for `orderable: true` columns, or columns named in the initial `order:` config). A dict entry with `"search"` but no `"order"` key is therefore safe to add purely for search purposes.

## 4. Responsive/wrapping behaviour

The narrow "Year and project class" column (`width="14%"`) in the screenshot forces the project-class colour badge and `period.display_name` text ("Submission Period #1") onto separate wrapped lines inside a 14%-wide cell. Once that column is removed and its content (year, project-class badge, period) becomes part of the single full-width "Report" panel's identity line, this wrapping problem disappears structurally — the panel already spans the remaining ~88% of the row width (only "Report grade" stays as a narrow second column). No additional CSS is needed beyond what Step 1 already does; `flex-wrap` on the identity-line container handles graceful wrapping at very narrow viewports without the previous "cell too narrow for its content" failure mode.

## Decisions for Step 1/2 (flagged, not silently picked)

- **Identity line contents**: programme (`student.programme.full_name`, plain text), research group (`record.project.group.name`, plain text — previously a colour badge, now stripped to plain text per this phase's explicit "all as plain text" instruction), **project-class badge kept as-is** (`simple_label(config.project_class.make_label())`, the one explicit exception called out in the phase prompt), year (`"{year}–{year+1}"`, plain text — previously a `bg-secondary` badge, now stripped), submission period (`period.display_name`, plain text, unchanged from Phase 2b), supervision/presentation grades (plain text, **now unconditionally present** with an em-dash placeholder when not yet graded, matching the existing `grade_display_data()` convention elsewhere in the model layer — a small, deliberate behaviour change from the previous "hide the whole line if both grades are None").
- **Flags line**: `report_flags()` and `turnitin_info()` are combined into one `flags_line()` macro so convenor-intervention/out-of-tolerance badges and Turnitin chips sit in the same flex row (wrapping together) rather than two separately-stacked divs — matches the phase prompt's "flags line: convenor_intervention, Turnitin score/band, AI risk (Phase 5), feedback doc link (Phase 5)" framing of these as one line. AI risk and feedback-doc link are left out entirely (no placeholder element) per "don't fabricate AI-risk content in this phase" — Phase 5's gap is the literal absence of any element here, not a fake placeholder.
- **`identity_parts` construction**: built as a plain Python list (mix of `str` and one `Markup` badge fragment from calling `simple_label` directly) in `avd_dashboard_rows()`, then rendered/joined with `&middot;` separators by a small `identity_line()` Jinja macro. This keeps autoescaping correct (plain strings still escaped by Jinja, the one pre-rendered badge fragment passed through safely) without resorting to the `{% set _ = list.append(...) %}` in-template idiom.
