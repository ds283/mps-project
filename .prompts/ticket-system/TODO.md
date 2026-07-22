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
- ✅ **Manage-labels page: full-width layout + free colour picker.** (this session, uncommitted)
  Replaced 440px card with two-column card layout; backend accepts any `#rrggbb` hex
  (`_resolve_colour` in `app/tickets/labels.py`); bootstrap-colorpicker + palette presets in
  `app/templates/tickets/labels.html`.
- ◻ **Labels entry-point discoverability.** The only ways into `tickets.labels_manage` are the
  inbox rail "Manage" link — which sits inside `{% if labels %}` (`_inbox.html:65`), so it's
  **hidden when zero labels exist** (chicken-and-egg on a fresh tenant) — and the convenor
  per-class pane button. Add an always-visible entry point (show "Manage" even with an empty
  label list, and/or a nav item). Gate: `can_manage_labels` (convenor / admin / root).
- ❌ **Inline label creation from the compose "labels" box.** Intentionally NOT supported —
  typing shows "No labels found" rather than minting a label, which stops ordinary users
  polluting the label pool. (Confirmed keep-as-is.)

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

### Tenant scoping (design question — item 4)
- ◻ **Single-tenant-per-ticket enforcement + scope-selector polish (compose).** `Ticket.tenant_id`
  is already a single scalar FK (`app/models/tickets.py:205`), so the model already assumes one
  tenant per ticket; it just isn't enforced at compose and the scope selector doesn't filter by
  tenant. Plan: reject subject sets spanning >1 tenant server-side; set `Ticket.tenant_id` from
  that tenant. Convenor compose → tenant implied by class. Faculty inbox compose → if the faculty
  member spans >1 tenant, add a tenant selector that filters the subject picker (server-side check
  as backstop). **Do this together with the scope-selector polish**, not piecemeal.
- ◻ **(minor) Manage-labels tenant dropdown**: keep it (needed for multi-tenant convenor/admin;
  already auto-hides for single-tenant users). Later refinement: pre-select the tenant when
  "Manage labels" is opened from a convenor class pane (pass `tenant_id`).

---

## Suggested order
1. Labels entry-point discoverability (small; unblocks the whole label feature).
2. Inbox reconciliation vs reference 2c (export the `.dc.html` first).
3. Convenor triage empty-state (small; fold in during dashboard work).
4. Compose scope-selector polish + single-tenant enforcement.
5. **Phase 8 teardown** (last).

## Uncommitted work right now
- Labels page full-width + colour picker (backend `app/tickets/labels.py`, form docstring
  `app/tickets/forms.py`, template `app/templates/tickets/labels.html`). Being tested by the user;
  commit once verified.
