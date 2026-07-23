# Ticket System — live task board

Working backlog for the ticket system. **This is the source of truth for "what's left"** —
update it as items land so context can be cleared safely. See `PLAN.md` for the full design and
phase history; `reference/` for the Claude Design spec + screens.

Legend: ✅ done · 🔧 in progress · ◻ outstanding · ❌ deliberately not doing

---

## Build phases
- ✅ Phases 1–7 (models, service layer, detail view, compose, dashboards, labels+bulk, notifications)
- ✅ Phase 8a — rollover hard-block on open student-scoped tickets
- ⚠ **Phase 8b — corrected retrospectively.** The original entry here claimed the convenor
  `status.html` CTA counts had been swapped to ticket data. That was inaccurate: commit `b3e13213`
  was explicitly additive (its own message says so) — it added a parallel "Tickets" tab/counts
  but left the old "Tasks" tab, "Upcoming tasks" card, and per-student task badges on the
  selectors/submitters pages fully wired to `ConvenorTask`, deliberately deferred until the ticket
  system was proven. That cutover is what actually happened in the three rewire commits below.
- ✅ Phase 8c — data migration `ConvenorTask` → `Ticket`
- ✅ **Rewire to tickets** (2026-07-23): closed the gap left by 8b before teardown.
  - Go-Live (`confirm_go_live`/`perform_go_live`) got the ticket-based blocking guard
    (`get_blocking_tickets`/`_flash_blocking_tickets`) that rollover already had.
  - `status.html`'s CTA panel now reads `get_convenor_open_tickets` (open tickets in class scope)
    instead of `ConvenorTask`; links into the ticket detail view / Tickets tab.
  - `SelectingStudent`/`SubmittingStudent` gained `number_open_tickets`; the "N tasks" badges on
    the selectors page, `submitters_v2.html`, and the legacy `submitters.html` ajax formatter
    (`app/ajax/convenor/submitters.py`, reachable behind the `SUBMITTERS_V2` flag) all read it now.
  - Decision (confirmed with user): the `ConvenorGenericTask.rollover=True` recurring-task
    carry-forward feature has no ticket equivalent and was **dropped**, not ported.
- ✅ **Phase 8 teardown (LAST)** — removed `ConvenorTask`, `ConvenorSelectorTask`,
  `ConvenorSubmitterTask`, `ConvenorGenericTask`, `ConvenorTasksMixinFactory`, and the orphaned
  `RepeatIntervalsMixin`; their routes (`app/convenor/student_tasks.py` — `inject_liveproject`,
  an unrelated route in that file, was relocated into `projects.py` rather than deleted),
  forms, ajax row formatters, and templates; the `ensure_ticket_migration` bootstrap in
  `initdb.py`/`serve.py`; and finally the four `convenor_task*` DB tables (migration
  `b4e7a1d9c3f2`, applied — all 138 legacy rows were already present in `tickets` via
  `source_task_id` before the tables were dropped). Verified against a rebuilt dev image at each
  step (status/selectors/submitters pages + ajax endpoints, Go-Live/rollover guards, old routes
  now correctly `BuildError`, migration applied cleanly).

## Polish / fix backlog (agreed sequencing: fix + polish, THEN teardown)

### Labels
- ✅ **Labels entry-point discoverability — resolved by design** (uncommitted). Consolidated onto the
  convenor ledger "Manage labels" button (unique tenant). The tenantless personal-inbox rail "Manage"
  link was **removed** (`_inbox.html`) — it was the sole trigger of the bad tenant default. No
  always-visible personal-inbox entry point; admin/root manage labels via the convenor dashboards too.
- ✅ **Manage-labels page: full-width layout + free colour picker.** (uncommitted)
  Two-column card layout; backend accepts any `#rrggbb` hex (`_resolve_colour`).
- ✅ **Colour picker UX** (uncommitted): fixed palette swatches + a final "custom" (rainbow)
  swatch that reveals the free picker; picker hidden while a palette swatch is selected. No more
  inconsistent swatch-vs-colour state.
