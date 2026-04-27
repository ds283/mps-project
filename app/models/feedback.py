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
from .associations import (
    feedback_recipe_to_assets,
    feedback_template_to_tags,
)
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin


class FeedbackAsset(db.Model, EditingMetadataMixin):
    """
    Represents an uploaded asset that can be used to generate feedback reports/documents
    """

    __tablename__ = "feedback_assets"

    __table_args__ = (db.UniqueConstraint("pclass_id", "label"),)

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # for which project class is this asset available?
    pclass_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"))
    pclass = db.relationship(
        "ProjectClass",
        foreign_keys=[pclass_id],
        uselist=False,
        backref=db.backref(
            "feedback_assets", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
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

    # unique label
    label = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
        index=True,
    )

    # description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))


class FeedbackTemplate(db.Model, EditingMetadataMixin):
    """
    Represents an editable template used for producing feedback documents
    """

    __tablename__ = "feedback_templates"

    __table_args__ = (db.UniqueConstraint("pclass_id", "label"),)

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # for which project class is this asset available?
    pclass_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"))
    pclass = db.relationship(
        "ProjectClass",
        foreign_keys=[pclass_id],
        uselist=False,
        backref=db.backref(
            "feedback_templates", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # template body, usually a Jinja2 HTML template
    template_body = db.Column(db.Text())

    # unique label
    label = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # applied tags
    tags = db.relationship(
        "FeedbackTemplateTag",
        secondary=feedback_template_to_tags,
        lazy="dynamic",
        backref=db.backref("assets", lazy="dynamic"),
    )


class FeedbackTemplateTag(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Represents a tag/label applied to a template asset
    """

    __tablename__ = "feedback_template_tags"

    __table_args__ = (db.UniqueConstraint("tenant_id", "name"),)

    # unique identifier used as primary key
    id = db.Column(db.Integer(), primary_key=True)

    # tenant this tag belongs to
    tenant_id = db.Column(db.Integer(), db.ForeignKey("tenants.id"), index=True)
    tenant = db.relationship(
        "Tenant",
        foreign_keys=[tenant_id],
        backref=db.backref("feedback_template_tags", lazy="dynamic"),
    )

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

    __table_args__ = (db.UniqueConstraint("pclass_id", "label"),)

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # for which project class is this asset available?
    pclass_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"))
    pclass = db.relationship(
        "ProjectClass",
        foreign_keys=[pclass_id],
        uselist=False,
        backref=db.backref(
            "feedback_recipes", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # unique label
    label = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # primary template
    template_id = db.Column(db.Integer(), db.ForeignKey("feedback_templates.id"))
    template = db.relationship(
        "FeedbackTemplate",
        foreign_keys=[template_id],
        uselist=False,
        backref=db.backref("feedback_recipes", lazy="dynamic"),
    )

    # other assets
    asset_list = db.relationship(
        "FeedbackAsset",
        secondary=feedback_recipe_to_assets,
        lazy="dynamic",
        backref=db.backref("feedback_recipes", lazy="dynamic"),
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
