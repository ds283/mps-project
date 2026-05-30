# Convenor UI patterns

## Student card structure

When displaying a list of students with per-student submission detail, use a card-per-student
layout rather than a DataTables table. Each card has three layers:

1. **Card header** (`background: var(--bs-tertiary-bg)`, `border-bottom: 1px solid var(--bs-border-color)`):
   - Student name as `<a>` at `font-size: 14px; font-weight: 600; color: var(--bs-primary)`.
   - Programme and cohort as plain secondary text (`font-size: 12px; color: var(--bs-secondary-color)`)
     with `·` separators on the same metadata line — no badge styling.
   - Status pills (Published/Unpublished, warnings, errors) on the same metadata line.
   - Student-level action buttons (Journal, History, Roles, overflow dropdown) in the card header right.
   - Only Published/Unpublished and alert states use pill styling; programme and cohort do not.

2. **Period tabs** — if `config.number_submissions > 1`, render a tab bar with one tab per period.
   - Active tab: `color: var(--bs-primary)`, `border-bottom: 2px solid var(--bs-primary)`.
   - If a period has errors, append a small dot (`7px`, `background: var(--bs-danger)`).
   - If a period has warnings (but no errors), append a small dot (`background: var(--bs-warning)`).
   - For single-period project classes, omit the tab bar entirely.

3. **Period panel** — project title + owner/change link + project page button; metric capsules;
   status strip; similarity strip if present; risk factor button if needed; roles grid.

## Metric capsules

Attendance metrics (Recorded, Missing, Rate) and grade metrics (Supervision, Report, Presentation)
must be rendered as two visually distinct labelled capsules — never a single undifferentiated row.

- **Attendance capsule**: `border-color: var(--bs-info-border-subtle)`,
  body `background: var(--bs-info-bg-subtle)`, label `color: var(--bs-info-text-emphasis)`.
- **Grades capsule**: `border-color: var(--bs-success-border-subtle)`,
  body `background: var(--bs-success-bg-subtle)`, label `color: var(--bs-success-text-emphasis)`.
- Suppress the Attendance capsule entirely when no attendance data exists for the period
  (`attendance_data['total'] == 0` or no data returned).
- Show the Grades capsule whenever there is at least one grade field relevant to the project class.

## Metric value colour coding

- Present, positive value: `color: var(--bs-success-text-emphasis)` (class `mv-ok`)
- Warning / zero recorded / non-zero missing: `color: var(--bs-danger-text-emphasis)` (class `mv-warn`)
- Null / not yet set: `color: var(--bs-border-color)` (class `mv-dim`) — renders as a dim `—`

## Status strip chips

Each period panel has a status strip showing report state, LLM status, and risk flags:

- LLM result present: `background: var(--bs-success-bg-subtle)`, `color: var(--bs-success-text-emphasis)`
- LLM pending (in-progress): `background: var(--bs-warning-bg-subtle)`, `color: var(--bs-warning-text-emphasis)` — add `data-sid="<record_id>"` for JS polling
- No LLM analysis: `background: var(--bs-secondary-bg)`, `color: var(--bs-secondary-color)`
- Flag ok (no risk factors): success subtle pair
- Flag warning: warning subtle pair with `border: 1px solid var(--bs-warning-border-subtle)`
- Flag danger (unresolved risk): danger subtle pair with `border: 1px solid var(--bs-danger-border-subtle)`

## Similarity and risk strips

- Similarity strip: `background: var(--bs-warning-bg-subtle)`, `border: 1px solid var(--bs-warning-border-subtle)`
- Risk factor button: `background: var(--bs-danger-bg-subtle)`, `color: var(--bs-danger-text-emphasis)`,
  `border: 1px solid var(--bs-danger-border-subtle)`

## Card list vs DataTables

The convenor submitters view (`submitters_v2.html`) does not use DataTables. Filtering is
server-side via query parameters; pagination is handled by slicing the Python list in the route
and rendering pager controls in the template. Other views in the convenor dashboard that are
genuinely tabular should retain DataTables.
