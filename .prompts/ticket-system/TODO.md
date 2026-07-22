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
- ◻ **Labels entry-point discoverability.** Only entry points are the inbox rail "Manage" link
  (inside `{% if labels %}` in `_inbox.html`, so hidden when zero labels exist) and the convenor
  per-class pane. Add an always-visible entry point (+ maybe a nav item).
- ❌ **Inline label creation from compose box.** Intentionally NOT supported (no pool pollution).

### Ticket detail (2a)
- ✅ **Breadcrumb "Tickets" link** (uncommitted): was linking to itself; now `_breadcrumb()` in
  `detail.py` points it to the convenor ledger for an in-scope class the user convenes (each class
  crumb links too), else the personal inbox.
- ⚠ **"No way to add labels" = a TENANT-DATA issue, not a code bug** (see Tenant section). The
  side-panel add-"+" only shows when `available_labels` is non-empty; that pool is filtered to
  `ticket.tenant_id`. The user's labels were created on tenant 1 ("Default") but the ticket/class
  are on tenant 2 ("Physics & Astronomy") → empty pool. Fix is the tenant-selector default, below.

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
- ◻ **Manage-labels tenant default is wrong for root/admin.** `_resolve_tenant(None)` picks the
  lowest tenant id = tenant 1 "Default", which has **no project classes**. Root created labels
  there, so they never appear on real (tenant-2) tickets. Fix: default to a tenant that actually
  has classes (or the user's "primary"), and/or make the selector state obvious. Partial mitigation
  already shipped: opening "Manage labels" from a convenor class ledger now pre-selects that
  class's tenant (`tenant_id=pclass.tenant_id`).
- ◻ **Single-tenant-per-ticket enforcement + scope-selector polish (compose).** `Ticket.tenant_id`
  is already a single scalar FK, so the model already assumes one tenant per ticket; not enforced
  at compose and the scope selector doesn't filter by tenant. Plan: reject subject sets spanning
  >1 tenant server-side; set `Ticket.tenant_id` from that tenant. Convenor compose → tenant implied
  by class. Faculty inbox compose spanning >1 tenant → tenant selector filtering the subject picker
  (server-side check as backstop). Do together with the scope-selector polish.

---

## Suggested order
1. Labels entry-point discoverability (small; unblocks the whole label feature).
2. Inbox reconciliation vs reference 2c (export the `.dc.html` first).
3. Convenor triage empty-state (small; fold in during dashboard work).
4. Compose scope-selector polish + single-tenant enforcement.
5. **Phase 8 teardown** (last).

## Uncommitted work right now (verify, then commit)
- Labels page: full-width layout, colour picker (palette + custom swatch), free hex backend, return
  link (`app/tickets/labels.py`, `app/tickets/forms.py`, `app/templates/tickets/labels.html`).
- Return-link entry points pass `return_to` (`convenor/dashboard/tickets.html`,
  `tickets/_inbox.html`); convenor link also pre-selects the class tenant.
- Ticket-detail breadcrumb fix (`app/tickets/detail.py` `_breadcrumb`, `templates/tickets/detail.html`).
