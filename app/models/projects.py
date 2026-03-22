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
from typing import Optional

from flask import current_app
from flask_security import current_user
from sqlalchemy import orm
from sqlalchemy.event import listens_for
from sqlalchemy.orm import validates

from ..cache import cache
from ..database import db
from ..shared.sqlalchemy import get_count
from .associations import (
    description_pclasses,
    description_supervisors,
    description_to_modules,
    project_assessors,
    project_pclasses,
    project_programmes,
    project_skills,
    project_supervisors,
    project_tags,
    tenant_to_project_tag_groups,
)
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import (
    AlternativesPriorityMixin,
    ApprovalCommentVisibilityStatesMixin,
    ColouredLabelMixin,
    EditingMetadataMixin,
    ProjectApprovalStatesMixin,
    ProjectConfigurationMixinFactory,
    ProjectDescriptionMixinFactory,
    WorkflowHistoryMixin,
    WorkflowMixin,
    _get_current_year,
)


class ProjectDescriptionWorkflowHistory(db.Model, WorkflowHistoryMixin):
    __tablename__ = "workflow_project"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # owning studentdata instance
    owner_id = db.Column(db.Integer(), db.ForeignKey("descriptions.id"))
    owner = db.relationship(
        "ProjectDescription",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref("workflow_history", lazy="dynamic"),
    )


