#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add ticket_subjects tombstone columns

Revision ID: 7fddffd79190
Revises: b4e7a1d9c3f2
Create Date: 2026-07-23

Adds `deleted_snapshot_label` / `deleted_at` to ticket_subjects so a subject can be "tombstoned"
(its FK nulled, kind left unchanged) when the SubmittingStudent/SelectingStudent it points at is
deleted, instead of the deletion being blocked by the FK constraint. Relaxes
ck_ticket_subject_exactly_one_target to also permit the tombstoned shape (all three target FKs
null, deleted_at set).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7fddffd79190"
down_revision = "b4e7a1d9c3f2"
branch_labels = None
depends_on = None

_OLD_CONSTRAINT = "((submitting_student_id IS NOT NULL) + (selecting_student_id IS NOT NULL) + (project_class_id IS NOT NULL)) = 1"

_NEW_CONSTRAINT = (
    "(((submitting_student_id IS NOT NULL) + (selecting_student_id IS NOT NULL) + (project_class_id IS NOT NULL)) = 1)"
    " OR "
    "(submitting_student_id IS NULL AND selecting_student_id IS NULL AND project_class_id IS NULL AND deleted_at IS NOT NULL)"
)


def upgrade():
    op.add_column("ticket_subjects", sa.Column("deleted_snapshot_label", sa.String(length=255, collation="utf8_bin"), nullable=True))
    op.add_column("ticket_subjects", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    op.drop_constraint("ck_ticket_subject_exactly_one_target", "ticket_subjects", type_="check")
    op.create_check_constraint("ck_ticket_subject_exactly_one_target", "ticket_subjects", _NEW_CONSTRAINT)


def downgrade():
    op.drop_constraint("ck_ticket_subject_exactly_one_target", "ticket_subjects", type_="check")
    op.create_check_constraint("ck_ticket_subject_exactly_one_target", "ticket_subjects", _OLD_CONSTRAINT)

    op.drop_column("ticket_subjects", "deleted_at")
    op.drop_column("ticket_subjects", "deleted_snapshot_label")
