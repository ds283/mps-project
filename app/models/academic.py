#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from sqlalchemy import or_
from sqlalchemy.event import listens_for
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import validates
from sqlalchemy.sql import func

from ..cache import cache
from ..database import db
from ..shared.sqlalchemy import get_count
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin, StudentLevelsMixin, _get_current_year
from .associations import (
    faculty_affiliations,
    programmes_to_modules,
    tenant_to_groups,
    tenant_to_project_tag_groups,
    tenant_to_degree_programmes,
)


class ResearchGroup(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Model a row from the research group table
    """

    # make table name plural
    __tablename__ = "research_groups"

    id = db.Column(db.Integer(), primary_key=True)

    # tenants to which this research group belongs
    tenants = db.relationship(
        "Tenant",
        secondary=tenant_to_groups,
        lazy="dynamic",
        backref=db.backref("research_groups", lazy="dynamic"),
    )

    # abbreviation for use in space-limited contexts
    abbreviation = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # long-form name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # optional website
    website = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # active flag
    active = db.Column(db.Boolean())

    def disable(self):
        """
        Disable this research group
        :return:
        """

        self.active = False

        # remove this group from any faculty that have become affiliated with it
        for member in self.faculty:
            member.remove_affiliation(self)

    def enable(self):
        """
        Enable this research group
        :return:
        """

        self.active = True

    def make_label(self, text=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """
        if text is None:
            text = self.abbreviation

        return self._make_label(text)


class DegreeType(
    db.Model, ColouredLabelMixin, EditingMetadataMixin, StudentLevelsMixin
):
    """
    Model a degree type
    """

    # make table name plural
    __tablename__ = "degree_types"

    id = db.Column(db.Integer(), primary_key=True)

    # degree type label (MSc, MPhys, BSc, etc.)
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # degree type abbreviation
    abbreviation = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True, unique=True
    )

    # number of years before graduation
    duration = db.Column(db.Integer())

    # degree level (UG, PGR, PGT)
    level = db.Column(db.Integer(), default=StudentLevelsMixin.LEVEL_UG)

    @validates("level")
    def _validate_level(self, key, value):
        if value < self.LEVEL_UG:
            value = self.LEVEL_UG

        if value > self.LEVEL_PGR:
            value = self.LEVEL_UG

        return value

    # active flag
    active = db.Column(db.Boolean())

    def disable(self):
        """
        Disable this degree type
        :return:
        """
        self.active = False

        # disable any degree programmes that depend on this degree type
        for prog in self.degree_programmes:
            prog.disable()

    def enable(self):
        """
        Enable this degree type
        :return:
        """
        self.active = True

    def make_label(self, text=None, show_type=False):
        if text is None:
            if show_type:
                text = "{abbrv} ({type})".format(
                    abbrv=self.abbreviation, type=self._level_text(self.level)
                )
            else:
                text = self.abbreviation

        return self._make_label(text)


