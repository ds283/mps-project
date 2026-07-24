#
# Created by David Seery on 21/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Subscriber (watcher) helpers for the ticket service layer. Subscriptions drive the "Watching" view
and the email fan-out. Auto-added subscribers: the opener, the assignee, and (on routing) the
in-scope convenor(s). None of these functions commit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from ...database import db
from ...models import CrontabSchedule, DatabaseSchedulerEntry, TicketEvent, TicketExternalSubscriber, TicketSubscription
from .events import record_event
from .scope import convenors_in_scope

# debounce delay for the watcher-added notification fan-out: each qualifying subscribe() call
# (re)schedules check_watcher_notifications this far in the future, so a burst of adds is bundled
# into a single dispatch once the ticket goes quiet. See _schedule_watcher_notification_check().
WATCHER_NOTIFICATION_DELAY = timedelta(minutes=10)

# name prefix for the persisted DatabaseSchedulerEntry backing the watcher-notification debounce
# for a given ticket — used both to find/replace the existing entry and to build a fresh one.
_WATCHER_NOTIFICATION_TASK = "app.tasks.ticket_notifications.check_watcher_notifications"

# salt for the unsubscribe-link token (see make_unsubscribe_token / resolve_unsubscribe_token) —
# signed with the app's existing SECRET_KEY, no separate secret to manage.
_UNSUBSCRIBE_TOKEN_SALT = "ticket-unsubscribe"


def is_subscribed(user, ticket) -> bool:
    if user is None:
        return False
    return ticket.subscriptions.filter_by(user_id=user.id).first() is not None


def subscribe(ticket, user, reason: int = TicketSubscription.MANUAL, actor=None) -> Optional[TicketSubscription]:
    """
    Subscribe a user to a ticket. Idempotent: if the user is already subscribed, the existing
    subscription (and its original reason) is preserved and returned — notify_pending is only ever
    set on a newly-created row, never re-triggered here.

    When this is a deliberate "someone else added this person" action (reason=MANUAL and actor is
    a different user from the one being subscribed — i.e. not a self-subscribe via watch(), an
    auto-subscribe of the opener/assignee, or convenor auto-sync), the new subscription is flagged
    notify_pending=True and the deferred watcher-notification check for this ticket is (re)scheduled
    WATCHER_NOTIFICATION_DELAY from now. See _schedule_watcher_notification_check().
    """
    if user is None:
        return None

    existing = ticket.subscriptions.filter_by(user_id=user.id).first()
    if existing is not None:
        return existing

    subscription = TicketSubscription(
        ticket=ticket,
        user_id=user.id,
        reason=reason,
        created_at=datetime.now(),
        added_by_id=(actor.id if actor is not None else None),
    )
    db.session.add(subscription)

    if reason == TicketSubscription.MANUAL and actor is not None and actor.id != user.id:
        subscription.notify_pending = True
        _schedule_watcher_notification_check(ticket)

    record_event(ticket, actor if actor is not None else user, TicketEvent.SUBSCRIBED, {"user": user.id, "reason": reason})
    return subscription


