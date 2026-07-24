# Matching workspace redesign — implementation handoff

Reference design: `Matching workspace redesign.dc.html` (options **1a** student dashboard, **1b** student drawer, **1c** faculty view, **1d** reassignment modal). This document is the spec; the `.dc.html` is the visual target.

## Goal

Keep **one row per `MatchingRecord`** (the current system's primitive) but make the **submission period** of every allocation unambiguous, restore the old system's at-a-glance scanning (per student *and* per period), move the comment anchor onto the record, and give the student drawer period context.

`MatchingRecord` = allocation of a `LiveProject` + `MatchingRole`s to a `SubmittingStudent` for **one** `SubmissionPeriodDefinition`. Period identity must be carried by the `SubmissionPeriodDefinition`, never by a numeric ordinal alone (see Sorting).

---

## Files in scope

| Template | Option | Change |
|---|---|---|
| `matching_dashboard.html` / `_student_pane.html` | 1a | Period pill per row; group bands; group-by toggle; comment anchor moved to row |
| `_student_drawer.html` | 1b | Period-context header; sibling-allocations strip |
| `_faculty_pane.html` | 1c | `class · period` tag on every supervising/marking allocation |
| `_faculty_reassign_modal.html` | 1d | `class · period` tag on **Currently assigned** students only |
| `_macros.html` | all | Add a `period_pill(spd)` macro; reuse everywhere |

The DataTables endpoints that feed `match_student_v2` / `match_faculty_v2` must return the `SubmissionPeriodDefinition` (id, name, `ProjectClass`, and its position within the class) for each row so the client can render pills and group/sort.

---

## 1a — Student dashboard

- **Retain** the existing *Filter by project class* / project type / hinting selectors exactly as they are. They are unchanged.
- Each record row **leads with a period pill** built from its `SubmissionPeriodDefinition.name` (e.g. "Autumn term", "Full year"). This is the fix for the disambiguation problem — do not rely on row order.
- **Group-by toggle: Student ⇄ Submission period.**
  - *By student*: group key is **(`SubmittingStudent`, `ProjectClass`)** — a student with records in two project classes appears as two groups, matching the old system. Group band shows name, class swatch, cohort, and a **score roll-up** (Total) once.
  - *By submission period*: see Sorting below — group key is the **`SubmissionPeriodDefinition`**, not the period number.
- **Comment anchor** (`💬` + add) moves off the student name into each record row's **Actions** cell, so it is unambiguously bound to that `MatchingRecord`. Existing comment plumbing (`_comments_panel.html`, `mw-drawer-open-comments`, `data-rec-id`) is unchanged — only the trigger's location moves.

## 1b — Student drawer (`_student_drawer.html`)

- Add a **period-context header**: the current record's `SubmissionPeriodDefinition.name` plus its position within the student's set for that class ("Autumn term · 1 of 2").
- Add a **sibling-allocations strip**: one small card per *other* `MatchingRecord` the student holds (period label · assigned project · rank · assigned/unassigned dot). Clicking a card re-fetches the drawer for that `record.id` (reuse the existing `match_student_drawer_ajax` route) — no need to close the offcanvas.
- **Comments, Ranked selection, Journal** stay scoped to the currently-shown record.

## 1c — Faculty view (`_faculty_pane.html`)

- Every supervising and marking allocation gets a **`class · period` tag** (swatch + class abbreviation + period pill). The current cells show only the class abbreviation, so two allocations of the same project in different periods are indistinguishable — this is the fix (e.g. Prof Calmet supervising *Theoretical Aspects of Black Holes* in both the autumn and spring MPP periods).
- Allocations within each cell are **sorted by the same order as 1a's period grouping** (see Sorting).

## 1d — Reassignment modal (`_faculty_reassign_modal.html`)

- **Currently assigned** cards get the `class · period` tag (they represent `MatchingRecord`s → each belongs to a period).
- **Per-project capacity** rows do **not** get a period tag. A `LiveProject` is period-independent and its capacity accumulates across all periods; keep only the class swatch + abbreviation there.

---

## Sorting (applies to 1a "by period" grouping and 1c allocation order)

Switching to *Submission period* grouping must **always** produce the same, stable order:

1. **Group by `ProjectClass`** first, in a defined `ProjectClass` order (use the existing project-class ordering — e.g. `ProjectClass.number` / sort key — the same order used elsewhere in the app).
2. **Within a `ProjectClass`, group by `SubmissionPeriodDefinition`**, ordered by that definition's position within its class (`SubmissionPeriodDefinition.period` / sequence field).
3. All periods of one `ProjectClass` are contiguous; classes follow one another in the defined order.

Because periods are keyed on the `SubmissionPeriodDefinition`, "period 1" of one class (e.g. MPP autumn term) and "period 1" of another (e.g. the year-long BSc period) are **distinct groups and never merged**, even though both sort first within their own class.

In **1c**, order the supervising list and the marking list by this same key (`ProjectClass` order, then period order within class) so faculty allocations read consistently with 1a.

---

## Colours

- `ProjectClass`-scoped items (swatches, and the tint of period pills for that class) must be **anchored on each `ProjectClass`'s assigned colour** — use `ProjectClass.make_CSS_style()` (already used by `swatch.html` and the faculty templates), not hand-picked hexes.
- The reference design uses **reduced-intensity** versions of those colours for the pill fills/borders (subtle-background / text-emphasis pairs) so the pills read as quiet chips rather than saturated blocks. Derive these from each class colour rather than hardcoding: lighten/desaturate for the fill, use the class colour (or a darkened form) for text/border. Follow the Bootstrap 5.3 `*-bg-subtle` / `*-text-emphasis` pattern the codebase already uses (`.claude/rules/template-colours.md`) — no raw hex literals.
- Rank/score/hint colours are unchanged (existing semantic tokens).

## Notes

- Full-page fidelity, spacing, and the pill/badge vocabulary in the `.dc.html` are the visual target; all markup should be Bootstrap 5.3 semantic tokens per the existing templates.
- No model changes are required beyond exposing `SubmissionPeriodDefinition` (id, name, class, in-class position) to the two table endpoints and the drawer payload.
