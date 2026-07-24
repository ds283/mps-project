# Matching workspace refine — period-anchored redesign

## Context

The matching workspace (`admin/matching_workspace/*`) lets root/admin/convenors inspect an automatic
matching attempt. Its primitive is one **`MatchingRecord`** = an allocation of a `LiveProject` +
`MatchingRole`s to one `SubmittingStudent` for **one** `SubmissionPeriodDefinition`.

Today the **submission period of an allocation is invisible**: the student tab (`_student_pane.html`)
and faculty tab (`_faculty_pane.html`) never name the period, so two allocations of the same project in
different periods (e.g. Prof Calmet supervising *Theoretical Aspects of Black Holes* in both the autumn
and spring MPP periods) are indistinguishable, and rows can only be disambiguated by row order. The old
system's at-a-glance scanning (per student **and** per period) was lost when both tabs became flat
server-side DataTables.

A Claude Design handoff (`.prompts/matching-workspace-refine/reference/project/HANDOFF.md`, visual target
`Matching workspace redesign.dc.html`, options **1a–1d**) specifies the fix: **keep one row per
`MatchingRecord`, but make every allocation name its `SubmissionPeriodDefinition` everywhere** — a leading
period pill on the student tab, a `class · period` tag on the faculty tab and reassignment modal, and
period context + siblings in the student drawer. Grouping "by period" must be anchored on the
`SubmissionPeriodDefinition` itself, so unrelated "period 1"s in different project classes never merge.

**Decisions taken with the user (2026-07-24):**
1. **Both** the student and faculty tabs are rebuilt as **server-rendered, paginated lists** in the visual
   language of `convenor/dashboard/submitters_v2.html` (dropping their server-side DataTables), for
   cross-tab consistency. Student search = by student name; faculty search = by faculty name. Both
   paginated. Pagination/search/per-page controls reuse the `submitters_v2` styling.
2. **Period pill colour** is a generated **ordered colour family derived from each `ProjectClass`'s own
   colour** — periods within a class are distinguishable but anchored on the class hue. Generate ~5 stops
   and cycle if a class has more periods.

Consequence to note: dropping DataTables removes the per-tab search-everywhere box and the copy/csv/
excel/pdf/print export buttons for these two tabs (the reference mock and `submitters_v2` have neither;
the pclass/type/hint filters and a name search remain). This is accepted.

---

## Key files & current behaviour (from exploration)

- **Route**: `app/admin/matching.py`
  - `matching_workspace(id)` (L1874) renders `workspace.html`, passing `pclasses`, `pclass_filter`,
    `type_filter`, `hint_filter` (session-persisted), `text`/`url`.
  - `match_student_view_v2_ajax` (L1961) — DataTables JSON via `ServerSideInMemoryHandler`; filters records
    by pclass/type/hint lambdas; row formatter → `ajax.admin.student_view_v2_data`.
  - `match_faculty_view_v2_ajax` (L2203) — same pattern → `faculty_view_v2_data`.
  - `match_student_drawer_ajax` (L2055) → `_student_drawer.html`.
  - `faculty_reassign_ajax` (L2291) → `_faculty_reassign_modal.html`.
- **Service**: `app/shared/matching_workspace.py`
  - `student_row` (L218), `student_drawer` (L261), `faculty_row` (L339), `faculty_drawer` (L478),
    `_group_records_by_pclass` (L189).
- **Row templaters (string-templates)**: `app/ajax/admin/matching/match_view_student_v2.py`,
  `.../match_view_faculty_v2.py`.
- **Templates**: `app/templates/admin/matching_workspace/` — `workspace.html` (shell + DataTable init +
  offcanvas/modals), `_student_pane.html`, `_faculty_pane.html`, `_student_drawer.html`,
  `_faculty_reassign_modal.html`, `_macros.html`, `_comments_panel.html`.
- **JS**: `app/static/js/admin/matching_workspace.js` — delegated listeners keyed on `data-rec-id`,
  `data-bs-toggle`, `.mw-drawer-open-comments`, `.mw-open-student`, `.mw-hint-dropdown`, drawer-chain
  navigation. Refreshes after edits via `window.matchStudentTable.ajax.reload()` (L57–58) /
  `window.matchFacultyTable.ajax.reload()` (L468–469).
