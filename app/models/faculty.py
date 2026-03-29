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

from flask import current_app
from flask_security import current_user
from sqlalchemy import and_, or_, orm
from sqlalchemy.event import listens_for
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesGcmEngine

from ..cache import cache
from ..database import db
from ..shared.sqlalchemy import get_count
from .assessment import PresentationAssessment, _PresentationAssessment_is_valid
from .associations import (
    faculty_affiliations,
    faculty_batch_to_tenants,
)
from .config import get_AES_key
from .defaults import DEFAULT_STRING_LENGTH
from .matching import MatchingAttempt, MatchingRecord, MatchingRole, _MatchingRecord_is_valid
from .model_mixins import ColouredLabelMixin, EditingMetadataMixin, _get_current_year
from .projects import (
    _Project_is_offerable,
    _Project_num_assessors,
    _Project_num_supervisors,
)


class FacultyData(db.Model, EditingMetadataMixin):
    """
    Models extra data held on faculty members
    """

    __tablename__ = "faculty_data"

    # primary key is same as users.id for this faculty member
    id = db.Column(db.Integer(), db.ForeignKey("users.id"), primary_key=True)
    user = db.relationship(
        "User", foreign_keys=[id], backref=db.backref("faculty_data", uselist=False)
    )

    # research group affiliations for this faculty member
    affiliations = db.relationship(
        "ResearchGroup",
        secondary=faculty_affiliations,
        lazy="dynamic",
        backref=db.backref("faculty", lazy="dynamic"),
    )

    # academic title (Prof, Dr, etc.)
    academic_title = db.Column(db.Integer())

    # use academic title?
    use_academic_title = db.Column(db.Boolean())

    # office location
    office = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # DEFAULT PROJECT SETTINGS

    # does this faculty want to sign off on students before they can apply?
    sign_off_students = db.Column(db.Boolean(), default=True)

    # default capacity
    project_capacity = db.Column(db.Integer(), default=2)

    # enforce capacity limits by default?
    enforce_capacity = db.Column(db.Boolean(), default=True)

    # enable popularity display by default?
    show_popularity = db.Column(db.Boolean(), default=True)

    # don't clash presentations by default?
    dont_clash_presentations = db.Column(db.Boolean(), default=True)

    # CAPACITY LIMITS FOR THIS FACULTY MEMBER

    # supervision CATS capacity
    CATS_supervision = db.Column(db.Integer())

    # marking CATS capacity
    CATS_marking = db.Column(db.Integer())

    # moderation CATS capacity
    CATS_moderation = db.Column(db.Integer())

    # presentation assessment CATS capacity
    CATS_presentation = db.Column(db.Integer())

    # ATTENDANCE MONITORING

    # send reminder emails?
    reminder_emails = db.Column(db.Integer(), default=True, nullable=False)

    # how frequently to send reminder emails
    _reminder_frequency_choices = [
        (1, "Every week"),
        (2, "Every two weeks"),
        (3, "Every three weeks"),
        (4, "Every four weeks"),
    ]
    reminder_frequency = db.Column(db.Integer(), default=2, nullable=False)

    # CANVAS INTEGRATION

    # used only for convenors

    # API access token for this user; AesGcmEngine is more secure but cannot perform queries
    # here, that's OK because we don't expect to have to query against the token
    canvas_API_token = db.Column(
        EncryptedType(
            db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"),
            get_AES_key,
            AesGcmEngine,
            "pkcs5",
        ),
        default=None,
        nullable=True,
    )

    @property
    def name(self):
        return self.user.name

    @property
    def email(self):
        return self.user.email

    def _supervisor_pool_query(self, pclass):
        from .project_class import ProjectClass
        from .projects import Project

        if isinstance(pclass, ProjectClass):
            pclass_id = pclass.id
        elif isinstance(pclass, int):
            pclass_id = pclass
        else:
            raise RuntimeError(
                "Could not interpret pclass parameter of type {typ} in FacultyData._projects_offered_query".format(
                    typ=type(pclass)
                )
            )

        return db.session.query(Project).filter(
            Project.active.is_(True),
            Project.project_classes.any(id=pclass_id),
            Project.generic.is_(True),
            Project.supervisors.any(id=self.id),
        )

    def projects_supervisor_pool(self, pclass):
        return self._supervisor_pool_query(pclass)

    def number_supervisor_pool(self, pclass):
        return get_count(self._supervisor_pool_query(pclass))

    def supervisor_pool_label(self, pclass):
        n = self.number_supervisor_pool(pclass)

        return {"label": f"In pool for: {n}", "type": "info"}

    def _projects_supervisable_query(self, pclass):
        from .project_class import ProjectClass
        from .projects import Project

        if isinstance(pclass, ProjectClass):
            pclass_id = pclass.id
        elif isinstance(pclass, int):
            pclass_id = pclass
        else:
            raise RuntimeError(
                "Could not interpret pclass parameter of type {typ} in FacultyData._projects_offered_query".format(
                    typ=type(pclass)
                )
            )

        # TODO: possibly needs revisiting if we continue decoupling the concept of supervisors from project owners
        return db.session.query(Project).filter(
            Project.active.is_(True),
            Project.project_classes.any(id=pclass_id),
            or_(
                and_(Project.generic.is_(True), Project.supervisors.any(id=self.id)),
                Project.owner_id == self.id,
            ),
        )

    def projects_supervisable(self, pclass):
        return self._projects_supervisable_query(pclass).all()

    def number_projects_supervisable(self, pclass):
        return get_count(self._projects_supervisable_query(pclass))

    def projects_supervisable_label(self, pclass):
        n = self.number_projects_supervisable(pclass)

        if n == 0:
            return {"label": "0 supervisable", "type": "danger", "fw": "semibold"}

        return {"label": f"{n} supervisable", "type": "success"}

    def _projects_offered_query(self, pclass):
        from .project_class import ProjectClass
        from .projects import Project

        if isinstance(pclass, ProjectClass):
            pclass_id = pclass.id
        elif isinstance(pclass, int):
            pclass_id = pclass
        else:
            raise RuntimeError(
                "Could not interpret pclass parameter of type {typ} in FacultyData._projects_offered_query".format(
                    typ=type(pclass)
                )
            )

        return db.session.query(Project).filter(
            Project.active.is_(True),
            Project.owner_id == self.id,
            Project.project_classes.any(id=pclass_id),
        )

    def projects_offered(self, pclass):
        return self._projects_offered_query(pclass).all()

    def number_projects_offered(self, pclass):
        return get_count(self._projects_offered_query(pclass))

    def projects_offered_label(self, pclass):
        n = self.number_projects_offered(pclass)

        if n == 0:
            return {"label": "0 offered", "type": "warning", "fw": "semibold"}

        return {"label": f"{n} offered", "type": "success"}

    def variants_offered(self, pclass, filter_warnings=None, filter_errors=None):
        from .project_class import ProjectClass
        from .projects import Project, ProjectDescription

        if isinstance(pclass, ProjectClass):
            pclass_id = pclass.id
        elif isinstance(pclass, int):
            pclass_id = pclass
        else:
            raise RuntimeError(
                "Could not interpret pclass parameter of type {typ} in FacultyData._variants_offered_query".format(
                    typ=type(pclass)
                )
            )

        # get variants that are explicitly marked as attached to the specified project class
        explicit_variants = (
            db.session.query(ProjectDescription)
            .select_from(Project)
            .filter(Project.active.is_(True), Project.owner_id == self.id)
            .join(ProjectDescription, ProjectDescription.parent_id == Project.id)
            .filter(ProjectDescription.project_classes.any(id=pclass_id))
        ).all()

        # get variants that are *not* marked as attached to the specified project class, but which *are* the
        # default variant for some project that *is* attached
        # This prevents us from selecting a variant which is marked as the default, but overridden by
        # some other explicitly-attached variant
        explicit_variant_project_ids = [d.parent_id for d in explicit_variants]
        default_variants = (
            db.session.query(ProjectDescription)
            .select_from(Project)
            .filter(
                Project.active.is_(True),
                Project.owner_id == self.id,
                ~Project.id.in_(explicit_variant_project_ids),
                Project.project_classes.any(id=pclass_id),
            )
            .join(ProjectDescription, ProjectDescription.parent_id == Project.id)
            .filter(ProjectDescription.id == Project.default_id)
        ).all()

        # the variants to be offered are the sum of these two groups
        vs = explicit_variants + default_variants

        if filter_warnings is not None:
            if isinstance(filter_warnings, str):
                vs = [v for v in vs if v.has_warning(filter_warnings)]
            elif isinstance(filter_warnings, Iterable):
                for w in filter_warnings:
                    vs = [v for v in vs if v.has_warning(w)]
            else:
                raise RuntimeError(
                    "Could not interpret parameter filter_warnings of type {typ} in FacultyData.variants_offered".format(
                        typ=type(filter_warnings)
                    )
                )

        if filter_errors is not None:
            if isinstance(filter_errors, str):
                vs = [v for v in vs if v.has_error(filter_errors)]
            elif isinstance(filter_errors, Iterable):
                for e in filter_errors:
                    vs = [v for v in vs if v.has_error(e)]
            else:
                raise RuntimeError(
                    "Could not interpret parameter filter_errors of type {typ} in FacultyData.variants_offered".format(
                        typ=type(filter_errors)
                    )
                )

        return vs

    @property
    def projects_unofferable(self):
        unofferable = 0
        for proj in self.projects:
            if proj.active and not proj.is_offerable:
                unofferable += 1

        return unofferable

    @property
    def projects_unofferable_label(self):
        n = self.projects_unofferable

        if n == 0:
            return {"label": "0 unofferable", "type": "secondary"}

        return {"label": f"{n} unofferable", "type": "warning"}

    def remove_affiliation(self, group, autocommit=False):
        """
        Remove an affiliation from a faculty member
        :param group:
        :return:
        """
        from .projects import Project

        self.affiliations.remove(group)

        # remove this group affiliation label from any projects owned by this faculty member
        ps = Project.query.filter_by(owner_id=self.id, group_id=group.id)

        for proj in ps.all():
            proj.group = None

        if autocommit:
            db.session.commit()

    def add_affiliation(self, group, autocommit=False):
        """
        Add an affiliation to this faculty member
        :param group:
        :return:
        """

        self.affiliations.append(group)

        if autocommit:
            db.session.commit()

    def has_affiliation(self, group):
        """
        Test whether this faculty members has a particular research group affiliation
        :param group:
        :return:
        """
        if group is None:
            return False

        return group in self.affiliations

    def is_enrolled(self, pclass):
        """
        Check whether this FacultyData record has an enrolment for a given project class
        :param pclass:
        :return:
        """

        # test whether an EnrollmentRecord exists for this project class
        record = self.get_enrollment_record(pclass)

        if record is None:
            return False

        return True

    def remove_enrollment(self, pclass):
        """
        Remove an enrolment from a faculty member
        :param pclass:
        :return:
        """
        from .projects import Project

        # find enrolment record for this project class
        record = self.get_enrollment_record(pclass)
        if record is not None:
            db.session.delete(record)

        # remove this project class from any projects owned by this faculty member
        ps = Project.query.filter(
            Project.owner_id == self.id, Project.project_classes.any(id=pclass.id)
        )

        for proj in ps.all():
            proj.remove_project_class(pclass)

        db.session.commit()

        celery = current_app.extensions["celery"]

        adjust_task = celery.tasks["app.tasks.availability.adjust"]
        delete_task = celery.tasks["app.tasks.issue_confirm.enrollment_deleted"]

        current_year = _get_current_year()
        adjust_task.apply_async(args=(record.id, current_year))
        delete_task.apply_async(args=(pclass.id, self.id, current_year))

    def add_enrollment(self, pclass):
        """
        Add an enrolment to this faculty member
        :param pclass:
        :return:
        """

        record = EnrollmentRecord(
            pclass_id=pclass.id,
            owner_id=self.id,
            supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED,
            supervisor_comment=None,
            supervisor_reenroll=None,
            marker_state=EnrollmentRecord.MARKER_ENROLLED,
            marker_comment=None,
            marker_reenroll=None,
            moderator_state=EnrollmentRecord.MODERATOR_ENROLLED,
            moderator_comment=None,
            moderator_reenroll=None,
            presentations_state=EnrollmentRecord.PRESENTATIONS_ENROLLED,
            presentations_comment=None,
            presentations_reenroll=None,
            CATS_supervision=None,
            CATS_marking=None,
            CATS_moderation=None,
            CATS_presentation=None,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
            last_edit_id=None,
            last_edit_timestamp=None,
        )

        # allow uncaught exceptions to propagate; it's the caller's responsibility to catch these
        db.session.add(record)
        db.session.commit()

        celery = current_app.extensions["celery"]
        adjust_task = celery.tasks["app.tasks.availability.adjust"]
        create_task = celery.tasks["app.tasks.issue_confirm.enrollment_created"]

        current_year = _get_current_year()
        adjust_task.apply_async(args=(record.id, current_year))
        create_task.apply_async(args=(record.id, current_year))

    def enrolled_labels(self, pclass):
        record = self.get_enrollment_record(pclass)

        if record is None:
            return {"label": "Not enrolled", "type": "warning"}

        return record.enrolled_labels

    def get_enrollment_record(self, pclass):
        from .project_class import ProjectClass

        if isinstance(pclass, ProjectClass):
            pcl_id = pclass.id
        elif isinstance(pclass, int):
            pcl_id = pclass
        else:
            raise RuntimeError("Cannot interpret pclass argument")

        return self.enrollments.filter_by(pclass_id=pcl_id).first()

    @property
    def ordered_enrollments(self):
        from .project_class import ProjectClass

        return self.enrollments.join(
            ProjectClass, ProjectClass.id == EnrollmentRecord.pclass_id
        ).order_by(ProjectClass.name)

    @property
    def is_convenor(self):
        """
        Determine whether this faculty member is convenor for any projects
        :return:
        """
        if self.convenor_for is not None and get_count(self.convenor_for) > 0:
            return True

        if self.coconvenor_for is not None and get_count(self.coconvenor_for) > 0:
            return True

        return False

    @property
    def convenor_list(self):
        """
        Return list of projects for which this faculty member is a convenor
        :return:
        """
        from .project_class import ProjectClass

        pcls = (
            self.convenor_for.order_by(ProjectClass.name).all()
            + self.coconvenor_for.order_by(ProjectClass.name).all()
        )
        pcl_set = set(pcls)
        return pcl_set

    def add_convenorship(self, pclass):
        """
        Set up this user faculty member for the convenorship of the given project class. Currently empty.
        :param pclass:
        :return:
        """
        pass

    def remove_convenorship(self, pclass):
        """
        Remove the convenorship of the given project class from this user.
        Does not commit any changes, which should be done by the client code.
        :param pclass:
        :return:
        """
        from .utilities import MessageOfTheDay

        # currently our only task is to remove system messages emplaced by this user in their role as convenor
        for item in MessageOfTheDay.query.filter_by(user_id=self.id).all():
            # if no assigned classes then this is a broadcast message; move on
            # (we can assume the user is still an administrator)
            if item.project_classes.first() is None:
                break

            # otherwise, remove this project class from the classes associated with this
            if pclass in item.project_classes:
                item.project_classes.remove(pclass)

                # if assigned project classes are now empty then delete the parent message
                if item.project_classes.first() is None:
                    db.session.delete(item)

    @property
    def number_assessor(self):
        """
        Determine the number of projects to which we are attached as an assessor
        :return:
        """
        return get_count(self.assessor_for)

    @property
    def assessor_label(self):
        """
        Generate a label for the number of projects to which we are attached as a second marker
        :return:
        """
        num = self.number_assessor

        if num == 0:
            return {"label": "Assessor for: 0", "type": "secondary"}

        return {"label": f"Assessor for: {num}", "type": "info"}

    def supervisor_assignments(self, config=None, pclass=None, period=None):
        """
        Return a list of current SubmissionRole instances for which we are supervisor
        :return:
        """
        from .submissions import SubmissionRole

        return self._apply_role_assignment_filters(
            [SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR],
            config=config,
            pclass=pclass,
            period=period,
        )

    def marker_assignments(self, config=None, pclass=None, period=None):
        """
        Return a list of current SubmissionRole instances for which we are marker
        :return:
        """
        from .submissions import SubmissionRole

        return self._apply_role_assignment_filters(
            SubmissionRole.ROLE_MARKER, config=config, pclass=pclass, period=period
        )

    def moderator_assignments(self, config=None, pclass=None, period=None):
        """
        Return a list of current SubmissionRole instances for which we are moderator
        :return:
        """
        from .submissions import SubmissionRole

        return self._apply_role_assignment_filters(
            SubmissionRole.ROLE_MODERATOR, config=config, pclass=pclass, period=period
        )

    def presentation_assignments(self, config=None, pclass=None, period=None):
        """
        Return a list of current SubmissionRole instances for which we are a presentation assessor
        :return:
        """
        from .submissions import SubmissionRole

        return self._apply_role_assignment_filters(
            SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
            config=config,
            pclass=pclass,
            period=period,
        )

    def _apply_role_assignment_filters(self, roles, config=None, pclass=None, period=None):
        from .live_projects import SubmittingStudent
        from .project_class import ProjectClass, ProjectClassConfig
        from .submissions import (
            SubmissionPeriodRecord,
            SubmissionRecord,
            SubmissionRole,
        )

        if not isinstance(roles, list):
            roles = [roles]

        query = (
            db.session.query(SubmissionRole)
            .filter(
                and_(
                    SubmissionRole.role.in_(roles),
                    SubmissionRole.user_id == self.id,
                )
            )
            .join(SubmissionRecord, SubmissionRecord.id == SubmissionRole.submission_id)
            .filter(SubmissionRecord.retired.is_(False))
            .join(SubmittingStudent, SubmissionRecord.owner_id == SubmittingStudent.id)
            .join(
                SubmissionPeriodRecord,
                SubmissionRecord.period_id == SubmissionPeriodRecord.id,
            )
        )

        if config is not None:
            if isinstance(config, int):
                query = query.filter(SubmittingStudent.config_id == config)
            elif isinstance(config, ProjectClassConfig):
                query = query.filter(SubmittingStudent.config_id == config.id)
            else:
                raise ValueError(
                    f"Unexpected type for config parameter: {type(config)}"
                )
        elif pclass is not None:
            query = query.join(
                ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id
            )
            if isinstance(pclass, int):
                query = query.filter(ProjectClassConfig.pclass_id == pclass)
            elif isinstance(pclass, ProjectClass):
                query = query.filter(ProjectClassConfig.pclass_id == pclass.id)
            else:
                raise ValueError(
                    f"Unexpected type for pclass parameter: {type(pclass)}"
                )

        if period is None:
            query = query.order_by(SubmissionPeriodRecord.submission_period.asc())
        elif isinstance(period, int):
            query = query.filter(SubmissionPeriodRecord.submission_period == period)
        else:
            raise ValueError(f"Unexpected type for period parameter: {type(period)}")

        return query

    def CATS_assignment(self, config_proxy):
        """
        Return (supervising CATS, marking CATS) for the current year
        :return:
        """
        from .project_class import ProjectClass, ProjectClassConfig

        if isinstance(config_proxy, ProjectClassConfig):
            config = config_proxy
        elif isinstance(config_proxy, ProjectClass):
            config = config_proxy.most_recent_config
        else:
            raise RuntimeError(
                "Could not interpret parameter config_proxy of type {typ} passed to FacultyData.CATS_assignment",
                typ=type(config_proxy),
            )

        if config.uses_supervisor:
            supv = self.supervisor_assignments(config=config)
            supv_CATS = [x.submission.supervising_CATS for x in supv]
            supv_total = sum(x for x in supv_CATS if x is not None)
        else:
            supv_total = 0

        if config.uses_marker:
            mark = self.marker_assignments(config=config)
            mark_CATS = [x.submission.marking_CATS for x in mark]
            mark_total = sum(x for x in mark_CATS if x is not None)
        else:
            mark_total = 0

        if config.uses_moderator:
            moderate = self.moderator_assignments(config=config)
            moderate_CATS = [x.submission.moderation_CATS for x in moderate]
            moderate_total = sum(x for x in moderate_CATS if x is not None)
        else:
            moderate_total = 0

        if config.uses_presentations:
            pres = self.presentation_assignments(config=config)
            pres_CATS = [x.submission.assessor_CATS for x in pres]
            pres_total = sum(x for x in pres_CATS if x is not None)
        else:
            pres_total = 0

        return supv_total, mark_total, moderate_total, pres_total

    def total_CATS_assignment(self):
        supv = 0
        mark = 0
        moderate = 0
        pres = 0

        for record in self.enrollments:
            s, ma, mo, p = self.CATS_assignment(record.pclass)

            supv += s
            mark += ma
            moderate += mo
            pres += p

        return supv, mark, moderate, pres

    def has_late_feedback(self, config_proxy, faculty_id):
        from .project_class import ProjectClass, ProjectClassConfig
        from .submissions import SubmissionRole

        if isinstance(config_proxy, ProjectClassConfig):
            config_id = config_proxy.id
        elif isinstance(config_proxy, ProjectClass):
            config_id = config_proxy.most_recent_config.id
        elif isinstance(config_proxy, int):
            config_id = config_proxy

        supervisor_late = [
            x.feedback_state == SubmissionRole.FEEDBACK_LATE
            for x in self.supervisor_assignments(config=config_id)
        ]

        response_late = [
            x.response_state == SubmissionRole.FEEDBACK_LATE
            for x in self.supervisor_assignments(config=config_id)
        ]

        marker_late = [
            x.feedback_state == SubmissionRole.FEEDBACK_LATE
            for x in self.marker_assignments(config=config_id)
        ]

        presentation_late = [
            x.feedback_state == SubmissionRole.FEEDBACK_LATE
            for x in self.presentation_assignments(config=config_id)
        ]

        return (
            any(supervisor_late)
            or any(marker_late)
            or any(response_late)
            or any(presentation_late)
        )

    @property
    def outstanding_availability_requests(self):
        from .assessment import AssessorAttendanceData, PresentationAssessment

        query = (
            db.session.query(AssessorAttendanceData)
            .filter(
                AssessorAttendanceData.faculty_id == self.id,
                AssessorAttendanceData.confirmed.is_(False),
            )
            .subquery()
        )

        return (
            db.session.query(PresentationAssessment)
            .join(query, query.c.assessment_id == PresentationAssessment.id)
            .filter(
                PresentationAssessment.year == _get_current_year(),
                PresentationAssessment.skip_availability.is_(False),
                PresentationAssessment.requested_availability.is_(True),
                PresentationAssessment.availability_closed.is_(False),
            )
            .order_by(PresentationAssessment.name.asc())
        )

    @property
    def editable_availability_requests(self):
        from .assessment import AssessorAttendanceData, PresentationAssessment

        query = (
            db.session.query(AssessorAttendanceData.assessment_id)
            .filter(AssessorAttendanceData.faculty_id == self.id)
            .subquery()
        )

        return (
            db.session.query(PresentationAssessment)
            .join(query, query.c.assessment_id == PresentationAssessment.id)
            .filter(
                PresentationAssessment.year == _get_current_year(),
                PresentationAssessment.skip_availability.is_(False),
                PresentationAssessment.availability_closed.is_(False),
            )
            .order_by(PresentationAssessment.name.asc())
        )

    @property
    def has_outstanding_availability_requests(self):
        return get_count(self.outstanding_availability_requests) > 0

    @property
    def has_editable_availability_requests(self):
        return get_count(self.editable_availability_requests) > 0

    @property
    def student_availability(self):
        """
        Compute how many students this supervisor is 'accessible' for (which may be unbounded)
        :return:
        """
        from .project_class import ProjectClass, ProjectClassConfig
        from .projects import Project, ProjectDescription

        total = 0.0
        unbounded = False

        max_CATS = None

        config_cache = {}

        pclasses = (
            db.session.query(ProjectClass)
            .filter(
                ProjectClass.active,
                ProjectClass.publish,
                ProjectClass.include_available,
            )
            .all()
        )

        for pcl in pclasses:
            pcl: ProjectClass

            if pcl.id in config_cache:
                config: ProjectClassConfig = config_cache[pcl.id]
            else:
                config: ProjectClassConfig = pcl.most_recent_config
                config_cache[pcl.id] = config

            if config is not None:
                if (
                    config.uses_supervisor
                    and config.CATS_supervision is not None
                    and config.CATS_supervision > 0
                ):
                    if max_CATS is None or config.CATS_supervision > max_CATS:
                        max_CATS = float(config.CATS_supervision)

        for record in self.enrollments:
            record: EnrollmentRecord

            if record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED:
                if (
                    record.pclass.active
                    and record.pclass.publish
                    and record.pclass.include_available
                ):
                    if record.pclass_id in config_cache:
                        config: ProjectClassConfig = config_cache[record.pclass_id]
                    else:
                        config: ProjectClassConfig = record.pclass.most_recent_config
                        config_cache[record.pclass_id] = config

                    if config is not None:
                        projects = self.projects.filter(
                            Project.project_classes.any(id=record.pclass_id)
                        ).all()

                        for p in projects:
                            p: Project

                            if p.enforce_capacity:
                                desc: ProjectDescription = p.get_description(
                                    record.pclass_id
                                )
                                if desc is not None and desc.capacity > 0:
                                    if max_CATS is not None:
                                        supv_CATS = desc.CATS_supervision(config)
                                        if supv_CATS is not None:
                                            total += (
                                                float(supv_CATS) / max_CATS
                                            ) * float(desc.capacity)
                                    else:
                                        total += float(desc.capacity)
                            else:
                                unbounded = True

        return total, unbounded


