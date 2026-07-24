# Matching Workspace — Design Reconciliation Checklist

> Reconcile the implemented product against the hi-fi reference design
> (`.prompts/matching-workspace/reference/`: `Matching Workspace.dc.html`, `README.md`,
> `screenshots/`). See `PLAN.md` for the implementation plan and `TODO.md` for build status.
>
> **Method — judge against the *adapted* spec, not the literal prototype.** The reference is
> hi-fi but deliberately diverges from production intent: emoji → Font Awesome, raw hex →
> Bootstrap 5.3 / `common.css` tokens, project-class swatches via `ProjectClass.make_CSS_style()`,
> no artificial max-width, real data model. Flag **intent** gaps (missing states, wrong layout
> structure, absent badges/behaviours) — do **not** treat raw hex or emoji as "must match."
> Use the screenshots for layout/hierarchy intent; use PLAN.md's decisions where the prototype
> and production intentionally differ.
>
> Work through these **in order**. Each item is self-contained enough to do in a fresh context.

---

## Global pass (do first — cross-cutting, de-risks everything downstream)

- [x] **Design-token remapping** — swept all workspace templates, v2 formatters
      (`match_view_student_v2`/`match_view_faculty_v2`/`matches_v2`), and JS
      (`matching_dashboard.js`/`matching_workspace.js`). **No raw hex** except policy-allowed white;
      no `rgba(...)`. Swatches consistently via `swatch.html` (`small_swatch`/`medium_swatch`) +
      `make_CSS_style()`. Capacity-bar thresholds (85% warning / 100% danger) match the reference.
- [x] **Shared macros** (`_macros.html`) — vocabulary is token-clean and consistent
      (`modified_pill`, `programme_pref_line`, `journal_chip`, `ticket_chip`, `capacity_bar`,
      `constraint_callout`). **Fixed:** the student v2 formatter (`match_view_student_v2.py`)
      duplicated the `programme_pref_line` body inline instead of calling the macro — a silent
      divergence risk. Rewired it to call the shared macro via `get_template_attribute`.
      Faculty view's tick/cross pref **badge** is an intentional compact variant (not the text
      line) — left as-is.
- [x] **Icon compliance** — Font Awesome throughout; **no residual emoji glyphs** in templates,
      v2 formatters, or JS.

> **Resolved in Screen 1:** `modified_pill()` now renders uppercase "MODIFIED" (matching the
> reference table); the student v2 formatter's inline duplicate was removed and now calls the macro.

## Screen-by-screen (in build order)

| # | Reference surface | Screenshot | Implementation files |
|---|---|---|---|
| 1 | Student view (table + filters) | `01-student-view` | `_student_pane.html` + `match_view_student_v2.py` |
| 2 | Student drawer | `06-student-drawer` | `_student_drawer.html` + service `student_drawer()` |
| — | Unified role editor | (in 01/06) | `_role_editor_modal.html` |
| 3 | Faculty view | `02-faculty-view` | `_faculty_pane.html` + `match_view_faculty_v2.py` |
| 4 | Faculty drawer | — | `_faculty_drawer.html` |
| 5 | Faculty reassignment workspace | `05-faculty-reassignment` | `_faculty_reassign_modal.html` |
| 6 | Changes tab | `03-changes` | `_changes_pane.html` |
| 7 | Matches dashboard | `04-matches-dashboard` | `matching_dashboard.html` + `matches_v2.py` + `_dashboard_stats.html` |
| 8 | Comments panel | `07-comments` | `_comments_panel.html` |

Detail shell (`workspace.html`) hosts the pills, Changes badge, Review-comments button, and the
offcanvas/modal containers — check it alongside whichever surface it frames (Screen 1 first).

### Per-screen checklist template

For each surface, compare against its screenshot + the matching README section + PLAN decisions:

- [ ] **Layout structure** — grid/columns, card chrome (header bar, border, radius), section order.
- [ ] **Content completeness** — every field/badge/chip/caption from the spec is present and bound
      to the real model (not omitted, not hard-coded).
