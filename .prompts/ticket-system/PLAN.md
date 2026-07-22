# Ticket System — implementation plan

> **Status (2026-07-22):** Phases 1–7 complete and committed. Phase 8 in progress:
> 8a (rollover hard-block), 8b (dashboard counts), 8c (data migration) done; the final
> **teardown** of `ConvenorTask` is the only remaining step of the plan. A polish/fix backlog
> accumulated during review — see **`TODO.md`** for the live task board. This file is the
> canonical design/plan and is preserved verbatim below.
>
> Original approved plan file: `~/.claude/plans/i-have-logged-in-shiny-pnueli.md` (now mirrored
> here so it is version-controlled and survives context clears).

---

## Context

We are building a greenfield **trouble-ticket system** for the MPS project platform, replacing the
single-user `ConvenorTask` infrastructure. It is multi-user, multi-channel (comments + logged
email), with label triage, action history, subscribers/watchers, and derived multi-class scope.

The design and specification come from a Claude Design project (project id
`ee364388-462e-4b66-b781-739491d86910`), comprising:
- `Ticket data model.md` — the authoritative data model (entities, derived scope, routing, permissions, migration).
- `Ticket System.dc.html` — the hi-fi reference screens (ids `1a`–`5b`).
- `Comment notification email.html` — the subscriber notification `EmailTemplate` HTML.
- `Implementation handoff brief.md` — a suggested 7-prompt build sequence.

(All of the above are mirrored in `reference/` alongside this file, except the large
`Ticket System.dc.html` + `support.js` — see `reference/README.md` for how to re-export those.)

The system is built **in parallel** with `ConvenorTask`; the old infrastructure is migrated and
removed only in the final phase, after the rollover guard and `status.html` read-paths are swapped
to tickets and verified.

**Confirmed product decisions (this session):**
- **Rollover: hard-block.** A class must not roll over while it has open student-scoped tickets in
  scope — same behaviour as today's `ConvenorTask` guard, reading ticket scope instead.