class ProjectTagGroup(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Normalize a set of tag groups, used to collect tags applied to projects.
    If desired, project classes can be set to allow tags only from specific groups.
    """

    __tablename__ = "project_tag_groups"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # tenants to which this tag group belongs
    tenants = db.relationship(
        "Tenant",
        secondary=tenant_to_project_tag_groups,
        lazy="dynamic",
        backref=db.backref("project_tag_groups", lazy="dynamic"),
    )

    # name of tag group
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # active flag
    active = db.Column(db.Boolean(), default=True)

    # add group name to labels
    add_group = db.Column(db.Boolean())

    # default group for new tags?
    default = db.Column(db.Boolean(), default=False)

    def _make_label(self):
        return super()._make_label(text=self.name)

    def enable(self):
        """
        Activate this tag group and cascade, i.e., enable any tags associated with this group
        :return:
        """
        self.active = True

        # should not steal the default from any existing default group
        self.default = False

        for tag in self.tags:
            tag.enable()

    def disable(self):
        """
        Deactivate this tag group and cascade, i.e., disable any tags associated with this group
        :return:
        """
        self.active = False

        # for safety, ensure default field is false; this should be true anyway
        self.default = False

        for tag in self.tags:
            tag.disable()


class ProjectTag(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Normalize a tag that can be attached to a project
    """

    __tablename__ = "project_tags"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name of tag
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # group that this tag belongs to
    group_id = db.Column(db.Integer(), db.ForeignKey("project_tag_groups.id"))
    group = db.relationship(
        "ProjectTagGroup",
        foreign_keys=[group_id],
        uselist=False,
        backref=db.backref("tags", lazy="dynamic"),
    )

    # active flag
    active = db.Column(db.Boolean(), default=True)

    @property
    def display_name(self):
        if self.group is not None and self.group.add_group:
            return "{group}: {tag}".format(group=self.group.name, tag=self.name)

        return self.name

    def make_label(self, text=None):
        label_text = text if text is not None else self.display_name

        return self._make_label(text=label_text)

    @property
    def is_active(self):
        if self.group is None:
            return self.active

        return self.active and self.group.active

    def enable(self):
        """
        Activate this tag
        :return:
        """
        self.active = True

    def disable(self):
        """
        Deactivate this tag
        :return:
        """
        self.active = False

    @property
    def uses(self):
        return {
            "Projects": get_count(self.projects),
            "Live Projects": get_count(self.live_projects),
        }


@cache.memoize()
def _Project_is_offerable(pid):
    """
    Determine whether a given Project instance is offerable.
    Must be implemented as a simple function to work well with Flask-Caching.
    This is quite annoying but there seems no reliable workaround, and we can't live without caching.
    :param pid:
    :return:
    """
    from .project_class import ProjectClass

    project: Project = db.session.query(Project).filter_by(id=pid).one()

    errors = {}
    warnings = {}

    # CONSTRAINT 1. At least one assigned project class should be active
    if get_count(project.project_classes.filter(ProjectClass.active)) == 0:
        errors["pclass"] = "No active project types assigned to project"

    # CONSTRAINT 2. The affiliated research group should be active, if this project is attached to any
    # classes that uses research groups
    if project.generic or project.group is None:
        if (
            get_count(
                project.project_classes.filter(ProjectClass.advertise_research_group)
            )
            > 0
        ):
            errors["groups"] = (
                "No affiliation or research group associated with project"
            )

    else:
        if not project.group.active:
            errors["groups"] = (
                "The project's assigned affiliation or research group is not active"
            )

    # CONSTRAINT 3.
    # -- A. For each attached project class, we should have enough assessors.
    # -- B. Also, there should be a project description
    # -- C. If there are required tag groups, at least one such tag must be supplied
    for pclass in project.project_classes:
        pclass: ProjectClass
        # A
        if (
            pclass.uses_marker
            and pclass.number_assessors is not None
            and project.number_assessors(pclass) < pclass.number_assessors
        ):
            errors[("pclass-assessors", pclass.id)] = (
                f"Too few assessors assigned for '{pclass.name}'"
            )

        # B
        desc = project.get_description(pclass)
        if desc is None:
            errors[("pclass-descriptions", pclass.id)] = (
                f"No project description assigned for '{pclass.name}'"
            )

        # C
        for group in pclass.force_tag_groups:
            group: ProjectTagGroup

            query = project.tags.filter(
                ProjectTag.group_id == group.id,
            )
            count = get_count(query)
            if count == 0:
                errors[("pclass-tags", pclass.id)] = (
                    f"{pclass.name} requires at least one tag to be assigned from the group '{group.name}'"
                )

    # CONSTRAINT 4. All attached project descriptions should validate individually
    for desc in project.descriptions:
        if desc.has_issues:
            if not desc.is_valid:
                errors[("descriptions", desc.id)] = (
                    f'Variant "{desc.label}" has validation errors'
                )
            else:
                warnings[("descriptions", desc.id)] = (
                    f'Variant "{desc.label}" has validation warnings'
                )

    # CONSTRAINT 5. For Generic projects, there should be a nonempty supervisor pool
    if project.generic:
        for pclass in project.project_classes:
            if project.number_supervisors(pclass) == 0:
                errors[("supervisors", pclass.id)] = (
                    f'There are no supervisors in the generic pool for "{pclass.name}"'
                )

    # CONSTRAINT 6. The ATAS restricted flag has to be set
    if any([p.enforce_ATAS for p in project.project_classes]):
        if project.ATAS_restricted is None:
            errors["ATAS"] = (
                f'The ATAS-restricted option has not been set, but "{pclass.name}" enforces ATAS restrictions'
            )

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


@cache.memoize()
def _Project_num_assessors(pid, pclass_id):
    project = db.session.query(Project).filter_by(id=pid).one()
    return get_count(project.assessor_list_query(pclass_id))


@cache.memoize()
def _Project_num_supervisors(pid, pclass_id):
    project = db.session.query(Project).filter_by(id=pid).one()
    return get_count(project.supervisor_list_query(pclass_id))


class Project(
    db.Model,
    EditingMetadataMixin,
    ProjectApprovalStatesMixin,
    ProjectConfigurationMixinFactory(
        backref_label="projects",
        force_unique_names="unique",
        skills_mapping_table=project_skills,
        skills_mapped_column=project_skills.c.skill_id,
        skills_self_column=project_skills.c.project_id,
        allow_edit_skills="allow",
        programmes_mapping_table=project_programmes,
        programmes_mapped_column=project_programmes.c.programme_id,
        programmes_self_column=project_programmes.c.project_id,
        allow_edit_programmes="allow",
        tags_mapping_table=project_tags,
        tags_mapped_column=project_tags.c.tag_id,
        tags_self_column=project_tags.c.project_id,
        allow_edit_tags="allow",
        assessor_mapping_table=project_assessors,
        assessor_mapped_column=project_assessors.c.faculty_id,
        assessor_self_column=project_assessors.c.project_id,
        assessor_backref_label="assessor_for",
        allow_edit_assessors="allow",
        supervisor_mapping_table=project_supervisors,
        supervisor_mapped_column=project_supervisors.c.faculty_id,
        supervisor_self_column=project_supervisors.c.project_id,
        supervisor_backref_label="supervisor_for",
        allow_edit_supervisors="allow",
    ),
):
    """
    Model a project
    """

    # make table name plural
    __tablename__ = "projects"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # active flag
    active = db.Column(db.Boolean())

    # which project classes are associated with this description?
    project_classes = db.relationship(
        "ProjectClass",
        secondary=project_pclasses,
        lazy="dynamic",
        backref=db.backref("projects", lazy="dynamic"),
    )

    # test if at least one project class to which we are attached is published
    @property
    def has_published_pclass(self):
        return self.project_classes.filter_by(publish=True).first() is not None

    @property
    def forced_group_tags(self):
        tags = set()
        for pcl in self.project_classes:
            for group in pcl.force_tag_groups:
                assigned_tags = self.tags.filter_by(group_id=group.id).all()
                for tag in assigned_tags:
                    tags.add(tag)

        return tags

    # tags, group_id and skills inherited from ProjectConfigurationMixin
    @validates("tags", "group_id", "skills", include_removes=True)
    def _tags_validate(self, key, value, is_remove):
        with db.session.no_autoflush:
            for desc in self.descriptions:
                desc.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
                desc.confirmed = False

        return value

    # meeting_reqd inherited from ProjectConfigurationMixin
    @validates("meeting_reqd")
    def _selection_validate(self, key, value):
        with db.session.no_autoflush:
            for desc in self.descriptions:
                desc.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
                desc.confirmed = False

        return value

    # enforce_capacity and assessors inherited from ProjectConfigurationMixin
    @validates("enforce_capacity", "assessors", include_removes=True)
    def _matching_validate(self, key, value, is_remove):
        with db.session.no_autoflush:
            for desc in self.descriptions:
                desc.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
                desc.confirmed = False

        return value

    # dont_clash_presentations inherited from ProjectConfigurationMixin
    @validates("dont_clash_presentations")
    def _settings_validate(self, key, value):
        with db.session.no_autoflush:
            for desc in self.descriptions:
                desc.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
                desc.confirmed = False

        return value

    # PROJECT DESCRIPTION

    # 'descriptions' field is established by backreference from ProjectDescription
    # (this works well but is a bit awkward because it creates a circular dependency between
    # Project and ProjectDescription which we solve using the SQLAlchemy post_update option)

    # link to default description, if one exists
    default_id = db.Column(
        db.Integer(), db.ForeignKey("descriptions.id", use_alter=True)
    )
    default = db.relationship(
        "ProjectDescription",
        foreign_keys=[default_id],
        uselist=False,
        post_update=True,
        backref=db.backref("default", uselist=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = {}
        self._warnings = {}

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = {}
        self._warnings = {}

    @property
    def show_popularity_data(self):
        return False

    def disable(self):
        """
        Disable this project
        :return:
        """
        self.active = False

    def enable(self):
        """
        Enable this project
        :return:
        """
        self.active = True

    def remove_project_class(self, pclass):
        """
        Remove ourselves from a given pclass, and cascade to our attached descriptions
        :param pclass:
        :return:
        """
        if pclass not in self.project_classes:
            return

        for desc in self.descriptions:
            desc: ProjectDescription
            desc.remove_project_class(pclass)

        self.project_classes.remove(pclass)

    @property
    def is_offerable(self):
        """
        Determine whether this project is available for selection
        :return:
        """
        flag, self._errors, self._warnings = _Project_is_offerable(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_offerable
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def errors(self):
        if not self._validated:
            check = self.is_offerable
        return self._errors.values()

    @property
    def warnings(self):
        if not self._validated:
            check = self.is_offerable
        return self._warnings.values()

    def mark_confirmed(self, pclass):
        desc = self.get_description(pclass)

        if desc is None:
            return

        if not desc.confirmed:
            desc.confirmed = True

    @property
    def is_deletable(self):
        return get_count(self.live_projects) == 0

    @property
    def available_degree_programmes(self):
        """
        Computes the degree programmes available to this project, from knowing which project
        classes it is available to
        :param data:
        :return:
        """
        from .academic import DegreeProgramme

        # get list of active degree programmes relevant for our degree classes;
        # to do this we have to build a rather complex UNION query
        queries = []
        for proj_class in self.project_classes:
            queries.append(
                DegreeProgramme.query.filter(
                    DegreeProgramme.active,
                    DegreeProgramme.project_classes.any(id=proj_class.id),
                )
            )

        if len(queries) > 0:
            q = queries[0]
            for query in queries[1:]:
                q = q.union(query)
        else:
            q = None

        return q

    def validate_programmes(self):
        """
        Check that the degree programmes associated with this project
        are valid, given the current project class associations
        :return:
        """
        available_programmes = self.available_degree_programmes
        if available_programmes is None:
            self.programmes = []
            return

        for prog in self.programmes:
            if prog not in available_programmes:
                self.remove_programme(prog)

    def assessor_list_query(self, pclass):
        return super()._assessor_list_query(pclass)

    def is_assessor(self, faculty_id):
        """
        Determine whether a given FacultyData instance is an assessor for this project
        :param faculty:
        :return:
        """
        return get_count(
            self.assessors.filter_by(id=faculty_id)
        ) > 0 and self._is_assessor_for_at_least_one_pclass(faculty_id)

    def number_assessors(self, pclass):
        """
        Determine the number of assessors enrolled who are available for a given project class
        :param pclass:
        :return:
        """
        return _Project_num_assessors(self.id, pclass.id)

    def get_assessor_list(self, pclass):
        """
        Build a list of FacultyData objects for assessors attached to this project who are
        available for a given project class
        :param pclass:
        :return:
        """
        return self.assessor_list_query(pclass).all()

    def can_enroll_assessor(self, faculty):
        """
        Determine whether a given FacultyData instance can be enrolled as an assessor for this project
        :param faculty:
        :return:
        """
        if self.is_assessor(faculty.id):
            return False

        if not faculty.user.active:
            return False

        # determine whether this faculty member is enrolled as a second marker for any project
        # class we are attached to
        return self._is_assessor_for_at_least_one_pclass(faculty)

    def supervisor_list_query(self, pclass):
        return super()._supervisor_list_query(pclass)

    def is_supervisor(self, faculty_id):
        """
        Determine whether a given FacultyData instance is a supervisor for this project
        :param faculty:
        :return:
        """
        return get_count(
            self.supervisors.filter_by(id=faculty_id)
        ) > 0 and self._is_supervisor_for_at_least_one_pclass(faculty_id)

    def number_supervisors(self, pclass: Optional = None):
        """
        Determine the number of supervisors enrolled who are available for a given project class
        :param pclass:
        :return:
        """
        if pclass is None:
            return get_count(self.supervisors)

        return _Project_num_supervisors(self.id, pclass.id)

    def get_supervisor_list(self, pclass):
        """
        Build a list of FacultyData objects for supervisors attached to this project who are
        available for a given project class
        :param pclass:
        :return:
        """
        return self.supervisor_list_query(pclass).all()

    def can_enroll_supervisor(self, faculty):
        """
        Determine whether a given FacultyData instance can be enrolled as a supervisor for this project
        :param faculty:
        :return:
        """
        if self.is_supervisor(faculty.id):
            return False

        if not faculty.user.active:
            return False

        # determine whether this faculty member is enrolled as a supervisor for any project
        # class we are attached to
        return self._is_supervisor_for_at_least_one_pclass(faculty)

    def get_description(self, pclass):
        """
        Gets the ProjectDescription instance for project class pclass, or returns None if no
        description is available
        :param pclass:
        :return:
        """
        from .project_class import ProjectClass

        if pclass is None:
            return None

        if isinstance(pclass, ProjectClass):
            pclass_id = pclass.id
        elif isinstance(pclass, int):
            pclass_id = pclass
        else:
            raise RuntimeError("Could not interpret pclass argument")

        desc = self.descriptions.filter(
            ProjectDescription.project_classes.any(id=pclass_id)
        ).first()
        if desc is not None:
            return desc

        return self.default

    @property
    def num_descriptions(self):
        return get_count(self.descriptions)

    def selector_live_counterpart(self, config):
        """
        :param config_id: current ProjectClassConfig instance
        :return:
        """
        from .project_class import ProjectClassConfig

        if isinstance(config, int):
            config_id = config
        elif isinstance(config, ProjectClassConfig):
            config_id = config.id
        else:
            raise RuntimeError(
                'Unexpected type for "config" in Project.selector_live_counterpart()'
            )

        return self.live_projects.filter_by(config_id=config_id).first()

    def submitter_live_counterpart(self, cfg):
        from .project_class import ProjectClassConfig

        config: ProjectClassConfig

        if isinstance(cfg, int):
            config = db.session.query(ProjectClassConfig).filter_by(id=cfg).first()
        elif isinstance(cfg, ProjectClassConfig):
            config = cfg
        else:
            raise RuntimeError(
                'Unexpected type for "config" in Project.submitter_live_counterpart()'
            )

        if config is None:
            return None

        if config.select_in_previous_cycle:
            previous_config = config.previous_config
            if previous_config is None:
                return None

            return self.live_projects.filter_by(config_id=previous_config.id).first()

        return self.live_projects.filter_by(config_id=config.id).first()

    def running_counterpart(self, cfg):
        project = self.submitter_live_counterpart(cfg)

        if project is None:
            return None

        if get_count(project.submission_records) == 0:
            return None

        return project

    def update_last_viewed_time(self, user, commit=False):
        # get last view record for this user
        record = self.last_viewing_times.filter_by(user_id=user.id).first()

        if record is None:
            record = LastViewingTime(
                user_id=user.id, project_id=self.id, last_viewed=None
            )
            db.session.add(record)

        record.last_viewed = datetime.now()
        if commit:
            db.session.commit()

    def has_new_comments(self, user):
        # build query to determine most recent comment, ignoring our own
        # (they don't count as new, unread comments)
        query = db.session.query(DescriptionComment.creation_timestamp).filter(
            DescriptionComment.owner_id != user.id
        )

        # if user not in approvals team, ignore any comments that are only visible to the approvals team
        if not user.has_role("project_approver"):
            query = query.filter(
                DescriptionComment.visibility
                != DescriptionComment.VISIBILITY_APPROVALS_TEAM
            )

        query = (
            query.join(
                ProjectDescription,
                ProjectDescription.id == DescriptionComment.parent_id,
            )
            .filter(ProjectDescription.parent_id == self.id)
            .order_by(DescriptionComment.creation_timestamp.desc())
        )

        # get timestamp of most recent comment
        most_recent = query.first()

        if most_recent is None:
            return False

        # get last view record for the specified user
        record = self.last_viewing_times.filter_by(user_id=user.id).first()

        if record is None:
            return True

        return most_recent[0] > record.last_viewed

    @property
    def approval_state(self):
        if not self.active:
            return Project.APPROVALS_NOT_ACTIVE

        if not self.is_offerable:
            return Project.APPROVALS_NOT_OFFERABLE

        num_descriptions = 0
        num_approved = 0

        for d in self.descriptions:
            if d.requires_confirmation and not d.confirmed:
                return Project.SOME_DESCRIPTIONS_UNCONFIRMED

            if d.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED:
                return Project.SOME_DESCRIPTIONS_REJECTED

            if d.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED:
                return Project.SOME_DESCRIPTIONS_QUEUED

            num_descriptions += 1
            if d.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED:
                num_approved += 1

        if num_descriptions == num_approved:
            return Project.DESCRIPTIONS_APPROVED

        return Project.APPROVALS_UNKNOWN

    @property
    def has_alternatives(self) -> bool:
        if self.number_alternatives > 0:
            return True

        return False

    @property
    def number_alternatives(self) -> int:
        return get_count(self.alternatives)

    def maintenance(self):
        """
        Perform regular basic maintenance, to ensure validity of the database
        :return:
        """
        modified = False

        modified = super()._maintenance_assessor_prune() or modified
        modified = super()._maintenance_assessor_remove_duplicates() or modified

        modified = super()._maintenance_supervisor_prune() or modified
        modified = super()._maintenance_supervisor_remove_duplicates() or modified

        return modified


@listens_for(Project, "before_update")
def _Project_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.id)

        for pclass in target.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.id, pclass.id)
            cache.delete_memoized(_Project_num_supervisors, target.id, pclass.id)


@listens_for(Project, "before_insert")
def _Project_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.id)

        for pclass in target.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.id, pclass.id)
            cache.delete_memoized(_Project_num_supervisors, target.id, pclass.id)


