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
- **Screen 6 Changes tab** — _not started_
- **Screen 7 Matches dashboard** — _not started_
- **Screen 8 Comments panel** — _not started_
</content>