- **Model facts**:
  - `MatchingRecord.period` (`app/models/matching.py:1284`) → the `SubmissionPeriodDefinition` via
    `pclass.get_period(self.submission_period)`. `record.current_score`, `record.total_rank` exist.
  - `SubmissionPeriodDefinition` (`app/models/project_class.py:611`): `.period` (1-based position in class),
    `.name`, `.owner` (`ProjectClass`), `.display_name(year)`.
  - `ProjectClass` ordering used app-wide is `ProjectClass.name` (no numeric sort field) → class sort key
    = `pclass.name`. `ColouredLabelMixin.make_CSS_style()` (`model_mixins.py:75`) uses `self.colour` (raw
    hex) + `get_text_colour`.
  - `app/shared/colours.py` already imports the `colour` lib (`from colour import Color`) — gives HSL.
- **`submitters_v2` pattern** (`convenor/submitters.py` + `submitters_v2.html`): server-side filter +
  Python slice; query params `name_filter`, `page`, `per_page` (default 10; options 5/10/15/20); controls
  `.sv2-search-input`, `.sv2-per-page-select`, `.sv2-pager`, `.sv2-pager-btn`, `.sv2-fbtn`; "Showing X–Y of
  Z entries" footer; every filter/pager link is a full-page GET that resets `page=1` on filter change.

---

## Sorting rule (applies to 1a "by period" grouping and 1c allocation order)

Stable order everywhere periods are grouped/listed:
1. Group by `ProjectClass` in `ProjectClass.name` order.
2. Within a class, by `SubmissionPeriodDefinition.period` ascending.
3. All periods of one class are contiguous; classes follow one another. "period 1" of different classes
   are **distinct groups**, keyed on the `SubmissionPeriodDefinition` (id), never merged.

Central sort key helper: `period_sort_key(spd) -> (spd.owner.name, spd.period)`.

---

## Phase 1 — Shared foundations (colour ramp, period pill, service exposure)

**Goal:** a reusable, class-anchored period-colour system and the data plumbing every option needs.

1. **`app/shared/colours.py`** — add:
   - `period_colour_family(base_colour: str, count: int) -> list[dict]`: derive `count` subtle shade
     triples from `base_colour` using the `colour` lib. Convert base → HSL; rotate hue by a fixed set of
     offsets (e.g. `[0, -25, +25, -50, +50]` degrees) per period position, **cycling** when
     `count` exceeds the offset count. Each entry returns:
     - `pill_bg` (high-lightness, reduced-saturation tint), `pill_fg` (dark emphasis), `pill_border`
       (mid tint),
     - `band_bg` (lighter than pill_bg), `band_fg`, `band_border` — for "by period" group bands.
     All values are `Color(...).hex_l` strings computed from the class hue (no hardcoded palette).
     Guard `base_colour is None` → return neutral tokens (fall back to `var(--bs-secondary-*)`).
   - Keep it pure/deterministic; memoise per `(base_colour, count)` if convenient.

2. **`app/shared/matching_workspace.py`** — add:
   - `build_period_pill(spd) -> dict`: `{ "id", "name" (spd.name or display_name), "position" (spd.period),
     "count" (spd.owner.number_submissions), "pclass_abbrev", "pclass_swatch" (owner.make_CSS_style()),
     "colours" (period_colour_family(owner.colour, owner.number_submissions)[spd.period-1]) }`. Cache the
     family per `pclass_id` within a request.
   - `period_sort_key(spd)` as above.
   - Have `student_row` expose `"period": build_period_pill(record.period)` (guard None period).

3. **`_macros.html`** — add two reusable macros (Bootstrap-token / inline-derived-colour only, per
   `.claude/rules/template-colours.md`; the class hex is model-supplied like existing swatches):
   - `period_pill(pill)` → the standalone period chip (fill/fg/border from `pill.colours`).
   - `class_period_tag(pill)` → swatch + `pclass_abbrev` + `period_pill(pill)` for the faculty/reassign
     `class · period` tag.

4. **Shared list controls partial** — new
   `app/templates/admin/matching_workspace/_list_controls.html` with macros for the toolbar (search box,
   per-page select, group-by toggle) and the pager, styled to match `submitters_v2` (mirror the
   `.sv2-*` CSS values under an `mw-*` prefix in one scoped `<style>`). Used by both panes so the tabs read
   as one system.

**Commit:** "matching-workspace-refine: period colour family, period_pill macros, shared list controls".

---

## Phase 2 — Student dashboard (1a)