def _FacultyData_delete_cache(faculty_id):
    from .live_projects import LiveProject
    from .scheduling import (
        ScheduleAttempt,
        ScheduleSlot,
        _ScheduleAttempt_is_valid,
        _ScheduleSlot_is_valid,
    )
    from .utilities import _MatchingAttempt_is_valid

    year = _get_current_year()

    marker_records = (
        db.session.query(MatchingRecord)
        .join(MatchingAttempt, MatchingAttempt.id == MatchingRecord.matching_id)
        .filter(
            MatchingAttempt.year == year,
            MatchingRecord.roles.any(
                and_(
                    MatchingRole.user_id == faculty_id,
                    MatchingRole.role == MatchingRole.ROLE_MARKER,
                )
            ),
        )
    )

    superv_records = (
        db.session.query(MatchingRecord)
        .join(MatchingAttempt, MatchingAttempt.id == MatchingRecord.matching_id)
        .filter(MatchingAttempt.year == year)
        .join(LiveProject, LiveProject.id == MatchingRecord.project_id)
        .filter(LiveProject.owner_id == faculty_id)
    )

    match_records = marker_records.union(superv_records)

    for record in match_records:
        cache.delete_memoized(_MatchingRecord_is_valid, record.id)
        cache.delete_memoized(_MatchingAttempt_is_valid, record.matching_id)

    schedule_slots = (
        db.session.query(ScheduleSlot)
        .join(ScheduleAttempt, ScheduleAttempt.id == ScheduleSlot.owner_id)
        .join(
            PresentationAssessment,
            PresentationAssessment.id == ScheduleAttempt.owner_id,
        )
        .filter(
            PresentationAssessment.year == year,
            ScheduleSlot.assessors.any(id=faculty_id),
        )
    )
    for slot in schedule_slots:
        cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, slot.owner_id)
        if slot.owner is not None:
            cache.delete_memoized(_PresentationAssessment_is_valid, slot.owner.owner_id)


