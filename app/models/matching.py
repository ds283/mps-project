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
from typing import List, Optional, Set

from flask import current_app
from sqlalchemy import and_, or_, orm
from sqlalchemy.event import listens_for
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import validates
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from ..cache import cache
from ..database import db
from ..shared.formatters import format_time
from ..shared.sqlalchemy import get_count
from .assets import GeneratedAsset
from .associations import (
    marker_matching_table,
    match_balancing,
    match_configs,
    matching_role_list,
    matching_role_list_original,
    project_matching_table,
    supervisors_matching_table,
)
from .config import get_AES_key
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import (
    EditingMetadataMixin,
    PuLPStatusMixin,
    SubmissionRoleTypesMixin,
)
from .utilities import (
    _MatchingAttempt_current_score,
    _MatchingAttempt_get_faculty_CATS,
    _MatchingAttempt_get_faculty_mark_CATS,
    _MatchingAttempt_get_faculty_sup_CATS,
    _MatchingAttempt_hint_status,
    _MatchingAttempt_number_project_assignments,
    _MatchingAttempt_prefer_programme_status,
)

# NOTE: the validation functions _MatchingAttempt_is_valid and _MatchingRecord_is_valid live in
# .matching_validation, which imports this module (and much of the rest of the model layer) at
# module level. They must therefore be imported lazily, inside the function bodies that use them.


class PuLPMixin(PuLPStatusMixin):
    # METADATA

    # outcome of calculation
    outcome = db.Column(db.Integer())

    # which solver are we using?
    solver = db.Column(db.Integer())

    @property
    def solver_name(self):
        if self.solver in self._solvers:
            return self._solvers[self.solver]

        return None

    # time taken to construct the PuLP problem
    construct_time = db.Column(db.Numeric(8, 3))

    # time taken by PulP to compute the solution
    compute_time = db.Column(db.Numeric(8, 3))

    # TASK DETAILS

    # Celery taskid, used in case we need to revoke the task;
    # typically this will be a UUID
    celery_id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # STATUS

    # are we waiting for manual upload?
    awaiting_upload = db.Column(db.Boolean(), default=False)

    # is the optimization job finished?
    finished = db.Column(db.Boolean(), default=False)

    # is the celery task finished (need not be the same as whether the optimization job is finished)
    celery_finished = db.Column(db.Boolean(), default=False)

    # value of objective function, if match was successful
    score = db.Column(db.Numeric(10, 2))

    # FILES FOR OFFLINE SCHEDULING

    # .LP file id
    @declared_attr
    def lp_file_id(cls):
        return db.Column(
            db.Integer(),
            db.ForeignKey("generated_assets.id", ondelete="SET NULL"),
            nullable=True,
            default=None,
        )

    # .LP file asset object
    @declared_attr
    def lp_file(cls):
        return db.relationship(
            "GeneratedAsset",
            primaryjoin=lambda: GeneratedAsset.id == cls.lp_file_id,
            uselist=False,
        )

    @property
    def formatted_construct_time(self):
        return format_time(self.construct_time)

    @property
    def formatted_compute_time(self):
        return format_time(self.compute_time)

    @property
    def solution_usable(self):
        # we are happy to use a solution if it is OPTIMAL or FEASIBLE
        return self.outcome == PuLPMixin.OUTCOME_OPTIMAL or self.outcome == PuLPMixin.OUTCOME_FEASIBLE


