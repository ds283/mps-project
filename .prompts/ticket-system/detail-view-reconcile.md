# Prompt — Reconcile ticket detail view with reference design (2a / 4a)

> Run this in a fresh Claude Code context against the repo. Follow the repo root `CLAUDE.md` and
> `.claude/rules/*` throughout. Land the work as small, separately-committable sub-tasks
> (`ticket-system: …`), per the commit-per-phase convention. End each sub-task with a diff/plan for
> review before applying. Reference material: `.prompts/ticket-system/reference/` (screens 2a detail,
> 4a assign picker; `Ticket data model.md` §4/§6).

## Context

The ticket-system detail page (`app/templates/tickets/detail.html`, screen 2a) is a strong match for
the Claude Design reference, but there are real gaps found while using it. This task closes those gaps
and adds the one genuinely missing capability — **managing a ticket's subscribers**.

Findings from comparing the current code with the reference:

1. **Subscribers are unmanageable from the UI.** The panel only *renders* avatars; there is no "+"
   affordance and no route to add/remove another user or an external email. Only self `watch`/`unwatch`
   exists (`app/tickets/detail.py:477-512`). The reference (2a, sidebar Subscribers block) shows a
   faint `fa-plus` at the right of the "Subscribers" heading — the same idiom as the Status / Assignee /
   Labels pencils.
2. **Assignee picker is a fixed 300px Bootstrap dropdown → truncated names** (`detail.html:229`). The
   reference (4a) is a ~460px panel with a "Search people…" box, a **Suggested · "Assign to me"** row
   (green rationale subline + `current · auto` pill), then grouped candidates, then Unassign.
3. **Weaker timeline colour / smaller text.** The reference colour-codes status words inline (blue
   "Open" → amber "In progress") and renders mini-avatars in reassignment events; body/event text reads
   a touch larger. Current impl renders these as plain grey sentences (`_describe_event`,
   `detail.py:77-117`; `.tk-event` `font-size:12.5px`, `detail.html:36`).
4. **The "email subscribers" notification is NOT broken.** `app/tasks/ticket_notifications.py` is fully
   wired and correctly routes through `EmailWorkflow` (project convention — not a direct send). It didn't
   fire in testing because the *only* subscriber was the commenter, who is deliberately excluded
   (`ticket_notifications.py:69`) → empty recipients → early return. Fixing (1) is what makes it useful.
   Only a stale docstring/comment (`forms.py:35`, `detail.py:326`) claims it is unwired.

Note: the `avatar()` macro (`detail.html:10`) already colours per-person via `user.avatar_colour`;
uniform-colour avatars in a thread just mean every entry is the same user. No change needed there.

### Decisions locked with the user
- **Subscriber pool** = baseline (in-scope convenors, supervisors of attached students, office) **plus
  a new seeded `ticket_subscriber` role** ("Management watchers" — senior tutor, student-experience,
  etc.) so those people can watch a ticket without office/admin power.
- **External email subscribers**: yes — a free-text email field creating `TicketExternalSubscriber`
  (model already exists; the email fan-out already includes external subscribers).
- **Remove** subscribers: yes — a small `×` per subscriber (internal avatars + external pills), visible
  to users who can manage the ticket.
- Assignee *pool* stays the reference set (convenors / supervisors / office). Assignment carries action
  duties, so `ticket_subscriber` is **watch-only** — not offered as an assignee. (Easy to extend later.)

---

## Implementation

### Task A — Subscriber management (the substantive piece)

**A1. New role.** Add a `ticket_subscriber` entry to `_REQUIRED_ROLES` in `initdb.py:391` (idempotently
created by `ensure_roles`, same pattern as the `data_dashboard_*` roles — **no migration needed**).
Description e.g. "Eligible to be added as a ticket watcher; grants no operational permissions." Give it a
purple-ish hex. It surfaces automatically in the existing manage-users role UI.

