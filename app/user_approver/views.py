#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime
from functools import partial

from flask import redirect, url_for, request, session
from flask_security import current_user, roles_required, roles_accepted
from sqlalchemy import and_, or_, func, String
from sqlalchemy.orm import aliased

import app.ajax as ajax
from . import user_approver
from ..database import db
from ..models import StudentData, DegreeProgramme, DegreeType, WorkflowMixin, User
from ..shared.context.global_context import render_template_context
from ..shared.conversions import is_integer
from ..shared.utils import redirect_url
from ..tools import ServerSideSQLHandler


@user_approver.route("/validate")
@roles_required("user_approver")
def validate():
    """
    Validate student records
    :return:
    """
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None or text is None:
        url = redirect_url()
        text = "approvals dashboard"

    prog_filter = request.args.get("prog_filter")

    if prog_filter is None and session.get("user_approver_prog_filter"):
        prog_filter = session["user_approver_prog_filter"]

    if prog_filter is not None:
        session["user_approver_prog_filter"] = prog_filter

    year_filter = request.args.get("year_filter")

    if year_filter is None and session.get("user_approver_year_filter"):
        year_filter = session["user_approver_year_filter"]

    if year_filter is not None:
        session["user_approver_year_filter"] = year_filter

    prog_query = db.session.query(StudentData.programme_id).distinct().subquery()
    programmes = (
        db.session.query(DegreeProgramme)
        .join(prog_query, prog_query.c.programme_id == DegreeProgramme.id)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )

    return render_template_context(
        "user_approver/validate.html", url=url, text=text, prog_filter=prog_filter, year_filter=year_filter, programmes=programmes
    )


@user_approver.route("/validate_ajax", methods=["GET", "POST"])
@roles_required("user_approver")
def validate_ajax():
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    base_query = (
        db.session.query(StudentData)
        .join(User, User.id == StudentData.id)
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .filter(
            StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
            or_(
                and_(StudentData.last_edit_id == None, StudentData.creator_id != current_user.id),
                and_(StudentData.last_edit_id != None, StudentData.last_edit_id != current_user.id),
            ),
        )
    )

    flag, prog_value = is_integer(prog_filter)
    if flag:
        base_query = base_query.filter(StudentData.programme_id == prog_value)

    flag, year_value = is_integer(year_filter)
    if flag:
        base_query = base_query.filter(StudentData.academic_year <= DegreeType.duration, StudentData.academic_year == year_value)
    elif year_filter == "grad":
        base_query = base_query.filter(StudentData.academic_year > DegreeType.duration)

    name = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    email = {"search": User.email, "order": User.email, "search_collation": "utf8_general_ci"}
    registration_number = {"search": func.cast(StudentData.registration_number, String), "order": StudentData.registration_number}
    programme = {"search": DegreeProgramme.name, "order": DegreeProgramme.name, "search_collation": "utf8_general_ci"}
    year = {"order": StudentData.academic_year}

    columns = {
        "name": name,
        "email": email,
        "registration_number": registration_number,
        "programme": programme,
        "year": year,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.user_approver.validate_data, url, text))


@user_approver.route("/approve/<int:id>")
@roles_required("user_approver")
def approve(id):
    record = StudentData.query.get_or_404(id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    record.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED
    record.validator_id = current_user.id
    record.validated_timestamp = datetime.now()
    db.session.commit()

    return redirect(url_for("user_approver.validate", url=url, text=text))


@user_approver.route("/reject/<int:id>")
@roles_required("user_approver")
def reject(id):
    record = StudentData.query.get_or_404(id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    record.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_REJECTED
    record.validator_id = current_user.id
    record.validated_timestamp = datetime.now()
    db.session.commit()

    return redirect(url_for("user_approver.validate", url=url, text=text))


@user_approver.route("/correct")
@roles_accepted("user_approver", "admin", "root")
def correct():
    """
    Correct a student record that has been rejected for containing errors
    :return:
    """
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None or text is None:
        url = redirect_url()
        text = "approvals dashboard"

    prog_filter = request.args.get("prog_filter")

    if prog_filter is None and session.get("user_approver_prog_filter"):
        prog_filter = session["user_approver_prog_filter"]

    if prog_filter is not None:
        session["user_approver_prog_filter"] = prog_filter

    year_filter = request.args.get("year_filter")

    if year_filter is None and session.get("user_approver_year_filter"):
        year_filter = session["user_approver_year_filter"]

    if year_filter is not None:
        session["user_approver_year_filter"] = year_filter

    prog_query = db.session.query(StudentData.programme_id).distinct().subquery()
    programmes = (
        db.session.query(DegreeProgramme)
        .join(prog_query, prog_query.c.programme_id == DegreeProgramme.id)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )

    return render_template_context(
        "user_approver/correct.html", url=url, text=text, prog_filter=prog_filter, year_filter=year_filter, programmes=programmes
    )


@user_approver.route("/correct_ajax", methods=["GET", "POST"])
@roles_accepted("user_approver", "admin", "root")
def correct_ajax():
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    student_user = aliased(User)
    validator_user = aliased(User)

    base_query = (
        db.session.query(StudentData)
        .join(student_user, student_user.id == StudentData.id)
        .join(validator_user, validator_user.id == StudentData.validator_id, isouter=True)
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .filter(
            StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED,
            or_(
                and_(StudentData.last_edit_id == None, StudentData.creator_id == current_user.id),
                and_(StudentData.last_edit_id != None, StudentData.last_edit_id == current_user.id),
            ),
        )
    )

    flag, prog_value = is_integer(prog_filter)
    if flag:
        base_query = base_query.filter(StudentData.programme_id == prog_value)

    flag, year_value = is_integer(year_filter)
    if flag:
        base_query = base_query.filter(StudentData.academic_year <= DegreeType.duration, StudentData.academic_year == year_value)
    elif year_filter == "grad":
        base_query = base_query.filter(StudentData.academic_year > DegreeType.duration)

    name = {
        "search": func.concat(student_user.first_name, " ", student_user.last_name),
        "order": [student_user.last_name, student_user.first_name],
        "search_collation": "utf8_general_ci",
    }
    email = {"search": student_user.email, "order": student_user.email, "search_collation": "utf8_general_ci"}
    registration_number = {"search": func.cast(StudentData.registration_number, String), "order": StudentData.registration_number}
    programme = {"search": DegreeProgramme.name, "order": DegreeProgramme.name, "search_collation": "utf8_general_ci"}
    year = {"order": StudentData.academic_year}
    rejected_by = {
        "search": func.concat(validator_user.first_name, " ", validator_user.last_name, " ", validator_user.email),
        "order": [validator_user.last_name, validator_user.first_name, validator_user.email],
        "search_collation": "utf8_general_ci",
    }

    columns = {
        "name": name,
        "email": email,
        "registration_number": registration_number,
        "programme": programme,
        "year": year,
        "rejected_by": rejected_by,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.user_approver.correction_data, url, text))
