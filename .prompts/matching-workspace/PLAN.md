# Matching Workspace — Implementation Plan

> This is the living plan for the Matching Workspace redesign. The companion checklist is
> `.prompts/matching-workspace/TODO.md`; keep it updated as each item completes. The design
> reference (hi-fi prototype, README, screenshots) is under `.prompts/matching-workspace/reference/`.

---

## Context

The admin **project-matching workspace** lets a convenor/administrator review the output of the
optimiser that allocates students to supervised projects (a `MatchingAttempt` and its per-student
`MatchingRecord`s), make manual corrections, see how the current state diverges from the optimiser
baseline, and (new) leave review comments before publishing to convenors.

The current UI is spread across several DataTables-heavy admin pages (`match_student_view`,
`match_faculty_view`, `match_dists_view`) plus two near-duplicate dashboard list pages
(`admin/matching/manage.html` for root and `convenor/matching/audit.html` for convenors). It has
seven known gaps (slow dashboard load, weak student/faculty inspectors, no faculty-level
reassignment, no review comments, no change tracking, cluttered tables).

A hi-fi HTML design prototype (`.prompts/matching-workspace/reference/Matching Workspace.dc.html`
+ `README.md` + screenshots) specifies a single **pill-nav workspace** with four tabs — Student,
Faculty, Changes, Matches — plus right-hand drawers (student & faculty inspectors), a unified role
editor modal, a faculty reassignment workspace modal, and a review-comments panel. This plan
recreates that design in the app's real stack (server-rendered Jinja2 + Bootstrap 5 + DataTables +
Bootstrap offcanvas/modals + vanilla JS), binding to the real data model.

**Intended outcome:** one coherent workspace that paints instantly, gives strong per-student and
per-faculty inspection, supports manual reassignment with capacity/constraint awareness, tracks
changes against the optimiser baseline, and hosts scoped review comments — replacing the current
scattered pages while preserving today's access-control model.

## What already exists (reuse — do not rebuild)

- **Optimiser baseline is already stored.** `MatchingRecord` keeps immutable optimiser fields
  (`original_project_id`, `original_alternative`, `original_parent_id`, `original_priority`) and a
  separate `original_roles` relationship, alongside the live `project_id`/`rank`/`alternative`/…
  and live `roles`. Edits never touch the `original_*` side. → *MODIFIED* pills and the Changes
  tab derive from live-vs-original comparison; no new baseline storage is needed.
- **All lifecycle/edit routes exist** in `app/admin/matching.py` (admin blueprint, prefix `/admin`):
  reassign project/marker/supervisor, duplicate, rename, delete, revert-to-baseline, publish/select,
  CSV/Excel export, compare, distributions, populate-submitters. Reuse them; add only a unified
  role-edit endpoint and a few AJAX feeds.
- **Row formatter is already privilege-aware:** `ajax.admin.matches_data(matches, config=None,
  is_root=False, text, url)` (`app/ajax/admin/matching/matches.py`) renders dashboard rows and is
  shared today by both `manage_matching` (root, all-for-year) and `audit_matches` (convenor,
  published-for-pclass).
- **Access control is already unified for the inspector.** `validate_match_inspector(record)`
  (`app/shared/validators.py:280`) allows root/admin for any match, and faculty only when the match
  is `published` and they convene one of its project classes. Convenors already reach the same admin
  inspector routes and can already edit published matches (reassign routes are
  `roles_accepted("faculty","admin","root")`). Only lifecycle actions (create/publish/select/delete)
  are `roles_required("root")`.
- **Statistics helpers exist** on `MatchingAttempt`: `current_score`, `score` (optimiser objective),
  `prefer_programme_status`→(matched,failed), `hint_status`→(satisfied,violated), `delta_max/min`,
  `CATS_max/min`, `is_valid`/`errors`/`warnings`/`student_issues`/`faculty_issues`, `is_modified`.
  Workload/binding: `get_faculty_CATS(fd,pclass_id)`, `is_supervisor_overassigned(...)` /
  `is_marker_overassigned(...)` (each returns `{flag, CATS_total, CATS_limit, error_message}`),
  `number_project_assignments(project)`.
