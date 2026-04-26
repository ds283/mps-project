#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..database import db

####################
# ASSOCIATION TABLES
####################


# TENANTS

# association table mapping from users to tenants
tenant_to_users = db.Table(
    "tenant_users",
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
    db.Column("tenant_id", db.Integer(), db.ForeignKey("tenants.id"), primary_key=True),
)

# association table mapping from research groups to tenants
tenant_to_groups = db.Table(
    "tenant_groups",
    db.Column(
        "group_id", db.Integer(), db.ForeignKey("research_groups.id"), primary_key=True
    ),
    db.Column("tenant_id", db.Integer(), db.ForeignKey("tenants.id"), primary_key=True),
)

# association table mapping from project tags to tenants
tenant_to_project_tag_groups = db.Table(
    "tenant_project_tag_groups",
    db.Column(
        "project_tag_group_id",
        db.Integer(),
        db.ForeignKey("project_tag_groups.id"),
        primary_key=True,
    ),
    db.Column("tenant_id", db.Integer(), db.ForeignKey("tenants.id"), primary_key=True),
)

# association table mapping from degree programmes to tenants
tenant_to_degree_programmes = db.Table(
    "tenant_to_degree_programmes",
    db.Column(
        "degree_programme.id",
        db.Integer(),
        db.ForeignKey("degree_programmes.id"),
        primary_key=True,
    ),
    db.Column("tenant_id", db.Integer(), db.ForeignKey("tenants.id"), primary_key=True),
)

# association table mapping from student batch records to tenants
student_batch_to_tenants = db.Table(
    "student_batch_tenants",
    db.Column(
        "batch_id", db.Integer(), db.ForeignKey("batch_student.id"), primary_key=True
    ),
    db.Column("tenant_id", db.Integer(), db.ForeignKey("tenants.id"), primary_key=True),
)

# association table mapping from faculty batch records to tenants
faculty_batch_to_tenants = db.Table(
    "faculty_batch_tenants",
    db.Column(
        "batch_id", db.Integer(), db.ForeignKey("batch_faculty.id"), primary_key=True
    ),
    db.Column("tenant_id", db.Integer(), db.ForeignKey("tenants.id"), primary_key=True),
)

# USERS

# association table mapping from roles to users
roles_to_users = db.Table(
    "roles_users",
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer(), db.ForeignKey("roles.id"), primary_key=True),
)

# association table: temporary mask roles
mask_roles_to_users = db.Table(
    "roles_users_masked",
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer(), db.ForeignKey("roles.id"), primary_key=True),
)