**Goal:** rebuild `_student_pane.html` as a server-rendered, grouped, paginated list with a leading period
pill, a Student⇄Submission-period group-by toggle, group bands + score roll-ups, and the comment anchor
moved into each row's Actions cell.

1. **Route `matching_workspace`** (student view branch), `app/admin/matching.py`:
   - Read new params: `group_by` (`student`|`period`, default `student`, session-persisted like the other
     filters), `name_filter`, `page`, `per_page` (default 10; 5/10/15/20).
   - Build the full record list: `attempt.records` ordered by selector then `submission_period`; apply the
     existing pclass/type/hint predicates (reuse the current lambda logic, moved inline) plus a
     case-insensitive `name_filter` on `record.selector.student.user.name`.
   - Group + roll-up in Python:
     - **By student**: group key `(student.id, pclass.id)`; band carries name, class swatch, programme ·
       cohort, period count, and `Total` = Σ `current_score`. Order groups by student surname then
       `pclass.name`; rows within a group by `period_sort_key`.
     - **By period**: group key `spd.id`; band carries class swatch, `"<ProjectClass> · <period name>"`,
       allocation count, `Σ` score, and `band_*` colours from the family. Order groups by
       `period_sort_key`; rows within a group by student surname.
   - **Paginate by group unit** (a group renders whole; groups never split across pages) — "Showing X–Y of
     Z groups". Slice the ordered group list.
   - Pass `groups`, pagination metadata, `group_by`, `name_filter`, filters, and a shared CSRF-less GET
     model to the template. Retire `match_student_view_v2_ajax` + `ajax.admin.student_view_v2_data` for the
     student pane (leave the module in place if still imported elsewhere; otherwise remove).
2. **`_student_pane.html`** — full rewrite:
   - Toolbar via `_list_controls` macros: search (student name) + per-page + **group-by toggle pills**
     (`fa-user-graduate` Student / `fa-layer-group` Submission period), then the existing collapsible
     pclass/type/hint filter panel (restyled to `sv2-fbtn` pills; keep the show/hide toggle).
   - Column header grid: **Period | Project | Markers | Rank | Score | Actions** (by student) or
     **Student | Project | Markers | Rank | Score | Actions** (by period) — first column label switches on
     `group_by`.
   - Group band per group (student band = neutral `var(--bs-tertiary-bg)` + class swatch + roll-up; period
     band = `band_*` tint from the family). Under "by period", render the info note about definition-keyed
     grouping from the mock.
   - Each record row: leading `period_pill(row.period)` (by student) or student name + swatch (by period);
     project (role-editor modal trigger, `modified_pill`, `programme_pref_line`); markers; rank (`rank_band`
     colour); score; **Actions cell** with Details link + the comment anchor (`💬`/count/`+`) — reuse the
     exact trigger markup/attributes currently in `match_view_student_v2.py`'s `_student` block
     (`data-bs-toggle="offcanvas" data-bs-target="#matchCommentsPanel" data-rec-id=…`, unseen-dot, add-focus)
     so `matching_workspace.js` keeps working unchanged. Journal chip + ticket chip retained.
   - Pager via `_list_controls`.
3. **`workspace.html`** — remove the `#match_student_v2` DataTable init block; keep `import_datatables`
   only while the faculty tab still needs it (removed in Phase 4). Student pane content is now present at
   load, so delegated tooltips/handlers from `base.html` cover it.
4. **`matching_workspace.js`** — replace `window.matchStudentTable.ajax.reload(null,false)` with a helper
   `reloadWorkspace()` = `window.location.reload()` (current URL already carries view + filters + page +
   per_page). Guard the old `if (window.matchStudentTable)` branch.

**Verify:** load student tab; confirm period pills, both groupings, roll-ups, search, pagination, and that
opening the drawer / role editor / comments and resolving a comment still refresh correctly.
**Commit:** "matching-workspace-refine: rebuild student dashboard (1a) as grouped paginated list".

---

## Phase 3 — Student drawer (1b)

**Goal:** the drawer names the period it is showing and surfaces the student's other allocations.

1. **`student_drawer`** (`matching_workspace.py`): add
   - `period` = `build_period_pill(record.period)` and a `position_label` = `"<name> · <k> of <n>"` where
     `k`=`spd.period`, `n`=count of the student's records in that project class.
   - `siblings`: the student's **other** `MatchingRecord`s (same selector, other submission periods within
     the class — and any other class the student has records in), each as
     `{ record_id, period (pill), project_name, rank, assigned (bool) }`, ordered by `period_sort_key`.