- [ ] **States** — empty states, loading states, active/inactive filters, modified/published flags,
      severity bands (rank colour bands, capacity bar thresholds 85%/100%, etc.).
- [ ] **Interactions** — drawer/modal triggers, quick-reassignment, on-demand stats, comments
      post/reply/resolve, filter navigation — match the intended behaviour.
- [ ] **Tokens & icons** — surface-local check that the global-pass rules hold here too.

---

## Progress log

- **Global pass** — ✅ done. Tokens/emoji clean across templates, formatters, JS. One fix:
  student v2 formatter now uses the shared `programme_pref_line` macro instead of an inline copy.
- **Screen 1 Student view** — ✅ done. Rank cell now dominant (`#N` + vivid
  `--bs-success`/`--bs-orange`/`--bs-danger` tokens); project-class line enriched to programme
  short_name + year label + cohort; `MODIFIED` pill uppercased + de-duplicated via the macro;
  `programme_pref_line` lowercased; student table de-bordered (horizontal rules only) and the
  filter-well `<hr>` removed. Kept: DataTables chrome, no "Matches" pill (PLAN decision 5),
  supervisors in the Project column (user decision).
- **Screen 2 Student drawer** — ✅ done. Ranked-selection hint badges are now colour-coded by
  severity (encourage/require → success, discourage → warning, forbid → danger, neutral → dim)
  via the new `hint_badge` macro + service-supplied `hint_icon`/`hint_severity`, and are editable
  through a "Change hint" dropdown (`SelectionRecord._menu_order`) POSTing to the new
  `admin.match_set_hint` endpoint (`validate_match_inspector`-guarded, CSRF via a drawer-scoped
  `ConfirmActionForm`), which repaints the drawer. Tickets card enriched from a bare count to a
  per-ticket list (title link → `tickets.detail`, opened date, status badge). Assigned-project
  card header softened to a light header with the MODIFIED pill moved into it (removes the
  blue-on-blue stack under the offcanvas header). Ranked-selection project titles now link to
  `faculty.live_project`. Kept (better than reference): the inline Comments card, and the
  offcanvas blue chrome for cross-drawer consistency.
- **Role editor** — ✅ done. Kept the three-section split (Responsible supervisors / Supervisors
  / Markers) — more correct than the reference's single group (models responsible-vs-additional +
  the ≥1-responsible constraint). Added "(from assessor pool)" caption to the Markers label to
  match the reference. select2 init already uses `select2-small` for
  `selectionCssClass`/`dropdownCssClass` (verified — no change needed).
- **Screen 3 Faculty view** — ✅ done. Nine divergences reviewed; five reference-wins fixes applied,
  three implementation-wins kept, one accepted as unimplementable.
  **Fixed:** (1) the workload cell's generic "N binding constraints" pill replaced by *named* pills —
  "Supervising limit binding" / "Marking limit binding" / "Capacity binding" — via the new
  `binding_pills()` service helper, which collapses `binding_constraints()` to at most one pill per
  category at that category's worst severity (severity colouring retained, which the reference lacks);
  (2) `table-bordered` dropped from the faculty table, matching the de-bordered Screen 1 student
  table; (3) project titles in the Supervising/Marking cells clamped to one line (`.mwfp-proj`,
  full title in `title=`) — untruncated titles were inflating rows to ~3 lines and halving density;
  (4) `offered_by_pclass` now seeded from the faculty member's `SUPERVISOR_ENROLLED` enrolments in
  the attempt's classes, so "enrolled but offering nothing" shows as an explicit `offered 0` line
  instead of vanishing; (7) faculty name link bumped to 15.5px as the row anchor; (9) card header
  reworded to "Faculty view of project matching".
  **Kept (better than reference):** project-class group labels use `abbreviation` not the full
  uppercase class name (the swatch already disambiguates, and the full name eats a 30%-width
  column); "None" placeholders for empty Supervising/Marking cells (reference leaves them blank);
  DataTables search/pager chrome (per the Screen 1 decision).
  **Accepted divergence:** the reference's per-faculty comments (💬) button is *not* implementable —
  `MatchingReviewComment` is scoped global-or-`matching_record` (PLAN decision 1) with no faculty
  scope, and adding one would fork the comments model for a single button.
  **Also removed:** the single-row filter well's "Hide filters" collapse toggle — the rule in
  `.claude/rules/template-ui-patterns.md` only asks for a collapsible panel above two filter rows,
  and the reference has none here.
