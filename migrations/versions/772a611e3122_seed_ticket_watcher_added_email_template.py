#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""seed ticket watcher-added notification EmailTemplate

Revision ID: 772a611e3122
Revises: 1b7da3a8b14b
Create Date: 2026-07-24

Seeds the global EmailTemplate (type 74, TICKET_WATCHER_ADDED_NOTIFICATION) sent to a user when
they are added as a watcher on a ticket. Tokens are filled by
app/tasks/ticket_notifications.py:check_watcher_notifications at send time:
    recipient_name, adder_name, adder_initials, ticket_id, ticket_title, ticket_url,
    project_class_name, status_label, status_color, status_bg, labels[] (name/fg/bg), added_time,
    watch_note (always None for now — no UI exists to author it), opener_name, assignee_name,
    opened_date, other_watchers_count, settings_url, unwatch_url

Companion to c2f5a8b3e6d1 (TICKET_COMMENT_NOTIFICATION) — same visual language.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "772a611e3122"
down_revision = "1b7da3a8b14b"
branch_labels = None
depends_on = None

_INSERT = (
    "INSERT INTO email_templates "
    "(active, type, subject, html_body, comment, version, "
    " tenant_id, pclass_id, last_used, "
    " creation_timestamp, last_edit_timestamp, creator_id, last_edit_id) "
    "VALUES (:active, :type, :subject, :html_body, :comment, :version, "
    " NULL, NULL, NULL, "
    " :creation_timestamp, NULL, NULL, NULL)"
)

_SUBJECT = "You were added as a watcher on ticket #{ticket_id} — {ticket_title}"