class DegreeProgramme(db.Model, EditingMetadataMixin):
    """
    Model a row from the degree programme table
    """

    # make table name plural
    __tablename__ = "degree_programmes"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # tenants to which this tag group belongs
    tenants = db.relationship(
        "Tenant",
        secondary=tenant_to_degree_programmes,
        lazy="dynamic",
        backref=db.backref("degree_programmes", lazy="dynamic"),
    )

    # programme name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    # programme abbreviation
    abbreviation = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True
    )

    # show degree type in name
    show_type = db.Column(db.Boolean(), default=True)

    # includes foundation year
    foundation_year = db.Column(db.Boolean(), default=False)

    # includes year abroad or placement year
    year_out = db.Column(db.Boolean(), default=False)

    # which year is the year out?
    year_out_value = db.Column(db.Integer())

    # active flag
    active = db.Column(db.Boolean())

    # degree type
    type_id = db.Column(db.Integer(), db.ForeignKey("degree_types.id"), index=True)
    degree_type = db.relationship(
        "DegreeType", backref=db.backref("degree_programmes", lazy="dynamic")
    )

    # modules that are part of this programme
    modules = db.relationship(
        "Module",
        secondary=programmes_to_modules,
        lazy="dynamic",
        backref=db.backref("programmes", lazy="dynamic"),
    )

    # course code, used to uniquely identify this degree programme
    course_code = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True
    )

    def disable(self):
        """
        Disable this degree programme
        :return:
        """
        self.active = False

        # disable any project classes that depend on this programme
        for pclass in self.project_classes:
            pclass.disable()

    def enable(self):
        """
        Enable this degree programme
        :return:
        """
        if self.available:
            self.active = True

    @property
    def available(self):
        """
        Determine whether this degree programme is available for use (or activation)
        :return:
        """
        # ensure degree type is active
        return self.degree_type.active

    @property
    def full_name(self):
        if self.show_type:
            return "{p} {t}".format(p=self.name, t=self.degree_type.name)

        return self.name

    @property
    def short_name(self):
        if self.show_type:
            return "{p} {t}".format(
                p=self.abbreviation, t=self.degree_type.abbreviation
            )

        return self.abbreviation

    def make_label(self, text=None):
        if text is None:
            text = self.full_name

        return self.degree_type.make_label(text=text)

    @property
    def label(self):
        return self.degree_type.make_label(self.full_name)

    @property
    def short_label(self):
        return self.degree_type.make_label(self.short_name)

    @property
    def ordered_modules(self):
        query = (
            db.session.query(programmes_to_modules.c.module_id)
            .filter(programmes_to_modules.c.programme_id == self.id)
            .subquery()
        )

        return (
            db.session.query(Module)
            .join(query, query.c.module_id == Module.id)
            .join(FHEQ_Level, FHEQ_Level.id == Module.level_id)
            .order_by(
                FHEQ_Level.numeric_level.asc(), Module.semester.asc(), Module.name.asc()
            )
        )

    def _level_modules_query(self, level_id):
        query = (
            db.session.query(programmes_to_modules.c.module_id)
            .filter(programmes_to_modules.c.programme_id == self.id)
            .subquery()
        )

        return (
            db.session.query(Module)
            .join(query, query.c.module_id == Module.id)
            .filter(Module.level_id == level_id)
            .order_by(Module.semester.asc(), Module.name.asc())
        )

    def _levels_query(self):
        query = (
            db.session.query(programmes_to_modules.c.module_id)
            .filter(programmes_to_modules.c.programme_id == self.id)
            .subquery()
        )

        return (
            db.session.query(FHEQ_Level)
            .join(Module, Module.level_id == FHEQ_Level.id, isouter=True)
            .join(query, query.c.module_id == Module.id)
            .order_by(FHEQ_Level.numeric_level.asc())
            .distinct()
        )

    def number_level_modules(self, level_id):
        return get_count(self._level_modules_query(level_id))

    def get_level_modules(self, level_id):
        return self._level_modules_query(level_id).all()

    def get_levels(self):
        return self._levels_query().all()