- **Student-drawer data sources exist:** ranked selections via `SelectingStudent.ordered_selections`
  / `SelectionRecord` (`rank`, `hint`, `liveproject`); hint enum + labels in
  `SelectHintTypesMixin`; programme-pref match via `LiveProject.satisfies_preferences(sel)`
  → True/False/None; journal via `journal_activity_summary(user, [student_id])` and
  `batch_journal_counts(...)` (`app/models/journal.py`); open tickets via
  `Ticket.query.filter(Ticket.subjects.any(selecting_student_id=…), Ticket.status.in_(Ticket.OPEN_STATES))`;
  recent emails via `user.received_emails.order_by(EmailLog.send_date.desc()).limit(n)`;
  assessor pool via `LiveProject.assessor_list_query`/`is_assessor`; supervisor roster via
  `EnrollmentRecord.SUPERVISOR_ENROLLED`; avatar monogram via `User.initials`.
- **Diff logic exists:** `_build_match_changes(...)` in `app/admin/matching.py` (compares two
  attempts) — adapt its role-set/project comparison to compare one record's live vs its own baseline.
- **Bootstrap 5 offcanvas is already used** for a student drawer (`app/templates/admin/matching/
  student_offcanvas.html`) and, more richly (AJAX-populated), for the convenor journal drawer
  (`app/templates/convenor/journal/_drawer.html` + `journal.js`) — the best pattern to follow.

## Locked decisions

1. **New model — YES.** Add `MatchingReviewComment` (threaded one level, resolvable, scoped
   global + per-assignment) with a hand-written Alembic migration.
2. **Rollout — parallel v2, switch entry points.** Build the new workspace as new routes/templates
   alongside the current ones; repoint the existing entry links to it; retire the superseded
   templates in the final phase.
3. **Matches list — single privilege-gated surface.** One shared list surface (the top-level Matches
   page) driven by one privilege-aware feed: root/admin → all attempts for a year with full
   actions; convenor → `config.published_matches` for their pclass with the audit action subset.
   Retire `admin/matching/manage.html` and `convenor/matching/audit.html`.
4. **Convenor entry — standalone workspace, pclass-scoped.** Convenors get the same standalone
   workspace; the Matches list is scoped to their published matches for that pclass; root-only
   actions are hidden; a Return link (`url`/`text` convention) goes back to their convenor dashboard.
5. **Navigation — explicit two-level hierarchy.** The old two levels are preserved, re-skinned to the
   new design. **Top level** = a standalone *Matches list* page (`matching_dashboard`): heading
   "Automatic matching", a root-only **Create match** button, and one card per attempt with **Open →**
   and an **Actions ▾** menu (Inspect, **View distributions**, Publish, Duplicate, Rename, Download
   CSV, Compare, Delete). **Detail level** = the per-attempt workspace (`matching_workspace/<id>`)
   with **three** sub-tabs — Student / Faculty / Changes — a persistent match-name heading, a
   "◀◀ Return to matches" control (not a Matches pill), and the Review-comments button. There is no
   "Matches" pill in the detail workspace, and **Distributions is not a sub-tab** — it stays as the
   existing `match_dists_view`, reached from the top-level Actions menu (reskin optional/later).

## Non-goals / accepted limitations

- ~~**No per-record edit provenance.**~~ **Reversed during the Screen 6 reconciliation.** The
  original decision was to record edit identity/time only at the attempt level, so the Changes
  tab's "Edited" column showed the same editor/time on every row (documented in the UI copy). In
  practice that column carried no information and was actively misleading, so `MatchingRecord` now
  carries its own `last_edit_id` / `last_edit_timestamp` pair (added by hand rather than via
  `EditingMetadataMixin`, whose `created_by`/`creation_timestamp` are redundant for a record that
  is always created by the optimiser run owning it), written through `MatchingRecord.mark_edited()`
  and cleared by `clear_edited()` on revert. Migration `f4a8c2e1b7d3`.