_BODY = """\
<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>You were added as a watcher on ticket #{{ ticket_id }}</title>
</head>
<body style="margin:0;padding:0;background:#f4f2ec;-webkit-font-smoothing:antialiased;">
<span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;mso-hide:all;">{{ adder_name }} added you as a watcher on #{{ ticket_id }} &mdash; {{ ticket_title }}</span>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f4f2ec;">
<tr><td align="center" style="padding:24px 12px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="600" style="width:600px;max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e6e2d6;font-family:Helvetica,Arial,sans-serif;">

    <!-- header -->
    <tr><td style="background:#212529;padding:16px 24px;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>
        <td style="font-family:'Roboto',Helvetica,Arial,sans-serif;font-weight:300;font-size:18px;color:#ffffff;">{{ branding_label }}</td>
        <td align="right" style="font-size:12px;color:rgba(255,255,255,.55);">Ticket&nbsp;#{{ ticket_id }}</td>
      </tr></table>
    </td></tr>

    <!-- headline strip -->
    <tr><td style="padding:18px 24px 0;">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="width:34px;vertical-align:top;">
          <div style="width:34px;height:34px;border-radius:8px;background:#e7f1ff;text-align:center;line-height:34px;font-size:16px;color:#0d6efd;">&#128065;</div>
        </td>
        <td style="padding-left:12px;">
          <div style="font-size:16px;line-height:1.35;font-weight:700;color:#1a1a1a;">You&rsquo;re now watching this ticket</div>
          <div style="font-size:13px;line-height:1.5;color:#6c757d;margin-top:2px;"><strong style="color:#334;">{{ adder_name }}</strong> added you as a watcher{% if watch_note %}.{% else %} &middot; {{ added_time }}{% endif %}</div>
        </td>
      </tr></table>
    </td></tr>

    <!-- context strip -->
    <tr><td style="padding:14px 24px 0;">
      <div style="font-size:12px;color:#8a94a3;">{{ project_class_name }}</div>
      <div style="font-size:19px;line-height:1.35;font-weight:700;color:#1a1a1a;margin-top:4px;">{{ ticket_title }}</div>
      <div style="margin-top:10px;">
        <span style="display:inline-block;padding:3px 11px;border-radius:20px;font-size:12px;font-weight:600;background:{{ status_bg }};color:{{ status_color }};">{{ status_label }}</span>
        {% for label in labels %}<span style="display:inline-block;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:600;background:{{ label.bg }};color:{{ label.fg }};margin-left:4px;">{{ label.name }}</span>{% endfor %}
      </div>
    </td></tr>

    <!-- ticket summary card -->
    <tr><td style="padding:18px 24px 6px;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #e6e2d6;border-radius:10px;overflow:hidden;">
        <tr><td style="background:#faf8f2;border-bottom:1px solid #efeade;padding:10px 14px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:#8a94a3;">Ticket at a glance</td></tr>
        <tr><td style="padding:4px 16px 6px;">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="font-size:13px;color:#343a40;">
            <tr>
              <td style="padding:8px 0;width:34%;color:#8a94a3;border-bottom:1px solid #f1eee4;">Opened by</td>
              <td style="padding:8px 0;border-bottom:1px solid #f1eee4;"><strong>{{ opener_name }}</strong></td>
            </tr>
            <tr>
              <td style="padding:8px 0;color:#8a94a3;border-bottom:1px solid #f1eee4;">Assigned to</td>
              <td style="padding:8px 0;border-bottom:1px solid #f1eee4;">{{ assignee_name }}</td>
            </tr>
            <tr>
              <td style="padding:8px 0;color:#8a94a3;">Opened</td>
              <td style="padding:8px 0;">{{ opened_date }}</td>
            </tr>
          </table>
        </td></tr>
        {% if watch_note %}
        <tr><td style="padding:2px 16px 16px;">
          <div style="border-left:3px solid #0d6efd;background:#f6f9ff;border-radius:0 8px 8px 0;padding:10px 14px;font-size:13px;line-height:1.6;color:#334;">
            <span style="font-size:11px;color:#8a94a3;">Note from {{ adder_name }} &middot; {{ added_time }}</span><br>
            {{ watch_note }}
          </div>
        </td></tr>
        {% endif %}
      </table>
    </td></tr>

    <!-- what this means -->
    <tr><td style="padding:6px 24px 2px;">
      <div style="font-size:13px;line-height:1.65;color:#6c757d;">
        As a watcher, you&rsquo;ll receive an email whenever a new comment is added or the status changes. You can reply to those emails to post directly to the ticket.
      </div>
    </td></tr>

    <!-- CTA -->
    <tr><td style="padding:14px 24px 4px;">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="border-radius:8px;background:#0d6efd;">
          <a href="{{ ticket_url }}" style="display:inline-block;padding:11px 22px;font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;">View ticket</a>
        </td>
      </tr></table>
    </td></tr>

    <!-- footer -->
    <tr><td style="padding:16px 24px 20px;border-top:1px solid #efeade;margin-top:8px;">
      <div style="font-size:11.5px;color:#adb5bd;line-height:1.6;">
        You received this because {{ adder_name }} added you as a watcher on ticket&nbsp;#{{ ticket_id }}.<br>
        <a href="{{ settings_url }}" style="color:#0d6efd;text-decoration:none;">Notification settings</a> &nbsp;&middot;&nbsp; <a href="{{ unwatch_url }}" style="color:#0d6efd;text-decoration:none;">Stop watching this ticket</a>
      </div>
    </td></tr>

  </table>
  <div style="font-size:11px;color:#c3bfb2;margin-top:14px;font-family:Helvetica,Arial,sans-serif;">{{ branding_label }} &middot; University of Sussex</div>
</td></tr>
</table>
</body>
</html>
"""


def upgrade():
    bind = op.get_bind()
    now = datetime.now()
    bind.execute(
        sa.text(_INSERT),
        {
            "active": True,
            "type": 74,
            "subject": _SUBJECT,
            "html_body": _BODY,
            "comment": "Ticket: Watcher added notification",
            "version": 1,
            "creation_timestamp": now,
        },
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM email_templates WHERE type = 74 AND tenant_id IS NULL AND pclass_id IS NULL"))