- ✅ **Return link from manage-labels page** (uncommitted): `?return_to=` (validated local path)
  threaded through create/edit/delete; "Back" link in the header. Convenor "Manage labels" also
  passes `tenant_id=pclass.tenant_id` so it opens on the *class's* tenant.
- ✅ **Manage-labels layout — GitHub-style** (uncommitted): full-width list of defined labels;
  create/edit in a **modal dialog** with a live preview pill; Back button restyled to
  `btn btn-sm btn-outline-secondary` + `fa-arrow-left fa-fw`.
- ❌ **Inline label creation from compose box.** Intentionally NOT supported (no pool pollution).

### Ticket detail (2a)
- ✅ **Breadcrumb "Tickets" link** (uncommitted): was linking to itself; now `_breadcrumb()` in
  `detail.py` points it to the convenor ledger for an in-scope class the user convenes (each class
  crumb links too), else the personal inbox.
- ⚠ **"No way to add labels" = a TENANT-DATA issue, not a code bug** (see Tenant section). The
  side-panel add-"+" only shows when `available_labels` is non-empty; that pool is filtered to
  `ticket.tenant_id`. The user's labels were created on tenant 1 ("Default") but the ticket/class
  are on tenant 2 ("Physics & Astronomy") → empty pool. Fix is the tenant-selector default, below.
- ✅ **Reconciled with reference design (2a/4a)**. Subscriber management (add/remove internal users,
  external emails, new `ticket_subscriber` "Management watchers" role, `can_manage_subscribers`);
  assignee picker widened with search + "Suggested / Assign to me"; timeline renders coloured status
  chips and reassignment mini-avatars at a larger text size. "Email subscribers didn't fire" is
  resolved as not-a-bug (the only subscriber was the commenter, who is excluded) — now exercisable
  since subscribers can be added. See `.prompts/ticket-system/detail-view-reconcile.md`.