2. **`_student_drawer.html`**: add a period-context header block (label + `position_label`) and a
   sibling-allocations strip (one small card per sibling: period pill · project · `#rank` · assigned dot).
   Sibling cards carry `data-rec-id` and a class (e.g. `mw-drawer-swap-record`). Scope the Assigned-project
   header's pill to the current period. Comments / Ranked selection / Journal stay scoped to the current
   record (unchanged).
3. **`matching_workspace.js`**: delegate-click on `.mw-drawer-swap-record` → re-fetch the drawer for the
   clicked `data-rec-id` (reuse the existing `openStudentDrawer(recId)` fetch path against
   `match_student_drawer_ajax`), replacing the body **without** closing the offcanvas and without pushing a
   drawer-chain hop.

**Verify:** open a multi-period student's drawer; confirm the header names the period, sibling cards render,
and clicking a sibling swaps content in place.
**Commit:** "matching-workspace-refine: student drawer period context + siblings (1b)".

---

## Phase 4 — Faculty view (1c) + faculty pane conversion

**Goal:** every supervising/marking allocation carries a `class · period` tag and reads in the Sorting
order; the faculty tab becomes a server-rendered, paginated, name-searchable list consistent with the
student tab.

1. **Service** (`matching_workspace.py`): replace `_group_records_by_pclass`'s consumption in `faculty_row`
   with a **flat allocation list** per column (supervising / marking): each item
   `{ record, student, project, period (build_period_pill), programme_pref }`, sorted by
   `period_sort_key(record.period)`. Keep `offered_by_pclass` for the name-column summary.
2. **`match_view_faculty_v2.py`**: update the `_supervising` / `_marking` string-templates to render a flat
   list where each allocation line leads with `class_period_tag(item.period)` then `student · project`
   (drop the per-pclass sub-header grouping). If the faculty pane moves fully server-rendered (below), fold
   these into Jinja partials instead.
3. **Faculty pane conversion** — `_faculty_pane.html` + route:
   - Route (faculty view branch): read `name_filter`/`page`/`per_page`; build the faculty list
     (`attempt`-scoped, filtered by `pclass_filter` and a case-insensitive `name_filter` on the faculty
     user name); map each to `faculty_row`; paginate; pass to the template.
   - `_faculty_pane.html`: server-rendered rows (Name / Supervising / Marking / Workload) using the same
     `_list_controls` toolbar (faculty-name search + per-page) and pager; each supervising/marking
     allocation uses `class_period_tag`. Retire `match_faculty_view_v2_ajax` for the pane.
   - `workspace.html`: remove the `#match_faculty_v2` DataTable init and the now-unneeded
     `import_datatables()` for the workspace.
   - `matching_workspace.js`: replace `window.matchFacultyTable.ajax.reload()` with `reloadWorkspace()`.

**Verify:** faculty tab shows `class · period` on every allocation, Calmet's two black-hole allocations are
distinct, allocations sort by class then period, and search/pagination work.
**Commit:** "matching-workspace-refine: faculty view period tags + paginated pane (1c)".

---

## Phase 5 — Reassignment modal (1d)

**Goal:** period identity on the assigned-student cards only.

1. **`faculty_drawer`** (`matching_workspace.py`): each `projects[*].assigned` entry gains
   `period = build_period_pill(record.period)` (a record belongs to a period).
2. **`_faculty_reassign_modal.html`**: in the **Currently assigned** cards, render `class_period_tag` for
   each student's record. Leave **Per-project capacity** rows unchanged (class swatch + abbreviation only —
   a `LiveProject` is period-independent; capacity accumulates across periods). Assignable-pool cards
   unchanged.

**Verify:** open the reassignment modal; assigned cards show the `class · period` tag, capacity rows do not.
**Commit:** "matching-workspace-refine: reassignment modal assigned-card period tags (1d)".

---

## Phase 6 — Faculty pane sort controls

**Goal:** the Faculty tab's hard-coded surname-order sort becomes a Name/Workload toggle with independent
ascending/descending direction, session-persisted like the pane's other filters.

1. **`matching_workspace.py`**: add `faculty_workload_total(attempt, fac)` next to `faculty_row` — returns
   `sup + mark` from the memoized `attempt.get_faculty_CATS(fac.id)`, so summing it across every candidate
   for sorting before pagination is cheap.