class MatchingAttempt(db.Model, PuLPMixin, EditingMetadataMixin):
    """
    Model configuration data for a matching attempt
    """

    # make table name plural
    __tablename__ = "matching_attempts"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # year should match an available year in MainConfig
    year = db.Column(db.Integer(), db.ForeignKey("main_config.year"))
    main_config = db.relationship(
        "MainConfig",
        foreign_keys=[year],
        uselist=False,
        backref=db.backref("matching_attempts", lazy="dynamic"),
    )

    # a name for this matching attempt
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True)

    # flag matching attempts that have been selected for use during rollover
    selected = db.Column(db.Boolean())

    # is this match based on another one?
    base_id = db.Column(db.Integer(), db.ForeignKey("matching_attempts.id"), nullable=True)
    base = db.relationship(
        "MatchingAttempt",
        foreign_keys=[base_id],
        uselist=False,
        remote_side=[id],
        backref=db.backref("descendants", lazy="dynamic", passive_deletes=True),
    )

    # bias towards base match
    base_bias = db.Column(db.Numeric(8, 3))

    # force agreement with base matches
    force_base = db.Column(db.Boolean())

    # PARTICIPATING PCLASSES

    # pclasses that are part of this match
    config_members = db.relationship(
        "ProjectClassConfig",
        secondary=match_configs,
        lazy="dynamic",
        backref=db.backref("matching_attempts", lazy="dynamic"),
    )

    # flag whether this attempt has been published to convenors for comments/editing
    published = db.Column(db.Boolean())

    # MATCHING OPTIONS

    # include only selectors who submitted choices
    include_only_submitted = db.Column(db.Boolean())

    # ignore CATS limits specified in faculty accounts?
    ignore_per_faculty_limits = db.Column(db.Boolean())

    # ignore degree programme preferences specified in project descriptions?
    ignore_programme_prefs = db.Column(db.Boolean())

    # how many years memory to include when levelling CATS scores
    years_memory = db.Column(db.Integer())

    # global supervising CATS limit
    supervising_limit = db.Column(db.Integer())

    # global 2nd-marking CATS limit
    marking_limit = db.Column(db.Integer())

    # maximum multiplicity for markers
    max_marking_multiplicity = db.Column(db.Integer())

    # maximum number of different types of group project to assign to a single supervisor.
    # None indicates no limit is being applied.
    max_different_group_projects = db.Column(db.Integer())

    # maximum number of different types of project (group or ordinary) to assign to a single supervisor.
    # None indicates no limit is being applied. Should be at least as large as max_different_group_projects
    max_different_all_projects = db.Column(db.Integer())

    # CONVENOR HINTS

    # enable/disable convenor hints
    use_hints = db.Column(db.Boolean())

    # bias for 'encourage'
    encourage_bias = db.Column(db.Numeric(8, 3))

    # bias for 'discourage'
    discourage_bias = db.Column(db.Numeric(8, 3))

    # bias for 'strong encourage'
    strong_encourage_bias = db.Column(db.Numeric(8, 3))

    # bias for 'strong discourage'
    strong_discourage_bias = db.Column(db.Numeric(8, 3))

    # treat 'require' as 'strong encourage'
    require_to_encourage = db.Column(db.Boolean())

    # treat 'forbid' as 'strong discourage'
    forbid_to_discourage = db.Column(db.Boolean())

    # MATCHING

    # programme matching bias
    programme_bias = db.Column(db.Numeric(8, 3))

    # bookmark bias - penalty for using bookmarks rather than a real submission
    bookmark_bias = db.Column(db.Numeric(8, 3))

    # WORKLOAD LEVELLING

    # workload levelling bias
    # (this is the prefactor we use to set the normalization of the tension term in the objective function.
    # the tension term represents the difference in CATS between the upper and lower workload in each group,
    # plus another term (the 'intra group tension') that tensions all groups together. 'Group' here means
    # faculty that supervise only, mark only, or (most commonly) both supervise and mark.
    # Each group will typically have a different median workload.)
    levelling_bias = db.Column(db.Numeric(8, 3))

    # intra-group tensioning
    intra_group_tension = db.Column(db.Numeric(8, 3))

    # pressure to keep maximum supervisory assignment low
    supervising_pressure = db.Column(db.Numeric(8, 3))

    # pressure to keep maximum marking assignment low
    marking_pressure = db.Column(db.Numeric(8, 3))

    # penalty for violating CATS limits
    CATS_violation_penalty = db.Column(db.Numeric(8, 3))

    # penality for leaving supervisory faculty without an assignment
    no_assignment_penalty = db.Column(db.Numeric(8, 3))

    # other MatchingAttempts to include in CATS calculations
    include_matches = db.relationship(
        "MatchingAttempt",
        secondary=match_balancing,
        primaryjoin=match_balancing.c.child_id == id,
        secondaryjoin=match_balancing.c.parent_id == id,
        backref="balanced_with",
        lazy="dynamic",
    )

    # CONFIGURATION

    # record participants in this matching attempt
    # note, there is no need to track the selectors since they are in 1-to-1 correspondence with the attached
    # MatchingRecords, available under the backref .records

    # participating supervisors
    supervisors = db.relationship(
        "FacultyData",
        secondary=supervisors_matching_table,
        lazy="dynamic",
        backref=db.backref("supervisor_matching_attempts", lazy="dynamic"),
    )

    # participating markers
    markers = db.relationship(
        "FacultyData",
        secondary=marker_matching_table,
        lazy="dynamic",
        backref=db.backref("marker_matching_attempts", lazy="dynamic"),
    )

    # participating projects
    projects = db.relationship(
        "LiveProject",
        secondary=project_matching_table,
        lazy="dynamic",
        backref=db.backref("project_matching_attempts", lazy="dynamic"),
    )

    # mean CATS per project during matching
    mean_CATS_per_project = db.Column(db.Numeric(8, 5))

    # CIRCULATION STATUS

    # draft circulated to selectors?
    draft_to_selectors = db.Column(db.DateTime())

    # draft circulated to supervisors?
    draft_to_supervisors = db.Column(db.DateTime())

    # final verison circulated to selectors?
    final_to_selectors = db.Column(db.DateTime())

    # final version circulated to supervisors?
    final_to_supervisors = db.Column(db.DateTime())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._CATS_list = None

        self._validated = False
        self._student_issues = False
        self._faculty_issues = False
        self._errors = {}
        self._warnings = {}

    @orm.reconstructor
    def _reconstruct(self):
        self._CATS_list = None

        self._validated = False
        self._student_issues = False
        self._faculty_issues = False
        self._errors = {}
        self._warnings = {}

    def selector_list_query(self):
        from .live_projects import SelectingStudent

        return (
            db.session.query(SelectingStudent)
            .join(
                MatchingRecord,
                and_(
                    MatchingRecord.matching_id == self.id,
                    MatchingRecord.selector_id == SelectingStudent.id,
                ),
            )
            .distinct()
        )

    def faculty_list_query(self):
        from .faculty import FacultyData

        return (
            db.session.query(FacultyData)
            .join(
                supervisors_matching_table,
                and_(
                    supervisors_matching_table.c.match_id == self.id,
                    supervisors_matching_table.c.supervisor_id == FacultyData.id,
                ),
                isouter=True,
            )
            .join(
                marker_matching_table,
                and_(
                    marker_matching_table.c.match_id == self.id,
                    marker_matching_table.c.marker_id == FacultyData.id,
                ),
                isouter=True,
            )
            .filter(
                or_(
                    supervisors_matching_table.c.match_id != None,
                    marker_matching_table.c.match_id != None,
                )
            )
            .distinct()
        )

    def get_faculty_CATS(self, fd, pclass_id=None):
        """
        Compute faculty workload in CATS, optionally for a specific pclass
        :param fd: FacultyData instance
        :return:
        """
        from .faculty import FacultyData
        from .users import User

        if isinstance(fd, int):
            fac_id = fd
        elif isinstance(fd, FacultyData) or isinstance(fd, User):
            fac_id = fd.id
        else:
            raise RuntimeError("Cannot interpret parameter fac of type {n} in get_faculty_CATS()".format(n=type(fd)))

        return _MatchingAttempt_get_faculty_CATS(self.id, fac_id, pclass_id)

    def _build_CATS_list(self):
        if self._CATS_list is not None:
            return

        fsum = lambda x: x[0] + x[1]

        query = self.faculty_list_query()
        self._CATS_list = [fsum(self.get_faculty_CATS(fac.id)) for fac in query.all()]

    @property
    def submit_year_a(self):
        return self.year + 1

    @property
    def submit_year_b(self):
        return self.year + 2

    @property
    def faculty_CATS(self):
        self._build_CATS_list()
        return self._CATS_list

    def _get_delta_set(self):
        selectors = self.selector_list_query().all()

        def _get_deltas(s):
            records: List[MatchingRecord] = s.matching_records.filter(MatchingRecord.matching_id == self.id).all()

            deltas = [r.delta for r in records]
            return sum(deltas) if None not in deltas else None

        delta_set = [_get_deltas(s) for s in selectors]

        return [x for x in delta_set if x is not None]

    @property
    def delta_max(self):
        delta_set = self._get_delta_set()

        if delta_set is None or len(delta_set) == 0:
            return None

        return max(delta_set)

    @property
    def delta_min(self):
        delta_set = self._get_delta_set()

        if delta_set is None or len(delta_set) == 0:
            return None

        return min(delta_set)

    @property
    def CATS_max(self):
        if len(self.faculty_CATS) == 0:
            return None

        return max(self.faculty_CATS)

    @property
    def CATS_min(self):
        if len(self.faculty_CATS) == 0:
            return None

        return min(self.faculty_CATS)

    def get_supervisor_records(self, fac_id):
        from .live_projects import LiveProject

        return (
            self.records.join(LiveProject, LiveProject.id == MatchingRecord.project_id)
            .filter(
                MatchingRecord.roles.any(
                    and_(
                        MatchingRole.user_id == fac_id,
                        MatchingRole.role.in_(
                            [
                                MatchingRole.ROLE_SUPERVISOR,
                                MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
                            ]
                        ),
                    )
                )
            )
            .order_by(MatchingRecord.submission_period.asc())
        )

    def get_marker_records(self, fac_id):
        from .live_projects import LiveProject

        return (
            self.records.join(LiveProject, LiveProject.id == MatchingRecord.project_id)
            .filter(
                MatchingRecord.roles.any(
                    and_(
                        MatchingRole.user_id == fac_id,
                        MatchingRole.role == MatchingRole.ROLE_MARKER,
                    )
                )
            )
            .order_by(MatchingRecord.submission_period.asc())
        )

    def number_project_assignments(self, project):
        return _MatchingAttempt_number_project_assignments(self.id, project.id)

    def is_supervisor_overassigned(self, faculty, include_matches=False, pclass_id=None):
        from .faculty import EnrollmentRecord
        from .project_class import ProjectClass

        pclass: Optional[ProjectClass]
        if pclass_id is not None:
            pclass = db.session.query(ProjectClass).filter_by(id=pclass_id).first()
            if pclass is None:
                raise RuntimeError(f"Could not load ProjectClass record for pclass_id={pclass_id}")
        else:
            pclass = None

        # calculate supervision assignment, either summed over all project types, or for one specific project type if specified
        sup, mark = self.get_faculty_CATS(faculty.id, pclass_id=pclass_id)

        included_matches = {}

        # calculate total assignment
        total = sup
        if include_matches:
            for match in self.include_matches:
                sup, mark = match.get_faculty_CATS(faculty.id, pclass_id=pclass_id)
                included_matches[match.id] = sup

            if len(included_matches) > 0:
                total += sum(included_matches.values())

        # CATS-limit violations are warnings (sometimes supervisors must take more students than
        # we would like, but the students do all have to be supervised somehow); enrolment
        # violations are errors
        error_messages: List[str] = []
        warning_messages: List[str] = []
        pclass_label: str = "" if pclass is None else f"/{pclass.abbreviation}"
        name: str = faculty.user.name

        # self.supervising_limit is guaranteed not to be None
        limit = self.supervising_limit

        if sup > self.supervising_limit:
            warning_messages.append(
                f"Assigned supervising workload of {sup} for {name}{pclass_label} exceeds CATS limit {self.supervising_limit} for this match"
            )

        if not self.ignore_per_faculty_limits and faculty.CATS_supervision is not None and faculty.CATS_supervision >= 0:
            if sup > faculty.CATS_supervision:
                warning_messages.append(
                    f"Assigned supervising workload of {sup} for {name}{pclass_label} exceeds global CATS limit {faculty.CATS_supervision} for this supervisor"
                )

            if faculty.CATS_supervision < limit:
                limit = faculty.CATS_supervision

        if pclass is not None:
            enrolment_rec: EnrollmentRecord = faculty.get_enrollment_record(pclass)
            if enrolment_rec is not None:
                if not self.ignore_per_faculty_limits and enrolment_rec.CATS_supervision is not None:
                    if 0 <= enrolment_rec.CATS_supervision < sup:
                        warning_messages.append(
                            f"Assigned supervising workload of {sup} for {name}{pclass_label} exceeds {pclass.abbreviation}-specific CATS limit {enrolment_rec.CATS_supervision} for this supervisor"
                        )

                    if enrolment_rec.CATS_supervision < limit:
                        limit = enrolment_rec.CATS_supervision

                if sup > 0 and enrolment_rec.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
                    error_messages.append(
                        f"{name}{pclass_label} is not enrolled to supervise for {pclass.abbreviation}, but has been assigned a supervising workload {sup}"
                    )

        if len(error_messages) == 0 and len(warning_messages) == 0 and total > limit:
            warning_messages.append(f"After inclusion of all matches, assigned supervising workload of {total} for {name} exceeds CATS limit {limit}")

        rval: bool = len(error_messages) > 0 or len(warning_messages) > 0
        all_messages = error_messages + warning_messages

        data = {
            "flag": rval,
            "CATS_total": total,
            "CATS_limit": limit,
            "error_message": "; ".join(all_messages) if len(all_messages) > 0 else None,
            "errors": error_messages,
            "warnings": warning_messages,
        }

        if include_matches:
            data["included"] = included_matches

        return data

    def is_marker_overassigned(self, faculty, include_matches=False, pclass_id=None):
        from .faculty import EnrollmentRecord
        from .project_class import ProjectClass

        if pclass_id is not None:
            pclass: Optional[ProjectClass] = db.session.query(ProjectClass).filter_by(id=pclass_id).first()
            if pclass is None:
                raise RuntimeError(f"Could not load ProjectClass record for pclass_id={pclass_id}")
        else:
            pclass: Optional[ProjectClass] = None

        # calculate marking assignment, either summed over all project types, or for one specific project type if specified
        sup, mark = self.get_faculty_CATS(faculty.id, pclass_id=pclass_id)

        included_matches = {}

        # calculate total assignment
        total = mark
        if include_matches:
            for match in self.include_matches:
                sup, mark = match.get_faculty_CATS(faculty.id, pclass_id=pclass_id)
                included_matches[match.id] = mark

            if len(included_matches) > 0:
                total += sum(included_matches.values())

        # CATS-limit violations are warnings; enrolment violations are errors
        error_messages: List[str] = []
        warning_messages: List[str] = []
        pclass_label = "" if pclass is None else f"/{pclass.abbreviation}"
        name = faculty.user.name

        limit = self.marking_limit

        if mark > self.marking_limit:
            warning_messages.append(
                f"Assigned marking workload of {mark} for {name}{pclass_label} exceeds CATS limit {self.marking_limit} for this match"
            )

        if not self.ignore_per_faculty_limits and faculty.CATS_marking is not None and faculty.CATS_marking >= 0:
            if mark > faculty.CATS_marking:
                warning_messages.append(
                    f"Assigned marking workload of {mark} for {name}{pclass_label} exceeds global CATS limit {faculty.CATS_marking} for this marker"
                )

            if faculty.CATS_marking < limit:
                limit = faculty.CATS_marking

        if pclass is not None:
            enrolment_rec: EnrollmentRecord = faculty.get_enrollment_record(pclass)
            if enrolment_rec is not None:
                if not self.ignore_per_faculty_limits and enrolment_rec.CATS_marking is not None:
                    if 0 <= enrolment_rec.CATS_marking < mark:
                        warning_messages.append(
                            f"Assigned marking workload of {mark} for {name}{pclass_label} exceeds {pclass.abbreviation}-specific CATS limit {enrolment_rec.CATS_marking} for this marker"
                        )

                    if enrolment_rec.CATS_marking < limit:
                        limit = enrolment_rec.CATS_marking

                if mark > 0 and enrolment_rec.marker_state != EnrollmentRecord.MARKER_ENROLLED:
                    error_messages.append(
                        f"{name}{pclass_label} is not enrolled to mark for {pclass.abbreviation}, but has been assigned a marking workload {mark}"
                    )

        if len(error_messages) == 0 and len(warning_messages) == 0 and total > limit:
            warning_messages.append(f"After inclusion of all matches, assigned marking workload of {total} for {name} exceeds CATS limit {limit}")

        rval: bool = len(error_messages) > 0 or len(warning_messages) > 0
        all_messages = error_messages + warning_messages

        data = {
            "flag": rval,
            "CATS_total": total,
            "CATS_limit": limit,
            "error_message": "; ".join(all_messages) if len(all_messages) > 0 else None,
            "errors": error_messages,
            "warnings": warning_messages,
        }

        if include_matches:
            data["included"] = included_matches

        return data

    @property
    def is_valid(self):
        """
        Perform validation
        :return:
        """
        from .matching_validation import _MatchingAttempt_is_valid

        try:
            (
                flag,
                self._student_issues,
                self._faculty_issues,
                self._errors,
                self._warnings,
            ) = _MatchingAttempt_is_valid(self.id)
            self._validated = True
        except Exception as e:
            current_app.logger.exception("** Exception in MatchingAttempt.is_valid", exc_info=e)
            return None

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

    @property
    def faculty_issues(self):
        if not self._validated:
            check = self.is_valid
        return self._faculty_issues

    @property
    def student_issues(self):
        if not self._validated:
            check = self.is_valid
        return self._student_issues

    @property
    def current_score(self):
        return _MatchingAttempt_current_score(self.id)

    def _compute_group_max_min(self, CATS_list, globalMax, globalMin):
        if len(CATS_list) == 0:
            return 0, globalMax, globalMin

        largest = max(CATS_list)
        smallest = min(CATS_list)

        if globalMax is None or largest > globalMax:
            globalMax = largest

        if globalMin is None or smallest < globalMin:
            globalMin = smallest

        return largest - smallest, globalMax, globalMin

    @property
    def _faculty_groups(self):
        sup_dict = {x.id: x for x in self.supervisors}
        mark_dict = {x.id: x for x in self.markers}

        supervisor_ids = sup_dict.keys()
        marker_ids = mark_dict.keys()

        # these are set difference and set intersection operators
        sup_only_ids = supervisor_ids - marker_ids
        mark_only_ids = marker_ids - supervisor_ids
        sup_and_mark_ids = supervisor_ids & marker_ids

        sup_only = [sup_dict[i] for i in sup_only_ids]
        mark_only = [mark_dict[i] for i in mark_only_ids]
        sup_and_mark = [sup_dict[i] for i in sup_and_mark_ids]

        return mark_only, sup_and_mark, sup_only

    def _get_group_CATS(self, group):
        fsum = lambda x: x[0] + x[1]

        # compute our self-CATS
        CAT_lists = {"self": [fsum(self.get_faculty_CATS(x.id)) for x in group]}

        for m in self.include_matches:
            CAT_lists[m.id] = [fsum(m.get_faculty_CATS(x.id)) for x in group]

        return [sum(i) for i in zip(*CAT_lists.values())]

    @property
    def _max_marking_allocation(self):
        allocs = [len(self.get_marker_records(fac.id).all()) for fac in self.markers]
        return max(allocs)

    @property
    def prefer_programme_status(self):
        return _MatchingAttempt_prefer_programme_status(self.id)

    @property
    def hint_status(self):
        return _MatchingAttempt_hint_status(self.id)

    @property
    def available_pclasses(self):
        from .project_class import ProjectClass

        configs = self.config_members.subquery()
        pclass_ids = db.session.query(configs.c.pclass_id).distinct().subquery()

        return db.session.query(ProjectClass).join(pclass_ids, ProjectClass.id == pclass_ids.c.pclass_id).all()

    @property
    def is_modified(self):
        return self.last_edit_timestamp is not None

    @property
    def can_clean_up(self):
        from .live_projects import SelectingStudent

        # check whether any MatchingRecords are associated with selectors who are not converting
        no_convert_query = self.records.join(SelectingStudent, MatchingRecord.selector_id == SelectingStudent.id).filter(
            SelectingStudent.convert_to_submitter.is_(False)
        )

        if get_count(no_convert_query) > 0:
            return True

        return False


