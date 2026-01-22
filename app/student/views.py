#
# Created by David Seery on 16/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime, date
from functools import partial
from typing import Optional

import parse
from flask import redirect, url_for, flash, request, jsonify, current_app, session
from flask_mailman import EmailMultiAlternatives
from flask_security import current_user, roles_required, roles_accepted
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql import func, or_, and_

import app.ajax as ajax
from . import student
from .actions import store_selection
from .forms import StudentFeedbackForm, StudentSettingsForm
from .utils import verify_submitter, verify_selector, verify_view_project, verify_open, verify_submission_record
from ..database import db
from ..models import (
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    LiveProject,
    Bookmark,
    MessageOfTheDay,
    ResearchGroup,
    SkillGroup,
    SubmissionRecord,
    TransferableSkill,
    User,
    EmailNotification,
    add_notification,
    CustomOffer,
    Project,
    SubmittingStudent,
    StudentData,
    DegreeProgramme,
    DegreeType,
    PresentationAssessment,
    PresentationSession,
)
from ..shared.context.global_context import render_template_context
from ..shared.utils import home_dashboard, home_dashboard_url, get_count, redirect_url, get_current_year
from ..shared.validators import validate_is_convenor, validate_submission_viewable, validate_using_assessment, validate_assessment
from ..task_queue import register_task
from ..tools import ServerSideSQLHandler


@student.route("/dashboard")
@roles_accepted("student", "admin", "root")
def dashboard():
    """
    Render dashboard for a student user
    :return:
    """
    has_selections = False
    has_submissions = False

    # build list of all project classes for which this student has roles
    enrolled_pclasses = set()

    if current_user.student_data is not None:
        data: StudentData = current_user.student_data

        for item in data.selecting.filter_by(retired=False).all():
            pclass: ProjectClass = item.config.project_class
            if pclass.active and pclass.publish:
                enrolled_pclasses.add(pclass)

        for item in data.submitting.filter_by(retired=False).all():
            pclass: ProjectClass = item.config.project_class
            if pclass.active and pclass.publish:
                enrolled_pclasses.add(pclass)

    # map list of project classes into ProjectClassConfig instance, and selector/submitter cards
    enrolled_configs = []
    for item in enrolled_pclasses:
        # extract live configuration for this project class
        config: ProjectClassConfig = item.most_recent_config

        # determine whether this student has a selector role for this project class
        select_q = config.selecting_students.filter_by(retired=False, student_id=current_user.id)

        if get_count(select_q) > 1:
            flash(
                'Multiple live "selector" records exist for "{pclass}" on your account. Please contact '
                "the system administrator".format(pclass=item.name),
                "error",
            )

        sel = select_q.first()
        if sel is not None:
            has_selections = True

        # determine whether this student has a submitter role for this project class
        submit_q = config.submitting_students.filter_by(retired=False, student_id=current_user.id)

        if get_count(submit_q) > 1:
            flash(
                'Multiple live "submitter" records exist for "{pclass}" on your account. Please contact '
                "the system administrator".format(pclass=item.name),
                "error",
            )

        sub = submit_q.first()
        if sub is not None:
            has_submissions = True

        enrolled_configs.append((config, sel, sub))

    enrolled_configs.sort(key=lambda x: x[0].project_class.name)

    # can't disable both panes, so if neither is active then force selection pane to be active
    if not has_selections and not has_submissions:
        has_selections = True

    pane = request.args.get("pane", None)
    if pane is None and session.get("dashboard_pane"):
        pane = session["dashboard_pane"]

    if pane not in ["select", "submit"]:
        pane = "select"

    if pane == "select" and not has_selections:
        pane = "submit"
    if pane == "submit" and not has_submissions:
        pane = "select"

    session["dashboard_pane"] = pane

    # list of all (active, published, suitable level) project classes used to generate a simple informational dashboard in the event
    # that this student doesn't have any live selector or submitter roles
    # Restrict attention to projects of the correct level (UG, PGT, PGR)
    if current_user.student_data is not None:
        data: StudentData = current_user.student_data
        programme: DegreeProgramme = data.programme
        ptype: DegreeType = programme.degree_type
        pclasses = ProjectClass.query.filter(ProjectClass.active == True, ProjectClass.publish == True, ProjectClass.student_level == ptype.level)
    else:
        pclasses = ProjectClass.query.filter(ProjectClass.active == True, ProjectClass.publish == True)

    # build list of system messages to consider displaying
    messages = []
    for message in (
            db.session.query(MessageOfTheDay)
                    .filter(MessageOfTheDay.show_students, ~MessageOfTheDay.dismissed_by.any(id=current_user.id))
                    .order_by(MessageOfTheDay.issue_date.desc())
                    .all()
    ):
        # if no project classes specified, always show
        include = message.project_classes.first() is None

        # otherwise, include if we are enrolled in one of the specified project classes
        if not include:
            for pcl in message.project_classes:
                if pcl in enrolled_pclasses:
                    include = True
                    break

        if include:
            messages.append(message)

    return render_template_context(
        "student/dashboard.html",
        enrolled_classes=enrolled_pclasses,
        enrollments=enrolled_configs,
        pclasses=pclasses,
        messages=messages,
        today=date.today(),
        pane=pane,
        has_selections=has_selections,
        has_submissions=has_submissions,
    )