2. **`matching.py`** (faculty branch of `matching_workspace()`): read `sort_by` (`"name"`/`"workload"`,
   default `"name"`) and `sort_dir` (`"asc"`/`"desc"`) via the same query-arg → session-fallback → validate
   → session-write pattern as `group_by`, under new keys `admin_match_faculty_sort_by` /
   `admin_match_faculty_sort_dir`. When no `sort_dir` is supplied by either the query string or the
   session, default it from `sort_by`: `"desc"` for `workload`, `"asc"` for `name` — so a bare first visit
   and a field switch both land on the sensible per-field default. Replace the hard-coded
   `candidates.sort(...)` with a branch on `sort_by` (`faculty_workload_total` vs. surname/first-name),
   `reverse=(sort_dir == "desc")` in both branches. Add `sort_by`/`sort_dir` to `faculty_ctx`.
3. **`_faculty_pane.html`**: import `mw_toolbar_sep, mw_toggle_pills`; add `sort_by`/`sort_dir` to
   `base_params` (so search, pager, and pclass-filter links round-trip them) and to the two pclass-filter
   `<a>` links' explicit `url_for` args. In the toolbar, after `mw_search_form(...)`: a separator, a "Sort
   by" label, two hand-built `mw-fbtn` pills (Name → `sort_by='name', sort_dir='asc'`; Workload →
   `sort_by='workload', sort_dir='desc'`) — plain links rather than `mw_toggle_pills`, since each pill must
   set two query params at once — then an `mw_toggle_pills(..., 'sort_dir', dir_options, sort_dir)` toggle
   whose `dir_options` labels ("A → Z"/"Z → A" vs. "Low → High"/"High → Low") depend on the current
   `sort_by`.

**Verify:** default load is unchanged (Name A→Z); Workload pill reorders highest-CATS-first with "High →
Low" active; the direction pill flips to "Low → High" and reverses order; switching back to Name resets to
A→Z; the sort selection survives pclass filter, name search, per-page, and paging.
**Commit:** "matching-workspace-refine: faculty pane name/workload sort controls".

---

## Cross-cutting constraints

- **Colours:** only Bootstrap 5.3 tokens or app semantic tokens, except the model-supplied class hex fed
  through the colour family / `make_CSS_style()` (same allowance swatches already use). No hand-picked hex
  literals in templates (`.claude/rules/template-colours.md`).
- **Initials/avatars** (comments panel): keep using `user.initials`.
- **Return links:** preserve `url`/`text` threading (`.claude/rules/return-link-url-text.md`); all
  filter/pager/toggle links are same-view GETs that carry `view`, filters, `url`, `text`, and reset
  `page=1` on any filter/search/toggle change.
- **No model or DB migration changes** — only service-layer exposure of existing
  `SubmissionPeriodDefinition` data.
- **Commit per phase** (memory: clean rollback points); run `ruff format --line-length 150` and
  `ruff check .` before each commit.

## End-to-end verification

- `ruff check .` clean; app boots via `python serve.py`.
- Manually exercise a completed matching attempt with ≥2 project classes and ≥2 periods (the HANDOFF's
  MPP autumn/spring + BSc full-year shape):
  - **1a**: period pills; Student and Submission-period groupings; per-group Total/Σ roll-ups; a student
    with records in two classes appears as two "by student" groups; MPP-period-1 and BSc-period-1 are
    separate "by period" groups; comment anchor in the Actions cell opens the comments panel; search +
    pagination + per-page work.
  - **1b**: drawer names the viewed period ("Autumn term · 1 of 2") and lists siblings; sibling click swaps
    in place.
  - **1c**: `class · period` tag on every supervising/marking allocation; Sorting order holds; a staff
    member supervising the same project in two periods shows two distinct tagged lines; faculty-name search
    + pagination work.
  - **1d**: assigned cards tagged with `class · period`; capacity rows untagged.
- Confirm role-editor edits, quick reassignment, hint changes, and comment resolve all refresh the pane
  (page reload) and update the comments badges.

## Note on the plan file location

The user asked to save this at `./.matching-workspace-refine/PLAN.md`. The reference bundle lives at
`.prompts/matching-workspace-refine/reference/`, and this repo keeps working docs under `.prompts/<name>/`
(per project memory). On approval I will write the plan to **`.prompts/matching-workspace-refine/PLAN.md`**
(sibling of `reference/`) unless the user prefers the literal `./.matching-workspace-refine/PLAN.md`.
