# Watcher-added notification email

## Context

The ticket system already sends a `TICKET_COMMENT_NOTIFICATION` email to a ticket's subscribers
when a new comment is posted (`app/tasks/ticket_notifications.py`, one `EmailWorkflow` per
comment, one `EmailWorkflowItem` per recipient, dispatched via the existing `EmailWorkflow`
machinery). There is no equivalent email when a user is *added* as a watcher.

A design for this second email was produced in Claude Design (project
`4364862c-42f8-4bf2-a02d-30d91155c682`, "Watcher notification email design" — files `Watcher
added notification email.html` / `... - preview.html`). It follows the same visual language as
the comment-notification email and documents its token set in a header comment:
`recipient_name, adder_name, adder_initials, ticket_id, ticket_title, ticket_url,
project_class_name, status_label, status_color, status_bg, labels[], added_time, watch_note
(optional), opener_name, assignee_name, opened_date, other_watchers_count, settings_url,
unwatch_url`.

Two behavioural requirements from the brief:

1. **Delay before sending** — a ticket owner might add then immediately remove a watcher, so the
   email must not fire immediately. `EmailWorkflow.build_()` supports a deferred `send_time`, but
   it has no way to re-check "is this user still subscribed?" at dispatch time — it just holds a
   fixed recipient list. So the check has to happen in application code, not inside the
   `EmailWorkflow`/`EmailWorkflowItem` machinery itself.
2. **Bundling** — several watchers added in quick succession should produce one `EmailWorkflow`
   (one item per recipient), not one workflow per add.

Resolved via a **trailing-edge debounce**, persisted rather than an in-memory
`apply_async(countdown=...)` call (which would be lost on a broker/worker restart): each qualifying
add deletes any existing `DatabaseSchedulerEntry`/`CrontabSchedule` row for the ticket and replaces
it with one 10 minutes in the future, mirroring the existing
`app.tasks.markingevent.schedule_close_marking_window` / `close_marking_window` pattern (a one-shot
crontab pinned to the exact target minute, `expires` shortly after, and the task deletes its own
row on execution). Because there is only ever one entry per ticket at a time, there is no
accumulation of no-op scheduled tasks from a burst of adds — the entry just keeps getting replaced
until the ticket goes quiet. When the task does fire, it re-reads `TicketSubscription` directly, so
anyone unsubscribed in the meantime (row deleted) is automatically excluded — no separate "is still
subscribed" flag needed.

The brief also flags that both this email and the existing comment-notification email need a real
`unsubscribe_url` (currently a placeholder) and asks for a click-through unsubscribe endpoint.
Per user decision: `settings_url` keeps pointing at the ticket inbox (no notification-preferences
feature exists or is being added), and the optional `watch_note` block is left unpopulated for now
(no UI exists to author it, and adding one is out of scope for this change) — the `{% if
watch_note %}` guard in the template just means it never renders.

## Data model changes

`app/models/tickets.py` — `TicketSubscription`: add

- `added_by_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True, index=True)`
  + `added_by` relationship — who performed the add (None for self-subscribe / auto reasons).
- `notify_pending = db.Column(db.Boolean(), nullable=False, default=False)` — set when this
  subscription still needs its "you were added" email; cleared once queued.

