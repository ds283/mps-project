#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from collections.abc import Iterable
from datetime import datetime

import humanize
from flask import current_app
from flask_security import current_user
from sqlalchemy import and_, or_
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import validates

import app.shared.cloud_object_store.bucket_types as buckets
import app.shared.cloud_object_store.encryption_types as encryptions

from ..database import db
from ..shared.colours import get_text_colour
from ..shared.sqlalchemy import get_count
from .defaults import DEFAULT_STRING_LENGTH


class EditingMetadataMixin:
    # created by
    @declared_attr
    def creator_id(cls):
        return db.Column(db.Integer(), db.ForeignKey("users.id"))

    @declared_attr
    def created_by(cls):
        return db.relationship(
            "User", foreign_keys=lambda: [cls.creator_id], uselist=False
        )

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    @declared_attr
    def last_edit_id(cls):
        return db.Column(db.Integer(), db.ForeignKey("users.id"))

    @declared_attr
    def last_edited_by(cls):
        return db.relationship(
            "User", foreign_keys=lambda: [cls.last_edit_id], uselist=False
        )

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


class ColouredLabelMixin:
    # colour
    colour = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    def make_CSS_style(self):
        if self.colour is None:
            return None

        return "background-color:{bg}!important; color:{fg}!important;".format(
            bg=self.colour, fg=get_text_colour(self.colour)
        )

    def _make_label(self, text, popover_text=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """
        style = self.make_CSS_style()

        data = {"label": f"{text}", "style": style}

        if popover_text is not None:
            data["popover"] = popover_text

        return data


class WorkflowStatesMixin:
    """
    Single point of definition for workflow states
    """

    WORKFLOW_APPROVAL_QUEUED = 2
    WORKFLOW_APPROVAL_REJECTED = 1
    WORKFLOW_APPROVAL_VALIDATED = 0

    WORKFLOW_CONFIRMED = 10

    _labels = {
        WORKFLOW_CONFIRMED: "Confirmed",
        WORKFLOW_APPROVAL_QUEUED: "Queued for approval",
        WORKFLOW_APPROVAL_REJECTED: "Rejected",
        WORKFLOW_APPROVAL_VALIDATED: "Approved",
    }


class WorkflowMixin(WorkflowStatesMixin):
    """
    Capture workflow state
    """

    # workflow status
    workflow_state = db.Column(
        db.Integer(), default=WorkflowStatesMixin.WORKFLOW_APPROVAL_QUEUED
    )

    # who validated this record, if it is validated?
    @declared_attr
    def validator_id(cls):
        return db.Column(db.Integer(), db.ForeignKey("users.id"))

    @declared_attr
    def validated_by(cls):
        return db.relationship(
            "User", foreign_keys=lambda: [cls.validator_id], uselist=False
        )

    # validator timestamp
    validated_timestamp = db.Column(db.DateTime())

    @validates("workflow_state")
    def _workflow_state_validator(self, key, value):
        with db.session.no_autoflush:
            if value == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED:
                self.validator_id = None
                self.validated_timestamp = None

            else:
                now = datetime.now()
                self.validated_timestamp = now

                # if we are called from inside a Celery task then current_user is not set, but
                # because it is a proxy we can't just test whether it is None.
                # instead, try to access the .id field, and if this raises an AttributeError then
                # bail out by setting validator_id to None
                try:
                    self.validator_id = current_user.id
                except AttributeError:
                    self.validator_id = None

                if self.workflow_state != value:
                    history = self.__history_model__(
                        owner_id=self.id,
                        year=_get_current_year(),
                        user_id=self.validator_id,
                        timestamp=now,
                        event=value,
                    )
                    db.session.add(history)

            return value


class WorkflowHistoryMixin(WorkflowStatesMixin):
    """
    Capture a workflow history
    """

    # workflow event
    event = db.Column(db.Integer())

    # year tag
    @declared_attr
    def year(cls):
        return db.Column(db.Integer(), db.ForeignKey("main_config.year"))

    # workflow user id
    @declared_attr
    def user_id(cls):
        return db.Column(db.Integer(), db.ForeignKey("users.id"), index=True)

    @declared_attr
    def user(cls):
        return db.relationship(
            "User", foreign_keys=lambda: [cls.user_id], uselist=False
        )

    # workflow timestamp
    timestamp = db.Column(db.DateTime(), index=True)

    @property
    def _text_event(self):
        if self.event not in WorkflowHistoryMixin._labels:
            return "Unknown workflow event"

        return WorkflowHistoryMixin._labels[self.event]

    @property
    def text_description(self):
        return "{event} by {name} at {time}".format(
            event=self._text_event,
            name="unknown user" if self.user is None else self.user.name,
            time="unknown time"
            if self.timestamp is None
            else self.timestamp.strftime("%a %d %b %Y %H:%M:%S"),
        )


def ProjectConfigurationMixinFactory(
    backref_label,
    force_unique_names,
    skills_mapping_table,
    skills_mapped_column,
    skills_self_column,
    allow_edit_skills,
    programmes_mapping_table,
    programmes_mapped_column,
    programmes_self_column,
    allow_edit_programmes,
    tags_mapping_table,
    tags_mapped_column,
    tags_self_column,
    allow_edit_tags,
    assessor_mapping_table,
    assessor_mapped_column,
    assessor_self_column,
    assessor_backref_label,
    allow_edit_assessors,
    supervisor_mapping_table,
    supervisor_mapped_column,
    supervisor_self_column,
    supervisor_backref_label,
    allow_edit_supervisors,
):
    class ProjectConfigurationMixin(ProjectMeetingChoicesMixin):
        # NAME

        name = db.Column(
            db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
            unique=(force_unique_names == "unique"),
            index=True,
        )

        # OWNERSHIP

        # which faculty member owns this project?
        # can be null if this is a generic project (one with a pool of faculty)
        @declared_attr
        def owner_id(cls):
            return db.Column(
                db.Integer(),
                db.ForeignKey("faculty_data.id"),
                index=True,
                nullable=True,
            )

        @declared_attr
        def owner(cls):
            return db.relationship(
                "FacultyData",
                foreign_keys=lambda: [cls.owner_id],
                backref=db.backref(backref_label, lazy="dynamic"),
            )

        # positively flag this as a generic project
        # (generic projects can only be set up by convenors)
        generic = db.Column(db.Boolean(), default=False)

        # TAGS AND METADATA

        # is this project ATAS restricted?
        ATAS_restricted = db.Column(db.Boolean(), default=False)

        # normalized tags associated with this project (if any)
        @declared_attr
        def tags(cls):
            return db.relationship(
                "ProjectTag",
                secondary=tags_mapping_table,
                lazy="dynamic",
                backref=db.backref(backref_label, lazy="dynamic"),
            )

        if allow_edit_tags == "allow":

            def add_tag(self, tag):
                if tag not in self.tags:
                    self.tags.append(tag)

            def remove_tag(self, tag):
                if tag in self.tags:
                    self.tags.remove(tag)

        @property
        def ordered_tags(self):
            from .projects import ProjectTag

            query = (
                db.session.query(tags_mapped_column.label("tag_id"))
                .filter(tags_self_column == self.id)
                .subquery()
            )

            return (
                db.session.query(ProjectTag)
                .join(query, query.c.tag_id == ProjectTag.id)
                .order_by(ProjectTag.name.asc())
            )

        # which research group is associated with this project?
        @declared_attr
        def group_id(cls):
            return db.Column(
                db.Integer(),
                db.ForeignKey("research_groups.id"),
                index=True,
                nullable=True,
            )

        @declared_attr
        def group(cls):
            return db.relationship(
                "ResearchGroup",
                foreign_keys=lambda: [cls.group_id],
                backref=db.backref(backref_label, lazy="dynamic"),
            )

        # which transferable skills are associated with this project?
        @declared_attr
        def skills(cls):
            return db.relationship(
                "TransferableSkill",
                secondary=skills_mapping_table,
                lazy="dynamic",
                backref=db.backref(backref_label, lazy="dynamic"),
            )

        if allow_edit_skills == "allow":

            def add_skill(self, skill):
                self.skills.append(skill)

            def remove_skill(self, skill):
                self.skills.remove(skill)

        @property
        def ordered_skills(self):
            from .academic import SkillGroup, TransferableSkill

            query = (
                db.session.query(skills_mapped_column.label("skill_id"))
                .filter(skills_self_column == self.id)
                .subquery()
            )

            return (
                db.session.query(TransferableSkill)
                .join(query, query.c.skill_id == TransferableSkill.id)
                .join(SkillGroup, SkillGroup.id == TransferableSkill.group_id)
                .order_by(SkillGroup.name.asc(), TransferableSkill.name.asc())
            )

        # which degree programmes are preferred for this project?
        @declared_attr
        def programmes(cls):
            return db.relationship(
                "DegreeProgramme",
                secondary=programmes_mapping_table,
                lazy="dynamic",
                backref=db.backref(backref_label, lazy="dynamic"),
            )

        if allow_edit_programmes == "allow":

            def add_programme(self, prog):
                self.programmes.append(prog)

            def remove_programme(self, prog):
                self.programmes.remove(prog)

        @property
        def ordered_programmes(self):
            from .academic import DegreeProgramme, DegreeType

            query = (
                db.session.query(programmes_mapped_column.label("programme_id"))
                .filter(programmes_self_column == self.id)
                .subquery()
            )

            return (
                db.session.query(DegreeProgramme)
                .join(query, query.c.programme_id == DegreeProgramme.id)
                .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
                .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
            )

        # SELECTION

        # is a meeting required before selecting this project?
        # takes values from ProjectMeetingChoicesMixin
        meeting_reqd = db.Column(db.Integer())

        # MATCHING

        # impose limitation on capacity
        enforce_capacity = db.Column(db.Boolean())

        # table of allowed assessors
        @declared_attr
        def assessors(cls):
            return db.relationship(
                "FacultyData",
                secondary=assessor_mapping_table,
                lazy="dynamic",
                backref=db.backref(assessor_backref_label, lazy="dynamic"),
            )

        if allow_edit_assessors:

            def add_assessor(self, faculty, autocommit=False):
                """
                Add a FacultyData instance as an assessor
                :param faculty:
                :return:
                """
                if not self.can_enroll_assessor(faculty):
                    return

                self.assessors.append(faculty)

                if autocommit:
                    db.session.commit()

            def remove_assessor(self, faculty, autocommit=False):
                """
                Remove a FacultyData instance as an assessor
                :param faculty:
                :return:
                """
                if (
                    not faculty in self.assessors
                ):  # no need to check carefully, just remove
                    return

                self.assessors.remove(faculty)

                if autocommit:
                    db.session.commit()

        def _assessor_list_query(self, pclass):
            from .faculty import EnrollmentRecord, FacultyData
            from .project_class import ProjectClass
            from .users import User

            if isinstance(pclass, int):
                pclass_id = pclass
            elif isinstance(pclass, ProjectClass):
                pclass_id = pclass.id
            else:
                raise RuntimeError(
                    "Could not interpret parameter pclass of type {typ} in ProjectConfigurationMixin._assessor_list_query".format(
                        typ=type(pclass)
                    )
                )

            fac_ids = (
                db.session.query(assessor_mapped_column.label("faculty_id"))
                .filter(assessor_self_column == self.id)
                .subquery()
            )

            query = (
                db.session.query(FacultyData)
                .join(fac_ids, fac_ids.c.faculty_id == FacultyData.id)
                .join(User, User.id == FacultyData.id)
                .filter(User.active.is_(True))
                .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id)
                .filter(EnrollmentRecord.pclass_id == pclass_id)
                .join(ProjectClass, ProjectClass.id == EnrollmentRecord.pclass_id)
                .filter(
                    or_(
                        and_(
                            ProjectClass.uses_marker.is_(True),
                            EnrollmentRecord.marker_state
                            == EnrollmentRecord.MARKER_ENROLLED,
                        ),
                        and_(
                            ProjectClass.uses_presentations.is_(True),
                            EnrollmentRecord.presentations_state
                            == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                        ),
                    )
                )
                .order_by(User.last_name.asc(), User.first_name.asc())
            )

            return query

        def _is_assessor_for_at_least_one_pclass(self, faculty):
            """
            Check whether a given faculty member is enrolled as an assessor for at least one
            of the project classes associated with this project
            :param faculty:
            :return:
            """
            from .faculty import EnrollmentRecord, FacultyData

            if not isinstance(faculty, FacultyData):
                faculty = db.session.query(FacultyData).filter_by(id=faculty).one()

            pclasses = self.project_classes.subquery()

            query = faculty.enrollments.join(
                pclasses, pclasses.c.id == EnrollmentRecord.pclass_id
            ).filter(
                or_(
                    and_(
                        pclasses.c.uses_marker.is_(True),
                        or_(
                            EnrollmentRecord.marker_state
                            == EnrollmentRecord.MARKER_ENROLLED,
                            EnrollmentRecord.marker_state
                            == EnrollmentRecord.MARKER_SABBATICAL,
                        ),
                    ),
                    and_(
                        pclasses.c.uses_presentations.is_(True),
                        or_(
                            EnrollmentRecord.presentations_state
                            == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                            EnrollmentRecord.presentations_state
                            == EnrollmentRecord.PRESENTATIONS_SABBATICAL,
                        ),
                    ),
                )
            )

            return get_count(query) > 0

        def _maintenance_assessor_prune(self):
            """
            ensure that assessor list does not contain anyone who is no longer enrolled for those tasks
            note that _is_assessor_for_at_least_one_pclass() allows faculty who are on sabbatical; we don't
            want to strip these assessors off, because then they would have to be pointlessly re-added by hand
            when they come back from sabbatical
            :return:
            """
            removed = [
                f
                for f in self.assessors
                if not self._is_assessor_for_at_least_one_pclass(f)
            ]
            self.assessors = [
                f
                for f in self.assessors
                if self._is_assessor_for_at_least_one_pclass(f)
            ]

            for f in removed:
                current_app.logger.info(
                    'Regular maintenance: pruned assessor "{name}" from project "{proj}" since '
                    "they no longer meet eligibility criteria".format(
                        name=f.user.name, proj=self.name
                    )
                )

            return len(removed) > 0

        def _maintenance_assessor_remove_duplicates(self):
            """
            remove any duplicates from assessor lists
            :return:
            """
            removed = 0

            faculty = set()
            for assessor in self.assessors:
                faculty.add(assessor.id)

            for assessor_id in faculty:
                count = get_count(self.assessors.filter_by(id=assessor_id))

                if count > 1:
                    f = self.assessors.filter_by(id=assessor_id).first()
                    current_app.logger.info(
                        'Regular maintenance: assessor "{name}" from project "{proj}" occurs '
                        "multiple times (multiplicity = {count})".format(
                            name=f.user.name, proj=self.name, count=count
                        )
                    )

                    while get_count(self.assessors.filter_by(id=assessor_id)) > 1:
                        self.assessors.remove(f)
                        removed += 1

            return removed > 0

        # table of allowed supervisors, if used (always used for generic projects)
        @declared_attr
        def supervisors(cls):
            return db.relationship(
                "FacultyData",
                secondary=supervisor_mapping_table,
                lazy="dynamic",
                backref=db.backref(supervisor_backref_label, lazy="dynamic"),
            )

        if allow_edit_supervisors:

            def add_supervisor(self, faculty, autocommit=False):
                """
                Add a FacultyData instance as a possible supervisor
                :param faculty:
                :param autocommit:
                :return:
                """
                if not self.can_enroll_supervisor(faculty):
                    return

                self.supervisors.append(faculty)

                if autocommit:
                    db.session.commit()

            def remove_supervisor(self, faculty, autocommit=False):
                """
                Remove a FacultyData instance as a possible supervisor
                :param faculty:
                :param autocommit:
                :return:
                """
                if not faculty in self.supervisors:
                    return

                self.supervisors.remove(faculty)

                if autocommit:
                    db.session.commit()

        def _supervisor_list_query(self, pclass):
            from .faculty import EnrollmentRecord, FacultyData
            from .project_class import ProjectClass
            from .users import User

            if isinstance(pclass, int):
                pclass_id = pclass
            elif isinstance(pclass, ProjectClass):
                pclass_id = pclass.id
            else:
                raise RuntimeError(
                    "Could not interpret parameter pclass of type {typ} in ProjectConfigurationMixin._supervisor_list_query".format(
                        typ=type(pclass)
                    )
                )

            fac_ids = (
                db.session.query(supervisor_mapped_column.label("faculty_id"))
                .filter(supervisor_self_column == self.id)
                .subquery()
            )

            query = (
                db.session.query(FacultyData)
                .join(fac_ids, fac_ids.c.faculty_id == FacultyData.id)
                .join(User, User.id == FacultyData.id)
                .filter(User.active.is_(True))
                .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id)
                .filter(EnrollmentRecord.pclass_id == pclass_id)
                .join(ProjectClass, ProjectClass.id == EnrollmentRecord.pclass_id)
                .filter(
                    or_(
                        and_(
                            ProjectClass.uses_supervisor.is_(True),
                            EnrollmentRecord.supervisor_state
                            == EnrollmentRecord.SUPERVISOR_ENROLLED,
                        )
                    )
                )
                .order_by(User.last_name.asc(), User.first_name.asc())
            )

            return query

        def _is_supervisor_for_at_least_one_pclass(self, faculty):
            """
            Check whether a given faculty member is enrolled as a supervisor for at least one
            of the project classes associated with this project
            :param faculty:
            :return:
            """
            from .faculty import EnrollmentRecord, FacultyData

            if not isinstance(faculty, FacultyData):
                faculty = db.session.query(FacultyData).filter_by(id=faculty).one()

            pclasses = self.project_classes.subquery()

            query = faculty.enrollments.join(
                pclasses, pclasses.c.id == EnrollmentRecord.pclass_id
            ).filter(
                and_(
                    pclasses.c.uses_supervisor.is_(True),
                    or_(
                        EnrollmentRecord.supervisor_state
                        == EnrollmentRecord.MARKER_ENROLLED,
                        EnrollmentRecord.supervisor_state
                        == EnrollmentRecord.MARKER_SABBATICAL,
                    ),
                )
            )

            return get_count(query) > 0

        def _maintenance_supervisor_prune(self):
            """
            ensure that supervisor list does not contain anyone who is no longer enrolled for those tasks
            note that _is_supervisor_for_at_least_one_pclass() allows faculty who are on sabbatical; we don't
            want to strip these supervisors off, because then they would have to be pointlessly re-added by hand
            when they come back from sabbatical
            :return:
            """
            # only generic projects should have a nonzero supervisor pool
            if not self.generic:
                count = get_count(self.supervisors) > 0
                if count > 0:
                    self.supervisors = []
                    current_app.logger.info(
                        'Regular maintenance: removed supervisor pool from project "{proj}" because '
                        "it is not of generic type,".format(proj=self.name)
                    )

                    return count

            if self.generic:
                removed = [
                    f
                    for f in self.supervisors
                    if not self._is_supervisor_for_at_least_one_pclass(f)
                ]
                self.supervisors = [
                    f
                    for f in self.supervisors
                    if self._is_supervisor_for_at_least_one_pclass(f)
                ]

                for f in removed:
                    current_app.logger.info(
                        'Regular maintenance: pruned supervisor "{name}" from project "{proj}" since '
                        "they no longer meet eligibility criteria".format(
                            name=f.user.name, proj=self.name
                        )
                    )

                return len(removed) > 0

            return 0

        def _maintenance_supervisor_remove_duplicates(self):
            """
            remove any duplicates from supervisor lists
            :return:
            """
            removed = 0

            faculty = set()
            for supv in self.supervisors:
                faculty.add(supv.id)

            for supv_id in faculty:
                count = get_count(self.supervisors.filter_by(id=supv_id))

                if count > 1:
                    f = self.supervisors.filter_by(id=supv_id).first()
                    current_app.logger.info(
                        'Regular maintenance: supervisor "{name}" from project "{proj}" occurs '
                        "multiple times (multiplicity = {count})".format(
                            name=f.user.name, proj=self.name, count=count
                        )
                    )

                    while get_count(self.supervisors.filter_by(id=supv_id)) > 1:
                        self.supervisors.remove(f)
                        removed += 1

            return removed > 0

        # PRESENTATIONS

        # don't schedule with other submitters doing the same project
        dont_clash_presentations = db.Column(db.Boolean(), default=True)

        # POPULARITY DISPLAY

        # show popularity estimate
        show_popularity = db.Column(db.Boolean())

        # show number of selections
        show_selections = db.Column(db.Boolean())

        # show number of bookmarks
        show_bookmarks = db.Column(db.Boolean())

    return ProjectConfigurationMixin


def ProjectDescriptionMixinFactory(
    team_mapping_table,
    team_backref,
    module_mapping_table,
    module_backref,
    module_mapped_column,
    module_self_column,
):
    class ProjectDescriptionMixin:
        # text description of the project
        description = db.Column(db.Text())

        # recommended reading/resources
        reading = db.Column(db.Text())

        # supervisory roles
        @declared_attr
        def team(self):
            return db.relationship(
                "Supervisor",
                secondary=team_mapping_table,
                lazy="dynamic",
                backref=db.backref(team_backref, lazy="dynamic"),
            )

        # maximum number of students
        capacity = db.Column(db.Integer())

        # tagged recommended modules
        @declared_attr
        def modules(self):
            return db.relationship(
                "Module",
                secondary=module_mapping_table,
                lazy="dynamic",
                backref=db.backref(module_backref, lazy="dynamic"),
            )

        # what are the aims of this project?
        # this data is provided to markers so that they have clear criteria to mark against.
        # SHOULD NOT BE EXPOSED TO STUDENTS
        aims = db.Column(db.Text())

        # is this project review-only?
        review_only = db.Column(db.Boolean(), default=False)

        # METHODS

        def _level_modules_query(self, level_id):
            from .academic import Module

            query = (
                db.session.query(module_mapped_column.label("module_id"))
                .filter(module_self_column == self.id)
                .subquery()
            )

            return (
                db.session.query(Module)
                .join(query, query.c.module_id == Module.id)
                .filter(Module.level_id == level_id)
                .order_by(Module.semester.asc(), Module.name.asc())
            )

        def number_level_modules(self, level_id):
            return get_count(self._level_modules_query(level_id))

        def get_level_modules(self, level_id):
            return self._level_modules_query(level_id).all()

        @property
        def has_modules(self):
            return get_count(self.modules) > 0

        @property
        def ordered_modules(self):
            from .academic import FHEQ_Level, Module

            query = (
                db.session.query(module_mapped_column.label("module_id"))
                .filter(module_self_column == self.id)
                .subquery()
            )

            return (
                db.session.query(Module)
                .join(query, query.c.module_id == Module.id)
                .join(FHEQ_Level, FHEQ_Level.id == Module.level_id)
                .order_by(
                    FHEQ_Level.numeric_level.asc(),
                    Module.semester.asc(),
                    Module.name.asc(),
                )
            )

    return ProjectDescriptionMixin


class AssetExpiryMixin:
    # expiry time: asset will be cleaned up by automatic garbage collector after this
    expiry = db.Column(db.DateTime(), nullable=True, default=None)


class AssetDownloadDataMixin:
    # optional mimetype
    mimetype = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), default=None
    )

    # target filename
    target_name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))


class BaseAssetMixin:
    # timestamp
    timestamp = db.Column(db.DateTime(), index=True)

    # unique filename
    unique_name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
        nullable=False,
        unique=True,
    )

    # raw filesize (not compressed, not encrypted)
    filesize = db.Column(db.Integer())

    # has this asset been marked as lost by a maintenance task?
    lost = db.Column(db.Boolean(), nullable=False, default=False)

    # has this asset been marked as unattached by a maintenance task?
    unattached = db.Column(db.Boolean(), nullable=False, default=False)

    # bucket associated with this asset
    bucket = db.Column(db.Integer(), nullable=False, default=buckets.ASSETS_BUCKET)


def InstrumentedAssetMixinFactory(acl_name, acr_name):
    class AssetMixin(BaseAssetMixin):
        # optional comment
        comment = db.Column(db.Text())

        # is this asset stored encrypted?
        encryption = db.Column(
            db.Integer(), nullable=False, default=encryptions.ENCRYPTION_NONE
        )

        # file size after encryption
        encrypted_size = db.Column(db.Integer())

        # store nonce, if needed. Ensure it is marked as unique, both because it should be,
        # and also to generate an index (we need to check to ensure nonces are not reused)
        nonce = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=True, unique=True)

        # is this asset stored compressed within the object store?
        compressed = db.Column(db.Boolean(), nullable=False, default=False)

        # file size after compression
        compressed_size = db.Column(db.Integer())

        # access control list: which users are authorized to view or download this file?
        @declared_attr
        def access_control_list(self):
            return db.relationship("User", secondary=acl_name, lazy="dynamic")

        @declared_attr
        def access_control_roles(self):
            return db.relationship("Role", secondary=acr_name, lazy="dynamic")

        def _get_userid(self, user):
            from .users import User

            user_obj: User = self._get_user(user)
            return user_obj.id

        def _get_user(self, user):
            from .faculty import FacultyData
            from .students import StudentData
            from .submissions import SubmissionRole
            from .users import User

            # dereference a Werkzeug LocalProxy if needed, eg. if current_user is passed to us
            if hasattr(user, "_get_current_object"):
                user = user._get_current_object()

            if isinstance(user, User):
                user_obj = user
            elif isinstance(user, SubmissionRole):
                user_obj = user.user
            elif isinstance(user, FacultyData):
                user_obj = user.user
            elif isinstance(user, StudentData):
                user_obj = user.user
            elif isinstance(user, int):
                user_obj = db.session.query(User).filter_by(id=user).first()
            else:
                raise RuntimeError(
                    f'Unrecognized object "{user}" of type "{type(user)}" passed to AssetMixin._get_user()'
                )

            return user_obj

        def _get_roleid(self, role):
            from .users import Role

            role_obj: Role = self._get_role(role)
            return role_obj.id

        def _get_role(self, role):
            from .users import Role

            if isinstance(role, Role):
                role_obj = role
            elif isinstance(role, str):
                role_obj = db.session.query(Role).filter_by(name=role).first()
            elif isinstance(role, int):
                role_obj = db.session.query(Role).filter_by(id=role).first()
            else:
                raise RuntimeError(
                    f'Unrecognized object "{role}" of type "{type(role)}" passed to AssetMixin._get_role()'
                )

            return role_obj

        def has_access(self, user):
            user_id = self._get_userid(user)

            if self.has_role_access(user_id):
                return True

            return self.in_user_acl(user)

        def has_role_access(self, user):
            user_obj = self._get_user(user)

            # admin and root users always have access
            if user_obj.has_role("root") or user_obj.has_role("admin"):
                return True

            # test whether current user has any other roles in access_control_roles
            for role in self.access_control_roles:
                if user_obj.has_role(role):
                    return True

            return False

        def get_eligible_roles(self, user):
            from .users import Role

            user_obj = self._get_user(user)

            role_list = []

            key_roles = (
                db.session.query(Role)
                .filter(or_(Role.name == "root", Role.name == "admin"))
                .all()
            )

            for r in key_roles:
                if user_obj.has_role(r) and r not in role_list:
                    role_list.append(r)

            for r in self.access_control_roles:
                if user_obj.has_role(r) and r not in role_list:
                    role_list.append(r)

            return role_list

        def in_user_acl(self, user):
            user_id = self._get_userid(user)

            return get_count(self.access_control_list.filter_by(id=user_id)) > 0

        def in_role_acl(self, role):
            role_id = self._get_roleid(role)

            return get_count(self.access_control_roles.filter_by(id=role_id)) > 0

        def grant_user(self, user):
            user_obj = self._get_user(user)

            if user_obj is not None and user_obj not in self.access_control_list:
                self.access_control_list.append(user_obj)

        def revoke_user(self, user):
            user_obj = self._get_user(user)

            if user_obj is not None:
                while user_obj in self.access_control_list:
                    self.access_control_list.remove(user_obj)

        def grant_role(self, role):
            role_obj = self._get_role(role)

            if role_obj is not None and role_obj not in self.access_control_roles:
                self.access_control_roles.append(role_obj)

        def revoke_role(self, role):
            role_obj = self._get_role(role)

            if role_obj is not None:
                while role_obj in self.access_control_roles:
                    self.access_control_roles.remove(role_obj)

        def grant_roles(self, roles):
            if not isinstance(roles, Iterable):
                return self.grant_role(roles)

            for role in roles:
                self.grant_role(role)

        def revoke_roles(self, roles):
            if not isinstance(roles, Iterable):
                return self.revoke_role(roles)

            for role in roles:
                self.revoke_role(role)

        @property
        def human_file_size(self):
            if self.filesize is None or self.filesize < 0:
                return "None"

            return humanize.naturalsize(self.filesize)

    return AssetMixin


class StudentLevelsMixin:
    """
    StudentLeveLMixin encapsulates common programme level indicators; we only want to have one copy of these,
    in order to ensure consistency between different places where they are used in the implmentation
    """

    LEVEL_UG = 0
    LEVEL_PGT = 1
    LEVEL_PGR = 2

    _level_text_map = {LEVEL_UG: "UG", LEVEL_PGT: "PGT", LEVEL_PGR: "PGR"}

    def _level_text(self, level: int):
        if level in self._level_text_map:
            return self._level_text_map[level]

        return "Unknown"


class AutoEnrolMixin:
    """
    AutoEnrollMixin encapsulates common auto-enroll choices; we only want a single place where these are
    defined
    """

    AUTO_ENROLL_FIRST_YEAR = 0
    AUTO_ENROLL_ALL_YEARS = 1


class RepeatIntervalsMixin:
    """
    Single point of definition for task repeat intervals
    """

    REPEAT_DAILY = 0
    REPEAT_MONTHLY = 1
    REPEAT_YEARLY = 2


class EmailNotificationsMixin:
    """
    Single point of definition for email notification types
    """

    CONFIRMATION_REQUEST_CREATED = 0
    CONFIRMATION_REQUEST_CANCELLED = 1

    CONFIRMATION_REQUEST_DELETED = 2
    CONFIRMATION_GRANT_DELETED = 3
    CONFIRMATION_DECLINE_DELETED = 4
    CONFIRMATION_GRANTED = 5
    CONFIRMATION_DECLINED = 6
    CONFIRMATION_TO_PENDING = 7

    FACULTY_REENROLL_SUPERVISOR = 8
    FACULTY_REENROLL_MARKER = 9
    FACULTY_REENROLL_PRESENTATIONS = 10
    FACULTY_REENROLL_MODERATOR = 11

    _events = {
        CONFIRMATION_REQUEST_CREATED: ("primary", "Create confirm request"),
        CONFIRMATION_REQUEST_CANCELLED: ("danger", "Confirm request cancel"),
        CONFIRMATION_REQUEST_DELETED: ("danger", "Confirm request deleted"),
        CONFIRMATION_GRANT_DELETED: ("warning", "Confirmation deleted"),
        CONFIRMATION_DECLINE_DELETED: ("secondary", "Confirm decline deleted"),
        CONFIRMATION_GRANTED: ("success", "Confirm granted"),
        CONFIRMATION_DECLINED: ("ddanger", "Confirm declined"),
        CONFIRMATION_TO_PENDING: ("secondary", "Confirm request pending"),
        FACULTY_REENROLL_SUPERVISOR: ("secondary", "Re-enrol as supervisor"),
        FACULTY_REENROLL_MARKER: ("secondary", "Re-enrol as marker"),
        FACULTY_REENROLL_MODERATOR: ("secondary", "Re-enrol as moderator"),
        FACULTY_REENROLL_PRESENTATIONS: ("secondary", "Re-enrol as assessor"),
    }


class SelectorLifecycleStatesMixin:
    """
    Single point of definition for selector lifecycle states
    """

    SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED = 1
    SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS = 2
    SELECTOR_LIFECYCLE_READY_GOLIVE = 3
    SELECTOR_LIFECYCLE_SELECTIONS_OPEN = 4
    SELECTOR_LIFECYCLE_READY_MATCHING = 5
    SELECTOR_LIFECYCLE_READY_ROLLOVER = 6


class SubmitterLifecycleStatesMixin:
    """
    Single point of definition for submitter lifecycle states
    """

    SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY = 0
    SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY = 1
    SUBMITTER_LIFECYCLE_READY_ROLLOVER = 2


class ProjectApprovalStatesMixin:
    """
    Single point of definition for project approvals workflow states
    """

    DESCRIPTIONS_APPROVED = 0
    SOME_DESCRIPTIONS_QUEUED = 1
    SOME_DESCRIPTIONS_REJECTED = 2
    SOME_DESCRIPTIONS_UNCONFIRMED = 3
    APPROVALS_NOT_ACTIVE = 10
    APPROVALS_NOT_OFFERABLE = 11
    APPROVALS_UNKNOWN = 100


class ApprovalCommentVisibilityStatesMixin:
    """
    Single point of definition for visibility states associated with approvals comments
    """

    VISIBILITY_EVERYONE = 0
    VISIBILITY_APPROVALS_TEAM = 1
    VISIBILITY_PUBLISHED_BY_APPROVALS = 2


class ConfirmRequestStatesMixin:
    """
    Single point of definition for confirmation states associated with student requests
    """

    REQUESTED = 0
    CONFIRMED = 1
    DECLINED = 2

    _values = {"requested": REQUESTED, "confirmed": CONFIRMED}


class SubmissionFeedbackStatesMixin:
    """
    Single point of definition for workflow states associated with submission feedback
    """

    FEEDBACK_NOT_REQUIRED = 0
    FEEDBACK_NOT_YET = 1
    FEEDBACK_WAITING = 2
    FEEDBACK_ENTERED = 3
    FEEDBACK_LATE = 4
    FEEDBACK_SUBMITTED = 5


class SubmissionAttachmentTypesMixin:
    """
    Single point of definition for attachment types that can be associated with submissions
    """

    ATTACHMENT_TYPE_UNSET = 0
    ATTACHMENT_MARKING_REPORT = 1
    ATTACHMENT_SIMILARITY_REPORT = 2
    ATTACHMENT_FEEDBACK_DOCUMENT = 4
    ATTACHMENT_OTHER = 3

    _labels = {
        ATTACHMENT_TYPE_UNSET: "Unset",
        ATTACHMENT_MARKING_REPORT: "Marking report",
        ATTACHMENT_SIMILARITY_REPORT: "Similarity report",
        ATTACHMENT_FEEDBACK_DOCUMENT: "Feedback document",
        ATTACHMENT_OTHER: "Other",
    }

    # ATTACHMENT TYPE
    type = db.Column(db.Integer(), default=0, nullable=True)

    def type_label(self):
        if self.type is None:
            return None

        if self.type in self._labels:
            return self._labels[self.type]

        return None


class SelectHintTypesMixin:
    """
    Single point of definition for hint types associated with student selections
    """

    SELECTION_HINT_NEUTRAL = 0
    SELECTION_HINT_REQUIRE = 1
    SELECTION_HINT_FORBID = 2
    SELECTION_HINT_ENCOURAGE = 3
    SELECTION_HINT_DISCOURAGE = 4
    SELECTION_HINT_ENCOURAGE_STRONG = 5
    SELECTION_HINT_DISCOURAGE_STRONG = 6

    _icons = {
        SELECTION_HINT_NEUTRAL: "",
        SELECTION_HINT_REQUIRE: "check-circle",
        SELECTION_HINT_FORBID: "times-circle",
        SELECTION_HINT_ENCOURAGE: "plus",
        SELECTION_HINT_DISCOURAGE: "minus",
        SELECTION_HINT_ENCOURAGE_STRONG: "plus-circle",
        SELECTION_HINT_DISCOURAGE_STRONG: "minus-circle",
    }

    _menu_items = {
        SELECTION_HINT_NEUTRAL: "Neutral",
        SELECTION_HINT_REQUIRE: "Require",
        SELECTION_HINT_FORBID: "Forbid",
        SELECTION_HINT_ENCOURAGE: "Encourage",
        SELECTION_HINT_DISCOURAGE: "Discourage",
        SELECTION_HINT_ENCOURAGE_STRONG: "Strongly encourage",
        SELECTION_HINT_DISCOURAGE_STRONG: "Strongly discourage",
    }

    _menu_order = [
        SELECTION_HINT_NEUTRAL,
        "Force fit",
        SELECTION_HINT_REQUIRE,
        SELECTION_HINT_FORBID,
        "Fitting hints",
        SELECTION_HINT_ENCOURAGE,
        SELECTION_HINT_DISCOURAGE,
        SELECTION_HINT_ENCOURAGE_STRONG,
        SELECTION_HINT_DISCOURAGE_STRONG,
    ]


class CustomOfferStatesMixin:
    """
    Single point of definition for states associated with custom offers
    """

    OFFERED = 0
    ACCEPTED = 1
    DECLINED = 2


class TaskWorkflowStatesMixin:
    """
    Single point of definition for workflow states associated with background/scheduled tasks
    """

    PENDING = 0
    RUNNING = 1
    SUCCESS = 2
    FAILURE = 3
    TERMINATED = 4
    STATES = {
        PENDING: "PENDING",
        RUNNING: "RUNNING",
        SUCCESS: "SUCCESS",
        FAILURE: "FAILURE",
        TERMINATED: "TERMINATED",
    }


class NotificationTypesMixin:
    """
    Single point of definition for live notifications on the website
    """

    TASK_PROGRESS = 1
    USER_MESSAGE = 2
    SHOW_HIDE_REQUEST = 100
    REPLACE_TEXT_REQUEST = 101
    RELOAD_PAGE_REQUEST = 102


class PuLPStatusMixin:
    """
    Single point of definition for PuLP status/outcome types
    """

    # outcome report from PuLP
    OUTCOME_OPTIMAL = 0
    OUTCOME_NOT_SOLVED = 1
    OUTCOME_INFEASIBLE = 2
    OUTCOME_UNBOUNDED = 3
    OUTCOME_UNDEFINED = 4
    OUTCOME_FEASIBLE = 5

    SOLVER_CBC_PACKAGED = 0
    SOLVER_CBC_CMD = 1
    SOLVER_GLPK_CMD = 2
    SOLVER_CPLEX_CMD = 3
    SOLVER_GUROBI_CMD = 4
    SOLVER_SCIP_CMD = 5

    # solver names
    _solvers = {
        SOLVER_CBC_PACKAGED: "PuLP-packaged CBC",
        SOLVER_CBC_CMD: "CBC external",
        SOLVER_GLPK_CMD: "GLPK external",
        SOLVER_CPLEX_CMD: "CPLEX external",
        SOLVER_GUROBI_CMD: "Gurobi external",
        SOLVER_SCIP_CMD: "SCIP external",
    }


class AvailabilityRequestStateMixin:
    """
    Single point of definition for availability request states
    """

    AVAILABILITY_NOT_REQUESTED = 0
    AVAILABILITY_REQUESTED = 1
    AVAILABILITY_CLOSED = 2

    AVAILABILITY_SKIPPED = 10


class PresentationSessionTypesMixin:
    """
    Single point of definition for presentation session types
    """

    MORNING_SESSION = 0
    AFTERNOON_SESSION = 1

    SESSION_TO_TEXT = {MORNING_SESSION: "morning", AFTERNOON_SESSION: "afternoon"}


class ScheduleEnumerationTypesMixin:
    """
    Single point of definition for schedule enumeration types
    """

    ASSESSOR = 0
    SUBMITTER = 1
    SLOT = 2
    PERIOD = 3


class MatchingEnumerationTypesMixin:
    """
    Single point of definition for matching enumeration types
    """

    SELECTOR = 0
    LIVEPROJECT = 1
    LIVEPROJECT_GROUP = 2
    SUPERVISOR = 3
    MARKER = 4
    SUPERVISOR_LIMITS = 5
    MARKER_LIMITS = 6


class ProjectMeetingChoicesMixin:
    """
    Single point of definition for choices
    """

    MEETING_REQUIRED = 1
    MEETING_OPTIONAL = 2
    MEETING_NONE = 3

    MEETING_OPTIONS = [
        (MEETING_REQUIRED, "Meeting required"),
        (MEETING_OPTIONAL, "Meeting optional"),
        (MEETING_NONE, "Prefer not to meet"),
    ]


class SubmissionRoleTypesMixin:
    """
    Single point of definition for staff roles associated with a SubmissionRecord
    """

    ROLE_SUPERVISOR = 0
    ROLE_MARKER = 1
    ROLE_PRESENTATION_ASSESSOR = 2
    ROLE_MODERATOR = 3
    ROLE_EXAM_BOARD = 4
    ROLE_EXTERNAL_EXAMINER = 5
    ROLE_RESPONSIBLE_SUPERVISOR = 6

    _MIN_ROLE = ROLE_SUPERVISOR
    _MAX_ROLE = ROLE_RESPONSIBLE_SUPERVISOR

    _role_string = {
        ROLE_SUPERVISOR: "Supervisor",
        ROLE_MARKER: "Marker",
        ROLE_PRESENTATION_ASSESSOR: "Assessor",
        ROLE_MODERATOR: "Moderator",
        ROLE_EXAM_BOARD: "Exam board",
        ROLE_EXTERNAL_EXAMINER: "External",
        ROLE_RESPONSIBLE_SUPERVISOR: "Responsible supervisor",
    }

    _role_id = {
        ROLE_SUPERVISOR: "supervisor",
        ROLE_MARKER: "marker",
        ROLE_PRESENTATION_ASSESSOR: "presentation_assessor",
        ROLE_MODERATOR: "moderator",
        ROLE_EXAM_BOARD: "exam_board",
        ROLE_EXTERNAL_EXAMINER: "external_examiner",
        ROLE_RESPONSIBLE_SUPERVISOR: "responsible_supervisor",
    }

    role_choices = [
        (ROLE_RESPONSIBLE_SUPERVISOR, "Responsible supervisor"),
        (ROLE_SUPERVISOR, "Supervisor"),
        (ROLE_MARKER, "Marker"),
        (ROLE_PRESENTATION_ASSESSOR, "Presentation assessor"),
        (ROLE_MODERATOR, "Moderator"),
        (ROLE_EXAM_BOARD, "Exam board member"),
        (ROLE_EXTERNAL_EXAMINER, "External examiner"),
    ]


class BackupTypesMixin:
    # type of backup
    SCHEDULED_BACKUP = 1
    PROJECT_ROLLOVER_FALLBACK = 2
    PROJECT_GOLIVE_FALLBACK = 3
    PROJECT_CLOSE_FALLBACK = 4
    PROJECT_ISSUE_CONFIRM_FALLBACK = 5
    BATCH_STUDENT_IMPORT_FALLBACK = 6
    MANUAL_BACKUP = 7
    BATCH_FACULTY_IMPORT_FALLBACK = 8

    _type_index = {
        SCHEDULED_BACKUP: "Scheduled backup",
        PROJECT_ROLLOVER_FALLBACK: "Rollover restore point",
        PROJECT_GOLIVE_FALLBACK: "Go Live restore point",
        PROJECT_CLOSE_FALLBACK: "Close selection restore point",
        PROJECT_ISSUE_CONFIRM_FALLBACK: "Issue confirmation requests restore point",
        BATCH_STUDENT_IMPORT_FALLBACK: "Batch student creation restore point",
        MANUAL_BACKUP: "Manual backup",
        BATCH_FACULTY_IMPORT_FALLBACK: "Batch faculty import restore point",
    }


class AlternativesPriorityMixin:
    HIGHEST_PRIORITY = 1
    LOWEST_PRIORIY = 10

    # priority for this alternative
    priority = db.Column(db.Integer(), default=HIGHEST_PRIORITY)

    @validates("priority")
    def _validate_priority(self, key, value):
        if value < self.HIGHEST_PRIORITY:
            return self.HIGHEST_PRIORITY

        if value > self.LOWEST_PRIORIY:
            return self.LOWEST_PRIORIY

        return value


class SupervisionEventTypesMixin:
    """
    Single point of definition for supervision event types
    """

    EVENT_ONE_TO_ONE_MEETING = 0
    EVENT_GROUP_MEETING = 1

    _MIN_TYPE = EVENT_ONE_TO_ONE_MEETING
    _MAX_TYPE = EVENT_GROUP_MEETING

    _event_string = {
        EVENT_ONE_TO_ONE_MEETING: "1-to-1 meeting",
        EVENT_GROUP_MEETING: "Group meeting",
    }

    _short_event_string = {
        EVENT_ONE_TO_ONE_MEETING: "1-to-1",
        EVENT_GROUP_MEETING: "Group",
    }

    event_options = [
        (EVENT_ONE_TO_ONE_MEETING, "1-to-1 meeting"),
        (EVENT_GROUP_MEETING, "Group meeting"),
    ]


class SupervisionEventAttendanceMixin:
    """
    Single point of definition for supervision event attendance states
    """

    ATTENDANCE_ON_TIME = 0
    ATTENDANCE_LATE = 1
    ATTENDANCE_NO_SHOW_NOTIFIED = 2
    ATTENDANCE_NO_SHOW_UNNOTIFIED = 3
    ATTENDANCE_RESCHEDULED = 4

    _MIN_ATTENDANCE = ATTENDANCE_ON_TIME
    _MAX_ATTANDANCE = ATTENDANCE_RESCHEDULED

    _attendance_labels = {
        ATTENDANCE_ON_TIME: "The meeting started on time",
        ATTENDANCE_LATE: "The meeting started late",
        ATTENDANCE_NO_SHOW_NOTIFIED: "The student did not attend, but I was notified in advance",
        ATTENDANCE_NO_SHOW_UNNOTIFIED: "The student did not attend, and I was not notified in advance",
        ATTENDANCE_RESCHEDULED: "This meeting was rescheduled",
    }

    _attendance_string = {
        ATTENDANCE_ON_TIME: "Started on time",
        ATTENDANCE_LATE: "Started late",
        ATTENDANCE_NO_SHOW_NOTIFIED: "No-show (notified)",
        ATTENDANCE_NO_SHOW_UNNOTIFIED: "No-show (not notified)",
        ATTENDANCE_RESCHEDULED: "Rescheduled",
    }

    attendance_menu = [
        (ATTENDANCE_ON_TIME, "Started on time"),
        (ATTENDANCE_LATE, "Started late"),
        (ATTENDANCE_NO_SHOW_NOTIFIED, "No-show (notified)"),
        (ATTENDANCE_NO_SHOW_UNNOTIFIED, "No-show (not notified)"),
        (ATTENDANCE_RESCHEDULED, "Rescheduled"),
    ]

    @classmethod
    def attendance_valid(cls, attendance):
        if cls._MIN_ATTENDANCE <= attendance <= cls._MAX_ATTANDANCE:
            return True

        return False


class AssessorPoolChoicesMixin:
    """
    Single point of definition for assessor pool choices used during assessment scheduling
    """

    AT_LEAST_ONE_IN_POOL = 0
    ALL_IN_POOL = 1
    ALL_IN_RESEARCH_GROUP = 2
    AT_LEAST_ONE_IN_RESEARCH_GROUP = 3

    ASSESSOR_CHOICES = [
        (
            AT_LEAST_ONE_IN_POOL,
            "For each talk, at least one assessor should belong to its assessor pool",
        ),
        (
            AT_LEAST_ONE_IN_RESEARCH_GROUP,
            "For each talk, at least one assessor should belong to its assessor pool or affiliation/research group",
        ),
        (
            ALL_IN_POOL,
            "For every talk, each assessor should belong to its assessor pool",
        ),
        (
            ALL_IN_RESEARCH_GROUP,
            "For every talk, each assessor should belong to its assessor pool or affiliation/research group",
        ),
    ]


# roll our own get_main_config() and get_current_year(), which we cannot import because it creates a dependency cycle
def _get_main_config():
    from .utilities import MainConfig

    return db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()


def _get_current_year():
    return _get_main_config().year
