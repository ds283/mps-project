# Ticket System — live task board

Working backlog for the ticket system. **This is the source of truth for "what's left"** —
update it as items land so context can be cleared safely. See `PLAN.md` for the full design and
phase history; `reference/` for the Claude Design spec + screens.

Legend: ✅ done · 🔧 in progress · ◻ outstanding · ❌ deliberately not doing

---

## Build phases
- ✅ Phases 1–7 (models, service layer, detail view, compose, dashboards, labels+bulk, notifications)
- ✅ Phase 8a — rollover hard-block on open student-scoped tickets
- ✅ Phase 8b — convenor `status.html` CTA counts ticket data
- ✅ Phase 8c — data migration `ConvenorTask` → `Ticket`
- ◻ **Phase 8 teardown (LAST)** — remove `ConvenorTask`, `ConvenorSelectorTask`,
  `ConvenorSubmitterTask`, `ConvenorGenericTask` + their routes / ajax / templates:
  - `app/convenor/student_tasks.py`, task views in `app/convenor/projects.py`
  - `app/ajax/convenor/student_tasks.py`, `app/ajax/convenor/todo_list.py`
  - class defs in `app/models/utilities.py`
  - **Precondition met** (migration + status swap + rollover guard done & verified). Do this
    after the polish backlog below, so the old UI stays available as a reference/fallback while
    the new system's gaps are closed. Watch for stale imports of `ConvenorTask` when deleting.

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
5. **Phase 8 teardown** (last).

## Uncommitted work right now (verify, then commit)
- Labels page: full-width layout, colour picker (palette + custom swatch), free hex backend, return
  link (`app/tickets/labels.py`, `app/tickets/forms.py`, `app/templates/tickets/labels.html`).
- Return-link entry points pass `return_to` (`convenor/dashboard/tickets.html`,
  `tickets/_inbox.html`); convenor link also pre-selects the class tenant.
- Ticket-detail breadcrumb fix (`app/tickets/detail.py` `_breadcrumb`, `templates/tickets/detail.html`).
- Tenant scoping: remove tenantless inbox "Manage" link (`tickets/_inbox.html`); `_resolve_tenant`
  aborts instead of guessing (`app/tickets/labels.py`); compose single-tenant backstop + tenant
  selector (`app/tickets/compose.py`, `templates/tickets/compose.html`).