No new column on `Ticket` — the debounce "fire no earlier than" state lives entirely in the
persisted `DatabaseSchedulerEntry`/`CrontabSchedule` rows described below (see "Deferred dispatch
+ bundling"), not on the ticket itself.

Hand-written Alembic migration (chain tip is `c3d9e2f6a1b4`, verified via the `comm -23 ...`
command from CLAUDE.md): revision `1b7da3a8b14b`, `down_revision = "c3d9e2f6a1b4"`, adding the two
`ticket_subscriptions` columns with `op.add_column`/`op.create_index`/`op.create_foreign_key`, and
a matching `downgrade()`. The `celery_crontabs`/`celery_schedules` tables used below already exist
(seeded by `e2774dca7471_reset_initial_migration_point.py`) — nothing new needed for those.

`app/models/emails.py` (`EmailTemplateTypesMixin`): add `TICKET_WATCHER_ADDED_NOTIFICATION = 74`
(next free value after `TICKET_COMMENT_NOTIFICATION = 73`) and its `_TYPE_NAMES` entry ("Ticket:
Watcher added notification").

Second migration, revision `772a611e3122`, `down_revision = "1b7da3a8b14b"`: seeds the
`email_templates` row for type 74, following exactly the pattern of
`migrations/versions/c2f5a8b3e6d1_seed_ticket_comment_email_template.py` (raw `INSERT`, `active`,
`comment`, `version=1`, global i.e. `tenant_id`/`pclass_id` NULL). Subject line e.g. `"You were
added as a watcher on ticket #{ticket_id} — {ticket_title}"` (`str.format` style, matching the
existing subject convention). HTML body is the Claude Design HTML from `Watcher added
notification email.html`, adapted to reuse real values for `settings_url`/`unwatch_url` (Jinja
tokens, unchanged) and `{{ branding_label }}` (already a token in the design).

## Deferred dispatch + bundling: persisted `DatabaseSchedulerEntry`, not `apply_async(countdown=...)`

An in-memory `apply_async(countdown=...)` call is lost if the broker/worker restarts before it
fires, and re-enqueuing on every add (as an early version of this plan did) accumulates redundant
scheduled tasks that mostly turn out to be no-ops. Instead this mirrors an existing pattern in the
codebase — `app.tasks.markingevent.schedule_close_marking_window` /
`close_marking_window`, and the reschedule-on-clear snippet in
`app/convenor/markingevent.py` — which persists a one-shot schedule as a `CrontabSchedule` pinned
to the exact target minute/hour/day/month, wrapped in a `DatabaseSchedulerEntry` row picked up by
the database-backed Celery Beat scheduler (`app.sqlalchemy_scheduler.DatabaseScheduler`, already
running per `CLAUDE.md`'s dev commands). Because Celery Beat polls `celery_schedules` for changes
(`DatabaseSchedulerEntry.date_changed`, bumped by a `before_insert` listener) rather than needing
an explicit signal, committing the session is enough for Beat to pick up a new/replaced entry on
its next tick.

`app/shared/tickets/subscriptions.py` — extend `subscribe(ticket, user, reason=MANUAL, actor=None)`:

- Always set `added_by_id = actor.id if actor is not None else None` on newly-created rows.
- When `reason == TicketSubscription.MANUAL and actor is not None and actor.id != user.id` (i.e.
  a deliberate "someone else added this person" action — this is exactly the `subscriber_add()`
  route path; it naturally excludes self-subscribe via `watch()` (`actor == user`), assignment
  (`reason == ASSIGNEE`), ticket-open auto-subscribe of opener/assignee, and convenor auto-sync
  (`reason == CONVENOR`, `actor` typically `None`)):
  - set `notify_pending = True` on the new subscription
  - call a new `_schedule_watcher_notification_check(ticket)` helper

`_schedule_watcher_notification_check(ticket)`:

1. Query `DatabaseSchedulerEntry` for an existing row whose `name` matches
   `f"watcher_notify_ticket{ticket.id}_%"`. If found, delete it and its linked `CrontabSchedule`
   (mirrors the `app/convenor/markingevent.py` reschedule snippet) — this is the "push out by 10
   minutes" behaviour: any existing entry is always replaced, never left in place.
2. Compute `target = datetime.now() + WATCHER_NOTIFICATION_DELAY` (module constant,
   `timedelta(minutes=10)`).
3. Create a `CrontabSchedule(minute=str(target.minute), hour=str(target.hour),
   day_of_month=str(target.day), month_of_year=str(target.month))` (day_of_week left at its `"*"`
   default — the other four fields already pin an exact instant), `flush()` to materialise its id.
4. Create a `DatabaseSchedulerEntry(name=f"watcher_notify_ticket{ticket.id}_{target:%Y%m%d%H%M}",
   task="app.tasks.ticket_notifications.check_watcher_notifications", crontab_id=crontab.id,
   expires=target + timedelta(hours=1), enabled=True)`, `flush()` to materialise its id, then set
   `entry.args = [ticket.id, entry.id]` (the entry needs its own id so the task can self-delete it).

Because step 1 always deletes any pre-existing entry before step 4 creates a new one, there is only
ever one entry per ticket at a time — no accumulation of no-op scheduled tasks from a burst of
adds, and each add genuinely pushes the fire time out rather than racing a stale earlier task.

`unsubscribe()` is already correct as-is: deleting the row is sufficient to drop any pending
notification for that user — no extra bookkeeping needed. None of this commits — the caller
(`subscribe()`'s caller) owns the transaction, so the subscription row, the notify_pending flag,
and the scheduler entry all land together in one commit.

## Celery task: `app/tasks/ticket_notifications.py`

Add `check_watcher_notifications(self, ticket_id, scheduler_entry_id)` (the extra arg is how the
task finds its own scheduler row to delete), registered from the same
`register_ticket_notification_tasks(celery)` factory (already the single call site wired in
`app/__init__.py`):

```python
def check_watcher_notifications(self, ticket_id, scheduler_entry_id):
    # self-cleanup: remove this one-shot scheduler entry and its crontab (mirrors
    # close_marking_window) — non-fatal on failure, logged and processing continues
    entry_row = db.session.query(DatabaseSchedulerEntry).filter_by(id=scheduler_entry_id).first()
    if entry_row is not None:
        crontab_id = entry_row.crontab_id
        db.session.delete(entry_row)
        if crontab_id is not None:
            crontab = db.session.query(CrontabSchedule).filter_by(id=crontab_id).first()
            if crontab is not None:
                db.session.delete(crontab)

    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return

    pending = list(ticket.subscriptions.filter_by(notify_pending=True))
    if not pending:
        db.session.commit()
        return

    # build one EmailWorkflow, one EmailWorkflowItem per still-pending recipient, using
    # `pending[i].added_by` / `.created_at` for adder_name/adder_initials/added_time — same
    # shared/per-recipient split as send_ticket_comment_notifications.
    ...
    for sub in pending:
        sub.notify_pending = False
    log_db_commit(f"Queued watcher-added notifications for ticket #{ticket.id} ...", ...)
```

There is no "is this firing stale?" check any more (an earlier version of this plan compared
against a `Ticket.watcher_notification_check_at` timestamp) — because `_schedule_watcher_notification_check`
always deletes any existing entry before creating a new one, there is only ever one live entry per
ticket, so every firing is the intended one. (A rare race between two near-simultaneous
`subscribe()` calls could in principle leave two entries; the first to fire would already pick up
every currently-`notify_pending` row, so the second just finds nothing pending and self-deletes as
a harmless no-op — graceful degradation, not a correctness issue.)

Shared body fields: `ticket_id`, `ticket_title`, `ticket_url` (`url_for("tickets.detail", ...,
_external=True)` — safe to call directly in the task since `celery_node.py` pushes an app context
and `SERVER_NAME` is configured), `project_class_name`, `status_label/color/bg` (reuse
`_STATUS_EMAIL_COLOURS`), `labels[]`, `opener_name` (`ticket.created_by.name`), `assignee_name`,
`opened_date` (`ticket.creation_timestamp`), `other_watchers_count`
(`ticket.subscriptions.count() - 1`), `settings_url` (`url_for("tickets.inbox", _external=True)`),
`watch_note` (`None`, per the scope decision above).

Per-recipient fields (one `EmailWorkflowItem` each, `recipient_list=[user.email]`):
`recipient_name`, `adder_name`/`adder_initials` (from `sub.added_by`, falling back to "Someone"/"?"
if somehow `None`), `added_time` (`sub.created_at`), `unwatch_url` (see below).

Skip recipients with no email, same guard as the comment-notification task.

## Unsubscribe endpoint (used by both emails)

New helpers in `app/shared/tickets/subscriptions.py`:

```python
_UNSUB_SALT = "ticket-unsubscribe"

def make_unsubscribe_token(ticket, *, user=None, email=None) -> str:
    s = URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_UNSUB_SALT)
    payload = {"t": ticket.id, "u": user.id} if user is not None else {"t": ticket.id, "e": email}
    return s.dumps(payload)

def resolve_unsubscribe_token(token) -> Optional[dict]:
    s = URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_UNSUB_SALT)
    try:
        return s.loads(token)
    except BadSignature:
        return None
```

(No expiry — `URLSafeSerializer`, not `URLSafeTimedSerializer`: these links should stay valid for
the life of the ticket. Signed with the app's existing `SECRET_KEY`, no new secret to manage —
mirrors how Flask-Security signs its own tokens.)

New route in `app/tickets/detail.py` (or a small new `app/tickets/unsubscribe.py` module wired
into `app/tickets/__init__.py` alongside the other view modules — cleaner given it's a
self-contained unauthenticated flow):

```python
@tickets.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe_link(token):
    payload = resolve_unsubscribe_token(token)
    if payload is None:
        abort(404)
    ticket = Ticket.query.get(payload["t"])
    if ticket is None:
        abort(404)

    if "u" in payload:
        target = User.query.get(payload["u"])
        already_out = target is None or not is_subscribed(target, ticket)
    else:
        target = None
        external = ticket.external_subscribers.filter_by(email=payload["e"]).first()
        already_out = external is None

    form = ConfirmActionForm()
    if form.validate_on_submit():
        if target is not None:
            unsubscribe(ticket, target, actor=target)
        elif external is not None:
            remove_external_subscriber(ticket, external, actor=None)
        _commit_unsubscribe(...)   # log_db_commit + rollback/flash, same shape as _commit_or_flash
        already_out = True

    return render_template_context("tickets/unsubscribe.html", ticket=ticket, already_out=already_out, form=form)
```

No `@login_required` — this route must work for a recipient who is not logged in. It does not sit
behind the blueprint's normal navigation chrome.

Template `app/templates/tickets/unsubscribe.html`: extends `security/index.html` (the same
unauthenticated card layout used by `security/reset_password.html` etc. — already proven to work
pre-login via `render_template_context`), shows the ticket title, and either a "You're
unsubscribed" confirmation or a single-button `ConfirmActionForm` ("Stop watching this ticket").

Wire this into both email tasks:

- `send_ticket_comment_notifications`: replace the current `"unsubscribe_url": ticket_url`
  placeholder. Since the token is per-recipient (keyed by user id or external email), move
  `unsubscribe_url` out of `shared` into the per-recipient payload, generated via
  `make_unsubscribe_token(ticket, user=user)` for internal subscribers and
  `make_unsubscribe_token(ticket, email=address)` for external ones.
- `check_watcher_notifications`: per-recipient `unwatch_url =
  url_for("tickets.unsubscribe_link", token=make_unsubscribe_token(ticket, user=user), _external=True)`.

`settings_url` in both tasks stays `url_for("tickets.inbox", _external=True)`, unchanged.

## Verification

- `ruff check` / `ruff format --line-length 150` over the touched files.
- Manual DB check after writing the migrations: confirm the `comm -23 ...` chain-tip command now
  returns `772a611e3122`, and `grep` for both new revision ids returns only the new files.
- Exercise the flow in a running dev stack (`./restart.sh` or `serve.py` + a Celery worker **and**
  Celery Beat running with `--scheduler app.sqlalchemy_scheduler:DatabaseScheduler`, per
  `CLAUDE.md`'s dev commands — Beat is what actually fires the persisted entry):
  1. Add a watcher to a ticket via the UI (`subscriber_add`) as a different user than the target;
     confirm a `celery_schedules` row named `watcher_notify_ticket<id>_...` appears (linked to a
     `celery_crontabs` row pinned ~10 minutes out).
  2. Add a second watcher within the 10-minute window; confirm the first `celery_schedules` row is
     deleted and replaced by a new one ~10 minutes from the *second* add, and that only one
     `EmailWorkflow` (with two items) is eventually created, not two.
  3. Remove one of the two watchers before the debounce fires; confirm only the remaining one gets
     an `EmailWorkflowItem`, and that both the `celery_schedules` and `celery_crontabs` rows are
     gone after it fires (self-cleanup).
  4. Let the task fire; inspect the rendered email (via the admin email-workflow viewer, if one
     exists, or by reading the `EmailWorkflowItem.body_payload`) against the Claude Design preview.
  5. Click an `unwatch_url` from a rendered payload while logged out; confirm it unsubscribes and
     shows the confirmation page, and that a second click is idempotent (already-unsubscribed
     state, no error).
  6. Confirm `send_ticket_comment_notifications`'s `unsubscribe_url` now resolves through the same
     endpoint for an existing ticket's subscriber.
