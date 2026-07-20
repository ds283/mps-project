#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta

from flask import abort, current_app, flash, jsonify, redirect, request, url_for
from flask_security import current_user, roles_accepted
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

import app.ajax as ajax
from app.convenor import convenor

from ..database import db
from ..models import (
    ProjectClass,
    SelectingStudent,
    StudentData,
    StudentJournalEntry,
    SubmittingStudent,
    User,
)
from ..models.journal import journal_activity_summary, student_journal_entry_read, visible_entries_query
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.utils import get_current_year, redirect_url
from ..shared.validators import validate_is_convenor
from ..shared.workflow_logging import log_db_commit
from ..tools import ServerSideSQLHandler
from .forms import (
    AddJournalEntryFormFactory,
    EditJournalEntryFormFactory,
    JournalDrawerActionForm,
)

_JOURNAL_TAB_FILTERS = ("all", "unread", "month", "selectors", "submitters")


def _config_student_scope(config):
    """
    Selecting/submitting student ids (retired excluded) for a single ProjectClassConfig,
    for scoping the per-project-class Journal tab.
    """
    selecting_ids = {
        sid
        for (sid,) in db.session.query(SelectingStudent.student_id).filter(
            SelectingStudent.config_id == config.id, SelectingStudent.retired.is_(False)
        )
    }
    submitting_ids = {
        sid
        for (sid,) in db.session.query(SubmittingStudent.student_id).filter(
            SubmittingStudent.config_id == config.id, SubmittingStudent.retired.is_(False)
        )
    }
    return selecting_ids, submitting_ids


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


@convenor.route("/student_journal/<int:student_id>")
@roles_accepted(*_ROLES)
def student_journal_inspector(student_id):
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    JournalForm = AddJournalEntryFormFactory(current_user)

    return render_template_context(
        "convenor/journal/inspector.html",
        student=student,
        url=url,
        text=text,
        quick_add_form=JournalForm(),
        mark_read_form=JournalDrawerActionForm(),
    )


