# Phase 8 — AVD dashboard: collapsible filter panel

Shared context: `.prompts/avd-dashboard/recon.md` §10/§13/Phase 6 notes
(filter-bar compactness was partially addressed in Phase 6 by merging
the AVD/exemplar consent sections; a full show/hide toggle for the whole
filter block was discussed as the next step but not yet implemented).
Current state per the latest screenshot: seven filter sections (tenant,
pclass, year, group, grade, consent) stacked vertically above the table,
each always visible, taking up roughly a full screen's height before any
results appear.

Scope: add a single show/hide control for the entire filter block. Small,
self-contained UI change — no filter logic changes.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase8-recon-output.md`, present before coding)

1. Search the codebase for existing collapsible-panel conventions (Bootstrap
   `data-bs-toggle="collapse"` + `.collapse`/`.collapse.show`, or any
   accordion component already in use elsewhere — check convenor
   dashboard templates, configure.html, status.html, or any other
   multi-section filter/config UI per memory of this codebase's existing
   patterns) and reuse whichever established pattern is closest, rather
   than introducing a new one. Quote the reference markup verbatim.
2. Copy verbatim the current filter-block markup in
   `avd_dashboard.html` (the seven sections, their wrapping container).
3. Decide and state: should the filter block default to expanded or
   collapsed on page load? Consider — a first-time visitor probably wants
   to see filter options; a returning user who's already set filters
   probably wants them out of the way. Propose remembering the
   expanded/collapsed state (e.g. via the same session-key persistence
   mechanism already used for individual filter selections, per earlier
   phases) so it doesn't reset to expanded on every page load/filter
   change — confirm this mechanism exists and is reusable for a single
   boolean rather than per-filter values.
4. Check whether DataTables' ajax reload (triggered on filter change)
   causes a full page reload or an in-place ajax refresh — relevant to
   whether the collapse state needs to survive a reload at all, or
   whether it's purely a client-side toggle that persists naturally
   within a session.

## Step 1 — Implement

- Add a toggle control (button or clickable header, per Step 0.1's
  established pattern) that shows/hides the entire filter block as one
  unit — not per-section, the whole thing collapses/expands together.
- When collapsed, show a compact summary of how many filters are
  currently non-default (e.g. "3 filters active") so a user isn't flying
  blind with the block hidden — reuse this dashboard's own filter-state
  tracking (the session-persisted filter values from Phases 1–6) to
  compute this count rather than introducing new state.
- Apply Step 0.3's decision on default state and persistence.

## Step 2 — Verification

- Manually confirm (describe what you checked):
  - toggle correctly shows/hides the full filter block
  - the "N filters active" summary (if implemented per Step 1) updates
    correctly as filters change
  - collapse/expand state persists according to Step 0.3's decision
  - all existing filter functionality (every button, every filter
    combination from Phases 1–6) is unaffected — this phase only adds a
    show/hide wrapper, it doesn't touch filter logic
  - no layout regression when collapsed (table area correctly reclaims
    the freed vertical space, doesn't leave an awkward gap)

## Out of scope

- Any further restructuring of the filter sections themselves (already
  addressed in Phase 6's consent-filter merge) — this phase only adds the
  show/hide wrapper around the existing structure.
- Restricted-row grade visibility (flagged in the latest review as an
  unresolved side effect of Phase 7, not yet decided) and project-class
  colour-coding remain deferred.