- **Screen 4 Faculty drawer** — ✅ done. Twelve divergences reviewed. Note this is the one surface
  with **no reference screenshot** — the spec is `README.md` ("Faculty drawer, 560px") plus the
  prototype markup (`Matching Workspace.dc.html:174-242`, view-model `:863-884`).
  **Fixed (reference wins):** (1) the identity card was content-free (the name appeared three times
  in the top 160px) — now carries "N projects offered · X CATS total"; (2) the workload card's
  `bg-primary text-white` header sat directly under the blue offcanvas header — softened to a light
  header (same fix as Screen 2), and the `border-primary` accent moved to the Projects card, which
  is the primary content; (3) bar labels de-duplicated ("Supervising", not "Supervising CATS … CATS")
  and each bar now states its own consequence via a new optional `binding_note` arg on `capacity_bar`
  ("no further supervisees can be added" / "no further marking can be allocated"); (4) **the biggest
  win** — constraint callouts stated the fact but not the blocked demand; a new
  `_enrich_constraints_for_drawer()` adds a `detail` line ("N further students who would prefer one
  of these projects cannot be added without exceeding this limit", "M more selectors chose this
  project but could not be allocated"), rendered as a second line by `constraint_callout`. The
  enrichment builds new dicts so the Faculty-tab `binding_pills` are untouched; (5) the missing
  "N selectors chose this · allocated:" demand caption added, reusing `LiveProject.number_selections`;
  (9) both drawers widened 400px → 560px (`max-width: 95vw`), matching the reference and the
  existing `#matchCommentsPanel` pattern; (10) allocated-student chips moved off `--bs-info-*`
  (discouraged by `.claude/rules/jinja2-templates.md`) onto primary-subtle tokens.
  **Kept (better than reference):** the tri-state capacity severity — `OVER n / c cap` (danger) vs
  `FULL n / c cap` (warning) vs plain — the reference collapses over-subscription and healthy
  at-capacity into the same red; the structured three-line candidate rows with severity dots (the
  reference's one-liner wraps at drawer width anyway, and only shows the ranked project for list 3);
  gender-neutral constraint copy (the reference says "without exceeding **her** supervising limit").
  Reference *labels* for the capacity badge were adopted — bare `0/3` was ambiguous.
  **Beat both:** duplicate-titled projects (the same generic project offered across several project
  classes) were distinguishable only by swatch colour. The reference has the same defect — it
  computes the class short name in its view-model and never renders it. The implementation now shows
  `project_class.abbreviation` beside the swatch, per the Screen 3 decision.
  **Also:** candidate lists now cap at 3 (was 5) and the previously-dead "+ N more" text is a real
  control opening the reassignment workspace; candidate names and allocated-student chips cross-link
  to the student inspector. That required adding the faculty drawer's **first post-injection binding
  step** (`bindOpenStudentLinks`) — Bootstrap does not support two open offcanvases, so the swap is
  hide-then-show on a one-shot `hidden.bs.offcanvas`, mirroring the student drawer's comments-panel
  handoff. `faculty_assignable_pool` entries and the per-project `assigned` list now carry
  `record_id`; `assigned_students` was left in place because `_faculty_reassign_modal.html` consumes
  the same dict. Because a chained open replaces the drawer that launched it, both drawer headers
  gained a ghost "Back" control driven by a shared navigation stack (`DRAWER_KINDS` /
  `navigateToDrawer` in `matching_workspace.js`): it is labelled with the drawer it returns to,
  renders only while the stack is non-empty, and the stack is cleared both when a drawer is opened
  from the page (rather than from another drawer) and when one is dismissed outright.
- **Screen 5 Faculty reassignment** — ✅ done. Eight divergences fixed; four items kept as-is.
  **Fixed (reference wins):** (A) the per-project capacity list had **no project-class swatch**, so
  the same generic project offered across several classes rendered as indistinguishable duplicate
  rows ("Sports Analytics (generic)" twice, "Choose your own project…" twice) — now
  `small_swatch(make_CSS_style())` + `project_class.abbreviation`, as the Screen 4 drawer already
  does; (B) the title/count row wrapped ("1 /" then "5") — title clamped via `.mwfr-proj`
  (2 lines, 1 in the assigned list, full title in `title=`), count `text-nowrap`; (C) the
  enforcement note was a flat grey "enforced" for every project — now four-state
  (`over capacity — enforced` danger / `at capacity — enforced` warning / `capacity enforced`
  secondary / `no capacity enforcement` dim), which keeps the reference's colour ramp *and* stays
  consistent with the drawer's OVER/FULL tri-state badge (the reference collapses over- and
  at-capacity into one red); (G) no visual separation between the two columns — `border-end` on
  the left column.
  **Fixed (implementation defect):** (D) `capacity_bar` was called without `binding_note`, so the
  fallback `label|lower` mangled the acronym into "At marking cats limit"; the modal now passes the
  same two strings as the drawer, and uses the drawer's "Supervising"/"Marking" labels (the unit
  already rides on the value).
  **Fixed (both designs were weak):** (E) all three tone groups rendered the identical
  `Ranked #N · project` line, so the green/blue/grey dots were unexplained — now grouped under the
  drawer's three `pool_list` captions with a dot key, and the "Colour shows why." sentence restored.
  The implementation's line is *kept* over the reference's: it names the project the student would
  be moved onto, which the reference never states even though Assign commits to a specific project.
  Current-allocation line demoted to `--bs-tertiary-color` to restore the reference's two-level
  hierarchy. (F) the Assign button had no over-limit affordance (the reference computes
  `warn`/`warnReason` but its `assignStyle` is a constant — the warn style is dead code, only a
  `title` tooltip survives): `faculty_assignable_pool` now annotates every entry with
  `warn`/`warn_reason` (supervising CATS at/over limit, and/or the target project at/over its
  enforced capacity, computed once rather than per entry), and the button renders
  `btn-outline-warning` + triangle + tooltip. The click is still allowed — overassignment is
  deliberately permitted here, mirroring the role editor.
  (H) Currently-assigned students were inert text; they now cross-link to the student inspector via
  `mw-open-student` (using the `record_id` already on `p.assigned`). Because a modal and an
  offcanvas cannot both be shown, the new `bindReassignStudentLinks` dismisses the workspace first,
  then hands off to `navigateToDrawer`; if the faculty drawer is still open behind the modal it is
  pushed as the "Back" target, otherwise nothing is pushed (guarded on `.show`, so a stale
  `data-fac-id` on a hidden drawer cannot fake an origin).
  **Kept (implementation wins):** the reference's cyan "pending" badge — a prototype artifact of
  client-side state; assignment here persists immediately and repaints, so a pending state would be
  a lie; the over-limit banner's extra "Overassignment is allowed here…" sentence (the reference
  only says this in its README); the 5/7 column ratio (the reference is 50/50, but the pool column
  carries far more content); the banner firing on the supervising limit only, matching the reference
  — the marking-limit case is still surfaced by the red gauge note.
  **Noted, not actioned:** the workspace is one-way — students can be assigned in but never removed.
  Neither design has a remove control; this is a scope decision rather than a divergence.