class SkillGroup(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Model a group of transferable skills
    """

    # make table name plural
    __tablename__ = "skill_groups"

    id = db.Column(db.Integer(), primary_key=True)

    # name of skill group
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # active?
    active = db.Column(db.Boolean())

    # add group name to labels
    add_group = db.Column(db.Boolean())

    def enable(self):
        """
        Enable this skill group and cascade, ie. enable any transferable skills associated with this group
        :return:
        """
        self.active = True

        for skill in self.skills:
            skill.enable()

    def disable(self):
        """
        Disable this skill group and cascade, ie. disable any transferable skills associated with this group
        :return:
        """
        self.active = False

        for skill in self.skills:
            skill.disable()

    def make_label(self, text=None):
        if text is None:
            text = self.name

        return self._make_label(text)

    def make_skill_label(self, skill):
        """
        Make an appropriately formatted, coloured label for a transferable skill
        :param skill:
        :return:
        """
        if self.add_group:
            label = self.name + ": "
        else:
            label = ""

        label += skill

        return self._make_label(text=label)


class TransferableSkill(db.Model, EditingMetadataMixin):
    """
    Model a transferable skill
    """

    # make table name plural
    __tablename__ = "transferable_skills"

    id = db.Column(db.Integer(), primary_key=True)

    # name of skill
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    # skill group
    group_id = db.Column(db.Integer(), db.ForeignKey("skill_groups.id"))
    group = db.relationship(
        "SkillGroup",
        foreign_keys=[group_id],
        uselist=False,
        backref=db.backref("skills", lazy="dynamic"),
    )

    # active?
    active = db.Column(db.Boolean())

    @property
    def is_active(self):
        if self.group is None:
            return self.active

        return self.active and self.group.active

    def disable(self):
        """
        Disable this transferable skill and cascade, ie. remove from any projects that have been labelled with it
        :return:
        """
        self.active = False

        # remove this skill from any projects that have been labelled with it
        for proj in self.projects:
            proj.skills.remove(self)

    def enable(self):
        """
        Enable this transferable skill
        :return:
        """
        self.active = True

    def make_label(self):
        """
        Make a label
        :return:
        """
        if self.group is None:
            return {"label": self.name, "type": "secondary"}

        return self.group.make_skill_label(self.name)

    @property
    def short_label(self):
        return self.group.make_label(self.name)


class Module(db.Model, EditingMetadataMixin):
    """
    Represent a module (course)
    """

    __tablename__ = "modules"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # unique course code
    code = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # course name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # FHEQ level
    level_id = db.Column(db.Integer(), db.ForeignKey("fheq_levels.id"))
    level = db.relationship(
        "FHEQ_Level",
        foreign_keys=[level_id],
        uselist=False,
        backref=db.backref("modules", lazy="dynamic"),
    )

    # runs in which semester?
    semester = db.Column(db.Integer())

    # first taught in
    first_taught = db.Column(db.Integer())

    # retired in
    last_taught = db.Column(db.Integer())

    @hybrid_property
    def active(self):
        return self.last_taught is None

    @active.expression
    def active(cls):
        return cls.last_taught == None

    @property
    def available(self):
        # check whether tagged FHEQ level is active
        return self.level.active

    def retire(self):
        # currently no need to cascade
        self.last_taught = _get_current_year()

    def unretire(self):
        # currently no need to cascade
        self.last_taught = None

    _semester_choices = {
        0: "Autumn Semester",
        1: "Spring Semester",
        2: "Autumn & Spring",
        3: "All-year",
    }

    @property
    def semester_label(self):
        idx = int(self.semester) if self.semester is not None else None
        if idx in Module._semester_choices:
            text = Module._semester_choices[idx]
            type = "info"
        else:
            text = "Unknown value {n}".format(n=self.semester)
            type = "danger"

        return {"label": text, "type": type}

    @property
    def level_label(self):
        return self.level.short_label

    @property
    def text_label(self):
        return self.code + " " + self.name

    def make_label(self, text=None):
        if text is None:
            text = self.text_label

        return self.level.make_label(text=text)


class FHEQ_Level(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Characterize an FHEQ level
    """

    __tablename__ = "fheq_levels"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # short version of name
    short_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # numerical level
    numeric_level = db.Column(db.Integer(), unique=True)

    # active flag
    active = db.Column(db.Boolean())

    def enable(self):
        self.active = True

    def disable(self):
        self.active = False

        # disable any modules that are attached on this FHEQ Level
        for module in self.modules:
            module.retire()

    def make_label(self, text=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """
        return self._make_label(text)

    @property
    def short_label(self):
        return self.make_label(text=self.short_name)
