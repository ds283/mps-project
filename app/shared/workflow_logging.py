#
# Created by David Seery on 26/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
workflow_logging.py
-------------------

Provides log_db_commit(), a wrapper around db.session.commit() that records a
WorkflowLogEntry before persisting the session.

Usage
-----

From a Flask route handler (endpoint is auto-detected from the request context):

    from app.shared.workflow_logging import log_db_commit

    db.session.add(some_object)
    log_db_commit("Created new submission record for Alice Smith (MSci Physics)")

From a Celery task (provide the task name explicitly):

    log_db_commit(
        "Rolled over project class MPhys",
        endpoint="app.tasks.rollover.rollover_pclass",
        project_classes=pclass,
    )

Parameters
----------
summary : str
    A human-readable description of the event. Should name any relevant students,
    faculty, or project classes so the log is useful without joining to other tables.

user : User | int | None
    The User instance or user id of the person who initiated the action. Pass None
    for background tasks where no user is directly involved.

project_classes : ProjectClass | list[ProjectClass] | None
    One or more ProjectClass instances that this event applies to.

endpoint : str | None
    The route name (e.g. ``"admin.global_config"``) or Celery task name
    (e.g. ``"app.tasks.rollover.rollover_pclass"``). When None, the function
    attempts to auto-detect:
    - Inside a Flask request context → ``flask.request.endpoint``
    - Inside a Celery task context → the current task name via celery.current_task

_commit : bool
    If True (the default) the session is committed after the log entry is added.
    Set to False when the caller manages its own commit inside a try/except block —
    the log entry will be flushed with the caller's subsequent db.session.commit().
"""

from datetime import datetime
from typing import List, Optional, Union

from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models.workflow_log import WorkflowLogEntry


def _resolve_endpoint(explicit: Optional[str]) -> Optional[str]:
    """Return the best available endpoint string."""
    if explicit is not None:
        return explicit

    # Try Flask request context first
    try:
        from flask import has_request_context, request

        if has_request_context() and request.endpoint:
            return request.endpoint
    except RuntimeError:
        pass

    # Try Celery current task
    try:
        from celery import current_task

        if current_task and current_task.name:
            return current_task.name
    except Exception:
        pass

    return None


def _resolve_user_id(user) -> Optional[int]:
    """Return the integer primary key for user, or None."""
    if user is None:
        return None

    if isinstance(user, int):
        return user

    # Assume a User-like ORM object with an .id attribute
    return getattr(user, "id", None)


def _resolve_student_id(student) -> Optional[int]:
    """Return the integer primary key for student, or None."""
    if student is None:
        return None

    if isinstance(student, int):
        return student

    # Assume either a User or StudentData instance with a .id attribute (they are guaranteed to be the same)
    return getattr(student, "id", None)


def _resolve_project_classes(project_classes) -> List:
    """Return a list of ProjectClass instances (possibly empty)."""
    if project_classes is None:
        return []

    if not isinstance(project_classes, (list, tuple)):
        return [project_classes]

    return list(project_classes)


def log_db_commit(
    summary: str,
    *,
    user=None,
    student=None,
    project_classes=None,
    endpoint: Optional[str] = None,
    _commit: bool = True,
) -> Optional[WorkflowLogEntry]:
    """
    Add a WorkflowLogEntry to the current session and (by default) commit it.

    Returns the newly created WorkflowLogEntry, or None if creation failed.
    On failure, does not roll back the session — the caller is responsible for
    its own error handling if _commit=False.  When _commit=True, a failed commit
    triggers a rollback and the exception is re-raised.
    """
    resolved_endpoint = _resolve_endpoint(endpoint)
    initiator_id = _resolve_user_id(user)
    student_id = _resolve_student_id(student)
    pclasses = _resolve_project_classes(project_classes)

    entry = WorkflowLogEntry(
        timestamp=datetime.now(),
        initiator_id=initiator_id,
        student_id=student_id,
        endpoint=resolved_endpoint,
        summary=summary,
    )

    # Associate project classes.  Because the relationship uses lazy="dynamic"
    # we must append after the object exists in the session.
    db.session.add(entry)
    for pc in pclasses:
        entry.project_classes.append(pc)

    if not _commit:
        return entry

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise

    return entry
