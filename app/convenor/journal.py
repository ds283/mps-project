#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from flask import current_app, flash, redirect, request, url_for
from flask_security import current_user, roles_accepted
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
from app.convenor import convenor

from ..database import db
from ..models import (
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    StudentJournalEntry,
    User,
    journal_entry_to_pclass_config,
)
from ..shared.context.global_context import render_template_context
from ..shared.utils import get_current_year, redirect_url
from ..shared.workflow_logging import log_db_commit
from ..tools import ServerSideSQLHandler
from .forms import AddJournalEntryFormFactory, EditJournalEntryFormFactory

_ROLES = ("faculty", "admin", "root", "office")


def _check_access(student):
    """
    Validate that the current user is allowed to inspect this student's journal.
    Returns True if access is granted, False otherwise (having already flashed an error).
    """
    if current_user.has_role("root"):
        return True

    if current_user.has_role("admin") or current_user.has_role("office"):
        student_tenant_ids = {t.id for t in student.user.tenants}
        user_tenant_ids = {t.id for t in current_user.tenants}
        if not student_tenant_ids.intersection(user_tenant_ids):
            flash(
                "You do not have permission to view the journal for this student.",
                "error",
            )
            return False
        return True

    # faculty/convenor: must be an actual convenor
    faculty_data = current_user.faculty_data
    if faculty_data is None or not faculty_data.is_convenor:
        flash(
            "You do not have permission to view the journal for this student.",
            "error",
        )
        return False

    return True


def _build_convenor_entry_filter(base_query):
    """
    For convenor users, restrict the base query to entries linked to pclasses the
    current user convenes or co-convenes.
    """
    faculty_data = current_user.faculty_data
    convenor_pclass_ids = (
        [pc.id for pc in faculty_data.convenor_projects] if faculty_data else []
    )

    if not convenor_pclass_ids:
        # Convenor with no project classes: show nothing
        return base_query.filter(False)

    return (
        base_query.join(
            journal_entry_to_pclass_config,
            journal_entry_to_pclass_config.c.entry_id == StudentJournalEntry.id,
        )
        .join(
            ProjectClassConfig,
            ProjectClassConfig.id == journal_entry_to_pclass_config.c.config_id,
        )
        .filter(ProjectClassConfig.pclass_id.in_(convenor_pclass_ids))
        .distinct()
    )


@convenor.route("/student_journal/<int:student_id>")
@roles_accepted(*_ROLES)
def student_journal_inspector(student_id):
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/journal/inspector.html",
        student=student,
        url=url,
        text=text,
    )


@convenor.route("/journal_ajax/<int:student_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def student_journal_ajax(student_id):
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return redirect(redirect_url())

    base_query = (
        db.session.query(StudentJournalEntry)
        .join(User, User.id == StudentJournalEntry.owner_id, isouter=True)
        .filter(StudentJournalEntry.student_id == student_id)
    )

    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("office")
    ):
        base_query = _build_convenor_entry_filter(base_query)

    columns = {
        "timestamp": {"order": StudentJournalEntry.created_timestamp},
        "year": {"order": StudentJournalEntry.config_year},
        "classes": {},
        "title": {
            "order": StudentJournalEntry.title,
            "search": StudentJournalEntry.title,
        },
        "owner": {
            "search": func.concat(User.first_name, " ", User.last_name),
            "order": [User.last_name, User.first_name],
            "search_collation": "utf8_general_ci",
        },
        "actions": {},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            lambda items: ajax.convenor.journal_data(items, student)
        )


@convenor.route("/add_journal_entry/<int:student_id>", methods=["GET", "POST"])
@roles_accepted(*_ROLES)
def add_journal_entry(student_id):
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.student_journal_inspector", student_id=student_id)
    )
    text = request.args.get("text", "Back to journal")

    JournalForm = AddJournalEntryFormFactory(current_user)
    form = JournalForm(request.form)

    if form.validate_on_submit():
        config_year = get_current_year()
        entry = StudentJournalEntry(
            student_id=student.id,
            config_year=config_year,
            created_timestamp=datetime.now(),
            owner_id=current_user.id,
            title=form.title.data,
            entry=form.entry.data,
        )

        try:
            db.session.add(entry)
            db.session.flush()

            for pclass_config in form.project_classes.data:
                entry.project_classes.append(pclass_config)

            log_db_commit(
                f"Added journal entry for student {student.user.name}",
                user=current_user,
                student=student,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not save journal entry due to a database error. Please contact a system administrator.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(
            url_for(
                "convenor.student_journal_inspector",
                student_id=student_id,
                url=url,
                text=text,
            )
        )

    return render_template_context(
        "convenor/journal/edit_entry.html",
        form=form,
        student=student,
        entry=None,
        title="Add journal entry",
        url=url,
        text=text,
    )


@convenor.route("/edit_journal_entry/<int:entry_id>", methods=["GET", "POST"])
@roles_accepted(*_ROLES)
def edit_journal_entry(entry_id):
    entry: StudentJournalEntry = StudentJournalEntry.query.get_or_404(entry_id)

    if entry.owner_id is None or entry.owner_id != current_user.id:
        flash("You can only edit journal entries that you created.", "error")
        return redirect(redirect_url())

    student: StudentData = entry.student

    url = request.args.get(
        "url",
        url_for("convenor.student_journal_inspector", student_id=student.id),
    )
    text = request.args.get("text", "Back to journal")

    JournalForm = EditJournalEntryFormFactory(current_user)
    form = JournalForm(obj=entry)

    if form.validate_on_submit():
        entry.title = form.title.data
        entry.entry = form.entry.data
        entry.project_classes = list(form.project_classes.data)

        try:
            log_db_commit(
                f"Edited journal entry for student {student.user.name}",
                user=current_user,
                student=student,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not save journal entry due to a database error. Please contact a system administrator.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context(
        "convenor/journal/edit_entry.html",
        form=form,
        student=student,
        entry=entry,
        title="Edit journal entry",
        url=url,
        text=text,
    )


@convenor.route("/delete_journal_entry/<int:entry_id>")
@roles_accepted(*_ROLES)
def delete_journal_entry(entry_id):
    entry: StudentJournalEntry = StudentJournalEntry.query.get_or_404(entry_id)

    if entry.owner_id is None or entry.owner_id != current_user.id:
        flash("You can only delete journal entries that you created.", "error")
        return redirect(redirect_url())

    student: StudentData = entry.student
    student_id = student.id

    url = request.args.get(
        "url",
        url_for("convenor.student_journal_inspector", student_id=student_id),
    )

    try:
        db.session.delete(entry)
        log_db_commit(
            f"Deleted journal entry for student {student.user.name}",
            user=current_user,
            student=student,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Could not delete journal entry due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)