@student.route("/selector_browse_projects/<int:id>")
@roles_accepted("student")
def selector_browse_projects(id):
    """
    Browse the live project table for a particular selecting student instance
    :param id:
    :return:
    """
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)
    config: ProjectClassConfig = sel.config

    # verify the logged-in user is allowed to view this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    state = config.selector_lifecycle
    if not verify_open(config, state=state, message=True):
        return redirect(redirect_url())

    # supply list of transferable skill groups and research groups that can be filtered against
    if config.advertise_research_group:
        groups = db.session.query(ResearchGroup).filter_by(active=True).order_by(ResearchGroup.name.asc()).all()
    else:
        groups = None

    skills = (
        db.session.query(TransferableSkill)
        .join(SkillGroup, SkillGroup.id == TransferableSkill.group_id)
        .filter(TransferableSkill.active == True, SkillGroup.active == True)
        .order_by(SkillGroup.name.asc(), TransferableSkill.name.asc())
        .all()
    )

    skill_list = {}
    for skill in skills:
        if skill_list.get(skill.group.name, None) is None:
            skill_list[skill.group.name] = []
        skill_list[skill.group.name].append(skill)

    is_live = state < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    endpoint = url_for("student.selector_projects_ajax", id=id)
    return render_template_context(
        "student/browse_projects.html",
        sel=sel,
        config=config,
        is_live=is_live,
        groups=groups,
        skill_groups=sorted(skill_list.keys()),
        skill_list=skill_list,
        ajax_endpoint=endpoint,
        uses_selection=config.uses_selection,
    )


@student.route("/selector_projects_ajax/<int:id>", methods=["POST"])
@roles_accepted("student")
def selector_projects_ajax(id):
    """
    Ajax data point for live projects table
    :param id:
    :return:
    """
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)
    config: ProjectClassConfig = sel.config
    state = config.selector_lifecycle

    # verify the logged-in user is allowed to view this SelectingStudent
    if not verify_selector(sel):
        return jsonify({})

    is_live = state < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    return _project_list_endpoint(sel.config, sel, partial(ajax.student.selector_liveprojects_data, sel, is_live), state=state)


@student.route("/submitter_browse_projects/<int:id>")
@roles_accepted("student")
def submitter_browse_projects(id):
    """
    Browse the live project table for a particular submitting student instance
    :param id:
    :return:
    """
    # id is a SelectingStudent
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(id)
    config: ProjectClassConfig = sub.selector_config

    # verify the logged-in user is allowed to view this SelectingStudent
    if not verify_submitter(sub, message=True):
        return redirect(redirect_url())

    state = config.selector_lifecycle
    if not verify_open(config, state=state, message=True):
        return redirect(redirect_url())

    is_live = state < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    endpoint = url_for("student.submitter_projects_ajax", id=id)
    return render_template_context(
        "student/browse_projects.html",
        sel=sub,
        config=config,
        is_live=is_live,
        groups=None,
        skill_groups=None,
        skill_list=None,
        ajax_endpoint=endpoint,
        uses_selection=False,
    )