# no need for insert handler, since at insert time no MatchingRecord or ScheduleSlot can reference this instance
# no need for delete handler, since not intended to be able to delete faculty users
@listens_for(FacultyData, "before_update")
def _FacultyData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _FacultyData_delete_cache(target.id)


class FacultyBatch(db.Model):
    """
    Model a batch import of faculty accounts
    """

    __tablename__ = "batch_faculty"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # original filename
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), index=True)

    # importing user
    owner_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    owner = db.relationship(
        "User",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref("faculty_batch_imports", lazy="dynamic"),
    )

    # tenants to assign to imported users
    tenants = db.relationship(
        "Tenant",
        secondary=faculty_batch_to_tenants,
        lazy="dynamic",
        backref=db.backref("faculty_batches", lazy="dynamic"),
    )

    # celery task UUID
    celery_id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # is the celery read-in task finished?
    celery_finished = db.Column(db.Boolean(), default=False)

    # did we succeed in interpreting the uploaded file?
    success = db.Column(db.Boolean(), default=False)

    # has this batch been converted to user accounts?
    converted = db.Column(db.Boolean(), default=False)

    # generation timestamp
    timestamp = db.Column(db.DateTime())

    # total lines read from the file
    total_lines = db.Column(db.Integer())

    # total lines that could be correctly interpreted
    interpreted_lines = db.Column(db.Integer())

    # cached import report
    report = db.Column(db.Text())

    @property
    def number_items(self):
        return get_count(self.items)


