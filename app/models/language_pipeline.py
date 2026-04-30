#
# Created by David Seery on 30/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from ..database import db


class GradingRubric(db.Model):
    __tablename__ = "grading_rubric"
    __table_args__ = (db.UniqueConstraint("project_class_id", "label"),)

    id = db.Column(db.Integer(), primary_key=True)

    project_class_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"), nullable=False)
    project_class = db.relationship(
        "ProjectClass",
        foreign_keys=[project_class_id],
        uselist=False,
        backref=db.backref("grading_rubrics", lazy="dynamic"),
    )

    label = db.Column(db.String(255, collation="utf8_bin"), nullable=False)

    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime(), nullable=False, default=datetime.now, onupdate=datetime.now)

    bands = db.relationship(
        "RubricBand",
        back_populates="rubric",
        order_by="RubricBand.position",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def clone_to(self, target_project_class):
        new_rubric = GradingRubric(
            project_class_id=target_project_class.id,
            label=self.label,
        )
        for band in self.bands:
            band.clone_to(new_rubric)
        return new_rubric

    def to_prompt_bands(self):
        return [
            {"band": band.label, "criteria": [c.text for c in band.criteria]}
            for band in self.bands
        ]

    def negative_criteria(self):
        return frozenset(
            c.text
            for band in self.bands
            for c in band.criteria
            if c.tag == "negative"
        )

    def positive_floor_criteria(self):
        return frozenset(
            c.text
            for band in self.bands
            for c in band.criteria
            if c.tag == "positive_floor"
        )


class RubricBand(db.Model):
    __tablename__ = "rubric_band"

    id = db.Column(db.Integer(), primary_key=True)

    rubric_id = db.Column(db.Integer(), db.ForeignKey("grading_rubric.id"), nullable=False)
    rubric = db.relationship("GradingRubric", back_populates="bands")

    label = db.Column(db.String(255, collation="utf8_bin"), nullable=False)
    position = db.Column(db.Integer(), nullable=False)

    criteria = db.relationship(
        "RubricCriterion",
        back_populates="band",
        order_by="RubricCriterion.position",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def clone_to(self, target_rubric):
        new_band = RubricBand(
            rubric=target_rubric,
            label=self.label,
            position=self.position,
        )
        for criterion in self.criteria:
            criterion.clone_to(new_band)
        return new_band


class RubricCriterion(db.Model):
    __tablename__ = "rubric_criterion"

    id = db.Column(db.Integer(), primary_key=True)

    band_id = db.Column(db.Integer(), db.ForeignKey("rubric_band.id"), nullable=False)
    band = db.relationship("RubricBand", back_populates="criteria")

    text = db.Column(db.Text(collation="utf8_bin"), nullable=False)
    tag = db.Column(db.String(20, collation="utf8_bin"), nullable=False, default="plain")
    position = db.Column(db.Integer(), nullable=False)

    def clone_to(self, target_band):
        return RubricCriterion(
            band=target_band,
            text=self.text,
            tag=self.tag,
            position=self.position,
        )