**A2. Permission predicate.** Add `can_manage_subscribers(user, ticket)` to
`app/shared/tickets/permissions.py` = `is_admin_or_root or is_convenor_in_scope or is_assignee`
(mirrors `can_label`). Export from `app/shared/tickets/__init__.py` (`__all__` + import block).

**A3. Service helpers** in `app/shared/tickets/subscriptions.py`:
- `subscribe` / `unsubscribe` already accept an arbitrary user — reuse for internal add/remove.
- Add `add_external_subscriber(ticket, email, actor)` and `remove_external_subscriber(ticket, external, actor)`
  that create/delete a `TicketExternalSubscriber` (model in `app/models/tickets.py`) and record a
  `TicketEvent.SUBSCRIBED` / `UNSUBSCRIBED` with an `{"email": …}` payload. Idempotent add; validate the
  email server-side. Do **not** commit (caller owns the txn). Export both.
- Extend `_describe_event` (`detail.py:105-109`) so SUBSCRIBED/UNSUBSCRIBED render an external
  `email` payload as well as the existing `user` payload.

**A4. Candidate builder.** Add `_build_subscriber_options(ticket)` in `detail.py`, modelled on
`_build_assign_options` (`detail.py:175`): sections **Convenors in scope**, **Supervisors of attached
students**, **Office**, **Management watchers** (new: `User.roles.any(Role.name == "ticket_subscriber")`,
tenant-filtered like `_office_users`). **Exclude users already subscribed** so the add-list only shows
addable people. Pass as `subscriber_sections` to the template.

**A5. Routes** in `app/tickets/detail.py` (all `@login_required`; gate on `can_manage_subscribers`;
validate `ConfirmActionForm`/dedicated form; commit via `_commit_or_flash`; redirect via `_back`):
- `POST /<ticket_id>/subscriber/add/<int:user_id>` → `subscribe(ticket, target, reason=MANUAL, actor)`
- `POST /<ticket_id>/subscriber/remove/<int:user_id>` → `unsubscribe(ticket, target, actor)`
- `POST /<ticket_id>/external_subscriber/add` → new `TicketExternalSubscriberForm` → `add_external_subscriber`
- `POST /<ticket_id>/external_subscriber/remove/<int:ext_id>` → `remove_external_subscriber`

Add `TicketExternalSubscriberForm` (single `email = StringField(validators=[DataRequired(), Email(), Length(max=255)])`)
to `app/tickets/forms.py`. Instantiate in the `detail` view; pass as `external_form`.

**A6. Template** (`detail.html` Subscribers section, lines 263–275):
- Add a `fa-plus` dropdown to the `.tk-panel-lbl` (copy the Labels-panel dropdown idiom, lines 281–293),
  gated by a new `perms.subscribe`. Dropdown body = client-side search input + `subscriber_sections`
  (grouped `dropdown-header` + POST-form rows, same shape as the assignee picker) + a divider + the
  external-email add form (`external_form`).
- On each rendered subscriber avatar and each external-email pill, add a small `×` remove button (POST
  form) when `perms.subscribe`.
- Add `"subscribe": can_manage_subscribers(current_user, ticket)` to the `perms` dict in the `detail`
  view (`detail.py:274`).

### Task B — Assignee picker width + richness (`detail.html:223-260`)

- Widen the menu: replace `style="width:300px; …"` with
  `min-width:340px; max-width:min(460px, calc(100vw - 2rem))` and stop truncating names (let the row
  grow / wrap rather than clip).
- Add a **"Search people…"** input at the top of the menu that filters the rendered rows client-side
  (vanilla JS, no AJAX — the candidate set is small and already server-rendered).
- Add a **Suggested** section with an **"Assign to me"** row when `current_user` is an eligible assigner
  in scope (appears in `convenors_in_scope`): tinted row, green rationale subline naming their in-scope
  convened class, and a `current · auto` pill when they are already the assignee. Build this in
  `_build_assign_options` (a leading `suggested` section) so the template stays declarative.
