#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime

import parse
from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_security import current_user, roles_accepted
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

import app.ajax as ajax
from app.convenor import convenor

from ..database import db
from ..models import (
    Bookmark,
    CustomOffer,
    FilterRecord,
    LiveProject,
    ProjectClass,
    ProjectClassConfig,
    ResearchGroup,
    SelectingStudent,
    SelectionRecord,
    TransferableSkill,
)
from ..shared.context.global_context import render_template_context
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    home_dashboard,
    redirect_url,
)
from ..shared.validators import (
    validate_is_convenor,
)
from ..shared.workflow_logging import log_db_commit
from .forms import (
    CreateCustomOfferFormFactory,
    EditCustomOfferFormFactory,
)


@convenor.route("/selector_bookmarks/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_bookmarks(id):
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view selector rankings before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/selector_bookmarks.html", sel=sel, now=datetime.now()
    )


@convenor.route("/project_bookmarks/<int:id>")
@roles_accepted("faculty", "admin", "root")
def project_bookmarks(id):
    # id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view selector rankings before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/project_bookmarks.html",
        project=proj,
        student_emails=[p.owner_email for p in proj.bookmarks],
    )


def _demap_project(item_id):
    result = parse.parse("P-{pid}", item_id)

    return int(result["pid"])


@convenor.route("/update_student_bookmarks", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def update_student_bookmarks():
    data = request.get_json()

    # discard if request is ill-formed
    if "ranking" not in data or "sid" not in data:
        return jsonify({"status": "ill_formed"})

    ranking = data["ranking"]
    sid = data["sid"]

    # sid is a SelectingStudent
    sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).first()

    if sel is None:
        return jsonify({"status": "data_missing"})

    if sel.retired:
        return jsonify({"status": "not_live"})

    if not validate_is_convenor(sel.config.project_class, message=False):
        return jsonify({"status": "insufficient_privileges"})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({"status": "too_early"})

    projects = map(_demap_project, ranking)

    rmap = {}
    index = 1
    for p in projects:
        rmap[p] = index
        index += 1

    # update ranking
    for bookmark in sel.bookmarks:
        bookmark: Bookmark
        bookmark.rank = rmap[bookmark.liveproject.id]

    try:
        log_db_commit(
            f"Updated bookmark ranking order for selector {sel.student.user.name}",
            user=current_user,
            student=sel.student,
            project_classes=sel.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "success"})