@convenor.route("/journal_ajax/<int:student_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def student_journal_ajax(student_id):
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return redirect(redirect_url())

    base_query = student.visible_journal_entries(current_user).join(User, User.id == StudentJournalEntry.owner_id, isouter=True)

    columns = {
        "timestamp": {"order": StudentJournalEntry.created_timestamp},
        "year": {"order": StudentJournalEntry.config_year},
        "classes": {},
        "type": {"order": StudentJournalEntry.entry_type},
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

    url = request.values.get(
        "url",
        url_for("convenor.student_journal_inspector", student_id=student_id),
    )
    text = request.values.get("text", "Back to journal")

    if url is not None:
        return_url = url_for(
            "convenor.student_journal_inspector",
            student_id=student.id,
            url=url,
            text=text,
        )
        return_text = "Journal entries"
    else:
        return_url = None
        return_text = None

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(lambda items: ajax.convenor.journal_data(items, return_url=return_url, return_text=return_text))


@convenor.route("/journal_drawer_ajax/<int:student_id>")
@roles_accepted(*_ROLES)
def journal_drawer_ajax(student_id):
    """
    Render the entry-list fragment shown in the shared journal drawer (offcanvas)
    for a single student. Visible entries only, newest first.
    """
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        abort(403)

    entries = student.visible_journal_entries(current_user).order_by(StudentJournalEntry.created_timestamp.desc()).all()
    counts = student.journal_counts(current_user)

    total_count = student.journal_entries.count()
    locked_count = max(total_count - counts["visible"], 0)

    return render_template_context(
        "convenor/journal/_drawer_body.html",
        student=student,
        entries=entries,
        counts=counts,
        locked_count=locked_count,
        recent_cutoff=datetime.now() - timedelta(days=30),
        mark_read_form=JournalDrawerActionForm(),
    )


@convenor.route("/journal_counts_ajax/<int:student_id>")
@roles_accepted(*_ROLES)
def journal_counts_ajax(student_id):
    """
    Return {visible, unread, recent} counts for a student's journal, scoped to
    entries visible to current_user. Used by refreshJournalIndicators() in the
    shared journal JS to repaint indicator chips after a change.
    """
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        abort(403)

    return jsonify(student.journal_counts(current_user))


@convenor.route("/quick_add_journal_entry/<int:student_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def quick_add_journal_entry(student_id):
    """
    Create a journal entry via AJAX from the shared quick-add modal.
    """
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return jsonify(success=False, message="You do not have permission to add a journal entry for this student."), 403

    JournalForm = AddJournalEntryFormFactory(current_user)
    form = JournalForm(request.form)

    if not form.validate_on_submit():
        return jsonify(success=False, errors=form.errors), 400

    config_year = get_current_year()
    entry = StudentJournalEntry(
        student_id=student.id,
        config_year=config_year,
        created_timestamp=datetime.now(),
        owner_id=current_user.id,
        title=form.title.data,
        entry_type=form.entry_type.data,
        entry=form.entry.data,
        restricted=form.restricted.data,
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
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify(success=False, message="Could not save journal entry due to a database error."), 500

    return jsonify(success=True)


@convenor.route("/journal_mark_all_read/<int:student_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def journal_mark_all_read(student_id):
    """
    Mark every entry currently visible to current_user as read, for use by the
    "Mark all read" action in the shared journal drawer.
    """
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return jsonify(success=False, message="You do not have permission to view the journal for this student."), 403

    form = JournalDrawerActionForm(request.form)
    if not form.validate_on_submit():
        return jsonify(success=False), 400

    for entry in student.visible_journal_entries(current_user).all():
        entry.mark_read(current_user)
    db.session.commit()

    return jsonify(success=True)


@convenor.route("/view_journal_entry/<int:entry_id>")
@roles_accepted(*_ROLES)
def view_journal_entry(entry_id):
    entry: StudentJournalEntry = StudentJournalEntry.query.get_or_404(entry_id)
    student: StudentData = entry.student

    if not _check_access(student):
        return redirect(redirect_url())

    if not entry.is_visible_to(current_user):
        abort(403)

    entry.mark_read(current_user)
    db.session.commit()

    url = request.args.get("url", url_for("convenor.student_journal_inspector", student_id=student.id))
    text = request.args.get("text", "Back to journal")

    return render_template_context(
        "convenor/journal/view_entry.html",
        entry=entry,
        student=student,
        url=url,
        text=text,
    )


@convenor.route("/add_journal_entry/<int:student_id>", methods=["GET", "POST"])
@roles_accepted(*_ROLES)
def add_journal_entry(student_id):
    student: StudentData = StudentData.query.get_or_404(student_id)

    if not _check_access(student):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.student_journal_inspector", student_id=student_id))
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
            entry_type=form.entry_type.data,
            entry=form.entry.data,
            restricted=form.restricted.data,
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
        entry.entry_type = form.entry_type.data
        entry.entry = form.entry.data
        entry.restricted = form.restricted.data
        entry.last_edit_timestamp = datetime.now()
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


@convenor.route("/journal_tab/<int:id>")
@roles_accepted("faculty", "admin", "root")
def journal_tab(id):
    """
    Top-level "Journal" dashboard tab for a project class: an aggregate, filterable list of
    all entries visible to the convenor across that project class's selectors and submitters.
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    filter_ = request.args.get("filter", "all")
    if filter_ not in _JOURNAL_TAB_FILTERS:
        filter_ = "all"

    selecting_ids, submitting_ids = _config_student_scope(config)
    student_ids = selecting_ids | submitting_ids

    summary = journal_activity_summary(current_user, student_ids, recent_limit=0)

    picker_students = []
    if student_ids:
        picker_students = (
            db.session.query(StudentData)
            .join(User, User.id == StudentData.id)
            .filter(StudentData.id.in_(student_ids))
            .order_by(User.last_name, User.first_name)
            .all()
        )

    JournalForm = AddJournalEntryFormFactory(current_user)

    return render_template_context(
        "convenor/dashboard/journal.html",
        pane="journal",
        pclass=pclass,
        config=config,
        convenor_data=get_convenor_dashboard_data(pclass, config),
        filter_=filter_,
        summary=summary,
        picker_students=picker_students,
        quick_add_form=JournalForm(),
        mark_read_form=JournalDrawerActionForm(),
    )


@convenor.route("/journal_tab_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def journal_tab_ajax(id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    if not validate_is_convenor(pclass):
        return jsonify({})

    config = pclass.most_recent_config
    if config is None:
        return jsonify({})

    filter_ = request.args.get("filter", "all")
    if filter_ not in _JOURNAL_TAB_FILTERS:
        filter_ = "all"

    selecting_ids, submitting_ids = _config_student_scope(config)

    if filter_ == "selectors":
        student_ids = selecting_ids
    elif filter_ == "submitters":
        student_ids = submitting_ids
    else:
        student_ids = selecting_ids | submitting_ids

    StudentUser = aliased(User)
    OwnerUser = aliased(User)

    base_query = (
        visible_entries_query(current_user, student_ids)
        .join(StudentData, StudentData.id == StudentJournalEntry.student_id)
        .join(StudentUser, StudentUser.id == StudentData.id)
        .join(OwnerUser, OwnerUser.id == StudentJournalEntry.owner_id, isouter=True)
    )

    recent_cutoff = datetime.now() - timedelta(days=30)

    if filter_ == "unread":
        read_entry_ids = db.session.query(student_journal_entry_read.c.entry_id).filter(student_journal_entry_read.c.user_id == current_user.id)
        base_query = base_query.filter(~StudentJournalEntry.id.in_(read_entry_ids))
    elif filter_ == "month":
        base_query = base_query.filter(StudentJournalEntry.created_timestamp >= recent_cutoff)

    columns = {
        "entry": {
            "order": StudentJournalEntry.title,
            "search": StudentJournalEntry.title,
        },
        "student": {
            "order": [StudentUser.last_name, StudentUser.first_name],
            "search": func.concat(StudentUser.first_name, " ", StudentUser.last_name),
            "search_collation": "utf8_general_ci",
        },
        "type": {"order": StudentJournalEntry.entry_type},
        "owner": {
            "order": [OwnerUser.last_name, OwnerUser.first_name],
            "search": func.concat(OwnerUser.first_name, " ", OwnerUser.last_name),
            "search_collation": "utf8_general_ci",
        },
        "timestamp": {"order": StudentJournalEntry.created_timestamp},
        "review": {},
    }

    with ServerSideSQLHandler(request, base_query, columns, secondary_order=[StudentJournalEntry.id.desc()]) as handler:
        return handler.build_payload(lambda items: ajax.convenor.journal_tab_data(items, pclass=pclass, recent_cutoff=recent_cutoff))