- **Screen 6 Changes tab** — ✅ done. Twelve divergences reviewed.
  **Fixed (model-layer — the headline item):** the "Edited" column showed the *attempt-level*
  `last_edited_by`/`last_edit_timestamp` on every row, so all 13 rows read the same name and time
  regardless of who touched which record — the column was misleading and the template carried an
  apologetic caption admitting it. PLAN.md's "no per-record edit provenance" non-goal is now
  **reversed**: `MatchingRecord` carries its own `last_edit_id` / `last_edited_by` /
  `last_edit_timestamp` (added by hand, *not* via `EditingMetadataMixin` — a record is always
  created by the optimiser run that owns it, so `created_by`/`creation_timestamp` would duplicate
  the attempt). Two new methods keep the record/attempt pair written together:
  `mark_edited(user)` stamps both, `clear_edited()` clears only the record's when it returns to
  baseline. Migration `f4a8c2e1b7d3` (chain tip `e7f8a9b0c1d2`); legacy rows backfill NULL and
  render as an em dash rather than falling back to the misleading attempt value. Every edit site
  was swept — `edit_match_roles`, `_apply_project_reassignment` (serving both
  `reassign_match_project` and `faculty_reassign_assign`), `reassign_match_marker`, the
  replace-from-source path, and the Celery `revert_record` (now clears). This also fixed a latent
  gap: `reassign_supervisor_roles` mutated roles but stamped *nothing*, at either level.
  **Fixed (reference wins):** (2) changes were flat "Supervisor: A → B" text — now the reference's
  grey `field_pill` (Project / Supervisors / Markers) + `diff_pair` (baseline struck through in
  `--bs-danger-text-emphasis`, current in `--bs-success-text-emphasis`), both new shared macros;
  (3) the objective-score card showed the current score with "baseline N" beneath, losing the
  reference's optimiser → current narrative — now `baseline → current` inline, and we beat both
  designs with a signed delta chip coloured by direction (success when the manual edits improved
  the objective, danger when they degraded it), which the reference lacks; (4) "Revert all" moved
  from the toolbar into the blue card header via `.btn-ghost-header`; (5) the empty state gained
  the reference's second hint line.
  **Neither:** rows were ordered by `selector_id`; now ordered most-recently-edited first with
  un-attributed rows last — an ordering only made possible by the new per-record timestamps.
  **Kept (implementation wins):** the project-class swatch + class line under the student name
  (the reference is a bare name); the student name as a drawer trigger (the reference is inert
  text); the danger-subtle per-row Revert (`.claude/rules/template-ui-patterns.md` requires danger
  tokens for destructive actions — the reference uses neutral grey); the de-bordered table, per
  the Screen 1/3 decision; **one row per record** rather than the reference's one row per field
  change — `revert_match_record` reverts project *and* roles together, so per-field rows would
  repeat an identical Revert button N times. The reference's *styling* was adopted inside that
  per-record row.
  **Not adopted:** the reference's relative timestamps ("Today 09:14", "Yesterday 16:40") — absolute
  `16 Mar 2026 13:22` is unambiguous and consistent with the rest of the app, and avoids a new
  Jinja filter.
