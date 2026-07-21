#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""seed ticket comment notification EmailTemplate

Revision ID: c2f5a8b3e6d1
Revises: e5b8c1d4f7a2
Create Date: 2026-07-22

Seeds the global EmailTemplate (type 73, TICKET_COMMENT_NOTIFICATION) sent to a ticket's
subscribers when a new comment is posted. Tokens are filled by
app/tasks/ticket_notifications.py at send time.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "c2f5a8b3e6d1"
down_revision = "e5b8c1d4f7a2"
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

_SUBJECT = "New comment on ticket #{ticket_id} — {ticket_title}"

_BODY = """\
<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>New comment on ticket #{{ ticket_id }}</title>
</head>
<body style="margin:0;padding:0;background:#f4f2ec;-webkit-font-smoothing:antialiased;">
<span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;mso-hide:all;">{{ commenter_name }} commented on #{{ ticket_id }} &mdash; {{ ticket_title }}</span>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f4f2ec;">
<tr><td align="center" style="padding:24px 12px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="600" style="width:600px;max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e6e2d6;font-family:Helvetica,Arial,sans-serif;">

    <tr><td style="background:#212529;padding:16px 24px;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>
        <td style="font-family:'Roboto',Helvetica,Arial,sans-serif;font-weight:300;font-size:18px;color:#ffffff;">{{ branding_label }}</td>
        <td align="right" style="font-size:12px;color:rgba(255,255,255,.55);">Ticket&nbsp;#{{ ticket_id }}</td>
      </tr></table>
    </td></tr>

    <tr><td style="padding:14px 24px 0;">
      <div style="font-size:12px;color:#8a94a3;">{{ project_class_name }}</div>
      <div style="font-size:19px;line-height:1.35;font-weight:700;color:#1a1a1a;margin-top:4px;">{{ ticket_title }}</div>
      <div style="margin-top:10px;">
        <span style="display:inline-block;padding:3px 11px;border-radius:20px;font-size:12px;font-weight:600;background:{{ status_bg }};color:{{ status_color }};">{{ status_label }}</span>
        {% for label in labels %}<span style="display:inline-block;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:600;background:{{ label.bg }};color:{{ label.fg }};margin-left:4px;">{{ label.name }}</span>{% endfor %}
      </div>
    </td></tr>

    <tr><td style="padding:18px 24px 6px;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #e6e2d6;border-radius:10px;overflow:hidden;">
        <tr><td style="background:#faf8f2;border-bottom:1px solid #efeade;padding:10px 14px;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="width:30px;"><div style="width:30px;height:30px;border-radius:50%;background:#0d6efd;color:#fff;text-align:center;line-height:30px;font-size:11px;font-weight:700;">{{ commenter_initials }}</div></td>
            <td style="padding-left:9px;font-size:13px;color:#334;"><strong>{{ commenter_name }}</strong>{% if is_email_reply %} <span style="font-size:11px;color:#0f5132;">via email</span>{% endif %}<div style="font-size:11px;color:#8a94a3;">{{ comment_time }}</div></td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:15px 16px;font-size:14px;line-height:1.65;color:#343a40;">{{ comment_html }}</td></tr>
      </table>
    </td></tr>

    <tr><td style="padding:12px 24px 4px;">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="border-radius:8px;background:#0d6efd;">
          <a href="{{ ticket_url }}" style="display:inline-block;padding:11px 22px;font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;">View &amp; reply on ticket</a>
        </td>
      </tr></table>
    </td></tr>

    <tr><td style="padding:16px 24px 20px;border-top:1px solid #efeade;margin-top:8px;">
      <div style="font-size:11.5px;color:#adb5bd;line-height:1.6;">
        You received this because you are {{ subscribe_reason }} on ticket&nbsp;#{{ ticket_id }}.<br>
        <a href="{{ settings_url }}" style="color:#0d6efd;text-decoration:none;">Notification settings</a> &nbsp;&middot;&nbsp; <a href="{{ unsubscribe_url }}" style="color:#0d6efd;text-decoration:none;">Unsubscribe from this ticket</a>
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
            "type": 73,
            "subject": _SUBJECT,
            "html_body": _BODY,
            "comment": "Ticket: New comment notification",
            "version": 1,
            "creation_timestamp": now,
        },
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM email_templates WHERE type = 73 AND tenant_id IS NULL AND pclass_id IS NULL"))