- **No new caching.** The "fast first load, no cache" behaviour is achieved by not touching the
  expensive stat properties during the initial dashboard render and fetching them per-row on demand.
  We keep the existing `@cache.memoize` helpers as-is (they are already invalidated on edit); we add
  no new cache and precompute nothing at page load.
- **Emoji glyphs → existing icon set.** Use Font Awesome (already in use) for functional icons, not
  the prototype's Unicode emoji.
- **Colours via tokens.** Follow `.claude/rules/template-colours.md`: use Bootstrap 5.3 tokens
  (`var(--bs-primary)`, `var(--bs-success-bg-subtle)`, …) and `common.css` semantic tokens — never
  the prototype's raw hex. Project-class swatches come from `ProjectClass.make_CSS_style()` /
  `make_label()`, never hardcoded. Avoid `bg-info`/`text-info`/`text-warning`.

---

## Architecture

### Blueprint & routing (admin blueprint)

Two levels (decision 5). The **top-level Matches list** is one standalone page; the **detail
workspace** is anchored to one attempt with three server-rendered panes selected by a `view` query
param and navigated with pill-styled `<a href>` links (`.claude/rules/template-ui-patterns.md`).
Drawers/modals/comments are client-side (Bootstrap offcanvas/modal + vanilla JS), AJAX-populated.

Top-level route:

- `GET /admin/matching_dashboard` — the Matches list. Privilege-scoped: root/admin → all attempts for
  a `year` (with the year selector + Create button); convenor (`pclass_id` present) →
  `config.published_matches` for that pclass (requires `validate_is_convenor`, root-only actions
  hidden). Reads/threads `url`/`text` for its own Return control. Replaces `manage.html` + `audit.html`.

Detail routes (all `roles_accepted("faculty","admin","root")` + `validate_match_inspector`):

- `GET /admin/matching_workspace/<int:id>?view=student` — Student pane (default)
- `GET /admin/matching_workspace/<int:id>?view=faculty` — Faculty pane
- `GET /admin/matching_workspace/<int:id>?view=changes` — Changes pane

The detail shell shows the match name persistently, a "◀◀ Return to matches" link back to
`matching_dashboard` (via `url`/`text`), the three pills (Changes carries the change-count badge),
and the Review-comments button. No "Matches" pill. **Distributions** is not a pane — it remains the
existing `match_dists_view`, linked from the top-level Actions menu.

### New AJAX feeds (`app/admin/matching.py` routes → formatters in `app/ajax/admin/matching/`)

- `POST /admin/match_student_view_v2_ajax/<int:id>` → new formatter `match_view_student_v2.py`
  producing the redesigned student row (dominant colour-coded rank, muted score, MODIFIED pill,
  two-line project cell with programme-pref status, journal/ticket/comment chips, drawer/role-editor
  triggers). Server-side via `ServerSideInMemoryHandler` (as today), filters (pclass/type/hint) via
  page-reload query args (session-persisted, as today), restyled as pill links.
- `POST /admin/match_faculty_view_v2_ajax/<int:id>` → new formatter `match_view_faculty_v2.py`
  (offered counts, supervising/marking grouped by pclass with programme tick/cross, workload CATS,
  binding pill).
- `GET /admin/match_student_drawer_ajax/<int:rec_id>` → student inspector drawer body.
- `GET /admin/match_faculty_drawer_ajax/<int:attempt_id>/<int:fac_id>` → faculty inspector drawer body.
- `GET /admin/match_role_editor_ajax/<int:rec_id>` → unified role-editor modal body + option lists.
- `GET /admin/faculty_reassign_ajax/<int:attempt_id>/<int:fac_id>` → reassignment workspace body
  (capacity gauges, per-project gauges, currently-assigned, assignable pool).
