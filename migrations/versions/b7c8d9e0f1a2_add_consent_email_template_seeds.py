#
# Created by David Seery on 13/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add seed EmailTemplate records for consent workflow (types 70, 71, 72)

Revision ID: b7c8d9e0f1a2
Revises: f1e2d3c4b5a6
Create Date: 2026-06-13

Data-only migration.  Inserts global (tenant_id=NULL, pclass_id=NULL) seed
EmailTemplate rows for the three consent workflow email types registered in
Phase 1.  These seed templates provide working defaults; administrators can
customise the wording via the admin UI.
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "b7c8d9e0f1a2"
down_revision = "f1e2d3c4b5a6"
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

_T70_SUBJECT = "Your project report — permissions for future use"

_T70_BODY = """\
<p>Dear {{ record.owner.student.user.first_name or "student" }},</p>

<p>Your project report for <strong>{{ pclass_name }} {{ year_a }}–{{ year_b }}</strong>
    has been marked and your grade has been confirmed.</p>

<p>We would like to ask whether you are willing to allow your report to be used
    in the following ways. Both are entirely optional and independent of each other.
    Declining has no effect on your assessment.</p>

<ul>
    <li><strong>Teaching exemplar</strong> — your report (with your name removed,
        candidate number visible) may be shared with future cohorts as a graded example
        of the standard of work at your grade level.
    </li>
    <li><strong>Open day and promotional events</strong> — your project title and
        abstract may be displayed at University open days. Your name will not be shown.
    </li>
</ul>

<p>To indicate your preferences, please follow this link:</p>

<p><a href="{{ consent_url }}">Manage your report permissions</a></p>

<p>You can change your preferences at any time using the same link.
    <strong>Please keep this link in a safe place</strong> — it is your permanent
    way to manage these preferences, even after you leave the University.</p>

<p>If you have any questions, please contact the School office.</p>"""

_T71_SUBJECT = "Reminder: your project report permissions"

_T71_BODY = """\
<p>Dear {{ record.owner.student.user.first_name or "student" }},</p>

<p>We recently wrote to ask whether your project report for
    <strong>{{ pclass_name }} {{ year_a }}–{{ year_b }}</strong>
    could be used as a teaching exemplar or at open days.</p>

<p>We have not yet received a response. If you are happy for us to use your
    report, or if you would like to decline, please follow this link:</p>

<p><a href="{{ consent_url }}">Manage your report permissions</a></p>

<p>If you have already responded, please disregard this message.</p>"""

_T72_SUBJECT = "Student consent for exemplar use — {{ pclass_name }} {{ year_a }}–{{ year_b }}"

_T72_BODY = """\
<p>Dear {{ role.user.first_name or "colleague" }},</p>

<p>A student you supervised on <strong>{{ pclass_name }} {{ year_a }}–{{ year_b }}</strong>
    has given consent for their project report to be used as a teaching exemplar
    for future cohorts.</p>

<p>Before the report can be used in this way, we need your approval that you
    consider it suitable — for example, that it does not overlap too closely with
    projects you expect to run in future years.</p>

<p>To review the report and indicate your decision, please log in to the
    MPS projects system and visit your
    <a href="{{ approval_url }}">My students</a> page.</p>

<p>You only need to respond once. If the student subsequently changes their
    consent preferences, you will not be contacted again unless you choose to
    update your decision yourself.</p>"""


def upgrade():
    bind = op.get_bind()
    now = datetime.now()

    bind.execute(
        sa.text(_INSERT),
        {
            "active": True,
            "type": 70,
            "subject": _T70_SUBJECT,
            "html_body": _T70_BODY,
            "comment": "Consent: Student invitation",
            "version": 1,
            "creation_timestamp": now,
        },
    )

    bind.execute(
        sa.text(_INSERT),
        {
            "active": True,
            "type": 71,
            "subject": _T71_SUBJECT,
            "html_body": _T71_BODY,
            "comment": "Consent: Student reminder",
            "version": 1,
            "creation_timestamp": now,
        },
    )

    bind.execute(
        sa.text(_INSERT),
        {
            "active": True,
            "type": 72,
            "subject": _T72_SUBJECT,
            "html_body": _T72_BODY,
            "comment": "Consent: Supervisor approval request",
            "version": 1,
            "creation_timestamp": now,
        },
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM email_templates WHERE type IN (70, 71, 72) AND tenant_id IS NULL AND pclass_id IS NULL"))
