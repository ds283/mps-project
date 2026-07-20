#
# Created by David Seery on 01/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import flash, jsonify, redirect, request, url_for
from flask_security import roles_accepted
from sqlalchemy import case, func, update
from sqlalchemy.exc import SQLAlchemyError

from app.convenor import convenor

from ..database import db
from ..models import GradingRubric, ProjectClass, RubricBand, RubricCriterion
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from .forms import (
    ActionForm,
    CloneRubricForm,
    EditRubricBandForm,
    EditRubricCriterionForm,
    EditRubricLabelForm,
    ReorderForm,
)

_ROLES = ("faculty", "admin", "root")

_TAG_CYCLE = {"plain": "negative", "negative": "positive_floor", "positive_floor": "plain"}


# ---------------------------------------------------------------------------
# Internal redirect helper — keeps the active rubric selected after a mutation
# ---------------------------------------------------------------------------


def _rubric_redirect(pclass_id, rubric_id):
    """Redirect to the grading-rubric page with the correct rubric selected."""
    return redirect(url_for("convenor.grading_rubric", pclass_id=pclass_id, rubric_id=rubric_id))


# ---------------------------------------------------------------------------
# Rubric manager (landing page + inline editor)
# ---------------------------------------------------------------------------


@convenor.route("/grading_rubric/<int:pclass_id>")
@roles_accepted(*_ROLES)
def grading_rubric(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config = pclass.most_recent_config
    if config is None:
        flash("Could not find a current configuration for this project class. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    convenor_data = get_convenor_dashboard_data(pclass, config)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # All rubrics for the selector row
    all_rubrics = pclass.grading_rubrics.order_by(GradingRubric.label).all()

    # Determine which rubric to display
    rubric_id = request.args.get("rubric_id", type=int)
    rubric: GradingRubric | None = None
    if rubric_id is not None:
        candidate = db.session.get(GradingRubric, rubric_id)
        if candidate is not None and candidate.pclass_id == pclass_id:
            rubric = candidate
    if rubric is None and all_rubrics:
        rubric = all_rubrics[0]

    action_form = ActionForm()
    label_form = EditRubricLabelForm()
    band_form = EditRubricBandForm()
    crit_form = EditRubricCriterionForm()

    if rubric is not None:
        label_form.label.data = rubric.label

    return render_template_context(
        "convenor/language_analysis/rubric_manager.html",
        pclass=pclass,
        config=config,
        pclass_config=config,
        convenor_data=convenor_data,
        grading_rubric=rubric,
        all_rubrics=all_rubrics,
        url=url,
        text=text,
        form=ReorderForm(),
        action_form=action_form,
        label_form=label_form,
        band_form=band_form,
        crit_form=crit_form,
    )


# ---------------------------------------------------------------------------
# Create rubric
# ---------------------------------------------------------------------------


@convenor.route("/create_grading_rubric/<int:pclass_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def create_grading_rubric(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = ActionForm()
    if form.validate_on_submit():
        # Generate a unique label
        existing = {r.label for r in pclass.grading_rubrics.all()}
        if not existing:
            new_label = "Default"
        else:
            base = f"Rubric {pclass.grading_rubrics.count() + 1}"
            new_label = base
            i = 2
            while new_label in existing:
                new_label = f"{base} {i}"
                i += 1

        rubric = GradingRubric(pclass_id=pclass.id, label=new_label)
        db.session.add(rubric)
        try:
            db.session.commit()
            return _rubric_redirect(pclass_id, rubric.id)
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while creating the rubric. Please try again.", "error")

    return redirect(url_for("convenor.grading_rubric", pclass_id=pclass_id))


# ---------------------------------------------------------------------------
# Edit rubric label
# ---------------------------------------------------------------------------


@convenor.route("/edit_grading_rubric_label/<int:rubric_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def edit_grading_rubric_label(rubric_id):
    rubric: GradingRubric = GradingRubric.query.get_or_404(rubric_id)
    pclass: ProjectClass = rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = EditRubricLabelForm()
    if form.validate_on_submit():
        rubric.label = form.label.data
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while saving the rubric label. Please try again.", "error")

    return _rubric_redirect(pclass.id, rubric.id)


# ---------------------------------------------------------------------------
# Band CRUD
# ---------------------------------------------------------------------------


@convenor.route("/add_rubric_band/<int:rubric_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def add_rubric_band(rubric_id):
    rubric: GradingRubric = GradingRubric.query.get_or_404(rubric_id)
    pclass: ProjectClass = rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = ActionForm()
    if form.validate_on_submit():
        max_pos = db.session.query(func.max(RubricBand.position)).filter_by(rubric_id=rubric_id).scalar() or 0
        band = RubricBand(rubric_id=rubric_id, label="New band", position=max_pos + 1)
        db.session.add(band)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while adding the band. Please try again.", "error")

    return _rubric_redirect(pclass.id, rubric_id)


@convenor.route("/edit_rubric_band/<int:band_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def edit_rubric_band(band_id):
    band: RubricBand = RubricBand.query.get_or_404(band_id)
    pclass: ProjectClass = band.rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = EditRubricBandForm()
    if form.validate_on_submit():
        band.label = form.label.data
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while saving the band label. Please try again.", "error")

    return _rubric_redirect(pclass.id, band.rubric_id)


@convenor.route("/delete_rubric_band/<int:band_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def delete_rubric_band(band_id):
    band: RubricBand = RubricBand.query.get_or_404(band_id)
    rubric_id = band.rubric_id
    pclass: ProjectClass = band.rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = ActionForm()
    if form.validate_on_submit():
        if band.criteria.count() > 0:
            flash("Cannot delete a band that still contains criteria. Remove all criteria first.", "error")
        else:
            db.session.delete(band)
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash("A database error occurred while deleting the band. Please try again.", "error")

    return _rubric_redirect(pclass.id, rubric_id)


@convenor.route("/reorder_rubric_bands/<int:rubric_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def reorder_rubric_bands(rubric_id):
    rubric: GradingRubric = GradingRubric.query.get_or_404(rubric_id)
    pclass: ProjectClass = rubric.pclass
    if not validate_is_convenor(pclass, message=False):
        return jsonify({"status": "insufficient_privileges"})

    data = request.get_json()
    if data is None or "ranking" not in data:
        return jsonify({"status": "ill_formed"})

    ordered_ids = [int(pk) for pk in data["ranking"]]
    if not ordered_ids:
        return jsonify({"status": "ok"})

    cases = case(*[(RubricBand.id == pk, i) for i, pk in enumerate(ordered_ids)])
    try:
        db.session.execute(update(RubricBand).where(RubricBand.id.in_(ordered_ids)).values(position=cases))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Criterion CRUD
# ---------------------------------------------------------------------------


@convenor.route("/add_rubric_criterion/<int:band_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def add_rubric_criterion(band_id):
    band: RubricBand = RubricBand.query.get_or_404(band_id)
    pclass: ProjectClass = band.rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = ActionForm()
    if form.validate_on_submit():
        max_pos = db.session.query(func.max(RubricCriterion.position)).filter_by(band_id=band_id).scalar() or 0
        criterion = RubricCriterion(band_id=band_id, text="New criterion", tag="plain", position=max_pos + 1)
        db.session.add(criterion)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while adding the criterion. Please try again.", "error")

    return _rubric_redirect(pclass.id, band.rubric_id)


@convenor.route("/edit_rubric_criterion/<int:criterion_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def edit_rubric_criterion(criterion_id):
    criterion: RubricCriterion = RubricCriterion.query.get_or_404(criterion_id)
    rubric_id = criterion.band.rubric_id
    pclass: ProjectClass = criterion.band.rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = EditRubricCriterionForm()
    if form.validate_on_submit():
        criterion.text = form.text.data
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while saving the criterion. Please try again.", "error")

    return _rubric_redirect(pclass.id, rubric_id)


@convenor.route("/delete_rubric_criterion/<int:criterion_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def delete_rubric_criterion(criterion_id):
    criterion: RubricCriterion = RubricCriterion.query.get_or_404(criterion_id)
    rubric_id = criterion.band.rubric_id
    pclass: ProjectClass = criterion.band.rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = ActionForm()
    if form.validate_on_submit():
        db.session.delete(criterion)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while deleting the criterion. Please try again.", "error")

    return _rubric_redirect(pclass.id, rubric_id)


@convenor.route("/cycle_rubric_criterion_tag/<int:criterion_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def cycle_rubric_criterion_tag(criterion_id):
    criterion: RubricCriterion = RubricCriterion.query.get_or_404(criterion_id)
    rubric_id = criterion.band.rubric_id
    pclass: ProjectClass = criterion.band.rubric.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    form = ActionForm()
    if form.validate_on_submit():
        criterion.tag = _TAG_CYCLE.get(criterion.tag, "plain")
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("A database error occurred while updating the criterion tag. Please try again.", "error")

    return _rubric_redirect(pclass.id, rubric_id)


@convenor.route("/reorder_rubric_criteria/<int:band_id>", methods=["POST"])
@roles_accepted(*_ROLES)
def reorder_rubric_criteria(band_id):
    band: RubricBand = RubricBand.query.get_or_404(band_id)
    pclass: ProjectClass = band.rubric.pclass
    if not validate_is_convenor(pclass, message=False):
        return jsonify({"status": "insufficient_privileges"})

    data = request.get_json()
    if data is None or "ranking" not in data or "band_id" not in data:
        return jsonify({"status": "ill_formed"})

    ordered_ids = [int(pk) for pk in data["ranking"]]
    dest_band_id = int(data["band_id"])

    if not ordered_ids:
        return jsonify({"status": "ok"})

    cases = case(*[(RubricCriterion.id == pk, i) for i, pk in enumerate(ordered_ids)])
    try:
        db.session.execute(update(RubricCriterion).where(RubricCriterion.id.in_(ordered_ids)).values(position=cases, band_id=dest_band_id))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Clone rubric from another project class
# ---------------------------------------------------------------------------


@convenor.route("/clone_grading_rubric/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted(*_ROLES)
def clone_grading_rubric(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config = pclass.most_recent_config
    if config is None:
        flash("Could not find a current configuration for this project class. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    convenor_data = get_convenor_dashboard_data(pclass, config)

    # Collect all rubrics that belong to other project classes
    candidate_rubrics = (
        db.session.query(GradingRubric)
        .join(GradingRubric.pclass)
        .filter(GradingRubric.pclass_id != pclass_id)
        .order_by(ProjectClass.name, GradingRubric.label)
        .all()
    )

    form = CloneRubricForm()
    form.source_rubric_id.choices = [(r.id, f"{r.pclass.name} — {r.label}") for r in candidate_rubrics]

    if form.validate_on_submit():
        source_rubric: GradingRubric = db.session.get(GradingRubric, form.source_rubric_id.data)
        if source_rubric is None or source_rubric.pclass_id == pclass_id:
            flash("Invalid source rubric selection.", "error")
            return redirect(url_for("convenor.grading_rubric", pclass_id=pclass_id))

        new_rubric = source_rubric.clone_to(pclass)

        # Ensure the label is unique for this project class
        existing_labels = {r.label for r in pclass.grading_rubrics.all()}
        if new_rubric.label in existing_labels:
            base = new_rubric.label
            i = 2
            while new_rubric.label in existing_labels:
                new_rubric.label = f"{base} (copy {i})"
                i += 1

        db.session.add(new_rubric)
        try:
            db.session.commit()
            flash(
                f'Rubric "{new_rubric.label}" cloned from "{source_rubric.pclass.name}" successfully.',
                "success",
            )
            return _rubric_redirect(pclass_id, new_rubric.id)
        except SQLAlchemyError:
            db.session.rollback()
            flash("A database error occurred while cloning the rubric. Please try again.", "error")

        return redirect(url_for("convenor.grading_rubric", pclass_id=pclass_id))

    return render_template_context(
        "convenor/language_analysis/clone_rubric.html",
        pclass=pclass,
        config=config,
        convenor_data=convenor_data,
        form=form,
        candidate_rubrics=candidate_rubrics,
    )
