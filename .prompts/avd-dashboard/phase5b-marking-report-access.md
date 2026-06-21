# Phase 5b — fix marking/moderator report access for data_dashboard_reports and data_dashboard_similarity users

Context: Phase 5's recon output
(`.prompts/avd-dashboard/phase5-recon-output.md`) flagged that the
per-role `MarkingReport`/`ModeratorReport` links added to the AVD
dashboard's details child row 403 for a user who holds only
`data_dashboard_reports` (not `faculty`/`admin`/`root`), since the
existing report-viewing routes are gated
`roles_accepted("faculty", "admin", "root")`. The Similarity dashboard
has the identical gap for its own non-faculty role,
`data_dashboard_similarity`. **This phase fixes both**, not just AVD —
the whole point of both `data_dashboard_*` roles (per `recon.md` §1–§2
for the reports case) is giving non-faculty, non-admin staff a working
view into this data, including exactly the report-history links each
dashboard surfaces. A dead link for either dashboard's primary intended
audience isn't acceptable.

This is an access-control change — go carefully, recon first, and surface
the options rather than just picking one.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase5b-recon-output.md`, present before any
code change, and **wait for explicit approval before proceeding** — this
phase touches permissions, not just display logic)

1. Find the actual view route(s) serving `MarkingReport`/`ModeratorReport`
   content that the Phase 5 links point at. Quote the route definition,
   its `@roles_accepted(...)` decorator, and its full body verbatim.
2. Determine whether this route is **read-only** (renders/serves the
   report content) or whether it also exposes edit/write actions on the
   same endpoint (e.g. a form for entering grades, accepting moderation,
   etc., gated behind the same decorator). This is the central question —
   the answer determines which fix is safe.
3. Check whether the route already does any per-object permission
   narrowing beyond the role decorator (e.g. "this faculty member can
   only view reports for projects they supervise") — if so, understand
   that logic, since a `data_dashboard_reports` user's permitted scope
   needs to be at least as narrow (probably: any report within their
   accessible tenants, matching the AVD dashboard's own tenant-scoping
   from Phase 1 — not blanket access to every report in the system).
4. Check whether a separate, already-read-only view exists elsewhere in
   the app for "look at this report's content without being able to act
   on it" (e.g. anything used by external examiners, or a print/PDF
   export view) — reusing an existing read-only surface is preferable to
   widening a route that also has write capability.
5. Confirm whether the Similarity dashboard's identical gap (mentioned in
   Phase 5's output) shares the exact same route, or a different one.
   **In scope for this phase**: find the equivalent marking/moderator (or
   whatever underlying report-viewing) links on the Similarity dashboard
   and confirm whether they hit the same route(s) identified in Step 0.1,
   or separate ones — either way, this phase now fixes both dashboards'
   instances of the gap, not just AVD's. The Similarity dashboard's
   non-faculty role is `data_dashboard_similarity` (parallel to
   `data_dashboard_reports` here).

## Step 1 — Propose, don't yet implement, a fix

Based on Step 0's findings, write up (still in
`phase5b-recon-output.md`) one of:

- **Option A**: if the route(s) are genuinely read-only with no write
  surface, add both `data_dashboard_reports` and `data_dashboard_similarity`
  to the relevant `roles_accepted(...)` call(s) — same route gets both
  roles added if it's the shared route serving both dashboards' links; if
  AVD and Similarity hit different routes, each gets its own role added —
  with the same tenant-scoping check from Step 0.3 applied in each case
  (don't grant blanket cross-tenant access to either role).
- **Option B**: if the route has write capability mixed in, do **not**
  widen its role decorator for either role. Instead, propose a new,
  narrowly-scoped read-only route (or query param / view mode on the
  existing route that forces read-only rendering for non-faculty roles)
  that both `data_dashboard_reports` and `data_dashboard_similarity` users
  can reach, reusing the route's own rendering logic where possible
  rather than duplicating template code — one shared read-only surface
  for both dashboards if their links point at the same underlying report
  type, separate ones if not.
- **Option C**: if Step 0.4 finds an existing read-only surface, point
  both dashboards' links at that instead of the faculty-facing route.

State which option applies and why, with the exact diff you intend to
make, before writing any code.

## Step 2 — Implement (only after the Step 1 proposal is reviewed)

- Implement the chosen option for both `data_dashboard_reports` (AVD) and
  `data_dashboard_similarity` (Similarity), per Step 0.5's finding on
  whether they share a route or not.
- Update the Phase 5 child-row links (AVD) and the equivalent Similarity
  dashboard links if they need to point at a different URL than
  originally wired (Option B/C).
- Apply the same tenant-scoping discipline used elsewhere in this
  dashboard (Phase 1) — both roles' users should be able to view reports
  within their accessible tenants only, not system-wide, even if the
  underlying route would otherwise allow it.

## Step 3 — Verification

- Manually confirm (describe what you checked):
  - a `data_dashboard_reports`-only user can now successfully open a
    marking/moderator report link from the AVD dashboard's details panel
  - a `data_dashboard_similarity`-only user can now successfully open the
    equivalent report link from the Similarity dashboard
  - neither user has gained any new ability to submit grades, accept
    moderation, or otherwise write to the fixed route(s) — confirm
    explicitly for both roles, this is the main risk of this phase
  - neither role can view a report belonging to a tenant outside their
    own access, even via a guessed/crafted URL
  - existing `faculty`/`admin`/`root` access to the same routes is
    unaffected
  - a user holding only `data_dashboard_reports` (not
    `data_dashboard_similarity`) still cannot use this fix as a backdoor
    into anything the Similarity dashboard would otherwise gate, and vice
    versa — confirm the fix doesn't accidentally cross-grant between the
    two roles
- If you chose Option A but later phases of this app might add write
  actions to that route, flag that as a risk for future maintainers in
  your written output (a comment in code, or a note in
  `phase5b-recon-output.md`) so it doesn't silently become a privilege
  escalation later.
