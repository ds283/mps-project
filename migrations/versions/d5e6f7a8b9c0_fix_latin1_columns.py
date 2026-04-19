"""Fix latin1 string columns — convert to utf8

Revision ID: d5e6f7a8b9c0
Revises: b3c4d5e6f7a8
Create Date: 2026-04-18

Background
----------
The MySQL server has character_set_server = latin1.  SQLAlchemy VARCHAR
columns that carry an explicit collation='utf8_bin' are created as utf8 and
are unaffected.  However, Text() columns (which have no explicit collation
in the ORM models) inherited the server default of latin1/latin1_swedish_ci.
Two VARCHAR columns in older tables also lack an explicit collation and are
likewise latin1.

Storing non-Latin Unicode content (accented names, non-Latin scripts, etc.)
in latin1 columns produces corrupted data or insertion errors.  This
migration converts all 37 affected columns to utf8 so they are consistent
with the rest of the schema.

Affected tables (verified against information_schema.COLUMNS):
  batch_faculty, confirm_requests, conflation_reports, custom_offers,
  email_templates, email_workflow_items, live_marking_schemes,
  marking_events, marking_reports, marking_schemes, moderator_reports,
  submission_records, submission_roles, supervision_events,
  tenants, users, workflow_log

Conversion safety
-----------------
MODIFY COLUMN is used (not CONVERT TO CHARACTER SET) so that only the
targeted columns are changed.  All existing data in these columns is
ASCII or standard Latin-1 content; converting latin1 -> utf8 re-encodes
it correctly.  No 4-byte / non-BMP characters are expected in any of
these columns.
"""
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None

_UTF8_VARCHAR255 = "VARCHAR(255) CHARACTER SET utf8 COLLATE utf8_bin"


def upgrade():
    # ------------------------------------------------------------------
    # VARCHAR columns (2) — convert to utf8_bin to match schema convention
    # ------------------------------------------------------------------
    op.execute(
        f"ALTER TABLE tenants "
        f"MODIFY COLUMN name {_UTF8_VARCHAR255} NULL"
    )
    op.execute(
        f"ALTER TABLE submission_roles "
        f"MODIFY COLUMN regular_meeting_location {_UTF8_VARCHAR255} NULL"
    )

    # ------------------------------------------------------------------
    # TEXT columns (35) — convert to utf8; no explicit collation so the
    # column will inherit whatever collation the table uses (which is
    # utf8_general_ci once the table default is corrected by a future
    # migration, or utf8_bin here since we force CHARACTER SET utf8).
    # ------------------------------------------------------------------

    # batch_faculty
    op.execute("ALTER TABLE batch_faculty MODIFY COLUMN report TEXT CHARACTER SET utf8 NULL")

    # confirm_requests
    op.execute("ALTER TABLE confirm_requests MODIFY COLUMN comment TEXT CHARACTER SET utf8 NULL")

    # conflation_reports
    op.execute(
        "ALTER TABLE conflation_reports "
        "MODIFY COLUMN conflation_report TEXT CHARACTER SET utf8 NULL"
    )

    # custom_offers
    op.execute("ALTER TABLE custom_offers MODIFY COLUMN comment TEXT CHARACTER SET utf8 NULL")

    # email_templates
    op.execute(
        "ALTER TABLE email_templates MODIFY COLUMN html_body TEXT CHARACTER SET utf8 NOT NULL"
    )

    # email_workflow_items
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN subject_payload TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN body_payload TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN body_override TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN recipient_list TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN reply_to TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN callbacks TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE email_workflow_items "
        "MODIFY COLUMN error_log TEXT CHARACTER SET utf8 NULL"
    )

    # live_marking_schemes
    op.execute(
        "ALTER TABLE live_marking_schemes "
        "MODIFY COLUMN title TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE live_marking_schemes "
        "MODIFY COLUMN rubric TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE live_marking_schemes "
        "MODIFY COLUMN `schema` TEXT CHARACTER SET utf8 NULL"
    )

    # marking_events
    op.execute(
        "ALTER TABLE marking_events MODIFY COLUMN targets TEXT CHARACTER SET utf8 NULL"
    )

    # marking_reports
    op.execute(
        "ALTER TABLE marking_reports MODIFY COLUMN report TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE marking_reports "
        "MODIFY COLUMN feedback_positive TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE marking_reports "
        "MODIFY COLUMN feedback_improvement TEXT CHARACTER SET utf8 NULL"
    )

    # marking_schemes
    op.execute(
        "ALTER TABLE marking_schemes MODIFY COLUMN title TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE marking_schemes MODIFY COLUMN rubric TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE marking_schemes MODIFY COLUMN `schema` TEXT CHARACTER SET utf8 NULL"
    )

    # moderator_reports
    op.execute(
        "ALTER TABLE moderator_reports MODIFY COLUMN report TEXT CHARACTER SET utf8 NULL"
    )

    # submission_records
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN exemplar_comment TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        # mediumtext — preserve the larger storage type
        "ALTER TABLE submission_records "
        "MODIFY COLUMN language_analysis MEDIUMTEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN llm_failure_reason TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN llm_feedback_failure_reason TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN risk_factors TEXT CHARACTER SET utf8 NULL"
    )

    # submission_roles
    op.execute(
        "ALTER TABLE submission_roles "
        "MODIFY COLUMN justification TEXT CHARACTER SET utf8 NULL"
    )

    # supervision_events
    op.execute(
        "ALTER TABLE supervision_events "
        "MODIFY COLUMN meeting_summary TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE supervision_events "
        "MODIFY COLUMN supervision_notes TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE supervision_events "
        "MODIFY COLUMN submitter_notes TEXT CHARACTER SET utf8 NULL"
    )

    # tenants
    op.execute(
        "ALTER TABLE tenants MODIFY COLUMN ai_calibration TEXT CHARACTER SET utf8 NULL"
    )

    # users — OAuth tokens are ASCII-safe; utf8 is fine
    op.execute(
        "ALTER TABLE users MODIFY COLUMN box_access_token TEXT CHARACTER SET utf8 NULL"
    )
    op.execute(
        "ALTER TABLE users MODIFY COLUMN box_refresh_token TEXT CHARACTER SET utf8 NULL"
    )

    # workflow_log
    op.execute(
        "ALTER TABLE workflow_log MODIFY COLUMN summary TEXT CHARACTER SET utf8 NULL"
    )


