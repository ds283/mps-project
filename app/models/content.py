#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from sqlalchemy.orm import validates

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin


class AssetLicense(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Model a license for distributing content
    """

    __tablename__ = "asset_licenses"

    # primary key ids
    id = db.Column(db.Integer(), primary_key=True)

    # license name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # abbreviation
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # short description
    description = db.Column(db.Text())

    # active flag
    active = db.Column(db.Boolean())

    # license version
    version = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # license URL
    url = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # LICENSE PROPERTIES

    # license allows redistribution?
    allows_redistribution = db.Column(db.Boolean(), default=False)

    def make_label(self, text=None, popover=True):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """
        if text is None:
            text = self.abbreviation

        popover_text = (
            self.description
            if (popover and self.description is not None and len(self.description) > 0)
            else None
        )

        return self._make_label(text, popover_text=popover_text)

    def enable(self):
        """
        Activate this license
        :return:
        """
        self.active = True

    def disable(self):
        """
        Disactivate this license
        :return:
        """
        self.active = False

        # TODO: eventually will need to iterate through all assets licensed under this license and set them
        #  all to the "unset" condition


class FormattedArticle(db.Model, EditingMetadataMixin):
    """
    Base class for generic HTML-like formatted page of text
    """

    __tablename__ = "formatted_articles"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # polymorphic identifier
    type = db.Column(db.Integer(), default=0, nullable=False)

    # title
    title = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # formatted text (usually held in HTML format, but doesn't have to be)
    article = db.Column(db.Text())

    # has this article been published? The exact meaning of 'published' might vary among derived models
    published = db.Column(db.Boolean(), default=False)

    # record time of publication
    publication_timestamp = db.Column(db.DateTime())

    @validates("published")
    def _validate_published(self, key, value):
        with db.session.no_autoflush:
            if value and not self.published:
                self.publication_timestamp = datetime.now()

        return value

    # set a time for this article to be automatically published, if desired
    publish_on = db.Column(db.DateTime())

    __mapper_args__ = {"polymorphic_identity": 0, "polymorphic_on": "type"}


class ConvenorSubmitterArticle(FormattedArticle):
    """
    Represents a formatted article written by a convenor and made available to all submitters attached to
    a particular ProjectClassConfig instance
    """

    __tablename__ = "submitter_convenor_articles"

    # primary key links to base table
    id = db.Column(
        db.Integer(), db.ForeignKey("formatted_articles.id"), primary_key=True
    )

    # owning ProjectClassConfig
    period_id = db.Column(db.Integer(), db.ForeignKey("submission_periods.id"))
    period = db.relationship(
        "SubmissionPeriodRecord",
        foreign_keys=[period_id],
        uselist=False,
        backref=db.backref(
            "articles", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    __mapper_args__ = {"polymorphic_identity": 1}


class ProjectSubmitterArticle(FormattedArticle):
    """
    Represents a formatted article written by a member of the supervision team and made available just to a single
    SubmissionRecord instance
    """

    __tablename__ = "submitter_project_articles"

    # primary key links to base table
    id = db.Column(
        db.Integer(), db.ForeignKey("formatted_articles.id"), primary_key=True
    )

    # owning SubmissionRecord
    record_id = db.Column(db.Integer(), db.ForeignKey("submission_records.id"))
    record = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_id],
        uselist=False,
        backref=db.backref(
            "articles", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    __mapper_args__ = {"polymorphic_identity": 2}
