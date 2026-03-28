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
from functools import partial
from itertools import chain as itertools_chain
from typing import Dict, Iterable, List, Tuple, Union

from bokeh.embed import components
from bokeh.plotting import figure
from celery import chain
from flask import (
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
    MatchingRecord,
    MatchingRole,
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    TaskRecord,
    User,
)
from ..shared.forms.forms import ChooseEmailTemplateForm, ChoosePairedEmailTemplatesForm
from ..shared.forms.queries import GetWorkflowTemplates
from ..shared.context.global_context import render_template_context
from ..shared.context.matching import (
    get_matching_dashboard_data,
    get_ready_to_match_data,
)
from ..shared.conversions import is_integer
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    get_automatch_pclasses,
    get_current_year,
    home_dashboard_url,
    redirect_url,
)
from ..shared.validators import (
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
    EditSupervisorRolesForm,
    NewMatchFormFactory,
    RenameMatchFormFactory,
    SelectMatchingYearFormFactory,
)


@admin.route("/manage_matching", methods=["GET", "POST"])
@roles_required("root")
def manage_matching():
    """
    Create the 'manage matching' dashboard view
    :return:
    """
    current_year = get_current_year()
    requested_year_arg = request.args.get("year", None)
    flag, requested_year = is_integer(requested_year_arg)

    allowed_years, data = _compute_allowed_matching_years(current_year)

    if len(allowed_years) == 0:
        if not data["matching_ready"]:
            flash(
                "Automated matching is not yet available because some project classes are not ready",
                "error",
            )
            return redirect(redirect_url())

        if data["rollover_in_progress"]:
            (
                flash(
                    "Automated matching is not available because a rollover of the academic year is underway",
                    "info",
                ),
            )
            return redirect(redirect_url())

        flash(
            "Automated matching is not available because no years are currently eligible",
            category="info",
        )
        return redirect(redirect_url())

    SelectMatchingYearForm = SelectMatchingYearFormFactory(allowed_years)
    form = SelectMatchingYearForm(request.form)

    if flag and requested_year is not None and requested_year in allowed_years:
        selected_year = requested_year
    elif (
        hasattr(form, "selector")
        and form.selector.data is not None
        and form.selector.data in allowed_years
    ):
        selected_year = form.selector.data
    else:
        selected_year = max(allowed_years)

    if hasattr(form, "selector"):
        form.selector.data = selected_year

    info = get_matching_dashboard_data(selected_year)

    return render_template_context(
        "admin/matching/manage.html",
        pane="manage",
        info=info,
        form=form,
        year=selected_year,
    )


@admin.route("/matches_ajax")
@roles_required("root")
def matches_ajax():
    """
    Create the 'manage matching' dashboard view
    :return:
    """
    current_year = get_current_year()

    allowed_years, data = _compute_allowed_matching_years(current_year)
    if len(allowed_years) == 0:
        return jsonify({})

    selected_year = request.args.get("year", None)
    if selected_year is None:
        return jsonify({})

    matches = db.session.query(MatchingAttempt).filter_by(year=selected_year).all()

    return ajax.admin.matches_data(
        matches,
        is_root=True,
        text="matching dashboard",
        url=url_for("admin.manage_matching", year=selected_year),
    )


