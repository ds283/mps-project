"""Add consent workflow fields to SubmissionRecord, consent_token to User, ConsentAuditEvent table

Revision ID: f1e2d3c4b5a6
Revises: d3e4f5a6b7c8
Create Date: 2026-06-13

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1e2d3c4b5a6"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    # --- submission_records: add consent workflow columns ---
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.add_column(sa.Column("exemplar_consent_granted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("exemplar_consent_withdrawn", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("exemplar_consent_withdrawn_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("exemplar_supervisor_approved", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("exemplar_supervisor_actioned_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("openday_consent_granted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("openday_consent_withdrawn", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("openday_consent_withdrawn_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("consent_invitation_sent_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("consent_reminder_sent_at", sa.DateTime(), nullable=True))

    # --- users: add consent_token column ---
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "consent_token",
                sa.String(36, collation="utf8_bin"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_users_consent_token", ["consent_token"], unique=True)

    # --- consent_audit_events: new table ---
    op.create_table(
        "consent_audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("ip_address", sa.String(45, collation="utf8_bin"), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["record_id"], ["submission_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consent_audit_events_record_id", "consent_audit_events", ["record_id"])
    op.create_index("ix_consent_audit_events_event_type", "consent_audit_events", ["event_type"])
    op.create_index("ix_consent_audit_events_timestamp", "consent_audit_events", ["timestamp"])


def downgrade():
    op.drop_index("ix_consent_audit_events_timestamp", table_name="consent_audit_events")
    op.drop_index("ix_consent_audit_events_event_type", table_name="consent_audit_events")
    op.drop_index("ix_consent_audit_events_record_id", table_name="consent_audit_events")
    op.drop_table("consent_audit_events")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_consent_token")
        batch_op.drop_column("consent_token")

    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.drop_column("consent_reminder_sent_at")
        batch_op.drop_column("consent_invitation_sent_at")
        batch_op.drop_column("openday_consent_withdrawn_at")
        batch_op.drop_column("openday_consent_withdrawn")
        batch_op.drop_column("openday_consent_granted_at")
        batch_op.drop_column("exemplar_supervisor_actioned_at")
        batch_op.drop_column("exemplar_supervisor_approved")
        batch_op.drop_column("exemplar_consent_withdrawn_at")
        batch_op.drop_column("exemplar_consent_withdrawn")
        batch_op.drop_column("exemplar_consent_granted_at")
