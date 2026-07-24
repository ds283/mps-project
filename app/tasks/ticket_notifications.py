#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Ticket notification fan-out. When a comment is posted (and the author asked to notify), the detail
view enqueues send_ticket_comment_notifications, which builds a single EmailWorkflow container with
one EmailWorkflowItem per recipient (every subscriber except the commenter, plus external
addresses). Actual delivery is handled by the EmailWorkflow machinery (poll_email_workflows /
send_workflow_item) — this task never sends email itself. Outbound only; there is no inbound path.

check_watcher_notifications is the deferred half of the "you were added as a watcher" email: the
ticket service layer's subscribe() (app/shared/tickets/subscriptions.py) persists a one-shot
DatabaseSchedulerEntry/CrontabSchedule targeting this task WATCHER_NOTIFICATION_DELAY in the
future every time a qualifying subscription is created — replacing (pushing out) any existing
entry for the same ticket, so a burst of adds is bundled into a single dispatch and there is never
more than one entry (and hence one eventual firing) pending per ticket. See
_schedule_watcher_notification_check() there for the persisted-scheduler rationale.
"""

from datetime import datetime

from flask import current_app, url_for
from markupsafe import escape
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    CrontabSchedule,
    DatabaseSchedulerEntry,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    Ticket,
    TicketComment,
    TicketSubscription,
    User,
    encode_email_payload,
)
from ..shared.colours import get_text_colour
from ..shared.tickets.subscriptions import make_unsubscribe_token
from ..shared.workflow_logging import log_db_commit

# email-safe status colours (text, background) — hex, since this is an HTML email
_STATUS_EMAIL_COLOURS = {
    Ticket.OPEN: ("#0a58ca", "#cfe2ff"),
    Ticket.IN_PROGRESS: ("#997404", "#fff3cd"),
    Ticket.RESOLVED: ("#0f5132", "#d1e7dd"),
    Ticket.CLOSED: ("#41464b", "#e2e3e5"),
}

_REASON_TEXT = {
    TicketSubscription.OPENER: "the opener",
    TicketSubscription.ASSIGNEE: "the assignee",
    TicketSubscription.CONVENOR: "a convenor",
    TicketSubscription.MANUAL: "subscribed",
}


def register_ticket_notification_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def send_ticket_comment_notifications(self, ticket_id, comment_id, actor_id, ticket_url, settings_url):
        ticket = Ticket.query.get(ticket_id)
        comment = TicketComment.query.get(comment_id)
        if ticket is None or comment is None:
            return

        commenter = User.query.get(actor_id) if actor_id is not None else None

        # recipients: internal subscribers (except the commenter) + external addresses. The
        # unsubscribe token is per-recipient (keyed by user id or external email), so it is built
        # here rather than in the shared body fields below.
        recipients = []
        for subscription in ticket.subscriptions:
            user = subscription.user
            if user is None or user.id == actor_id or not user.email:
                continue
            unsubscribe_url = url_for("tickets.unsubscribe_link", token=make_unsubscribe_token(ticket, user=user), _external=True)
            recipients.append((user.email, user.name, _REASON_TEXT.get(subscription.reason, "subscribed"), unsubscribe_url))
        for external in ticket.external_subscribers:
            if external.email:
                unsubscribe_url = url_for("tickets.unsubscribe_link", token=make_unsubscribe_token(ticket, email=external.email), _external=True)
                recipients.append((external.email, external.email, "subscribed", unsubscribe_url))

        if not recipients:
            return

        template = EmailTemplate.find_template_(EmailTemplate.TICKET_COMMENT_NOTIFICATION, tenant=ticket.tenant)
        if template is None:
            current_app.logger.error("send_ticket_comment_notifications: TICKET_COMMENT_NOTIFICATION template not seeded")
            return

        pclasses = list(ticket.scope_classes)
        workflow = EmailWorkflow.build_(
            name=f"Ticket #{ticket.id} — new comment",
            template=template,
            send_time=datetime.now(),
            pclasses=pclasses or None,
            creator=commenter,
        )
        db.session.add(workflow)
        db.session.flush()

        # shared body fields (identical for every recipient)
        status_color, status_bg = _STATUS_EMAIL_COLOURS.get(ticket.status, ("#41464b", "#e2e3e5"))
        shared = {
            "commenter_name": commenter.name if commenter is not None else "Someone",
            "commenter_initials": commenter.initials if commenter is not None else "?",
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "ticket_url": ticket_url,
            "project_class_name": ", ".join(sorted(pclass.name for pclass in pclasses)) or "General",
            "status_label": Ticket._labels.get(ticket.status, "Unknown"),
            "status_color": status_color,
            "status_bg": status_bg,
            "comment_html": str(escape(comment.body or "")).replace("\n", "<br>"),
            "comment_time": comment.created_at.strftime("%d %b %Y, %H:%M") if comment.created_at else "",
            "labels": [{"name": label.name, "bg": label.colour, "fg": get_text_colour(label.colour)} for label in ticket.labels],
            "settings_url": settings_url,
            "is_email_reply": False,
        }
        subject_payload = encode_email_payload({"ticket_id": ticket.id, "ticket_title": ticket.title})

        for address, name, reason, unsubscribe_url in recipients:
            body_payload = encode_email_payload({**shared, "recipient_name": name, "subscribe_reason": reason, "unsubscribe_url": unsubscribe_url})
            item = EmailWorkflowItem.build_(
                subject_payload=subject_payload,
                body_payload=body_payload,
                recipient_list=[address],
                creator=commenter,
            )
            item.workflow = workflow
            db.session.add(item)

        try:
            log_db_commit(
                f"Queued comment notifications for ticket #{ticket.id} ({len(recipients)} recipient(s))",
                user=commenter,
                project_classes=pclasses,
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("send_ticket_comment_notifications: failed to queue workflow", exc_info=exc)

    @celery.task(bind=True, default_retry_delay=30)
    def check_watcher_notifications(self, ticket_id, scheduler_entry_id):
        """
        Fired once by the database-backed Celery Beat scheduler (see
        app.shared.tickets.subscriptions._schedule_watcher_notification_check),
        WATCHER_NOTIFICATION_DELAY after the most recent qualifying subscribe() call for this
        ticket. Deletes its own one-shot DatabaseSchedulerEntry/CrontabSchedule on execution (to
        avoid accumulation of one-off schedule rows — mirrors close_marking_window), then
        dispatches a single EmailWorkflow (one item per still-subscribed recipient) for every
        TicketSubscription still flagged notify_pending.
        """
        # self-cleanup: remove this one-shot scheduler entry and its crontab
        try:
            entry_row = db.session.query(DatabaseSchedulerEntry).filter_by(id=scheduler_entry_id).first()
            if entry_row is not None:
                crontab_id = entry_row.crontab_id
                db.session.delete(entry_row)
                if crontab_id is not None:
                    crontab = db.session.query(CrontabSchedule).filter_by(id=crontab_id).first()
                    if crontab is not None:
                        db.session.delete(crontab)
        except SQLAlchemyError as exc:
            current_app.logger.exception(f"check_watcher_notifications: could not delete scheduler entry #{scheduler_entry_id}", exc_info=exc)
            # non-fatal — continue processing

        ticket = Ticket.query.get(ticket_id)
        if ticket is None:
            return

        pending = list(ticket.subscriptions.filter_by(notify_pending=True))
        if not pending:
            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.exception("check_watcher_notifications: failed to commit", exc_info=exc)
            return

        template = EmailTemplate.find_template_(EmailTemplate.TICKET_WATCHER_ADDED_NOTIFICATION, tenant=ticket.tenant)
        if template is None:
            current_app.logger.error("check_watcher_notifications: TICKET_WATCHER_ADDED_NOTIFICATION template not seeded")
            return

        for sub in pending:
            sub.notify_pending = False
        recipients = [sub for sub in pending if sub.user is not None and sub.user.email]

        if not recipients:
            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.exception("check_watcher_notifications: failed to commit", exc_info=exc)
            return

        pclasses = list(ticket.scope_classes)
        workflow = EmailWorkflow.build_(
            name=f"Ticket #{ticket.id} — watcher(s) added",
            template=template,
            send_time=datetime.now(),
            pclasses=pclasses or None,
            creator=None,
        )
        db.session.add(workflow)
        db.session.flush()

        # shared body fields (identical for every recipient)
        status_color, status_bg = _STATUS_EMAIL_COLOURS.get(ticket.status, ("#41464b", "#e2e3e5"))
        ticket_url = url_for("tickets.detail", ticket_id=ticket.id, _external=True)
        settings_url = url_for("tickets.inbox", _external=True)
        shared = {
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "ticket_url": ticket_url,
            "project_class_name": ", ".join(sorted(pclass.name for pclass in pclasses)) or "General",
            "status_label": Ticket._labels.get(ticket.status, "Unknown"),
            "status_color": status_color,
            "status_bg": status_bg,
            "labels": [{"name": label.name, "bg": label.colour, "fg": get_text_colour(label.colour)} for label in ticket.labels],
            "opener_name": ticket.created_by.name if ticket.created_by is not None else "Unknown",
            "assignee_name": ticket.assignee.name if ticket.assignee is not None else "Unassigned",
            "opened_date": ticket.creation_timestamp.strftime("%d %b %Y") if ticket.creation_timestamp else "",
            "other_watchers_count": max(ticket.subscriptions.count() - 1, 0),
            "settings_url": settings_url,
            "watch_note": None,
        }
        subject_payload = encode_email_payload({"ticket_id": ticket.id, "ticket_title": ticket.title})

        for sub in recipients:
            user = sub.user
            adder = sub.added_by
            unwatch_url = url_for("tickets.unsubscribe_link", token=make_unsubscribe_token(ticket, user=user), _external=True)
            body_payload = encode_email_payload(
                {
                    **shared,
                    "recipient_name": user.name,
                    "adder_name": adder.name if adder is not None else "Someone",
                    "adder_initials": adder.initials if adder is not None else "?",
                    "added_time": sub.created_at.strftime("%d %b %Y, %H:%M") if sub.created_at else "",
                    "unwatch_url": unwatch_url,
                }
            )
            item = EmailWorkflowItem.build_(
                subject_payload=subject_payload,
                body_payload=body_payload,
                recipient_list=[user.email],
                creator=adder,
            )
            item.workflow = workflow
            db.session.add(item)

        try:
            log_db_commit(
                f"Queued watcher-added notifications for ticket #{ticket.id} ({len(recipients)} recipient(s))",
                user=None,
                project_classes=pclasses,
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("check_watcher_notifications: failed to queue workflow", exc_info=exc)

    return send_ticket_comment_notifications