# association table giving faculty research group affiliations
faculty_affiliations = db.Table(
    "faculty_affiliations",
    db.Column(
        "user_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
    db.Column(
        "group_id", db.Integer(), db.ForeignKey("research_groups.id"), primary_key=True
    ),
)

# association table mapping degree programmes to modules
programmes_to_modules = db.Table(
    "programmes_to_modules",
    db.Column(
        "programme_id",
        db.Integer(),
        db.ForeignKey("degree_programmes.id"),
        primary_key=True,
    ),
    db.Column("module_id", db.Integer(), db.ForeignKey("modules.id"), primary_key=True),
)

# PROJECT CLASS ASSOCIATIONS


# association table giving association between project classes and degree programmes
pclass_programme_associations = db.Table(
    "project_class_to_programmes",
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
    db.Column(
        "programme_id",
        db.Integer(),
        db.ForeignKey("degree_programmes.id"),
        primary_key=True,
    ),
)

# association table giving co-convenors for a project class
pclass_coconvenors = db.Table(
    "project_class_coconvenors",
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
)

# association table giving School Office contacts for a project class
office_contacts = db.Table(
    "office_contacts",
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
    db.Column("office_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

# association table giving approvals team for a project class
approvals_team = db.Table(
    "approvals_team",
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

# track who has received a Go Live email notification so that we don't double-post
golive_emails = db.Table(
    "golive_emails",
    db.Column(
        "config_id",
        db.Integer(),
        db.ForeignKey("project_class_config.id"),
        primary_key=True,
    ),
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

# force tagging with a specific tag group
force_tag_groups = db.Table(
    "force_tag_groups",
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
    db.Column(
        "tag_group_id",
        db.Integer(),
        db.ForeignKey("project_tag_groups.id"),
        primary_key=True,
    ),
)

# SYSTEM MESSAGES


# association between project classes and messages
pclass_message_associations = db.Table(
    "project_class_to_messages",
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
    db.Column(
        "message_id", db.Integer(), db.ForeignKey("messages.id"), primary_key=True
    ),
)

# associate dismissals with messages
message_dismissals = db.Table(
    "message_dismissals",
    db.Column(
        "message_id", db.Integer(), db.ForeignKey("messages.id"), primary_key=True
    ),
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

# GO-LIVE CONFIRMATIONS FROM FACULTY

golive_confirmation = db.Table(
    "go_live_confirmation",
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
    db.Column(
        "pclass_config_id",
        db.Integer(),
        db.ForeignKey("project_class_config.id"),
        primary_key=True,
    ),
)

# PROJECT ASSOCIATIONS (LIBRARY VERSIONS -- NOT LIVE)


# association table giving association between projects and project classes
project_pclasses = db.Table(
    "project_to_classes",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("projects.id"), primary_key=True
    ),
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
)

# association table giving association between projects and transferable skills
project_skills = db.Table(
    "project_to_skills",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("projects.id"), primary_key=True
    ),
    db.Column(
        "skill_id",
        db.Integer(),
        db.ForeignKey("transferable_skills.id"),
        primary_key=True,
    ),
)

# association table giving association between projects and degree programmes
project_programmes = db.Table(
    "project_to_programmes",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("projects.id"), primary_key=True
    ),
    db.Column(
        "programme_id",
        db.Integer(),
        db.ForeignKey("degree_programmes.id"),
        primary_key=True,
    ),
)

# association table giving assessors
project_assessors = db.Table(
    "project_to_assessors",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("projects.id"), primary_key=True
    ),
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
)

# association table giving supervisor pool (currently only used for generic projects)
# note this is different from the supervision team, which is a list of role *descriptors*, not
# the people available to fill those roles
project_supervisors = db.Table(
    "project_to_supervisors",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("projects.id"), primary_key=True
    ),
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
)

# association table matching project descriptions to supervision team
# note this is different from the supervisor pool. This is a list of links to role *descriptors*,
# not the people available to fill those roles
description_supervisors = db.Table(
    "description_to_supervisors",
    db.Column(
        "description_id",
        db.Integer(),
        db.ForeignKey("descriptions.id"),
        primary_key=True,
    ),
    db.Column(
        "supervisor_id",
        db.Integer(),
        db.ForeignKey("supervision_team.id"),
        primary_key=True,
    ),
)

# association table matching project descriptions to project classes
description_pclasses = db.Table(
    "description_to_pclasses",
    db.Column(
        "description_id",
        db.Integer(),
        db.ForeignKey("descriptions.id"),
        primary_key=True,
    ),
    db.Column(
        "project_class_id",
        db.Integer(),
        db.ForeignKey("project_classes.id"),
        primary_key=True,
    ),
)

# association table matching project descriptions to modules
description_to_modules = db.Table(
    "description_to_modules",
    db.Column(
        "description_id",
        db.Integer(),
        db.ForeignKey("descriptions.id"),
        primary_key=True,
    ),
    db.Column("module_id", db.Integer(), db.ForeignKey("modules.id"), primary_key=True),
)

# association table linking projects to tags
project_tags = db.Table(
    "project_to_tags",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("projects.id"), primary_key=True
    ),
    db.Column(
        "tag_id", db.Integer(), db.ForeignKey("project_tags.id"), primary_key=True
    ),
)

# PROJECT ASSOCIATIONS (LIVE)


# association table giving association between projects and transferable skills
live_project_skills = db.Table(
    "live_project_to_skills",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column(
        "skill_id",
        db.Integer(),
        db.ForeignKey("transferable_skills.id"),
        primary_key=True,
    ),
)

# association table giving association between projects and degree programmes
live_project_programmes = db.Table(
    "live_project_to_programmes",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column(
        "programme_id",
        db.Integer(),
        db.ForeignKey("degree_programmes.id"),
        primary_key=True,
    ),
)

# association table matching live projects to assessors
live_assessors = db.Table(
    "live_project_to_assessors",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
)

# association table giving supervisor pool for this live project (currently only used for generic projects)
# note this is different from the supervision team, which is a list of role *descriptors*, not
# the people available to fill those roles
live_supervisors = db.Table(
    "live_project_to_supervisors",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
)

# association table matching live projects to supervision team
# note this is different from the supervisor pool. This is a list of links to role *descriptors*,
# not the people available to fill those roles
live_project_supervision = db.Table(
    "live_project_to_supervision",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column(
        "supervisor.id",
        db.Integer(),
        db.ForeignKey("supervision_team.id"),
        primary_key=True,
    ),
)