def _delete_MatchingAttempt_cache(target_id):
    from .matching_validation import _MatchingAttempt_is_valid

    cache.delete_memoized(_MatchingAttempt_current_score, target_id)
    cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target_id)
    cache.delete_memoized(_MatchingAttempt_is_valid, target_id)
    cache.delete_memoized(_MatchingAttempt_hint_status, target_id)

    cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
    cache.delete_memoized(_MatchingAttempt_get_faculty_sup_CATS)
    cache.delete_memoized(_MatchingAttempt_get_faculty_mark_CATS)

    cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@listens_for(MatchingAttempt, "before_update")
def _MatchingAttempt_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingAttempt_cache(target.id)


@listens_for(MatchingAttempt, "before_insert")
def _MatchingAttempt_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingAttempt_cache(target.id)


@listens_for(MatchingAttempt, "before_delete")
def _MatchingAttempt_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingAttempt_cache(target.id)


class MatchingRole(db.Model, SubmissionRoleTypesMixin):
    """
    Analogue of SubmissionRole for a MatchingRecord
    """

    __tablename__ = "matching_roles"

    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # owning user (does not have to be a FacultyData instance, but usually will be)
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        uselist=False,
        backref=db.backref("matching_roles", lazy="dynamic"),
    )

    # role identifier, drawn from SubmissionRoleTypesMixin
    role = db.Column(
        db.Integer(),
        default=SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        nullable=False,
    )

    @validates("role")
    def _validate_role(self, key, value):
        # reject out-of-range values rather than silently clamping them: clamping converts a
        # data-entry bug into a wrong (but plausible-looking) role assignment
        if value is None or value < self._MIN_ROLE or value > self._MAX_ROLE:
            raise ValueError(f"Invalid MatchingRole role value: {value}")

        return value

    @property
    def role_as_str(self) -> str:
        return self._role_string.get(self.role, "Unknown")

    @property
    def roleid_as_str(self) -> str:
        return self._role_id.get(self.role, "unknown")