@convenor.route("/delete_student_bookmark/<int:sid>/<int:bid>")
@roles_accepted("faculty", "admin", "root")
def delete_student_bookmark(sid, bid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # bid is a Bookmark
    bookmark: Bookmark = Bookmark.query.get_or_404(bid)

    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to delete selector bookmarks before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    title = "Delete selector bookmark"
    panel_title = (
        'Delete bookmark for selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>, '
        "project <strong>{proj}</strong>".format(
            name=sel.student.user.name, proj=bookmark.liveproject.name
        )
    )
    action_url = url_for(
        "convenor.perform_delete_student_bookmark", sid=sid, bid=bid, url=url
    )
    message = (
        '<p>Please confirm that you wish to delete the bookmark held by selector <i class="fas fa-user-circle"></i> <strong>{name}</strong> '
        "for project <strong>{proj}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(
            name=sel.student.user.name, proj=bookmark.liveproject.name
        )
    )
    submit_label = "Delete bookmark"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/perform_delete_student_bookmark/<int:sid>/<int:bid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_student_bookmark(sid, bid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selector_bookmarks", id=sid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to delete selector bookmarks before the corresponding project class has gone live.",
            "error",
        )
        return redirect(url_for("convenor.selector_bookmarks", id=sid))

    bm: Bookmark = sel.bookmarks.filter_by(id=bid).first()

    if bm:
        sel.bookmarks.remove(bm)
        sel.re_rank_bookmarks()

        try:
            log_db_commit(
                f"Deleted bookmark for selector {sel.student.user.name}",
                user=current_user,
                student=sel.student,
                project_classes=sel.config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not remove bookmark due to a database error. Please inform a system administrator.",
                "info",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

    return redirect(url)


@convenor.route("/add_student_bookmark/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_bookmark(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to add a selector bookmark before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context("convenor/selector/add_bookmark.html", sel=sel)


@convenor.route("/add_student_bookmark_ajax/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_bookmark_ajax(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to add a selector bookmark before the corresponding project class has gone live.",
            "error",
        )
        return jsonify({})

    config = sel.config
    projects = config.live_projects.filter(~LiveProject.bookmarks.any(owner_id=sid))

    return ajax.convenor.add_student_bookmark(projects.all(), sel)


@convenor.route("/create_student_bookmark/<int:sel_id>/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def create_student_bookmark(sel_id, proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selector_bookmarks", id=sel_id)

    # check project and selector belong to the same project class
    if proj.config_id != sel.config_id:
        flash(
            'Project "{pname}" and selector "{sname}" do not belong to the same project class, so a '
            "bookmark cannot be created for this pair.".format(
                pname=proj.name, sname=sel.student.user.name
            ),
            "error",
        )
        return redirect(url)

    # check whether a bookmark with this project already exists
    q = sel.bookmarks.filter_by(liveproject_id=proj_id)

    if get_count(q) > 0:
        flash(
            'A request to create a bookmark for project "{pname}" and selector "{sname}" was ignored, '
            "because a bookmark for this pair already exists".format(
                pname=proj.name, sname=sel.student.user.name
            ),
            "info",
        )
        return redirect(url)

    bm = Bookmark(
        liveproject_id=proj.id, owner_id=sel.id, rank=sel.number_bookmarks + 1
    )

    try:
        db.session.add(bm)
        log_db_commit(
            f"Created bookmark for selector {sel.student.user.name} on project {proj.name}",
            user=current_user,
            student=sel.student,
            project_classes=sel.config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not create bookmark due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/selector_choices/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_choices(id):
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if text is None and url is None:
        url = url_for("convenor.selectors", id=sel.config.pclass_id)
        text = "dashboard"

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view selector rankings before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    if not sel.has_submitted:
        flash(
            "The ranking list for {name} can not yet be inspected because this selector has "
            "not yet submitted their ranked project choices (or accepted a "
            "custom offer.".format(name=sel.student.user.name),
            "info",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/selector_choices.html", sel=sel, text=text, url=url
    )


@convenor.route("/project_choices/<int:id>")
@roles_accepted("faculty", "admin", "root")
def project_choices(id):
    # id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view project rankings before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/project_choices.html",
        project=proj,
        student_emails=[p.owner_email for p in proj.selections],
    )


@convenor.route("/update_student_choices", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def update_student_choices():
    data = request.get_json()

    # discard is request is ill-formed
    if "ranking" not in data or "sid" not in data:
        return jsonify({"status": "ill_formed"})

    ranking = data["ranking"]
    sid = data["sid"]

    if ranking is None or sid is None:
        return jsonify({"status": "ill_formed"})

    # sid is a SelectingStudent
    sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).first()

    if sel is None:
        return jsonify({"status": "data_missing"})

    if sel.retired:
        return jsonify({"status": "not_live"})

    if not validate_is_convenor(sel.config.project_class, message=False):
        return jsonify({"status": "insufficient_privileges"})

    projects = map(_demap_project, ranking)

    rmap = {}
    index = 1
    for p in projects:
        rmap[p] = index
        index += 1

    # update ranking
    for selection in sel.selections:
        selection.rank = rmap[selection.liveproject.id]

    try:
        log_db_commit(
            f"Updated selection ranking order for selector {sel.student.user.name}",
            user=current_user,
            student=sel.student,
            project_classes=sel.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "success"})


@convenor.route("/delete_student_choice/<int:sid>/<int:cid>")
@roles_accepted("faculty", "admin", "root")
def delete_student_choice(sid, cid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # cid is a SelectionRecord
    record: SelectionRecord = SelectionRecord.query.get_or_404(cid)

    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to delete selector rankings before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    title = "Delete selector ranking"
    panel_title = (
        'Delete ranking for selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>, '
        "project <strong>{proj}</strong>".format(
            name=sel.student.user.name, proj=record.liveproject.name
        )
    )
    action_url = url_for(
        "convenor.perform_delete_student_choice", sid=sid, cid=cid, url=url
    )
    message = (
        '<p>Please confirm that you wish to delete <i class="fas fa-user-circle"></i> <strong>{name}</strong> '
        "ranking #{num} for project <strong>{proj}</strong>.</p>"
        "<p>This action cannot be undone.</p>"
        "<p><strong>Student-submitted rankings should be deleted only when there "
        "is a clear rationale for doing "
        "so.</strong></p>".format(
            name=sel.student.user.name, num=record.rank, proj=record.liveproject.name
        )
    )
    submit_label = "Delete ranking"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/perform_delete_student_choice/<int:sid>/<int:cid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_student_choice(sid, cid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selector_choices", id=sid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to delete selector rankings before the corresponding project class has gone live.",
            "error",
        )
        return redirect(url_for("convenor.selector_bookmarks", id=sid))

    rec: SelectionRecord = sel.selections.filter_by(id=cid).first()

    if rec:
        sel.selections.remove(rec)
        sel.re_rank_selections()

        try:
            log_db_commit(
                f"Deleted selection ranking for selector {sel.student.user.name}",
                user=current_user,
                student=sel.student,
                project_classes=sel.config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not remove ranking due to a database error. Please inform a system administrator.",
                "info",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

    return redirect(url)


@convenor.route("/add_student_ranking/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_ranking(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to add a selector ranking before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    if not sel.has_submitted:
        flash(
            "It is not possible to add a new ranking until the selector has submitted their own ranked list.",
            "info",
        )
        return redirect(redirect_url())

    return render_template_context("convenor/selector/add_ranking.html", sel=sel)


@convenor.route("/add_student_ranking_ajax/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_ranking_ajax(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    if not sel.has_submitted:
        return jsonify({})

    config = sel.config
    projects = config.live_projects.filter(~LiveProject.selections.any(owner_id=sid))

    return ajax.convenor.add_student_ranking(projects.all(), sel)


@convenor.route("/create_student_ranking/<int:sel_id>/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def create_student_ranking(sel_id, proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    if not sel.has_submitted:
        flash(
            "It is not possible to add a new ranking until the selector has submitted their own ranked list.",
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selector_bookmarks", id=sel_id)

    # check project and selector belong to the same project class
    if proj.config_id != sel.config_id:
        flash(
            'Project "{pname}" and selector "{sname}" do not belong to the same project class, so a '
            "ranking cannot be created for this pair.".format(
                pname=proj.name, sname=sel.student.user.name
            ),
            "error",
        )
        return redirect(url)

    # check whether a bookmark with this project already exists
    q = sel.selections.filter_by(liveproject_id=proj_id)

    if get_count(q) > 0:
        flash(
            'A request to create a ranking for project "{pname}" and selector "{sname}" was ignored, '
            "because a ranking for this pair already exists".format(
                pname=proj.name, sname=sel.student.user.name
            ),
            "info",
        )
        return redirect(url)

    rec = SelectionRecord(
        liveproject_id=proj.id,
        owner_id=sel.id,
        rank=sel.number_selections + 1,
        converted_from_bookmark=False,
        hint=SelectionRecord.SELECTION_HINT_NEUTRAL,
    )

    try:
        db.session.add(rec)
        log_db_commit(
            f"Created selection ranking for selector {sel.student.user.name} on project {proj.name}",
            user=current_user,
            student=sel.student,
            project_classes=sel.config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not create ranking due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/selector_confirmations/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_confirmations(id):
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view selector confirmations before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/selector_confirmations.html", sel=sel, now=datetime.now()
    )


@convenor.route("/project_custom_offers/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def project_custom_offers(proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view project custom offers before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/project_custom_offers.html",
        project=proj,
        pclass_id=proj.config.project_class.id,
    )


@convenor.route("/project_custom_offers_ajax/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def project_custom_offers_ajax(proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return jsonify({})

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    return ajax.convenor.project_offer_data(proj, proj.ordered_custom_offers.all())


@convenor.route("/selector_custom_offers/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def selector_custom_offers(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to view selector custom offers before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/selector_custom_offers.html",
        sel=sel,
        pclass_id=sel.config.project_class.id,
    )


@convenor.route("/selector_custom_offers_ajax/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def selector_custom_offers_ajax(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    return ajax.convenor.student_offer_data(sel, sel.ordered_custom_offers.all())


@convenor.route("/new_selector_offer/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def new_selector_offer(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to set up a new selector custom offer before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/selector_new_offer.html",
        sel=sel,
        pclass_id=sel.config.project_class.id,
    )


@convenor.route("/new_selector_offer_ajax/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def new_selector_offer_ajax(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    # get list of available projects, excluding any projects for which this selector already holds offers
    config: ProjectClassConfig = sel.config
    projects = config.live_projects.filter(
        ~LiveProject.custom_offers.any(selector_id=sel_id)
    )

    return ajax.convenor.new_student_offer_projects(projects.all(), sel)


@convenor.route("/new_project_offer/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def new_project_offer(proj_id):
    # proj_id is a LiveProject
    proj = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to set up a new custom offer before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    return render_template_context(
        "convenor/selector/project_new_offer.html",
        project=proj,
        pclass_id=proj.config.project_class.id,
    )


@convenor.route("/new_project_offer_ajax/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def new_project_offer_ajax(proj_id):
    # proj_id is a LiveProject
    proj = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return jsonify({})

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash(
            "It is not possible to set up a new custom offer before the corresponding project class has gone live.",
            "error",
        )
        return redirect(redirect_url())

    # get list of available selectors, excluding any selectors who already hold offers for this project
    config: ProjectClassConfig = proj.config
    selectors = config.selecting_students.filter(
        ~SelectingStudent.custom_offers.any(liveproject_id=proj_id)
    )

    return ajax.convenor.new_project_offer_selectors(selectors.all(), proj)


@convenor.route("/create_new_offer/<int:sel_id>/<int:proj_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def create_custom_offer(sel_id, proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)
    config: ProjectClassConfig = proj.config
    pclass: ProjectClass = config.project_class

    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    url = request.args.get("url", None)
    if url is None:
        # in theory would be more natural to default to the custom offer view,
        # but we could have arrived here from the project or selector route, and we
        # don't know which is which
        url = url_for("convenor.selectors", id=config.pclass_id)

    # check project and selector belong to the same project class
    if proj.config_id != sel.config_id:
        flash(
            'Project "{pname}" and selector "{sname}" do not belong to the same project cycle, so a '
            "custom offer cannot be created for this pair.".format(
                pname=proj.name, sname=sel.student.user.name
            ),
            "error",
        )
        return redirect(url)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    # check whether an offer with this selector and project already exists
    q = (
        db.session.query(CustomOffer)
        .filter(
            CustomOffer.liveproject_id == proj_id, CustomOffer.selector_id == sel_id
        )
        .first()
    )
    if q is not None:
        flash(
            'A request to create a custom offer for project "{pname}" and selector "{sname}" was ignored, '
            "because an offer for this pair already exists".format(
                pname=proj.name, sname=sel.student.user.name
            ),
            "info",
        )
        return redirect(url)

    OfferForm = CreateCustomOfferFormFactory(pclass, config.year + 1)
    form = OfferForm(request.form)
    if hasattr(form, "period"):
        form.period.query = pclass.ordered_periods

    if form.validate_on_submit():
        offer = CustomOffer(
            liveproject_id=proj.id,
            selector_id=sel.id,
            status=CustomOffer.OFFERED,
            period=None,
            comment=form.comment.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )
        if hasattr(form, "period"):
            offer.period = form.period.data

        try:
            db.session.add(offer)
            log_db_commit(
                f"Created custom offer for selector {sel.student.user.name} on project {proj.name}",
                user=current_user,
                student=sel.student,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not create custom offer due to a database error. Please contact a system administrator",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

        return redirect(url)

    return render_template_context(
        "convenor/selector/create_custom_offer.html",
        form=form,
        sel=sel,
        proj=proj,
        config=config,
        url=url,
    )


@convenor.route("/edit_custom_offer/<int:offer_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_custom_offer(offer_id):
    # offer_id is a CustomOffer instances
    offer: CustomOffer = CustomOffer.query.get_or_404(offer_id)
    proj: LiveProject = offer.liveproject
    config: ProjectClassConfig = proj.config
    pclass: ProjectClass = config.project_class
    sel: SelectingStudent = offer.selector

    url = request.args.get("url", None)
    if url is None:
        # in theory would be more natural to default to the custom offer view,
        # but we could have arrived here from the project or selector route, and we
        # don't know which is which
        url = url_for("convenor.selectors", id=config.pclass_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    OfferForm = EditCustomOfferFormFactory(pclass, config.year + 1)
    form = OfferForm(obj=offer)
    if hasattr(form, "period"):
        form.period.query = pclass.ordered_periods

    if form.validate_on_submit():
        offer.comment = form.comment.data
        if hasattr(form, "period"):
            offer.period = form.period.data

        offer.last_edit_id = current_user.id
        offer.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Edited custom offer for selector {sel.student.user.name} on project {proj.name}",
                user=current_user,
                student=sel.student,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save edited custom offer due to a database error. Please contact a system administrator",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

        return redirect(url)

    return render_template_context(
        "convenor/selector/edit_custom_offer.html", form=form, offer=offer, url=url
    )


@convenor.route("/accept_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def accept_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer: CustomOffer = CustomOffer.query.get_or_404(offer_id)
    proj: LiveProject = offer.liveproject
    sel: SelectingStudent = offer.selector
    config: ProjectClassConfig = sel.config
    pclass: ProjectClass = config.project_class

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if sel.number_offers_accepted() >= sel.number_choices:
        flash(
            "The maximum number of custom offers have already been accepted for selector {name}. "
            "Please decline this offer before accepting a new one.".format(
                name=offer.selector.student.user.name
            ),
            "error",
        )
        return redirect(redirect_url())

    if offer.period is not None and sel.number_offers_accepted(offer.period) > 0:
        flash(
            f"A custom offer has already been accepted for selector {offer.selector.student.user.name} "
            f"in period {offer.period.display_name(config.year + 1)}. "
            f"Please decline this offer before accepting a new one.",
            "error",
        )
        return redirect(redirect_url())

    offer.status = CustomOffer.ACCEPTED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        log_db_commit(
            f"Accepted custom offer for selector {sel.student.user.name} on project {proj.name}",
            user=current_user,
            student=sel.student,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not mark custom offer as accepted due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/decline_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def decline_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer = CustomOffer.query.get_or_404(offer_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(offer.liveproject.config.project_class):
        return redirect(redirect_url())

    offer.status = CustomOffer.DECLINED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        log_db_commit(
            f"Declined custom offer for selector {offer.selector.student.user.name} on project {offer.liveproject.name}",
            user=current_user,
            student=offer.selector.student,
            project_classes=offer.liveproject.config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not mark custom offer as declined due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/undecide_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def undecide_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer = CustomOffer.query.get_or_404(offer_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(offer.liveproject.config.project_class):
        return redirect(redirect_url())

    offer.status = CustomOffer.OFFERED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        log_db_commit(
            f"Reset custom offer to pending for selector {offer.selector.student.user.name} on project {offer.liveproject.name}",
            user=current_user,
            student=offer.selector.student,
            project_classes=offer.liveproject.config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not mark custom offer as pending due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/delete_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def delete_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer = CustomOffer.query.get_or_404(offer_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(offer.liveproject.config.project_class):
        return redirect(redirect_url())

    _offer_selector_name = offer.selector.student.user.name
    _offer_project_name = offer.liveproject.name
    _offer_pclass = offer.liveproject.config.project_class
    _offer_student = offer.selector.student

    try:
        db.session.delete(offer)
        log_db_commit(
            f"Deleted custom offer for selector {_offer_selector_name} on project {_offer_project_name}",
            user=current_user,
            student=_offer_student,
            project_classes=_offer_pclass,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not delete custom offer due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/project_confirmations/<int:id>")
@roles_accepted("faculty", "admin", "root")
def project_confirmations(id):
    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return home_dashboard()

    return render_template_context(
        "convenor/selector/project_confirmations.html", project=proj, now=datetime.now()
    )


@convenor.route("/add_group_filter/<int:id>/<int:gid>")
@roles_accepted("faculty", "admin", "root")
def add_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if group not in record.group_filters:
        try:
            record.group_filters.append(group)
            log_db_commit(
                f"Added research group filter '{group.name}' for selector filter record",
                user=current_user,
                project_classes=record.config.project_class,
            )
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/remove_group_filter/<int:id>/<int:gid>")
@roles_accepted("faculty", "admin", "root")
def remove_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if group in record.group_filters:
        try:
            record.group_filters.remove(group)
            log_db_commit(
                f"Removed research group filter '{group.name}' from selector filter record",
                user=current_user,
                project_classes=record.config.project_class,
            )
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/clear_group_filters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def clear_group_filters(id):
    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    try:
        record.group_filters = []
        log_db_commit(
            "Cleared all research group filters from selector filter record",
            user=current_user,
            project_classes=record.config.project_class,
        )
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/add_skill_filter/<int:id>/<int:skill_id>")
@roles_accepted("faculty", "admin", "root")
def add_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if skill not in record.skill_filters:
        try:
            record.skill_filters.append(skill)
            log_db_commit(
                f"Added transferable skill filter '{skill.name}' to selector filter record",
                user=current_user,
                project_classes=record.config.project_class,
            )
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/remove_skill_filter/<int:id>/<int:skill_id>")
@roles_accepted("faculty", "admin", "root")
def remove_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if skill in record.skill_filters:
        try:
            record.skill_filters.remove(skill)
            log_db_commit(
                f"Removed transferable skill filter '{skill.name}' from selector filter record",
                user=current_user,
                project_classes=record.config.project_class,
            )
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/clear_skill_filters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def clear_skill_filters(id):
    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    try:
        record.skill_filters = []
        log_db_commit(
            "Cleared all transferable skill filters from selector filter record",
            user=current_user,
            project_classes=record.config.project_class,
        )
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/set_hint/<int:id>/<int:hint>")
@roles_accepted("faculty", "admin", "root")
def set_hint(id, hint):
    rec = SelectionRecord.query.get_or_404(id)
    config = rec.owner.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash(
            "Selection hints may only be set once student choices are closed and the project class is ready to match",
            "error",
        )
        return redirect(redirect_url())

    try:
        rec.set_hint(hint)
        log_db_commit(
            f"Set selection hint for selector {rec.owner.student.user.name} on project {rec.liveproject.name}",
            user=current_user,
            student=rec.owner.student,
            project_classes=config.project_class,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not set selection hint due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/hints_list/<int:id>")
@roles_accepted("faculty", "admin", "root")
def hints_list(id):
    # pid is a ProjectClass
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

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash(
            "Selection hints may only be set once student choices are closed and the project class is ready to match",
            "error",
        )
        return redirect(redirect_url())

    hints = (
        db.session.query(SelectionRecord)
        .join(SelectingStudent, SelectingStudent.id == SelectionRecord.owner_id)
        .filter(SelectingStudent.config_id == config.id)
        .filter(SelectionRecord.hint != SelectionRecord.SELECTION_HINT_NEUTRAL)
        .all()
    )

    return render_template_context(
        "convenor/dashboard/hints_list.html", pclass=pclass, hints=hints
    )
