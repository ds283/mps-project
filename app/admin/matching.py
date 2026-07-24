#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple, Union

from bokeh.embed import components
from bokeh.plotting import figure
from celery import chain
from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask_security import (
    current_user,
    roles_accepted,
    roles_required,
)
from numpy import histogram
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax

from ..database import db
from ..models import (
    EmailTemplate,
    EnrollmentRecord,
    FacultyData,
    LiveProject,
    MatchingAttempt,
    MatchingCommentReadMarker,
    MatchingRecord,
    MatchingReviewComment,
    MatchingRole,
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    SelectionRecord,
    TaskRecord,
    User,
)
from ..shared.forms.forms import ChooseEmailTemplateForm, ChoosePairedEmailTemplatesForm, ConfirmActionForm
from ..shared.forms.queries import GetWorkflowTemplates
from ..shared.context.global_context import render_template_context
from ..shared.context.matching import (
    get_matching_dashboard_data,
    get_ready_to_match_data,
)
from ..shared.conversions import is_integer
from ..shared.sqlalchemy import get_count
from ..shared import matching_workspace as workspace_service
from ..shared.utils import (
    get_automatch_pclasses,
    get_current_year,
    home_dashboard_url,
    redirect_url,
)
from ..shared.validators import (
    validate_is_convenor,
    validate_match_inspector,
)
from ..shared.workflow_logging import log_db_commit
from ..task_queue import progress_update, register_task
from ..tools import ServerSideInMemoryHandler
from . import admin
from .actions import estimate_CATS_load
from .system import _compute_allowed_matching_years
from .forms import (
    CompareMatchFormFactory,
    EditMatchRolesFormFactory,
    EditSupervisorRolesForm,
    MatchCommentFormFactory,
    MatchCommentReplyForm,
    NewMatchFormFactory,
    RenameMatchFormFactory,
    SelectMatchingYearFormFactory,
)


@admin.route("/manage_matching", methods=["GET", "POST"])
@roles_required("root")
def manage_matching():
    # legacy entry point — the top-level Matches list now lives in the Matching Workspace
    # (see .prompts/matching-workspace/PLAN.md, decision 2: "parallel v2, switch entry points")
    year_arg = request.args.get("year", None)
    kwargs = {"year": year_arg} if year_arg is not None else {}
    return redirect(url_for("admin.matching_dashboard", **kwargs))


def _resolve_matching_dashboard_scope():
    """
    Resolve the privilege-scoped view for the top-level Matches list (decision 3 in
    .prompts/matching-workspace/PLAN.md): a `pclass_id` query arg selects the convenor scope
    (config.published_matches for that pclass); otherwise root/admin see all attempts for a year.

    Returns (is_root_view, pclass_or_none, config_or_none, year_or_none, error_response_or_none).
    """
    pclass_id = request.args.get("pclass_id", None)

    if pclass_id is not None:
        flag, pclass_id_value = is_integer(pclass_id)
        if not flag:
            abort(404)
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id_value)

        if not validate_is_convenor(pclass):
            return False, None, None, None, redirect(redirect_url())

        config: ProjectClassConfig = pclass.most_recent_config
        if config is None:
            flash(
                "Could not find a current configuration for this project class. Please contact a system administrator.",
                "error",
            )
            return False, None, None, None, redirect(url_for("convenor.overview"))

        return False, pclass, config, config.year, None

    if not (current_user.has_role("root") or current_user.has_role("admin")):
        flash("This operation is available only to administrative users and project convenors.", "error")
        return True, None, None, None, redirect(redirect_url())

    return True, None, None, None, None


@admin.route("/matching_dashboard")
@roles_accepted("faculty", "admin", "root")
def matching_dashboard():
    """
    Top-level Matches list (decision 5 in .prompts/matching-workspace/PLAN.md): one
    privilege-scoped standalone page, replacing `manage.html` + `audit.html`.
    """
    is_root_view, pclass, config, _year, error = _resolve_matching_dashboard_scope()
    if error is not None:
        return error

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()
        text = "home dashboard"

    if not is_root_view:
        return render_template_context(
            "admin/matching_workspace/matching_dashboard.html",
            is_root_view=False,
            pclass=pclass,
            config=config,
            year=config.year,
            form=None,
            text=text,
            url=url,
        )

    current_year = get_current_year()
    year_arg = request.args.get("year", request.args.get("selector", None))
    flag, requested_year = is_integer(year_arg)

    allowed_years, data = _compute_allowed_matching_years(current_year)

    if len(allowed_years) == 0:
        if not data["matching_ready"]:
            flash(
                "Automated matching is not yet available because some project classes are not ready",
                "error",
            )
            return redirect(redirect_url())

        if data["rollover_in_progress"]:
            flash(
                "Automated matching is not available because a rollover of the academic year is underway",
                "info",
            )
            return redirect(redirect_url())

        flash(
            "Automated matching is not available because no years are currently eligible",
            category="info",
        )
        return redirect(redirect_url())

    SelectMatchingYearForm = SelectMatchingYearFormFactory(allowed_years)
    form = SelectMatchingYearForm(request.args)

    if flag and requested_year is not None and requested_year in allowed_years:
        selected_year = requested_year
    elif hasattr(form, "selector") and form.selector.data is not None and form.selector.data in allowed_years:
        selected_year = form.selector.data
    else:
        selected_year = max(allowed_years)

    if hasattr(form, "selector"):
        form.selector.data = selected_year

    return render_template_context(
        "admin/matching_workspace/matching_dashboard.html",
        is_root_view=True,
        pclass=None,
        config=None,
        year=selected_year,
        form=form,
        text=text,
        url=url,
    )


@admin.route("/matches_v2_ajax")
@roles_accepted("faculty", "admin", "root")
def matches_v2_ajax():
    """
    Consolidated privilege-scoped feed for the top-level Matches list. Renders only cheap,
    always-available fields (name/tags/status flags/counts) — never the expensive per-attempt
    statistics (score, programme-preference/hint status, delta/CATS range, errors/warnings),
    which are fetched on demand per-card via match_statistics_ajax.

    Each card's own links (Open, Inspect: student/faculty view) must return to *this* dashboard
    (scoped by pclass_id/year) — not to whatever upstream url/text the dashboard page itself was
    given for its own Return control — so the return target is (re)built here rather than being
    threaded through from the page's query args.
    """
    is_root_view, pclass, config, _year, error = _resolve_matching_dashboard_scope()
    if error is not None:
        return jsonify({"cards": []}), 403

    if not is_root_view:
        matches = config.published_matches.order_by(MatchingAttempt.creation_timestamp.desc()).all()
        return ajax.admin.matches_dashboard_data(
            matches,
            config=config,
            is_root=current_user.has_role("root"),
            text="matching audit dashboard",
            url=url_for("admin.matching_dashboard", pclass_id=pclass.id),
        )

    year_arg = request.args.get("year", None)
    flag, requested_year = is_integer(year_arg)
    if not flag:
        return jsonify({"cards": []})

    matches = db.session.query(MatchingAttempt).filter_by(year=requested_year).order_by(MatchingAttempt.creation_timestamp.desc()).all()

    return ajax.admin.matches_dashboard_data(
        matches,
        config=None,
        is_root=True,
        text="matching dashboard",
        url=url_for("admin.matching_dashboard", year=requested_year),
    )


