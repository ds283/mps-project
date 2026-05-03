---
paths:
  - app/templates/dashboards/**
---

# Dashboard colour conventions

## Token system

All dashboard identity colours must use the named CSS custom properties defined
in [shared stylesheet or base_app.html]. Never use hardcoded hex values or
Bootstrap's `bg-primary`, `text-primary`, `bg-success`, `text-success` classes
to express dashboard identity. Those Bootstrap classes are reserved for semantic
use (alerts, status indicators) elsewhere in the application.

The two ramps are:

- `--db-blue-*`  (50, 100, 200, 400, 600, 800) — AI Risk Dashboard identity
- `--db-green-*` (50, 100, 200, 400, 600, 800) — Marking Dashboard identity

## Stop usage convention

| Stop | Use                                               |
|------|---------------------------------------------------|
| 50   | Panel/card background fills                       |
| 100  | Section header background fills                   |
| 200  | Borders and dividers                              |
| 400  | Interactive elements, progress bar fills, buttons |
| 600  | Secondary text, labels, export button text        |
| 800  | Heading text on light coloured backgrounds        |

## Per-dashboard rules

**AI Risk Dashboard** (`ai_dashboard.html`)

- Pipeline status panel header: `--db-blue-50` background, `--db-blue-200` border, `--db-blue-800` text
- Academic year section headers: `--db-blue-100` background, `--db-blue-800` text
- Cycle summary headers: `--db-blue-50` background, `--db-blue-200` border
- Progress bar fills: `--db-blue-400`
- Primary action buttons (Apply, Submit): `.btn-db-blue` class
- No `linear-gradient` with hardcoded hex values

**Marking Dashboard** (`marking_dashboard.html`)

- Page header banner: `--db-green-50` background, `--db-green-200` border
- Event role section headers: `--db-green-50` background, `--db-green-800` text
- Primary action buttons (Apply): `.btn-db-green` class
- Health indicator progress bars (distribution, submitted, feedback, etc.) remain
  Bootstrap semantic colours (`bg-success`, `bg-warning`, `bg-danger`) — these
  encode workflow health, not dashboard identity, and must not be changed

**Overview page** (`overview.html`)

- AI Risk card icon background: `--db-blue-50`
- Marking card icon background: `--db-green-50`
- Open dashboard buttons: `.btn-db-blue` and `.btn-db-green` respectively

## Adding a new dashboard

1. Choose a new ramp name following the `--db-{colour}-*` convention
2. Define all six stops (50, 100, 200, 400, 600, 800) in the single shared token block
3. Create `.btn-db-{colour}` and `.btn-db-{colour}:hover` utility classes alongside
   the existing button definitions
4. Add a per-dashboard section to this rules file documenting which elements use which stops
5. Add an entry to the overview page using the 50-stop for the icon background
   and the new button class for the open-dashboard button