@admin.route("/skip_matching")
@roles_required("root")
def skip_matching():
    """
    Mark current set of ProjectClassConfig instances to skip automated matching
    :return:
    """
    current_year = get_current_year()

    pcs = (
        db.session.query(ProjectClass)
        .filter_by(active=True)
        .order_by(ProjectClass.name.asc())
        .all()
    )

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

    NewMatchForm = NewMatchFormFactory(
        current_year, base_id=base_id, base_match=base_match
    )
    form = NewMatchForm(request.form)

    if form.validate_on_submit():
        offline = False

        if form.submit.data:
            task_name = 'Perform project matching for "{name}"'.format(
                name=form.name.data
            )
            desc = "Automated project matching task"

        elif form.offline.data:
            offline = True
            task_name = 'Generate file for offline matching for "{name}"'.format(
                name=form.name.data
            )
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
        include_only_submitted = (
            include_control.data if include_control is not None else False
        ) and (base_match.include_only_submitted if base_match is not None else True)

        base_bias_control = getattr(form, "base_bias", None)
        force_base_control = getattr(form, "force_base", None)

        attempt = MatchingAttempt(
            year=selected_year,
            base_id=base_id,
            base_bias=base_bias_control.data if base_bias_control is not None else None,
            force_base=force_base_control.data
            if force_base_control is not None
            else None,
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
                            '"{pname}" which overlaps with the current match'.format(
                                name=match.name, pname=config_a.name
                            )
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
                form.max_different_group_projects.data = (
                    base_match.max_different_group_projects
                )
                form.max_different_all_projects.data = (
                    base_match.max_different_all_projects
                )

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
            'Can not terminate matching task "{name}" because it has finished.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    title = "Terminate match"
    panel_title = "Terminate match <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_terminate_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to terminate the matching job "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Terminate job"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_terminate_match/<int:id>")
@roles_required("root")
def perform_terminate_match(id):
    record: MatchingRecord = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if record.finished:
        flash(
            'Can not terminate matching task "{name}" because it has finished.'.format(
                name=record.name
            ),
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
            'Can not terminate matching task "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=record.name),
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
            'Can not delete match "{name}" because it has not terminated. If you wish to delete this '
            "match, please terminate it first.".format(name=attempt.name),
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
    message = (
        "<p>Please confirm that you wish to delete the matching "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=attempt.name)
    )
    submit_label = "Delete match"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_delete_match/<int:id>")
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
            'Can not delete match "{name}" because it has not terminated.'.format(
                name=attempt.name
            ),
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
            'Can not delete match "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=attempt.name),
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
            'Can not clean up match "{name}" because it has not terminated.'.format(
                name=attempt.name
            ),
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

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_clean_up_match/<int:id>")
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
            'Can not clean up match "{name}" because it has not terminated.'.format(
                name=attempt.name
            ),
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
            'Can not clean up match "{name}" due to a database error. '
            "Please contact a system administrator.".format(name=attempt.name),
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
                'Can not revert match "{name}" because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not revert match "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not revert match "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
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

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_revert_match/<int:id>")
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
                'Can not revert match "{name}" because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not revert match "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not revert match "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
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
                'Can not duplicate match "{name}" because it is still awaiting '
                "manual upload".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not duplicate match "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Can not duplicate match "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
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
            'Can not duplicate match "{name}" because a new unique tag could not '
            "be generated.".format(name=record.name),
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
                'Could not rename match "{name}" due to a database error. '
                "Please contact a system administrator.".format(name=record.name),
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context(
        "admin/match_inspector/rename.html", form=form, record=record, url=url
    )