- `GET /admin/match_statistics_ajax/<int:id>` → on-demand dashboard statistics for one attempt
  (programme matched/failed, hints satisfied, δ range, CATS range) as rendered chips. Computed fresh
  on request only.
- `GET /admin/match_comments_ajax/<int:attempt_id>` → comments (global + assignment tabs) + counts.
- `GET /admin/matches_v2_ajax` → **consolidated** privilege-scoped Matches-list feed for the
  top-level page. Resolves the visible set: if `pclass_id` present → require
  `validate_is_convenor(pclass)` and use `config.published_matches`; else → require root/admin and use
  all attempts for `year`. Delegates rendering to the existing `matches_data(..., is_root=…,
  config=…)` (extended with the new card layout / on-demand-stats hooks; each card carries Open → and
  the Actions menu incl. View distributions).

### New mutation endpoints (WTForms-backed, CSRF via `form.hidden_tag()`, `log_db_commit`)

- `POST /admin/edit_match_roles/<int:rec_id>` — unified role editor: set assigned project (from the
  selector's ranked selections), supervisor set, marker set in one transaction. Reuses validation
  from the existing reassign routes (project in selections; markers in assessor pool; supervisors
  enrolled). Overassignment allowed (surfaces as a validation warning, not blocked). Sets
  `attempt.last_edit_*`.
- `POST /admin/faculty_reassign_assign/<int:attempt_id>/<int:fac_id>/<int:selector_id>/<int:project_id>`
  — assign a pooled student to one of the faculty's projects (reuses `reassign_match_project`
  logic on that student's record). Immediate; workspace re-renders.
- `POST /admin/post_match_comment/<int:attempt_id>` — new comment (scope global|assignment,
  optional `matching_record_id`), unresolved.
- `POST /admin/reply_match_comment/<int:comment_id>` — one-level reply (sets `parent_id`).
- `POST /admin/resolve_match_comment/<int:comment_id>` — toggle resolved (+ `resolved_by`/`resolved_timestamp`).

Existing GET reassign routes remain and are reused by the drawers where a single-field change is
enough (quick reassignment buttons).

### Data/service layer — new module `app/shared/matching_workspace.py`

Pure, read-only helpers (unit-testable, no request state) that assemble view dicts from existing
model methods:

- `student_row(attempt, record)` — name, pclass label+swatch (`make_CSS_style`), cohort, owner,
  project title+owner, `modified` (project_id≠original_project_id OR live roles≠original_roles),
  programme-pref status (`project.satisfies_preferences(selection)`), markers, `rank`
  (`record.total_rank`), rank severity band (1–2 success / 3 orange / 4+ danger), `score`
  (`record.current_score`), journal count (`batch_journal_counts`), open-ticket count.
- `faculty_row(attempt, fac)` — offered counts per pclass, supervising grouped by pclass (student +
  project + programme tick/cross), marking grouped by pclass, workload (sup/mark/total CATS via
  `get_faculty_CATS`), binding pill (overassigned helpers + capacity-full).
- `faculty_drawer(attempt, fac)` — workload bars + binding notes; constraint callouts (CATS amber
  via overassigned helpers; capacity red via `number_project_assignments` vs `capacity`/
  `enforce_capacity`); projects offered with capacity badges + allocated-student chips; assignable
  pool (below).
- `faculty_assignable_pool(attempt, fac)` — **new algorithm** (read-only over `SelectionRecord` +
  `MatchingRecord`), three deduplicated, tone-coded lists:
  - *Ranked an F project #1 but allocated elsewhere* — selectors with a `rank==1` `SelectionRecord`
    for one of F's LiveProjects whose current allocation is not an F project.
  - *Would prefer an F project to their current allocation* — selectors whose best rank among
    F-project selections is lower (better) than their current allocation's `total_rank`, and not
    currently on an F project.
  - *Next-highest interested* — selectors ranking any F project, allocated elsewhere, ordered by
    rank ascending; excludes those already listed above.
- `binding_constraints(attempt, fac)` — normalises the overassigned-helper output + capacity-full
  enforced projects into callout dicts (severity/icon/text).
- `student_drawer(attempt, record)` — assigned project + owner + modified flag; quick-reassignment
  options (ranked selections, current highlighted, original tagged "automatch"); ranked-selection
  table (rank/project/owner/hint badge); journal preview (`journal_activity_summary` recent entries
  + visible count); open tickets; recent emails.
- `changes_data(attempt)` — for each record, diff live vs baseline: project (project_id vs
  original_project_id, names+ranks), supervisors (live supervisor role user-set vs original), markers
  (live vs original). Summary: field-change count, distinct students, objective `score`→
  `current_score`. Provenance = attempt-level `last_edited_by`/`last_edit_timestamp` (see limitations).
- `changes_count(attempt)` — number of records where live ≠ baseline (drives the Changes badge).
- `dashboard_statistics(attempt)` — the on-demand stat bundle (programme matched/failed, hints
  satisfied, δ range, CATS range), computed fresh.

### New model — `MatchingReviewComment` (`app/models/matching.py`)

```
matching_review_comments
  id                     PK
  matching_attempt_id    FK matching_attempts  (NOT NULL, indexed)
  matching_record_id     FK matching_records   (NULL = global scope; set = per-assignment, indexed)
  parent_id              FK self               (NULL = top-level; set = one-level reply, indexed)
  owner_id               FK users
  body                   AES-encrypted text (EncryptedType, following TicketComment)
  resolved               Boolean default False
  resolved_by_id         FK users  (nullable)
  resolved_timestamp     DateTime  (nullable)
  creation_timestamp     DateTime index
  last_edit_timestamp    DateTime  (nullable)
```

Relationships: `matching_attempt`, `matching_record`, `owner`, `resolved_by`, `parent` + `replies`
backref (cascade delete-orphan). Property `scope_label` → student name when record-scoped else
"whole match". Cascade-delete comments when the attempt/record is deleted.

**Migration:** hand-written Alembic file, `down_revision="b4e7a1d9c3f2"` (current chain tip; re-verify
at implementation time with the CLAUDE.md `comm` command). New 12-hex revision id (verify unused).
Create table with `collation='utf8_bin'` on the text column and FKs/indexes per
`.claude/rules/sqlalchemy-columns.md`. Provide `downgrade()` dropping the table.

### Templates — new dir `app/templates/admin/matching_workspace/`

- `matching_dashboard.html` — **top-level** Matches list page (extends `base_app.html`): heading
  "Automatic matching", root-only Create button + year selector, info banner ("fast first load"),
  match cards (name+tags, status/modified/published flags, original/current score + counts, **Open →**,
  **Actions ▾** dropdown reusing existing action routes incl. View distributions, on-demand stats area
  with Compute button + Compute all, errors/warnings expandable). "current" match highlighted.
  Return control (via `url`/`text`) back to the admin/convenor dashboard.
- `workspace.html` — **detail** shell (extends `base_app.html`): sub-toolbar with "◀◀ Return to
  matches" (via `url`/`text`), persistent match-name heading, three pills (Student/Faculty/Changes,
  Changes badge), Review-comments button + unresolved badge; renders the active pane. Hosts the
  offcanvas/modal containers.
