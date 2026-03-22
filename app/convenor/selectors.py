#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import date, datetime, timedelta
from functools import partial
from typing import List, Optional, Tuple
from uuid import uuid4

import parse
from celery import chain
from celery.result import AsyncResult
from dateutil import parser
from dateutil.relativedelta import relativedelta
from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_security import current_user, roles_accepted
from ordered_set import OrderedSet
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import class_mapper, with_polymorphic
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql import func, literal_column

import app.ajax as ajax

from ..admin.forms import EditEmailTemplateForm, LevelSelectorForm
from ..admin.views import create_new_email_template_labels
from ..database import db
from ..documents.forms import EditPeriodAttachmentForm, UploadPeriodAttachmentForm
from ..faculty.forms import (
    AddDescriptionFormFactory,
    AddProjectFormFactory,
    EditDescriptionContentForm,
    EditDescriptionSettingsFormFactory,
    EditProjectFormFactory,
    MoveDescriptionFormFactory,
    PresentationFeedbackForm,
    SkillSelectorForm,
    SubmissionRoleFeedbackForm,
    SubmissionRoleResponseForm,
)
from ..models import (
    BackupRecord,
    Bookmark,
    ConfirmRequest,
    ConvenorGenericTask,
    ConvenorSelectorTask,
    ConvenorSubmitterTask,
    ConvenorTask,
    CustomOffer,
    DegreeProgramme,
    DegreeType,
    EmailTemplate,
    EnrollmentRecord,
    FacultyData,
    FeedbackRecipe,
    FeedbackReport,
    FHEQ_Level,
    FilterRecord,
    GeneratedAsset,
    LiveProject,
    LiveProjectAlternative,
    MatchingRecord,
    MatchingRole,
    Module,
    PeriodAttachment,
    PopularityRecord,
    PresentationFeedback,
    Project,
    ProjectAlternative,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ResearchGroup,
    SelectingStudent,
    SelectionRecord,
    SkillGroup,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionPeriodUnit,
    SubmissionRecord,
    SubmissionRole,
    SubmittedAsset,
    SubmittingStudent,
    SupervisionEvent,
    SupervisionEventTemplate,
    Tenant,
    TransferableSkill,
    User,
    WorkflowMixin,
)
from ..projecthub.forms import ReassignEventOwnerFormFactory
from ..shared.actions import do_cancel_confirm, do_confirm, do_deconfirm_to_pending
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.convenor_dashboard import (
    build_convenor_tasks_query,
    get_capacity_data,
    get_convenor_approval_data,
    get_convenor_dashboard_data,
    get_convenor_todo_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.convenor import (
    add_blank_submitter,
    add_liveproject,
    add_selector,
    build_outstanding_confirmations_query,
)
from ..shared.conversions import is_integer
from ..shared.forms.forms import SelectSubmissionRecordFormFactory
from ..shared.projects import (
    create_new_tags,
    get_filter_list_for_groups_and_skills,
    project_list_in_memory_handler,
    project_list_SQL_handler,
)
from ..shared.quickfixes import (
    QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_AVAILABLE,
    QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_UNAVAILABLE,
)
from ..shared.security import validate_nonce
from ..shared.sqlalchemy import clone_model, get_count
from ..shared.utils import (
    build_enrol_selector_candidates,
    build_enrol_submitter_candidates,
    build_submitters_data,
    filter_assessors,
    get_convenor_filter_record,
    get_current_year,
    home_dashboard,
    home_dashboard_url,
    redirect_url,
)
from ..shared.validators import (
    validate_assign_feedback,
    validate_edit_description,
    validate_edit_project,
    validate_is_admin_or_convenor,
    validate_is_administrator,
    validate_is_convenor,
    validate_project_class,
    validate_project_open,
    validate_view_project,
)
from ..student.actions import store_selection
from ..task_queue import register_task
from ..tools import ServerSideInMemoryHandler, ServerSideSQLHandler
from ..tools.ServerSideProcessing import FakeQuery
from app.convenor import convenor
from .forms import (
    AddConvenorGenericTask,
    AddConvenorStudentTask,
    AddSubmissionPeriodUnitFormFactory,
    AddSubmitterRoleForm,
    AddSupervisionEventTemplateFormFactory,
    AssignPresentationFeedbackFormFactory,
    ChangeDeadlineFormFactory,
    CreateCustomOfferFormFactory,
    CustomCATSLimitForm,
    DuplicateProjectFormFactory,
    EditConvenorGenericTask,
    EditConvenorStudentTask,
    EditCustomOfferFormFactory,
    EditLiveProjectAlternativeForm,
    EditLiveProjectSupervisorsFactory,
    EditPeriodRecordFormFactory,
    EditProjectAlternativeForm,
    EditProjectConfigFormFactory,
    EditProjectSupervisorsFactory,
    EditRolesFormFactory,
    EditSubmissionPeriodRecordPresentationsForm,
    EditSubmissionPeriodUnitFormFactory,
    EditSubmissionRoleForm,
    EditSupervisionEventTemplateFormFactory,
    GoLiveFormFactory,
    IssueFacultyConfirmRequestFormFactory,
    ManualAssignFormFactory,
    OpenFeedbackFormFactory,
    TestOpenFeedbackForm,
)


@convenor.route("/selectors/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selectors(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

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

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)

        academic_year = sel.academic_year
        if academic_year is not None:
            years.add(academic_year)

        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active.is_(True))
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_selectors_cohort_filter"):
        cohort_filter = session["convenor_selectors_cohort_filter"]

    if (
            isinstance(cohort_filter, str)
            and cohort_filter not in ["all", "twd"]
            and int(cohort_filter) not in cohorts
    ):
        cohort_filter = "all"

    if cohort_filter is not None:
        session["convenor_selectors_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_selectors_prog_filter"):
        prog_filter = session["convenor_selectors_prog_filter"]

    if (
            isinstance(prog_filter, str)
            and prog_filter != "all"
            and int(prog_filter) not in programmes
    ):
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_selectors_prog_filter"] = prog_filter

    if state_filter is None and session.get("convenor_selectors_state_filter"):
        state_filter = session["convenor_selectors_state_filter"]

    if isinstance(state_filter, str) and state_filter not in [
        "all",
        "submitted",
        "bookmarks",
        "none",
        "confirmations",
        "custom",
    ]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_selectors_state_filter"] = state_filter

    if convert_filter is None and session.get("convenor_selectors_convert_filter"):
        convert_filter = session["convenor_selectors_convert_filter"]

    if isinstance(convert_filter, str) and convert_filter not in [
        "all",
        "convert",
        "no-convert",
    ]:
        convert_filter = "all"

    if convert_filter is not None:
        session["convenor_selectors_convert_filter"] = convert_filter

    if year_filter is None and session.get("convenor_selectors_year_filter"):
        year_filter = session["convenor_selectors_year_filter"]

    if (
            isinstance(year_filter, str)
            and year_filter != "all"
            and int(year_filter) not in years
    ):
        year_filter = "all"

    if year_filter is not None:
        session["convenor_selectors_year_filter"] = year_filter

    # get list of current published matchings (if any) that include this project type;
    # these can be used to filter for students that are/are not included in the matching
    if config.has_published_matches:
        matches = config.published_matches.all()
        match_ids = [x.id for x in matches]
    else:
        matches = None

    if match_filter is None and session.get("convenor_selectors_match_filter"):
        match_filter = session["convenor_selectors_match_filter"]

    if match_show is None and session.get("convenor_selectors_match_show"):
        match_show = session["convenor_selectors_match_show"]

    if matches is None:
        match_filter = "all"
        match_show = "all"
    else:
        if (
                isinstance(match_filter, str)
                and match_filter != "all"
                and int(match_filter) not in match_ids
        ):
            match_filter = "all"
            match_show = "all"

    if match_show not in ["all", "included", "missing"]:
        match_show = "all"

    if match_filter is not None:
        session["convenor_selectors_match_filter"] = match_filter

    if match_show is not None:
        session["convenor_selectors_match_show"] = match_show

    # build list of student emails for passing to local email client via mailto: list
    selectors = _build_selector_data(
        config,
        cohort_filter,
        prog_filter,
        state_filter,
        convert_filter,
        year_filter,
        match_filter,
        match_show,
    )
    emails = [s.student.user.email for s in selectors]

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/selectors.html",
        pane="selectors",
        subpane="list",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        matches=matches,
        selector_emails=emails,
        match_filter=match_filter,
        match_show=match_show,
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        state_filter=state_filter,
        year_filter=year_filter,
        convert_filter=convert_filter,
    )