- ✅ **Second-pass colour + context reconciliation** (commit `e5a59651`). Screenshot compare vs
  reference #412 closed the remaining colour/structure gaps: Context is now icon-led with a Class
  link plus **Scope / Opened / Due** rows (surfaces the model's previously-unused `due_date`);
  timeline label events render the actual coloured label chips, grouping consecutive same-actor
  adds into one row; header gained an outline **Watching/Watch** button + a `…` overflow menu
  (Copy link, Log an email); subscriber remove-`×` reveals on hover for a clean avatar row.
  Actions log kept its verbose format but **capped at 12 events** (`_ACTIONS_LOG_LIMIT`) to bound
  rail height. Deliberately **not** done: compact "date · initials" actions-log reformat and the
  reply-box formatting toolbar (user opted out); solid label-pill style left as-is.

### Compose / "New ticket" view (2b/3b) — reconcile with reference
- ✅ **Compose view reconciliation** (per `compose-reconcile.md`; commit `ticket-system: reconcile
  compose view chrome + scope filter`). Delivered:
  1. **Surface-correct chrome.** `_compose_template()` / `_origin_pclass_compose()` in
     `app/tickets/compose.py` mirror `detail._detail_template()`; new `convenor_compose.html` +
     `faculty/dashboard/faculty_compose.html` wrappers + `_compose_body.html` /
     `_compose_scripts.html` split, threaded via `origin`/`pclass` through GET → POST → the
     detail redirect so chrome persists. Entry points (`convenor/dashboard/tickets.html`,
     `tickets/_inbox.html`) thread `origin`.
  2. **Hide past-cycle students.** `_student_results` / `_faculty_candidates` filter on
     `ProjectClassConfig.year >= get_current_year()` unless `include_past` is set; a "Show past
     students" checkbox in the picker toggles it via `compose_people`. `_authorized()` left
     unfiltered.
  3. **Full visual reconciliation:** avatar+subtitle picker rows (`user.initials`) via select2
     `templateResult`/`templateSelection`, subscriber avatar chips (current user + in-scope
     convenors, live-updated from `compose_routing`), Cancel button, linked "Tickets" breadcrumb.
  - Verified via a Flask test-client run against the dev stack: all three chrome variants render
    (200, surface-correct nav markers present), `compose_people` avatar/subtitle rows and
    `include_past` filtering confirmed against real data, and a full POST round-trip (convenor
    origin) lands on the detail view with the same origin/pclass chrome. Test ticket cleaned up
    after verification.

### Convenor triage pane (3a)
- ◻ **Empty-state.** Pane, view, and nav tab all exist and work (`app/convenor/tickets.py`,
  `templates/convenor/dashboard/tickets.html`, `nav.html:99`). It renders only when there are
  unassigned multi-class tickets (`assignee IS NULL AND |scope|>1`), so it *vanishes* when there
  are none and reads as "missing". Add a "nothing to triage" empty state; verify with real
  multi-class unassigned data.

### Inbox (2c)
- ◻ **Reconcile chrome with the reference design (screen 2c).** `templates/tickets/inbox.html`
  + `_inbox.html` are functional but have drifted from the Claude Design reference. **Blocked on**
  exporting `reference/Ticket System.dc.html` (+ `support.js`) — see `reference/README.md`. Do a
  side-by-side before/after. This is the main genuine polish item.

### Tenant scoping (design question — item 4) — PRIORITY, causing real breakage
- ✅ **Manage-labels tenant default eliminated** (uncommitted). Decision: label management always has a
  single well-defined tenant (the owning class's), because it is reached **only from a convenor class
  ledger** (admin/root use the convenor dashboards too). So there is no default heuristic: removed the
  `if tenant_id is None` guess in `_resolve_tenant` → now `abort(400)`; removed the tenantless
  personal-inbox "Manage" link that was the only way to hit it. Supplied-id validation
  (`manageable.get` / `abort(403)`) unchanged.
- ✅ **Single-tenant-per-ticket enforcement + scope-selector polish (compose)** (uncommitted).
  Server-side backstop in `compose()`: reject a resolved subject set spanning >1 tenant (via
  `_target_tenant_id`) before `create_ticket`, so `Ticket.tenant_id` (derived by `recompute_scope`)
  is always unambiguous. UI: `_available_tenants(user)` drives a tenant `<select>` shown only when the
  user's candidate scope spans >1 tenant; `compose_people` + `_office_candidates`/`_faculty_candidates`
  take an optional `tenant_id` filter; changing the selector clears stale picks and re-scopes the
  select2 picker. `derive_tenant_id` left as-is (now only ever fed one tenant).
- ✅ **Manage-labels page: removed the in-page tenant-switcher dropdown.** The labels page is
  reached only from a convenor class ledger, which already fixes the tenant
  (`tenant_id=pclass.tenant_id`) — so a switcher just reintroduced a "pick/guess a tenant" surface
  that duplicated what the entry point already resolved. Removed the `tenants|length > 1` dropdown
  branch in `labels.html` and the now-unused `tenants=_manageable_tenants(...)` context var in
  `labels.py` (`_manageable_tenants` is still used internally by `_resolve_tenant`). Note this is a
  local simplification for this one screen, not a system-wide single-tenant assumption — the
  `Tenant` model and admin tenant CRUD (`app/tenants/`) still fully support multiple tenants.

---

## Suggested order
1. ✅ Labels entry-point / tenant default — resolved (removed inbox link; convenor-ledger only).
2. Inbox reconciliation vs reference 2c (export the `.dc.html` first).
3. Convenor triage empty-state (small; fold in during dashboard work).
4. ✅ Compose scope-selector polish + single-tenant enforcement — done.
5. ✅ **Phase 8 teardown** — done, including the rewire it depended on. See "Build phases" above.

## What's left
Only the two ◻ items above: convenor triage empty-state (3a), and inbox chrome reconciliation
(2c, blocked on exporting the `.dc.html` reference). `ConvenorTask` is fully gone — no remaining
build-phase or teardown work.