- `_student_pane.html`, `_faculty_pane.html` — filter well (pill-link filters) + DataTable (v2
  server-side) + "Showing N of M".
- `_changes_pane.html` — three summary cards + changes table (server-rendered from `changes_data`;
  small enough to skip DataTables) + empty state.
- `_student_drawer.html`, `_faculty_drawer.html` — offcanvas (`offcanvas-end`), AJAX-populated.
- `_role_editor_modal.html` — 640px modal; `select2-small` for project/supervisor/marker selects
  (per CLAUDE.md).
- `_faculty_reassign_modal.html` — 920px modal (capacity gauges + candidate pool + over-limit bar).
- `_comments_panel.html` — 440px offcanvas (Global/By-assignment tabs, threaded list, composer).
- `_macros.html` — shared pills, swatches (reuse `swatch.html`), capacity bars, pref badges, chips.
- `workspace.js` (registered via `{% assets %}`) — vanilla JS (no jQuery, per repo pattern): AJAX
  drawer/modal population, on-demand stats fetch, comments post/reply/resolve, role-editor select2
  init, faculty-reassign assign. CTA banners (if used) go through `render_convenor_actions`.

### Access control (net)

- Per-attempt panes/drawers/edits/comments: `roles_accepted("faculty","admin","root")` +
  `validate_match_inspector` (already encodes convenor-of-published-pclass).
