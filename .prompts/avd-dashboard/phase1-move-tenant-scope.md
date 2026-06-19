# Phase 1 — AVD dashboard: move into dashboards blueprint, tenant scoping, role rename

Shared context: `.prompts/avd-dashboard/recon.md` (read this first — it
records the model fields, access-control patterns, and UI decisions this
phase depends on, plus the reasoning behind options we rejected; don't
re-derive any of that, just verify it against current source).

This phase is **Python/routing/access-control only**. No template changes
beyond the minimum needed to keep the app working (nav link removal,
landing-page card). No new columns, badges, or row content yet — that's
later phases. Do not touch `archive/reports.html`'s table markup or
`reports_ajax`'s column definitions in this phase.

## Step 0 — Reconnaissance (do this first, produce a written plan before

touching any code)

Produce a short plan, written to
`.prompts/avd-dashboard/phase1-recon-output.md`, covering:

1. Every reference to `archive_reports` in the codebase: route
   decorators, role-seed/fixture data, any role-management UI or
   migration scripts, tests, and templates (`grep -rn "archive_reports"`
   across the whole repo, not just the files already reviewed in
   `recon.md`). List each file and line.
2. Every reference to `url_for('archive.reports'` / `url_for('archive.
   reports_ajax'` / `archive.reports` / `archive.reports_ajax` as a string
   (nav templates, redirects, tests). List each file and line.
3. The exact current `overview()` access-control OR-condition in
   `app/dashboards/views.py`, copied verbatim, so the edit in Step 4 is a
   precise diff rather than a guess.
4. The exact current card markup for one existing dashboard card (e.g.
   the AI Risk card) in `dashboards/overview.html`, copied verbatim, to
   use as the template for the new card in Step 5.
5. Confirm whether `_get_accessible_tenants` / `_get_default_tenant_id`
   are usable as-is from a new view function in the same module, or
   whether they need to move/be exported if Phase 1 puts the new route in
   a separate file. State which approach you'll take and why.
6. Check whether a role named `data_dashboard_reports` (or similar)
   already exists anywhere (seed data, role table) to avoid a collision.

Stop after this and present the plan before proceeding to Step 1, so it
can be reviewed.

## Step 1 — Role rename: `archive_reports` → `data_dashboard_reports`

- Add `data_dashboard_reports` wherever `archive_reports` is currently
  used as a role check, role-seed entry, or fixture, per the Step 0
  inventory. This is a rename, not an addition — `archive_reports` should
  not remain as a parallel/legacy role unless the Step 0 recon surfaces a
  reason it must (e.g. a migration constraint) — flag that explicitly
  rather than silently keeping both.
- If role grants are stored in the database (not just code), write a
  migration (or note clearly in the output if a manual `UPDATE`/admin
  action is required instead, and why) that moves existing
  `archive_reports` holders onto `data_dashboard_reports`.
- Verify: `grep -rn "archive_reports"` returns nothing except an explicit,
  justified exception (e.g. a migration file referencing the old name for
  historical purposes). Paste the grep output in your response.

## Step 2 — Relocate the route

- Move `reports()` and `reports_ajax()` from `app/archive/views.py` into
  `app/dashboards/views.py` (or a new sibling module imported by the
  `dashboards` blueprint, per whatever Step 0.5 concluded), renamed to
  `avd_dashboard()` and `avd_dashboard_ajax()`.
- Update the `@roles_accepted(...)` decorator on both to
  `roles_accepted("root", "admin", "data_dashboard_reports")` — no
  `faculty`/convenor branch, per `recon.md` (these users are explicitly
  not convenors).
- Update routes to live under the `dashboards` blueprint's URL prefix
  (match the existing pattern, e.g. `/dashboards/avd` and
  `/dashboards/avd_ajax`, consistent with `/dashboards/ai`,
  `/dashboards/marking` etc.).
