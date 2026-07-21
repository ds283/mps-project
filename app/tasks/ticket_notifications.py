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
"""

from datetime import datetime

from flask import current_app
from markupsafe import escape
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
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

        # recipients: internal subscribers (except the commenter) + external addresses
        recipients = []
        for subscription in ticket.subscriptions:
            user = subscription.user
            if user is None or user.id == actor_id or not user.email:
                continue
            recipients.append((user.email, user.name, _REASON_TEXT.get(subscription.reason, "subscribed")))
        for external in ticket.external_subscribers:
            if external.email:
                recipients.append((external.email, external.email, "subscribed"))

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
            "unsubscribe_url": ticket_url,
            "is_email_reply": False,
        }
        subject_payload = encode_email_payload({"ticket_id": ticket.id, "ticket_title": ticket.title})

        for address, name, reason in recipients:
            body_payload = encode_email_payload({**shared, "recipient_name": name, "subscribe_reason": reason})
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

    return send_ticket_comment_notifications
