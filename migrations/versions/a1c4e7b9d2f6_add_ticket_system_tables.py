#
# Created by David Seery on 21/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add ticket system tables

Revision ID: a1c4e7b9d2f6
Revises: cd2a6f3fec15
Create Date: 2026-07-21

Creates the greenfield trouble-ticket schema: tickets, comments, logged emails, append-only
events, polymorphic subjects (with a check constraint enforcing exactly one target), the cached
derived class-scope association, subscribers (internal + external), and tenant-scoped labels.
No data migration and no removal of the ConvenorTask tables (that is deferred to the final phase).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1c4e7b9d2f6"
down_revision = "cd2a6f3fec15"
branch_labels = None
depends_on = None


def upgrade():
    # tickets
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("description", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_id", sa.Integer(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], name=op.f("fk_tickets_assignee_id_users")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_tickets_tenant_id_tenants")),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name=op.f("fk_tickets_creator_id_users")),
        sa.ForeignKeyConstraint(["last_edit_id"], ["users.id"], name=op.f("fk_tickets_last_edit_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index(op.f("ix_tickets_status"), "tickets", ["status"], unique=False)
    op.create_index(op.f("ix_tickets_assignee_id"), "tickets", ["assignee_id"], unique=False)
    op.create_index(op.f("ix_tickets_tenant_id"), "tickets", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tickets_due_date"), "tickets", ["due_date"], unique=False)
    op.create_index(op.f("ix_tickets_updated_at"), "tickets", ["updated_at"], unique=False)

    # tenant-scoped labels
    op.create_table(
        "ticket_label_defs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("colour", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_ticket_label_defs_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_label_defs")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ticket_label_tenant_name"),
    )
    op.create_index(op.f("ix_ticket_label_defs_tenant_id"), "ticket_label_defs", ["tenant_id"], unique=False)

    # comments
    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_comments_ticket_id_tickets")),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_ticket_comments_author_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_comments")),
    )
    op.create_index(op.f("ix_ticket_comments_ticket_id"), "ticket_comments", ["ticket_id"], unique=False)
    op.create_index(op.f("ix_ticket_comments_created_at"), "ticket_comments", ["created_at"], unique=False)

    # logged emails
    op.create_table(
        "ticket_emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("logged_by_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("from_addr", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("to_addrs", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("subject", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("body", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("message_id", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("logged_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_emails_ticket_id_tickets")),
        sa.ForeignKeyConstraint(["logged_by_id"], ["users.id"], name=op.f("fk_ticket_emails_logged_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_emails")),
    )
    op.create_index(op.f("ix_ticket_emails_ticket_id"), "ticket_emails", ["ticket_id"], unique=False)
    op.create_index(op.f("ix_ticket_emails_message_id"), "ticket_emails", ["message_id"], unique=False)
    op.create_index(op.f("ix_ticket_emails_logged_at"), "ticket_emails", ["logged_at"], unique=False)

    # append-only events
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_events_ticket_id_tickets")),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_ticket_events_actor_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
    )
    op.create_index(op.f("ix_ticket_events_ticket_id"), "ticket_events", ["ticket_id"], unique=False)
    op.create_index(op.f("ix_ticket_events_created_at"), "ticket_events", ["created_at"], unique=False)

    # polymorphic subjects
    op.create_table(
        "ticket_subjects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Integer(), nullable=False),
        sa.Column("submitting_student_id", sa.Integer(), nullable=True),
        sa.Column("selecting_student_id", sa.Integer(), nullable=True),
        sa.Column("project_class_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_subjects_ticket_id_tickets")),
        sa.ForeignKeyConstraint(
            ["submitting_student_id"],
            ["submitting_students.id"],
            name=op.f("fk_ticket_subjects_submitting_student_id_submitting_students"),
        ),
        sa.ForeignKeyConstraint(
            ["selecting_student_id"],
            ["selecting_students.id"],
            name=op.f("fk_ticket_subjects_selecting_student_id_selecting_students"),
        ),
        sa.ForeignKeyConstraint(
            ["project_class_id"],
            ["project_classes.id"],
            name=op.f("fk_ticket_subjects_project_class_id_project_classes"),
        ),
        sa.CheckConstraint(
            "((submitting_student_id IS NOT NULL) + (selecting_student_id IS NOT NULL) + (project_class_id IS NOT NULL)) = 1",
            name="ck_ticket_subject_exactly_one_target",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_subjects")),
    )
    op.create_index(op.f("ix_ticket_subjects_ticket_id"), "ticket_subjects", ["ticket_id"], unique=False)
    op.create_index(op.f("ix_ticket_subjects_submitting_student_id"), "ticket_subjects", ["submitting_student_id"], unique=False)
    op.create_index(op.f("ix_ticket_subjects_selecting_student_id"), "ticket_subjects", ["selecting_student_id"], unique=False)
    op.create_index(op.f("ix_ticket_subjects_project_class_id"), "ticket_subjects", ["project_class_id"], unique=False)

    # subscribers (internal users)
    op.create_table(
        "ticket_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_subscriptions_ticket_id_tickets")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ticket_subscriptions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_subscriptions")),
        sa.UniqueConstraint("ticket_id", "user_id", name="uq_ticket_subscription_user"),
    )
    op.create_index(op.f("ix_ticket_subscriptions_ticket_id"), "ticket_subscriptions", ["ticket_id"], unique=False)
    op.create_index(op.f("ix_ticket_subscriptions_user_id"), "ticket_subscriptions", ["user_id"], unique=False)

    # subscribers (external email addresses)
    op.create_table(
        "ticket_external_subscribers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_external_subscribers_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_external_subscribers")),
        sa.UniqueConstraint("ticket_id", "email", name="uq_ticket_external_subscriber_email"),
    )
    op.create_index(op.f("ix_ticket_external_subscribers_ticket_id"), "ticket_external_subscribers", ["ticket_id"], unique=False)

    # cached derived class scope
    op.create_table(
        "ticket_class_scope",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("project_class_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_class_scope_ticket_id_tickets")),
        sa.ForeignKeyConstraint(
            ["project_class_id"],
            ["project_classes.id"],
            name=op.f("fk_ticket_class_scope_project_class_id_project_classes"),
        ),
        sa.PrimaryKeyConstraint("ticket_id", "project_class_id", name=op.f("pk_ticket_class_scope")),
    )

    # ticket <-> label many-to-many
    op.create_table(
        "ticket_labels",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_labels_ticket_id_tickets")),
        sa.ForeignKeyConstraint(["label_id"], ["ticket_label_defs.id"], name=op.f("fk_ticket_labels_label_id_ticket_label_defs")),
        sa.PrimaryKeyConstraint("ticket_id", "label_id", name=op.f("pk_ticket_labels")),
    )


