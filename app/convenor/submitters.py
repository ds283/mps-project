#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime, timedelta

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask_security import current_user, roles_accepted
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

import app.ajax as ajax
from app.convenor import convenor

from ..database import db
from ..models import (
    DegreeProgramme,
    DegreeType,
    FeedbackReport,
    GeneratedAsset,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    User,
)
from ..shared.context.convenor_dashboard import (
    get_convenor_dashboard_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.convenor import (
    add_blank_submitter,
)
from ..shared.conversions import is_integer
from ..shared.utils import (
    build_enrol_submitter_candidates,
    build_submitters_data,
    get_current_year,
    redirect_url,
)
from ..shared.validators import (
    validate_is_administrator,
    validate_is_convenor,
)
from ..shared.journal import create_auto_journal_entry
from ..shared.workflow_logging import log_db_commit
from ..tools import ServerSideSQLHandler
from .forms import (
    AddSubmitterRoleForm,
    ConfirmDeleteWithReasonForm,
    EditRolesFormFactory,
    EditSubmissionRoleForm,
)


@convenor.route("/submitters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def submitters(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")
    data_display = request.args.get("data_display")

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    submitters = config.submitting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for sub in submitters:
        cohorts.add(sub.student.cohort)

        academic_year = sub.academic_year
        if academic_year is not None:
            years.add(academic_year)

        programmes.add(sub.student.programme_id)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active.is_(True))
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_submitters_cohort_filter"):
        cohort_filter = session["convenor_submitters_cohort_filter"]

    if (
            isinstance(cohort_filter, str)
            and cohort_filter != "all"
            and int(cohort_filter) not in cohorts
    ):
        cohort_filter = "all"

    if cohort_filter is not None:
        session["convenor_submitters_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_submitters_prog_filter"):
        prog_filter = session["convenor_submitters_prog_filter"]

    if (
            isinstance(prog_filter, str)
            and prog_filter != "all"
            and int(prog_filter) not in programmes
    ):
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_submitters_prog_filter"] = prog_filter

    if state_filter is None and session.get("convenor_submitters_state_filter"):
        state_filter = session["convenor_submitters_state_filter"]

    if isinstance(state_filter, str) and state_filter not in [
        "all",
        "published",
        "unpublished",
        "late-feedback",
        "no-late-feedback",
        "report",
        "no-report",
        "attachments",
        "no-attachments",
        "twd",
    ]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_submitters_state_filter"] = state_filter

    if year_filter is None and session.get("convenor_submitters_year_filter"):
        year_filter = session["convenor_submitters_year_filter"]

    if (
            isinstance(year_filter, str)
            and year_filter != "all"
            and int(year_filter) not in years
    ):
        year_filter = "all"

    if year_filter is not None:
        session["convenor_submitters_year_filter"] = year_filter

    if data_display is None and session.get("convenor_submitters_data_display"):
        data_display = session["convenor_submitters_data_display"]

    if isinstance(data_display, str) and data_display not in [
        "name",
        "number",
        "both-name",
        "both-number",
    ]:
        data_display = "name"

    if data_display is not None:
        session["convenor_submitters_data_display"] = data_display

    # build list of student emails for passing to local email client via mailto: list
    submitters = build_submitters_data(
        config, cohort_filter, prog_filter, state_filter, year_filter
    )
    emails = [s.student.user.email for s in submitters]

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/submitters.html",
        pane="submitters",
        subpane="list",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        submitter_emails=emails,
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        state_filter=state_filter,
        year_filter=year_filter,
        data_display=data_display,
    )


