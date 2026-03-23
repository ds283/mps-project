#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin
from .associations import (
    feedback_asset_to_pclasses,
    feedback_asset_to_tags,
    feedback_recipe_to_pclasses,
    feedback_recipe_to_assets,
)


class FeedbackAsset(db.Model, EditingMetadataMixin):
    """
    Represents an uploaded asset that can be used to generate feedback reports/documents
    """

    __tablename__ = "feedback_assets"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # for which project classes is this asset available?
    project_classes = db.relationship(
        "ProjectClass",
        secondary=feedback_asset_to_pclasses,
        lazy="dynamic",
        backref=db.backref("feedback_assets", lazy="dynamic"),
    )

    # link to SubmittedAsset representing this asset
    asset_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), default=None
    )
    asset = db.relationship(
        "SubmittedAsset",
        foreign_keys=[asset_id],
        uselist=False,
        backref=db.backref("feedback_asset", uselist=False),
    )

    # is this asset a base template?
    is_template = db.Column(db.Boolean(), default=False)

    # unique label
    label = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # applied tags
    tags = db.relationship(
        "TemplateTag",
        secondary=feedback_asset_to_tags,
        lazy="dynamic",
        backref=db.backref("assets", lazy="dynamic"),
    )


class TemplateTag(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Represents a tag/label applied to a template asset
    """

    __tablename__ = "template_tags"

    # unique identifier used as primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name of label
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    def make_label(self, text=None):
        label_text = text if text is not None else self.name
        return self._make_label(text=label_text)


class FeedbackRecipe(db.Model, EditingMetadataMixin):
    """
    Represents a recipe used to create a feedback report
    """

    __tablename__ = "feedback_recipes"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # for which project classes is this recipe available?
    project_classes = db.relationship(
        "ProjectClass",
        secondary=feedback_recipe_to_pclasses,
        lazy="dynamic",
        backref=db.backref("feedback_recipes", lazy="dynamic"),
    )

    # unique label
    label = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # primary template
    template_id = db.Column(db.Integer(), db.ForeignKey("feedback_assets.id"))
    template = db.relationship(
        "FeedbackAsset",
        foreign_keys=[template_id],
        uselist=False,
        backref=db.backref("template_recipes", lazy="dynamic"),
    )

    # other assets
    asset_list = db.relationship(
        "FeedbackAsset",
        secondary=feedback_recipe_to_assets,
        lazy="dynamic",
        backref=db.backref("asset_recipes", lazy="dynamic"),
    )


class FeedbackReport(db.Model):
    """
    Record data about a generated feedback report
    """

    __tablename__ = "feedback_reports"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # link to underlying asset
    asset_id = db.Column(db.Integer(), db.ForeignKey("generated_assets.id"))
    asset = db.relationship("GeneratedAsset", foreign_keys=[asset_id], uselist=False)

    # who generated the feedback
    generated_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    generated_by = db.relationship("User", foreign_keys=[generated_id], uselist=False)

    # timestamp for feedback generation
    timestamp = db.Column(db.DateTime())

    # 'owner' member set by backref to SubmissionRecord
