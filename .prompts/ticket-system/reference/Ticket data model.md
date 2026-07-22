# Ticket system — data model spec

Derived from the UI/UX in `Ticket System.dc.html` (turns 1–4). This is the model the
screens imply; it is meant to be reviewed and adjusted, not treated as final.

---

## 1. Core entities

### `Ticket`
| field | type | notes |
|---|---|---|
| `id` | pk | shown as `#412` etc. |
| `title` | str | required |
| `description` | text | markdown; the opening post of the thread |
| `status` | enum | `open → in_progress → resolved → closed` (see §5) |
| `created_by_id` | fk → `User` | the opener; auto-subscribed |
| `assignee_id` | fk → `User`, **nullable** | null = unassigned but still routable (see §4) |
| `due_date` | date, nullable | optional throughout the UI |
| `created_at` / `updated_at` | datetime | `updated_at` drives "Recently updated" sort |

A ticket is **not** owned by a single `ProjectClass` column. Its class scope is *derived*
from its subjects (§2–3) so that a ticket can legitimately span more than one class.

### `TicketComment`
Thread entries authored by users. `id, ticket_id, author_id, body, created_at`.

### `TicketEmail`
Logged inbound/outbound email, auto-linked to a ticket by a `[#id]` token in the subject.
`id, ticket_id, direction (in|out), from_addr, to_addrs, subject, body, message_id, logged_at`.
Rendered inline in the thread (2a) as a distinct "Email logged" event.

### `TicketEvent` (actions log)
Append-only audit entries that render both in the side-panel "Actions log" and inline in the
thread. `id, ticket_id, actor_id, kind, payload_json, created_at`, where `kind ∈
{opened, status_changed, assigned, unassigned, label_added, label_removed, subscribed,
comment_added, email_logged, subject_added, subject_removed}`. `payload_json` carries the
before/after (e.g. `{from:"open", to:"in_progress"}`, or the reassignment `{from, to}`).

---

## 2. Subjects — what a ticket is "about"

A ticket has **zero or more subjects**, each pointing at exactly one target. This is the
polymorphic join that lets a ticket name several students and/or classes at once (office
compose, 3b).

### `TicketSubject`
| field | type | notes |
|---|---|---|
| `id` | pk | |
| `ticket_id` | fk → `Ticket` | |
| `kind` | enum | `submitting_student` \| `selecting_student` \| `project_class` |
| `submitting_student_id` | fk, nullable | set when `kind = submitting_student` |
| `selecting_student_id` | fk, nullable | set when `kind = selecting_student` |
| `project_class_id` | fk, nullable | set when `kind = project_class` (a *pinned* class) |

Exactly one of the three fk columns is non-null, matching `kind` (DB check constraint).

A ticket with **no** subjects is a "General" ticket (office may open these); it has empty
class scope and therefore no auto-assignee and no convenor surfacing — it lives only with its
creator/assignee until a subject is added. The compose forms nudge against this.

---

## 3. Class scope — derived, not stored

`scope(ticket)` = the set of `ProjectClass` the ticket touches:

```
scope(ticket) =
    { s.project_class_id for s in subjects if s.kind == project_class }          # pinned
  ∪ { home_class(student) for each student subject }                             # inherited
```

**`home_class(student)`** is the class the student sits in:
- `SelectingStudent` → its `SelectingStudent.config.project_class` (the class they select in).
- `SubmittingStudent` → the `ProjectClass` reached from the submission config. Where a student
  has submission records under a `SubmissionRole` (`SubmissionRole → SubmissionRecord →
  SubmittingStudent`), the class is that record's project class.

Scope is computed on demand (or cached in a `TicketClassScope` association table refreshed on
subject change) so the convenor dashboard queries stay index-friendly.

---

## 4. Routing & assignment

**Assignment rule (from 3a/3b):**
- `|scope| == 1` → **auto-assign** to that class's convenor at creation
  (`assignee = convenor_of(the one class)`), and record an `assigned` event with a marker that
  it was automatic ("auto" badge in the ledger).
- `|scope| > 1` → **leave unassigned** (`assignee_id = null`). It surfaces on the triage panel
  of *every* in-scope convenor's dashboard until someone Claims/Assigns it.
- `|scope| == 0` (General) → no routing; not surfaced to convenors.

**Convenor dashboard query** — a ticket shows on convenor `C`'s dashboard for class `K` iff
`K ∈ scope(ticket)` and `C` convenes `K`. This covers both student-scoped and generic
class-scoped tickets, assigned or not. The "needs triage" panel is the subset where
`assignee_id IS NULL AND |scope| > 1`.

**Personal inbox (2c)** — for faculty/office (and convenors acting personally): tickets where
`user ∈ subscribers` OR `assignee == user`. Never the whole class. A convenor's *personal*
inbox therefore differs from their *convenor dashboard*.