@cache.memoize()
def _MatchingRecord_current_score(id):
    from .live_projects import SelectingStudent
    from .project_class import ProjectClassConfig
    from .submissions import SelectionRecord

    obj: MatchingRecord = db.session.query(MatchingRecord).filter_by(id=id).one()
    sel: SelectingStudent = obj.selector
    config: ProjectClassConfig = sel.config

    # return None is SelectingStudent record is missing
    if sel is None:
        return None

    # return None if SelectingStudent has no submission records.
    # This happens if they didn't submit a choices list and have no bookmarks.
    # In this case we had to set their rank matrix to 1 for all suitable projects, in order that
    # an allocation could be made (because of the constraint that allocation <= rank).
    # Also weight is 1 so we always score 1
    if not sel.has_submitted:
        return 1.0

    # if selector had a custom offer, we score 1.0 if the selector is assigned to this offer, otherwise
    # we score 0
    if sel.has_accepted_offers():
        accepted_offers = sel.accepted_offers()
        return 1.0 if any(offer.liveproject.id == obj.project_id for offer in accepted_offers) else 0.0

    # find selection record corresponding to our project
    record: SelectionRecord = sel.selections.filter_by(liveproject_id=obj.project_id).first()

    # if there isn't one, presumably a convenor has reallocated us to a project for which
    # we score 0
    if record is None:
        return 0.0

    # if hint is forbid, we contribute nothing
    if record.hint == SelectionRecord.SELECTION_HINT_FORBID:
        return 0.0

    # score is 1/rank of assigned project, weighted
    weight = 1.0

    # downweight by penalty factor if selection record was converted from a bookmark
    if record.converted_from_bookmark:
        weight *= float(obj.matching_attempt.bookmark_bias)

    # upweight by encourage/discourage bias terms, if needed
    if obj.matching_attempt.use_hints:
        if record.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE:
            weight *= float(obj.matching_attempt.encourage_bias)
        elif record.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE:
            weight *= float(obj.matching_attempt.discourage_bias)
        elif record.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG:
            weight *= float(obj.matching_attempt.strong_encourage_bias)
        elif record.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG:
            weight *= float(obj.matching_attempt.strong_discourage_bias)

    # upweight by programme bias, if this is not disabled
    if not obj.matching_attempt.ignore_programme_prefs:
        if obj.project.satisfies_preferences(sel):
            weight *= float(obj.matching_attempt.programme_bias)

    rank = obj.total_rank

    return weight / float(rank)


