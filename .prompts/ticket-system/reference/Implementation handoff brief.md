# Ticket system — implementation handoff brief

Carry this file, `Ticket data model.md`, and `Ticket System.dc.html` into a Claude.ai chat that
**also has the codebase attached**. The prompts below are written to be run in order by Claude
Code against the real repo; each assumes the previous one has landed.

---

## 1. What this is

A greenfield **trouble-ticket system** replacing the single-user `ConvenorTask` infrastructure.
Multi-user, multi-channel (comments + logged email), label triage, action history. Built in
**parallel** with the old task system; `ConvenorTask` is migrated and removed last (see §5 and
the migration section of the data-model spec).

Two companion documents:
- **`Ticket data model.md`** — the authoritative model: entities, derived class scope,
  routing/auto-assign rule, permissions, resolved decisions, migration plan. **Read first.**
- **`Ticket System.dc.html`** — the hi-fi design, as a set of referenceable screens (below).

### Roles & the core rules (quick reference)
- **faculty / office** → personal **Inbox** (2c): only tickets assigned to them *or* that they
  watch — never a whole class. They can open tickets (faculty: own supervisees + classes they
  supervise; office: any submitting/selecting student or class in their subscribed tenants).
- **convenor** → **Convenor dashboard** (3a): every ticket whose derived scope includes a class
  they convene. A convenor's *personal* inbox (assigned/watched) is distinct from this.
- **admin / root** → see the convenor dashboard too; can assign like a convenor.
- **Auto-assign:** scope of exactly one class → auto-assign that class's convenor; scope > 1 →
  unassigned + on every in-scope convenor's triage; scope 0 (General) → not routed.

---

## 2. Screen inventory (ids into `Ticket System.dc.html`)

| id | screen | purpose |
|---|---|---|
| **1a** | Ledger | convenor default list; upgraded table, can surface every ticket in a class |
| **1b** | Inbox | personal list with Views + Labels rail (basis for 2c) |
| **1c** | Triage board | Kanban by status; optional convenor lens, cannot surface *all* tickets |
| **2a** | Ticket detail | shared by all roles; thread, logged email, events, reassignment, side panel, actions log |
| **2b** | Compose (faculty) | role-scoped subject picker (supervisees / class) + convenor routing |
| **2c** | Faculty/office home | Views + Labels + Activity in one rail; metric tiles; assigned/watched list |
| **3a** | Convenor triage | "needs triage" panel (unassigned multi-class) + full class ledger; Watchers/Due/Scope cols |
| **3b** | Compose (office) | wider multi-select scope across tenants; multi-class → no auto-assignee |
| **4a** | Assign picker | convenor/admin/root; in-scope convenors, student supervisors, office, unassign |
| **4b** | Label management | create/edit, palette colour auto-assign, inline apply, watcher read-only |
| **5a** | Edit label | rename + recolour existing label |
| **5b** | Bulk actions | multi-select ledger rows → add/remove label, set status, assign |

Plus **`Comment notification email.html`** — the `EmailTemplate` (Jinja tokens) sent to
subscribers on a new comment.

---

## 3. Recommended prompt sequence for Claude Code

Run in order. Each prompt should end by asking Claude Code to show a diff/plan before applying,
and to add tests where the repo has them.

**Prompt 1 — Models & routing core.**
Create the ticket models from `Ticket data model.md` §1–§7: `Ticket`, `TicketComment`,
`TicketEmail`, `TicketEvent`, `TicketSubject` (polymorphic: submitting/selecting student or
project class), `TicketSubscription` + `TicketExternalSubscriber`, tenant-scoped `Label` +
`TicketLabel`, and the `TicketClassScope` association table. Implement `home_class(student)`
and the scope-recompute hook on subject change. Implement the auto-assign rule. Migrations only;
no UI yet.

**Prompt 2 — Detail view + thread.**
Build the shared ticket detail page to match **2a**: conversation thread (comments +
manually-logged email + events), reassignment event, the side panel (status, assignee,
subscribers, labels, context, actions log), and the reply composer with the "email subscribers"
toggle. Wire `TicketEvent` creation for every state change.

**Prompt 3 — Compose forms.**
Build the two compose flows: faculty (**2b**, subjects limited to supervisees via
`SubmissionRole → SubmissionRecord → SubmittingStudent` + supervised classes) and office
(**3b**, any submitting/selecting student or class in subscribed tenants, multi-select). Show
live routing/auto-assign consequences. Enforce scope rules server-side.

**Prompt 4 — Dashboards.**
Build the convenor dashboard (**3a**: needs-triage panel + full class ledger with
Watchers/Due/Scope) and the faculty/office inbox (**2c**: Views + Labels + Activity rail,
metric tiles, assigned/watched list). Reuse the ledger table for the convenor default (**1a**).
Optionally the board (**1c**) as a lens.

**Prompt 5 — Labels & bulk actions.**
Tenant-scoped label management (**4b/5a**): create/edit, 9-colour palette with next-unused
auto-assign + override, permission gate (convenor / admin·root / assigned owner; watchers
read-only). Inline apply from rows (2c/1a/3a) and the bulk action bar (**5b**).

**Prompt 6 — Notifications.**
Store `Comment notification email.html` as an `EmailTemplate` instance and wire the fan-out to
subscribers (incl. external addresses) on new comment, honouring the reply toggle. Outbound +
manual-log only — no inbound path (see decision 4).

**Prompt 7 — Migration, rollover & `status.html` (LAST).**
Migrate `ConvenorTask`/`ConvenorSelectorTask`/`ConvenorSubmitterTask` → tickets + subjects.
Rework the **rollover blocker** to consult open student-scoped tickets via `TicketClassScope`
instead of the old task tables. Rebuild the convenor **`status.html` CTA aggregation** to count
ticket data. Then remove the `ConvenorTask` infrastructure.

---

## 4. Decisions locked (from the spec)

- Labels are **per tenant** (vocabulary leakage across a tenant's classes accepted).
- Class scope is cached in **`TicketClassScope`**, refreshed on subject change.
- Adding a subject that makes a ticket multi-class **keeps the existing owner**; it just appears
  on the newly-in-scope convenor's triage board (informational, not "needs a claim").
- **No inbound email** path yet (no readable mailbox); `TicketEmail` is outbound + manual log.

## 5. Sequencing risks to watch

- Do **not** remove `ConvenorTask` until Prompt 7's migration + `status.html` swap are verified.
- The **rollover guard** is the highest-risk change — a class must not roll over with open
  student-scoped tickets unless that's an explicit product decision. Test both paths.
- `status.html` is a **read-path swap**: the CTA panel must show ticket counts, not task counts,
  before teardown.