@convenor.route("/submitters_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def submitters_ajax(id):
    """
    Ajax data point for submitters view
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")
    data_display = request.args.get("data_display")

    show_name = True
    show_number = False
    sort_number = False

    if data_display == "number":
        show_name = False
        show_number = True
        sort_number = True
    elif data_display == "both-name":
        show_number = True
    elif data_display == "both-number":
        show_number = True
        sort_number = True

    data = build_submitters_data(
        config, cohort_filter, prog_filter, state_filter, year_filter
    )

    return ajax.convenor.submitters_data(
        data, config, show_name, show_number, sort_number
    )


@convenor.route("/enrol_submitters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def enrol_submitters(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    if (
            config.submitter_lifecycle
            >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER
    ):
        flash(
            "Manual enrolment of selectors is no longer possible at this stage in the project lifecycle.",
            "error",
        )
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    candidates = build_enrol_submitter_candidates(config)

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for student in candidates:
        cohorts.add(student.cohort)
        programmes.add(student.programme_id)

        academic_year = student.academic_year
        if academic_year is not None:
            years.add(academic_year)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active.is_(True))
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_sub_enroll_cohort_filter"):
        cohort_filter = session["convenor_sub_enroll_cohort_filter"]

    if cohort_filter is not None:
        session["convenor_sel_enroll_cohort_filter"] = cohort_filter

    if cohort_filter is not None:
        session["convenor_sub_enroll_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_sub_enroll_prog_filter"):
        prog_filter = session["convenor_sub_enroll_prog_filter"]

    if (
            isinstance(prog_filter, str)
            and prog_filter != "all"
            and int(prog_filter) not in programmes
    ):
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_sub_enroll_prog_filter"] = prog_filter

    if year_filter is None and session.get("convenor_sub_enroll_year_filter"):
        year_filter = session["convenor_sub_enroll_year_filter"]

    if (
            isinstance(year_filter, str)
            and year_filter != "all"
            and int(year_filter) not in years
    ):
        year_filter = "all"

    if year_filter is not None:
        session["convenor_sub_enroll_year_filter"] = year_filter

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/enrol_submitters.html",
        pane="submitters",
        subpane="enroll",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        year_filter=year_filter,
    )


@convenor.route("/enrol_submitters_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def enrol_submitters_ajax(id):
    """
    Ajax data point for enroll submitters view
    :param id:
    :return:
    """

    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    if (
            config.submitter_lifecycle
            >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER
    ):
        return jsonify({})

    candidates = build_enrol_submitter_candidates(config)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    if year_flag:
        candidates = [
            s
            for s in candidates.all()
            if s.academic_year is None
               or (not s.has_graduated and s.academic_year == year_value)
        ]
    else:
        candidates = candidates.all()

    return ajax.convenor.enrol_submitters_data(candidates, config)


@convenor.route("/enroll_all_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_all_submitters(configid):
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if (
            config.submitter_lifecycle
            > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY
    ):
        flash(
            "Manual enrolment of submitters is only possible during normal project activity",
            "error",
        )
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    # get current year
    current_year = get_current_year()
    old_config: ProjectClassConfig = config.project_class.get_config(config.year - 1)

    candidates = build_enrol_submitter_candidates(config)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    if year_flag:
        candidates = [
            s
            for s in candidates.all()
            if (s.academic_year is None or s.academic_yea == year_value)
        ]
    else:
        candidates = candidates.all()

    for c in candidates:
        add_blank_submitter(
            c,
            old_config.id if old_config is not None else None,
            configid,
            autocommit=False,
        )

    try:
        log_db_commit(
            'Bulk-enrolled {count} submitters for project class "{proj}"'.format(
                count=len(candidates), proj=config.project_class.name
            ),
            user=current_user,
            project_classes=config.project_class,
        )
        flash(
            'Added {count} submitters to project "{proj}"'.format(
                count=len(candidates), proj=config.project_class.name
            ),
            "info",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Could not add submitters because a database error occurred. Please check the logs for further information.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/enrol_submitter/<int:sid>/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_submitter(sid, configid):
    """
    Manually enroll a student as a submitter
    :param sid:
    :param configid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # return 404 if student does not exist
    student: StudentData = StudentData.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if (
            config.submitter_lifecycle
            > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY
    ):
        if not validate_is_administrator(message=False):
            flash(
                "Manual enrolment of submitters is only possible during normal project activity. "
                "Please contact an administrator to perform this operation.",
                "error",
            )
            return redirect(redirect_url())

    old_config: ProjectClassConfig = config.project_class.get_config(config.year - 1)

    add_blank_submitter(
        student,
        old_config.id if old_config is not None else None,
        configid,
        autocommit=True,
    )

    return redirect(redirect_url())


@convenor.route("/remove_feedback_report/<int:rec_id>")
@roles_accepted("faculty", "admin", "root")
def remove_feedback_report(rec_id):
    """
    Manually remove feedback reports from a SubmissionRecord
    :param sid:
    :return:
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(rec_id)

    sub: SubmittingStudent = record.owner
    config: ProjectClassConfig = sub.config
    pclass: ProjectClass = config.project_class

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    expiry_date = datetime.now() + timedelta(days=30)

    try:
        for report in record.feedback_reports:
            report: FeedbackReport
            asset: GeneratedAsset = report.asset

            asset.expiry = expiry_date
            record.feedback_reports.remove(report)
            db.session.delete(report)

        record.feedback_generated = False

        log_db_commit(
            "Removed feedback reports from submission record for submitter",
            user=current_user,
            student=sub.student,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Could not remove feedback reports for this submitter due to a database error ("{n}"). Please contact a system administrator.'.format(
                n=e
            ),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/delete_submitter/<int:sid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def delete_submitter(sid):
    """
    Manually delete a submitter. Shows a confirmation form that also collects a reason,
    which is recorded in the student's journal.
    """
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    if (
            sub.config.submitter_lifecycle
            > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY
    ):
        flash(
            "Manual deletion of submitters is only possible during normal project activity",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    form = ConfirmDeleteWithReasonForm(request.form)

    if form.validate_on_submit():
        student = sub.student
        pclass = sub.config.project_class
        config = sub.config
        reason = form.reason.data

        programme_name = student.programme.full_name if student.programme else "unknown"
        academic_year = f"Year {student.academic_year}" if student.academic_year else "unknown"
        year = config.year
        year_str = f"{year}/{str(year + 1)[-2:]}" if isinstance(year, int) else str(year)
        journal_html = (
            f"<p>Submitting student record deleted for project class "
            f"<strong>{pclass.name}</strong> ({year_str}).</p>"
            f"<ul>"
            f"<li>Student academic year: {academic_year}</li>"
            f"<li>Degree programme: {programme_name}</li>"
            f"<li>Action initiated by: {current_user.name}</li>"
            f"</ul>"
            f"<p><strong>Reason for deletion:</strong> {reason}</p>"
            f"<p><em>This entry was created automatically.</em></p>"
        )

        try:
            sub.detach_records()
            db.session.delete(sub)
            db.session.flush()

            create_auto_journal_entry(student, journal_html, project_class_config=config)

            log_db_commit(
                "Deleted submitter record",
                user=current_user,
                student=student,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                'Could not delete submitter due to a database error ("{n}"). Please contact a system administrator.'.format(
                    n=e
                ),
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    title = 'Delete submitter "{name}"'.format(name=sub.student.user.name)
    panel_title = 'Delete submitter <i class="fas fa-user-circle"></i> <strong>{name}</strong>'.format(
        name=sub.student.user.name
    )
    message = (
        '<p>Are you sure that you wish to delete submitter <i class="fas fa-user-circle"></i> <strong>{name}</strong>?</p>'
        "<p>This action cannot be undone.</p>".format(name=sub.student.user.name)
    )

    return render_template_context(
        "convenor/journal/delete_with_reason.html",
        form=form,
        title=title,
        panel_title=panel_title,
        action_url=url_for("convenor.delete_submitter", sid=sid, url=url),
        message=message,
        cancel_url=url,
    )


@convenor.route("/delete_all_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def delete_all_submitters(configid):
    """
    Delete all submitters -- confirmation step
    :param configid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if (
            config.submitter_lifecycle
            > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY
    ):
        flash(
            "Manual deletion of submitters is only possible during normal project activity",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = "Delete all submitters"
    panel_title = "Delete all submitters"

    action_url = url_for(
        "convenor.do_delete_all_submitters", configid=configid, url=url
    )
    message = (
        "<p>Are you sure that you wish to delete <strong>all submitters</strong>?"
        "<p>This action cannot be undone.</p>"
    )
    submit_label = "Delete all submitters"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/do_delete_all_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_all_submitters(configid):
    """
    Delete all submitters -- action step
    :param sid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if (
            config.submitter_lifecycle
            > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY
    ):
        flash(
            "Manual deletion of submitters is only possible during normal project activity",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        submitter_list = config.submitting_students

        for item in submitter_list:
            item.detach_records()
            db.session.delete(item)

        log_db_commit(
            'Deleted all submitters for project class "{proj}"'.format(proj=config.project_class.name),
            user=current_user,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Could not delete all submitters due to a database error ("{n}"). Please contact a system '
            "administrator.".format(n=e),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/edit_roles/<int:sub_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_roles(sub_id):
    # sub_id is a SubmittingStudent instance
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(sub_id)
    config: ProjectClassConfig = sub.config
    pclass: ProjectClass = config.project_class
    student: StudentData = sub.student
    user: User = student.user

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    EditRolesForm = EditRolesFormFactory(config)
    form = EditRolesForm(request.form)

    # determine whether a specific SubmissionRecord instance has been provided, otherwise use the one from the
    # selector form, or default to the current submission period
    record_id = request.args.get("record_id", None)
    if record_id is not None:
        record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

        # check that record actually belongs to the specified SubmittingStudent instance
        if record.owner_id != sub.id:
            flash(
                "Cannot edit roles for this combination of submitter and submission record, "
                "because the specified submission record does not belong to the student.",
                "error",
            )
            return redirect(redirect_url())
    else:
        if hasattr(form, "selector") and form.selector.data is not None:
            record: SubmissionRecord = sub.get_assignment(period=form.selector.data)
        else:
            record = sub.get_assignment()

    period: SubmissionPeriodRecord = record.period

    if hasattr(form, "selector"):
        form.selector.data = period

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None and text is None:
        url = url_for("convenor.submitters", id=pclass.id)
        text = "convenor submitters view"

    return render_template_context(
        "convenor/submitter/edit_roles.html",
        form=form,
        pclass=pclass,
        config=config,
        record=record,
        sub=sub,
        student=student,
        user=user,
        period=period,
        url=url,
        text=text,
    )


@convenor.route("edit_roles_ajax/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_roles_ajax(record_id):
    # sub_id is a SubmissionRecord instance
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None and text is None:
        url = url_for("convenor.submitters", id=pclass.id)
        text = "convenor submitters view"

    base_query = record.roles.join(User, User.id == SubmissionRole.user_id)

    name = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "urf8_general_ci",
    }
    role = {"order": SubmissionRole.role}

    columns = {"name": name, "role": role}

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(roles):
            return ajax.convenor.edit_roles(
                roles,
                return_url=url_for(
                    "convenor.edit_roles",
                    sub_id=sub.id,
                    record_id=record.id,
                    url=url,
                    text=text,
                ),
            )

        return handler.build_payload(row_formatter)


@convenor.route("/delete_role/<int:role_id>")
@roles_accepted("faculty", "admin", "root")
def delete_role(role_id):
    # role_id is a SubmissionRole
    role = SubmissionRole.query.get_or_404(role_id)

    record: SubmissionRecord = role.submission
    sub: SubmittingStudent = record.owner
    student: StudentData = sub.student
    sub_user: User = student.user
    role_user: User = role.user
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for(
            "convenor.edit_roles",
            sub_id=sub.id,
            record_id=record.id,
            url=url_for(
                "convenor.submitters",
                id=config.project_class.id,
                text="convenor submitters view",
            ),
        )

    title = "Delete role"
    panel_title = f'Delete {role.role_as_str} role for <i class="fas fa-user-circle"></i> <strong>{sub_user.name}</strong>'

    action_url = url_for("convenor.perform_delete_role", role_id=role_id, url=url)
    message = f'<p>Please confirm that you wish to delete the {role.role_as_str} role for <i class="fas fa-user-circle"></i> <strong>{role_user.name}</strong> belonging to submitter <i class="fas fa-user-circle"></i> <strong>{sub_user.name}</strong>.</p><p>This action cannot be undone.</p>'
    submit_label = "Delete role"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/perform_delete_role/<int:role_id>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_role(role_id):
    # role_id is a SubmissionRole
    role = SubmissionRole.query.get_or_404(role_id)

    record: SubmissionRecord = role.submission
    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for("convenor.edit_roles", sub_id=sub.id, record_id=record.id)

    try:
        db.session.delete(role)

        log_db_commit(
            "Deleted submission role from submission record",
            user=current_user,
            student=sub.student,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete role due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(url)


@convenor.route("/add_role/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_role(record_id):
    # sub_id is a SubmissionRecord instance
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for(
            "convenor.edit_roles",
            sub_id=sub.id,
            record_id=record.id,
            url=url_for("convenor.submitters", id=config.project_class.id),
            text="convenor submitters view",
        )

    form = AddSubmitterRoleForm(request.form)
    form._record = record

    if form.validate_on_submit():
        weight = 1.0
        role = form.role.data

        if role in [SubmissionRole.ROLE_MARKER]:
            weight = 1.0 / float(period.number_markers)

        role = SubmissionRole.build_(
            role=role,
            user=form.user.data.user,
            submission_id=record.id,
            weight=weight,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(role)
            log_db_commit(
                "Added new submission role to submission record",
                user=current_user,
                student=sub.student,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new role due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)
    elif request.method == "GET":
        if len(record.supervisor_roles) == 0:
            form.role.data = SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR
        else:
            form.role.data = SubmissionRole.ROLE_MARKER

    return render_template_context(
        "convenor/submitter/add_role.html",
        form=form,
        record=record,
        period=period,
        config=config,
        sub=sub,
        url=url,
    )


@convenor.route("/edit_role/<int:role_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_role(role_id):
    # role_id is a SubmissionRole
    role: SubmissionRole = SubmissionRole.query.get_or_404(role_id)

    record: SubmissionRecord = role.submission
    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.edit_roles", sub_id=sub.id, record_id=record.id)

    form = EditSubmissionRoleForm(obj=role)

    if form.validate_on_submit():
        role.role = form.role.data

        # only update marking-related fields for supervisor/responsible supervisor roles
        if form.role.data in [
            SubmissionRole.ROLE_SUPERVISOR,
            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
        ]:
            role.marking_distributed = form.marking_distributed.data
            role.external_marking_url = (
                form.external_marking_url.data
                if form.external_marking_url.data
                else None
            )
            role.grade = form.grade.data
            role.weight = form.weight.data
            role.justification = (
                form.justification.data if form.justification.data else None
            )

        role.last_edit_id = current_user.id
        role.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                "Saved changes to submission role",
                user=current_user,
                student=sub.student,
                project_classes=config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to role due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/submitter/edit_role.html",
        form=form,
        role=role,
        record=record,
        period=period,
        config=config,
        sub=sub,
        url=url,
    )