class MatchingRecord(db.Model):
    """
    Store matching data for an individual selector
    """

    __tablename__ = "matching_records"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # owning MatchingAttempt
    matching_id = db.Column(db.Integer(), db.ForeignKey("matching_attempts.id"))
    matching_attempt = db.relationship(
        "MatchingAttempt",
        foreign_keys=[matching_id],
        uselist=False,
        backref=db.backref("records", lazy="dynamic", cascade="all, delete, delete-orphan"),
    )

    # owning SelectingStudent
    selector_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"))
    selector = db.relationship(
        "SelectingStudent",
        foreign_keys=[selector_id],
        uselist=False,
        backref=db.backref("matching_records", lazy="dynamic"),
    )

    # submission period
    submission_period = db.Column(db.Integer())

    # PROJECT

    # assigned project
    project_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    project = db.relationship("LiveProject", foreign_keys=[project_id], uselist=False)

    # keep copy of original project assignment, can use later to revert
    original_project_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))

    # rank of this project in the student's selection, or None if the assigned project wasn't in the selection (e.g. because it is an alternative)
    rank = db.Column(db.Integer(), nullable=True)

    # is this project an alternative?
    alternative = db.Column(db.Boolean(), nullable=False, default=False)

    # if this project is an alternative, link to the project it was an alternative for, or None if it is not an alternative
    # (anyway ignored unless the alternative flag is set to True)
    parent_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"), nullable=True, default=None)
    parent = db.relationship("LiveProject", foreign_keys=[parent_id], uselist=False)

    # if this project is an alternative, record its priority, or None if it is not an alternative
    priority = db.Column(db.Integer(), nullable=True, default=None)

    # keep copies of the original alternative fields so that revert_record() can restore them exactly
    original_alternative = db.Column(db.Boolean(), nullable=False, default=False)
    original_parent_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"), nullable=True, default=None)
    original_parent = db.relationship("LiveProject", foreign_keys=[original_parent_id], uselist=False)
    original_priority = db.Column(db.Integer(), nullable=True, default=None)

    # PERSONNEL

    # for submissions, the relationship between SubmissionRole and SubmissionRecord is handled by placing
    # the SubmissionRecord foreign key on SubmissionRole. This is the natural way to do it, and it would be
    # easier to do it this way here.

    # Here, we have two association tables that map MatchingRole instances to here (MatchingRecord).
    # The point is that we want some MatchingRole instances to record the 'original' assignment
    # (accessible via the 'original_roles' data member), and other instances to record the 'current' assignment
    # (accessible via the 'roles' data member), and this can't be done by configuring the relationship on the
    # MatchingRole table.

    # assigned personnel
    roles = db.relationship(
        "MatchingRole",
        secondary=matching_role_list,
        lazy="dynamic",
        single_parent=True,
        cascade="all, delete, delete-orphan",
        backref=db.backref("role_for", lazy="dynamic"),
    )

    # keep copy of originally assigned personnel (to support later reversion, if desired; note these are
    # *separate* instances of MatchingRole, not the same instance that is pointed to by two association tables)
    original_roles = db.relationship(
        "MatchingRole",
        secondary=matching_role_list_original,
        lazy="dynamic",
        single_parent=True,
        cascade="all, delete, delete-orphan",
        backref=db.backref("original_role_for", lazy="dynamic"),
    )

    # EDIT PROVENANCE

    # who last diverged this record from its optimizer baseline, and when. Cleared when the record is
    # reverted back to baseline. Note there is deliberately no created_by/creation_timestamp pair, and
    # therefore no use of EditingMetadataMixin: a MatchingRecord is always created by the optimizer run
    # that owns it, so per-record creation metadata would just duplicate the owning MatchingAttempt.
    last_edit_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True, default=None)
    last_edited_by = db.relationship("User", foreign_keys=[last_edit_id], uselist=False)

    last_edit_timestamp = db.Column(db.DateTime(), nullable=True, default=None)

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

    def mark_edited(self, user):
        """
        Record a manual edit to this MatchingRecord, and propagate the same provenance to the owning
        MatchingAttempt. The record-level and attempt-level pairs are always written together, so that
        the Changes tab can attribute each row individually while the attempt still knows when it was
        last touched as a whole. Does not commit; the caller owns the transaction.
        """
        now = datetime.now()

        self.last_edit_id = user.id if user is not None else None
        self.last_edit_timestamp = now

        attempt = self.matching_attempt
        if attempt is not None:
            attempt.last_edit_id = self.last_edit_id
            attempt.last_edit_timestamp = now

    def clear_edited(self):
        """
        Clear per-record edit provenance. Used when the record is restored to its optimizer baseline,
        after which it no longer represents a manual divergence. Does not touch the owning
        MatchingAttempt (a revert is itself an edit of the attempt). Does not commit.
        """
        self.last_edit_id = None
        self.last_edit_timestamp = None

    @property
    def is_valid(self):
        from .matching_validation import _MatchingRecord_is_valid

        try:
            flag, self._errors, self._warnings = _MatchingRecord_is_valid(self.id)
            self._validated = True
        except Exception as e:
            current_app.logger.exception("** Exception in MatchingRecord.is_valid", exc_info=e)
            return None

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

    def _filter(self, base, include, omit):
        if include is not None:
            filtered = [base[key] for key in base if key[0] in include]
            return filtered

        if omit is not None:
            filtered = [base[key] for key in base if key[0] not in omit]
            return filtered

        return base.values()

    def filter_errors(self, include=None, omit=None):
        if not self._validated:
            check = self.is_valid

        return self._filter(self._errors, include, omit)

    def filter_warnings(self, include=None, omit=None):
        if not self._validated:
            check = self.is_valid

        return self._filter(self._warnings, include, omit)

    def get_role_records(self, role: str) -> List:
        """
        Return MatchingRole instances attached to this record for role type 'role'
        :param role: specified role type
        :return:
        """
        role = role.lower()
        role_map = {
            "supervisor": [
                MatchingRole.ROLE_SUPERVISOR,
                MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR,
            ],
            "responsible_supervisor": [MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR],
            "supervisor_only": [MatchingRole.ROLE_SUPERVISOR],
            "marker": [MatchingRole.ROLE_MARKER],
        }

        if role not in role_map:
            raise KeyError("Unknown role in MatchingRecord.get_role_records()")

        role_ids = role_map[role]
        return [r for r in self.roles if r.role in role_ids]

    def get_roles(self, role: str) -> List:
        """
        Return User instances corresponding to attached MatchingRole records for role type 'role'
        :param role: specified role type
        :return:
        """
        return [r.user for r in self.get_role_records(role)]

    def get_role_ids(self, role: str) -> Set[int]:
        """
        Return a set of user ids for User instances obtained from get_roles()
        :return:
        """
        return set(u.id for u in self.get_roles(role))

    @property
    def supervisor_role_records(self) -> List:
        """
        Convenience function for get_role_records() with role='supervisor'
        :return:
        """
        return self.get_role_records("supervisor")

    @property
    def supervisor_roles(self) -> List:
        """
        Convenience function for get_roles() with role='supervisor'
        :return:
        """
        return self.get_roles("supervisor")

    @property
    def supervisor_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='supervisor'
        :return:
        """
        return self.get_role_ids("supervisor")

    @property
    def responsible_supervisor_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='responsible_supervisor'
        :return:
        """
        return self.get_role_ids("responsible_supervisor")

    @property
    def supervisor_only_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='supervisor_only' (plain
        ROLE_SUPERVISOR roles, excluding responsible supervisors)
        :return:
        """
        return self.get_role_ids("supervisor_only")

    @property
    def marker_roles(self) -> List:
        """
        Convenience function for get_roles() with role='marker'
        :return:
        """
        return self.get_roles("marker")

    @property
    def marker_role_ids(self) -> Set[int]:
        """
        Convenience function for get_role_ids() with role='marker'
        :return:
        """
        return self.get_role_ids("marker")

    @property
    def period(self):
        from .project_class import ProjectClass, ProjectClassConfig

        sel = self.selector
        config: ProjectClassConfig = sel.config
        pclass: ProjectClass = config.project_class

        return pclass.get_period(self.submission_period)

    @property
    def delta(self):
        rk = self.total_rank
        if rk is None:
            return None

        return rk - 1

    @property
    def total_rank(self):
        if self.rank is not None:
            if self.rank > 0:
                return self.rank
            else:
                return None

        if self.alternative and self.priority is not None:
            sel = self.selector
            config = sel.config
            base_priority = max(
                config.initial_choices,
                config.switch_choices if config.allow_switching else 0,
            )

            return base_priority + self.priority

        return None

    @property
    def hi_ranked(self):
        return self.rank == 1 or self.rank == 2

    @property
    def lo_ranked(self):
        if self.alternative:
            return True

        choices = self.selector.config.project_class.initial_choices
        return self.rank == choices or self.rank == choices - 1

    @property
    def current_score(self):
        return _MatchingRecord_current_score(self.id)

    @property
    def hint_status(self):
        from .submissions import SelectionRecord

        if self.selector is None or self.selector.selections is None:
            return None

        satisfied = set()
        violated = set()

        for item in self.selector.selections:
            if (
                item.hint == SelectionRecord.SELECTION_HINT_FORBID
                or item.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE
                or item.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG
            ):
                if self.project_id == item.liveproject_id:
                    violated.add(item.id)
                else:
                    satisfied.add(item.id)

            if (
                item.hint == SelectionRecord.SELECTION_HINT_REQUIRE
                or item.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE
                or item.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG
            ):
                if self.project_id != item.liveproject_id:
                    # check whether any other MatchingRecord for the same selector but a different
                    # submission period satisfies the match
                    check = (
                        db.session.query(MatchingRecord)
                        .filter_by(
                            matching_id=self.matching_id,
                            selector_id=self.selector_id,
                            project_id=item.liveproject_id,
                        )
                        .first()
                    )

                    if check is None:
                        violated.add(item.id)

                else:
                    satisfied.add(item.id)

        return satisfied, violated


def _delete_MatchingRecord_cache(record_id, attempt_id):
    from .matching_validation import _MatchingAttempt_is_valid, _MatchingRecord_is_valid

    cache.delete_memoized(_MatchingRecord_current_score, record_id)
    cache.delete_memoized(_MatchingRecord_is_valid, record_id)

    cache.delete_memoized(_MatchingAttempt_current_score, attempt_id)
    cache.delete_memoized(_MatchingAttempt_prefer_programme_status, attempt_id)
    cache.delete_memoized(_MatchingAttempt_is_valid, attempt_id)
    cache.delete_memoized(_MatchingAttempt_hint_status, attempt_id)

    cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
    cache.delete_memoized(_MatchingAttempt_get_faculty_sup_CATS)
    cache.delete_memoized(_MatchingAttempt_get_faculty_mark_CATS)
    cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@listens_for(MatchingRecord, "before_update")
def _MatchingRecord_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingRecord_cache(target.id, target.matching_id)


@listens_for(MatchingRecord, "before_insert")
def _MatchingRecord_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingRecord_cache(target.id, target.matching_id)


@listens_for(MatchingRecord, "before_delete")
def _MatchingRecord_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingRecord_cache(target.id, target.matching_id)


@listens_for(MatchingRecord.roles, "append")
def _MatchingRecord_roles_append_handler(target, value, initiator):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingRecord_cache(target.id, target.matching_id)


@listens_for(MatchingRecord.roles, "remove")
def _MatchingRecord_roles_remove_handler(target, value, initiator):
    target._validated = False

    with db.session.no_autoflush:
        _delete_MatchingRecord_cache(target.id, target.matching_id)


def _MatchingRole_invalidate_owners(target):
    # in-place edits to a MatchingRole (e.g. changing .role or .user_id) do not fire the
    # append/remove events on MatchingRecord.roles, so we must invalidate the validation
    # cache of any owning MatchingRecord explicitly
    for rec in target.role_for:
        rec._validated = False
        _delete_MatchingRecord_cache(rec.id, rec.matching_id)


@listens_for(MatchingRole, "before_update")
def _MatchingRole_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _MatchingRole_invalidate_owners(target)


@listens_for(MatchingRole, "before_delete")
def _MatchingRole_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _MatchingRole_invalidate_owners(target)


class MatchingReviewComment(db.Model):
    """
    A review comment posted against a MatchingAttempt during convenor/root review, before
    publishing. Scoped either to the whole match (matching_record_id is None) or to one
    student's assignment (matching_record_id set). Threaded one level via parent_id, and
    independently resolvable. Body follows the TicketComment pattern: encrypted at rest, since
    it may contain free-form, potentially sensitive student detail.
    """

    __tablename__ = "matching_review_comments"

    id = db.Column(db.Integer(), primary_key=True)

    matching_attempt_id = db.Column(db.Integer(), db.ForeignKey("matching_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    matching_attempt = db.relationship(
        "MatchingAttempt",
        foreign_keys=[matching_attempt_id],
        uselist=False,
        backref=db.backref("review_comments", lazy="dynamic"),
    )

    # NULL = whole-match scope; set = scoped to one student's assignment
    matching_record_id = db.Column(db.Integer(), db.ForeignKey("matching_records.id", ondelete="CASCADE"), nullable=True, index=True)
    matching_record = db.relationship(
        "MatchingRecord",
        foreign_keys=[matching_record_id],
        uselist=False,
        backref=db.backref("review_comments", lazy="dynamic"),
    )

    # NULL = top-level comment; set = one-level reply to another MatchingReviewComment
    parent_id = db.Column(db.Integer(), db.ForeignKey("matching_review_comments.id", ondelete="CASCADE"), nullable=True, index=True)
    parent = db.relationship(
        "MatchingReviewComment",
        remote_side=[id],
        backref=db.backref("replies", lazy="dynamic", cascade="all, delete-orphan"),
    )

    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    owner = db.relationship("User", foreign_keys=[owner_id], uselist=False)

    # comment body, encrypted at rest
    body = db.Column(EncryptedType(db.Text(), get_AES_key, AesEngine, "oneandzeroes"), nullable=True, default=None)

    resolved = db.Column(db.Boolean(), nullable=False, default=False)
    resolved_by_id = db.Column(db.Integer(), db.ForeignKey("users.id"), nullable=True)
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_id], uselist=False)
    resolved_timestamp = db.Column(db.DateTime(), nullable=True)

    creation_timestamp = db.Column(db.DateTime(), default=datetime.now, index=True)
    last_edit_timestamp = db.Column(db.DateTime(), nullable=True)

    @property
    def scope_label(self):
        """
        Human-readable description of this comment's scope, for panel headers/chips.
        """
        if self.matching_record_id is None:
            return "whole match"

        record: MatchingRecord = self.matching_record
        if record is not None and record.selector is not None and record.selector.student is not None:
            return record.selector.student.user.name

        return "this assignment"
