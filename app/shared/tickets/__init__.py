#
# Created by David Seery on 21/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Ticket service layer: the pure, request-context-free core of the ticket system (scope derivation,
routing/auto-assign, subscriptions, event log, state transitions, permissions). UI phases build on
these; none of the functions commit — the caller owns the transaction (log_db_commit()).
"""

from .actions import (
    add_comment,
    add_label,
    assign,
    change_status,
    log_email,
    remove_label,
    unassign,
)
from .administrators import admin_root_users_for
from .candidates import (
    SEARCH_LIMIT,
    authorized,
    candidates_for,
    faculty_classes,
    faculty_related_student_query,
    faculty_selectee_query,
    faculty_supervisee_query,
    is_office_like,
    name_filter,
    resolve_convenor_pclass,
    resolve_token,
    scope_kind_for,
    student_name,
    target_tenant_id,
    token_for,
    user_tenant_ids,
)
from .events import record_event, touch
from .permissions import (
    can_assign,
    can_change_status,
    can_comment,
    can_edit_scope,
    can_label,
    can_manage_labels,
    can_manage_subscribers,
    can_view,
    is_admin_or_root,
    is_assignee,
    is_convenor_in_scope,
)
from .read_state import is_unread, mark_read, record_inbox_visit
from .routing import apply_auto_assign
from .scope import (
    class_convenor_users,
    compute_scope_classes,
    convenors_in_scope,
    derive_tenant_id,
    home_class,
    primary_convenor_user,
    recompute_scope,
)
from .subjects import add_subject, create_ticket, remove_subject
from .subscriptions import (
    add_external_subscriber,
    is_subscribed,
    remove_external_subscriber,
    subscribe,
    sync_convenor_subscriptions,
    unsubscribe,
)

__all__ = [
    "SEARCH_LIMIT",
    "add_comment",
    "add_external_subscriber",
    "add_label",
    "add_subject",
    "admin_root_users_for",
    "apply_auto_assign",
    "assign",
    "authorized",
    "can_assign",
    "can_change_status",
    "can_comment",
    "can_edit_scope",
    "can_label",
    "can_manage_labels",
    "can_manage_subscribers",
    "can_view",
    "candidates_for",
    "change_status",
    "class_convenor_users",
    "compute_scope_classes",
    "convenors_in_scope",
    "create_ticket",
    "derive_tenant_id",
    "faculty_classes",
    "faculty_related_student_query",
    "faculty_selectee_query",
    "faculty_supervisee_query",
    "home_class",
    "is_admin_or_root",
    "is_assignee",
    "is_convenor_in_scope",
    "is_office_like",
    "is_subscribed",
    "is_unread",
    "log_email",
    "mark_read",
    "name_filter",
    "primary_convenor_user",
    "record_event",
    "record_inbox_visit",
    "recompute_scope",
    "remove_external_subscriber",
    "remove_label",
    "remove_subject",
    "resolve_convenor_pclass",
    "resolve_token",
    "scope_kind_for",
    "student_name",
    "subscribe",
    "sync_convenor_subscriptions",
    "target_tenant_id",
    "token_for",
    "touch",
    "unassign",
    "unsubscribe",
    "user_tenant_ids",
]