@admin.route("/compare_match/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def compare_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )

    if not record.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    year = get_current_year()
    our_pclasses = {x.id for x in record.available_pclasses}

    CompareMatchForm = CompareMatchFormFactory(
        year, record.id, our_pclasses, current_user.has_role("root")
    )
    form = CompareMatchForm(request.form)

    if form.validate_on_submit():
        comparator = form.target.data
        return redirect(
            url_for(
                "admin.do_match_compare", id1=id, id2=comparator.id, text=text, url=url
            )
        )

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
                'Can not compare match "{name}" because it is still awaiting '
                "manual upload.".format(name=record1.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(
                    name=record1.name
                ),
                "error",
            )
        return redirect(url)

    if not record1.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(
                name=record1.name
            ),
            "error",
        )
        return redirect(url)

    if not record2.finished:
        if record2.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting '
                "manual upload.".format(name=record2.name),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(
                    name=record2.name
                ),
                "error",
            )
        return redirect(url)

    if not record2.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(
                name=record2.name
            ),
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
        "moderator",
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
                'Can not compare match "{name}" because it is still awaiting upload of an offline solution.'.format(
                    name=attempt1.name
                ),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(
                    name=attempt1.name
                ),
                "error",
            )
        return jsonify({})

    if attempt1.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(
                name=attempt1.name
            ),
            "error",
        )
        return jsonify({})

    if not attempt2.finished:
        if attempt2.awaiting_upload:
            flash(
                'Can not compare match "{name}" because it is still awaiting upload of an offline solution.'.format(
                    name=attempt2.name
                ),
                "error",
            )
        else:
            flash(
                'Can not compare match "{name}" because it has not yet terminated.'.format(
                    name=attempt2.name
                ),
                "error",
            )
        return jsonify({})

    if not attempt2.solution_usable:
        flash(
            'Can not compare match "{name}" because it did not yield a usable outcome.'.format(
                name=attempt2.name
            ),
            "error",
        )
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    flag, pclass_value = is_integer(pclass_filter)

    diff_filter = request.args.get("diff_filter")

    discrepant_records = _build_match_changes(
        attempt1, attempt2, diff_filter, flag, pclass_value
    )
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
                attempt.records.join(
                    SelectingStudent, SelectingStudent.id == MatchingRecord.selector_id
                )
                .join(
                    ProjectClassConfig,
                    ProjectClassConfig.id == SelectingStudent.config_id,
                )
                .filter(ProjectClassConfig.pclass_id == pclass_id_value)
            )
        else:
            query = attempt.records
        recs: List[MatchingRecord] = query.order_by(
            MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc()
        )

        # convert to a dictionary, indexed by
        rec_dict: RecordDictType = {
            (rec.selector_id, rec.submission_period): rec for rec in recs
        }

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
            raise RuntimeError(
                "do_match_compare_ajax: rec1.selector_id and rec2.selector_id do not match"
            )

        if rec1.submission_period != rec2.submission_period:
            raise RuntimeError(
                "do_match_compare_ajax: rec1.submission_period and rec2.submission_period do not match"
            )

        # dictionary is indexed by user_id
        RoleDictType = Dict[int, MatchingRole]

        def get_role_dict(
            rec: MatchingRecord, roles: Union[int, List[int]]
        ) -> RoleDictType:
            if not isinstance(roles, list):
                roles = [roles]

            role_records: List[MatchingRole] = rec.roles.filter(
                MatchingRole.role.in_(roles)
            )
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

        def get_moderator_roles(rec: MatchingRecord) -> RoleDictType:
            return get_role_dict(rec, MatchingRole.ROLE_MODERATOR)

        def find_record_changes(
            rec1: MatchingRecord, rec2: MatchingRecord, diff_filter: str
        ) -> List[str]:
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

            # check for differing moderator roles
            if diff_filter == "all" or diff_filter == "moderator":
                moderators1: RoleDictType = get_moderator_roles(rec1)
                moderators2: RoleDictType = get_moderator_roles(rec2)
                moderators_diff = moderators1.keys() ^ moderators2.keys()
                if len(moderators_diff) > 0:
                    changes.append("moderator")

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

    if not validate_match_inspector(
        source.matching_attempt
    ) or not validate_match_inspector(dest.matching_attempt):
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

        dest.matching_attempt.last_edit_id = current_user.id
        dest.matching_attempt.last_edit_timestamp = datetime.now()

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

    if not validate_match_inspector(
        source_record.matching_attempt
    ) or not validate_match_inspector(dest_attempt):
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
                'Match "{name}" is not yet available for export because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for export because it has not yet completed.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for export because it did not yield a useable solution'.format(
                name=record.name
            ),
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
    flash(
        f'An Excel report for "{record.name}" is being generated, and you will be notified when it is available.'
    )

    return redirect(redirect_url())


@admin.route("/match_student_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_student_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for inspection because it has not yet completed.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for inspection because it did not yield a useable solution'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter", default=None)
    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # if no state filter supplied, check if one is stored in session
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
        type_filter = session["admin_match_hint_filter"]

    if hint_filter not in ["all", "satisfied", "violated"]:
        hint_filter = "all"

    if hint_filter is not None:
        session["admin_match_hint_filter"] = hint_filter

    pclasses = record.available_pclasses

    return render_template_context(
        "admin/match_inspector/student.html",
        pane="student",
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        type_filter=type_filter,
        hint_filter=hint_filter,
        text=text,
        url=url,
    )