- Delete `app/archive/views.py`'s `reports`/`reports_ajax` once the move
  is verified working (don't leave a duplicate route).
- If `app/archive/` becomes empty/dead after this move (per `recon.md`,
  there's no other use case for the `Archive` dropdown), remove the
  blueprint registration and nav dropdown entry; if anything else still
  lives under `archive/`, leave the blueprint in place and just remove
  the `reports` route and its nav link.

## Step 3 — Tenant scoping

- Add tenant selection to `avd_dashboard()` using the exact pattern from
  `ai_dashboard()` (`_get_accessible_tenants`, `_get_default_tenant_id`,
  single-tenant auto-select, `tenant_id` query param with clamping to the
  accessible set).
- Scope the pclass/year/group option-lists currently built in
  `reports()` to the *selected* tenant, not the full union of
  `current_user.tenants` as today — same shape as
  `_get_accessible_pclasses(tenant_id)` but without the convenor branch
  (root/admin/`data_dashboard_reports` see everything in-tenant; there is
  no third branch).
- Apply the same `tenant_id` scoping to `avd_dashboard_ajax()`'s base
  query (it currently filters on `allowed_tenant_ids` — the full set —
  for non-root users; change this to filter on the single selected
  `tenant_id`, passed through as a request arg the same way
  `pclass_filter`/`year_filter`/`group_filter` already are).
- Pass `accessible_tenants` and `selected_tenant` into the template.

## Step 4 — `overview()` gate

- Add `data_dashboard_reports` to the access OR-condition in `overview()`
  (the exact condition found in Step 0.3), so report-only users reach the
  landing page.
- Confirm (don't just assume) that the existing AI/Marking/Similarity
  cards are each independently gated within `dashboards/overview.html`
  (per Step 0.4) so a `data_dashboard_reports`-only user sees *only* the
  new AVD card, not the other three. If they are not independently gated
  today, that's a pre-existing gap — flag it in your output rather than
  silently fixing unrelated cards in this phase.

## Step 5 — Landing-page card

- Add a fourth card to `dashboards/overview.html` for the AVD dashboard,
  matching the structure of the existing cards (icon, description, stat
  chips, "Open dashboard" button), gated on the same condition as Step 4.
- Stat chips: reuse the shape of `_dashboard_summary_for_user()` /
  `_marking_summary_for_user()` — write a small `_avd_dashboard_summary_
  for_user()` helper returning counts only (e.g. tenants, eligible
  reports, AVD-consented count). Do **not** implement the consent-count
  query against `openday_consent_active` with full correctness obsession
  in this phase if it requires touching `reports_ajax`'s row logic before
  Phase 3 exists — a simple count query against `SubmissionRecord` is
  fine; the badge/filter UI for consent comes in Phase 3.
- Colour: use a new `--db-teal-*` token set in `common.css`, following
  the existing `--db-blue-*`/`--db-green-*`/`--db-orange-*`/`--db-purple-*`
  pattern exactly (six stops: 50/100/200/400/600/800). Do not reuse
  purple (reserved for AI-generated-content provenance per the existing
  `.badge-ai-generated` rule) or any of the three colours already
  assigned to AI/Marking/Similarity. No hardcoded hex values in the
  template — card accent, button, and chip colours all reference the new
  named tokens, consistent with the CSS-token-discipline rule in
  `recon.md`.

## Step 6 — Verification

Run and paste the output of each:

```bash
grep -rn "archive_reports" .
grep -rn "archive\.reports" .
grep -rn "url_for('archive.reports" .
grep -rn "url_for(\"archive.reports" .
```

All should return nothing (or only the explicitly justified exception
from Step 1).

Manually confirm (describe what you checked, don't just assert):

- a `data_dashboard_reports`-only user can load `/dashboards/` and sees
  only the AVD card
- the same user can load the AVD dashboard itself and the tenant
  selector behaves correctly for both single- and multi-tenant users
- a `root` user still sees all four cards and can switch tenants on the
  AVD dashboard
- the old `/archive/reports` URL no longer resolves (404, not a silent
  redirect that masks a missed reference)

## Out of scope for this phase (do not implement)

- Report grade column, thumbnails, consent badges, staff-roles block,
  details child-row — all later phases per `recon.md`'s phase breakdown.
  If you find yourself editing `reports_ajax`'s `columns` dict or the
  table's row-rendering logic, stop — that's Phase 2+.