def _schedule_watcher_notification_check(ticket) -> None:
    """
    (Re)schedule the deferred watcher-added-notification check for a ticket, persisted as a
    DatabaseSchedulerEntry backed by a one-shot CrontabSchedule (picked up by the database-backed
    Celery Beat scheduler, app.sqlalchemy_scheduler.DatabaseScheduler) rather than an in-memory
    apply_async(countdown=...) call — this survives a broker/worker restart, unlike a plain Celery
    countdown task. Mirrors app.tasks.markingevent.schedule_close_marking_window /
    app.convenor.markingevent's reschedule-on-clear snippet.

    Any existing entry for this ticket is deleted and replaced with one WATCHER_NOTIFICATION_DELAY
    from now, so a burst of adds keeps pushing the fire time out — there is only ever one entry per
    ticket at a time, so no accumulation of redundant/no-op scheduled tasks. The task itself
    (app.tasks.ticket_notifications.check_watcher_notifications) deletes its own entry and crontab
    on execution.

    Does not commit — the caller (subscribe()'s caller) owns the transaction.
    """
    existing = db.session.query(DatabaseSchedulerEntry).filter(DatabaseSchedulerEntry.name.like(f"watcher_notify_ticket{ticket.id}_%")).first()
    if existing is not None:
        crontab_id = existing.crontab_id
        db.session.delete(existing)
        if crontab_id is not None:
            crontab = db.session.query(CrontabSchedule).filter_by(id=crontab_id).first()
            if crontab is not None:
                db.session.delete(crontab)
        db.session.flush()

    target = datetime.now() + WATCHER_NOTIFICATION_DELAY

    crontab = CrontabSchedule(
        minute=str(target.minute),
        hour=str(target.hour),
        day_of_month=str(target.day),
        month_of_year=str(target.month),
    )
    db.session.add(crontab)
    db.session.flush()  # materialise crontab.id

    entry = DatabaseSchedulerEntry(
        name=f"watcher_notify_ticket{ticket.id}_{target.strftime('%Y%m%d%H%M')}",
        task=_WATCHER_NOTIFICATION_TASK,
        crontab_id=crontab.id,
        expires=target + timedelta(hours=1),
        enabled=True,
    )
    db.session.add(entry)
    db.session.flush()  # materialise entry.id so we can pass it as an arg

    entry.args = [ticket.id, entry.id]


def make_unsubscribe_token(ticket, *, user=None, email: Optional[str] = None) -> str:
    """
    Build a signed, non-expiring token identifying (ticket, recipient) for the one-click
    unsubscribe link carried in notification emails. Exactly one of `user` / `email` must be
    supplied — `user` for an internal subscriber, `email` for an external one.
    """
    if (user is None) == (email is None):
        raise RuntimeError("make_unsubscribe_token(): exactly one of user or email must be supplied")

    serializer = URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_UNSUBSCRIBE_TOKEN_SALT)
    payload = {"t": ticket.id, "u": user.id} if user is not None else {"t": ticket.id, "e": email}
    return serializer.dumps(payload)


def resolve_unsubscribe_token(token: str) -> Optional[dict]:
    """
    Decode a token produced by make_unsubscribe_token(), or return None if it is missing/invalid.
    """
    serializer = URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_UNSUBSCRIBE_TOKEN_SALT)
    try:
        return serializer.loads(token)
    except BadSignature:
        return None


def unsubscribe(ticket, user, actor=None) -> None:
    if user is None:
        return

    subscription = ticket.subscriptions.filter_by(user_id=user.id).first()
    if subscription is None:
        return

    db.session.delete(subscription)
    record_event(ticket, actor if actor is not None else user, TicketEvent.UNSUBSCRIBED, {"user": user.id})


def sync_convenor_subscriptions(ticket, actor=None) -> None:
    """Ensure every in-scope convenor is subscribed (reason = convenor). Idempotent."""
    for user in convenors_in_scope(ticket):
        subscribe(ticket, user, reason=TicketSubscription.CONVENOR, actor=actor)


def add_external_subscriber(ticket, email: str, actor=None) -> Optional[TicketExternalSubscriber]:
    """
    Subscribe an external (non-User) email address to a ticket. Idempotent: if the address is
    already subscribed, the existing row is returned unchanged.
    """
    if not email:
        return None
    email = email.strip()
    if not email:
        return None

    existing = ticket.external_subscribers.filter_by(email=email).first()
    if existing is not None:
        return existing

    external = TicketExternalSubscriber(ticket=ticket, email=email, created_at=datetime.now())
    db.session.add(external)
    record_event(ticket, actor, TicketEvent.SUBSCRIBED, {"email": email})
    return external


def remove_external_subscriber(ticket, external: TicketExternalSubscriber, actor=None) -> None:
    if external is None:
        return

    email = external.email
    db.session.delete(external)
    record_event(ticket, actor, TicketEvent.UNSUBSCRIBED, {"email": email})