@admin.route("/match_faculty_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_faculty_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(
                    name=record.name
                ),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for inspection because it has not yet terminated.'.format(
                    name=record.name
                ),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for inspection because it did not yield an optimal solution.'.format(
                name=record.name
            ),
            "error",
        )
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter", default=None)
    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)
    show_includes = request.args.get("show_includes", default=None)

    if show_includes is not None and show_includes not in ["true", "false"]:
        show_includes = "false"

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # if no state filter supplied, check if one is stored in session
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
        type_filter = session["admin_match_hint_filter"]

    if hint_filter not in ["all", "satisfied", "violated"]:
        hint_filter = "all"

    if hint_filter is not None:
        session["admin_match_hint_filter"] = hint_filter

    if show_includes is None and session.get("admin_match_include_match_CATS"):
        show_includes = session["admin_match_include_match_CATS"]

    if show_includes is not None:
        session["admin_match_include_match_CATS"] = show_includes

    pclasses = get_automatch_pclasses()

    return render_template_context(
        "admin/match_inspector/faculty.html",
        pane="faculty",
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        type_filter=type_filter,
        hint_filter=hint_filter,
        show_includes=show_includes,
        text=text,
        url=url,
    )


@admin.route("/match_dists_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_dists_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for inspection because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for inspection because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" is not available for inspection '
            "because it did not yield an optimal solution.".format(name=record.name),
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

    fsum = lambda x: x[0] + x[1] + x[2]
    query = record.faculty_list_query()
    CATS_tot = [
        fsum(record.get_faculty_CATS(f.id, pclass_value if flag else None))
        for f in query.all()
    ]

    CATS_plot = figure(
        title="Workload distribution", x_axis_label="CATS", width=800, height=300
    )
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

        records: List[MatchingRecord] = s.matching_records.filter(
            MatchingRecord.matching_id == record.id
        ).all()

        deltas = [r.delta for r in records]
        return sum(deltas) if None not in deltas else None

    delta_set = [_get_deltas(s) for s in selectors]
    delta_set = [x for x in delta_set if x is not None]

    delta_plot = figure(
        title="Delta distribution", x_axis_label="Total delta", width=800, height=300
    )
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


@admin.route("/match_student_view_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def match_student_view_ajax(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return jsonify({})

    if not record.finished or not record.solution_usable:
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter", default=None)
    pclass_flag, pclass_value = is_integer(pclass_filter)

    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)

    url = request.args.get("url", default=None)
    text = request.args.get("text", default=None)

    base_query = record.selector_list_query()

    def search_name(row: SelectingStudent):
        user: User = row.student.user
        return user.name

    def sort_name(row: SelectingStudent):
        user: User = row.student.user
        return [user.last_name, user.first_name]

    def search_pclass(row: SelectingStudent):
        config: ProjectClassConfig = row.config
        return config.name

    def sort_pclass(row: SelectingStudent):
        config: ProjectClassConfig = row.config
        return config.name

    def search_projects(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(
            MatchingRecord.matching_id == record.id
        ).all()

        def _get_data(rec: MatchingRecord):
            yield rec.project.name if rec.project is not None else ""
            for item in rec.roles:
                item: MatchingRole
                yield item.user.name if item.user is not None else ""

        return list(itertools_chain.from_iterable(_get_data(rec) for rec in records))

    def sort_projects(row: SelectingStudent):
        records: List[MatchingRecord] = (
            row.matching_records.filter(MatchingRecord.matching_id == record.id)
            .order_by(MatchingRecord.submission_period)
            .all()
        )

        return list(
            rec.project.name if rec.project is not None else "" for rec in records
        )

    def sort_rank(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(
            MatchingRecord.matching_id == record.id
        ).all()

        return sum(rec.total_rank for rec in records)

    def sort_score(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(
            MatchingRecord.matching_id == record.id
        ).all()

        return sum(rec.current_score for rec in records)

    student = {"search": search_name, "order": sort_name}
    pclass = {"search": search_pclass, "order": sort_pclass}
    projects = {"search": search_projects, "order": sort_projects}
    rank = {"order": sort_rank}
    score = {"order": sort_score}
    columns = {
        "student": student,
        "pclass": pclass,
        "projects": projects,
        "rank": rank,
        "scores": score,
    }

    filter_list = []

    if pclass_flag:

        def filt(pclass_value, rs: List[MatchingRecord]):
            return any(r.selector.config.pclass_id == pclass_value for r in rs)

        filter_list.append(partial(filt, pclass_value))

    if type_filter == "ordinary":

        def filt(rs: List[MatchingRecord]):
            return any(not r.project.generic for r in rs)

        filter_list.append(filt)

    elif type_filter == "generic":

        def filt(rs: List[MatchingRecord]):
            return any(r.project.generic for r in rs)

        filter_list.append(filt)

    if hint_filter == "satisfied":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[0]) > 0 for r in rs)

        filter_list.append(filt)

    elif hint_filter == "violated":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[1]) > 0 for r in rs)

        filter_list.append(filt)

    def row_filter(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(
            MatchingRecord.matching_id == record.id
        ).all()

        return all(f(records) for f in filter_list)

    with ServerSideInMemoryHandler(
        request,
        base_query,
        columns,
        row_filter=row_filter if len(filter_list) > 0 else None,
    ) as handler:

        def row_formatter(selectors: List[SelectingStudent]):
            def _internal_format(ss: List[SelectingStudent]):
                for s in ss:
                    records: List[MatchingRecord] = (
                        s.matching_records.filter(
                            MatchingRecord.matching_id == record.id
                        )
                        .order_by(MatchingRecord.submission_period)
                        .all()
                    )

                    deltas = [r.delta for r in records]
                    delta = sum(deltas) if None not in deltas else None

                    scores = [r.current_score for r in records]
                    score = sum(scores)

                    yield (records, delta, score)

            return ajax.admin.student_view_data(
                _internal_format(selectors), record.id, url=url, text=text
            )

        return handler.build_payload(row_formatter)


@admin.route("/match_faculty_view_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def match_faculty_view_ajax(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return jsonify({})

    if not record.finished or not record.solution_usable:
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter", default=None)
    pclass_flag, pclass_value = is_integer(pclass_filter)

    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)
    show_includes = request.args.get("show_includes", default=None)

    base_query = record.faculty_list_query()

    def search_name(row: FacultyData):
        user: User = row.user
        return user.name

    def sort_name(row: FacultyData):
        user: User = row.user
        return [user.last_name, user.first_name]

    def search_projects(row: FacultyData):
        records: List[MatchingRecord] = record.get_supervisor_records(row.id).all()

        return [r.project.name if r.project is not None else "" for r in records]

    def sort_projects(row: FacultyData):
        return get_count(record.get_supervisor_records(row.id))

    def search_marker(row: FacultyData):
        records: List[MatchingRecord] = record.get_marker_records(row.id).all()

        return [r.project.name if r.project is not None else "" for r in records]

    def sort_marker(row: FacultyData):
        return get_count(record.get_marker_records(row.id))

    def sort_workload(row: FacultyData):
        sup, mark, mod = record.get_faculty_CATS(row, pclass_id=pclass_value)

        return sup + mark + mod

    name = {"search": search_name, "order": sort_name}
    projects = {"search": search_projects, "order": sort_projects}
    marking = {"search": search_marker, "order": sort_marker}
    workload = {"order": sort_workload}
    columns = {
        "name": name,
        "projects": projects,
        "marking": marking,
        "workload": workload,
    }

    filter_list = []

    if pclass_flag:

        def filt(pclass_value, rs: List[MatchingRecord]):
            return any(r.selector.config.pclass_id == pclass_value for r in rs)

        filter_list.append(partial(filt, pclass_value))

    if type_filter == "ordinary":

        def filt(rs: List[MatchingRecord]):
            return any(not r.project.generic for r in rs)

        filter_list.append(filt)

    elif type_filter == "generic":

        def filt(rs: List[MatchingRecord]):
            return any(r.project.generic for r in rs)

        filter_list.append(filt)

    if hint_filter == "satisfied":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[0]) > 0 for r in rs)

        filter_list.append(filt)

    elif hint_filter == "violated":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[1]) > 0 for r in rs)

        filter_list.append(filt)

    def row_filter(row: FacultyData):
        records: List[MatchingRecord] = record.get_supervisor_records(row.id).all()

        return all(f(records) for f in filter_list)

    with ServerSideInMemoryHandler(
        request,
        base_query,
        columns,
        row_filter=row_filter if len(filter_list) > 0 else None,
    ) as handler:

        def row_formatter(records: List[FacultyData]):
            return ajax.admin.faculty_view_data(
                records,
                record,
                pclass_value if pclass_flag else None,
                type_filter,
                hint_filter,
                show_includes == "true",
            )

        return handler.build_payload(row_formatter)