- Matches list feed: privilege-scoped as in decision 3; hide root-only actions for non-root; reuse
  `matches_data(is_root=…, config=…)`.
- Lifecycle actions (create/publish/select/delete): keep existing `roles_required("root")`.

---

## Phased delivery (one commit per phase; format `matching-workspace: <imperative summary>`)

- **Phase 0 — Planning artifacts.** Write `.prompts/matching-workspace/PLAN.md` (this doc) and
  `TODO.md` (checklist). Commit. ✅ **DONE**
- **Phase 1 — Service layer.** Add `app/shared/matching_workspace.py` with all read-only helpers
  (student_row, faculty_row, faculty_drawer, faculty_assignable_pool, binding_constraints,
  student_drawer, changes_data, changes_count, dashboard_statistics). No UI. Commit.
- **Phase 2 — Detail shell + Student tab.** `workspace.html` (detail shell, `matching_workspace/<id>`
  route + view dispatch), `_macros.html`, `_student_pane.html`, v2 student row formatter, student
  drawer (offcanvas + AJAX), unified role-editor modal + `edit_match_roles` endpoint. Repoint
  `match_student_view` entry link to the workspace. Commit.
- **Phase 3 — Faculty tab + reassignment.** `_faculty_pane.html`, v2 faculty formatter, faculty
  drawer, faculty reassignment modal, assignable-pool + assign endpoints. Commit.
- **Phase 4 — Changes tab.** `_changes_pane.html` from baseline diff; Changes badge count; revert
  wired to existing `revert_match`/per-record revert. Commit.
- **Phase 5 — Top-level Matches list (consolidated dashboard).** `matching_dashboard.html` +
  `matching_dashboard` route, `matches_v2_ajax` privilege-scoped feed, on-demand
  `match_statistics_ajax`, info banner, Create (root), Open → / Actions menu (incl. View
  distributions), errors/warnings expandable. Repoint `manage_matching` and convenor `audit_matches`
  entry points to `matching_dashboard`; mark old list templates for retirement. Commit.
- **Phase 6 — Review comments.** `MatchingReviewComment` model + hand-written migration; comments
  panel + post/reply/resolve endpoints; unresolved badge. Commit.
- **Phase 7 — Consolidation & polish.** Colour-token/icon compliance pass; retire superseded
  templates/routes (`manage.html`, `audit.html`, old `student.html`/`faculty.html` if fully
  replaced) or leave thin redirects; accessibility; final QA. Commit.

## Verification

- `ruff check .` and `ruff format --line-length 150` clean.
- In Docker (or `python serve.py` with infra): open the workspace for a *finished, usable* match;
  exercise each tab, both drawers, role editor, faculty reassignment, comments (post/reply/resolve),
  on-demand stats (single + Compute all), Changes tab after an edit (MODIFIED pill + badge + row),
  Revert.
- Migration: `flask db upgrade` then `flask db downgrade` inside a container (migrations are
  hand-written, per CLAUDE.md — never `flask db migrate`). Confirm table + FKs + utf8_bin.
- Access matrix: root (all matches + full actions), convenor of a published match's pclass (only
  their published matches, no root-only actions, can inspect/edit/comment), faculty non-convenor and
  unpublished match (blocked by `validate_match_inspector`).
- Performance: initial dashboard paints without touching expensive stat properties; stats appear
  only after Compute.