- **Screen 7 Matches dashboard** — ✅ done. Eight divergences reviewed.
  **Fixed (defect — the headline item):** the errors/warnings chips were **inert**. `base.html`
  initialises popovers once at `$(document).ready()`, but `matching_dashboard.js` injects the card
  list and each statistics fragment by `innerHTML` long afterwards, so the `data-bs-toggle="popover"`
  badges emitted by `error_block_popover` were never bound — on every card, both chips. Replaced
  with the reference's inline expandable panel via a new `validation_detail()` macro: the chips are
  `data-bs-toggle="collapse"` buttons (declarative, so they survive AJAX injection with no JS init)
  opening a two-block panel — danger-subtle "Validation errors (N)" and warning-subtle "Validation
  warnings (N)", each a full `<ul>`. This also drops `error_block_popover`'s 10-item cap, which was
  silently truncating an 18-error match. Messages arrive as either plain strings or mappings with a
  `msg` key, so the macro handles both; `format_inline_item` was *not* reused because it emits
  `text-warning`, forbidden by `.claude/rules/jinja2-templates.md`. `error_block.html` is untouched —
  it is used across the app.
  **Fixed (reference wins):** (2) the list had no card chrome at all — heading and both buttons sat
  loose in `pillblock`, the only workspace surface not wrapped in the `card border-primary` +
  `card-header bg-primary text-white` shell used by Screens 1/3/6; now wrapped, with "Compute all
  statistics" as a `.btn-ghost-header` in the card header (the Screen 6 "Revert all" pattern) and
  the Return link, root-only Create button and year selector left in `pillblock`; (3) the four
  stacked count lines — the tallest element on a card, for the least information — collapsed to one
  wrapping `·`-separated line, keeping full words rather than the reference's `sel/sup/mark/proj`
  abbreviations; (4) 1px vertical rules between the card columns (`.mdash-col`, suppressed below
  `lg` where the columns stack); (5) the four `δ max`/`δ min`/`CATS max`/`CATS min` chips collapsed
  to the reference's two range chips `δ 0–4` / `CATS 0–152`, with a one-sided fallback when only one
  end is known.
  **Beat both:** the objective score was two independent lines ("Original score" / "Current score"),
  losing the optimiser → current narrative that the Changes tab already tells. Both surfaces now
  share a new `score_progression()` macro — `baseline → current` plus a signed delta chip coloured
  by direction — extracted from `_changes_pane.html`. The reference has neither the arrow form here
  nor a delta anywhere.
  **Fixed (latent bug):** `dashboard_statistics()` returned `score` as a `Decimal` (a stored column)
  and `current_score` as a `float` sum, so taking a delta across them would have raised — exactly
  the mismatch fixed for the Changes tab in `8daaaabb`. Both are now coerced to `float` and a
  `score_delta` key added, mirroring `changes_data()`.
  **Kept (implementation wins):** the "Open →" primary CTA (the reference relies on the name link
  alone); the full-width statistics strip below a `border-top` rather than the reference's cramped
  4th column; the `Violated N hints` chip (absent from the reference); the year selector, root-only
  Create button and privilege scoping (no prototype equivalent); the spinner-in-button in place of
  the reference's shimmering placeholder chips.
  **Accepted divergence:** the reference renders the error/warning chips unconditionally, but
  `attempt.errors`/`warnings` force full validation via `is_valid` — that would defeat the
  fast-first-load behaviour, so they stay inside the on-demand bundle. Same reasoning keeps both
  scores there: `score` is a cheap column but `_MatchingAttempt_current_score` walks every record.
  **Not adopted:** the reference's "⚡ Fast first load, no cache…" info banner (user decision) — its
  copy is implementation trivia, and the dashed Compute button is self-explanatory.
  **Noted, not actioned:** `error_block_popover` uses a positive `tabindex="1"`, which hijacks the
  global tab order — an app-wide a11y wart, out of scope now that this surface no longer uses it.