@student.route("/submitter_projects_ajax/<int:id>", methods=["POST"])
@roles_accepted("student")
def submitter_projects_ajax(id):
    """
    Ajax data point for live projects table
    :param id:
    :return:
    """
    # id is a SubmittingStudent
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(id)
    config: ProjectClassConfig = sub.selector_config

    # verify the logged-in user is allowed to view this SelectingStudent
    if not verify_submitter(sub):
        return jsonify({})

    return _project_list_endpoint(config, None, partial(ajax.student.submitter_liveprojects_data, sub))


def _project_list_endpoint(config: ProjectClassConfig, sel: Optional[SelectingStudent], row_formatter, state=None):
    # check that project is viewable for this ProjectClassConfig instance
    if state is None:
        state = config.selector_lifecycle

    if not verify_open(config, state=state):
        return jsonify({})

    base_query = (
        config.live_projects.filter(~LiveProject.hidden)
        .join(Project, Project.id == LiveProject.parent_id)
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(ResearchGroup, ResearchGroup.id == LiveProject.group_id, isouter=True)
    )

    if sel is not None:
        filter_groups = config.advertise_research_group and sel.group_filters.first()
        filter_skills = sel.skill_filters.first()

        if filter_groups and filter_skills:
            base_query = base_query.filter(
                and_(
                    or_(ResearchGroup.id == g.id for g in sel.group_filters),
                    or_(LiveProject.skills.any(TransferableSkill.id == s.id) for s in sel.skill_filters),
                )
            )
        elif filter_groups:
            base_query = base_query.filter(or_(ResearchGroup.id == g.id for g in sel.group_filters))
        elif filter_skills:
            base_query = base_query.filter(or_(LiveProject.skills.any(TransferableSkill.id == s.id) for s in sel.skill_filters))

    name = {"search": LiveProject.name, "order": LiveProject.name, "search_collation": "utf8_general_ci"}
    supervisor = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    group = {"search": ResearchGroup.name, "order": ResearchGroup.name, "search_collation": "utf8_general_ci"}
    meeting = {"order": LiveProject.meeting_reqd}

    columns = {"name": name, "supervisor": supervisor, "group": group, "meeting": meeting}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(row_formatter)


@student.route("/add_group_filter/<id>/<gid>")
@roles_accepted("student")
def add_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)
    sel = SelectingStudent.query.get_or_404(id)

    if group not in sel.group_filters:
        try:
            sel.group_filters.append(group)
            db.session.commit()
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@student.route("/remove_group_filter/<id>/<gid>")
@roles_accepted("student")
def remove_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)
    sel = SelectingStudent.query.get_or_404(id)

    if group in sel.group_filters:
        try:
            sel.group_filters.remove(group)
            db.session.commit()
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@student.route("/clear_group_filters/<id>")
@roles_accepted("student")
def clear_group_filters(id):
    sel = SelectingStudent.query.get_or_404(id)

    try:
        sel.group_filters = []
        db.session.commit()
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(redirect_url())


@student.route("/add_skill_filter/<id>/<skill_id>")
@roles_accepted("student")
def add_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)
    sel = SelectingStudent.query.get_or_404(id)

    if skill not in sel.skill_filters:
        try:
            sel.skill_filters.append(skill)
            db.session.commit()
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@student.route("/remove_skill_filter/<id>/<skill_id>")
@roles_accepted("student")
def remove_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)
    sel = SelectingStudent.query.get_or_404(id)

    if skill in sel.skill_filters:
        try:
            sel.skill_filters.remove(skill)
            db.session.commit()
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@student.route("/clear_skill_filters/<id>")
@roles_accepted("student")
def clear_skill_filters(id):
    sel = SelectingStudent.query.get_or_404(id)

    try:
        sel.skill_filters = []
        db.session.commit()
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(redirect_url())