def downgrade():
    # Restore to latin1/latin1_swedish_ci (the charset these columns had
    # before this migration, inherited from the server default).
    op.execute(
        "ALTER TABLE tenants "
        "MODIFY COLUMN name VARCHAR(255) CHARACTER SET latin1 COLLATE latin1_swedish_ci NULL"
    )
    op.execute(
        "ALTER TABLE submission_roles "
        "MODIFY COLUMN regular_meeting_location "
        "VARCHAR(255) CHARACTER SET latin1 COLLATE latin1_swedish_ci NULL"
    )

    for table, col, typ in [
        ("batch_faculty",               "report",                      "TEXT"),
        ("confirm_requests",            "comment",                     "TEXT"),
        ("conflation_reports",          "conflation_report",           "TEXT"),
        ("custom_offers",               "comment",                     "TEXT"),
        ("email_templates",             "html_body",                   "TEXT"),
        ("email_workflow_items",        "subject_payload",             "TEXT"),
        ("email_workflow_items",        "body_payload",                "TEXT"),
        ("email_workflow_items",        "body_override",               "TEXT"),
        ("email_workflow_items",        "recipient_list",              "TEXT"),
        ("email_workflow_items",        "reply_to",                    "TEXT"),
        ("email_workflow_items",        "callbacks",                   "TEXT"),
        ("email_workflow_items",        "error_log",                   "TEXT"),
        ("live_marking_schemes",        "title",                       "TEXT"),
        ("live_marking_schemes",        "rubric",                      "TEXT"),
        ("live_marking_schemes",        "`schema`",                    "TEXT"),
        ("marking_events",              "targets",                     "TEXT"),
        ("marking_reports",             "report",                      "TEXT"),
        ("marking_reports",             "feedback_positive",           "TEXT"),
        ("marking_reports",             "feedback_improvement",        "TEXT"),
        ("marking_schemes",             "title",                       "TEXT"),
        ("marking_schemes",             "rubric",                      "TEXT"),
        ("marking_schemes",             "`schema`",                    "TEXT"),
        ("moderator_reports",           "report",                      "TEXT"),
        ("submission_records",          "exemplar_comment",            "TEXT"),
        ("submission_records",          "language_analysis",           "MEDIUMTEXT"),
        ("submission_records",          "llm_failure_reason",          "TEXT"),
        ("submission_records",          "llm_feedback_failure_reason", "TEXT"),
        ("submission_records",          "risk_factors",                "TEXT"),
        ("submission_roles",            "justification",               "TEXT"),
        ("supervision_events",          "meeting_summary",             "TEXT"),
        ("supervision_events",          "supervision_notes",           "TEXT"),
        ("supervision_events",          "submitter_notes",             "TEXT"),
        ("tenants",                     "ai_calibration",              "TEXT"),
        ("users",                       "box_access_token",            "TEXT"),
        ("users",                       "box_refresh_token",           "TEXT"),
        ("workflow_log",                "summary",                     "TEXT"),
    ]:
        # email_templates.html_body is NOT NULL; everything else is NULL
        null = "NOT NULL" if (table, col) == ("email_templates", "html_body") else "NULL"
        op.execute(
            f"ALTER TABLE {table} MODIFY COLUMN {col} "
            f"{typ} CHARACTER SET latin1 COLLATE latin1_swedish_ci {null}"
        )
