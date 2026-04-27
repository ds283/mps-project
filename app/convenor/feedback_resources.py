#
# Created by David Seery on 27/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from flask import flash, redirect, request, url_for, current_app
from flask_login import current_user
from flask_security import roles_accepted
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
import app.shared.cloud_object_store.bucket_types as buckets

from app.convenor import convenor

from ..admin.utilities import create_new_template_tags
from ..database import db
from ..models import (
    FeedbackAsset,
    FeedbackRecipe,
    FeedbackTemplate,
    ProjectClass,
    SubmittedAsset,
)
from ..models.assets import ThumbnailAsset
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.context.global_context import render_template_context
from ..tasks.thumbnails import dispatch_thumbnail_task
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..shared.workflow_logging import log_db_commit

from .feedback_resources_forms import (
    EditFeedbackAssetForm,
    EditFeedbackTemplateForm,
    FeedbackRecipeFormFactory,
    UploadFeedbackAssetForm,
    AddFeedbackTemplateForm,
)
from ..shared.forms.wtf_validators import (
    make_unique_feedback_asset_label_in_pclass,
    make_unique_feedback_recipe_label_in_pclass,
    make_unique_feedback_template_label_in_pclass,
)


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------


@convenor.route("/feedback_resources/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def feedback_resources(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    num_recipes = pclass.feedback_recipes.count()
    num_templates = pclass.feedback_templates.count()
    num_assets = pclass.feedback_assets.count()

    return render_template_context(
        "convenor/dashboard/feedback_resources.html",
        pclass=pclass,
        config=config,
        url=url,
        text=text,
        num_recipes=num_recipes,
        num_templates=num_templates,
        num_assets=num_assets,
    )


# ---------------------------------------------------------------------------
# AJAX endpoints
# ---------------------------------------------------------------------------


@convenor.route("/feedback_assets_ajax/<int:pclass_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def feedback_assets_ajax(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return ajax.convenor.feedback_assets_data(pclass)


@convenor.route("/feedback_templates_ajax/<int:pclass_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def feedback_templates_ajax(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return ajax.convenor.feedback_templates_data(pclass)


@convenor.route("/feedback_recipes_ajax/<int:pclass_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def feedback_recipes_ajax(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return ajax.convenor.feedback_recipes_data(pclass)


# ---------------------------------------------------------------------------
# FeedbackAsset CRUD
# ---------------------------------------------------------------------------


@convenor.route("/add_feedback_asset/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_feedback_asset(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass_id))
    text = request.args.get("text", "Feedback resources")

    form = UploadFeedbackAssetForm(request.form)
    form.label.validators.append(make_unique_feedback_asset_label_in_pclass(pclass_id))

    if form.validate_on_submit():
        if "attachment" not in request.files or request.files["attachment"].filename == "":
            flash("Please select a file to upload.", "error")
        else:
            attachment_file = request.files["attachment"]

            submitted_asset = SubmittedAsset(
                timestamp=datetime.now(),
                uploaded_id=current_user.id,
                expiry=None,
                bucket=buckets.PROJECT_BUCKET,
            )
            db.session.add(submitted_asset)

            bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")
            object_store = bucket_map.get(buckets.PROJECT_BUCKET)

            with AssetUploadManager(
                submitted_asset,
                data=attachment_file.stream.read(),
                storage=object_store,
                audit_data=f"add_feedback_asset (pclass id #{pclass_id})",
                length=attachment_file.content_length,
                mimetype=attachment_file.content_type,
            ):
                pass

            try:
                db.session.flush()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash("Could not upload asset due to a database error. Please contact a system administrator.", "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url)

            dispatch_thumbnail_task(submitted_asset)

            now = datetime.now()
            feedback_asset = FeedbackAsset(
                pclass_id=pclass_id,
                asset_id=submitted_asset.id,
                label=form.label.data,
                description=form.description.data,
                creator_id=current_user.id,
                creation_timestamp=now,
                last_edit_id=current_user.id,
                last_edit_timestamp=now,
            )

            try:
                db.session.add(feedback_asset)
                log_db_commit(
                    f"Added feedback asset '{form.label.data}' to project class {pclass.name}",
                    user=current_user,
                    project_classes=pclass,
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                flash("Could not save feedback asset due to a database error. Please contact a system administrator.", "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url)

            flash(f'Feedback asset "{form.label.data}" was successfully uploaded.', "info")
            return redirect(url)

    return render_template_context(
        "convenor/feedback/add_feedback_asset.html",
        form=form,
        pclass=pclass,
        title="Add feedback asset",
        url=url,
        text=text,
    )


@convenor.route("/edit_feedback_asset/<int:asset_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_feedback_asset(asset_id):
    feedback_asset: FeedbackAsset = FeedbackAsset.query.get_or_404(asset_id)
    pclass: ProjectClass = feedback_asset.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass.id))
    text = request.args.get("text", "Feedback resources")

    form = EditFeedbackAssetForm(obj=feedback_asset)
    form.label.validators.append(
        make_unique_feedback_asset_label_in_pclass(pclass.id, label=feedback_asset.label)
    )

    if form.validate_on_submit():
        try:
            feedback_asset.label = form.label.data
            feedback_asset.description = form.description.data
            feedback_asset.last_edit_id = current_user.id
            feedback_asset.last_edit_timestamp = datetime.now()

            log_db_commit(
                f"Edited feedback asset '{feedback_asset.label}' in project class {pclass.name}",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save changes due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return redirect(url)

        return redirect(url)

    return render_template_context(
        "convenor/feedback/edit_feedback_asset.html",
        form=form,
        feedback_asset=feedback_asset,
        pclass=pclass,
        title="Edit feedback asset",
        url=url,
        text=text,
    )


@convenor.route("/delete_feedback_asset/<int:asset_id>")
@roles_accepted("faculty", "admin", "root")
def delete_feedback_asset(asset_id):
    feedback_asset: FeedbackAsset = FeedbackAsset.query.get_or_404(asset_id)
    pclass: ProjectClass = feedback_asset.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass.id))

    submitted_asset: SubmittedAsset = feedback_asset.asset
    label = feedback_asset.label

    try:
        bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")

        if submitted_asset is not None:
            # remove the cloud object
            if submitted_asset.bucket in bucket_map:
                storage = AssetCloudAdapter(
                    submitted_asset,
                    bucket_map[submitted_asset.bucket],
                    audit_data=f"delete_feedback_asset (asset id #{asset_id})",
                )
                try:
                    storage.delete()
                except FileNotFoundError:
                    pass

            # remove thumbnails
            thumbnails_store = bucket_map.get(buckets.THUMBNAILS_BUCKET)
            for thumb_attr in ("small_thumbnail", "medium_thumbnail"):
                thumbnail: ThumbnailAsset = getattr(submitted_asset, thumb_attr, None)
                if thumbnail is not None:
                    if thumbnails_store is not None:
                        try:
                            thumb_adapter = AssetCloudAdapter(
                                thumbnail,
                                thumbnails_store,
                                audit_data=f"delete_feedback_asset thumbnail (asset id #{asset_id})",
                            )
                            thumb_adapter.delete()
                        except FileNotFoundError:
                            pass
                    db.session.delete(thumbnail)
                    setattr(submitted_asset, f"{thumb_attr}_id", None)

            db.session.delete(submitted_asset)

        db.session.delete(feedback_asset)

        log_db_commit(
            f"Deleted feedback asset '{label}' from project class {pclass.name}",
            user=current_user,
            project_classes=pclass,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not delete feedback asset due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


# ---------------------------------------------------------------------------
# FeedbackTemplate CRUD
# ---------------------------------------------------------------------------


@convenor.route("/add_feedback_template/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_feedback_template(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass_id))
    text = request.args.get("text", "Feedback resources")

    form = AddFeedbackTemplateForm()
    form.label.validators.append(make_unique_feedback_template_label_in_pclass(pclass_id))

    if form.validate_on_submit():
        tag_list = create_new_template_tags(form)

        now = datetime.now()
        template = FeedbackTemplate(
            pclass_id=pclass_id,
            label=form.label.data,
            description=form.description.data,
            template_body=form.template_body.data,
            creator_id=current_user.id,
            creation_timestamp=now,
            last_edit_id=current_user.id,
            last_edit_timestamp=now,
        )
        template.tags = tag_list

        try:
            db.session.add(template)
            log_db_commit(
                f"Added feedback template '{form.label.data}' to project class {pclass.name}",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save feedback template due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return redirect(url)

        return redirect(url)

    return render_template_context(
        "convenor/feedback/add_feedback_template.html",
        form=form,
        pclass=pclass,
        title="Add feedback template",
        url=url,
        text=text,
    )


@convenor.route("/edit_feedback_template/<int:template_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_feedback_template(template_id):
    template: FeedbackTemplate = FeedbackTemplate.query.get_or_404(template_id)
    pclass: ProjectClass = template.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass.id))
    text = request.args.get("text", "Feedback resources")

    form = EditFeedbackTemplateForm(obj=template)
    form.label.validators.append(
        make_unique_feedback_template_label_in_pclass(pclass.id, label=template.label)
    )

    if request.method == "GET":
        # pre-populate tags from existing assignments
        form.tags.data = (list(template.tags.all()), [])

    if form.validate_on_submit():
        tag_list = create_new_template_tags(form)

        try:
            template.label = form.label.data
            template.description = form.description.data
            template.template_body = form.template_body.data
            template.tags = tag_list
            template.last_edit_id = current_user.id
            template.last_edit_timestamp = datetime.now()

            log_db_commit(
                f"Edited feedback template '{template.label}' in project class {pclass.name}",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save changes due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return redirect(url)

        return redirect(url)

    return render_template_context(
        "convenor/feedback/edit_feedback_template.html",
        form=form,
        template=template,
        pclass=pclass,
        title="Edit feedback template",
        url=url,
        text=text,
    )


@convenor.route("/delete_feedback_template/<int:template_id>")
@roles_accepted("faculty", "admin", "root")
def delete_feedback_template(template_id):
    template: FeedbackTemplate = FeedbackTemplate.query.get_or_404(template_id)
    pclass: ProjectClass = template.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass.id))
    label = template.label

    # guard: refuse if referenced by any recipe
    if template.feedback_recipes.count() > 0:
        flash(
            f'Cannot delete template "{label}" because it is used by one or more feedback recipes. '
            "Remove the template from all recipes before deleting.",
            "error",
        )
        return redirect(url)

    try:
        db.session.delete(template)
        log_db_commit(
            f"Deleted feedback template '{label}' from project class {pclass.name}",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not delete feedback template due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


# ---------------------------------------------------------------------------
# FeedbackRecipe CRUD
# ---------------------------------------------------------------------------


@convenor.route("/add_feedback_recipe/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_feedback_recipe(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass_id))
    text = request.args.get("text", "Feedback resources")

    AddFeedbackRecipeForm, _ = FeedbackRecipeFormFactory(pclass)
    form = AddFeedbackRecipeForm()
    form.label.validators.append(make_unique_feedback_recipe_label_in_pclass(pclass_id))

    if form.validate_on_submit():
        now = datetime.now()
        recipe = FeedbackRecipe(
            pclass_id=pclass_id,
            label=form.label.data,
            template_id=form.template.data.id if form.template.data is not None else None,
            creator_id=current_user.id,
            creation_timestamp=now,
            last_edit_id=current_user.id,
            last_edit_timestamp=now,
        )

        try:
            db.session.add(recipe)
            log_db_commit(
                f"Added feedback recipe '{form.label.data}' to project class {pclass.name}",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save feedback recipe due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return redirect(url)

        return redirect(url)

    return render_template_context(
        "convenor/feedback/add_feedback_recipe.html",
        form=form,
        pclass=pclass,
        title="Add feedback recipe",
        url=url,
        text=text,
    )


@convenor.route("/edit_feedback_recipe/<int:recipe_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_feedback_recipe(recipe_id):
    recipe: FeedbackRecipe = FeedbackRecipe.query.get_or_404(recipe_id)
    pclass: ProjectClass = recipe.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass.id))
    text = request.args.get("text", "Feedback resources")

    _, EditFeedbackRecipeForm = FeedbackRecipeFormFactory(pclass)
    form = EditFeedbackRecipeForm(obj=recipe)
    form.label.validators.append(
        make_unique_feedback_recipe_label_in_pclass(pclass.id, label=recipe.label)
    )

    if form.validate_on_submit():
        try:
            recipe.label = form.label.data
            recipe.template_id = form.template.data.id if form.template.data is not None else None
            recipe.last_edit_id = current_user.id
            recipe.last_edit_timestamp = datetime.now()

            log_db_commit(
                f"Edited feedback recipe '{recipe.label}' in project class {pclass.name}",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save changes due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            return redirect(url)

        return redirect(url)

    asset_list = list(recipe.asset_list.all())

    return render_template_context(
        "convenor/feedback/edit_feedback_recipe.html",
        form=form,
        recipe=recipe,
        pclass=pclass,
        asset_list=asset_list,
        title="Edit feedback recipe",
        url=url,
        text=text,
    )


@convenor.route("/delete_feedback_recipe/<int:recipe_id>")
@roles_accepted("faculty", "admin", "root")
def delete_feedback_recipe(recipe_id):
    recipe: FeedbackRecipe = FeedbackRecipe.query.get_or_404(recipe_id)
    pclass: ProjectClass = recipe.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.feedback_resources", pclass_id=pclass.id))
    label = recipe.label

    try:
        db.session.delete(recipe)
        log_db_commit(
            f"Deleted feedback recipe '{label}' from project class {pclass.name}",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not delete feedback recipe due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/add_recipe_asset/<int:recipe_id>")
@roles_accepted("faculty", "admin", "root")
def add_recipe_asset(recipe_id):
    recipe: FeedbackRecipe = FeedbackRecipe.query.get_or_404(recipe_id)
    pclass: ProjectClass = recipe.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.edit_feedback_recipe", recipe_id=recipe_id))
    text = request.args.get("text", "Edit recipe")

    already_attached_ids = {a.id for a in recipe.asset_list.all()}
    available = [a for a in pclass.feedback_assets.all() if a.id not in already_attached_ids]

    return render_template_context(
        "convenor/feedback/add_recipe_asset.html",
        recipe=recipe,
        pclass=pclass,
        available=available,
        url=url,
        text=text,
    )


@convenor.route("/attach_recipe_asset/<int:recipe_id>/<int:asset_id>")
@roles_accepted("faculty", "admin", "root")
def attach_recipe_asset(recipe_id, asset_id):
    recipe: FeedbackRecipe = FeedbackRecipe.query.get_or_404(recipe_id)
    pclass: ProjectClass = recipe.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.edit_feedback_recipe", recipe_id=recipe_id))

    asset: FeedbackAsset = FeedbackAsset.query.get_or_404(asset_id)
    if asset.pclass_id != pclass.id:
        flash("This asset does not belong to the correct project class.", "error")
        return redirect(url)

    if recipe.asset_list.filter_by(id=asset_id).first() is None:
        try:
            recipe.asset_list.append(asset)
            recipe.last_edit_id = current_user.id
            recipe.last_edit_timestamp = datetime.now()
            log_db_commit(
                f"Attached asset '{asset.label}' to feedback recipe '{recipe.label}'",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not attach asset due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/remove_recipe_asset/<int:recipe_id>/<int:asset_id>")
@roles_accepted("faculty", "admin", "root")
def remove_recipe_asset(recipe_id, asset_id):
    recipe: FeedbackRecipe = FeedbackRecipe.query.get_or_404(recipe_id)
    pclass: ProjectClass = recipe.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.edit_feedback_recipe", recipe_id=recipe_id))

    asset: FeedbackAsset = FeedbackAsset.query.filter_by(id=asset_id).first()
    if asset is not None:
        try:
            recipe.asset_list.remove(asset)
            recipe.last_edit_id = current_user.id
            recipe.last_edit_timestamp = datetime.now()
            log_db_commit(
                f"Removed asset '{asset.label}' from feedback recipe '{recipe.label}'",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not remove asset due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)