- **Screen 8 Comments panel** — ✅ done. The largest gaps here were in neither design: the panel had
  no filter, no per-student index, no scoping, and no unread notion, so with more than a handful of
  comments it became an undifferentiated wall.
  **Fixed (reference wins):** (1) the panel was one long scrolling `offcanvas-body` with the composer
  *after* the last comment — already ~1,400px down with four comments. It is now the reference's
  three-region flex column (fixed head / scrolling list / pinned footer), with `#matchCommentsPanelBody`
  carrying `d-flex flex-column p-0` and the fragment supplying its own regions; (2) tab counts —
  Global had none and "By student" counted *students*; both now count threads, reference-style, on
  `nav-underline` tabs (Bootstrap 5.3.8, so the class is available); (3) resolved threads only
  swapped a border colour — they now take the reference's full green tint
  (`--bs-success-bg-subtle` + `--bs-success-border-subtle`), and the heavy `card`/`card-header`
  chrome is gone in favour of the reference's light bordered block; (4) the reference's `On: {…}`
  scope pill added as an optional `show_scope` macro arg.
  **Fixed (implementation defects the reference also has or worsens):** (5) `resolved_by_id` /
  `resolved_timestamp` were written by `resolve_match_comment` but **never rendered** — a resolved
  thread never said who closed it or when; there is now a `Resolved by … · <timestamp>` line;
  (6) Resolve (a thread-level action) sat beside Reply (a comment-level action), and Reopen sat in
  the body action row far from the "Resolved" badge in the header — Resolve/Reopen moved into the
  thread header beside the resolved-by line, Reply stayed in the body; (7) replying to a resolved
  thread silently left it resolved, so a closed conversation could accumulate unread discussion. The
  reply box now offers `Post reply` + `Reply and resolve` on an open thread and *only*
  `Reopen and reply` on a closed one — a new `transition` field on `MatchCommentReplyForm`, applied
  by `reply_match_comment` in the same transaction as the reply insert (each transition a no-op if
  already in that state, not an error).
  **Beat both (new structure):** the By-student tab is now an **inbox** — one row per commented-on
  student (name, latest snippet, unresolved/resolved/new chips, latest-activity timestamp, ordered by
  recency), drilling into that student's threads. Above 10 rows a client-side name filter appears;
  beyond 25 the tail sits behind "Show more" (a name search overrides the cap, so a match in the
  hidden tail is never invisible). No paginator — its controls are cramped at 440px.
  A three-way filter (`All` / `Unresolved` / `Resolved`, **default Unresolved**) applies to both
  tabs, with counts computed *before* filtering so the pills and tab counts do not move as the filter
  changes. Opening from a student's comment chip now **hard-scopes** the panel (`?record_id=`) with a
  `Scoped to <name>` banner and a "Show all students" control — previously only the composer's
  dropdown was preselected while the list still showed everyone. Inbox drill-in reuses that same
  scoping path, so there is one mechanism, not two. Scope/filter/tab live on the offcanvas element
  and are echoed back by the fragment, so a re-fetch after post/reply/resolve returns to exactly the
  same view — previously every mutation bounced the user to the Global tab. Opening the panel afresh
  deliberately resets to unresolved/unscoped, so a stale scope cannot silently hide most of it.
  The two composer forms collapsed into one pinned footer, collapsed to a `+ New comment` button that
  expands in place; its scope follows the active tab. This also **fixed a CSRF policy violation** —
  the assignment composer injected `comment_form.csrf_token._value()` as a raw hidden input, which
  CLAUDE.md forbids; it is now `{{ comment_form.hidden_tag() }}`.
  **Unread (neither design has any):** new `MatchingCommentReadMarker` (one row per user/attempt,
  migration `c3d9e2f6a1b4`, chain tip `f4a8c2e1b7d3`) plus
  `POST /admin/mark_match_comments_read/<id>`, fired by JS *after* the body renders so the marker
  used to compute the flags is the previous one and the `New` pills stay visible on the view that
  clears them. A user's own comments are never new to them. Drives per-comment `New` pills, inbox
  `N new` chips, a `N new` pill on the header button (repainted from the counts every mutation now
  returns), and a dot on the Student-tab row. The read receipt uses a plain `db.session.commit()`,
  not `log_db_commit` — it is exactly the routine bookkeeping CLAUDE.md says to exclude from the
  audit log.
  **Student-row chip:** was a neutral grey *total*, so an unresolved thread looked identical to a
  resolved one. Now severity-coded — warning-subtle with the unresolved count (the same tone as the
  open-ticket chip), neutral grey with a tick when everything is resolved, outline when there are no
  comments — plus the unread dot. `comment_counts_by_record` returns
  `{total, unresolved, new}` from one grouped query with conditional aggregates, so it is still one
  query per AJAX page, not one per row.
  **Kept (implementation wins):** grouping/indexing by student over the reference's flat list; the
  explicit student `<select>` in the unscoped composer over the reference's ambient "Scoped to:"
  caption, which is incoherent even in its own screenshot (*Noah Boyer* above comments about Rachel
  Binnie and Adam Booth); absolute timestamps, per the Screen 6 decision.
  **Not adopted:** a CTA banner for unresolved comments — it would duplicate the header button's
  badge, which is the same information in less space.
  **Also fixed (latent):** the `review_comments` backrefs lacked `passive_deletes=True` despite a
  NOT NULL `matching_attempt_id` and a DB-level `ON DELETE CASCADE`, so an ORM-level attempt delete
  would have tried to null the FK. Both backrefs (and the new read-marker backref) now defer to the
  database cascade.
  **Noted, not actioned:** the student drawer's comments card stays a read-only *preview* rather than
  adopting the full thread macro — its reply/resolve controls would need their own JS binding inside
  the drawer, and "View full conversation" already hands off to the panel. It did gain the
  resolved-by line and the `N new` badge.
</content>