@admin.route("/delete_match_record/<int:attempt_id>/<int:selector_id>")
@roles_accepted("faculty", "admin", "root")
def delete_match_record(attempt_id, selector_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    if attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(
                name=attempt.name
            ),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=attempt.name
            ),
            "info",
        )
        return redirect(redirect_url())

    try:
        # remove all matching records associated with this selector
        records = db.session.query(MatchingRecord).filter_by(
            matching_id=attempt.id, selector_id=selector_id
        )
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


@admin.route("/reassign_match_project/<int:id>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def reassign_match_project(id, pid):
    record: MatchingRecord = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(
                name=record.matching_attempt.name
            ),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    project: LiveProject = LiveProject.query.get_or_404(pid)

    if record.selector.has_submitted:
        submitted_data = record.selector.is_project_submitted(project)
        if submitted_data.get("submitted"):
            adjust = False

            if project.generic:
                # don't change supervisors here
                adjust = True

            else:
                if project.owner is not None:
                    enroll_record = project.owner.get_enrollment_record(
                        project.config.pclass_id
                    )

                    if (
                        enroll_record is not None
                        and enroll_record.supervisor_state
                        == EnrollmentRecord.SUPERVISOR_ENROLLED
                    ):
                        adjust = True

                        # remove any previous supervision roles and replace with a supervision role for the new project
                        existing_supv = record.roles.filter(
                            MatchingRole.role.in_(
                                [
                                    MatchingRole.ROLE_SUPERVISOR,
                                    MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                                ]
                            )
                        ).all()
                        for item in existing_supv:
                            record.roles.remove(item)

                        new_supv = MatchingRole(
                            user_id=project.owner_id,
                            role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                        )
                        record.roles.add(new_supv)

                    else:
                        flash(
                            "Could not reassign '{proj}' to {name} because this project's supervisor is no longer "
                            "enrolled for this project class.".format(
                                proj=project.name,
                                name=record.selector.student.user.name,
                            )
                        )

            if adjust:
                record.project_id = project.id
                record.rank = record.selector.project_rank(project.id)

                record.matching_attempt.last_edit_id = current_user.id
                record.matching_attempt.last_edit_timestamp = datetime.now()

                try:
                    log_db_commit("Reassign matched project for selector in matching attempt", user=current_user)
                except SQLAlchemyError as e:
                    flash(
                        "Could not reassign matched project because a database error was encountered.",
                        "error",
                    )
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )

        else:
            flash(
                "Could not reassign '{proj}' to {name} because this project "
                "was not included in this selector's choices".format(
                    proj=project.name, name=record.selector.student.user.name
                ),
                "error",
            )

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
            '"selected" for use during rollover of the academic year.'.format(
                name=record.matching_attempt.name
            ),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash(
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    # check intended mid is in list of attached second markers
    count = get_count(record.project.assessor_list_query.filter(FacultyData.id == mid))

    if count == 0:
        marker = FacultyData.query.get_or_404(mid)
        flash(
            "Could not assign {name} as marker since "
            'not tagged as available for assigned project "{proj}"'.format(
                name=marker.user.name, proj=record.project.name
            ),
            "error",
        )

    elif count == 1:
        record.marker_id = mid

        record.matching_attempt.last_edit_id = current_user.id
        record.matching_attempt.last_edit_timestamp = datetime.now()

        log_db_commit("Reassign marker for matching record", user=current_user)

    else:
        flash(
            "Inconsistent marker counts for matching record (id={id}). Please contact a system administrator".format(
                id=record.id
            ),
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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
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
                new_item = MatchingRole(
                    role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR, user_id=fd.id
                )
                record.roles.add(new_item)

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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for email because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for email because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
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

        return redirect(redirect_url())

    if not form.is_submitted():
        form.template.data = EmailTemplate.find_template_(_template_type, tenant=_tenant_id)

    return render_template_context(
        "shared/choose_email_template.html",
        title="Email matching results to selectors",
        action=url_for("admin.publish_matching_selectors", id=id),
        message=f'Select the email template to use when emailing matching results to selectors for "{record.name}".',
        template_fields=[{"heading": None, "field": form.template}],
        form=form,
        cancel_url=redirect_url(),
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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for email because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for email because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
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

        return redirect(redirect_url())

    if not form.is_submitted():
        form.template_primary.data = EmailTemplate.find_template_(_notify_type, tenant=_tenant_id)
        form.template_secondary.data = EmailTemplate.find_template_(_unneeded_type, tenant=_tenant_id)

    return render_template_context(
        "shared/choose_email_template.html",
        title="Email matching results to supervisors",
        action=url_for("admin.publish_matching_supervisors", id=id),
        message=f'Select the email templates to use when emailing matching results to supervisors for "{record.name}".',
        template_fields=[
            {"heading": "Email to supervisors with assignments", "field": form.template_primary},
            {"heading": "Email to supervisors with no assignments", "field": form.template_secondary},
        ],
        form=form,
        cancel_url=redirect_url(),
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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for publication because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for publication because it has not yet '
                "terminated.".format(name=record.name),
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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for unpublication because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for unpublication because it has not yet '
                "terminated.".format(name=record.name),
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


@admin.route("/select_match/<int:id>")
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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for selection because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for selection because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution '
            "and is not available for use.".format(name=record.name),
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

        return render_template_context(
            "admin/danger_confirm.html",
            title=title,
            panel_title=panel_title,
            action_url=action_url,
            message=message,
            submit_label=submit_label,
        )

    # determine whether any already-selected projects have allocations for a pclass we own
    our_pclasses = set()
    for item in record.available_pclasses:
        our_pclasses.add(item.id)

    selected_pclasses = set()
    selected = (
        db.session.query(MatchingAttempt).filter_by(year=year, selected=True).all()
    )
    for match in selected:
        for item in match.available_pclasses:
            selected_pclasses.add(item.id)

    intersection = our_pclasses & selected_pclasses
    if len(intersection) > 0:
        flash(
            'Cannot select match "{name}" because some project classes it handles are already '
            "determined by selected matches.".format(name=record.name),
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
            'Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for deselection because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for deselection because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution '
            "and is not available for use.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.selected = False
    log_db_commit('Deselect matching attempt "{name}" for academic year rollover'.format(name=record.name), user=current_user)

    return redirect(redirect_url())


def _validate_match_populate_submitters(
    record: MatchingAttempt, config: ProjectClassConfig
):
    year = get_current_year()
    if record.year != year:
        flash(
            'Match "{name}" cannot be used to populate submitter records because it belongs to a previous selection cycle'.format(
                name=record.name
            ),
            "info",
        )
        return False

    if config.year != record.year:
        flash(
            'Match "{match_name}" cannot be used to populate submitter records for project type "{pcl_name}", '
            "year = {config_year} because this configuration belongs to a previous "
            "year".format(
                match_name=record.name, pcl_name=config.name, config_year=config.year
            )
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
                'Match "{name}" is not yet available for use because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Match "{name}" is not yet available for use because it has not yet '
                "terminated.".format(name=record.name),
                "error",
            )
        return False

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution '
            "and is not available for use.".format(name=record.name),
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
    panel_title = 'Populate submitters for "{name}" from match "{match_name}"'.format(
        name=config.name, match_name=record.name
    )

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

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/do_populate_submitters_from_match/<int:match_id>/<int:config_id>")
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

    task.apply_async(
        args=(match_id, config_id, current_user.id, task_id), task_id=task_id
    )

    return redirect(url)