**Who may assign (4a):** convenor of an in-scope class, or `admin`/`root`. The picker offers
in-scope convenors, supervisors of attached students, the office, and Unassign.

---

## 5. Status

`open → in_progress → resolved → closed`, linear but any transition allowed (with an event
logged). "Comment & resolve" in 2a is a comment + `status_changed→resolved` in one action.
`resolved` vs `closed`: resolved = fixed, awaiting confirmation; closed = done/won't-do,
drops out of the default open views.

---

## 6. Subscribers (watchers)

### `TicketSubscription` — `ticket_id, user_id, reason (opener|assignee|manual|convenor)`
Drives the "Watching" view and email fan-out. Auto-added: opener, assignee, and (on routing)
the in-scope convenor(s). External addresses (e.g. ATAS office) are stored as
`TicketExternalSubscriber(ticket_id, email)` so they receive the same email thread without a
`User` row.

---

## 7. Labels

### `Label` — per tenant (resolved: tenant-scoped, not per class)
| field | type | notes |
|---|---|---|
| `id` | pk | |
| `tenant_id` | fk | labels belong to a tenant; shared across that tenant's classes |
| `name` | str | unique within tenant |
| `color` | str (hex) | from a fixed 9-colour palette; auto-assigned = next unused, override by swatch (4b) |

### `TicketLabel` — `ticket_id, label_id` (m2m).

**Who may add/remove labels:** convenor, `admin`/`root`, or the **assigned owner**. Watchers
and other users see labels **read-only** (4b). Same permission gates the inline label control
in 2c/1a/3a and the label editor.

---

## 8. Permissions summary

| action | faculty | office | assignee | convenor (in scope) | admin/root |
|---|---|---|---|---|---|
| open ticket (scoped to own supervisees / class) | ✓ | ✓ (wider scope) | – | ✓ | ✓ |
| comment / log email | ✓* | ✓* | ✓ | ✓ | ✓ |
| change status | – | – | ✓ | ✓ | ✓ |
| assign / unassign (4a) | – | – | – | ✓ | ✓ |
| add / remove labels | – | – | ✓ | ✓ | ✓ |
| manage label definitions | – | – | – | ✓ | ✓ |
| see convenor dashboard | – | – | – | ✓ | ✓ |

\* if subscribed / a participant on the ticket.

---

## Resolved decisions

1. **Label scope: per tenant.** `Label` hangs off the tenant, not `ProjectClass`. Vocabulary
   leakage across classes in a tenant is accepted. (Update §7: replace `project_class_id` with
   `tenant_id`; `name` unique within tenant.)
2. **Scope caching: yes — association table.** Maintain `TicketClassScope(ticket_id,
   project_class_id)`, refreshed whenever a `TicketSubject` is added/removed (and when a
   student's home class changes). Dashboard queries join against it.
3. **Reassignment on subject-add: keep the existing owner.** Adding a subject that pushes a
   ticket to multi-class does **not** unassign it. The current owner stays; the ticket is
   simply added to the newly-in-scope convenor's triage board (it appears there as assigned to
   someone else, i.e. informational rather than "needs a claim").
4. **Closed-ticket email replies: out of scope for now.** We have no inbox the app can read, so
   there is no inbound-email path yet. `TicketEmail` covers outbound + manually-logged mail
   only. Inbound auto-linking (and any reopen-on-reply behaviour) is a future feature that
   depends on provisioning a mailbox the app can poll/receive from.

---

## Migration & retirement of `ConvenorTask`

Build the ticket system **in parallel** with the existing task system; migrate and remove the
old infrastructure only once tickets are complete.

- **Data migration:** map `ConvenorTask → Ticket`. Student-scoped subclasses become
  `TicketSubject` rows: `ConvenorSelectorTask → TicketSubject(selecting_student)`,
  `ConvenorSubmitterTask → TicketSubject(submitting_student)`; generic tasks become a
  `project_class` subject (or General where none applies). Carry over status, owner, dates.
- **⚠ Rollover blocker:** `ConvenorSelectorTask` / `ConvenorSubmitterTask` currently **block
  rollover** of a project class to the new academic year. The equivalent guard must be reworked
  for tickets whose scope includes a selecting/submitting student in the class being rolled
  over — i.e. rollover checks `TicketClassScope` / open student-scoped subjects instead of the
  old task tables. Decide whether open tickets hard-block rollover (as today) or just warn.
- **`status.html` CTA panel:** rebuild the convenor `status.html` data aggregation so the CTA
  panel counts/surfaces **ticket** data (open + needs-triage for the class) rather than
  `ConvenorTask` counts. This is the main read-path swap.
- **Teardown:** once migrated and `status.html` is swapped, remove `ConvenorTask`,
  `ConvenorSelectorTask`, `ConvenorSubmitterTask` and their templates/routes.