@convenor.route("/selectors_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selectors_ajax(id):
    """
    Ajax data point for selectors view
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
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    data = _build_selector_data(
        config,
        cohort_filter,
        prog_filter,
        state_filter,
        convert_filter,
        year_filter,
        match_filter,
        match_show,
    )

    def _quickfixes(s: SelectingStudent):
        return {
            QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_AVAILABLE: {
                "msg": "Populate (available only)...",
                "url": url_for(
                    "convenor.force_convert_bookmarks",
                    sel_id=s.id,
                    converted=0,
                    no_submit_IP=1,
                    force=1,
                    reset=0,
                    force_unavailable=0,
                ),
            },
            QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_UNAVAILABLE: {
                "msg": "Populate (incl. unavailable)...",
                "url": url_for(
                    "convenor.force_convert_bookmarks",
                    sel_id=s.id,
                    converted=0,
                    no_submit_IP=1,
                    force=1,
                    reset=0,
                    force_unavailable=1,
                ),
            },
        }

    return ajax.convenor.selectors_data(data, config, quickfix_factory=_quickfixes)


def _build_selector_data(
        config,
        cohort_filter,
        prog_filter,
        state_filter,
        convert_filter,
        year_filter,
        match_filter,
        match_show,
):
    # build a list of live students selecting from this project class
    selectors: List[SelectingStudent] = config.selecting_students.filter_by(
        retired=False
    )

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)
    match_flag, match_value = is_integer(match_filter)

    if cohort_flag or prog_flag:
        selectors = selectors.join(
            StudentData, StudentData.id == SelectingStudent.student_id
        )

    if cohort_flag:
        selectors = selectors.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        selectors = selectors.filter(StudentData.programme_id == prog_value)

    if convert_filter == "convert":
        selectors = selectors.filter(SelectingStudent.convert_to_submitter.is_(True))
    elif convert_filter == "no-convert":
        selectors = selectors.filter(SelectingStudent.convert_to_submitter.is_(False))

    if state_filter == "submitted":
        data = [rec for rec in selectors.all() if rec.has_submitted]
    elif state_filter == "bookmarks":
        data = [
            rec
            for rec in selectors.all()
            if not rec.has_submitted and rec.has_bookmarks
        ]
    elif state_filter == "none":
        data = [
            rec
            for rec in selectors.all()
            if not rec.has_submitted and not rec.has_bookmarks
        ]
    elif state_filter == "confirmations":
        data = [rec for rec in selectors.all() if rec.number_pending > 0]
    elif state_filter == "custom":
        data = [rec for rec in selectors.all() if rec.number_custom_offers() > 0]
    else:
        data = selectors.all()

    if cohort_filter == "twd":
        data = [rec for rec in selectors.all() if rec.student.intermitting]

    if year_flag:
        data = [
            s
            for s in data
            if (s.academic_year is None or s.academic_year == year_value)
        ]

    if match_flag:
        match = config.published_matches.filter_by(id=match_value).first()

        if match is not None:
            # get list of student ids that are included in the match
            student_set = set(x.selector.student_id for x in match.records)

            if match_show == "included":
                data = [s for s in data if s.student_id in student_set]
            elif match_show == "missing":
                data = [s for s in data if s.student_id not in student_set]

    return data


@convenor.route("/enrol_selectors/<int:id>")
@roles_accepted("faculty", "admin", "root")
def enrol_selectors(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    if (
            not (current_user.has_role("admin") or current_user.has_role("root"))
            and config.selector_lifecycle
            >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        flash(
            "Manual enrolment of selectors is only possible before student choices are closed",
            "error",
        )
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter", "all")
    prog_filter = request.args.get("prog_filter", "all")
    year_filter = request.args.get("year_filter", "all")

    if prog_filter is None and session.get("convenor_sel_enroll_prog_filter"):
        prog_filter = session["convenor_sel_enroll_prog_filter"]

    prog_flag, prog_value = is_integer(prog_filter)

    if not prog_flag:
        if prog_filter not in ["all", "off"]:
            prog_filter = "all"

    disable = (
        True
        if (
                prog_flag or (isinstance(prog_filter, str) and prog_filter.lower() == "off")
        )
        else False
    )
    candidates = build_enrol_selector_candidates(
        config, disable_programme_filter=disable
    )

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
    progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active.is_(True), DegreeProgramme.id.in_(programmes))
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )

    if cohort_filter is None and session.get("convenor_sel_enroll_cohort_filter"):
        cohort_filter = session["convenor_sel_enroll_cohort_filter"]

    if (
            isinstance(cohort_filter, str)
            and cohort_filter not in ["all"]
            and int(cohort_filter) not in cohorts
    ):
        cohort_filter = "all"

    if cohort_filter is not None:
        session["convenor_sel_enroll_cohort_filter"] = cohort_filter

    if (
            isinstance(prog_filter, str)
            and prog_filter not in ["all", "off"]
            and int(prog_filter) not in programmes
    ):
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_sel_enroll_prog_filter"] = prog_filter

    if year_filter is None and session.get("convenor_sel_enroll_year_filter"):
        year_filter = session["convenor_sel_enroll_year_filter"]

    if (
            isinstance(year_filter, str)
            and year_filter not in ["all"]
            and int(year_filter) not in years
    ):
        year_filter = "all"

    if year_filter is not None:
        session["convenor_sel_enroll_year_filter"] = year_filter

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/enrol_selectors.html",
        pane="selectors",
        subpane="enroll",
        pclass=pclass,
        config=config,
        convenor_data=data,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        year_filter=year_filter,
    )


@convenor.route("/enrol_selectors_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def enrol_selectors_ajax(id):
    """
    Ajax data point for enroll selectors view
    :param id:
    :return:
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter", "all")
    prog_filter = request.args.get("prog_filter", "all")
    year_filter = request.args.get("year_filter", "all")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    if (
            not (current_user.has_role("admin") or current_user.has_role("root"))
            and config.selector_lifecycle
            >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        return jsonify({})

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    disable = (
        True
        if (
                prog_flag or (isinstance(prog_filter, str) and prog_filter.lower() == "off")
        )
        else False
    )
    candidates = build_enrol_selector_candidates(
        config, disable_programme_filter=disable
    )

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)
    elif prog_filter.lower() == "all":
        candidates = candidates.filter(
            or_(StudentData.programme_id == p.id for p in pclass.programmes)
        )

    if not year_flag:
        # use SQL server-side handler for performance if it is possible
        # (we can't use SQL to filter by the available years because this also tests for students that have
        # graduated)
        return _enrol_selectors_ajax_handler(request, candidates, config)

    return _enrol_selectors_ajax_handler(request, candidates, config, year_value)


def _filter_candidates(year: int, row: StudentData):
    if row.has_graduated:
        return False

    if year is None or row.academic_year is None:
        return True  # to avoid not offering students who should be visible

    if row.academic_year != year:
        return False

    return True


def _enrol_selectors_ajax_handler(
        request, candidates, config: ProjectClassConfig, year_value: int = None
):
    def search_name(row: StudentData):
        u: User = row.user
        return u.name

    def sort_name(row: StudentData):
        u: User = row.user
        return [u.last_name, u.first_name]

    def search_programme(row: StudentData):
        p: DegreeProgramme = row.programme
        return p.name

    def sort_programme(row: StudentData):
        p: DegreeProgramme = row.programme
        return p.name

    def search_cohort(row: StudentData):
        return str(row.cohort)

    def sort_cohort(row: StudentData):
        return row.cohort

    def search_current_year(row: StudentData):
        return str(row.academic_year)

    def sort_current_year(row: StudentData):
        return row.academic_year

    def search_userid(row: StudentData):
        u: User = row.user
        return u.username

    def sort_userid(row: StudentData):
        u: User = row.user
        return u.username

    name = {"search": search_name, "order": sort_name}
    userid = {"search": search_userid, "order": sort_userid}
    programme = {"search": search_programme, "order": sort_programme}
    cohort = {"search": search_cohort, "order": sort_cohort}
    current_year = {"search": search_current_year, "order": sort_current_year}

    columns = {
        "name": name,
        "userid": userid,
        "programme": programme,
        "cohort": cohort,
        "current_year": current_year,
    }

    with ServerSideInMemoryHandler(
            request, candidates, columns, row_filter=partial(_filter_candidates, year_value)
    ) as handler:
        return handler.build_payload(
            partial(ajax.convenor.enrol_selectors_data, config)
        )


@convenor.route("/enroll_all_selectors/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_all_selectors(configid):
    config = ProjectClassConfig.query.get_or_404(configid)
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
            not (current_user.has_role("admin") or current_user.has_role("root"))
            and config.selector_lifecycle
            >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        flash(
            "Manual enrolment of selectors is only possible before student choices are closed",
            "error",
        )
        return redirect(redirect_url())

    convert = bool(int(request.args.get("convert", 1)))

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    candidates = build_enrol_selector_candidates(
        config,
        disable_programme_filter=True
        if isinstance(prog_filter, str) and prog_filter.lower() != "all"
        else False,
    )

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    candidate_values = candidates.all()

    year = year_value if year_flag else None
    c_list = [x for x in candidate_values if _filter_candidates(year, x)]

    try:
        for c in c_list:
            add_selector(c, configid, convert=convert, autocommit=False)

        db.session.commit()
        flash(
            'Added {count} selectors to project "{proj}"'.format(
                count=len(c_list), proj=config.project_class.name
            ),
            "info",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Could not add selectors because a database error occurred. Please check the logs for further information.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/enrol_selector/<int:sid>/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_selector(sid, configid):
    """
    Manually enroll a student as a selector
    :param sid:
    :param configid:
    :return:
    """
    config = ProjectClassConfig.query.get_or_404(configid)
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
            not (current_user.has_role("admin") or current_user.has_role("root"))
            and config.selector_lifecycle
            >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        flash(
            "Manual enrolment of selectors is only possible before student choices are closed",
            "error",
        )
        return redirect(redirect_url())

    convert = bool(int(request.args.get("convert", 1)))

    add_selector(sid, configid, convert=convert, autocommit=True)

    return redirect(redirect_url())


@convenor.route("/delete_selector/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def delete_selector(sid):
    """
    Manually delete a selector
    :param sid:
    :return:
    """
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    if (
            not (current_user.has_role("admin") or current_user.has_role("root"))
            and sel.config.selector_lifecycle
            > ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash(
            "Manual deletion of selectors is only possible before student choices are closed",
            "error",
        )
        return redirect(redirect_url())

    if sel.has_bookmarks or sel.has_submitted or sel.has_matches:
        url = request.args.get("url", None)
        if url is None:
            url = redirect_url()

        title = 'Delete selector "{name}"'.format(name=sel.student.user.name)
        panel_title = 'Delete selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>'.format(
            name=sel.student.user.name
        )

        action_url = url_for("convenor.do_delete_selector", sid=sid, url=url)
        message = (
            '<p>Are you sure that you wish to delete selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>?</p>'
            "<p>This selector has stored bookmarks, submitted a list of project choices, or has been included "
            "in a matching.</p>"
            "<p>This action cannot be undone. Any bookmarks and submitted preferences will be lost, and "
            "the selector will be deleted from any matches of which they are currently part.</p>".format(
                name=sel.student.user.name
            )
        )
        submit_label = "Delete selector"

        return render_template_context(
            "admin/danger_confirm.html",
            title=title,
            panel_title=panel_title,
            action_url=action_url,
            message=message,
            submit_label=submit_label,
        )

    try:
        # delete should cascade to Bookmark and SelectionRecord items; also, no need to remove
        # matching_records elements because we are guaranteed that there aren't any
        db.session.delete(sel)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Could not delete selector due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/do_delete_selector/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_selector(sid):
    """
    Manually delete a selector -- action step
    :param sid:
    :return:
    """
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    if (
            not (current_user.has_role("admin") or current_user.has_role("root"))
            and sel.config.selector_lifecycle
            > ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash(
            "Manual deletion of selectors is only possible before student choices are closed",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        sel.detach_records()
        db.session.delete(sel)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Could not delete selector due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/selector_grid/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_grid(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")
    state_filter = request.args.get("state_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

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

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash(
            "The selector grid view is available only after student choices are closed",
            "error",
        )
        return redirect(redirect_url())

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    years = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)

        academic_year = sel.academic_year
        if academic_year is not None:
            years.add(academic_year)

        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active.is_(True))
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]
    groups = (
        db.session.query(ResearchGroup)
        .filter_by(active=True)
        .order_by(ResearchGroup.name.asc())
        .all()
    )

    if cohort_filter is None and session.get("convenor_sel_grid_cohort_filter"):
        cohort_filter = session["convenor_sel_grid_cohort_filter"]

    if cohort_filter is not None:
        session["convenor_sel_grid_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_sel_grid_prog_filter"):
        prog_filter = session["convenor_sel_grid_prog_filter"]

    if prog_filter is not None:
        session["convenor_sel_grid_prog_filter"] = prog_filter

    if year_filter is None and session.get("convenor_sel_grid_year_filter"):
        year_filter = session["convenor_sel_grid_year_filter"]

    if (
            isinstance(year_filter, str)
            and year_filter != "all"
            and int(year_filter) not in years
    ):
        year_filter = "all"

    if year_filter is not None:
        session["convenor_sel_grid_filter"] = year_filter

    if state_filter is None and session.get("convenor_sel_grid_state_filter"):
        state_filter = session["convenor_sel_grid_state_filter"]

    if isinstance(state_filter, str) and state_filter not in ["all", "twd"]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_sel_grid_state_filter"] = state_filter

    # get list of current published matchings (if any) that include this project type;
    # these can be used to filter for students that are/are not included in the matching
    if config.has_published_matches:
        matches = config.published_matches.all()
        match_ids = [x.id for x in matches]
    else:
        matches = None

    if match_filter is None and session.get("convenor_sel_grid_match_filter"):
        match_filter = session["convenor_sel_grid_match_filter"]

    if match_show is None and session.get("convenor_sel_grid_match_show"):
        match_show = session["convenor_sel_grid_match_show"]

    if matches is None:
        match_filter = "all"
        match_show = "all"
    else:
        if (
                isinstance(match_filter, str)
                and match_filter != "all"
                and int(match_filter) not in match_ids
        ):
            match_filter = "all"
            match_show = "all"

    if match_show not in ["all", "included", "missing"]:
        match_show = "all"

    if match_filter is not None:
        session["convenor_sel_grid_match_filter"] = match_filter

    if match_show is not None:
        session["convenor_sel_grid_match_show"] = match_show

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/selector_grid.html",
        pane="selectors",
        subpane="grid",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        matches=matches,
        match_filter=match_filter,
        match_show=match_show,
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        year_filter=year_filter,
        groups=groups,
        state_filter=state_filter,
    )


@convenor.route("/selector_grid_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_grid_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")
    state_filter = request.args.get("state_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        return jsonify({})

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)
    match_flag, match_value = is_integer(match_filter)

    if cohort_flag or prog_flag or state_filter != "all":
        selectors = selectors.join(
            StudentData, StudentData.id == SelectingStudent.student_id
        )

    if state_filter == "twd":
        selectors = selectors.filter(StudentData.intermitting.is_(True))

    if cohort_flag:
        selectors = selectors.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        selectors = selectors.filter(StudentData.programme_id == prog_value)

    if year_flag:
        data = [
            s
            for s in selectors.all()
            if (s.academic_year is None or s.academic_year == year_value)
        ]
    else:
        data = selectors.all()

    # for selection_open_to_all type project classes (eg. RP), no need to include students who did not respond
    if pclass.selection_open_to_all:
        data = [s for s in data if s.has_submitted or s.has_bookmarks]

    if match_flag:
        match = config.published_matches.filter_by(id=match_value).first()

        if match is not None:
            # get list of student ids that are included in the match
            student_set = set(x.selector.student_id for x in match.records)

            if match_show == "included":
                data = [s for s in data if s.student_id in student_set]
            elif match_show == "missing":
                data = [s for s in data if s.student_id not in student_set]

    return ajax.convenor.selector_grid_data(data, config)


@convenor.route("/show_confirmations/<int:id>")
@roles_accepted("faculty", "admin", "root")
def show_confirmations(id):
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
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash(
            "The outstanding confirmations view is available only after student choices have opened",
            "error",
        )
        return redirect(redirect_url())

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash(
            "The outstanding confirmations view is not available after matching has been completed",
            "error",
        )
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/show_confirmations.html",
        pane="selectors",
        subpane="confirm",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
    )


@convenor.route("/show_confirmations_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def show_confirmations_ajax(id):
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

    if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        return jsonify({})

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        return jsonify({})

    outstanding = build_outstanding_confirmations_query(config).all()

    return ajax.convenor.show_confirmations(outstanding, pclass.id)


@convenor.route("/approve_outstanding_confirms/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def approve_outstanding_confirms(pid):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash(
            "Approval of all outstanding confirmation requests can be performed only after student choices have opened",
            "error",
        )
        return redirect(redirect_url())

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash(
            "Approval of all outstanding confirmation requests can not be performed after matching has been completed",
            "error",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    approve_task = celery.tasks["app.tasks.selecting.approve_outstanding_confirms"]

    tk_name = f"Approve all outstanding confirmation requests for {pclass.name} {config.year}-{config.year + 1}"
    tk_description = "Approve all outstanding confirmation requests"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    approve_task.apply_async(
        args=(task_id, config.id, current_user.id), task_id=task_id
    )

    return redirect(redirect_url())


@convenor.route("/delete_outstanding_confirms/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def delete_outstanding_confirms(pid):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(pid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash(
            "Deletion of all outstanding confirmation requests can be performed only after student choices have opened",
            "error",
        )
        return redirect(redirect_url())

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash(
            "Deletion of all outstanding confirmation requests can not be performed after matching has been completed",
            "error",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    delete_task = celery.tasks["app.tasks.selecting.delete_outstanding_confirms"]

    tk_name = f"Delete all outstanding confirmation requests for {pclass.name} {config.year}-{config.year + 1}"
    tk_description = "Delete all outstanding confirmation requests"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    delete_task.apply_async(args=(task_id, config.id), task_id=task_id)

    return redirect(redirect_url())