# association table matching live projects to modules
live_project_to_modules = db.Table(
    "live_project_to_modules",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column("module_id", db.Integer(), db.ForeignKey("modules.id"), primary_key=True),
)

# association table linking projects to tags
live_project_tags = db.Table(
    "live_project_to_tags",
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
    db.Column(
        "tag_id", db.Integer(), db.ForeignKey("project_tags.id"), primary_key=True
    ),
)

# CONVENOR FILTERS

# association table : active research group filters
convenor_group_filter_table = db.Table(
    "convenor_group_filters",
    db.Column("owner_id", db.Integer(), db.ForeignKey("filters.id"), primary_key=True),
    db.Column(
        "research_group_id",
        db.Integer(),
        db.ForeignKey("research_groups.id"),
        primary_key=True,
    ),
)

# assocation table: active skill group filters
convenor_skill_filter_table = db.Table(
    "convenor_tskill_filters",
    db.Column("owner_id", db.Integer(), db.ForeignKey("filters.id"), primary_key=True),
    db.Column(
        "skill_id",
        db.Integer(),
        db.ForeignKey("transferable_skills.id"),
        primary_key=True,
    ),
)

# STUDENT FILTERS

# association table: active research group filters for selectors
sel_group_filter_table = db.Table(
    "sel_group_filters",
    db.Column(
        "selector_id",
        db.Integer(),
        db.ForeignKey("selecting_students.id"),
        primary_key=True,
    ),
    db.Column(
        "research_group_id",
        db.Integer(),
        db.ForeignKey("research_groups.id"),
        primary_key=True,
    ),
)

# association table: active skill group filters for selectors
sel_skill_filter_table = db.Table(
    "sel_tskill_filters",
    db.Column(
        "selector_id",
        db.Integer(),
        db.ForeignKey("selecting_students.id"),
        primary_key=True,
    ),
    db.Column(
        "skill_id",
        db.Integer(),
        db.ForeignKey("transferable_skills.id"),
        primary_key=True,
    ),
)

# MATCHING

# project classes participating in a match
match_configs = db.Table(
    "match_configs",
    db.Column(
        "match_id",
        db.Integer(),
        db.ForeignKey("matching_attempts.id"),
        primary_key=True,
    ),
    db.Column(
        "config_id",
        db.Integer(),
        db.ForeignKey("project_class_config.id"),
        primary_key=True,
    ),
)

# workload balancing: include CATS from other MatchingAttempts
match_balancing = db.Table(
    "match_balancing",
    db.Column(
        "child_id",
        db.Integer(),
        db.ForeignKey("matching_attempts.id"),
        primary_key=True,
    ),
    db.Column(
        "parent_id",
        db.Integer(),
        db.ForeignKey("matching_attempts.id"),
        primary_key=True,
    ),
)

# configuration association: supervisors
supervisors_matching_table = db.Table(
    "match_config_supervisors",
    db.Column(
        "match_id",
        db.Integer(),
        db.ForeignKey("matching_attempts.id"),
        primary_key=True,
    ),
    db.Column(
        "supervisor_id",
        db.Integer(),
        db.ForeignKey("faculty_data.id"),
        primary_key=True,
    ),
)

# configuration association: markers
marker_matching_table = db.Table(
    "match_config_markers",
    db.Column(
        "match_id",
        db.Integer(),
        db.ForeignKey("matching_attempts.id"),
        primary_key=True,
    ),
    db.Column(
        "marker_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
)

# configuration association: projects
project_matching_table = db.Table(
    "match_config_projects",
    db.Column(
        "match_id",
        db.Integer(),
        db.ForeignKey("matching_attempts.id"),
        primary_key=True,
    ),
    db.Column(
        "project_id", db.Integer(), db.ForeignKey("live_projects.id"), primary_key=True
    ),
)

# SUPERVISION ROLES, EVENTS, ATTENDANCE MONITORING

# email log linking all emails to the supervision event they are associated with
event_email_table = db.Table(
    "supervision_event_emails",
    db.Column(
        "event_id",
        db.Integer(),
        db.ForeignKey("supervision_events.id"),
        primary_key=True,
    ),
    db.Column(
        "email_id", db.Integer(), db.ForeignKey("email_log.id"), primary_key=True
    ),
)

# email log linking reminder emails to the supervision event they are associated with
# (we use this to ensure we respect faculty members' individual preferences for the frequency of contact)
event_reminder_table = db.Table(
    "supervision_event_reminders",
    db.Column(
        "event_id",
        db.Integer(),
        db.ForeignKey("supervision_events.id"),
        primary_key=True,
    ),
    db.Column(
        "email_id", db.Integer(), db.ForeignKey("email_log.id"), primary_key=True
    ),
)

# link members of the supervision team to a supervision event
event_roles_table = db.Table(
    "supervision_event_roles",
    db.Column(
        "event_id",
        db.Integer(),
        db.ForeignKey("supervision_events.id"),
        primary_key=True,
    ),
    db.Column(
        "submission_role_id",
        db.Integer(),
        db.ForeignKey("submission_roles.id"),
        primary_key=True,
    ),
)

even_assets_table = db.Table(
    "supervision_event_assets",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("submitted_assets.id"), primary_key=True
    ),
    db.Column(
        "event_id",
        db.Integer(),
        db.ForeignKey("supervision_events.id"),
        primary_key=True,
    ),
)