- **Sequencing:** refined breakdown below (the brief's 7 prompts, adjusted).

There is **no project test suite** (`CLAUDE.md`), so each phase is verified by running the app
locally and exercising the flows; the service layer (Phase 2) is the one place a small standalone
sanity script is worthwhile.

---

## Key architectural decisions

1. **Polymorphic subject via a single table (follow the spec, not joined-table inheritance).**
   `TicketSubject` is one table with a `kind` discriminator and three nullable FKs
   (`submitting_student_id`, `selecting_student_id`, `project_class_id`) plus a DB **check
   constraint** that exactly one is set. This is cleaner than the `ConvenorTask` joined-table
   pattern for a join row. (`ConvenorTask` in `app/models/utilities.py:126` remains the reference
   for *how* polymorphism is done in this repo, but the subject is a join, not an entity hierarchy.)

2. **Statuses/kinds use int-constant mixins, not Python/DB enums.** The repo convention
   (`app/models/model_mixins.py`, e.g. `WorkflowStatesMixin:97`, `TaskWorkflowStatesMixin:1353`)
   is integer constants + `_labels`/`_menu` dicts. Apply this to:
   `TicketWorkflowStatesMixin` (OPEN/IN_PROGRESS/RESOLVED/CLOSED),
   `TicketSubjectKindMixin`, `TicketEventKindMixin`, `TicketEmailDirectionMixin`,
   `TicketSubscriptionReasonMixin`.

3. **Split the brief's monolithic "Prompt 1" into model + service layer.** The routing/scope/
   auto-assign logic is the highest-risk core; isolating it (Phase 2) as pure, callable service
   functions (no request context) makes it testable and keeps the UI phases thin.

4. **Derived class scope is cached** in a `TicketClassScope(ticket_id, project_class_id)`
   association table, recomputed on any subject add/remove. `home_class(student)` resolves:
   - `SelectingStudent` → `selecting_student.config.project_class`
   - `SubmittingStudent` → `submitting_student.config.project_class`
   (relationships confirmed in `app/models/live_projects.py:1076,1750`, `app/models/project_class.py:705`).

5. **Auto-assign / convenor resolution** uses `ProjectClass.convenor.user` (+ `coconvenors`,
   `is_convenor_for`, `app/models/project_class.py:302,314,461`). `|scope|==1` → auto-assign that
   class's convenor; `|scope|>1` → unassigned + on every in-scope convenor's triage; `|scope|==0` →
   not routed.

6. **Tenant scoping** follows the existing pattern: derive allowed tenants from
   `current_user.tenants` (`app/models/users.py:76`) and filter with `.tenants.any(...)`. `Label`
   carries `tenant_id`; `Ticket` gets a cached `tenant_id` (derived from scope) for query
   efficiency and office cross-tenant filtering.

7. **New blueprint** `app/tickets/` (multi-module, like `app/convenor/`), registered in
   `app/__init__.py` (~line 498) with `url_prefix="/tickets"`. AJAX row formatters go in
   `app/ajax/tickets/`. All routes render via `render_template_context(...)`.

---

## Phase breakdown

### Phase 1 — Data model + migration (no logic, no UI)  ✅ done (f8eedc81)
**Goal:** all tables exist and migrate cleanly.

New `app/models/tickets.py` (register in `app/models/__init__.py`):
- `Ticket` — `id`, `title`, `description` (Text), `status` (int, `TicketWorkflowStatesMixin`),
  `created_by_id`→User, `assignee_id`→User (nullable), `due_date`, cached `tenant_id`→Tenant,
  `created_at`/`updated_at`; use `EditingMetadataMixin` (`app/models/model_mixins.py:45`).
- `TicketComment`, `TicketEmail` (direction/from/to/subject/body/message_id/logged_at),
  `TicketEvent` (append-only: `kind`, `payload_json` Text/JSON, `actor_id`, `created_at`).
- `TicketSubject` (single-table polymorphic-by-`kind` + 3 nullable FKs + check constraint).
- `TicketClassScope(ticket_id, project_class_id)` association.
- `TicketSubscription(ticket_id, user_id, reason)`, `TicketExternalSubscriber(ticket_id, email)`.
- `Label(tenant_id, name unique-within-tenant, color)` + `TicketLabel(ticket_id, label_id)`.

Conventions: `id` int PK; strings `collation="utf8_bin"` + `DEFAULT_STRING_LENGTH`
(`app/models/defaults.py`); `lazy="dynamic"` collections; relationships/backrefs per repo style.

**Migration:** hand-written Alembic file (per `CLAUDE.md` — find tip with the documented `comm`
command; never `flask db migrate`). Include the check constraint.

**Deliverable:** `flask db upgrade` succeeds; no UI.

### Phase 2 — Service layer: scope, routing, subscriptions, events  ✅ done (e00d9194)
**Goal:** pure, testable core in `app/shared/tickets/` (no request/UI).
- `home_class(student)`; `recompute_scope(ticket)` (rebuilds `TicketClassScope` from subjects).
- `apply_auto_assign(ticket)` (the |scope| rule); `convenors_in_scope(ticket)`.
- `add_subject(ticket, ...)` / `remove_subject(...)` → recompute scope, keep existing owner
  (decision 3 in spec), refresh convenor subscriptions.
- Subscription helpers (auto-add opener/assignee/in-scope convenors; reason tracking).
- `record_event(ticket, actor, kind, payload)` + convenience wrappers for each transition.
- Permission helpers (who-may-assign / label / status-change), mirroring the spec §8 matrix.

**Deliverable:** a short scratch script instantiating a ticket with 1 and >1 class subjects and
asserting scope + assignee + subscriber outcomes (stands in for absent unit tests).

### Phase 3 — Blueprint scaffold + ticket detail (screen 2a) + assign picker (4a)  ✅ done (a29106db)
- Create `app/tickets/` blueprint, register it, add a nav entry in `app/templates/base.html`
  (role-gated block, ~lines 285–411).
- Detail page (extends `base_app.html`): conversation thread (comments + logged email + events
  interleaved), reply composer with "email subscribers" toggle, side panel (status, assignee,
  subscribers, labels, context, actions log).
- Wire POST actions (each backed by a WTForms `Form` + `form.hidden_tag()`, per `CLAUDE.md`):
  add comment, log email, change status ("Comment & resolve" = comment + status in one),
  add/remove label, subscribe/unsubscribe, **assign/unassign (assign picker 4a)**. Every action
  calls `record_event(...)` and `log_db_commit(...)`.

### Phase 4 — Compose flows (2b faculty, 3b office)  ✅ done (6a1f498e)
- Faculty compose (2b): subject picker limited to supervisees
  (`SubmissionRole→SubmissionRecord→SubmittingStudent`, `app/models/faculty.py:539`) + supervised
  classes (`EnrollmentRecord`), with live routing/auto-assign preview.
- Office compose (3b): multi-select any submitting/selecting student or class in subscribed
  tenants; multi-class → no auto-assignee. Enforce scope rules **server-side**.
- Forms use `flask_security.forms.Form` + shared mixins (`app/shared/forms/mixins.py`),
  `QuerySelectField`/`QuerySelectMultipleField`, select2 wired in-template (`select2-small`).

### Phase 5 — Dashboards (3a convenor, 2c faculty/office, 1a ledger)  ✅ done (b36d9bcd)
- Convenor dashboard (3a): "needs triage" panel (`assignee IS NULL AND |scope|>1`, joined via
  `TicketClassScope` to classes the convenor convenes) + full class ledger with Watchers/Due/Scope
  columns. Ledger table (1a) is a reusable DataTables component (`ServerSideSQLHandler`, row
  formatter in `app/ajax/tickets/`).
- Faculty/office inbox (2c): Views + Labels + Activity rail, metric tiles, assigned/watched list
  (`user ∈ subscribers OR assignee == user`).

### Phase 6 — Labels management (4b/5a) + bulk actions (5b)  ✅ done (fc41063a)
- Tenant-scoped label CRUD: create/edit/delete, 9-colour palette (next-unused auto-assign +
  swatch override), permission gate (convenor / admin·root / assigned owner; watchers read-only).
- Inline label apply from rows (2c/1a/3a) + bulk action bar (5b): multi-select ledger rows →
  add/remove label, set status, assign.

### Phase 7 — Notifications  ✅ done (b2f5960f)
- Seed `Comment notification email.html` as an `EmailTemplate` (new type constant in
  `EmailTemplateTypesMixin` + `_TYPE_NAMES`, `app/models/emails.py:49`) via an Alembic seed
  migration (pattern: `migrations/versions/b7c8d9e0f1a2_...`).
- On new comment, fan out to subscribers (incl. `TicketExternalSubscriber` addresses), honouring
  the reply toggle, using the existing email pipeline
  (`app/tasks/services.py:149 send_email_list` / `EmailTemplate.apply_`). Outbound + manual-log
  only — **no inbound path** (spec decision 4).

### Phase 8 — Migration, rollover hard-block, `status.html` swap, teardown (LAST)  ◻ in progress
- **8a ✅ (55cb8875)** Rollover guard (hard-block): so `confirm_rollover`/`rollover` block on
  open in-scope student-scoped tickets, reading `TicketClassScope`. Same `_flash_blocking_tasks` UX.
- **8b ✅ (b3e13213)** `status.html` CTA swap: convenor dashboard aggregation
  (`get_convenor_dashboard_data`; `todo_count`, `get_convenor_action_items`, `get_convenor_todo_data`)
  now counts **ticket** data (open + needs-triage per class).
- **8c ✅ (2cec6532)** Data migration `ConvenorTask`→`Ticket` (+ subjects): selector/submitter
  tasks → student subjects; generic → `project_class` subject (or General). Carry status/owner/dates.
- **◻ Teardown (remaining):** once migrated + status swapped + verified, remove `ConvenorTask`,
  `ConvenorSelectorTask`, `ConvenorSubmitterTask`, `ConvenorGenericTask`, their routes
  (`app/convenor/student_tasks.py`, task views in `app/convenor/projects.py`), ajax
  (`app/ajax/convenor/student_tasks.py`, `todo_list.py`), and templates.

---

## Cross-cutting conventions (apply throughout)
- All POST forms backed by WTForms `Form` (`flask_security.forms.Form`), CSRF via
  `{{ form.hidden_tag() }}`; POST views use `form.validate_on_submit()`. Never mutate
  `field.validators` after instantiation.
- DB writes logged with `log_db_commit(...)` (`app/shared/workflow_logging.py:132`) for
  user-initiated workflow events; skip noisy low-level activity.
- Inspector/list views: DataTables + `ServerSideSQLHandler` AJAX, row formatters in
  `app/ajax/tickets/` (see `.claude/rules/ajax-datatables.md`).
- Colours from Bootstrap 5.3 tokens / `common.css` semantic tokens (`.claude/rules/template-colours.md`);
  the design's blue `#0d6efd`, status pills, dark `#212529` navbar map to `var(--bs-primary)` etc.
- Initials always from `user.initials` (`app/models/users.py:257`); `datetime.datetime.now()`.
- Migrations hand-written; find the tip with the `CLAUDE.md` `comm` command before each.

## Verification
Per phase, run locally (`python serve.py` + Celery worker/beat for Phase 7) and exercise the
matching screen(s). Phase 2 gets a scratch script. Phase 8 is the critical read-path swap: confirm
`status.html` shows ticket counts and rollover blocks on an open in-scope ticket **before** any
teardown. `ruff check .` / `ruff format --line-length 150` on touched files.

## Note on execution
This is large; it is implemented as a **sequence of separate prompts, one phase at a time**,
each ending with a diff/plan for review before applying. This plan is the shared map for that
sequence.
