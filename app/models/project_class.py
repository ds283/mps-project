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
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, List, Optional, Union
from urllib.parse import urljoin

# import symbols that are needed just for type annotations, but are not needed at runtime, and would
# cause circular import errors if they were imported directly
if TYPE_CHECKING:
    from .assessment import PresentationAssessment
    from .projects import Project
    from .submissions import SubmissionRecord, SubmissionRole

from flask_security import current_user
from sqlalchemy import and_, or_, orm
from sqlalchemy.event import listens_for
from sqlalchemy.orm import validates
from sqlalchemy.sql import func
from url_normalize import url_normalize

from ..cache import cache
from ..database import db
from ..shared.formatters import format_readable_time
from ..shared.sqlalchemy import get_count
from .academic import DegreeProgramme, DegreeType, FHEQ_Level, Module
from .associations import (
    approvals_team,
    assessment_to_periods,
    even_assets_table,
    event_email_table,
    event_reminder_table,
    event_roles_table,
    force_tag_groups,
    golive_confirmation,
    golive_emails,
    live_assessors,
    office_contacts,
    pclass_coconvenors,
    pclass_programme_associations,
)
from .defaults import (
    DEFAULT_STRING_LENGTH,
)
from .faculty import EnrollmentRecord, FacultyData
from .model_mixins import (
    AutoEnrolMixin,
    ColouredLabelMixin,
    EditingMetadataMixin,
    SelectorLifecycleStatesMixin,
    StudentLevelsMixin,
    SubmissionRoleTypesMixin,
    SubmitterLifecycleStatesMixin,
    SupervisionEventAttendanceMixin,
    SupervisionEventTypesMixin,
    _get_current_year,
)
from .projects import (
    _Project_is_offerable,
    _Project_num_assessors,
    _Project_num_supervisors,
)
from .students import StudentData
from .users import User
from .utilities import (
    ConvenorGenericTask,
    ConvenorSelectorTask,
    ConvenorSubmitterTask,
    ConvenorTasksMixinFactory,
    MainConfig,
    PopularityRecord,
)


class ProjectClass(
    db.Model,
    ColouredLabelMixin,
    EditingMetadataMixin,
    StudentLevelsMixin,
    AutoEnrolMixin,
):
    """
    Model a single project class
    """

    # make table name plural
    __tablename__ = "project_classes"

    id = db.Column(db.Integer(), primary_key=True)

    # project class name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # user-facing abbreviatiaon
    abbreviation = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # publish to students/faculty?
    publish = db.Column(db.Boolean(), default=True)

    # active?
    active = db.Column(db.Boolean(), default=True)

    # TENANT

    # tenant this project class belongs to
    tenant_id = db.Column(db.Integer(), db.ForeignKey("tenants.id"), index=True)
    tenant = db.relationship(
        "Tenant",
        foreign_keys=[tenant_id],
        backref=db.backref("project_classes", lazy="dynamic"),
    )

    # PRACTICAL DATA

    # what student level is this project associated with (UG, PGT, PGR)
    student_level = db.Column(db.Integer(), default=StudentLevelsMixin.LEVEL_UG)

    @validates("student_level")
    def _validate_level(self, key, value):
        if value < self.LEVEL_UG:
            value = self.LEVEL_UG

        if value > self.LEVEL_PGR:
            value = self.LEVEL_UG

        return value

    # enforce ATAS flags?
    enforce_ATAS = db.Column(db.Boolean(), default=False)

    # is this an optional project type? e.g., JRA, research placement
    is_optional = db.Column(db.Boolean(), default=False)

    # in which academic year/FHEQ level does this project class begin?
    start_year = db.Column(db.Integer(), default=3)

    # how many years does the project extend? usually 1, but RP is more
    extent = db.Column(db.Integer(), default=1)

    # does this project type use selection? i.e., do selectors actually have to submit a ranked list of preferences?
    uses_selection = db.Column(db.Integer(), default=True)

    # selection runs in the previous academic cycle?
    # This is the default for FYPs and MPPs, but not usually for MSc projects
    select_in_previous_cycle = db.Column(db.Boolean(), default=True)

    # does this project type use submission? i.e., do submitters actually have to submit work?
    uses_submission = db.Column(db.Integer(), default=True)

    # are projects supervised (or just marked?)
    uses_supervisor = db.Column(db.Boolean(), default=True)

    # are submissions marked?
    uses_marker = db.Column(db.Boolean(), default=True)

    # are submissions moderated?
    uses_moderator = db.Column(db.Boolean(), default=False)

    # display second marker information in UI?
    display_marker = db.Column(db.Boolean(), default=True)

    # are there presentations?
    uses_presentations = db.Column(db.Boolean(), default=False)

    # display presentation information in UI?
    display_presentations = db.Column(db.Boolean(), default=True)

    # how many initial_choices should students make?
    initial_choices = db.Column(db.Integer())

    # is "switching" allowed in subsequent years? (This allows a different number of choices to initial_choices)
    allow_switching = db.Column(db.Boolean(), default=False)

    # how many switch choices should students be allowed?
    switch_choices = db.Column(db.Integer())

    # how many choices can be with the same faculty member?
    faculty_maximum = db.Column(db.Integer())

    # is project selection open to all students?
    selection_open_to_all = db.Column(db.Boolean(), default=False)

    # auto-enrol selectors during rollover of the academic year?
    auto_enrol_enable = db.Column(db.Boolean(), default=True)

    # in which years should students be auto-enrolled as selectors?
    # takes values from AutoEnrolMixin (AUTO_ENROLL_FIRST_YEAR, AUTO_ENROLL_ALL_YEARS)
    auto_enroll_years = db.Column(
        db.Integer(), default=AutoEnrolMixin.AUTO_ENROLL_FIRST_YEAR
    )

    @validates("auto_enroll_years")
    def _validate_auto_enroll_years(self, key, value):
        if value < self.AUTO_ENROLL_FIRST_YEAR:
            value = self.AUTO_ENROLL_FIRST_YEAR

        if value > self.AUTO_ENROLL_ALL_YEARS:
            value = self.AUTO_ENROLL_FIRST_YEAR

        return value

    # INFORMATION PRESENTED TO STUDENTS

    # advertise research group information for each project
    advertise_research_group = db.Column(db.Boolean(), default=True)

    # use tags for each project
    use_project_tags = db.Column(db.Boolean(), default=False)

    # SELECTOR CARD TEXT

    # text displayed when a project is detected as being optional
    card_text_optional = db.Column(db.Text())

    # text displayed when a project is detected as being mandatory
    card_text_normal = db.Column(db.Text())

    # text displayed when a project is detected as being a change-supervisor request
    card_text_noninitial = db.Column(db.Text())

    # MATCHING EMAIL TEXT

    # preamble for draft matching email
    email_text_draft_match_preamble = db.Column(db.Text())

    # preamble for final matching email
    email_text_final_match_preamble = db.Column(db.Text())

    # OPTIONS

    # explicitly ask supervisors to confirm projects each year?
    require_confirm = db.Column(db.Boolean())

    # carry over supervisor in subsequent years?
    supervisor_carryover = db.Column(db.Boolean())

    # include in 'availability' calculations -- how many students a given supervisor is 'available' for
    include_available = db.Column(db.Boolean())

    # require that an ATAS

    # POPULARITY DISPLAY

    # how many days to keep hourly popularity data for
    keep_hourly_popularity = db.Column(db.Integer())

    # how many weeks to keep daily popularity data for
    keep_daily_popularity = db.Column(db.Integer())

    # WORKLOAD MODEL

    # CATS awarded for supervising
    CATS_supervision = db.Column(db.Integer())

    # CATS awarded for marking
    CATS_marking = db.Column(db.Integer())

    # CATS awarded for moderation
    CATS_moderation = db.Column(db.Integer())

    # CATS awarded for presentation assessment
    CATS_presentation = db.Column(db.Integer())

    # AUTOMATED MATCHING

    # what level of automated student/project/2nd-marker matching does this project class use?
    # does it participate in the global automated matching, or is matching manual?
    do_matching = db.Column(db.Boolean())

    # number of assessors that should be specified per project
    number_assessors = db.Column(db.Integer())

    # PERSONNEL

    # principal project convenor. Must be a faculty member, so we link to faculty_data table
    convenor_id = db.Column(db.Integer(), db.ForeignKey("faculty_data.id"), index=True)
    convenor = db.relationship(
        "FacultyData",
        foreign_keys=[convenor_id],
        backref=db.backref("convenor_for", lazy="dynamic"),
    )

    # project co-convenors
    # co-convenors are similar to convenors, except that the principal convenor is always the
    # displayed contact point.
    # co-convenors could eg. be old convenors who are able to help out during a transition period
    # between convenors
    coconvenors = db.relationship(
        "FacultyData",
        secondary=pclass_coconvenors,
        lazy="dynamic",
        backref=db.backref("coconvenor_for", lazy="dynamic"),
    )

    # approvals team
    approvals_team = db.relationship(
        "User",
        secondary=approvals_team,
        lazy="dynamic",
        backref=db.backref("approver_for", lazy="dynamic"),
    )

    @property
    def number_approvals_team(self):
        return get_count(self.approvals_team)

    # School Office contacts
    office_contacts = db.relationship(
        "User",
        secondary=office_contacts,
        lazy="dynamic",
        backref=db.backref("contact_for", lazy="dynamic"),
    )

    # associate this project class with a set of degree programmes
    programmes = db.relationship(
        "DegreeProgramme",
        secondary=pclass_programme_associations,
        lazy="dynamic",
        backref=db.backref("project_classes", lazy="dynamic"),
    )

    # AUTOMATIC RE-ENROLLMENT

    # re-enroll supervisors one year early (normally we want this to be yes, because projects are
    # *offered* one academic year before they *run*)
    reenroll_supervisors_early = db.Column(db.Boolean(), default=True)

    # ENFORCE TAGGING
    force_tag_groups = db.relationship(
        "ProjectTagGroup",
        secondary=force_tag_groups,
        lazy="dynamic",
        backref=db.backref("force_tags_for", lazy="dynamic"),
    )

    # ATTACHED PROJECTS

    # 'projects' data member added by back reference from Project model

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._most_recent_config = None

    @orm.reconstructor
    def reconstruct(self):
        self._most_recent_config = None

    @property
    def number_submissions(self):
        return get_count(self.periods)

    @property
    def most_recent_config(self):
        # check whether we have a cached most recent ProjectClassConfig instance
        if self._most_recent_config is not None:
            return self._most_recent_config

        self._most_recent_config = (
            db.session.query(ProjectClassConfig)
            .filter_by(pclass_id=self.id)
            .order_by(ProjectClassConfig.year.desc())
            .first()
        )
        return self._most_recent_config

    def get_config(self, year):
        return (
            db.session.query(ProjectClassConfig)
            .filter_by(pclass_id=self.id, year=year)
            .first()
        )

    def disable(self):
        """
        Disable this project class
        :return:
        """

        self.active = False
        self.publish = False

        # remove this project class from any projects that have been attached with it
        for proj in self.projects:
            proj: Project
            proj.remove_project_class(self)

    def enable(self):
        """
        Enable this project class
        :return:
        """

        if self.available:
            self.active = True

    def set_unpublished(self):
        """
        Unpublish this project class
        :return:
        """

        self.publish = False

    def set_published(self):
        """
        Publish this project class
        :return:
        """

        if self.available:
            self.publish = True

    @property
    def available(self):
        """
        Determine whether this project class is available for use (or activation)
        :return:
        """

        # ensure that at least one active programme is available
        if not self.programmes.filter(DegreeProgramme.active).first():
            return False

        if self.uses_presentations:
            if get_count(self.periods.filter_by(has_presentation=True)) == 0:
                return False

        return True

    @property
    def convenor_email(self):
        return self.convenor.user.email

    @property
    def convenor_name(self):
        return self.convenor.user.name

    @property
    def convenor_simple_name(self):
        return self.convenor.user.simple_name

    def is_convenor(self, id):
        """
        Determine whether a given user 'id' is a convenor for this project class
        :param id:
        :return:
        """
        if self.convenor_id == id:
            return True

        if any([item.id == id for item in self.coconvenors]):
            return True

        return False

    @property
    def ordered_programmes(self):
        query = (
            db.session.query(pclass_programme_associations.c.programme_id)
            .filter(pclass_programme_associations.c.project_class_id == self.id)
            .subquery()
        )

        return (
            db.session.query(DegreeProgramme)
            .join(query, query.c.programme_id == DegreeProgramme.id)
            .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
            .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        )

    def make_label(self, text=None):
        if text is None:
            text = self.name

        return self._make_label(text)

    def get_period(self, n):
        # note submission periods start at 1
        if n <= 0 or n > self.number_submissions:
            return None

        return self.periods.filter_by(period=n).one()

    @property
    def ordered_periods(self):
        return self.periods.order_by(SubmissionPeriodDefinition.period.asc())

    def module_available(self, module_id):
        # the module should be at an FHEQ level which is less than or equal to our starting level

        # all modules are available for PGR or PGT
        if self.student_level == self.LEVEL_UG:
            # check if module's start level maps to our starting year
            # note that the FHEQ numerical level (3, 4, 5, 6, 7) maps to undergraduate years as year = level-3,
            # with Y0 as foundation year
            q = (
                db.session.query(Module)
                .filter(Module.id == module_id)
                .join(FHEQ_Level, FHEQ_Level.id == Module.level_id)
                .filter(FHEQ_Level.numeric_level <= self.start_year + 3)
            )

            if get_count(q) == 0:
                return False

        # the module should be included in at least one programme attached to this project class
        for prog in self.programmes:
            if get_count(prog.modules.filter_by(id=module_id)) > 0:
                return True

        return False

    def validate_periods(self, minimum_expected=0):
        # ensure that there is at least one period definition record, and that all records in the database
        # have ascending serial numbers
        modified: bool = False

        if (
            self.periods is None or get_count(self.periods) == 0
        ) and minimum_expected > 0:
            if current_user is not None:
                data = SubmissionPeriodDefinition(
                    owner_id=self.id,
                    period=1,
                    name=None,
                    number_markers=1 if self.uses_marker else 0,
                    number_moderators=1 if self.uses_moderator else 0,
                    start_date=None,
                    has_presentation=self.uses_presentations,
                    collect_presentation_feedback=True,
                    collect_project_feedback=True,
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now(),
                )
                self.periods = [data]
                modified = True
            else:
                raise RuntimeError("Cannot insert missing SubmissionPeriodDefinition")

        expected = 1
        for item in self.periods.order_by(
            SubmissionPeriodDefinition.period.asc()
        ).all():
            if item.period != expected:
                item.period = expected
                modified = True

            expected += 1

        return modified

    def validate_presentations(self):
        if not self.uses_presentations:
            return False

        modified: bool = False

        modified = self.validate_periods(minimum_expected=1) or modified
        number_with_presentations = get_count(
            self.periods.filter_by(has_presentation=True)
        )

        if number_with_presentations > 0:
            return modified

        data = self.periods.first()
        data.has_presentation = True
        modified = True

        return modified

    def maintenance(self):
        modified = False

        # no need to invoke validate_periods() separately since this is done as part of
        # validate_presentations()
        modified = self.validate_presentations() or modified

        return modified