def downgrade():
    op.drop_table("ticket_labels")
    op.drop_table("ticket_class_scope")

    op.drop_index(op.f("ix_ticket_external_subscribers_ticket_id"), table_name="ticket_external_subscribers")
    op.drop_table("ticket_external_subscribers")

    op.drop_index(op.f("ix_ticket_subscriptions_user_id"), table_name="ticket_subscriptions")
    op.drop_index(op.f("ix_ticket_subscriptions_ticket_id"), table_name="ticket_subscriptions")
    op.drop_table("ticket_subscriptions")

    op.drop_index(op.f("ix_ticket_subjects_project_class_id"), table_name="ticket_subjects")
    op.drop_index(op.f("ix_ticket_subjects_selecting_student_id"), table_name="ticket_subjects")
    op.drop_index(op.f("ix_ticket_subjects_submitting_student_id"), table_name="ticket_subjects")
    op.drop_index(op.f("ix_ticket_subjects_ticket_id"), table_name="ticket_subjects")
    op.drop_table("ticket_subjects")

    op.drop_index(op.f("ix_ticket_events_created_at"), table_name="ticket_events")
    op.drop_index(op.f("ix_ticket_events_ticket_id"), table_name="ticket_events")
    op.drop_table("ticket_events")

    op.drop_index(op.f("ix_ticket_emails_logged_at"), table_name="ticket_emails")
    op.drop_index(op.f("ix_ticket_emails_message_id"), table_name="ticket_emails")
    op.drop_index(op.f("ix_ticket_emails_ticket_id"), table_name="ticket_emails")
    op.drop_table("ticket_emails")

    op.drop_index(op.f("ix_ticket_comments_created_at"), table_name="ticket_comments")
    op.drop_index(op.f("ix_ticket_comments_ticket_id"), table_name="ticket_comments")
    op.drop_table("ticket_comments")

    op.drop_index(op.f("ix_ticket_label_defs_tenant_id"), table_name="ticket_label_defs")
    op.drop_table("ticket_label_defs")

    op.drop_index(op.f("ix_tickets_updated_at"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_due_date"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_tenant_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_assignee_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_status"), table_name="tickets")
    op.drop_table("tickets")