# SUBMISSION AND MARKING WORKLOW

# email log linking all marking emails to a SubmissionRole instance
submission_role_emails = db.Table(
    "submission_role_emails",
    db.Column(
        "role_id", db.Integer(), db.ForeignKey("submission_roles.id"), primary_key=True
    ),
    db.Column(
        "email_id", db.Integer(), db.ForeignKey("email_log.id"), primary_key=True
    ),
)

# link feedback reports to submission records
submission_record_to_feedback_report = db.Table(
    "submission_record_to_feedback_report",
    db.Column(
        "submission_id",
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        primary_key=True,
    ),
    db.Column(
        "report_id",
        db.Integer(),
        db.ForeignKey("feedback_reports.id"),
        primary_key=True,
    ),
)

# PRESENTATIONS AND SCHEDULING

# link presentation assessments to submission periods
assessment_to_periods = db.Table(
    "assessment_to_periods",
    db.Column(
        "assessment_id",
        db.Integer(),
        db.ForeignKey("presentation_assessments.id"),
        primary_key=True,
    ),
    db.Column(
        "period_id",
        db.Integer(),
        db.ForeignKey("submission_periods.id"),
        primary_key=True,
    ),
)

# link sessions to rooms
session_to_rooms = db.Table(
    "session_to_rooms",
    db.Column(
        "session_id",
        db.Integer(),
        db.ForeignKey("presentation_sessions.id"),
        primary_key=True,
    ),
    db.Column("room_id", db.Integer(), db.ForeignKey("rooms.id"), primary_key=True),
)

# faculty to slots map
faculty_to_slots = db.Table(
    "faculty_to_slots",
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
    db.Column(
        "slot_id", db.Integer(), db.ForeignKey("schedule_slots.id"), primary_key=True
    ),
)

# submitter to slots map
submitter_to_slots = db.Table(
    "submitter_to_slots",
    db.Column(
        "submitter_id",
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        primary_key=True,
    ),
    db.Column(
        "slot_id", db.Integer(), db.ForeignKey("schedule_slots.id"), primary_key=True
    ),
)

# original faculty to slots map - used for reverting
orig_fac_to_slots = db.Table(
    "orig_fac_to_slots",
    db.Column(
        "faculty_id", db.Integer(), db.ForeignKey("faculty_data.id"), primary_key=True
    ),
    db.Column(
        "slot_id", db.Integer(), db.ForeignKey("schedule_slots.id"), primary_key=True
    ),
)

# orig submitter to slots map - used for reverting
orig_sub_to_slots = db.Table(
    "orig_sub_to_slots",
    db.Column(
        "submitter_id",
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        primary_key=True,
    ),
    db.Column(
        "slot_id", db.Integer(), db.ForeignKey("schedule_slots.id"), primary_key=True
    ),
)

# assessor attendance: available
assessor_available_sessions = db.Table(
    "assessor_available",
    db.Column(
        "assessor_id",
        db.Integer(),
        db.ForeignKey("assessor_attendance_data.id"),
        primary_key=True,
    ),
    db.Column(
        "session_id",
        db.Integer(),
        db.ForeignKey("presentation_sessions.id"),
        primary_key=True,
    ),
)

# assessor attendance: unavailable
assessor_unavailable_sessions = db.Table(
    "assessor_unavailable",
    db.Column(
        "assessor_id",
        db.Integer(),
        db.ForeignKey("assessor_attendance_data.id"),
        primary_key=True,
    ),
    db.Column(
        "session_id",
        db.Integer(),
        db.ForeignKey("presentation_sessions.id"),
        primary_key=True,
    ),
)

