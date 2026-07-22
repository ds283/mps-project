# Ticket system — working folder

Durable, version-controlled home for the ticket-system build (the greenfield trouble-ticket
system replacing `ConvenorTask`). Kept in-repo so the plan, the live task list, and the design
references survive context clears and travel with the code.

## What's here

| File | Purpose |
|---|---|
| `PLAN.md` | Canonical 8-phase implementation plan (mirrors the original approved plan), with per-phase status. |
| `TODO.md` | **Live task board — the source of truth for what's left.** Update as items land. |
| `reference/` | Claude Design spec + notification email (mirrored). See `reference/README.md`. |

## Current status (2026-07-22)

Phases 1–7 complete; Phase 8 sub-parts 8a/8b/8c (rollover guard, `status.html` swap, data
migration) done. Remaining: a small polish/fix backlog (labels entry-point, inbox reconciliation,
triage empty-state, compose scope/tenant), then the **Phase 8 teardown** of `ConvenorTask` (last).
Full detail in `TODO.md`.

## Conventions

- Work proceeds as a sequence of prompts, one task at a time, each ending with a diff/plan for
  review before applying, and committed as a clean rollback point (`ticket-system: <summary>`).
- Follow the repo root `CLAUDE.md` and `.claude/rules/*` throughout.

## Source

Design/spec produced in a Claude Design project, id `ee364388-462e-4b66-b781-739491d86910`.