@listens_for(Project, "before_delete")
def _Project_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.id)

        for pclass in target.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.id, pclass.id)
            cache.delete_memoized(_Project_num_supervisors, target.id, pclass.id)


class ProjectAlternative(db.Model, AlternativesPriorityMixin):
    """
    Capture alternatives to a given project, with a priority
    """

    __tablename__ = "project_alternatives"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # owning project
    parent_id = db.Column(db.Integer(), db.ForeignKey("projects.id"))
    parent = db.relationship(
        "Project",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref(
            "alternatives", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # alternative project
    alternative_id = db.Column(db.Integer(), db.ForeignKey("projects.id"))
    alternative = db.relationship(
        "Project",
        foreign_keys=[alternative_id],
        uselist=False,
        backref=db.backref("alternative_for", lazy="dynamic"),
    )

    def get_reciprocal(self):
        """
        get reciprocal version of this alternative, if one exists
        :return:
        """
        return (
            db.session.query(ProjectAlternative)
            .filter_by(parent_id=self.alternative_id, alternative_id=self.parent_id)
            .first()
        )

    @property
    def has_reciprocal(self):
        rcp: Optional[ProjectAlternative] = self.get_reciprocal()
        return rcp is not None


@cache.memoize()
def _ProjectDescription_is_valid(id):
    from .faculty import Supervisor

    obj: ProjectDescription = ProjectDescription.query.filter_by(id=id).one()

    errors = {}
    warnings = {}

    # CONSTRAINT 1 - At least one supervisory role must be specified
    if get_count(obj.team.filter(Supervisor.active)) == 0:
        errors["supervisors"] = (
            'No active supervisory roles assigned. Use the "Settings..." menu to specify them.'
        )

    # CONSTRAINT 2 - If parent project enforces capacity limits, a capacity must be specified
    if obj.parent.enforce_capacity:
        if obj.capacity is None or obj.capacity <= 0:
            errors["capacity"] = (
                "Capacity is zero or unset, but enforcement is enabled for "
                'parent project. Use the "Settings..." menu to specify a maximum capacity.'
            )

    # CONSTRAINT 3 - All tagged recommended modules should be valid
    for module in obj.modules:
        if not obj.module_available(module.id):
            errors[("module", module.id)] = (
                'Tagged recommended module "{name}" is not available for this '
                "description".format(name=module.name)
            )

    # CONSTRAINT 4 - Description should be specified
    if obj.description is None or len(obj.description) == 0:
        errors["description"] = (
            'No project description. Use the "Edit content..." menu item to specify it.'
        )

    # CONSTRAINT 5 - Resource should be specified
    if obj.reading is None or len(obj.reading) == 0:
        warnings["reading"] = (
            'No project resources specified. Use the "Edit content..." menu item to add details.'
        )

    # CONSTRAINT 6 - Aims should be specified
    if obj.aims is None or len(obj.aims) == 0:
        warnings["aims"] = (
            'No project aims. Use the "Settings..." menu item to specify them.'
        )

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


class ProjectDescription(
    db.Model,
    EditingMetadataMixin,
    ProjectDescriptionMixinFactory(
        team_mapping_table=description_supervisors,
        team_backref="descriptions",
        module_mapping_table=description_to_modules,
        module_backref="tagged_descriptions",
        module_mapped_column=description_to_modules.c.module_id,
        module_self_column=description_to_modules.c.description_id,
    ),
    WorkflowMixin,
):
    """
    Capture a project description. Projects can have multiple descriptions, each
    attached to a set of project classes
    """

    __tablename__ = "descriptions"

    # which model should we use to generate history records
    __history_model__ = ProjectDescriptionWorkflowHistory

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # CONFIGURATION

    # owning project
    parent_id = db.Column(db.Integer(), db.ForeignKey("projects.id"))
    parent = db.relationship(
        "Project",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref(
            "descriptions", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # which project classes are associated with this description?
    project_classes = db.relationship(
        "ProjectClass",
        secondary=description_pclasses,
        lazy="dynamic",
        backref=db.backref("descriptions", lazy="dynamic"),
    )

    # label
    label = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # probably don't need to include project classes
    @validates("parent_id", "label", include_removes=True)
    def _config_enqueue(self, key, value, is_remove):
        with db.session.no_autoflush:
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
            self.confirmed = False

        return value

    # APPROVALS WORKFLOW

    # has this description been confirmed by the project owner?
    confirmed = db.Column(db.Boolean(), default=False)

    # add 'confirmed by' tag
    confirmed_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    confirmed_by = db.relationship(
        "User",
        foreign_keys=[confirmed_id],
        uselist=False,
        backref=db.backref("confirmed_descriptions", lazy="dynamic"),
    )

    # add confirmation timestamp
    confirmed_timestamp = db.Column(db.DateTime())

    @validates("confirmed")
    def _confirmed_validator(self, key, value):
        with db.session.no_autoflush:
            if value:
                now = datetime.now()

                self.confirmed_id = current_user.id
                self.confirmed_timestamp = now

                if not self.confirmed:
                    history = ProjectDescriptionWorkflowHistory(
                        owner_id=self.id,
                        year=_get_current_year(),
                        event=WorkflowHistoryMixin.WORKFLOW_CONFIRMED,
                        user_id=current_user.id if current_user is not None else None,
                        timestamp=now,
                    )
                    db.session.add(history)

            else:
                self.confirmed_id = None
                self.confirmed_timestamp = None

            return value

    @validates(
        "description",
        "reading",
        "aims",
        "team",
        "capacity",
        "modules",
        "review_only",
        include_removes=True,
    )
    def _description_enqueue(self, key, value, is_remove):
        with db.session.no_autoflush:
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
            self.confirmed = False

        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = {}
        self._warnings = {}

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = {}
        self._warnings = {}

    @property
    def is_valid(self):
        """
        Perform validation
        :return:
        """
        flag, self._errors, self._warnings = _ProjectDescription_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def errors(self):
        if not self._validated:
            check = self.is_valid
        return self._errors.values()

    @property
    def warnings(self):
        if not self._validated:
            check = self.is_valid
        return self._warnings.values()

    def has_error(self, key):
        if not self._validated:
            check = self.is_valid
        return key in self._errors

    def has_warning(self, key):
        if not self._validated:
            check = self.is_valid
        return key in self._warnings

    def get_error(self, key):
        if not self._validated:
            check = self.is_valid
        return self._errors.get(key, None)

    def get_warning(self, key):
        if not self._validated:
            check = self.is_valid
        return self._warnings.get(key, None)

    def remove_project_class(self, pclass):

        if pclass in self.project_classes:
            self.project_classes.remove(pclass)

    def module_available(self, module_id):
        """
        Determine whether a given module can be applied as a pre-requisite for this project;
        that depends whether it's available for all possible project classes
        :param module_id:
        :return:
        """
        for pclass in self.project_classes:
            if not pclass.module_available(module_id):
                return False

        return True

    def get_available_modules(self, level_id=None):
        """
        Return a list of all modules that can be applied as pre-requisites for this project
        :param level_id:
        :return:
        """
        from .academic import Module

        query = db.session.query(Module).filter_by(active=True)
        if level_id is not None:
            query = query.filter_by(level_id=level_id)
        modules = query.all()

        return [m for m in modules if self.module_available(m.id)]

    def validate_modules(self):
        self.modules = [m for m in self.modules if self.module_available(m.id)]

    def has_new_comments(self, user):
        # build query to determine most recent comment, ignoring our own
        # (they don't count as new, unread comments)
        query = db.session.query(DescriptionComment.creation_timestamp).filter(
            DescriptionComment.owner_id != user.id,
            DescriptionComment.parent_id == self.id,
        )

        # if user not in approvals team, ignore any comments that are only visible to the approvals team
        if not user.has_role("project_approver"):
            query = query.filter(
                DescriptionComment.visibility
                != DescriptionComment.VISIBILITY_APPROVALS_TEAM
            )

        query = query.order_by(DescriptionComment.creation_timestamp.desc())

        # get timestamp of most recent comment
        most_recent = query.first()

        if most_recent is None:
            return False

        # get last view record for the specified user
        record = self.parent.last_viewing_times.filter_by(user_id=user.id).first()

        if record is None:
            return True

        return most_recent[0] > record.last_viewed

    @property
    def requires_confirmation(self):
        for p in self.project_classes:
            if p.active and p.require_confirm:
                return True

        return False

    @property
    def has_workflow_history(self):
        return get_count(self.workflow_history) > 0

    def CATS_supervision(self, config):

        if config.uses_supervisor:
            if config.CATS_supervision is not None and config.CATS_supervision > 0:
                return config.CATS_supervision

        return None

    @property
    def CATS_marking(self, config):

        if config.uses_marker:
            if config.CATS_marking is not None and config.CATS_marking > 0:
                return config.CATS_marking

        return None

    @property
    def CATS_moderation(self, config):

        if config.uses_moderator:
            if config.CATS_moderation is not None and config.CATS_moderation > 0:
                return config.CATS_moderation

        return None

    @property
    def CATS_presentation(self, config):

        if config.uses_presentations:
            if config.CATS_presentation is not None and config.CATS_presentation > 0:
                return config.CATS_presentation

        return None

    def maintenance(self):
        """
        Perform regular basic maintenance, to ensure validity of the database
        :return:
        """
        modified = False

        # ensure that project class list does not contain any class that is not attached to the parent project
        removed = [
            pcl
            for pcl in self.project_classes
            if pcl not in self.parent.project_classes
        ]

        for pcl in removed:
            current_app.logger.info(
                'Regular maintenance: pruned project class "{name}" from project description '
                '"{proj}/{desc}" since this class is not attached to the parent '
                "project".format(name=pcl.name, proj=self.parent.name, desc=self.label)
            )
            self.project_classes.remove(pcl)

        if len(removed) > 0:
            modified = True

        if self.confirmed and self.has_issues:
            self.confirmed = False
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

            current_app.logger.info(
                "Regular maintenance: reset confirmation state for project description "
                '"{proj}/{desc}" since this description has validation '
                "issues.".format(proj=self.parent.name, desc=self.label)
            )

            modified = True

        return modified


@listens_for(ProjectDescription, "before_update")
def _ProjectDescription_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ProjectDescription_is_valid, target.id)
        cache.delete_memoized(_Project_is_offerable, target.parent_id)

        if target is not None and target.parent is not None:
            for pclass in target.parent.project_classes:
                cache.delete_memoized(
                    _Project_num_assessors, target.parent_id, pclass.id
                )
                cache.delete_memoized(
                    _Project_num_supervisors, target.parent_id, pclass.id
                )


@listens_for(ProjectDescription, "before_insert")
def _ProjectDescription_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ProjectDescription_is_valid, target.id)
        cache.delete_memoized(_Project_is_offerable, target.parent_id)

        if target is not None and target.parent is not None:
            for pclass in target.parent.project_classes:
                cache.delete_memoized(
                    _Project_num_assessors, target.parent_id, pclass.id
                )
                cache.delete_memoized(
                    _Project_num_supervisors, target.parent_id, pclass.id
                )


@listens_for(ProjectDescription, "before_delete")
def _ProjectDescription_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_ProjectDescription_is_valid, target.id)
        cache.delete_memoized(_Project_is_offerable, target.parent_id)

        if target is not None and target.parent is not None:
            for pclass in target.parent.project_classes:
                cache.delete_memoized(
                    _Project_num_assessors, target.parent_id, pclass.id
                )
                cache.delete_memoized(
                    _Project_num_supervisors, target.parent_id, pclass.id
                )


class DescriptionComment(db.Model, ApprovalCommentVisibilityStatesMixin):
    """
    Comment attached to ProjectDescription, eg. used by approvals team
    """

    __tablename__ = "description_comments"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # which approvals cycle does this comment belong to?
    year = db.Column(db.Integer(), db.ForeignKey("main_config.year"))

    # comment owner
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    owner = db.relationship(
        "User", uselist=False, backref=db.backref("comments", lazy="dynamic")
    )

    # project description
    parent_id = db.Column(db.Integer(), db.ForeignKey("descriptions.id"))
    parent = db.relationship(
        "ProjectDescription",
        uselist=False,
        backref=db.backref(
            "comments", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # comment
    comment = db.Column(db.Text())

    # VISIBILITY

    # indicate the visbility status of this comment
    visibility = db.Column(
        db.Integer(), default=ApprovalCommentVisibilityStatesMixin.VISIBILITY_EVERYONE
    )

    # deleted flag
    deleted = db.Column(db.Boolean(), default=False)

    # EDITING METADATA

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime(), index=True)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())

    def is_visible(self, user):
        if (
            self.visibility == DescriptionComment.VISIBILITY_EVERYONE
            or self.visibility == DescriptionComment.VISIBILITY_PUBLISHED_BY_APPROVALS
        ):
            return True

        if self.visibility == DescriptionComment.VISIBILITY_APPROVALS_TEAM:
            if user.has_role("project_approver"):
                return True

            return False

        # default to safe value
        return False

    @property
    def format_name(self):
        if self.visibility == DescriptionComment.VISIBILITY_PUBLISHED_BY_APPROVALS:
            return "Approvals team"

        return self.owner.name


class LastViewingTime(db.Model):
    """
    Capture the last time a given user viewed a project
    """

    __tablename__ = "last_view_projects"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # link to user to whom this record applies
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        uselist=False,
        backref=db.backref("last_viewing_times", lazy="dynamic"),
    )

    # link to project to which this record applies
    project_id = db.Column(db.Integer(), db.ForeignKey("projects.id"))
    project = db.relationship(
        "Project",
        foreign_keys=[project_id],
        uselist=False,
        backref=db.backref(
            "last_viewing_times", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # last viewing time
    last_viewed = db.Column(db.DateTime(), index=True)