- Keep it a Bootstrap dropdown (least disruptive); the visual target is the reference 4a panel.

### Task C — Timeline colour + size (`detail.html` styles + timeline loop)

- Bump `.tk-event` `font-size:12.5px → 13px` and render the event sentence in `--bs-body-color` (actor
  already bold) instead of all-grey.
- Colour-code the two rich event kinds **in the template** (so the `avatar()` macro stays usable),
  branching on a new `item.kind` field added by `_describe_event`/`_build_timeline`:
  - **STATUS_CHANGED**: render the from/to status words as coloured `status_pill`-style chips using the
    existing `STATUS_TONE` map (`--bs-*-text-emphasis`), not plain text.
  - **ASSIGNED with a `from`** (reassignment): render inline mini avatars for the from/to users via the
    `avatar(user, 16)` macro (reference "DS → MB").
  - All other events keep the current generic `{{ item.text }}` rendering.
- Colours must use Bootstrap `--bs-*` / app semantic tokens only (per `template-colours.md`). The
  `_STATUS_EMAIL_COLOURS` hexes in the *email task* stay as literal hex (email needs it).

### Task D — Notification hygiene (no behaviour change)

- Fix the stale comment in `app/tickets/forms.py:35` and the `_notify_subscribers` "Phase 7" docstring
  in `detail.py:326` to state the fan-out is wired.
- No change to the send path. See Verification for confirming the template seed + `email_is_live`.

---

## Files to modify
- `initdb.py` — add `ticket_subscriber` to `_REQUIRED_ROLES`.
- `app/shared/tickets/permissions.py` + `app/shared/tickets/__init__.py` — `can_manage_subscribers`.
- `app/shared/tickets/subscriptions.py` — external add/remove helpers.
- `app/tickets/detail.py` — `_build_subscriber_options`, suggested/enriched `_build_assign_options`,
  new subscriber routes, `_describe_event` external + `kind`, `perms["subscribe"]`, extra context.
- `app/tickets/forms.py` — `TicketExternalSubscriberForm`; fix stale comment.
- `app/templates/tickets/detail.html` — Subscribers "+" dropdown + per-sub `×`; assignee
  width/search/suggested; timeline colour/size + status-word / reassignment rendering.

## Verification
- `ruff check .` and `ruff format --line-length 150` on touched files.
- Confirm the comment-email template is seeded/applied: verify migration
  `c2f5a8b3e6d1_seed_ticket_comment_email_template` is in the applied chain and that
  `EmailTemplate.find_template_(EmailTemplate.TICKET_COMMENT_NOTIFICATION)` returns a row. Delivery also
  requires `email_is_live` and a running Celery worker + `poll_email_workflows` beat.
- Manual, via `python serve.py` (or Docker) on a real ticket:
  1. As convenor/admin, open the Subscribers "+": add another **internal** user, a **management watcher**
     (grant a test user the `ticket_subscriber` role first via manage-users), and an **external email**;
     confirm avatars/pill appear, `×` removes them, and TicketEvents are logged.
  2. Post a comment with "Email subscribers" on and **a second subscriber present** → confirm an
     `EmailWorkflow` + one `EmailWorkflowItem` per non-commenter recipient is created (the path that
     silently no-op'd before, when self was the only subscriber).
  3. Open the assignee picker: verify no name truncation, the search box filters, and "Assign to me"
     appears for an in-scope convenor.
  4. Change status and reassign; confirm the timeline shows coloured status chips and reassignment
     mini-avatars at the larger text size.

## TODO.md follow-ups (update when this lands)
- Mark "Ticket detail (2a)" reconciliation done; note the new `ticket_subscriber` role.
- The "email subscribers didn't fire" observation is **resolved as not-a-bug** (self-only subscriber);
  subscriber management now makes it exercisable.