@listens_for(ProjectClass, "before_update")
def _ProjectClass_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)
        cache.delete_memoized(_Project_num_supervisors)


@listens_for(ProjectClass, "before_insert")
def _ProjectClass_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)
        cache.delete_memoized(_Project_num_supervisors)


@listens_for(ProjectClass, "before_delete")
def _ProjectClass_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)
        cache.delete_memoized(_Project_num_supervisors)


class SubmissionPeriodDefinition(db.Model, EditingMetadataMixin):
    """
    Record the configuration of an individual submission period
    """

    __tablename__ = "period_definitions"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # link to parent ProjectClass
    owner_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"))
    owner = db.relationship(
        "ProjectClass",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "periods", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # numerical submission period
    period = db.Column(db.Integer())

    # optional start date - purely for UI purposes
    start_date = db.Column(db.Date())

    # alternative textual name; can be left null if not used
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # MARKING SUPPORT

    # number of markers to be assigned
    number_markers = db.Column(db.Integer(), default=1)

    # number of moderators to be assigned
    number_moderators = db.Column(db.Integer(), default=0)

    # PERIOD CONFIGURATION

    # does this period have a presentation submission?
    has_presentation = db.Column(db.Boolean())

    # if using a presentation, does it require lecture capture?
    lecture_capture = db.Column(db.Boolean())

    # if using a presentation, number of faculty assessors to schedule per session
    number_assessors = db.Column(db.Integer())

    # target number of students per group
    max_group_size = db.Column(db.Integer())

    # morning session times, eg 10am-12pm
    morning_session = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # afternoon session times, eg 2pm-4pm
    afternoon_session = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # talk format
    talk_format = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # use platform to collect presentation feedback?
    collect_presentation_feedback = db.Column(db.Boolean(), default=True)

    # use platform to collect project feedback online?
    collect_project_feedback = db.Column(db.Boolean(), default=True)

    def display_name(self, year):
        if isinstance(year, int):
            pass
        elif isinstance(year, float):
            year = int(year)
        else:
            year = year.year

        if self.name is not None and len(self.name) > 0:
            return str(self.name).format(year1=year, year2=year + 1)

        return "Submission Period #{n}".format(n=self.period)


SubmissionPeriodDefinitionLike = Union[SubmissionPeriodDefinition, int]


def _get_submission_period(
    period: SubmissionPeriodDefinitionLike, pclass: ProjectClass
) -> Optional[SubmissionPeriodDefinition]:
    if period is None:
        return None

    if isinstance(period, SubmissionPeriodDefinition):
        return period

    if isinstance(period, int):
        return pclass.get_period(period)

    raise RuntimeError(
        f'Could not convert identifier "{period}" to SubmissionPeriodDefinition instance'
    )


class ProjectClassConfig(
    db.Model,
    ConvenorTasksMixinFactory(ConvenorGenericTask),
    SelectorLifecycleStatesMixin,
    SubmitterLifecycleStatesMixin,
):
    """
    Model current configuration options for each project class
    """

    # make table name plural
    __tablename__ = "project_class_config"

    # id is really a surrogate key for (year, pclass_id) - need to ensure these remain unique
    id = db.Column(db.Integer(), primary_key=True)

    # year should match an available year in MainConfig
    year = db.Column(db.Integer(), db.ForeignKey("main_config.year"))
    main_config = db.relationship(
        "MainConfig",
        uselist=False,
        foreign_keys=[year],
        backref=db.backref("project_classes", lazy="dynamic"),
    )

    # id should be an available project class
    pclass_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"))
    project_class = db.relationship(
        "ProjectClass",
        uselist=False,
        foreign_keys=[pclass_id],
        backref=db.backref("configs", lazy="dynamic"),
    )

    # who was convenor in this year?
    convenor_id = db.Column(db.Integer(), db.ForeignKey("faculty_data.id"))
    convenor = db.relationship(
        "FacultyData",
        uselist=False,
        foreign_keys=[convenor_id],
        backref=db.backref("past_convenorships", lazy="dynamic"),
    )

    # who created this record, i.e., initiated the rollover of the academic year?
    creator_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    created_by = db.relationship("User", uselist=False, foreign_keys=[creator_id])

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # LOCAL CONFIGURATION

    # these settings replicate settings in ProjectClass (for where they are inherited if nothing else is done),
    # but we need local copies in case the display or marking settings change from year to year

    # are projects supervised (or just marked?)
    uses_supervisor = db.Column(db.Boolean())

    # are submissions marked?
    uses_marker = db.Column(db.Boolean())

    # are submissions moderated?
    uses_moderator = db.Column(db.Boolean())

    # display second marker information in UI?
    display_marker = db.Column(db.Boolean())

    # are there presentations?
    uses_presentations = db.Column(db.Boolean())

    # display presentation information in UI?
    display_presentations = db.Column(db.Boolean())

    # CANVAS INTEGRATION

    # Canvas id for the module corresponding to this ProjectClassConfig
    canvas_module_id = db.Column(db.Integer(), default=None, nullable=True)

    # Link to FacultyData record for convenor whose access token we are using
    canvas_login_id = db.Column(db.Integer(), db.ForeignKey("faculty_data.id"))
    canvas_login = db.relationship(
        "FacultyData",
        uselist=False,
        foreign_keys=[canvas_login_id],
        backref=db.backref("canvas_logins", lazy="dynamic"),
    )

    # invalidate cached course URL if is changed
    @validates("canvas_module_id")
    def _validate_canvas_module_id(self, key, value):
        self._canvas_course_URL = None
        return value

    # SELECTOR LIFECYCLE MANAGEMENT

    # are faculty requests to confirm projects open?
    requests_issued = db.Column(db.Boolean(), default=False)

    # who issued confirmation requests?
    requests_issued_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    requests_issued_by = db.relationship(
        "User", uselist=False, foreign_keys=[requests_issued_id]
    )

    # requests issued timestamp
    requests_timestamp = db.Column(db.DateTime())

    # deadline for confirmation requests
    request_deadline = db.Column(db.Date())

    # have we skipped confirmation requests?
    requests_skipped = db.Column(db.Boolean(), default=False)

    # who skipped them?
    requests_skipped_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    requests_skipped_by = db.relationship(
        "User", uselist=False, foreign_keys=[requests_skipped_id]
    )

    # requests skipped timestamp
    requests_skipped_timestamp = db.Column(db.DateTime())

    # have we gone 'live' this year, ie. frozen a definitive 'live table' of projects and
    # made these available to students?
    live = db.Column(db.Boolean())

    # who signed-off on go live event?
    golive_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    golive_by = db.relationship("User", uselist=False, foreign_keys=[golive_id])

    # golive timestamp
    golive_timestamp = db.Column(db.DateTime())

    # golive record of email notifications
    golive_notified = db.relationship("User", secondary=golive_emails, lazy="dynamic")

    # deadline for students to make their choices on the live system
    live_deadline = db.Column(db.Date())

    # should we accommodate an existing matching when offering projects?
    accommodate_matching_id = db.Column(
        db.Integer(), db.ForeignKey("matching_attempts.id")
    )
    accommodate_matching = db.relationship(
        "MatchingAttempt",
        uselist=False,
        foreign_keys=[accommodate_matching_id],
        backref=db.backref("accommodations", lazy="dynamic"),
    )

    # if an existing match is being accommodated, the maximum number of CATS a supervisor can carry
    # before they are regarded as "full"
    full_CATS = db.Column(db.Integer())

    # is project selection closed?
    selection_closed = db.Column(db.Boolean())

    # who signed-off on close event?
    closed_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    closed_by = db.relationship("User", uselist=False, foreign_keys=[closed_id])

    # closed timestamp
    closed_timestamp = db.Column(db.DateTime())

    # list the faculty members who we are still requiring to sign-off on their projects for this configuration
    confirmation_required = db.relationship(
        "FacultyData",
        secondary=golive_confirmation,
        lazy="dynamic",
        backref=db.backref("confirmation_outstanding", lazy="dynamic"),
    )

    # SUBMISSION LIFECYCLE MANAGEMENT

    # current submission period
    submission_period = db.Column(db.Integer())

    # 'periods' member constructed by backreference from SubmissionPeriodRecord below

    # STUDENTS

    # 'selectors' member constructed by backreference from SelectingStudent

    # 'submitters' member constructed by backreference from SubmittingStudent

    # MATCHING

    # override participation in automatic matching, just for this instance
    skip_matching = db.Column(db.Boolean(), default=False)

    # WORKLOAD MODEL

    # CATS awarded for supervising in this year
    CATS_supervision = db.Column(db.Integer())

    # CATS awarded for marking in this year
    CATS_marking = db.Column(db.Integer())

    # CATS awarded for moderating in this year
    CATS_moderation = db.Column(db.Integer())

    # CATS awarded for presentation assessment in this year
    CATS_presentation = db.Column(db.Integer())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._canvas_course_URL = None

    @orm.reconstructor
    def _reconstruct(self):
        self._canvas_course_URL = None

    @property
    def messages(self):
        messages = []

        if self.main_config.enable_canvas_sync:
            if self.canvas_enabled:
                messages.append("Canvas integration enabled")
            else:
                if not self.canvas_module_id:
                    messages.append("Canvas module identifier not set")
                if not self.canvas_login:
                    messages.append("Canvas login identifier not set")

        if self.do_matching:
            messages.append("Use automated matching")

        if self.skip_matching:
            messages.append("Skip matching this cycle")

        if self.requests_skipped:
            messages.append("Skip confirmation requests this cycle")

        if self.require_confirm:
            messages.append("Requires project confirmation")

        messages.append("Initial choices={m}".format(m=self.initial_choices))
        messages.append("Switch choices={m}".format(m=self.switch_choices))
        messages.append(
            "Max selectable projects with same supervisor={m}".format(
                m=self.faculty_maximum
            )
        )
        messages.append(
            "Start year Y{m} {level}".format(
                m=self.start_year,
                level=self.project_class._level_text(self.student_level),
            )
        )
        messages.append("Extent={m}".format(m=self.extent))

        if self.selection_open_to_all:
            messages.append("Selection open to all")
        else:
            messages.append("Selection by invitation")

        if self.full_CATS:
            messages.append("Max CATS for accommodation={m}".format(m=self.full_CATS))

        return messages

    def _outstanding_descriptions_generator(self, faculty: FacultyData):
        if not isinstance(faculty, FacultyData) or faculty is None:
            raise RuntimeError("FacultyData object could not be loaded or interpreted")

        # have to use list of projects offered for the pclass and then the
        # get_description() method of Project in order to account for possible defaults
        projects = faculty.projects_offered(self.pclass_id)

        # express as generators so that the elements are not computed unless they are used
        descs = (p.get_description(self.pclass_id) for p in projects)
        outstanding = (d.id for d in descs if d is not None and not d.confirmed)

        return outstanding

    def project_confirmations_outstanding(self, faculty):
        # confirmation not required if project class doesn't use it
        if not self.project_class.require_confirm:
            return []

        # confirmation not required until requests have been issued
        if not self.requests_issued:
            return []

        # if we are already live, or requests are marked as skipped, then confirmation also not required
        if self.live or self.requests_skipped:
            return []

        if isinstance(faculty, User):
            fac_data = faculty.faculty_data
        elif isinstance(faculty, int):
            fac_data = db.session.query(FacultyData).filter_by(id=faculty).first()
        else:
            fac_data = faculty

        if not isinstance(fac_data, FacultyData) or fac_data is None:
            raise RuntimeError("FacultyData object could not be loaded or interpreted")

        # have to use list of projects offered for the pclass and then the
        # get_description() method of Project in order to account for possible defaults
        projects = fac_data.projects_offered(self.pclass_id)

        # express as generators so that the elements are not computed unless they are used
        descs = [p.get_description(self.pclass_id) for p in projects]
        outstanding = [d.parent for d in descs if d is not None and not d.confirmed]

        return outstanding

    def number_confirmations_outstanding(self, faculty):
        if isinstance(faculty, User):
            fac_data = faculty.faculty_data
        elif isinstance(faculty, int):
            fac_data = db.session.query(FacultyData).filter_by(id=faculty).first()
        else:
            fac_data = faculty

        # confirmation not required if faculty member is on sabbatical from this project type
        record = fac_data.get_enrollment_record(self.pclass_id)
        if (
            record is not None
            and record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED
        ):
            return 0

        # confirmation not required if project class doesn't use it
        if not self.project_class.require_confirm:
            return 0

        # confirmation not required until requests have been issued
        if not self.requests_issued:
            return 0

        # if we are already live, or requests are marked as skipped, then confirmation also not required
        if self.live or self.requests_skipped:
            return 0

        return len(set(self._outstanding_descriptions_generator(fac_data)))

    def has_confirmations_outstanding(self, faculty):
        """
        Accepts a faculty descriptor (possibly a FacultyData id, a User instance or a FacultyData instance)
        and determines whether there are any project descriptions for this faculty member, attached to the
        current project class, which do not have the .confirm flag set
        :param faculty:
        :return:
        """
        if isinstance(faculty, User):
            fac_data = faculty.faculty_data
        elif isinstance(faculty, int):
            fac_data = db.session.query(FacultyData).filter_by(id=faculty).first()
        else:
            fac_data = faculty

        # confirmation not required if faculty member is on sabbatical from this project type
        record = fac_data.get_enrollment_record(self.pclass_id)
        if (
            record is not None
            and record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED
        ):
            return False

        # confirmation not required if project class doesn't use it
        if not self.project_class.require_confirm:
            return False

        # confirmation not required until requests have been issued
        if not self.requests_issued:
            return False

        # if we are already live, or requests are marked as skipped, then confirmation also not required
        if self.live or self.requests_skipped:
            return False

        gen = self._outstanding_descriptions_generator(fac_data)
        try:
            item = next(gen)
        except StopIteration:
            return False

        return True

    def is_confirmation_required(self, faculty):
        """
        Accepts a faculty descriptor (possibly a FacultyData id, a User instance or a FacultyData instance)
        and determines whether we are still waiting for confirmation from this faculty member.
        Returns True if either: the faculty member is present in the list of faculty who have not
        given confirmation (self.confirmation_required), or if self.has_confirmations_outstanding(faculty)
        returns True. self.has_confirmations_outstanding() will check for project descriptions that
        do not have the .confirm flag set
        :param faculty: proxy for FacultyData instance
        :return:
        """
        # confirmation not required if project class doesn't use it
        if not self.project_class.require_confirm:
            return False

        # confirmation not required until requests have been issued
        if not self.requests_issued:
            return False

        # if we are already live, or requests are marked as skipped, then confirmation also not required
        if self.live or self.requests_skipped:
            return False

        if isinstance(faculty, User):
            fac_data = faculty.faculty_data
        elif isinstance(faculty, int):
            fac_data = db.session.query(FacultyData).filter_by(id=faculty).first()
        else:
            fac_data = faculty

        if not isinstance(fac_data, FacultyData) or fac_data is None:
            raise RuntimeError("FacultyData object could not be loaded or interpreted")

        # confirmation required if there are outstanding project descriptions needing confirmation,
        # or if this user hasn't yet given confirmation for this ProjectClassConfig
        return (
            self.has_confirmations_outstanding(fac_data.id)
            or get_count(self.confirmation_required.filter_by(id=fac_data.id)) > 0
        )

    def mark_confirmed(self, faculty, message=False):
        if isinstance(faculty, User):
            fac_data = faculty.faculty_data
        elif isinstance(faculty, int):
            fac_data = db.session.query(FacultyData).filter_by(id=faculty).first()
        else:
            fac_data = faculty

        if not isinstance(fac_data, FacultyData) or fac_data is None:
            raise RuntimeError("FacultyData object could not be loaded or interpreted")

        projects = fac_data.projects_offered(self.pclass_id)
        for p in projects:
            p.mark_confirmed(self.pclass_id)

        messages = []
        if fac_data in self.confirmation_required:
            self.confirmation_required.remove(fac_data)

            if message:
                messages.append(
                    (
                        "Thank you for confirming that your projects belonging to "
                        'class "{name}" are ready to publish.'.format(
                            name=self.project_class.name
                        ),
                        "info",
                    )
                )

        return messages

    @property
    def _faculty_waiting_confirmation_generator(self):
        # build a list of faculty members who are enrolled as active supervisors
        faculty = (
            db.session.query(FacultyData)
            .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id)
            .filter(
                EnrollmentRecord.pclass_id == self.pclass_id,
                EnrollmentRecord.supervisor_state
                == EnrollmentRecord.SUPERVISOR_ENROLLED,
            )
            .join(User, User.id == FacultyData.id)
            .filter(User.active)
            .all()
        )

        # return a generator that loops through all these faculty, if they satisfy the
        # .is_confirmation_required() property
        return (
            f for f in faculty if f is not None and self.is_confirmation_required(f)
        )

    @property
    def faculty_waiting_confirmation(self):
        return list(self._faculty_waiting_confirmation_generator)

    @property
    def confirm_outstanding_count(self):
        return len(self.faculty_waiting_confirmation)

    @property
    def has_pending_confirmations(self):
        gen = self._faculty_waiting_confirmation_generator

        try:
            item = next(gen)
        except StopIteration:
            return False

        return True

    def no_explicit_confirm(self, faculty):
        if isinstance(faculty, User):
            fac_data = faculty.faculty_data
        elif isinstance(faculty, int):
            fac_data = db.session.query(FacultyData).filter_by(id=faculty).first()
        else:
            fac_data = faculty

        if not isinstance(fac_data, FacultyData) or fac_data is None:
            raise RuntimeError("FacultyData object could not be loaded or interpreted")

        if fac_data in self.confirmation_required:
            return True

        return False

    @property
    def name(self):
        return self.project_class.name

    @property
    def abbreviation(self):
        return self.project_class.abbreviation

    @property
    def student_level(self):
        return self.project_class.student_level

    @property
    def is_optional(self):
        return self.project_class.is_optional

    @property
    def uses_selection(self):
        return self.project_class.uses_selection

    @property
    def uses_submission(self):
        return self.project_class.uses_submission

    @property
    def do_matching(self):
        return self.project_class.do_matching and not self.skip_matching

    @property
    def require_confirm(self):
        return self.project_class.require_confirm

    @property
    def initial_choices(self):
        return self.project_class.initial_choices

    @property
    def allow_switching(self):
        return self.project_class.allow_switching

    @property
    def switch_choices(self):
        return self.project_class.switch_choices

    @property
    def faculty_maximum(self):
        return self.project_class.faculty_maximum

    @property
    def start_year(self):
        return self.project_class.start_year

    @property
    def select_year_a(self):
        if self.select_in_previous_cycle:
            return self.year + 1

        return self.year

    @property
    def select_year_b(self):
        if self.select_in_previous_cycle:
            return self.year + 2

        return self.year + 1

    @property
    def submit_year_a(self):
        return self.year

    @property
    def submit_year_b(self):
        return self.year + 1

    @property
    def extent(self):
        return self.project_class.extent

    @property
    def select_in_previous_cycle(self):
        return self.project_class.select_in_previous_cycle

    @property
    def number_submissions(self):
        return self.project_class.number_submissions

    @property
    def selection_open_to_all(self):
        return self.project_class.selection_open_to_all

    @property
    def auto_enrol_enable(self):
        return self.project_class.auto_enrol_enable

    @property
    def auto_enroll_years(self):
        return self.project_class.auto_enroll_years

    @property
    def advertise_research_group(self):
        return self.project_class.advertise_research_group

    @property
    def use_project_tags(self):
        return self.project_class.use_project_tags

    @property
    def force_tag_groups(self):
        return self.project_class.force_tag_groups

    @property
    def supervisor_carryover(self):
        return self.project_class.supervisor_carryover

    @property
    def include_available(self):
        return self.project_class.include_available

    @property
    def programmes(self):
        return self.project_class.programmes

    @property
    def ordered_programmes(self):
        return self.project_class.ordered_programmes

    @property
    def template_periods(self):
        return self.project_class.periods.order_by(
            SubmissionPeriodDefinition.period.asc()
        )

    @property
    def card_text_normal(self):
        return self.project_class.card_text_normal

    @property
    def card_text_optional(self):
        return self.project_class.card_text_optional

    @property
    def card_text_noninitial(self):
        return self.project_class.card_text_noninitial

    @property
    def email_text_draft_match_preamble(self):
        return self.project_class.email_text_draft_match_preamble

    @property
    def email_text_final_match_preamble(self):
        return self.project_class.email_text_final_match_preamble

    @property
    def get_blocking_tasks(self):
        from .live_projects import SelectingStudent, SubmittingStudent

        selectors: List[SelectingStudent] = self.selecting_students.filter(
            SelectingStudent.tasks.any(
                and_(
                    ~ConvenorSelectorTask.complete,
                    ~ConvenorSelectorTask.dropped,
                    ConvenorSelectorTask.blocking,
                )
            )
        ).all()

        selector_tasks = []
        for sel in selectors:
            tks = sel.tasks.filter(
                and_(
                    ~ConvenorSelectorTask.complete,
                    ~ConvenorSelectorTask.dropped,
                    ConvenorSelectorTask.blocking,
                )
            ).all()
            selector_tasks.extend(tks)

        submitters: List[SubmittingStudent] = self.submitting_students.filter(
            SubmittingStudent.tasks.any(
                and_(
                    ~ConvenorSubmitterTask.complete,
                    ~ConvenorSubmitterTask.dropped,
                    ConvenorSubmitterTask.blocking,
                )
            )
        ).all()

        submitter_tasks = []
        for sub in submitters:
            tks = sub.tasks.filter(
                and_(
                    ~ConvenorSubmitterTask.complete,
                    ~ConvenorSubmitterTask.dropped,
                    ConvenorSubmitterTask.blocking,
                )
            ).all()
            submitter_tasks.extend(tks)

        global_tasks: List[ConvenorGenericTask] = self.tasks.filter(
            and_(
                ~ConvenorGenericTask.complete,
                ~ConvenorGenericTask.dropped,
                ConvenorGenericTask.blocking,
            )
        ).all()

        tasks = {
            "selector": selector_tasks,
            "submitter": submitter_tasks,
            "global": global_tasks,
        }

        num_tasks = len(selector_tasks) + len(submitter_tasks) + len(global_tasks)

        return tasks, num_tasks

    @property
    def _selection_open(self):
        return self.live and not self.selection_closed

    @property
    def _previous_config_query(self):
        return db.session.query(ProjectClassConfig).filter_by(
            year=self.year - 1, pclass_id=self.pclass_id
        )

    @property
    def previous_config(self):
        return self._previous_config_query.first()

    @property
    def selector_lifecycle(self):
        # an unpublished project class is always ready for rollover
        if not self.project_class.publish:
            return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER

        # if gone live and closed, then either we are ready to match or we are ready to rollover
        if self.live and self.selection_closed:
            if self.do_matching and self.select_in_previous_cycle:
                # check whether a matching configuration has been assigned for the current year
                match = self.allocated_match

                if match is not None:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER
                else:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING

            else:
                return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER

        # open case is simple
        if self._selection_open:
            return ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN

        # if we get here, project is not open for selection
        if self.require_confirm:
            if self.requests_skipped:
                return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE

            if self.requests_issued:
                if self.has_pending_confirmations:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
                else:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE

            else:
                return ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED

        return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE

    @property
    def submitter_lifecycle(self):
        # an unpublished project class is always ready for rollover
        if not self.project_class.publish:
            return ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER

        if self.submission_period > self.number_submissions:
            return ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER

        # get submission period data for current period
        period = self.current_period

        if period is None:
            t = self.template_periods.filter_by(period=self.submission_period).one()

            # allow period record to be auto-generated
            period = SubmissionPeriodRecord(
                config_id=self.id,
                name=t.name,
                number_markers=t.number_markers,
                number_moderators=t.number_moderators,
                start_date=t.start_date,
                has_presentation=t.has_presentation,
                lecture_capture=t.lecture_capture,
                collect_presentation_feedback=t.collect_presentation_feedback,
                collect_project_feedback=t.collect_project_feedback,
                number_assessors=t.number_assessors,
                max_group_size=t.max_group_size,
                morning_session=t.morning_session,
                afternoon_session=t.afternoon_session,
                talk_format=t.talk_format,
                retired=False,
                submission_period=self.submission_period,
                feedback_open=False,
                feedback_id=None,
                feedback_timestamp=None,
                feedback_deadline=None,
                closed=False,
                closed_id=None,
                closed_timestamp=None,
                canvas_module_id=None,
                canvas_assignment_id=None,
            )
            db.session.add(period)
            db.session.commit()

        if not period.is_feedback_open:
            return self.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY

        if period.is_feedback_open and not period.closed:
            return self.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY

        # can assume period.closed at this point
        if self.submission_period >= self.number_submissions:
            return ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER

        # we don't want to be in this position; we may as well advance the submission period
        # and return PROJECT_ACTIVITY
        self.submission_period += 1
        db.session.commit()

        return ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY

    def rollover_ready(self, current_year: Optional[int]) -> bool:
        if current_year is None:
            current_year = _get_current_year()

        selector_status = self.selector_lifecycle
        submitter_status = self.submitter_lifecycle

        if self.year >= current_year:
            return False

        if (
            selector_status
            != SelectorLifecycleStatesMixin.SELECTOR_LIFECYCLE_READY_ROLLOVER
        ):
            return False

        if (
            submitter_status
            != SubmitterLifecycleStatesMixin.SUBMITTER_LIFECYCLE_READY_ROLLOVER
        ):
            return False

        return True

    @property
    def allocated_match(self):
        return self.matching_attempts.filter_by(selected=True).first()

    @property
    def time_to_request_deadline(self) -> Optional[str]:
        if self.request_deadline is None:
            return None

        today = date.today()
        if today > self.request_deadline:
            return "in the past"

        delta = self.request_deadline - today
        return format_readable_time(delta)

    @property
    def time_to_live_deadline(self) -> Optional[str]:
        if self.live_deadline is None:
            return None

        today = date.today()
        if today > self.live_deadline:
            return "in the past"

        delta = self.live_deadline - today
        return format_readable_time(delta)

    @property
    def number_selectors(self):
        from .live_projects import SelectingStudent

        query = db.session.query(SelectingStudent).with_parent(self)
        return get_count(query)

    @property
    def number_submitters(self):
        from .live_projects import SubmittingStudent

        query = db.session.query(SubmittingStudent).with_parent(self)
        return get_count(query)

    @property
    def selector_data(self):
        """
        Report simple statistics about selectors attached to this ProjectClassConfig instance.

        **
        BEFORE SELECTIONS ARE CLOSED,
        we report the total number of selectors, the number who have already made submissions, the number who have
        bookmarks but have not yet made a submission, the number who are entirely missing.

        AFTER SELECTIONS ARE CLOSED,
        we report the total number of selectors, the number who made submissions,
        and the number who are entirely missing. This is because bookmarks are converted to SelectionRecords
        on project closure, if possible (ie. the bookmarks formed a valid submission).
        :return:
        """

        if self.selector_lifecycle < self.SELECTOR_LIFECYCLE_READY_MATCHING:
            return self._open_selector_data()

        return self._closed_selector_data()

    def _open_selector_data(self):
        total = 0
        submitted = 0
        bookmarks = 0
        missing = 0

        for student in self.selecting_students:
            total += 1

            if student.has_submitted:
                submitted += 1

            if not student.has_submitted and student.has_bookmarks:
                bookmarks += 1

            if not student.has_submitted and not student.has_bookmarks:
                missing += 1

        return {
            "have_submitted": submitted,
            "have_bookmarks": bookmarks,
            "missing": missing,
            "total": total,
        }

    def _closed_selector_data(self):
        total = 0
        submitted = 0
        missing = 0

        for student in self.selecting_students:
            total += 1

            if student.has_submitted:
                submitted += 1
            else:
                missing += 1

        return {"have_submitted": submitted, "missing": missing, "total": total}

    def most_popular_projects(
        self, limit: int = 5, compare_interval: Optional[timedelta] = timedelta(days=3)
    ):
        popularity_subq = (
            db.session.query(
                PopularityRecord.liveproject_id.label("popq_liveproject_id"),
                func.max(PopularityRecord.datestamp).label("popq_datestamp"),
            )
            .filter(PopularityRecord.score_rank != None)
            .group_by(PopularityRecord.liveproject_id)
            .subquery()
        )

        # could base query on self.live_projects, but that would apparently require a subquery (because of the .select_from()),
        # and so to avoid that we filter directly from LiveProjects
        from .live_projects import LiveProject

        query = (
            db.session.query(LiveProject, PopularityRecord)
            .select_from(LiveProject)
            .filter(LiveProject.config_id == self.id)
            .join(FacultyData, FacultyData.id == LiveProject.owner_id, isouter=True)
            .join(User, User.id == FacultyData.id, isouter=True)
            .join(
                popularity_subq,
                popularity_subq.c.popq_liveproject_id == LiveProject.id,
                isouter=True,
            )
            .join(
                PopularityRecord,
                and_(
                    PopularityRecord.liveproject_id
                    == popularity_subq.c.popq_liveproject_id,
                    PopularityRecord.datestamp == popularity_subq.c.popq_datestamp,
                ),
                isouter=True,
            )
            .order_by(PopularityRecord.score_rank.asc())
            .limit(limit)
        )

        now: datetime = datetime.now()
        compare_cutoff: datetime = (
            now - compare_interval if compare_interval is not None else None
        )

        def _build_item(p: LiveProject, pr: Optional[PopularityRecord]):
            if pr is None:
                return None

            data = {
                "project": p,
                "score_rank": pr.score_rank,
                "bookmarks": pr.bookmarks,
                "views": pr.views,
                "selections": pr.selections,
            }

            if compare_interval is not None:
                compare_pr: PopularityRecord = (
                    db.session.query(PopularityRecord)
                    .filter(
                        PopularityRecord.liveproject_id == p.id,
                        PopularityRecord.datestamp <= compare_cutoff,
                    )
                    .order_by(PopularityRecord.datestamp.desc())
                    .first()
                )
                if compare_pr is not None:
                    compare = {
                        "score_rank": compare_pr.score_rank,
                        "bookmarks": compare_pr.bookmarks,
                        "views": compare_pr.views,
                        "selections": compare_pr.selections,
                    }

                    def compute_delta(a, b):
                        if a is None or b is None:
                            return None

                        return a - b

                    delta = {
                        "score_rank": compute_delta(
                            pr.score_rank, compare_pr.score_rank
                        ),
                        "bookmarks": compute_delta(pr.bookmarks, compare_pr.bookmarks),
                        "views": compute_delta(pr.views, compare_pr.views),
                        "selections": compute_delta(
                            pr.selections, compare_pr.selections
                        ),
                    }

                    data.update({"compare": compare, "delta": delta})

            return data

        items = [_build_item(*p) for p in query]
        return [x for x in items if x is not None]

    @property
    def convenor_email(self):
        if self.convenor is not None and self.convenor.user is not None:
            return self.convenor.user.email
        else:
            raise RuntimeError("convenor not set")

    @property
    def convenor_name(self):
        if self.convenor is not None and self.convenor.user is not None:
            return self.convenor.user.name
        else:
            raise RuntimeError("convenor not set")

    @property
    def convenor_simple_name(self):
        if self.convenor is not None and self.convenor.user is not None:
            return self.convenor.user.simple_name
        else:
            raise RuntimeError("convenor not set")

    @property
    def published_matches(self):
        return self.matching_attempts.filter_by(published=True)

    @property
    def has_published_matches(self):
        return get_count(self.published_matches) > 0

    @property
    def published_schedules(self):
        from .assessment import PresentationAssessment
        from .scheduling import ScheduleAttempt

        # determine whether any of our periods have published schedules
        query = (
            db.session.query(ScheduleAttempt)
            .filter_by(published=True)
            .join(
                PresentationAssessment,
                PresentationAssessment.id == ScheduleAttempt.owner_id,
            )
            .join(
                assessment_to_periods,
                assessment_to_periods.c.assessment_id == PresentationAssessment.id,
            )
            .join(
                SubmissionPeriodRecord,
                SubmissionPeriodRecord.id == assessment_to_periods.c.period_id,
            )
            .filter(SubmissionPeriodRecord.config_id == self.id)
        )

        return query

    @property
    def has_auditable_schedules(self):
        # auditable schedules are published schedules for a PresentationAssessment that isn't deployed
        for period in self.periods:
            if not period.has_presentation:
                continue

            assessment = period.presentation_assessments.first()
            if assessment is None:
                continue

            if assessment.is_deployed:
                continue

            if assessment.has_published_schedules:
                return True

        return False

    def get_period(self, n):
        # note submission periods start at 1
        if n is None or n <= 0 or n > self.number_submissions:
            return None

        return self.periods.filter_by(submission_period=n).first()

    @property
    def ordered_periods(self):
        return self.periods.order_by(SubmissionPeriodRecord.submission_period.asc())

    @property
    def current_period(self):
        return self.get_period(self.submission_period)

    @property
    def all_markers_assigned(self):
        return all([p.all_markers_assigned for p in self.periods])

    @property
    def all_supervisors_assigned(self):
        return all([p.all_supervisors_assigned for p in self.periods])

    def number_supervisor_records(self, faculty) -> int:
        return sum(p.number_supervisor_records(faculty) for p in self.periods)

    @property
    def canvas_enabled(self):
        return (
            self.main_config.enable_canvas_sync
            and self.canvas_module_id is not None
            and self.canvas_login is not None
        )

    @property
    def canvas_root_URL(self):
        main_config: MainConfig = self.main_config
        return main_config.canvas_root_URL

    @property
    def canvas_course_URL(self):
        if self._canvas_course_URL is not None:
            return self._canvas_course_URL

        URL_root = self.canvas_root_URL
        course_URL = urljoin(
            URL_root, "courses/{course_id}/".format(course_id=self.canvas_module_id)
        )
        self._canvas_course_URL = url_normalize(course_URL)

        return self._canvas_course_URL