@admin.route("/match_statistics_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_statistics_ajax(id):
    """
    On-demand statistics bundle for one MatchingAttempt (programme-preference matched/failed,
    hint satisfied/violated, delta/CATS range, objective score, and validation errors/warnings).
    Computed fresh on every call — never cached, and never touched by the initial dashboard
    render (see PLAN.md non-goals: "no new caching").
    """
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(attempt):
        return jsonify({}), 403

    if not attempt.finished or not attempt.solution_usable:
        return jsonify({}), 404

    stats = workspace_service.dashboard_statistics(attempt)

    return render_template_context(
        "admin/matching_workspace/_dashboard_stats.html",
        m=attempt,
        stats=stats,
    )


@admin.route("/skip_matching")
@roles_required("root")
def skip_matching():
    """
    Mark current set of ProjectClassConfig instances to skip automated matching
    :return:
    """
    current_year = get_current_year()

    pcs = db.session.query(ProjectClass).filter_by(active=True).order_by(ProjectClass.name.asc()).all()

    for pclass in pcs:
        # get current configuration record for this project class
        config = pclass.most_recent_config

        if config is not None and config.year == current_year:
            config.skip_matching = True

    try:
        log_db_commit("Mark all active project class configs to skip automated matching", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Can not skip matching due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/create_match", methods=["GET", "POST"])
@roles_required("root")
def create_match():
    """
    Create the 'create match' dashboard view
    :return:
    """
    current_year = get_current_year()
    selected_year = request.args.get("year", current_year)

    # check that all projects are ready to match
    data = get_ready_to_match_data()

    if selected_year == current_year and data["rollover_in_progress"]:
        (
            flash(
                "Automated matching is not available because a rollover of the academic year is underway",
                "info",
            ),
        )
        return redirect(redirect_url())

    info = get_matching_dashboard_data(selected_year)

    base_id = request.args.get("base_id", None)

    base_match: MatchingAttempt
    base_match = None
    if base_id is not None:
        base_match = MatchingAttempt.query.get_or_404(base_id)

        if base_match.year != selected_year:
            flash(
                f'Cannot use base match "{base_match.name}" because it belongs to a different '
                f"academic year (base match year = {base_match.year}, selected year = {selected_year}",
                "info",
            )
            return redirect(redirect_url())

    NewMatchForm = NewMatchFormFactory(current_year, base_id=base_id, base_match=base_match)
    form = NewMatchForm(request.form)

    if form.validate_on_submit():
        offline = False

        if form.submit.data:
            task_name = 'Perform project matching for "{name}"'.format(name=form.name.data)
            desc = "Automated project matching task"

        elif form.offline.data:
            offline = True
            task_name = 'Generate file for offline matching for "{name}"'.format(name=form.name.data)
            desc = "Produce .LP file for download and offline matching"

        else:
            raise RuntimeError("Unknown submit button in create_match()")

        uuid = register_task(task_name, owner=current_user, description=desc)

        include_control = getattr(form, "include_only_submitted", None)
        # logic for include_only_submitted is a bit delicate:
        #   Form    Base    Outcome
        #   T/F     None    T/F based on form
        #   T/F     True    T/F based on form
        #   absent  False   False
        include_only_submitted = (include_control.data if include_control is not None else False) and (
            base_match.include_only_submitted if base_match is not None else True
        )

        base_bias_control = getattr(form, "base_bias", None)
        force_base_control = getattr(form, "force_base", None)

        attempt = MatchingAttempt(
            year=selected_year,
            base_id=base_id,
            base_bias=base_bias_control.data if base_bias_control is not None else None,
            force_base=force_base_control.data if force_base_control is not None else None,
            name=form.name.data,
            celery_id=uuid,
            finished=False,
            celery_finished=False,
            awaiting_upload=offline,
            outcome=None,
            published=False,
            selected=False,
            construct_time=None,
            compute_time=None,
            include_only_submitted=include_only_submitted,
            ignore_per_faculty_limits=form.ignore_per_faculty_limits.data,
            ignore_programme_prefs=form.ignore_programme_prefs.data,
            years_memory=form.years_memory.data,
            supervising_limit=form.supervising_limit.data,
            marking_limit=form.marking_limit.data,
            max_marking_multiplicity=form.max_marking_multiplicity.data,
            max_different_group_projects=form.max_different_group_projects.data,
            max_different_all_projects=form.max_different_all_projects.data,
            levelling_bias=form.levelling_bias.data,
            supervising_pressure=form.supervising_pressure.data,
            marking_pressure=form.marking_pressure.data,
            CATS_violation_penalty=form.CATS_violation_penalty.data,
            no_assignment_penalty=form.no_assignment_penalty.data,
            intra_group_tension=form.intra_group_tension.data,
            programme_bias=form.programme_bias.data,
            bookmark_bias=form.bookmark_bias.data,
            use_hints=form.use_hints.data,
            require_to_encourage=form.require_to_encourage.data,
            forbid_to_discourage=form.forbid_to_discourage.data,
            encourage_bias=form.encourage_bias.data,
            discourage_bias=form.discourage_bias.data,
            strong_encourage_bias=form.strong_encourage_bias.data,
            strong_discourage_bias=form.strong_discourage_bias.data,
            solver=form.solver.data,
            creation_timestamp=datetime.now(),
            creator_id=current_user.id,
            last_edit_timestamp=None,
            last_edit_id=None,
            score=None,
            lp_file_id=None,
        )

        # check whether there is any work to do -- is there a current config entry for each
        # attached pclass?
        count = 0
        for pclass in form.pclasses_to_include.data:
            config = pclass.get_config(current_year)

            if config is not None:
                if config not in attempt.config_members:
                    count += 1
                    attempt.config_members.append(config)

        if base_match is not None:
            for config in base_match.config_members:
                if config not in attempt.config_members:
                    count += 1
                    attempt.config_members.append(config)

        if count == 0:
            flash(
                "No project classes were specified for inclusion, so no match was computed.",
                "error",
            )
            return redirect(url_for("admin.manage_caching"))

        def _validate_included_match(match):
            ok = True

            for config_a in attempt.config_members:
                for config_b in match.config_members:
                    if config_a.id == config_b.id:
                        ok = False
                        flash(
                            'Excluded CATS from existing match "{name}" since it contains project class '
                            '"{pname}" which overlaps with the current match'.format(name=match.name, pname=config_a.name)
                        )
                        break

            return ok

        # for matches we are supposed to take account of when levelling workload, check that there is no overlap
        # with the projects we will include in this match
        for match in form.include_matches.data:
            if match not in attempt.include_matches:
                if _validate_included_match(match):
                    attempt.include_matches.append(match)

        if base_match is not None:
            for match in base_match.include_matches:
                if match not in attempt.include_matches:
                    if _validate_included_match(match):
                        attempt.include_matches.append(match)

        try:
            db.session.add(attempt)
            log_db_commit("Create new matching attempt and schedule matching task", user=current_user)

            if offline:
                celery = current_app.extensions["celery"]
                match_task = celery.tasks["app.tasks.matching.offline_match"]

                match_task.apply_async(args=(attempt.id, current_user.id), task_id=uuid)

            else:
                celery = current_app.extensions["celery"]
                match_task = celery.tasks["app.tasks.matching.create_match"]

                match_task.apply_async(args=(attempt.id,), task_id=uuid)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not perform matching due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.manage_matching"))

    else:
        if request.method == "GET":
            form.use_hints.data = True

            if base_match is not None:
                # pre-populate form fields with same parameters used for base match
                form.programme_bias.data = base_match.programme_bias
                form.bookmark_bias.data = base_match.bookmark_bias

                form.use_hints.data = base_match.use_hints
                form.require_to_encourage.data = False
                form.forbid_to_discourage.data = False

                form.supervising_limit.data = base_match.supervising_limit
                form.marking_limit.data = base_match.marking_limit
                form.max_marking_multiplicity.data = base_match.max_marking_multiplicity
                form.max_different_group_projects.data = base_match.max_different_group_projects
                form.max_different_all_projects.data = base_match.max_different_all_projects

                form.levelling_bias.data = base_match.levelling_bias
                form.supervising_pressure.data = base_match.supervising_pressure
                form.marking_pressure.data = base_match.marking_pressure
                form.CATS_violation_penalty.data = base_match.CATS_violation_penalty
                form.no_assignment_penalty.data = base_match.no_assignment_penalty

                form.intra_group_tension.data = base_match.intra_group_tension

                form.encourage_bias.data = base_match.encourage_bias
                form.discourage_bias.data = base_match.discourage_bias
                form.strong_encourage_bias.data = base_match.strong_encourage_bias
                form.strong_discourage_bias.data = base_match.strong_discourage_bias

                form.solver.data = base_match.solver

            else:
                form.solver.data = MatchingAttempt.SOLVER_CBC_CMD

    # estimate equitable CATS loading
    data = estimate_CATS_load()

    return render_template_context(
        "admin/matching/create.html",
        pane="create",
        info=info,
        form=form,
        data=data,
        base_match=base_match,
    )


@admin.route("/terminate_match/<int:id>")
@roles_required("root")
def terminate_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if record.finished:
        flash(
            'Can not terminate matching task "{name}" because it has finished.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    title = "Terminate match"
    panel_title = "Terminate match <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_terminate_match", id=id, url=request.referrer)
    message = "<p>Please confirm that you wish to terminate the matching job <strong>{name}</strong>.</p><p>This action cannot be undone.</p>".format(
        name=record.name
    )
    submit_label = "Terminate job"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@admin.route("/perform_terminate_match/<int:id>", methods=["POST"])
@roles_required("root")
def perform_terminate_match(id):
    record: MatchingRecord = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if record.finished:
        flash(
            'Can not terminate matching task "{name}" because it has finished.'.format(name=record.name),
            "error",
        )
        return redirect(url)

    if not record.celery_finished:
        celery = current_app.extensions["celery"]
        celery.control.revoke(record.celery_id, terminate=True, signal="SIGUSR1")

    try:
        if not record.celery_finished:
            progress_update(
                record.celery_id,
                TaskRecord.TERMINATED,
                100,
                "Task terminated by user",
                autocommit=False,
            )

        # delete all MatchingRecords associated with this MatchingAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(MatchingRecord).filter_by(matching_id=record.id).delete()

        expire_time = datetime.now() + timedelta(days=1)
        if record.lp_file is not None:
            record.lp_file.expiry = expire_time
            record.lp_file = None

        db.session.delete(record)
        log_db_commit("Terminate matching task and delete associated matching attempt record", user=current_user)

    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not terminate matching task "{name}" due to a database error. Please contact a system administrator.'.format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/delete_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def delete_match(id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    if not current_user.has_role("root") and current_user.id != attempt.creator_id:
        flash('Match "{name}" cannot be deleted because it belongs to another user')
        return redirect(redirect_url())

    if not attempt.finished:
        flash(
            'Can not delete match "{name}" because it has not terminated. If you wish to delete this match, please terminate it first.'.format(
                name=attempt.name
            ),
            "error",
        )
        return redirect(redirect_url())

    if attempt.selected:
        flash(
            'Can not delete match "{name}" because it has been selected for use during rollover of the '
            "academic year. Please deselect and unpublish this match before attempting to delete "
            "it.".format(name=attempt.name),
            "error",
        )
        return redirect(redirect_url())

    if attempt.published:
        flash(
            'Can not delete match "{name}" because it has been published to convenors. Please unpublish '
            "this match before attempting to delete it.".format(name=attempt.name),
            "error",
        )
        return redirect(redirect_url())

    title = "Delete match"
    panel_title = "Delete match <strong>{name}</strong>".format(name=attempt.name)

    action_url = url_for("admin.perform_delete_match", id=id, url=request.referrer)
    message = "<p>Please confirm that you wish to delete the matching <strong>{name}</strong>.</p><p>This action cannot be undone.</p>".format(
        name=attempt.name
    )
    submit_label = "Delete match"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@admin.route("/perform_delete_match/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def perform_delete_match(id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if not validate_match_inspector(attempt):
        return redirect(url)

    year = get_current_year()
    if attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(url)

    if not current_user.has_role("root") and current_user.id != attempt.creator_id:
        flash('Match "{name}" cannot be deleted because it belongs to another user')
        return redirect(url)

    if not attempt.finished:
        flash(
            'Can not delete match "{name}" because it has not terminated.'.format(name=attempt.name),
            "error",
        )
        return redirect(url)

    if attempt.selected:
        flash(
            'Can not delete match "{name}" because it has been selected for use during rollover of the '
            "academic year. Please deselect and unpublish this match before attempting to delete "
            "it.".format(name=attempt.name),
            "error",
        )
        return redirect(url)

    if attempt.published:
        flash(
            'Can not delete match "{name}" because it has been published to convenors. Please unpublish '
            "this match before attempting to delete it.".format(name=attempt.name),
            "error",
        )
        return redirect(url)

    try:
        expire_time = datetime.now() + timedelta(days=1)
        if attempt.lp_file is not None:
            attempt.lp_file.expiry = expire_time
            attempt.lp_file = None

        db.session.delete(attempt)
        log_db_commit('Delete matching attempt "{name}"'.format(name=attempt.name), user=current_user)
        flash(
            'Match "{name}" was successfully deleted.'.format(name=attempt.name),
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not delete match "{name}" due to a database error. Please contact a system administrator.'.format(name=attempt.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/clean_up_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def clean_up_match(id):
    attempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    if not attempt.finished:
        flash(
            'Can not clean up match "{name}" because it has not terminated.'.format(name=attempt.name),
            "error",
        )
        return redirect(redirect_url())

    title = "Clean up match"
    panel_title = "Clean up match <strong>{name}</strong>".format(name=attempt.name)

    action_url = url_for("admin.perform_clean_up_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to clean up the matching "
        "<strong>{name}</strong>.</p>"
        "<p>Some selectors may be removed if they are no longer available for conversion.</p>"
        "<p>This action cannot be undone.</p>".format(name=attempt.name)
    )
    submit_label = "Clean up match"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@admin.route("/perform_clean_up_match/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def perform_clean_up_match(id):
    attempt = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if not validate_match_inspector(attempt):
        return redirect(url)

    year = get_current_year()
    if attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(url)

    if not attempt.finished:
        flash(
            'Can not clean up match "{name}" because it has not terminated.'.format(name=attempt.name),
            "error",
        )
        return redirect(url)

    if not current_user.has_role("root") and current_user.id != attempt.creator_id:
        flash('Match "{name}" cannot be cleaned up because it belongs to another user')
        return redirect(url)

    try:
        # delete all MatchingRecords associated with selectors who are not converting
        for rec in attempt.records:
            if not rec.selector.convert_to_submitter:
                db.session.delete(rec)

        log_db_commit(
            'Clean up matching attempt "{name}" by removing records for non-converting selectors'.format(name=attempt.name),
            user=current_user,
        )
        flash(
            'Match "{name}" was successfully cleaned up.'.format(name=attempt.name),
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not clean up match "{name}" due to a database error. Please contact a system administrator.'.format(name=attempt.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/revert_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def revert_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not revert match "{name}" because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not revert match "{name}" because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not revert match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    title = "Revert match"
    panel_title = "Revert match <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_revert_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to revert the matching "
        "<strong>{name}</strong> to its original state.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Revert match"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@admin.route("/perform_revert_match/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def perform_revert_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        # TODO consider an alternative implementation here
        url = url_for("admin.manage_matching")

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not revert match "{name}" because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not revert match "{name}" because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not revert match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    # hand off revert job to asynchronous queue
    celery = current_app.extensions["celery"]
    revert = celery.tasks["app.tasks.matching.revert"]

    tk_name = "Revert {name}".format(name=record.name)
    tk_description = "Revert matching to its original state"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        revert.si(record.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url)


@admin.route("/revert_match_record/<int:rec_id>")
@roles_accepted("faculty", "admin", "root")
def revert_match_record(rec_id):
    """
    Revert a single MatchingRecord to its optimiser baseline (original_project_id/
    original_alternative/original_parent_id/original_priority/original_roles). Unlike
    revert_match/perform_revert_match (which reverts every record in the attempt via an
    asynchronous Celery chain), this is a single-record edit and is applied synchronously,
    consistent with reassign_match_project/reassign_match_marker.
    """
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    record.project_id = record.original_project_id
    record.rank = record.selector.project_rank(record.original_project_id)
    record.alternative = record.original_alternative
    record.parent_id = record.original_parent_id
    record.priority = record.original_priority

    for role in record.roles.all():
        db.session.delete(role)
    db.session.flush()

    for orig_role in record.original_roles.all():
        orig_role: MatchingRole
        new_role = MatchingRole(user_id=orig_role.user_id, role=orig_role.role)
        record.roles.append(new_role)

    # the record is back at its optimizer baseline, so it no longer represents a manual divergence;
    # but the attempt as a whole has just been edited, so its own provenance is updated
    record.clear_edited()
    record.matching_attempt.last_edit_id = current_user.id
    record.matching_attempt.last_edit_timestamp = datetime.now()

    try:
        log_db_commit(
            "Reverted matching record #{id} to original project and role assignments".format(id=record.id),
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not revert matching record because a database error was encountered.", "error")

    return redirect(redirect_url())


@admin.route("/duplicate_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def duplicate_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle.',
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not duplicate match "{name}" because it is still awaiting manual upload'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not duplicate match "{name}" because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not duplicate match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    suffix = 2
    while suffix < 100:
        new_name = "{name} #{suffix}".format(name=record.name, suffix=suffix)

        if MatchingAttempt.query.filter_by(name=new_name, year=year).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash(
            'Can not duplicate match "{name}" because a new unique tag could not be generated.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    # hand off duplicate job to asynchronous queue
    celery = current_app.extensions["celery"]
    duplicate = celery.tasks["app.tasks.matching.duplicate"]

    tk_name = "Duplicate {name}".format(name=record.name)
    tk_description = "Duplicate matching"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        duplicate.si(record.id, new_name, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/rename_match/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def rename_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    RenameMatchForm = RenameMatchFormFactory(year)
    form = RenameMatchForm(request.form)
    form.record = record

    if form.validate_on_submit():
        try:
            record.name = form.name.data
            log_db_commit('Rename matching attempt to "{name}"'.format(name=form.name.data), user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                'Could not rename match "{name}" due to a database error. Please contact a system administrator.'.format(name=record.name),
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context("admin/match_inspector/rename.html", form=form, record=record, url=url)


@admin.route("/compare_match/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def compare_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(name=record.name),
                "error",
            )

    if not record.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    year = get_current_year()
    our_pclasses = {x.id for x in record.available_pclasses}

    CompareMatchForm = CompareMatchFormFactory(year, record.id, our_pclasses, current_user.has_role("root"))
    form = CompareMatchForm(request.form)

    if form.validate_on_submit():
        comparator = form.target.data
        return redirect(url_for("admin.do_match_compare", id1=id, id2=comparator.id, text=text, url=url))

    return render_template_context(
        "admin/match_inspector/compare_setup.html",
        form=form,
        record=record,
        text=text,
        url=url,
    )


@admin.route("/do_match_compare/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_match_compare(id1, id2):
    record1 = MatchingAttempt.query.get_or_404(id1)
    record2 = MatchingAttempt.query.get_or_404(id2)

    pclass_filter = request.args.get("pclass_filter")
    diff_filter = request.args.get("diff_filter")
    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if url is None:
        url = redirect_url()

    if not validate_match_inspector(record1) or not validate_match_inspector(record2):
        return redirect(url)

    if not record1.finished:
        if record1.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting manual upload.'.format(name=record1.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(name=record1.name),
                "error",
            )
        return redirect(url)

    if not record1.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record1.name),
            "error",
        )
        return redirect(url)

    if not record2.finished:
        if record2.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting manual upload.'.format(name=record2.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(name=record2.name),
                "error",
            )
        return redirect(url)

    if not record2.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record2.name),
            "error",
        )
        return redirect(url)

    pclasses1 = record1.available_pclasses
    pclasses2 = record2.available_pclasses

    pclass_dict = {}

    for pclass in pclasses1:
        pclass: ProjectClass
        if pclass.id not in pclass_dict:
            pclass_dict[pclass.id] = pclass

    for pclass in pclasses2:
        pclass: ProjectClass
        if pclass.id not in pclass_dict:
            pclass_dict[pclass.id] = pclass

    pclass_values: Iterable[ProjectClass] = pclass_dict.values()
    pclass_values_ids: List[int] = [p.id for p in pclass_values]

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        if pclass_value not in pclass_values_ids:
            pclass_filter = "all"
    else:
        if pclass_filter is not None and pclass_filter not in ["all"]:
            pclass_filter = "all"

    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    # if no difference filter supplied, check if one is stored in ession
    if diff_filter is None and session.get("admin_match_diff_filter"):
        diff_filter = session["admin_match_diff_filter"]

    if diff_filter is not None and diff_filter not in [
        "all",
        "project",
        "supervisor",
        "marker",
    ]:
        diff_filter = "all"

    if diff_filter is not None:
        session["admin_match_diff_filter"] = diff_filter

    return render_template_context(
        "admin/match_inspector/compare.html",
        record1=record1,
        record2=record2,
        text=text,
        url=url,
        pclasses=pclass_dict.values(),
        pclass_filter=pclass_filter,
        diff_filter=diff_filter,
    )


@admin.route("/do_match_compare_ajax/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_match_compare_ajax(id1, id2):
    attempt1: MatchingAttempt = MatchingAttempt.query.get_or_404(id1)
    attempt2: MatchingAttempt = MatchingAttempt.query.get_or_404(id2)

    if not validate_match_inspector(attempt1) or not validate_match_inspector(attempt2):
        return jsonify({})

    if not attempt1.finished:
        if attempt1.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting upload of an offline solution.'.format(name=attempt1.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(name=attempt1.name),
                "error",
            )
        return jsonify({})

    if attempt1.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=attempt1.name),
            "error",
        )
        return jsonify({})

    if not attempt2.finished:
        if attempt2.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting upload of an offline solution.'.format(name=attempt2.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(name=attempt2.name),
                "error",
            )
        return jsonify({})

    if not attempt2.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=attempt2.name),
            "error",
        )
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    flag, pclass_value = is_integer(pclass_filter)

    diff_filter = request.args.get("diff_filter")

    discrepant_records = _build_match_changes(attempt1, attempt2, diff_filter, flag, pclass_value)
    return ajax.admin.compare_match_data(discrepant_records, attempt1, attempt2)


def _build_match_changes(
    attempt1: MatchingAttempt,
    attempt2: MatchingAttempt,
    diff_filter: str,
    filter_pclasses: bool,
    pclass_id_value: int,
    include_only_common_records: bool = False,
):
    # perform a symmetric comparison between the MatchingRecord instances
    # first, we need to build a dictionary of the MatchingRecord instances in each MatchingAttempt, so that we can
    # quickly perform lookups
    # dictionary is indexed by a pair of selector_id, submission_period
    RecordIndexType = Tuple[int, int]
    RecordDictType = Dict[RecordIndexType, MatchingRecord]

    def build_record_dict(attempt: MatchingAttempt) -> RecordDictType:
        # query supplied MatchingAttempt for an ordered list of records, restricting by project class if required
        if filter_pclasses:
            query = (
                attempt.records.join(SelectingStudent, SelectingStudent.id == MatchingRecord.selector_id)
                .join(
                    ProjectClassConfig,
                    ProjectClassConfig.id == SelectingStudent.config_id,
                )
                .filter(ProjectClassConfig.pclass_id == pclass_id_value)
            )
        else:
            query = attempt.records
        recs: List[MatchingRecord] = query.order_by(MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc())

        # convert to a dictionary, indexed by
        rec_dict: RecordDictType = {(rec.selector_id, rec.submission_period): rec for rec in recs}

        return rec_dict

    recs1 = build_record_dict(attempt1)
    recs2 = build_record_dict(attempt2)

    # obtain set of keys for each group of records
    keys1 = recs1.keys()
    keys2 = recs2.keys()

    # find records that are common to both MatchingAttempt instances
    common_keys = keys1 & keys2

    # find records that are only in attempt1 or attempt1
    attempt1_only_keys = keys1 - common_keys
    attempt2_only_keys = keys2 - common_keys

    # discrepant_records will hold the records that differ
    discrepant_records = []

    # iterate over common_keys and check for differences between the MatchingRecord cases
    for key in common_keys:
        key: RecordIndexType
        rec1: MatchingRecord = recs1[key]
        rec2: MatchingRecord = recs2[key]

        if rec1.selector_id != rec2.selector_id:
            raise RuntimeError("do_match_compare_ajax: rec1.selector_id and rec2.selector_id do not match")

        if rec1.submission_period != rec2.submission_period:
            raise RuntimeError("do_match_compare_ajax: rec1.submission_period and rec2.submission_period do not match")

        # dictionary is indexed by user_id
        RoleDictType = Dict[int, MatchingRole]

        def get_role_dict(rec: MatchingRecord, roles: Union[int, List[int]]) -> RoleDictType:
            if not isinstance(roles, list):
                roles = [roles]

            role_records: List[MatchingRole] = rec.roles.filter(MatchingRole.role.in_(roles))
            role_dict: RoleDictType = {role.user_id: role for role in role_records}

            return role_dict

        def get_supervisor_roles(rec: MatchingRecord) -> RoleDictType:
            return get_role_dict(
                rec,
                [
                    MatchingRole.ROLE_SUPERVISOR,
                    MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                ],
            )

        def get_marker_roles(rec: MatchingRecord) -> RoleDictType:
            return get_role_dict(rec, MatchingRole.ROLE_MARKER)

        def find_record_changes(rec1: MatchingRecord, rec2: MatchingRecord, diff_filter: str) -> List[str]:
            # is the project assignment different?
            changes = []

            if diff_filter == "all" or diff_filter == "project":
                if rec1.project_id != rec2.project_id:
                    changes.append("project")

            # check for differing supervisor roles
            if diff_filter == "all" or diff_filter == "supervisor":
                supervisors1: RoleDictType = get_supervisor_roles(rec1)
                supervisors2: RoleDictType = get_supervisor_roles(rec2)
                supervisors_diff = supervisors1.keys() ^ supervisors2.keys()
                if len(supervisors_diff) > 0:
                    changes.append("supervisor")

            # check for differing marker roles
            if diff_filter == "all" or diff_filter == "marker":
                markers1: RoleDictType = get_marker_roles(rec1)
                markers2: RoleDictType = get_marker_roles(rec2)
                markers_diff = markers1.keys() ^ markers2.keys()
                if len(markers_diff) > 0:
                    changes.append("marker")

            return changes

        # test whether there is a disagreement between records
        changes: List[str] = find_record_changes(rec1, rec2, diff_filter)

        # if so, add this record pair to the discrepant pile
        if len(changes) > 0:
            discrepant_records.append((rec1, rec2, changes))

    if not include_only_common_records:
        # iterate over keys that are only in one match or the other
        for key in attempt1_only_keys:
            key: RecordIndexType
            rec: MatchingRecord = recs1[key]

            discrepant_records.append((rec, None, ["all"]))
        for key in attempt2_only_keys:
            key: RecordIndexType
            rec: MatchingRecord = recs2[key]

            discrepant_records.append((None, rec, ["all"]))

    return discrepant_records


@admin.route("/replace_matching_record/<int:src_id>/<int:dest_id>")
@roles_accepted("faculty", "admin", "root")
def replace_matching_record(src_id, dest_id):
    source: MatchingRecord = MatchingRecord.query.get_or_404(src_id)
    dest: MatchingRecord = MatchingRecord.query.get_or_404(dest_id)

    if not validate_match_inspector(source.matching_attempt) or not validate_match_inspector(dest.matching_attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if dest.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    if source.selector_id != dest.selector_id:
        flash(
            "Cannot merge these matching records because they do not refer to the same selector",
            "error",
        )
        return redirect(redirect_url())

    if source.submission_period != dest.submission_period:
        flash(
            "Cannot merge these matching records because they do not refer to the same submission period",
            "error",
        )
        return redirect(redirect_url())

    try:
        # overwrite destination project assignment
        dest.project_id = source.project_id

        # overwrite alternative data
        dest.alternative = source.alternative
        dest.parent_id = source.parent_id
        dest.priority = source.priority

        # overwrite rank
        dest.rank = source.rank

        # deep copy role assignments
        dest.roles = []
        for old_role in source.roles:
            old_role: MatchingRole

            new_role = MatchingRole(
                user_id=old_role.user_id,
                role=old_role.role,
            )
            dest.roles.append(new_role)

        dest.mark_edited(current_user)

        log_db_commit("Replace matching record project assignment and role assignments from source record", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Can not replace matching record due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/insert_matching_record/<int:src_id>/<int:attempt_id>")
@roles_accepted("faculty", "admin", "root")
def insert_matching_record(src_id, attempt_id):
    source_record: MatchingRecord = MatchingRecord.query.get_or_404(src_id)
    dest_attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(source_record.matching_attempt) or not validate_match_inspector(dest_attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if dest_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle',
            "info",
        )
        return redirect(redirect_url())

    sel: SelectingStudent = source_record.selector
    if sel.config not in dest_attempt.config_members:
        flash(
            f'Cannot insert this matching record into attempt "{dest_attempt.name}" because it does not contain matches for projects of type "{sel.config.name}"',
            "error",
        )
        return redirect(redirect_url())

    try:
        # insert new MatchingRecord instance
        new_record = MatchingRecord(
            matching_id=dest_attempt.id,
            selector_id=source_record.selector_id,
            submission_period=source_record.submission_period,
            project_id=source_record.project_id,
            original_project_id=source_record.project_id,
            rank=source_record.rank,
            alternative=source_record.alternative,
            parent_id=source_record.parent_id,
            priority=source_record.priority,
            original_alternative=source_record.alternative,
            original_parent_id=source_record.parent_id,
            original_priority=source_record.priority,
        )
        db.session.add(new_record)
        db.session.flush()

        # deep copy role assignments
        new_record.roles = []
        new_record.original_roles = []
        for old_role in source_record.roles:
            old_role: MatchingRole

            new_role = MatchingRole(
                user_id=old_role.user_id,
                role=old_role.role,
            )
            new_record.roles.append(new_role)

            new_original_role = MatchingRole(
                user_id=old_role.user_id,
                role=old_role.role,
            )
            new_record.original_roles.append(new_original_role)

        dest_attempt.last_edit_id = current_user.id
        dest_attempt.last_edit_timestamp = datetime.now()

        log_db_commit("Insert new matching record copied from source into destination matching attempt", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Can not insert matching record due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/match_export_excel/<int:matching_id>")
@roles_accepted("faculty", "admin", "root")
def match_export_excel(matching_id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(matching_id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for export because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for export because it has not yet completed.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for export because it did not yield a useable solution'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    task_id = register_task(
        f'Export matching attempt "{record.name}" to Excel',
        owner=current_user,
        description=f'Export matching attempt "{record.name}" to Excel and send by email',
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.matching.generate_excel_matching_report"]

    task.apply_async(args=(matching_id, current_user.id, task_id), task_id=task_id)
    flash(f'An Excel report for "{record.name}" is being generated, and you will be notified when it is available.')

    return redirect(redirect_url())


@admin.route("/match_student_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_student_view(id):
    # legacy entry point — the student inspector now lives in the Matching Workspace
    # (see .prompts/matching-workspace/PLAN.md, decision 2: "parallel v2, switch entry points")
    return redirect(url_for("admin.matching_workspace", id=id, view="student", **request.args.to_dict()))


@admin.route("/match_faculty_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_faculty_view(id):
    # legacy entry point — the faculty inspector now lives in the Matching Workspace
    # (see .prompts/matching-workspace/PLAN.md, decision 2: "parallel v2, switch entry points")
    return redirect(url_for("admin.matching_workspace", id=id, view="faculty", **request.args.to_dict()))


@admin.route("/match_dists_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_dists_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for inspection because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for inspection because it did not yield an optimal solution.'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter")

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]

    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    flag, pclass_value = is_integer(pclass_filter)

    pclasses = get_automatch_pclasses()

    fsum = lambda x: x[0] + x[1]
    query = record.faculty_list_query()
    CATS_tot = [fsum(record.get_faculty_CATS(f.id, pclass_value if flag else None)) for f in query.all()]

    CATS_plot = figure(title="Workload distribution", x_axis_label="CATS", width=800, height=300)
    CATS_hist, CATS_edges = histogram(CATS_tot, bins="auto")
    CATS_plot.quad(
        top=CATS_hist,
        bottom=0,
        left=CATS_edges[:-1],
        right=CATS_edges[1:],
        fill_color="#036564",
        line_color="#033649",
    )
    CATS_plot.sizing_mode = "scale_width"
    CATS_plot.toolbar.logo = None
    CATS_plot.border_fill_color = None
    CATS_plot.background_fill_color = "lightgrey"

    CATS_script, CATS_div = components(CATS_plot)

    selectors = record.selector_list_query().all()

    def _get_deltas(s: SelectingStudent):
        if flag:
            if s.config.pclass_id != pclass_value:
                return None

        records: List[MatchingRecord] = s.matching_records.filter(MatchingRecord.matching_id == record.id).all()

        deltas = [r.delta for r in records]
        return sum(deltas) if None not in deltas else None

    delta_set = [_get_deltas(s) for s in selectors]
    delta_set = [x for x in delta_set if x is not None]

    delta_plot = figure(title="Delta distribution", x_axis_label="Total delta", width=800, height=300)
    delta_hist, delta_edges = histogram(delta_set, bins="auto")
    delta_plot.quad(
        top=delta_hist,
        bottom=0,
        left=delta_edges[:-1],
        right=delta_edges[1:],
        fill_color="#036564",
        line_color="#033649",
    )
    delta_plot.sizing_mode = "scale_width"
    delta_plot.toolbar.logo = None
    delta_plot.border_fill_color = None
    delta_plot.background_fill_color = "lightgrey"

    delta_script, delta_div = components(delta_plot)

    return render_template_context(
        "admin/match_inspector/dists.html",
        pane="dists",
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        CATS_script=CATS_script,
        CATS_div=CATS_div,
        delta_script=delta_script,
        delta_div=delta_div,
        text=text,
        url=url,
    )


@admin.route("/matching_workspace/<int:id>")
@roles_accepted("faculty", "admin", "root")
def matching_workspace(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for inspection because it has not yet completed.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for inspection because it did not yield a useable solution'.format(name=record.name),
            "error",
        )
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    view = request.args.get("view", "student")
    if view not in ("student", "faculty", "changes"):
        view = "student"

    pclass_filter = request.args.get("pclass_filter", default=None)
    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        if current_user.has_role("root") or current_user.has_role("admin"):
            url = url_for("admin.matching_dashboard", year=record.year)
        else:
            convened = next((pc for pc in record.available_pclasses if pc.is_convenor(current_user.id)), None)
            url = url_for("admin.matching_dashboard", pclass_id=convened.id) if convened is not None else url_for("admin.matching_dashboard")
        text = "matches list"

    # filters are session-persisted, exactly as for the legacy student/faculty inspectors
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]
    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    if type_filter is None and session.get("admin_match_type_filter"):
        type_filter = session["admin_match_type_filter"]
    if type_filter not in ["all", "ordinary", "generic"]:
        type_filter = "all"
    if type_filter is not None:
        session["admin_match_type_filter"] = type_filter

    if hint_filter is None and session.get("admin_match_hint_filter"):
        hint_filter = session["admin_match_hint_filter"]
    if hint_filter not in ["all", "satisfied", "violated"]:
        hint_filter = "all"
    if hint_filter is not None:
        session["admin_match_hint_filter"] = hint_filter

    pclasses = record.available_pclasses

    changes = workspace_service.changes_data(record)

    student_ctx = {}
    if view == "student":
        group_by = request.args.get("group_by", default=None)
        if group_by is None and session.get("admin_match_group_by"):
            group_by = session["admin_match_group_by"]
        if group_by not in ("student", "period"):
            group_by = "student"
        session["admin_match_group_by"] = group_by

        name_filter = request.args.get("name_filter", "").strip()

        page = request.args.get("page", 1, type=int)
        _ALLOWED_PER_PAGE = {5, 10, 15, 20}
        per_page_raw = request.args.get("per_page", 10, type=int)
        per_page = per_page_raw if per_page_raw in _ALLOWED_PER_PAGE else 10

        pclass_flag, pclass_value = is_integer(pclass_filter)

        filter_list = []
        if pclass_flag:
            filter_list.append(lambda row: row.selector.config.pclass_id == pclass_value)
        if type_filter == "ordinary":
            filter_list.append(lambda row: row.project is not None and not row.project.use_supervisor_pool)
        elif type_filter == "generic":
            filter_list.append(lambda row: row.project is not None and row.project.use_supervisor_pool)
        if hint_filter == "satisfied":
            filter_list.append(lambda row: row.hint_status is not None and len(row.hint_status[0]) > 0)
        elif hint_filter == "violated":
            filter_list.append(lambda row: row.hint_status is not None and len(row.hint_status[1]) > 0)
        if name_filter:
            name_lower = name_filter.lower()
            filter_list.append(lambda row: name_lower in row.selector.student.user.name.lower())

        matching_records = [
            r
            for r in record.records.order_by(MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc()).all()
            if all(f(r) for f in filter_list)
        ]

        all_groups = workspace_service.build_student_groups(record, matching_records, group_by)
        total_groups = len(all_groups)
        page_start = (page - 1) * per_page
        groups = all_groups[page_start : page_start + per_page]

        student_ctx = dict(
            groups=groups,
            group_by=group_by,
            name_filter=name_filter,
            page=page,
            per_page=per_page,
            total_groups=total_groups,
        )

    return render_template_context(
        "admin/matching_workspace/workspace.html",
        view=view,
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        type_filter=type_filter,
        hint_filter=hint_filter,
        changes=changes,
        changes_badge=len(changes["rows"]),
        unresolved_comments=workspace_service.unresolved_comment_count(record),
        new_comments=workspace_service.new_comment_count(record, current_user),
        text=text,
        url=url,
        **student_ctx,
    )


@admin.route("/match_student_drawer_ajax/<int:rec_id>")
@roles_accepted("faculty", "admin", "root")
def match_student_drawer_ajax(rec_id):
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)

    if not validate_match_inspector(record.matching_attempt):
        return jsonify({}), 403

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    drawer = workspace_service.student_drawer(record.matching_attempt, record)

    return render_template_context(
        "admin/matching_workspace/_student_drawer.html",
        drawer=drawer,
        hint_form=ConfirmActionForm(),
        text=text,
        url=url,
    )


@admin.route("/match_role_editor_ajax/<int:rec_id>")
@roles_accepted("faculty", "admin", "root")
def match_role_editor_ajax(rec_id):
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)

    if not validate_match_inspector(record.matching_attempt):
        return jsonify({}), 403

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # optional project override: the modal JS reloads this fragment with ?project_id= when the
    # user changes the project selection, so the scoped supervisor/marker choice lists track
    # the currently selected project rather than the stored assignment
    scope_project = None
    project_flag, project_value = is_integer(request.args.get("project_id", default=None))
    if project_flag:
        scope_project = db.session.get(LiveProject, project_value)

    form = EditMatchRolesFormFactory(record, scope_project=scope_project)()
    form.project.data = scope_project if scope_project is not None else record.project
    form.responsible_supervisors.data = sorted(record.responsible_supervisor_role_ids)
    form.supervisors.data = sorted(record.supervisor_only_role_ids)
    form.markers.data = sorted(record.marker_role_ids)

    return render_template_context(
        "admin/matching_workspace/_role_editor_modal.html",
        record=record,
        form=form,
        text=text,
        url=url,
    )


@admin.route("/edit_match_roles/<int:rec_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def edit_match_roles(rec_id):
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)
    attempt: MatchingAttempt = record.matching_attempt

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to edit this matching record."), 403

    if attempt.selected:
        return (
            jsonify(
                success=False,
                message='Match "{name}" cannot be edited because an administrative user has marked it as '
                '"selected" for use during rollover of the academic year.'.format(name=attempt.name),
            ),
            409,
        )

    year = get_current_year()
    if attempt.year != year:
        return (
            jsonify(
                success=False,
                message='Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=attempt.name),
            ),
            409,
        )

    # scope the supervisor/marker choice lists by the *submitted* project, so selections made
    # against a reloaded (project-changed) fragment validate against the same choice lists
    # they were rendered from
    scope_project = None
    project_flag, project_value = is_integer(request.form.get("project", default=None))
    if project_flag:
        scope_project = db.session.get(LiveProject, project_value)

    form = EditMatchRolesFormFactory(record, scope_project=scope_project)()

    if not form.validate_on_submit():
        return jsonify(success=False, errors=form.errors), 400

    new_project: LiveProject = form.project.data
    new_responsible_ids = set(form.responsible_supervisors.data)
    new_supervisor_ids = set(form.supervisors.data) - new_responsible_ids
    new_marker_ids = set(form.markers.data)

    record.project_id = new_project.id
    record.rank = record.selector.project_rank(new_project.id)
    record.alternative = False
    record.parent_id = None
    record.priority = None

    # reconcile existing roles: retype supervisor-family roles in place when a person moves
    # between the responsible/plain lists, and remove anyone no longer assigned
    for item in list(record.roles):
        item: MatchingRole
        if item.role in (MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR):
            if item.user_id in new_responsible_ids:
                item.role = MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR
            elif item.user_id in new_supervisor_ids:
                item.role = MatchingRole.ROLE_SUPERVISOR
            else:
                record.roles.remove(item)
        elif item.role == MatchingRole.ROLE_MARKER and item.user_id not in new_marker_ids:
            record.roles.remove(item)
    db.session.flush()

    existing_responsible_ids = {item.user_id for item in record.roles if item.role == MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR}
    for fd_id in new_responsible_ids - existing_responsible_ids:
        record.roles.add(MatchingRole(role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR, user_id=fd_id))

    existing_supervisor_ids = {item.user_id for item in record.roles if item.role == MatchingRole.ROLE_SUPERVISOR}
    for fd_id in new_supervisor_ids - existing_supervisor_ids:
        record.roles.add(MatchingRole(role=MatchingRole.ROLE_SUPERVISOR, user_id=fd_id))

    existing_marker_ids = {item.user_id for item in record.roles if item.role == MatchingRole.ROLE_MARKER}
    for fd_id in new_marker_ids - existing_marker_ids:
        record.roles.add(MatchingRole(role=MatchingRole.ROLE_MARKER, user_id=fd_id))

    record.mark_edited(current_user)

    try:
        log_db_commit("Edit roles for matching record", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify(success=False, message="Could not save role changes because a database error was encountered."), 500

    return jsonify(success=True)


@admin.route("/match_faculty_view_v2_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def match_faculty_view_v2_ajax(id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(attempt):
        return jsonify({})

    if not attempt.finished or not attempt.solution_usable:
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter", default=None)
    pclass_flag, pclass_value = is_integer(pclass_filter)

    url = request.args.get("url", default=None)
    text = request.args.get("text", default=None)

    base_query = attempt.faculty_list_query()

    def search_name(row: FacultyData):
        return row.user.name

    def sort_name(row: FacultyData):
        user: User = row.user
        return [user.last_name, user.first_name]

    def sort_workload(row: FacultyData):
        sup_info = attempt.is_supervisor_overassigned(row)
        mark_info = attempt.is_marker_overassigned(row)
        return sup_info["CATS_total"] + mark_info["CATS_total"]

    name = {"search": search_name, "order": sort_name}
    workload = {"order": sort_workload}
    columns = {
        "name": name,
        "supervising": {},
        "marking": {},
        "workload": workload,
    }

    row_filter = None
    if pclass_flag:

        def row_filter(row: FacultyData):
            sup_records = attempt.get_supervisor_records(row.id).all()
            if any(r.selector.config.pclass_id == pclass_value for r in sup_records):
                return True

            mark_records = attempt.get_marker_records(row.id).all()
            return any(r.selector.config.pclass_id == pclass_value for r in mark_records)

    with ServerSideInMemoryHandler(
        request,
        base_query,
        columns,
        row_filter=row_filter,
    ) as handler:

        def row_formatter(records: List[FacultyData]):
            rows = [workspace_service.faculty_row(attempt, fac) for fac in records]
            return ajax.admin.faculty_view_v2_data(rows, attempt, text=text, url=url)

        return handler.build_payload(row_formatter)


@admin.route("/match_faculty_drawer_ajax/<int:attempt_id>/<int:fac_id>")
@roles_accepted("faculty", "admin", "root")
def match_faculty_drawer_ajax(attempt_id, fac_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)
    fac: FacultyData = FacultyData.query.get_or_404(fac_id)

    if not validate_match_inspector(attempt):
        return jsonify({}), 403

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    drawer = workspace_service.faculty_drawer(attempt, fac)

    return render_template_context(
        "admin/matching_workspace/_faculty_drawer.html",
        attempt=attempt,
        drawer=drawer,
        text=text,
        url=url,
    )


@admin.route("/faculty_reassign_ajax/<int:attempt_id>/<int:fac_id>")
@roles_accepted("faculty", "admin", "root")
def faculty_reassign_ajax(attempt_id, fac_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)
    fac: FacultyData = FacultyData.query.get_or_404(fac_id)

    if not validate_match_inspector(attempt):
        return jsonify({}), 403

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    drawer = workspace_service.faculty_drawer(attempt, fac)

    return render_template_context(
        "admin/matching_workspace/_faculty_reassign_modal.html",
        attempt_id=attempt.id,
        drawer=drawer,
        form=ConfirmActionForm(),
        text=text,
        url=url,
    )


@admin.route(
    "/faculty_reassign_assign/<int:attempt_id>/<int:fac_id>/<int:selector_id>/<int:project_id>",
    methods=["POST"],
)
@roles_accepted("faculty", "admin", "root")
def faculty_reassign_assign(attempt_id, fac_id, selector_id, project_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)
    fac: FacultyData = FacultyData.query.get_or_404(fac_id)

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to edit this matching attempt."), 403

    form = ConfirmActionForm()
    if not form.validate_on_submit():
        return jsonify(success=False, message="Could not validate this request; please reload the page and try again."), 400

    if attempt.selected:
        return (
            jsonify(
                success=False,
                message='Match "{name}" cannot be edited because an administrative user has marked it as '
                '"selected" for use during rollover of the academic year.'.format(name=attempt.name),
            ),
            409,
        )

    year = get_current_year()
    if attempt.year != year:
        return (
            jsonify(
                success=False,
                message='Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=attempt.name),
            ),
            409,
        )

    record: MatchingRecord = attempt.records.filter_by(selector_id=selector_id).first()
    if record is None:
        return jsonify(success=False, message="No matching record was found for this selector in this attempt."), 404

    project: LiveProject = LiveProject.query.get_or_404(project_id)

    if project.id not in workspace_service.faculty_project_ids(attempt, fac):
        return jsonify(success=False, message="This project is not offered by the selected faculty member in this matching attempt."), 400

    success, message = _apply_project_reassignment(record, project)
    if not success:
        return jsonify(success=False, message=message or "Could not reassign this student."), 400

    return jsonify(success=True)


def _comment_badge_counts(attempt: MatchingAttempt) -> dict:
    """
    Counts driving the workspace shell's Review-comments button, returned by every comment
    mutation so the client can repaint the badges without a page reload.
    """
    return {
        "unresolved_count": workspace_service.unresolved_comment_count(attempt),
        "new_count": workspace_service.new_comment_count(attempt, current_user),
    }


@admin.route("/match_comments_ajax/<int:attempt_id>")
@roles_accepted("faculty", "admin", "root")
def match_comments_ajax(attempt_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(attempt):
        return jsonify({}), 403

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    state = request.args.get("state", workspace_service.DEFAULT_COMMENT_STATE)

    # scope the By-student tab to one assignment, but only if that record really belongs to this
    # attempt — the record id arrives from the client
    record_id = request.args.get("record_id", None, type=int)
    record: Optional[MatchingRecord] = MatchingRecord.query.get(record_id) if record_id is not None else None
    if record is None or record.matching_id != attempt.id:
        record_id = None
        record = None

    # which tab the client was last on, so a re-fetch after a mutation does not bounce the user
    # back to Global; a scoped panel always lands on the By-student tab
    active_tab = request.args.get("tab", "global")
    if active_tab not in ("global", "student"):
        active_tab = "global"

    data = workspace_service.comments_data(attempt, state=state, record=record if record_id is not None else None, user=current_user)

    return render_template_context(
        "admin/matching_workspace/_comments_panel.html",
        attempt=attempt,
        data=data,
        active_tab=active_tab,
        scoped_record_id=record_id,
        comment_form=MatchCommentFormFactory(attempt)(),
        reply_form=MatchCommentReplyForm(),
        resolve_form=ConfirmActionForm(),
        text=text,
        url=url,
    )


@admin.route("/post_match_comment/<int:attempt_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def post_match_comment(attempt_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to comment on this matching attempt."), 403

    form = MatchCommentFormFactory(attempt)()
    if not form.validate_on_submit():
        return jsonify(success=False, errors=form.errors), 400

    record = form.matching_record.data if form.scope.data == "assignment" else None

    comment = MatchingReviewComment(
        matching_attempt_id=attempt.id,
        matching_record_id=record.id if record is not None else None,
        owner_id=current_user.id,
        body=form.body.data,
        creation_timestamp=datetime.now(),
    )
    db.session.add(comment)

    try:
        log_db_commit("Post matching review comment", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify(success=False, message="Could not post this comment because a database error was encountered."), 500

    return jsonify(success=True, **_comment_badge_counts(attempt))


@admin.route("/reply_match_comment/<int:comment_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def reply_match_comment(comment_id):
    parent: MatchingReviewComment = MatchingReviewComment.query.get_or_404(comment_id)
    attempt: MatchingAttempt = parent.matching_attempt

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to comment on this matching attempt."), 403

    if parent.parent_id is not None:
        return jsonify(success=False, message="Replies can only be one level deep."), 400

    form = MatchCommentReplyForm()
    if not form.validate_on_submit():
        return jsonify(success=False, errors=form.errors), 400

    now = datetime.now()

    reply = MatchingReviewComment(
        matching_attempt_id=attempt.id,
        matching_record_id=parent.matching_record_id,
        parent_id=parent.id,
        owner_id=current_user.id,
        body=form.body.data,
        creation_timestamp=now,
    )
    db.session.add(reply)

    # "Reply and resolve" and "Reopen and reply" both land here: the reply and the thread's state
    # change are one action, so they commit together. Each transition is a no-op if the thread is
    # already in the requested state, rather than an error.
    transition = form.transition.data
    if transition == "resolve" and not parent.resolved:
        parent.resolved = True
        parent.resolved_by_id = current_user.id
        parent.resolved_timestamp = now
    elif transition == "reopen" and parent.resolved:
        parent.resolved = False
        parent.resolved_by_id = None
        parent.resolved_timestamp = None

    try:
        log_db_commit("Reply to matching review comment", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify(success=False, message="Could not post this reply because a database error was encountered."), 500

    return jsonify(success=True, resolved=parent.resolved, **_comment_badge_counts(attempt))


@admin.route("/resolve_match_comment/<int:comment_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def resolve_match_comment(comment_id):
    comment: MatchingReviewComment = MatchingReviewComment.query.get_or_404(comment_id)
    attempt: MatchingAttempt = comment.matching_attempt

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to update this comment."), 403

    form = ConfirmActionForm()
    if not form.validate_on_submit():
        return jsonify(success=False, message="Could not validate this request; please reload the page and try again."), 400

    comment.resolved = not comment.resolved
    if comment.resolved:
        comment.resolved_by_id = current_user.id
        comment.resolved_timestamp = datetime.now()
    else:
        comment.resolved_by_id = None
        comment.resolved_timestamp = None

    try:
        log_db_commit("Toggle resolved state of matching review comment", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify(success=False, message="Could not update this comment because a database error was encountered."), 500

    return jsonify(success=True, resolved=comment.resolved, **_comment_badge_counts(attempt))


@admin.route("/mark_match_comments_read/<int:attempt_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def mark_match_comments_read(attempt_id):
    """
    Stamp the current user's read marker for this attempt's review comments. Fired by the client
    *after* the panel body has been delivered, so the marker used to compute the "new" flags is
    the previous one and those flags stay visible on the view that clears them.
    """
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to view this matching attempt."), 403

    form = ConfirmActionForm()
    if not form.validate_on_submit():
        return jsonify(success=False, message="Could not validate this request; please reload the page and try again."), 400

    marker: MatchingCommentReadMarker = MatchingCommentReadMarker.query.filter_by(user_id=current_user.id, matching_attempt_id=attempt.id).first()
    if marker is None:
        marker = MatchingCommentReadMarker(user_id=current_user.id, matching_attempt_id=attempt.id)
        db.session.add(marker)

    marker.last_read_timestamp = datetime.now()

    # deliberately not log_db_commit(): a read receipt is routine per-view bookkeeping, not a
    # workflow event worth an audit entry
    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify(success=False, message="Could not record that these comments have been read."), 500

    return jsonify(success=True, unresolved_count=workspace_service.unresolved_comment_count(attempt), new_count=0)


@admin.route("/delete_match_record/<int:attempt_id>/<int:selector_id>")
@roles_accepted("faculty", "admin", "root")
def delete_match_record(attempt_id, selector_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    if attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=attempt.name),
            "info",
        )
        return redirect(redirect_url())

    try:
        # remove all matching records associated with this selector
        records = db.session.query(MatchingRecord).filter_by(matching_id=attempt.id, selector_id=selector_id)
        for record in records:
            records: MatchingRecord
            db.session.delete(record)

        log_db_commit("Delete all matching records for selector from matching attempt", user=current_user)

    except SQLAlchemyError as e:
        flash(
            "Could not delete matching records for this selector because a database error was encountered.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


def _apply_project_reassignment(record: MatchingRecord, project: LiveProject) -> Tuple[bool, Optional[str]]:
    """
    Core mutation shared by `reassign_match_project` and `faculty_reassign_assign`: reassign
    `record`'s matched project to `project`, adjusting supervisor roles to match, subject to the
    same validation (`project` must be one of the selector's submitted choices; a non-pooled
    project's owner must still be enrolled as supervisor). Returns (success, error_message);
    `error_message` is None both on success and on the pre-existing silent no-op cases (selector
    has not submitted / project has no owner) inherited from the original `reassign_match_project`
    behaviour.
    """
    if not record.selector.has_submitted:
        return False, None

    submitted_data = record.selector.is_project_submitted(project)
    if not submitted_data.get("submitted"):
        return False, "Could not reassign '{proj}' to {name} because this project was not included in this selector's choices".format(
            proj=project.name, name=record.selector.student.user.name
        )

    if not project.use_supervisor_pool:
        if project.owner is None:
            return False, None

        enroll_record = project.owner.get_enrollment_record(project.config.pclass_id)
        if enroll_record is None or enroll_record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
            return False, (
                "Could not reassign '{proj}' to {name} because this project's supervisor is no longer enrolled for this project class.".format(
                    proj=project.name, name=record.selector.student.user.name
                )
            )

        # remove any previous supervision roles and replace with a supervision role for the new project
        existing_supv = record.roles.filter(MatchingRole.role.in_([MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR])).all()
        for item in existing_supv:
            record.roles.remove(item)

        new_supv = MatchingRole(user_id=project.owner_id, role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR)
        record.roles.add(new_supv)

    record.project_id = project.id
    record.rank = record.selector.project_rank(project.id)
    record.alternative = False
    record.parent_id = None
    record.priority = None

    record.mark_edited(current_user)

    try:
        log_db_commit("Reassign matched project for selector in matching attempt", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return False, "Could not reassign matched project because a database error was encountered."

    return True, None


@admin.route("/match_set_hint/<int:rec_id>/<int:sel_id>/<int:hint>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def match_set_hint(rec_id, sel_id, hint):
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)
    attempt: MatchingAttempt = record.matching_attempt

    if not validate_match_inspector(attempt):
        return jsonify(success=False, message="You do not have permission to edit this matching attempt."), 403

    form = ConfirmActionForm()
    if not form.validate_on_submit():
        return jsonify(success=False, message="Could not validate this request; please reload the page and try again."), 400

    if attempt.selected:
        return (
            jsonify(
                success=False,
                message='Match "{name}" cannot be edited because an administrative user has marked it as '
                '"selected" for use during rollover of the academic year.'.format(name=attempt.name),
            ),
            409,
        )

    year = get_current_year()
    if attempt.year != year:
        return (
            jsonify(
                success=False,
                message='Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=attempt.name),
            ),
            409,
        )

    selection: SelectionRecord = SelectionRecord.query.get_or_404(sel_id)
    if selection.owner_id != record.selector_id:
        return jsonify(success=False, message="This selection does not belong to the student for this matching record."), 400

    if hint < SelectionRecord.SELECTION_HINT_NEUTRAL or hint > SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG:
        return jsonify(success=False, message="Unknown selection hint."), 400

    # NB: hints feed the optimiser input; changing one here does not re-run matching. This only
    # records the convenor's intent against the student's ranked selection.
    try:
        selection.set_hint(hint)
        log_db_commit(
            "Set selection hint for {student} on project {proj} from the matching workspace".format(
                student=record.selector.student.user.name, proj=selection.liveproject.name
            ),
            user=current_user,
            student=record.selector.student,
            project_classes=record.selector.config.project_class,
        )
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False, message="Could not set the selection hint due to a database error."), 500

    return jsonify(success=True, hint_label=SelectionRecord._menu_items.get(selection.hint))


@admin.route("/reassign_match_project/<int:id>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def reassign_match_project(id, pid):
    record: MatchingRecord = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    project: LiveProject = LiveProject.query.get_or_404(pid)

    success, message = _apply_project_reassignment(record, project)
    if not success and message:
        flash(message, "error")

    return redirect(redirect_url())


@admin.route("/reassign_match_marker/<int:id>/<int:mid>")
@roles_accepted("faculty", "admin", "root")
def reassign_match_marker(id, mid):
    record: MatchingRecord = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    # check intended mid is in list of attached second markers
    count = get_count(record.project.assessor_list_query.filter(FacultyData.id == mid))

    if count == 0:
        marker = FacultyData.query.get_or_404(mid)
        flash(
            'Could not assign {name} as marker since not tagged as available for assigned project "{proj}"'.format(
                name=marker.user.name, proj=record.project.name
            ),
            "error",
        )

    elif count == 1:
        # old_mid identifies the specific marker role being replaced (for multi-marker records);
        # if absent, all existing ROLE_MARKER roles are replaced
        old_mid = request.args.get("old_mid", None, type=int)

        if old_mid is not None:
            to_remove = record.roles.filter(
                MatchingRole.user_id == old_mid,
                MatchingRole.role == MatchingRole.ROLE_MARKER,
            ).all()
        else:
            to_remove = record.roles.filter(
                MatchingRole.role == MatchingRole.ROLE_MARKER,
            ).all()

        for role in to_remove:
            db.session.delete(role)
        db.session.flush()

        new_role = MatchingRole(user_id=mid, role=MatchingRole.ROLE_MARKER)
        record.roles.append(new_role)

        record.mark_edited(current_user)

        log_db_commit("Reassign marker for matching record", user=current_user)

    else:
        flash(
            "Inconsistent marker counts for matching record (id={id}). Please contact a system administrator".format(id=record.id),
            "error",
        )

    return redirect(redirect_url())


@admin.route("/reassign_supervisor_roles/<int:rec_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def reassign_supervisor_roles(rec_id):
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as "selected" for use during rollover of the academic year.'.format(
                name=record.matching_attempt.name
            ),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    assign_form: EditSupervisorRolesForm = EditSupervisorRolesForm(obj=record)

    if assign_form.validate_on_submit():
        new_supv_roles = assign_form.supervisors.data

        existing_roles = []

        for item in record.roles:
            item: MatchingRole

            if item.role in [
                MatchingRole.ROLE_SUPERVISOR,
                MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ]:
                if not any(fd.id == item.user_id for fd in new_supv_roles):
                    record.roles.remove(item)
                else:
                    existing_roles.append(item.user_id)

        for fd in new_supv_roles:
            if fd.id not in existing_roles:
                new_item = MatchingRole(role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR, user_id=fd.id)
                record.roles.add(new_item)

        record.mark_edited(current_user)

        try:
            log_db_commit("Reassign supervisor roles for matching record", user=current_user)
        except SQLAlchemyError as e:
            flash(
                "Could not reassign supervisors for this matching record because a database error was encountered.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    else:
        if request.method == "GET":
            supv_roles = [
                x.user.faculty_data
                for x in record.roles
                if x.role
                in [
                    MatchingRole.ROLE_SUPERVISOR,
                    MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                ]
            ]
            assign_form.supervisors.data = supv_roles

    return render_template_context(
        "admin/match_inspector/reassign_supervisor.html",
        form=assign_form,
        record=record,
        url=url,
        text=text,
    )


@admin.route("/publish_matching_selectors/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def publish_matching_selectors(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for email because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for email because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use. It cannot be shared by email.'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.published:
        flash(
            'Match "{name}" cannot be advertised to selectors because it has not yet been '
            "published to the module convenor. Please publish the match before attempting to distribute "
            "notifications.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    # derive tenant_id from the matching's config_members
    _tenant_id = None
    _first_config = record.config_members.first()
    if _first_config is not None and _first_config.project_class is not None:
        _tenant_id = _first_config.project_class.tenant_id

    # determine template type based on draft/final state
    _template_type = EmailTemplate.MATCHING_FINAL_NOTIFY_STUDENTS if record.selected else EmailTemplate.MATCHING_DRAFT_NOTIFY_STUDENTS

    url = request.args.get("url", redirect_url())

    form = ChooseEmailTemplateForm()
    form.template.query_factory = lambda: GetWorkflowTemplates(_template_type, tenant_id=_tenant_id)

    if form.validate_on_submit():
        template = form.template.data
        template_id = template.id if template is not None else None

        task_id = register_task(
            "Send matching to selectors",
            owner=current_user,
            description='Email details of match "{name}" to submitters'.format(name=record.name),
        )

        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.matching_emails.publish_to_selectors"]
        task.apply_async(args=(id, current_user.id, task_id), kwargs=dict(selector_template_id=template_id), task_id=task_id)

        return redirect(url)

    if not form.is_submitted():
        form.template.data = EmailTemplate.find_template_(_template_type, tenant=_tenant_id)

    return render_template_context(
        "shared/choose_email_template.html",
        title="Email matching results to selectors",
        action=url_for("admin.publish_matching_selectors", id=id, url=url),
        message=f'Select the email template to use when emailing matching results to selectors for "{record.name}".',
        template_fields=[{"heading": None, "field": form.template}],
        form=form,
        cancel_url=url,
    )


@admin.route("/publish_matching_supervisors/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def publish_matching_supervisors(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for email because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for email because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use. It cannot be shared by email.'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.published:
        flash(
            'Match "{name}" cannot be advertised to supervisors because it has not yet been '
            "published to the module convenor. Please publish the match before attempting to distribute "
            "notifications.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    # derive tenant_id from the matching's config_members
    _tenant_id = None
    _first_config = record.config_members.first()
    if _first_config is not None and _first_config.project_class is not None:
        _tenant_id = _first_config.project_class.tenant_id

    # determine template types based on draft/final state
    if record.selected:
        _notify_type = EmailTemplate.MATCHING_FINAL_NOTIFY_FACULTY
        _unneeded_type = EmailTemplate.MATCHING_FINAL_UNNEEDED_FACULTY
    else:
        _notify_type = EmailTemplate.MATCHING_DRAFT_NOTIFY_FACULTY
        _unneeded_type = EmailTemplate.MATCHING_DRAFT_UNNEEDED_FACULTY

    url = request.args.get("url", redirect_url())

    form = ChoosePairedEmailTemplatesForm()
    form.template_primary.query_factory = lambda: GetWorkflowTemplates(_notify_type, tenant_id=_tenant_id)
    form.template_secondary.query_factory = lambda: GetWorkflowTemplates(_unneeded_type, tenant_id=_tenant_id)

    if form.validate_on_submit():
        notify_template = form.template_primary.data
        unneeded_template = form.template_secondary.data
        notify_template_id = notify_template.id if notify_template is not None else None
        unneeded_template_id = unneeded_template.id if unneeded_template is not None else None

        task_id = register_task(
            "Send matching to supervisors",
            owner=current_user,
            description='Email details of match "{name}" to supervisors'.format(name=record.name),
        )

        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.matching_emails.publish_to_supervisors"]
        task.apply_async(
            args=(id, current_user.id, task_id),
            kwargs=dict(notify_template_id=notify_template_id, unneeded_template_id=unneeded_template_id),
            task_id=task_id,
        )

        return redirect(url)

    if not form.is_submitted():
        form.template_primary.data = EmailTemplate.find_template_(_notify_type, tenant=_tenant_id)
        form.template_secondary.data = EmailTemplate.find_template_(_unneeded_type, tenant=_tenant_id)

    return render_template_context(
        "shared/choose_email_template.html",
        title="Email matching results to supervisors",
        action=url_for("admin.publish_matching_supervisors", id=id, url=url),
        message=f'Select the email templates to use when emailing matching results to supervisors for "{record.name}".',
        template_fields=[
            {"heading": "Email to supervisors with assignments", "field": form.template_primary},
            {"heading": "Email to supervisors with no assignments", "field": form.template_secondary},
        ],
        form=form,
        cancel_url=url,
    )


@admin.route("/publish_match/<int:id>")
@roles_required("root")
def publish_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for publication because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for publication because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use during rollover. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.published = True
    log_db_commit('Publish matching attempt "{name}" to convenors'.format(name=record.name), user=current_user)

    return redirect(redirect_url())


@admin.route("/unpublish_match/<int:id>")
@roles_required("root")
def unpublish_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for unpublication because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for unpublication because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use during rollover. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.published = False
    log_db_commit('Unpublish matching attempt "{name}" from convenors'.format(name=record.name), user=current_user)

    return redirect(redirect_url())


@admin.route("/select_match/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def select_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    force = request.args.get("force", False)
    if not isinstance(force, bool):
        force = bool(int(force))

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for selection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for selection because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use.'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.is_valid and not force:
        title = 'Select match "{name}"'.format(name=record.name)
        panel_title = 'Select match "{name}"'.format(name=record.name)

        action_url = url_for("admin.select_match", id=id, force=1, url=url)
        message = (
            '<p>Match "{name}" has validation errors.</p>'
            "<p>Please confirm that you wish to select it for use during rollover of the "
            "academic year.</p>".format(name=record.name)
        )
        submit_label = "Force selection"

        form = ConfirmActionForm()
        return render_template_context(
            "admin/danger_confirm.html",
            title=title,
            panel_title=panel_title,
            action_url=action_url,
            message=message,
            submit_label=submit_label,
            form=form,
        )

    # determine whether any already-selected projects have allocations for a pclass we own
    our_pclasses = set()
    for item in record.available_pclasses:
        our_pclasses.add(item.id)

    selected_pclasses = set()
    selected = db.session.query(MatchingAttempt).filter_by(year=year, selected=True).all()
    for match in selected:
        for item in match.available_pclasses:
            selected_pclasses.add(item.id)

    intersection = our_pclasses & selected_pclasses
    if len(intersection) > 0:
        flash(
            'Cannot select match "{name}" because some project classes it handles are already determined by selected matches.'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    record.selected = True
    log_db_commit('Select matching attempt "{name}" for use during academic year rollover'.format(name=record.name), user=current_user)

    return redirect(url)


@admin.route("/deselect_match/<int:id>")
@roles_required("root")
def deselect_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for deselection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for deselection because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use.'.format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.selected = False
    log_db_commit('Deselect matching attempt "{name}" for academic year rollover'.format(name=record.name), user=current_user)

    return redirect(redirect_url())


def _validate_match_populate_submitters(record: MatchingAttempt, config: ProjectClassConfig):
    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" cannot be used to populate submitter records because it belongs to a previous selection cycle'.format(name=record.name),
            "info",
        )
        return False

    if config.year != record.year:
        flash(
            'Match "{match_name}" cannot be used to populate submitter records for project type "{pcl_name}", '
            "year = {config_year} because this configuration belongs to a previous "
            "year".format(match_name=record.name, pcl_name=config.name, config_year=config.year)
        )
        return False

    if config.select_in_previous_cycle:
        flash(
            'Match "{match_name}" cannot be used to populate submitter records for project type "{pcl_name}" '
            "because this project type is not configured to use selection in the same cycle as "
            "submission".format(match_name=record.name, pcl_name=config.name)
        )
        return False

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for use because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for use because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return False

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use.'.format(name=record.name),
            "info",
        )
        return False

    if not record.published:
        flash(
            'Match "{name}" cannot be used to populate submitter records because it has not yet been '
            "published to the module convenor. Please publish the match before attempting to generate "
            "selectors.".format(name=record.name),
            "info",
        )
        return False

    return True


@admin.route("/populate_submitters_from_match/<int:match_id>/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def populate_submitters_from_match(match_id, config_id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(match_id)
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not _validate_match_populate_submitters(record, config):
        return redirect(redirect_url())

    title = "Populate submitters from match"
    panel_title = 'Populate submitters for "{name}" from match "{match_name}"'.format(name=config.name, match_name=record.name)

    action_url = url_for(
        "admin.do_populate_submitters_from_match",
        match_id=record.id,
        config_id=config.id,
        url=redirect_url(),
    )
    message = (
        "<p>Please confirm that you wish to populate submitters for <strong>{name}</strong> from match "
        "<strong>{match_name}</strong>.</p>"
        "<p>Changes made during this process cannot be undone.</p>"
        "<p>Project assignments for submitters that already exist will not be modified. "
        "New submitters will be generated if required, "
        "and project assignments will be generated from any submission periods in which they are "
        "missing.</p>".format(name=config.name, match_name=record.name)
    )
    submit_label = "Populate submitters"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@admin.route("/do_populate_submitters_from_match/<int:match_id>/<int:config_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def do_populate_submitters_from_match(match_id, config_id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(match_id)
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not _validate_match_populate_submitters(record, config):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    task_id = register_task(
        "Populate submitters from match",
        owner=current_user,
        description=f'Use match "{record.name}" to populate submitter records in the current cycle for project type "{config.name}"',
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.matching.populate_submitters"]

    task.apply_async(args=(match_id, config_id, current_user.id, task_id), task_id=task_id)

    return redirect(url)
