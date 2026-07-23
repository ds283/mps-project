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

> **Deferred to Screen 1:** `modified_pill()` renders sentence-case "Modified"; the reference
> table (screenshot 01) shows uppercase "MODIFIED". Cosmetic — decide during the Student-view pass.

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
- **Screen 1 Student view** — _not started_
- **Screen 2 Student drawer** — _not started_
- **Role editor** — _not started_
- **Screen 3 Faculty view** — _not started_
- **Screen 4 Faculty drawer** — _not started_
- **Screen 5 Faculty reassignment** — _not started_
- **Screen 6 Changes tab** — _not started_
- **Screen 7 Matches dashboard** — _not started_
- **Screen 8 Comments panel** — _not started_
</content>