@listens_for(ProjectClassConfig, "before_insert")
def _ProjectClassConfig_insert_handler(mapper, connection, target: ProjectClassConfig):
    with db.session.no_autoflush:
        if target.project_class is not None:
            target.project_class._most_recent_config = None
        else:
            pclass = (
                db.session.query(ProjectClass)
                .filter(ProjectClass.id == target.pclass_id)
                .first()
            )
            if pclass is not None:
                pclass._most_recent_config = None


@listens_for(ProjectClassConfig, "before_delete")
def _ProjectClassConfig_delete_handler(mapper, connection, target: ProjectClassConfig):
    with db.session.no_autoflush:
        if target.project_class is not None:
            target.project_class._most_recent_config = None
        else:
            pclass = (
                db.session.query(ProjectClass)
                .filter(ProjectClass.id == target.pclass_id)
                .first()
            )
            if pclass is not None:
                pclass._most_recent_config = None


class SubmissionPeriodRecord(db.Model):
    """
    Capture details about a submission period
    """

    __tablename__ = "submission_periods"

    id = db.Column(db.Integer(), primary_key=True)

    # parent ProjectClassConfig
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        foreign_keys=[config_id],
        uselist=False,
        backref=db.backref(
            "periods", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # submission period
    # note this does not directly link to SubmissionPeriodDefinition; it's a literal number that refers
    # to the numerical position of the SubmissionPeriodDefinition record, but it isn't a link to the
    # SubmissionPeriodDefinition primary key
    submission_period = db.Column(db.Integer(), index=True)

    # optional start date
    start_date = db.Column(db.Date())

    # optional hand-in date
    hand_in_date = db.Column(db.Date())

    # alternative textual name for this period (eg. "Autumn Term", "Spring Term");
    # can be null if not used
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # MARKING SUPPORT

    # number of markers to be assigned
    number_markers = db.Column(db.Integer(), default=1)

    # number of moderators to be assigned
    number_moderators = db.Column(db.Integer(), default=0)

    # PRESENTATION DATA, IF USED

    # does this submission period have an associated presentation assessment?
    has_presentation = db.Column(db.Boolean())

    # if using a presentation, does it require lecture capture?
    lecture_capture = db.Column(db.Boolean())

    # if using a presentation, number of faculty assessors to schedule per session
    number_assessors = db.Column(db.Integer())

    # target number of students per group;
    max_group_size = db.Column(db.Integer())

    # morning session times, eg 10am-12pm
    morning_session = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # afternoon session times, eg 2pm-4pm
    afternoon_session = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # talk format
    talk_format = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # FEEDBACK COLLECTION

    # use platform to collect presentation feedback?
    collect_presentation_feedback = db.Column(db.Boolean(), default=True)

    # use platform to collect project feedback?
    collect_project_feedback = db.Column(db.Boolean(), default=True)

    # LIFECYCLE DATA

    # retired flag, set by rollover code
    retired = db.Column(db.Boolean(), index=True)

    # has feedback been opened in this period
    feedback_open = db.Column(db.Boolean())

    # who opened feedback?
    feedback_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    feedback_by = db.relationship("User", uselist=False, foreign_keys=[feedback_id])

    # feedback opened timestamp
    feedback_timestamp = db.Column(db.DateTime())

    # deadline for feedback to be submitted
    feedback_deadline = db.Column(db.DateTime())

    # has this period been closed?
    closed = db.Column(db.Boolean())

    # who closed the period?
    closed_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    closed_by = db.relationship("User", uselist=False, foreign_keys=[closed_id])

    # closed timestamp
    closed_timestamp = db.Column(db.DateTime())

    # CANVAS INTEGRATION

    # Canvas id for the module used to submit to this submission period
    canvas_module_id = db.Column(db.Integer(), default=None, nullable=True)

    # Canvas id for the assignment matching this submission period
    canvas_assignment_id = db.Column(db.Integer(), default=None, nullable=True)

    # invalidate cached course URL if Canvas details are changed
    @validates("canvas_module_id")
    def _validate_canvas_module_id(self, key, value):
        self._canvas_assignment_URL = None
        return value

    @validates("canvas_assignment_id")
    def _validate_canvas_assignment_id(self, key, value):
        self._canvas_assignment_URL = None
        return value

    # SUBMISSION RECORDS

    # 'submissions' generated by back-reference from SubmissionRecord

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._canvas_assignment_URL = None

    @orm.reconstructor
    def _reconstruct(self):
        self._canvas_assignment_URL = None

    @property
    def messages(self):
        messages = []

        messages.append("Markers={m}".format(m=self.number_markers))
        messages.append("Moderators={m}".format(m=self.number_moderators))

        if self.config.main_config.enable_canvas_sync:
            if self.canvas_enabled:
                messages.append("Canvas integration enabled")
            else:
                if not self.canvas_module_id:
                    messages.append("Canvas module identifier not set")

                if not self.canvas_assignment_id:
                    messages.append("Canvas assignment identifier not set")

        if self.collect_project_feedback:
            messages.append("Collect project feedback")
        else:
            messages.append("Do not collect project feedback")

        if self.has_presentation:
            messages.append("Has presentation")

            if self.collect_presentation_feedback:
                messages.append("Collect presentation feedback")
            else:
                messages.append("Do not collect presentation feedback")

        return messages

    @property
    def presentation_messages(self):
        messages = []

        if self.talk_format and len(self.talk_format) > 0:
            messages.append(self.talk_format)
        else:
            messages.append("Format not set")

        if self.lecture_capture:
            messages.append("Requires lecture capture")

        if self.number_assessors and self.number_assessors > 0:
            messages.append("Assessors={m}".format(m=self.number_assessors))

        if self.max_group_size and self.max_group_size > 0:
            messages.append("Max group size={m}".format(m=self.max_group_size))

        return messages

    @property
    def display_name(self):
        if self.name is not None and len(self.name) > 0:
            return str(self.name).format(
                year1=self.config.submit_year_a, year2=self.config.submit_year_b
            )

        return "Submission Period #{n}".format(n=self.submission_period)

    @property
    def time_to_feedback_deadline(self):
        if self.feedback_deadline is None:
            return "<invalid>"

        feedback_deadline_date: date = self.feedback_deadline.date()
        today: date = date.today()

        if today > feedback_deadline_date:
            return "in the past"

        delta = feedback_deadline_date - today
        return format_readable_time(delta)

    @property
    def has_attachments(self):
        return self.attachments.first() is not None

    @property
    def number_attachments(self):
        return get_count(self.attachments)

    @property
    def is_feedback_open(self):
        return self.feedback_open

    @property
    def time_to_hand_in(self):
        if self.hand_in_date is None:
            return "<invalid>"

        today = date.today()
        if today > self.hand_in_date:
            return "in the past"

        delta = self.hand_in_date - today
        return format_readable_time(delta)

    def _unordered_records_query(self, user, roles: Union[Iterable[str], str]):
        """
        Base query to extract SubmissionRecord instances belonging to this submission period,
        for which the quoted faculty member has a specified role
        :param user: identify staff member, either primary key for User, FacultyData or a User/FacultyData instance
        :param role: one of 'supervisor', 'marker', 'moderator', 'presentation', 'exam_board', 'external'
        :return:
        """
        from .submissions import SubmissionRecord, SubmissionRole

        if isinstance(user, int):
            user_id = user
        elif isinstance(user, FacultyData) or isinstance(user, User):
            user_id = user.id
        else:
            raise RuntimeError(
                'Unknown faculty id type "{typ}" passed to SubmissionPeriodRecord.get_supervisor_records'.format(
                    typ=type(user)
                )
            )

        role_map = {
            "supervisor": SubmissionRole.ROLE_SUPERVISOR,
            "marker": SubmissionRole.ROLE_MARKER,
            "moderator": SubmissionRole.ROLE_MODERATOR,
            "presentation": SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
            "exam_board": SubmissionRole.ROLE_EXAM_BOARD,
            "external": SubmissionRole.ROLE_EXTERNAL_EXAMINER,
            "responsible supervisor": SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
            "responsible": SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
        }

        def stringize_role(role):
            if isinstance(role, str):
                role_str = role.lower()
            else:
                role_str = str(role).lower()

            if role_str not in role_map:
                raise RuntimeError(
                    f'Unknown role "{role}" passed to SubmissionPeriodRecord.get_supervisor_records'
                )

            return role_str

        if isinstance(roles, str):
            roles_list = [stringize_role(roles)]
        elif isinstance(roles, Iterable):
            roles_list = [stringize_role(r) for r in roles]
        else:
            raise RuntimeError(
                f'Unknown roles type "{type(roles)}" passed to SubmissionPeriodRecord.get_supervisor_records'
            )

        role_ids = [role_map[role] for role in roles_list]

        # find all SubmissionRole instances of the required role types, belonging to this submission period and the specified user
        return (
            db.session.query(SubmissionRole)
            .join(SubmissionRecord, SubmissionRecord.id == SubmissionRole.submission_id)
            .filter(
                SubmissionRecord.period_id == self.id,
                SubmissionRecord.retired.is_(False),
                SubmissionRole.user_id == user_id,
                SubmissionRole.role.in_(role_ids),
            )
        )

    def _ordered_records_query(
        self, user, roles: Union[Iterable[str], str], order_by: str
    ):
        """
        Same as _unordered_records_query(), but now order by student name or exam number (as specified)
        :param user: identify staff member, either primary key for User, FacultyData or a User/FacultyData instance
        :param role: one of 'supervisor', 'marker', 'moderator', 'presentation', 'exam_board', 'external'
        :param order_by: one of 'name', 'exam'
        :return:
        """
        from .live_projects import SubmittingStudent
        from .submissions import SubmissionRecord

        if order_by not in ["name", "exam"]:
            raise KeyError(
                f'Unknown order type "{order_by}" in SubmissionPeriodRecord._ordered_records_query()'
            )

        query = self._unordered_records_query(user, roles).join(
            SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id
        )
        if order_by == "name":
            query = query.join(User, User.id == SubmittingStudent.student_id).order_by(
                User.last_name.asc(), User.first_name.asc()
            )

        if order_by == "exam":
            query = query.join(
                StudentData, StudentData.id == SubmittingStudent.student_id
            ).order_by(StudentData.exam_number.asc())

        return query

    def number_supervisor_records(self, user) -> int:
        return get_count(
            self._unordered_records_query(user, ["supervisor", "responsible"])
        )

    def get_supervisor_records(self, user):
        return self._ordered_records_query(
            user, ["supervisor", "responsible"], "name"
        ).all()

    def number_marker_records(self, user) -> int:
        return get_count(self._unordered_records_query(user, "marker"))

    def get_marker_records(self, user):
        return self._ordered_records_query(user, "marker", "exam").all()

    def number_moderator_records(self, user) -> int:
        return get_count(self._unordered_records_query(user, "moderator"))

    def get_moderator_records(self, user):
        return self._ordered_records_query(user, "moderator", "exam").all()

    def get_faculty_presentation_slots(self, fac):
        schedule = self.deployed_schedule
        return schedule.get_faculty_slots(fac).all()

    @property
    def uses_supervisor_feedback(self):
        return self.collect_project_feedback and self.config.uses_supervisor

    def get_student_presentation_slot(self, student):
        schedule = self.deployed_schedule
        return schedule.get_student_slot(student).first()

    @property
    def uses_marker_feedback(self):
        return self.collect_project_feedback and self.config.uses_marker

    @property
    def uses_presentation_feedback(self):
        return self.has_presentation and self.collect_presentation_feedback

    @property
    def submitter_list(self):
        return self.submissions

    @property
    def number_submitters(self):
        return get_count(self.submissions)

    @property
    def projects_list(self):
        from .live_projects import LiveProject

        records = self.submissions.subquery()

        # find all distinct projects in this submission period
        return (
            db.session.query(LiveProject)
            .join(records, records.c.project_id == LiveProject.id)
            .distinct()
        )

    @property
    def number_projects(self):
        return get_count(self.projects_list)

    @property
    def assessors_list(self):
        projects = self.projects_list.subquery()

        # find all faculty who are assessors for at least one project in this submission period
        assessors = (
            db.session.query(live_assessors.c.faculty_id)
            .join(projects, projects.c.id == live_assessors.c.project_id)
            .distinct()
            .subquery()
        )

        return db.session.query(FacultyData).join(
            assessors, assessors.c.faculty_id == FacultyData.id
        )

    @property
    def label(self):
        return self.config.project_class.make_label(
            self.config.abbreviation + ": " + self.display_name
        )

    @property
    def has_deployed_schedule(self):
        if not self.has_presentation:
            return False

        assessments: List[PresentationAssessment] = self.presentation_assessments.all()
        num_deployed = sum(1 for a in assessments if a.is_deployed)

        return num_deployed > 0

    @property
    def deployed_schedule(self):
        if not self.has_presentation:
            return None

        assessments: List[PresentationAssessment] = self.presentation_assessments.all()
        deployed = [a.deployed_schedule for a in assessments if a.is_deployed]

        num_deployed = len(deployed)
        if num_deployed == 0:
            return None

        # TODO: deployed_schedule should return a list, allowing multiple schedules to be deployed
        return deployed[-1]
        #
        # raise RuntimeError("Too many assessments deployed for this submission period")

    @property
    def number_submitters_feedback_pushed(self):
        return get_count(self.submissions.filter_by(feedback_sent=True))

    @property
    def number_submitters_feedback_not_pushed(self):
        from .submissions import SubmissionRole

        count = 0
        for record in self.submissions:
            record: SubmissionRecord

            if record.has_feedback_to_push:
                if not record.feedback_sent:
                    count += 1
                    continue

                role_available = 0
                for role in record.roles:
                    role: SubmissionRole

                    if role.role in [
                        SubmissionRole.ROLE_SUPERVISOR,
                        SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                        SubmissionRole.ROLE_MARKER,
                    ]:
                        if role.submitted_feedback and not role.feedback_sent:
                            role_available = 1
                            break

                if role_available > 0:
                    count += 1
                    continue

        return count

    @property
    def number_submitters_feedback_not_generated(self):
        count = 0
        for record in self.submissions:
            record: SubmissionRecord

            if record.has_feedback and not record.feedback_generated:
                count += 1
                continue

        return count

    def _number_submitters_with_role_feedback(self, allowed_roles):
        count = 0
        for record in self.submissions:
            record: SubmissionRecord

            for role in record.roles:
                role: SubmissionRole

                if role.role in allowed_roles and role.submitted_feedback:
                    count += 1
                    break

        return count

    @property
    def number_submitters_supervisor_feedback(self):
        from .submissions import SubmissionRole

        return self._number_submitters_with_role_feedback(
            [SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR]
        )

    @property
    def number_submitters_marker_feedback(self):
        from .submissions import SubmissionRole

        return self._number_submitters_with_role_feedback([SubmissionRole.ROLE_MARKER])

    @property
    def number_submitters_presentation_feedback(self):
        from .submissions import SubmissionRecord

        return get_count(
            self.submissions.filter(
                SubmissionRecord.presentation_feedback.any(submitted=True)
            )
        )

    @property
    def number_submitters_without_reports(self):
        from .submissions import SubmissionRecord

        return get_count(self.submissions.filter(SubmissionRecord.report_id == None))

    @property
    def number_submitters_canvas_report_available(self):
        from .live_projects import SubmittingStudent
        from .submissions import SubmissionRecord

        return get_count(
            self.submissions.join(
                SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id
            ).filter(
                and_(
                    SubmissionRecord.report_id == None,
                    SubmissionRecord.canvas_submission_available.is_(True),
                    SubmittingStudent.canvas_user_id != None,
                )
            )
        )

    @property
    def number_reports_to_email(self):
        from .submissions import SubmissionRecord, SubmissionRole

        return get_count(
            self.submissions.filter(
                and_(
                    SubmissionRecord.report_id != None,
                    SubmissionRecord.processed_report_id != None,
                    SubmissionRecord.roles.any(
                        or_(
                            and_(
                                SubmissionRole.role.in_(
                                    [
                                        SubmissionRole.ROLE_SUPERVISOR,
                                        SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                                    ]
                                ),
                                ~SubmissionRole.marking_distributed,
                            ),
                            and_(
                                SubmissionRole.role == SubmissionRole.ROLE_MARKER,
                                ~SubmissionRole.marking_distributed,
                            ),
                        )
                    ),
                )
            )
        )

    @property
    def all_markers_assigned(self):
        if not self.config.uses_marker:
            return True

        return self.submissions.filter_by(marker_id=None).first() is None

    @property
    def all_supervisors_assigned(self):
        if not self.config.uses_supervisor:
            return True

        return self.submissions.filter_by(project_id=None).first() is None

    @property
    def ordered_attachments(self):
        from .submissions import PeriodAttachment

        return self.attachments.order_by(PeriodAttachment.rank_order).all()

    @property
    def canvas_enabled(self):
        if not self.config.canvas_enabled:
            return False

        return (
            self.canvas_module_id is not None and self.canvas_assignment_id is not None
        )

    @property
    def canvas_assignment_URL(self):
        if self._canvas_assignment_URL is not None:
            return self._canvas_assignment_URL

        URL_root = self.config.canvas_root_URL
        course_URL = urljoin(
            URL_root, "courses/{course_id}/".format(course_id=self.canvas_module_id)
        )
        assignment_URL = urljoin(
            course_URL,
            "assignments/{assign_id}/".format(assign_id=self.canvas_assignment_id),
        )
        self._canvas_assignment_URL = url_normalize(assignment_URL)

        return self._canvas_assignment_URL

    @property
    def number_units(self) -> int:
        return get_count(self.units)

    @property
    def has_units(self) -> bool:
        return self.number_units > 0

    @property
    def ordered_units(self):
        return self.units.order_by(
            SubmissionPeriodUnit.start_date, SubmissionPeriodUnit.end_date
        )

    @property
    def validate(self):
        messages = []

        if self.start_date is None:
            messages.append(
                "A start date for this submission period has not yet been configured"
            )

        if self.hand_in_date is None:
            messages.append(
                "A hand-in date for this submission period has not yet been configured"
            )

        if self.name is None or len(self.name) == 0:
            messages.append(
                "A unique name for this submission period has not yet been configured"
            )

        if not self.all_supervisors_assigned:
            messages.append("Some students still require projects to be assigned")

        if not self.all_markers_assigned:
            messages.append("Some students still require markers to be assigned")

        if self.config.main_config.enable_canvas_sync:
            if not self.config.canvas_enabled:
                messages.append("Canvas integration is not yet set up for this cycle")
            elif not self.canvas_enabled:
                messages.append(
                    "Canvas integration is not yet set up for this submission period"
                )

        return messages


class SubmissionPeriodUnit(db.Model, EditingMetadataMixin):
    """
    Capture details about a particular unit within a submission period.
    Units can refer to any time period that is required, but in a typical Sussex semester they will usually
    refer to weeks. Each unit can contain a number of meetings.
    """

    __tablename__ = "submission_period_units"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent submission period
    owner_id = db.Column(
        db.Integer(), db.ForeignKey("submission_periods.id"), nullable=False
    )
    owner = db.relationship(
        "SubmissionPeriodRecord",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "units", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # text name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # unit start date (inclusive)
    start_date = db.Column(db.Date())

    # unit end date (inclusive)
    end_date = db.Column(db.Date())

    # TODO: consider adding
    #  - week-by-week articles covering relevant topics or HOWTOs
    #  - scheduled emails
    #  - messages and notices

    @property
    def number_templates(self) -> int:
        return get_count(self.templates)

    @property
    def number_events(self) -> int:
        return get_count(self.events)


class SupervisionEventTemplate(
    db.Model, EditingMetadataMixin, SupervisionEventTypesMixin, SubmissionRoleTypesMixin
):
    """
    Capture a template (later to be replicated over all submitters) for a supervision event within a submission unit.
    In a typical Sussex supervision arrangement, events will be 1-to-1 supervision meetings
    """

    __tablename__ = "supervision_event_templates"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent submission unit
    unit_id = db.Column(
        db.Integer(), db.ForeignKey("submission_period_units.id"), nullable=False
    )
    unit = db.relationship(
        "SubmissionPeriodUnit",
        foreign_keys=[unit_id],
        uselist=False,
        backref=db.backref(
            "templates", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # name of this event
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False
    )

    # assign this event to which submission roles?
    target_role = db.Column(db.Integer(), nullable=False)

    ## ATTENDEES AND TEAM
    # event type identifier, drawn from SupervisionEventTypesMixin
    type = db.Column(
        db.Integer(),
        default=SupervisionEventTypesMixin.EVENT_ONE_TO_ONE_MEETING,
        nullable=False,
    )

    ## ATTENDANCE MONITORING

    # collect attendance data for this event?
    monitor_attendance = db.Column(db.Boolean(), default=True)

    @property
    def target_role_as_str(self):
        return self._role_string.get(self.target_role, "Unknown")

    @property
    def short_target_role_as_str(self):
        return self._role_string.get(self.target_role, "?")

    @property
    def event_as_str(self):
        return self._event_string.get(self.type, "Unknown")

    @property
    def short_event_as_str(self):
        return self._short_event_string.get(self.type, "?")

    @property
    def number_events(self) -> int:
        return get_count(self.events)


class SupervisionEvent(
    db.Model,
    EditingMetadataMixin,
    SupervisionEventTypesMixin,
    SupervisionEventAttendanceMixin,
):
    """
    Capture details about a supervision event within a submission unit.
    In a typical Sussex supervision arrangement, events will be 1-to-1 supervision meetings
    """

    __tablename__ = "supervision_events"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent submission unit
    unit_id = db.Column(
        db.Integer(), db.ForeignKey("submission_period_units.id"), nullable=False
    )
    unit = db.relationship(
        "SubmissionPeriodUnit",
        foreign_keys=[unit_id],
        uselist=False,
        backref=db.backref(
            "events", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # parent template
    template_id = db.Column(
        db.Integer(), db.ForeignKey("supervision_event_templates.id")
    )
    template = db.relationship(
        "SupervisionEventTemplate",
        foreign_keys=[template_id],
        uselist=False,
        backref=db.backref("events", lazy="dynamic"),
    )

    ## EVENT PROPERTIES

    # name of this event
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=False
    )

    # time of event
    time = db.Column(db.DateTime(), nullable=True)

    # location of event
    location = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True
    )

    ## ATTENDEES AND TEAM

    # submitter to whom this event applies
    sub_record_id = db.Column(db.Integer(), db.ForeignKey("submission_records.id"))
    sub_record = db.relationship(
        "SubmissionRecord",
        foreign_keys=[sub_record_id],
        uselist=False,
        backref=db.backref(
            "events", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # responsible event owner, usually the responsible supervisor, but does not have to be
    owner_id = db.Column(db.Integer(), db.ForeignKey("submission_roles.id"))
    owner = db.relationship(
        "SubmissionRole",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref("events_owner", lazy="dynamic"),
    )

    # other attending members of the supervision team
    team = db.relationship(
        "SubmissionRole",
        secondary=event_roles_table,
        lazy="dynamic",
        backref=db.backref("events_team", lazy="dynamic"),
    )

    # event type identifier, drawn from SupervisionEventTypesMixin
    type = db.Column(
        db.Integer(),
        default=SupervisionEventTypesMixin.EVENT_ONE_TO_ONE_MEETING,
        nullable=False,
    )

    ## ATTENDANCE MONITORING

    # collect attendance data for this event?
    monitor_attendance = db.Column(db.Boolean(), default=True)

    # attendance record
    attendance = db.Column(db.Integer(), default=None, nullable=True)

    ## RECORD-KEEPING AND STUDENT PROGRESS

    # meeting summary
    meeting_summary = db.Column(db.Text())

    # private notes for faculty
    supervision_notes = db.Column(db.Text())

    # private notes for students
    submitter_notes = db.Column(db.Text())

    # assets uploaded for this event
    uploaded_assets = db.relationship(
        "SubmittedAsset",
        secondary=even_assets_table,
        lazy="dynamic",
        backref=db.backref("supervision_events", lazy="dynamic"),
    )

    ## PROMPTS AND REMINDERES

    # mute notifications for this event?
    mute = db.Column(db.Boolean(), default=False, nullable=False)

    # has a prompt been sent for this event?
    prompt_sent_timestamp = db.Column(db.DateTime(), default=None, nullable=True)

    # when was the last reminder sent for this event?
    last_reminder_timestamp = db.Column(db.DateTime(), default=None, nullable=True)

    ## EMAIL LOGS

    # emails associated with this event
    email_log = db.relationship("EmailLog", secondary=event_email_table, lazy="dynamic")

    # reminder emails (specifically) associated with this event
    reminder_log = db.relationship(
        "EmailLog", secondary=event_reminder_table, lazy="dynamic"
    )

    @property
    def attendance_str(self):
        return self._attendance_string.get(self.attendance, "Unknown")

    def get_start_time(self) -> datetime:
        if self.time is not None:
            return self.time

        # if no start time specified, assume it happens on the closest weekday on or after the end
        # of the submission unit, at 12pm
        unit_start_date = self.unit.start_date
        unit_start_weekday = unit_start_date.isoweekday()

        if unit_start_weekday > 5:
            shift: timedelta = timedelta(days=8 - unit_start_weekday)
            start_date = unit_start_date + shift
        else:
            start_date = unit_start_date

        start_time: datetime = datetime.combine(
            start_date, time(hour=12, minute=0, second=0, microsecond=0)
        )
        return start_time

    def is_in_past(self, now: datetime = None) -> bool:
        if now is None:
            now = datetime.now()

        start_time = self.get_start_time()

        return start_time < now