# assessor attendance: if needed
assessor_ifneeded_sessions = db.Table(
    "assessor_ifneeded",
    db.Column(
        "assessor_id",
        db.Integer(),
        db.ForeignKey("assessor_attendance_data.id"),
        primary_key=True,
    ),
    db.Column(
        "session_id",
        db.Integer(),
        db.ForeignKey("presentation_sessions.id"),
        primary_key=True,
    ),
)

# submitter attendance: available
submitter_available_sessions = db.Table(
    "submitter_available",
    db.Column(
        "submitter_id",
        db.Integer(),
        db.ForeignKey("submitter_attendance_data.id"),
        primary_key=True,
    ),
    db.Column(
        "session_id",
        db.Integer(),
        db.ForeignKey("presentation_sessions.id"),
        primary_key=True,
    ),
)

# submitter attendance: available
submitter_unavailable_sessions = db.Table(
    "submitter_unavailable",
    db.Column(
        "submitter_id",
        db.Integer(),
        db.ForeignKey("submitter_attendance_data.id"),
        primary_key=True,
    ),
    db.Column(
        "session_id",
        db.Integer(),
        db.ForeignKey("presentation_sessions.id"),
        primary_key=True,
    ),
)

# ACCESS CONTROL LISTS

# generated assets
generated_acl = db.Table(
    "acl_generated",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("generated_assets.id"), primary_key=True
    ),
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

generated_acr = db.Table(
    "acr_generated",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("generated_assets.id"), primary_key=True
    ),
    db.Column("role_id", db.Integer(), db.ForeignKey("roles.id"), primary_key=True),
)

# temporary assets
temporary_acl = db.Table(
    "acl_temporary",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("temporary_assets.id"), primary_key=True
    ),
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

temporary_acr = db.Table(
    "acr_temporary",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("temporary_assets.id"), primary_key=True
    ),
    db.Column("role_id", db.Integer(), db.ForeignKey("roles.id"), primary_key=True),
)

# submitted assets
submitted_acl = db.Table(
    "acl_submitted",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("submitted_assets.id"), primary_key=True
    ),
    db.Column("user_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True),
)

submitted_acr = db.Table(
    "acr_submitted",
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("submitted_assets.id"), primary_key=True
    ),
    db.Column("role_id", db.Integer(), db.ForeignKey("roles.id"), primary_key=True),
)

## EMAIL LOG

# recipient list
recipient_list = db.Table(
    "email_log_recipients",
    db.Column(
        "email_id", db.Integer(), db.ForeignKey("email_log.id"), primary_key=True
    ),
    db.Column(
        "recipient_id", db.Integer(), db.ForeignKey("users.id"), primary_key=True
    ),
)

## MATCHING ROLES

# main role list
matching_role_list = db.Table(
    "matching_to_roles",
    db.Column(
        "record_id",
        db.Integer(),
        db.ForeignKey("matching_records.id"),
        primary_key=True,
    ),
    db.Column(
        "role_id", db.Integer(), db.ForeignKey("matching_roles.id"), primary_key=True
    ),
)

# original role list (to support reversion of changes)
matching_role_list_original = db.Table(
    "matching_to_roles_original",
    db.Column(
        "record_id",
        db.Integer(),
        db.ForeignKey("matching_records.id"),
        primary_key=True,
    ),
    db.Column(
        "role_id", db.Integer(), db.ForeignKey("matching_roles.id"), primary_key=True
    ),
)

## BACKUP LABELS

backup_record_to_labels = db.Table(
    "backups_to_labels",
    db.Column("backup_id", db.Integer(), db.ForeignKey("backups.id"), primary_key=True),
    db.Column(
        "label_id", db.Integer(), db.ForeignKey("backup_labels.id"), primary_key=True
    ),
)

## FEEDBACK ASSETS

feedback_template_to_tags = db.Table(
    "feedback_template_to_tags",
    db.Column(
        "template_id",
        db.Integer(),
        db.ForeignKey("feedback_templates.id"),
        primary_key=True,
    ),
    db.Column(
        "tag_id", db.Integer(), db.ForeignKey("feedback_template_tags.id"), primary_key=True
    ),
)

feedback_recipe_to_assets = db.Table(
    "feedback_recipe_to_assets",
    db.Column(
        "recipe_id",
        db.Integer(),
        db.ForeignKey("feedback_recipes.id"),
        primary_key=True,
    ),
    db.Column(
        "asset_id", db.Integer(), db.ForeignKey("feedback_assets.id"), primary_key=True
    ),
)
