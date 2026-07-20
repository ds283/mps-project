# 07 — Overview dashboard: "Journal activity" summary card

## Goal
Add a compact "Journal activity" card to the convenor overview, mirroring the Tasks
inspector pattern, summarising unread / recent / accessible counts and the most recent
entries — at a density that matches the other overview fixtures.

## Context
- Template: `app/templates/convenor/dashboard/overview.html`.
- Route: `convenor.overview` in `app/convenor/dashboard.py` (assembles the panel context).
- The other overview panels are compact cards — match that, do **not** use tall stat blocks.

## Tasks
1. **Aggregate context.** In `convenor.overview`, compute for the current convenor across the
   config's students: total visible entries, unread count, count created in the last 30 days,
   and the ~2–3 most recent visible entries (with student, author, type, timestamp). Reuse the
   prompt-01 helpers; keep it a bounded query, not per-student loops decrypting bodies.
2. **Card.** Add a `card` with a single-line header summary
   (`… · N unread · N this month · N accessible`) and a flush `list-group` of the most-recent
   entries (type icon, title link → drawer, student · author · time, `new` tag when recent).
   Header has an "Open journal →" button that activates the new Journal tab (prompt 08).
   Match the compact density of neighbouring panels.
3. **Wire drawer.** Entry links open the shared drawer (prompt 04) for that student.

## Acceptance
- Card renders with correct aggregate counts (visible-only) and recent entries.
- Visually compact, consistent with adjacent overview panels; primary blue, no teal.
- "Open journal" switches to the Journal tab; entry links open the drawer.

## Commit
```
git add -A && git commit -m "journal-redesign(07): journal activity summary card on overview dashboard"
```