class FacultyBatchItem(db.Model):
    """
    Model an individual record in a batch import of faculty accounts
    """

    __tablename__ = "batch_faculty_items"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent StudentBatch instance
    parent_id = db.Column(db.Integer(), db.ForeignKey("batch_faculty.id"))
    parent = db.relationship(
        "FacultyBatch",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref(
            "items", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # optional link to an existing FacultyData instance
    existing_id = db.Column(db.Integer(), db.ForeignKey("faculty_data.id"))
    existing_record = db.relationship(
        "FacultyData",
        foreign_keys=[existing_id],
        uselist=False,
        backref=db.backref("counterparts", lazy="dynamic"),
    )

    # user_id
    user_id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # first name
    first_name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # last or family name
    last_name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # email address
    email = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # office
    office = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # CAPACITY LIMITS FOR THIS FACULTY MEMBER

    # supervision CATS capacity
    CATS_supervision = db.Column(db.Integer())

    # marking CATS capacity
    CATS_marking = db.Column(db.Integer())

    # moderation CATS capacity
    CATS_moderation = db.Column(db.Integer())

    # presentation assessment CATS capacity
    CATS_presentation = db.Column(db.Integer())

    # METADATA

    # flag as "don't convert to user"
    dont_convert = db.Column(db.Boolean(), default=False)

    @property
    def warnings(self):
        w = []

        if self.existing_record is None:
            return w

        if (
            self.first_name is not None
            and self.existing_record.user.first_name != self.first_name
        ):
            w.append(
                f'Current first name "{self.existing_record.user.first_name}" (imported "{self.first_name}")'
            )

        if (
            self.last_name is not None
            and self.existing_record.user.last_name != self.last_name
        ):
            w.append(
                f'Current last name "{self.existing_record.user.last_name}" (imported "{self.last_name}")'
            )

        if (
            self.user_id is not None
            and self.existing_record.user.username != self.user_id
        ):
            w.append(
                f'Current user id "{self.existing_record.user.username}" (imported "{self.username}")'
            )

        if self.email is not None and self.existing_record.user.email != self.email:
            w.append(
                f'Current email "{self.existing_record.user.email}" (imported "{self.email}")'
            )

        if self.office is not None and self.existing_record.office != self.office:
            w.append(
                f'Current office "{self.existing_record.office}" (imported "{self.office}")'
            )

        if (
            self.CATS_supervision is not None
            and self.existing_record.CATS_supervision != self.CATS_supervision
        ):
            w.append(
                f"Current supervision CATS {' = default' if self.existing_record.CATS_supervision is None else self.existing_record.CATS_supervision}"
            )

        if (
            self.CATS_marking is not None
            and self.existing_record.CATS_marking != self.CATS_marking
        ):
            w.append(
                f"Current marking CATS {' = default' if self.existing_record.CATS_marking is None else self.existing_record.CATS_marking}"
            )

        if (
            self.CATS_moderation is not None
            and self.existing_record.CATS_moderation != self.CATS_moderation
        ):
            w.append(
                f"Current moderation CATS {' = default' if self.existing_record.CATS_moderation is None else self.existing_record.CATS_moderation}"
            )

        if (
            self.CATS_presentation is not None
            and self.existing_record.CATS_presentation != self.CATS_presentation
        ):
            w.append(
                f"Current presentation CATS {' = default' if self.existing_record.CATS_presentation is None else self.existing_record.CATS_presentation}"
            )

        return w


class EnrollmentRecord(db.Model, EditingMetadataMixin):
    """
    Capture details about a faculty member's enrolment in a single project class
    """

    __tablename__ = "enrollment_record"

    id = db.Column(db.Integer(), primary_key=True)

    # pointer to project class for which this is an enrolment record
    pclass_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"))
    pclass = db.relationship(
        "ProjectClass",
        uselist=False,
        foreign_keys=[pclass_id],
        backref=db.backref(
            "enrollments", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # pointer to faculty member this record is associated with
    owner_id = db.Column(db.Integer(), db.ForeignKey("faculty_data.id"))
    owner = db.relationship(
        "FacultyData",
        uselist=False,
        foreign_keys=[owner_id],
        backref=db.backref(
            "enrollments", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # SUPERVISOR STATUS

    # enrolment for supervision
    SUPERVISOR_ENROLLED = 1
    SUPERVISOR_SABBATICAL = 2
    SUPERVISOR_EXEMPT = 3
    supervisor_choices = [
        (SUPERVISOR_ENROLLED, "Normally enrolled"),
        (SUPERVISOR_SABBATICAL, "On sabbatical or buy-out"),
        (SUPERVISOR_EXEMPT, "Exempt"),
    ]
    supervisor_state = db.Column(db.Integer(), index=True)

    # comment (eg. can be used to note circumstances of exemptions)
    supervisor_comment = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # sabbatical auto re-enrol year (after sabbatical)
    supervisor_reenroll = db.Column(db.Integer())

    # MARKER STATUS

    # enrolment for marking
    MARKER_ENROLLED = 1
    MARKER_SABBATICAL = 2
    MARKER_EXEMPT = 3
    marker_choices = [
        (MARKER_ENROLLED, "Normally enrolled"),
        (MARKER_SABBATICAL, "On sabbatical or buy-out"),
        (MARKER_EXEMPT, "Exempt"),
    ]
    marker_state = db.Column(db.Integer(), index=True)

    # comment (eg. can be used to note circumstances of exemption)
    marker_comment = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    # marker auto re-enrol year (after sabbatical)
    marker_reenroll = db.Column(db.Integer())

    # MODERATOR STATUS

    # enrolment for moderation
    MODERATOR_ENROLLED = 1
    MODERATOR_SABBATICAL = 2
    MODERATOR_EXEMPT = 3
    moderator_choices = [
        (MODERATOR_ENROLLED, "Normally enrolled"),
        (MODERATOR_SABBATICAL, "On sabbatical or buy-out"),
        (MODERATOR_EXEMPT, "Exempt"),
    ]
    moderator_state = db.Column(db.Integer(), index=True)

    # comment (e.g. can be used to note circumstances of exemption)
    moderator_comment = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # moderator auto re-enrol year (after sabbatical)
    moderator_reenroll = db.Column(db.Integer())

    # PRESENTATION ASSESSOR STATUS

    # enrolment for assessing talks
    PRESENTATIONS_ENROLLED = 1
    PRESENTATIONS_SABBATICAL = 2
    PRESENTATIONS_EXEMPT = 3
    presentations_choices = [
        (MARKER_ENROLLED, "Normally enrolled"),
        (MARKER_SABBATICAL, "On sabbatical or buy-out"),
        (MARKER_EXEMPT, "Exempt"),
    ]
    presentations_state = db.Column(db.Integer(), index=True)

    # comment (eg. can be used to note circumstances of exemption)
    presentations_comment = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # marker auto re-enrol year (after sabbatical)
    presentations_reenroll = db.Column(db.Integer())

    # CUSTOM CATS LIMITS - these should be blanked every year

    # custom limit for supervising
    CATS_supervision = db.Column(db.Integer())

    # custom limit for marking
    CATS_marking = db.Column(db.Integer())

    # custom limit for moderation
    CATS_moderation = db.Column(db.Integer())

    # custom limit for presentations
    CATS_presentation = db.Column(db.Integer())

    @orm.reconstructor
    def _reconstruct(self):
        if self.supervisor_state is None:
            self.supervisor_state = EnrollmentRecord.SUPERVISOR_ENROLLED

        if self.marker_state is None:
            self.marker_state = EnrollmentRecord.MARKER_ENROLLED

        if self.presentations_state is None:
            self.presentations_state = EnrollmentRecord.PRESENTATIONS_ENROLLED

    def _generic_label(
        self, label, state, reenroll, comment, enrolled, sabbatical, exempt
    ):
        data = {"label": label}

        if state == enrolled:
            data |= {"suffix": "active", "type": "info"}
            return data

        # comment popover is added only if status is not active
        if comment is not None:
            bleach = current_app.extensions["bleach"]
            data["popover"] = bleach.clean(comment)

        if state == sabbatical:
            data |= {
                "suffix": "sab" if reenroll is None else f"sab {reenroll}",
                "type": "warning",
            }
            return data

        if state == exempt:
            data |= {"suffix": "exempt", "type": "danger"}
            return data

        data["type"] = "danger"
        data["label"] = "Unknown"
        return data

    @property
    def supervisor_label(self):
        return self._generic_label(
            "Supervisor",
            self.supervisor_state,
            self.supervisor_reenroll,
            self.supervisor_comment,
            EnrollmentRecord.SUPERVISOR_ENROLLED,
            EnrollmentRecord.SUPERVISOR_SABBATICAL,
            EnrollmentRecord.SUPERVISOR_EXEMPT,
        )

    @property
    def marker_label(self):
        return self._generic_label(
            "Marker",
            self.marker_state,
            self.marker_reenroll,
            self.marker_comment,
            EnrollmentRecord.MARKER_ENROLLED,
            EnrollmentRecord.MARKER_SABBATICAL,
            EnrollmentRecord.MARKER_EXEMPT,
        )

    @property
    def moderator_label(self):
        return self._generic_label(
            "Moderator",
            self.moderator_state,
            self.moderator_reenroll,
            self.moderator_comment,
            EnrollmentRecord.MODERATOR_ENROLLED,
            EnrollmentRecord.MODERATOR_SABBATICAL,
            EnrollmentRecord.MODERATOR_EXEMPT,
        )

    @property
    def presentation_label(self):
        return self._generic_label(
            "Presentations",
            self.presentations_state,
            self.presentations_reenroll,
            self.presentations_comment,
            EnrollmentRecord.PRESENTATIONS_ENROLLED,
            EnrollmentRecord.PRESENTATIONS_SABBATICAL,
            EnrollmentRecord.PRESENTATIONS_EXEMPT,
        )

    @property
    def enrolled_labels(self):
        labels = []

        if self.pclass.uses_supervisor:
            labels.append(self.supervisor_label)
        if self.pclass.uses_marker:
            labels.append(self.marker_label)
        if self.pclass.uses_moderator:
            labels.append(self.moderator_label)
        if self.pclass.uses_presentations:
            labels.append(self.presentation_label)

        return labels


def _delete_EnrollmentRecord_cache(faculty_id):
    from .live_projects import LiveProject
    from .scheduling import (
        ScheduleAttempt,
        ScheduleSlot,
        _ScheduleAttempt_is_valid,
        _ScheduleSlot_is_valid,
    )
    from .utilities import _MatchingAttempt_is_valid

    cache.delete_memoized(_Project_is_offerable)
    cache.delete_memoized(_Project_num_assessors)
    cache.delete_memoized(_Project_num_supervisors)

    year = _get_current_year()

    marker_records = (
        db.session.query(MatchingRecord)
        .join(MatchingAttempt, MatchingAttempt.id == MatchingRecord.matching_id)
        .filter(
            MatchingAttempt.year == year,
            MatchingRecord.roles.any(
                and_(
                    MatchingRole.user_id == faculty_id,
                    MatchingRole.role == MatchingRole.ROLE_MARKER,
                )
            ),
        )
    )

    superv_records = (
        db.session.query(MatchingRecord)
        .join(MatchingAttempt, MatchingAttempt.id == MatchingRecord.matching_id)
        .filter(MatchingAttempt.year == year)
        .join(LiveProject, LiveProject.id == MatchingRecord.project_id)
        .filter(LiveProject.owner_id == faculty_id)
    )

    match_records = marker_records.union(superv_records)

    for record in match_records:
        cache.delete_memoized(_MatchingRecord_is_valid, record.id)
        cache.delete_memoized(_MatchingAttempt_is_valid, record.matching_id)

    schedule_slots = (
        db.session.query(ScheduleSlot)
        .join(ScheduleAttempt, ScheduleAttempt.id == ScheduleSlot.owner_id)
        .join(
            PresentationAssessment,
            PresentationAssessment.id == ScheduleAttempt.owner_id,
        )
        .filter(
            PresentationAssessment.year == year,
            ScheduleSlot.assessors.any(id=faculty_id),
        )
    )
    for slot in schedule_slots:
        cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)
        cache.delete_memoized(_ScheduleAttempt_is_valid, slot.owner_id)
        if slot.owner is not None:
            cache.delete_memoized(_PresentationAssessment_is_valid, slot.owner.owner_id)


@listens_for(EnrollmentRecord, "before_update")
def _EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_EnrollmentRecord_cache(target.owner_id)


@listens_for(EnrollmentRecord, "before_insert")
def _EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_EnrollmentRecord_cache(target.owner_id)


@listens_for(EnrollmentRecord, "before_delete")
def _EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_EnrollmentRecord_cache(target.owner_id)


class Supervisor(db.Model, ColouredLabelMixin, EditingMetadataMixin):
    """
    Model a supervision team member
    """

    # make table name plural
    __tablename__ = "supervision_team"

    id = db.Column(db.Integer(), primary_key=True)

    # role name
    name = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True
    )

    # role abbreviation
    abbreviation = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), unique=True, index=True
    )

    # active flag
    active = db.Column(db.Boolean())

    def disable(self):
        """
        Disable this supervisory role and cascade, ie. remove from any projects that have been labelled with it
        :return:
        """

        self.active = False

        # remove this supervisory role from any projects that have been labelled with it
        for proj in self.projects:
            proj.team.remove(self)

    def enable(self):
        """
        Enable this supervisory role
        :return:
        """

        self.active = True

    def make_label(self, text=None):
        if text is None:
            text = self.abbreviation

        return self._make_label(text)
