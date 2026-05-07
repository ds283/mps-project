#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from typing import Optional

from ..database import db


class SimilarityConcern(db.Model):
    """
    Record a detected similarity concern between two SubmissionRecords for a
    specific chunk type (abstract, introduction, etc.).

    Always stored with record_a_id < record_b_id (canonical ordering).
    Upsert semantics: minhash_jaccard, transformer_cosine, and created_at are
    updated on conflict; reviewer workflow fields are never reset.
    """

    __tablename__ = "similarity_concerns"

    __table_args__ = (
        db.UniqueConstraint("record_a_id", "record_b_id", "chunk_type", name="uq_similarity_concern"),
    )

    id = db.Column(db.Integer(), primary_key=True)

    record_a_id = db.Column(
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        index=True,
        nullable=False,
    )
    record_b_id = db.Column(
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        index=True,
        nullable=False,
    )

    chunk_type = db.Column(db.String(40, collation="utf8_bin"), nullable=False)

    minhash_jaccard = db.Column(db.Float(), nullable=True)
    transformer_cosine = db.Column(db.Float(), nullable=True)

    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.now)

    reviewed = db.Column(db.Boolean(), nullable=False, default=False)
    reviewed_by_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime(), nullable=True)

    resolution = db.Column(db.String(20, collation="utf8_bin"), nullable=True)
    resolution_note = db.Column(db.Text(collation="utf8_bin"), nullable=True)

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    record_a = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_a_id],
        uselist=False,
        backref=db.backref("similarity_concerns_as_a", lazy="dynamic"),
    )
    record_b = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_b_id],
        uselist=False,
        backref=db.backref("similarity_concerns_as_b", lazy="dynamic"),
    )
    reviewed_by = db.relationship(
        "User",
        foreign_keys=[reviewed_by_id],
        uselist=False,
    )
