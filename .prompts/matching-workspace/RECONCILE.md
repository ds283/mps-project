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
- **Screen 4 Faculty drawer** — _not started_
- **Screen 5 Faculty reassignment** — _not started_
- **Screen 6 Changes tab** — _not started_
- **Screen 7 Matches dashboard** — _not started_
- **Screen 8 Comments panel** — _not started_
</content>