@student.route("/selector_view_project/<int:sid>/<int:pid>")
@roles_accepted("student", "admin", "root")
def selector_view_project(sid, pid):
    """
    View a specific project
    :param sid:
    :param pid:
    :return:
    """
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)
    config: ProjectClassConfig = sel.config

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = url_for("student.selector_browse_projects", id=sel.id)
        text = "project list"

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    # pid is the id for a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(pid)

    # verify student is allowed to view this live project
    if not verify_view_project(config, project):
        return redirect(redirect_url())

    # verify project is open
    if not verify_open(config, message=True):
        return redirect(redirect_url())

    # update page views
    if project.page_views is None:
        project.page_views = 1
    else:
        project.page_views += 1

    project.last_view = datetime.today()
    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return render_template_context("student/show_project.html", title=project.name, sel=sel, project=project, desc=project, text=text, url=url)


@student.route("/submitter_view_project/<int:sid>/<int:pid>")
@roles_accepted("student", "admin", "root")
def submitter_view_project(sid, pid):
    """
    View a specific project
    :param sid:
    :param pid:
    :return:
    """
    # sid is a SelectingStudent
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(sid)
    config: ProjectClassConfig = sub.selector_config

    # verify the logged-in user is allowed to perform operations for this SubmittingStudent
    if not verify_submitter(sub, message=True):
        return redirect(redirect_url())

    # pid is the id for a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(pid)

    # verify student is allowed to view this live project
    if not verify_view_project(config, project):
        return redirect(redirect_url())

    # verify project is open
    if not verify_open(config, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None and text is None:
        url = url_for("student.submitter_browse_projects", id=sub.id)
        text = "project list"

    return render_template_context(
        "student/show_project.html", title=project.name, sel=None, project=project, desc=project, url=url, text=text, archived=True
    )


@student.route("/add_bookmark/<int:sid>/<int:pid>")
@roles_accepted("student", "admin", "root")
def add_bookmark(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify project is open
    if not verify_open(project.config, strict=True, message=True):
        return redirect(redirect_url())

    if project.hidden:
        flash("This project has been marked as unavailable by the convenor, and cannot be bookmarked.", "error")
        return redirect(redirect_url())

    # verify student is allowed to view this live project
    if not verify_view_project(sel.config, project):
        return redirect(redirect_url())

    # add bookmark
    bookmark_data = sel.is_project_bookmarked(project)
    if not bookmark_data.get("bookmarked"):
        bm = Bookmark(owner_id=sid, liveproject_id=pid, rank=sel.bookmarks.count() + 1)
        db.session.add(bm)
        db.session.commit()

    return redirect(redirect_url())


@student.route("/remove_bookmark/<int:sid>/<int:pid>")
@roles_accepted("student", "admin", "root")
def remove_bookmark(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    # pid is the id for a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify project is open
    if not verify_open(project.config, strict=True, message=True):
        return redirect(redirect_url())

    # verify student is allowed to view this live project
    if not verify_view_project(sel.config, project):
        return redirect(redirect_url())

    # remove bookmark
    bm = sel.bookmarks.filter_by(liveproject_id=pid).first()

    if bm:
        sel.bookmarks.remove(bm)
        sel.re_rank_bookmarks()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not remove bookmark due to a database error. Please inform a system administrator.", "info")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

    return redirect(redirect_url())


@student.route("/request_confirm/<int:sid>/<int:pid>")
@roles_accepted("student", "faculty", "admin", "root")
def request_confirmation(sid, pid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    # pid is the id for a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(pid)
    config: ProjectClassConfig = project.config

    # verify project is open
    if not verify_open(project.config, strict=True, message=True):
        return redirect(redirect_url())

    # verify student is allowed to view this live project
    if not verify_view_project(sel.config, project):
        return redirect(redirect_url())

    if project.hidden:
        flash("This project has been marked as unavailable by the convenor. It is not possible to request confirmation for it.", "error")
        return redirect(redirect_url())

    # check whether this project type uses selections
    if not config.uses_selection:
        flash(
            "This project belongs to a project class for which online selection is not required. "
            "It is not possible to request confirmation for it.",
            "error",
        )
        return redirect(redirect_url())

    # check if confirmation has already been issued
    if project.is_confirmed(sel):
        flash('Confirmation has already been issued for project "{n}"'.format(n=project.name), "info")
        return redirect(redirect_url())

    # check if confirmation is already pending
    if project.is_waiting(sel):
        flash('Confirmation is already pending for project "{n}"'.format(n=project.name), "info")
        return redirect(redirect_url())

    # add confirm request
    req = project.make_confirm_request(sel)
    db.session.add(req)
    add_notification(project.owner, EmailNotification.CONFIRMATION_REQUEST_CREATED, req, autocommit=False)

    # check if a bookmark already exists, and make one if not
    bookmark_data = sel.is_project_bookmarked(project)
    if not bookmark_data.get("bookmarked"):
        bm = Bookmark(owner_id=sid, liveproject_id=pid, rank=sel.bookmarks.count() + 1)
        db.session.add(bm)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not issue confirmation request due to a database error. Please inform a system administrator.", "info")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@student.route("/cancel_confirm/<int:sid>/<int:pid>")
@roles_accepted("student", "admin", "root")
def cancel_confirmation(sid, pid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    # pid is the id for a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(pid)
    config: ProjectClassConfig = project.config

    # verify project is open
    if not verify_open(project.config, strict=True, message=True):
        return redirect(redirect_url())

    # verify student is allowed to view this live project
    if not verify_view_project(sel.config, project):
        return redirect(redirect_url())

    # check whether this project type uses selections
    if not config.uses_selection:
        flash(
            "This project belongs to a project class for which online selection is not required. "
            "It is not possible to request confirmation for it.",
            "error",
        )
        return redirect(redirect_url())

    # check if confirmation has already been issued
    if project.is_confirmed(sel):
        flash('Confirmation has already been issued for project "{n}"'.format(n=project.name), "info")
        return redirect(redirect_url())

    # remove confirm request if one exists
    if project.is_waiting(sel):
        req = project.get_confirm_request(sel)
        if req is not None:
            req.remove(notify_student=False, notify_owner=True)
            db.session.delete(req)

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                flash("Could not cancel confirmation request due to a database error. Please inform a system administrator.", "info")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                db.session.rollback()

    return redirect(redirect_url())


def _demap_project(item_id):
    result = parse.parse("P{configid}-{pid}", item_id)

    return int(result["pid"])


@student.route("/update_ranking", methods=["POST"])
@roles_accepted("student", "admin", "root")
def update_ranking():
    data = request.get_json()

    # discard if request is ill-formed
    if "ranking" not in data or "configid" not in data or "sid" not in data:
        return jsonify({"status": "ill_formed"})

    # extract data from payload:
    #  - config_id identifies a ProjectClassConfig instance
    #  - sid identified a SelectingStudent instance
    #  - ranking is the new project ranking
    config_id = data["configid"]
    sid = data["sid"]
    ranking = data["ranking"]

    if config_id is None or sid is None or ranking is None:
        return jsonify({"status": "ill_formed"})

    config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=config_id).first()
    sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).first()

    if config is None or sel is None:
        return jsonify({"status": "database_error"})

    # check logged-in user is eligible to modify ranking data
    if current_user.id != sel.student.id:
        return jsonify({"status": "insufficient_privileges"})

    # convert ranking data from the payload into an ordered list of project ids
    projects = map(_demap_project, ranking)

    rmap = {}
    index = 1
    for p in projects:
        rmap[p] = index
        index += 1

    # update ranking
    for bookmark in sel.bookmarks:
        if bookmark.liveproject.id not in rmap:
            raise RuntimeError("Failed to demap POSTed ranking to bookmark list in update_ranking()")

        bookmark.rank = rmap[bookmark.liveproject.id]

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_error"})

    # work out which HTML elements to make visible and which to hide, based on validity of this selection
    valid, messages = sel.is_valid_selection if config.uses_selection else (True, [])
    hide_list = []
    reveal_list = []

    if config.uses_selection:
        if valid:
            hide_list.append("P{config}-invalid-button".format(config=config.id))
            reveal_list.append("P{config}-valid-button".format(config=config.id))
        else:
            hide_list.append("P{config}-valid-button".format(config=config.id))
            reveal_list.append("P{config}-invalid-button".format(config=config.id))

    return jsonify(
        {
            "status": "success",
            "hide": hide_list,
            "reveal": reveal_list,
            "submittable": valid,
            "message-id": "P{n}-status-list".format(n=config.id),
            "messages": messages,
        }
    )


@student.route("/submit/<int:sid>")
@roles_required("student")
def submit(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash("You do not have permission to submit project preferences for this selector.", "error")
        return redirect(redirect_url())

    valid, errors = sel.is_valid_selection
    if not valid:
        flash(
            "The current bookmark list is not a valid set of project preferences. This is an internal error; "
            "please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    try:
        _ = store_selection(sel)
        db.session.commit()

        celery = current_app.extensions["celery"]
        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

        msg = EmailMultiAlternatives(
            subject="Your project choices have been received ({pcl})".format(pcl=sel.config.project_class.name),
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=[sel.student.user.email],
        )

        msg.body = render_template_context(
            "email/student_notifications/choices_received.txt", user=sel.student.user, pclass=sel.config.project_class, config=sel.config, sel=sel
        )

        # register a new task in the database
        task_id = register_task(msg.subject, description="Send project choices confirmation email to {r}".format(r=", ".join(msg.to)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        flash("Your project preferences were submitted successfully. A confirmation email has been sent to your registered email address.", "info")

    except SQLAlchemyError as e:
        db.session.rollback()
        flash("A database error occurred during submission. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@student.route("/clear_submission/<int:sid>")
@roles_required("student")
def clear_submission(sid):
    sel = SelectingStudent.query.get_or_404(sid)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash("You do not have permission to clear project preferences for this selector.", "error")
        return redirect(redirect_url())

    title = "Clear submitted preferences"
    panel_title = "Clear submitted preferences for {name}".format(name=sel.config.name)

    action_url = url_for("student.do_clear_submission", sid=sid)
    message = (
        "<p>Please confirm that you wish to clear your submitted preferences for "
        "<strong>{name} {yeara}&ndash;{yearb}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=sel.config.name, yeara=sel.config.select_year_a, yearb=sel.config.select_year_b)
    )
    submit_label = "Clear submitted preferences"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@student.route("/do_clear_submission/<int:sid>")
@roles_required("student")
def do_clear_submission(sid):
    sel = SelectingStudent.query.get_or_404(sid)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash("You do not have permission to clear project preferences for this selector.", "error")
        return home_dashboard()

    sel.selections = []
    sel.submission_time = None
    sel.submission_IP = None

    try:
        db.session.commit()
        flash("Your project preferences have been cleared successfully.", "info")
    except SQLAlchemyError as e:
        flash("Could not clear project preferences due to a database error. Please inform a system administrator.", "info")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return home_dashboard()


@student.route("/manage_custom_offers/<int:sel_id>")
@roles_required("student")
def manage_custom_offers(sel_id):
    sel = SelectingStudent.query.get_or_404(sel_id)

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash("You do not have permission to manage custom offers for this selector.", "error")
        return home_dashboard()

    return render_template_context("student/manage_custom_offers.html", sel=sel)


@student.route("/accept_custom_offer/<int:offer_id>")
@roles_required("student")
def accept_custom_offer(offer_id):
    offer = CustomOffer.query.get_or_404(offer_id)

    sel = offer.selector

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash("You do not have permission to manage custom offers for this selector.", "error")
        return home_dashboard()

    # reset any previous acceptances
    accepted = sel.custom_offers.filter_by(status=CustomOffer.ACCEPTED).all()
    for o in accepted:
        o.status = CustomOffer.OFFERED

    offer.status = CustomOffer.ACCEPTED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not accept custom offer due to a database error. Please inform a system administrator.", "info")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    # accepting an offer returns the user to their dashboard
    return home_dashboard()


@student.route("/decline_custom_offer/<int:offer_id>")
@roles_required("student")
def decline_custom_offer(offer_id):
    offer = CustomOffer.query.get_or_404(offer_id)

    sel = offer.selector

    # verify logged-in user is the selector
    if current_user.id != sel.student_id:
        flash("You do not have permission to manage custom offers for this selector.", "error")
        return home_dashboard()

    offer.status = CustomOffer.DECLINED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not decline custom offer due to a database error. Please inform a system administrator.", "info")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    # decline an offer stays on the "manage" view
    return redirect(redirect_url())


@student.route("/view_selection/<int:sid>")
@roles_accepted("student", "admin", "root")
def view_selection(sid):
    sel = SelectingStudent.query.get_or_404(sid)

    # verify the logged-in user is allowed to perform operations for this SelectingStudent
    if not verify_selector(sel, message=True):
        return redirect(redirect_url())

    return render_template_context("student/choices.html", sel=sel)


@student.route("/view_feedback/<int:id>", methods=["GET", "POST"])
@roles_accepted("student")
def view_feedback(id):
    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not verify_submission_record(record, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = redirect_url()

    if not record.has_feedback:
        flash(
            "It is only possible to view feedback after the convenor has made it available. Try again when this submission period is closed.",
            "info",
        )
        return redirect(url)

    config = record.owner.config
    period = config.get_period(record.submission_period)

    preview = request.args.get("preview", None)

    return render_template_context("student/dashboard/view_feedback.html", record=record, period=period, text=text, url=url, preview=preview)


@student.route("/edit_feedback/<int:id>", methods=["GET", "POST"])
@roles_accepted("student")
def edit_feedback(id):
    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not verify_submission_record(record, message=True):
        return redirect(redirect_url())

    if record.retired:
        flash("It is no longer possible to submit feedback for this submission because it belongs to a previous academic year.", "info")
        return redirect(redirect_url())

    config = record.owner.config
    period = config.get_period(record.submission_period)

    if not period.closed:
        flash(
            "It is only possible to give feedback to your supervisor once your own marks and feedback are available. "
            "Try again when this submission period is closed.",
            "info",
        )
        return redirect(redirect_url())

    if period.closed and record.student_feedback_submitted:
        flash("It is not possible to edit your feedback once it has been submitted", "info")
        return redirect(redirect_url())

    form = StudentFeedbackForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        record.student_feedback = form.feedback.data
        db.session.commit()

        return redirect(url)

    else:
        if request.method == "GET":
            form.feedback.data = record.student_feedback

    return render_template_context(
        "student/dashboard/edit_feedback.html",
        form=form,
        unique_id="stud-{id}".format(id=id),
        submit_url=url_for("student.edit_feedback", id=id, url=url),
        text="home dashboard",
        url=home_dashboard_url(),
    )


@student.route("/submit_feedback/<int:id>")
@roles_accepted("student")
def submit_feedback(id):
    # id identifies a SubmissionRecord
    record = SubmissionRecord.query.get_or_404(id)

    if not verify_submission_record(record, message=True):
        return redirect(redirect_url())

    if record.student_feedback_submitted:
        return redirect(redirect_url())

    if record.retired:
        flash("It is no longer possible to submit feedback for this submission because it belongs to a previous academic year.", "info")
        return redirect(redirect_url())

    config = record.owner.config
    period = config.get_period(record.submission_period)

    if not period.closed:
        flash(
            "It is only possible to give feedback to your supervisor once your own marks and feedback are available. "
            "Try again when this submission period is closed.",
            "info",
        )
        return redirect(redirect_url())

    if not record.is_student_valid:
        flash("Cannot submit your feedback because it is incomplete.", "info")
        return redirect(redirect_url())

    record.student_feedback_submitted = True
    record.student_feedback_timestamp = datetime.now()
    db.session.commit()

    return redirect(redirect_url())


@student.route("/set_availability/<int:assessment_id>/<int:submitter_id>")
@roles_accepted("student")
def set_availability(assessment_id, submitter_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment = PresentationAssessment.query.get_or_404(assessment_id)
    submission_record: SubmissionRecord = SubmissionRecord.query.get_or_404(submitter_id)

    owner: SubmittingStudent = submission_record.owner

    if not owner.student.id == current_user.id:
        flash("You do not have permission to set availability for this assessment.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot set availability for this assessment because it has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash("Cannot set availability for this assessment because it has been closed", "info")
        return redirect(redirect_url())

    return render_template_context("student/set_availability.html", assessment=assessment, submitter=submission_record, url=url, text=text)

@student.route("/set_available/<int:session_id>/<int:submitter_id>")
@roles_accepted("student")
def set_available(session_id, submitter_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    session: PresentationSession = PresentationSession.query.get_or_404(session_id)
    assessment: PresentationAssessment = session.owner
    submission_record: SubmissionRecord = SubmissionRecord.query.get_or_404(submitter_id)

    owner: SubmittingStudent = submission_record.owner

    if not owner.student.id == current_user.id:
        flash("You do not have permission to set availability for this assessment.", "error")
        return redirect(redirect_url())

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot set availability for this assessment because availability collection has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash("Cannot set availability for this session because its parent assessment has been closed", "info")
        return redirect(redirect_url())

    session.submitter_make_available(submission_record)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes due to a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@student.route("/set_unavailable//<int:session_id>/<int:submitter_id>")
@roles_accepted("student")
def set_unavailable(session_id, submitter_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    session: PresentationSession = PresentationSession.query.get_or_404(session_id)
    assessment: PresentationAssessment = session.owner
    submission_record: SubmissionRecord = SubmissionRecord.query.get_or_404(submitter_id)

    owner: SubmittingStudent = submission_record.owner

    if not owner.student.id == current_user.id:
        flash("You do not have permission to set availability for this assessment.", "error")
        return redirect(redirect_url())

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot set availability for this assessment because availability collection has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash("Cannot set availability for this session because its parent assessment has been closed", "info")
        return redirect(redirect_url())

    session.submitter_make_unavailable(submission_record)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes due to a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@student.route("/settings", methods=["GET", "POST"])
@roles_required("student")
def settings():
    """
    Edit settings for a student user
    :return:
    """
    user = User.query.get_or_404(current_user.id)

    form = StudentSettingsForm(obj=user)
    form.user = user

    if form.validate_on_submit():
        user.default_license = form.default_license.data

        user.group_summaries = form.group_summaries.data
        user.summary_frequency = form.summary_frequency.data

        flash("All changes saved", "success")
        db.session.commit()

        return home_dashboard()

    return render_template_context("student/settings.html", settings_form=form, user=user)


@student.route("/timeline/<int:student_id>")
@roles_accepted("student", "admin", "root", "faculty")
def timeline(student_id):
    """
    Show student timeline
    :return:
    """

    if current_user.has_role("student") and student_id != current_user.id:
        flash("It is only possible to view the project timeline for your own account.", "info")
        return redirect(redirect_url())

    user = User.query.get_or_404(student_id)

    if not user.has_role("student"):
        flash("It is only possible to view project timelines for a student account.", "info")
        return redirect(redirect_url())

    if user.student_data is None:
        flash("Cannot display project timeline for this student account because the corresponding StudentData record is missing.", "error")
        return redirect(redirect_url())

    data = user.student_data

    if not data.has_timeline:
        if current_user.has_role("student"):
            flash(
                "You do not yet have a timeline because you have not completed any projects. "
                "This option will become available once you have one or more completed "
                "submissions in the database.",
                "info",
            )

        else:
            flash(
                "This student does not yet have any completed submissions. The timeline option "
                "will become available once one or more retired submissions have been entered "
                "in the database.",
                "info",
            )

        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # collate retired selector and submitter records for this student
    years, selector_records, submitter_records = data.collect_student_records()

    # check roles for logged-in user, to determine whether they are permitted to view the student's feedback
    roles = {}
    for year in submitter_records:
        submissions = submitter_records[year]
        for sub in submissions:
            for record in sub.ordered_assignments:
                if validate_is_convenor(sub.config.project_class, message=False):
                    roles[record.id] = "convenor"
                elif validate_submission_viewable(record, message=False):
                    roles[record.id] = "faculty"
                elif user.id == current_user.id and current_user.has_role("student"):
                    roles[record.id] = "student"

    student_text = "my timeline"
    generic_text = "student timeline".format(name=user.name)
    return_url = url_for("student.timeline", student_id=data.id, text=text, url=url)

    return render_template_context(
        "student/timeline.html",
        data=data,
        years=years,
        user=user,
        student=data,
        selector_records=selector_records,
        submitter_records=submitter_records,
        roles=roles,
        text=text,
        url=url,
        student_text=student_text,
        generic_text=generic_text,
        return_url=return_url,
    )
