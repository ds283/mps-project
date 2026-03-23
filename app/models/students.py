#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .live_projects import SelectingStudent, SubmittingStudent

from sqlalchemy import and_
from sqlalchemy.orm import validates
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from ..database import db
from ..shared.sqlalchemy import get_count
from .associations import student_batch_to_tenants
from .config import get_AES_key
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import (
    EditingMetadataMixin,
    WorkflowHistoryMixin,
    WorkflowMixin,
    _get_current_year,
)


class StudentDataWorkflowHistory(db.Model, WorkflowHistoryMixin):
    __tablename__ = "workflow_studentdata"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # owning StudentData instance
    owner_id = db.Column(db.Integer(), db.ForeignKey("student_data.id"))
    owner = db.relationship(
        "StudentData",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref("workflow_history", lazy="dynamic"),
    )


class StudentData(db.Model, WorkflowMixin, EditingMetadataMixin):
    """
    Models extra data held on students
    """

    __tablename__ = "student_data"

    # which model should we use to generate history records
    __history_model__ = StudentDataWorkflowHistory

    # primary key is same as users.id for this student member
    id = db.Column(db.Integer(), db.ForeignKey("users.id"), primary_key=True)
    user = db.relationship(
        "User", foreign_keys=[id], backref=db.backref("student_data", uselist=False)
    )

    # ATAS CONFIGURATION

    # is this user ATAS restricted?
    ATAS_restricted = db.Column(db.Boolean(), default=False)

    # IDENTIFIERS

    # registration number
    registration_number = db.Column(db.Integer(), unique=True)

    # exam number is needed for marking
    # we store this encrypted out of prudence. Note that we use AesEngine which is the less secure of the two
    # AES choices provided by SQLAlchemyUtils, but which can perform queries against the field
    exam_number = db.Column(
        EncryptedType(db.Integer(), get_AES_key, AesEngine, "oneandzeroes")
    )

    # STUDENT INFORMATION

    # cohort is used to compute this student's academic year, and
    # identifies which project classes this student will be enrolled for
    cohort = db.Column(db.Integer(), index=True)

    # degree programme
    programme_id = db.Column(db.Integer, db.ForeignKey("degree_programmes.id"))
    programme = db.relationship(
        "DegreeProgramme",
        foreign_keys=[programme_id],
        uselist=False,
        backref=db.backref("students", lazy="dynamic"),
    )

    # did this student do a foundation year? This information is partially contained in the
    # degree programme, but can become 'detached' if the programme is changed at a later point.
    # We allow a separate per-student 'foundation_year' flag to catch cases like this
    foundation_year = db.Column(db.Boolean())

    # has this student had repeat years? If so, they also upset the academic year calculation
    repeated_years = db.Column(db.Integer())

    # is this student currently intermitting?
    intermitting = db.Column(db.Boolean(), default=None)

    # cache current academic year; introduced because the academic year calculation is now quite complex
    # (eg. allowing for foundation year, repeated year, years out on industrial placement or year abroad).
    # The calculation is too complex to write performant queries against.
    # This field should not be set directly. It should be recalculated when the record is changed,
    # or otherwise on a reasonably frequent basis as part of normal database maintenance
    academic_year = db.Column(db.Integer(), default=None)

    # SEND LABELLING

    # requires dyspraxia sticker on reports distributed for marking?
    dyspraxia_sticker = db.Column(db.Boolean(), default=False, nullable=False)

    # requires dyslexia stricker on reports distributed for marking?
    dyslexia_sticker = db.Column(db.Boolean(), default=False, nullable=False)

    def _get_raw_provisional_year(self, cohort, repeat_years):
        if cohort is None:
            return None

        current_year = _get_current_year()
        if current_year is None:
            return None

        if cohort > current_year:
            return None

        if repeat_years is None:
            repeat_years = 0

        return (
            current_year
            - cohort
            + 1
            - (1 if self.has_foundation_year else 0)
            - repeat_years
        )

    def _get_provisional_year(self, cohort, repeat_years):
        from .academic import DegreeProgramme

        provisional_year = self._get_raw_provisional_year(cohort, repeat_years)

        if provisional_year is None:
            return None

        current_programme: DegreeProgramme = self.programme

        if current_programme is not None and current_programme.year_out:
            year_out_value = current_programme.year_out_value

            if provisional_year == year_out_value:
                provisional_year = None
            elif provisional_year > year_out_value:
                provisional_year = provisional_year - 1

        return provisional_year

    @validates("exam_number")
    def _queue_for_validation(self, key, value):
        with db.session.no_autoflush:
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

        return value

    @validates("foundation_year")
    def _validate_foundation_year(self, key, value):
        """
        Adjust foundation_year value to correspond with assigned programme of study
        :param key: name of edited attribute
        :param value: new value
        :return: value to be stored in named attribute
        """
        # allow validation to be disabled during batch import
        if hasattr(self, "disable_validate"):
            return value

        # if setting to false, assume user knows what they are doing
        self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

        if not value:
            return False

        # if programme already includes a foundation year, our own flag should be set to false
        if self.programme.foundation_year:
            value = False

        # recalculate current academic year
        provisional_year = self._get_provisional_year(self.cohort, self.repeated_years)
        if provisional_year is not None and provisional_year < 0:
            provisional_year = None

        self.disable_validate = True
        self.academic_year = provisional_year
        del self.disable_validate

        # otherwise, return true
        return value

    @validates("cohort")
    def _validate_cohort(self, key, value):
        """
        Adjust academic_year and repeated_years to match new value for cohort
        :param key: name of edited attribute
        :param value: new value
        :return: value to be stored in named attribute
        """
        # allow validation to be disabled during batch import
        if hasattr(self, "disable_validate"):
            return value

        with db.session.no_autoflush:
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

            provisional_year = self._get_provisional_year(value, self.repeated_years)

            if provisional_year is not None and provisional_year < (
                0 if self.has_foundation_year else 1
            ):
                diff = self.repeated_years - abs(provisional_year)

                if diff >= 0:
                    self.repeated_years = self.repeated_years - diff
                    provisional_year = provisional_year + diff
                else:
                    raise ValueError

            self.disable_validate = True
            self.academic_year = provisional_year
            del self.disable_validate

        return value

    @validates("academic_year")
    def _validate_academic_year(self, key, value):
        """
        Adjust number of repeated years to match new value for academic year
        :param key: name of edited attribute
        :param value: new value
        :return: value to be stored in named attribute
        """
        # allow validation to be disabled during batch import
        if not hasattr(self, "disable_validate"):
            with db.session.no_autoflush:
                self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

                provisional_year = self._get_provisional_year(
                    self.cohort, self.repeated_years
                )

                self.disable_validate = True

                if provisional_year is not None and provisional_year != value:
                    if provisional_year > value:
                        self.repeated_years = provisional_year - value

                    elif provisional_year < value:
                        diff = self.repeated_years - abs(provisional_year)

                        if diff >= 0:
                            self.repeated_years = self.repeated_years - diff
                        else:
                            raise ValueError

                del self.disable_validate

        return value

    @validates("repeated_years")
    def _validate_repeated_years(self, key, value):
        """
        Adjust academic year to match new value for repeated_years
        :param key: name of edited attribute
        :param value: new value
        :return: value to be stored in named attribute
        """
        # allow validation to be disabled during batch import
        if hasattr(self, "disable_validate"):
            return value

        with db.session.no_autoflush:
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

            if value < 0:
                value = 0

            provisional_year = self._get_provisional_year(self.cohort, value)

            if provisional_year is not None and provisional_year < (
                0 if self.has_foundation_year else 1
            ):
                raise ValueError

            self.disable_validate = True
            self.academic_year = provisional_year
            del self.disable_validate

        return value

    @validates("programme_id")
    def _validate_programme(self, key, value):
        """
        When changing programme, if old programme had foundation year but new programme does not,
        set our local foundation_year_flag
        :param key:
        :param value:
        :return:
        """
        from .academic import DegreeProgramme

        if hasattr(self, "disable_validate"):
            return value

        with db.session.no_autoflush:
            self.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED

            current_programme = self.programme

            if current_programme is None:
                if self.programme_id is None:
                    return value

                current_programme: DegreeProgramme = (
                    db.session.query(DegreeProgramme)
                    .filter_by(id=self.programme_id)
                    .first()
                )

            if current_programme is None:
                return value

            if not current_programme.foundation_year:
                return value

            programme: DegreeProgramme = (
                db.session.query(DegreeProgramme).filter_by(id=value).first()
            )

            if not programme.foundation_year:
                self.disable_validate = True
                self.foundation_year = True
                del self.disable_validate

        return value

    @property
    def name(self):
        return self.user.name

    @property
    def email(self):
        return self.user.email

    @property
    def cohort_label(self):
        return {"label": f"{self.cohort} cohort", "type": "info"}

    @property
    def exam_number_label(self):
        if self.exam_number is None:
            return {"label": "Exam #TBA", "type": "secondary"}

        return {"label": f"#{self.exam_number}"}

    @property
    def has_foundation_year(self):
        from .academic import DegreeProgramme

        if self.programme is not None and self.programme.foundation_year:
            return True

        if self.programme_id is not None:
            programme = (
                db.session.query(DegreeProgramme)
                .filter_by(id=self.programme_id)
                .first()
            )
            if programme is not None and programme.foundation_year:
                return True

        return self.foundation_year

    @property
    def has_graduated(self):
        if self.academic_year is None:
            return None

        diff = (
            self.academic_year
            - self.programme.degree_type.duration
            - (1 if self.programme.year_out else 0)
        )

        if diff <= 0:
            return False

        return True

    def compute_academic_year(self, desired_year, current_year=None):
        """
        Computes the academic year of a student, relative to a given year
        :param desired_year:
        :return:
        """
        if self.academic_year is None:
            return None

        if current_year is None:
            current_year = _get_current_year()

        diff = desired_year - current_year

        return self.academic_year + diff

    def academic_year_label(
        self, desired_year=None, show_details=False, current_year=None
    ):
        if desired_year is not None:
            academic_year = self.compute_academic_year(
                desired_year, current_year=current_year
            )
        else:
            academic_year = self.academic_year

        if not self.user.active:
            text = "Inactive"
            type = "secondary"
        elif self.has_graduated:
            text = "Graduated"
            type = "primary"
        elif academic_year is None:
            text = None
            type = None

            if self.cohort is not None:
                current_year = _get_current_year()

                if self.cohort > current_year:
                    text = "Awaiting rollover..."
                    type = "warning"

                elif self.programme is not None and self.programme.year_out:
                    check_year = self._get_raw_provisional_year(
                        self.cohort, self.repeated_years
                    )

                    if check_year == self.programme.year_out_value:
                        text = "Year out"
                        type = "info"

            if text is None:
                text = "Awaiting update..."
                type = "secondary"
        elif academic_year < 0:
            text = "Error(<0)"
            type = "danger"
        else:
            text = "Y{y}".format(y=academic_year)
            type = "info"

            if show_details:
                if self.has_foundation_year:
                    text += " F"

                if self.repeated_years > 0:
                    text += " R{n}".format(n=self.repeated_years)

        return {"label": text, "type": type}

    @property
    def has_timeline(self):
        # we allow published or unpublished records in the timeline
        return (
            self.selecting.filter_by(retired=True).first() is not None
            or self.submitting.filter_by(retired=True).first() is not None
        )

    @property
    def has_previous_submissions(self):
        # this is intended to count "real" submissions, so we drop any records that
        # have not been published
        return (
            self.submitting.filter_by(retired=True, published=True).first() is not None
        )

    def collect_student_records(self):
        selector_records = {}
        submitter_records = {}

        years = set()

        for rec in self.selecting.filter_by(retired=True):
            rec: "SelectingStudent"
            if rec.config is not None and rec.config.year is not None:
                year = rec.config.year
                years.add(year)

                if year not in selector_records:
                    selector_records[year] = []
                selector_records[year].append(rec)

        for rec in self.submitting.filter_by(retired=True):
            rec: "SubmittingStudent"
            if rec.config is not None and rec.config.year is not None:
                year = rec.config.year
                years.add(year)

                if year not in submitter_records:
                    submitter_records[year] = []
                submitter_records[year].append(rec)

        return sorted(years, reverse=True), selector_records, submitter_records

    @property
    def ordered_selecting(self):
        from .live_projects import SelectingStudent
        from .project_class import ProjectClass, ProjectClassConfig

        return (
            self.selecting.join(
                ProjectClassConfig, ProjectClassConfig.id == SelectingStudent.config_id
            )
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
            .order_by(ProjectClass.name.asc())
        )

    @property
    def ordered_submitting(self):
        from .live_projects import SubmittingStudent
        from .project_class import ProjectClass, ProjectClassConfig

        return (
            self.submitting.join(
                ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id
            )
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
            .order_by(ProjectClass.name.asc())
        )

    @property
    def active_availability_events(self):
        from .assessment import PresentationAssessment, SubmitterAttendanceData
        from .live_projects import SubmittingStudent
        from .submissions import SubmissionRecord

        return (
            db.session.query(PresentationAssessment, SubmissionRecord)
            .join(
                SubmitterAttendanceData,
                and_(
                    SubmitterAttendanceData.assessment_id == PresentationAssessment.id,
                ),
            )
            .join(
                SubmissionRecord,
                SubmissionRecord.id == SubmitterAttendanceData.submitter_id,
            )
            .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
            .filter(
                PresentationAssessment.year == _get_current_year(),
                PresentationAssessment.availability_closed.is_(False),
                SubmissionRecord.retired.is_(False),
                SubmittingStudent.student_id == self.id,
            )
            .order_by(PresentationAssessment.name.asc())
        )

    @property
    def has_active_availability_events(self):
        return get_count(self.active_availability_events) > 0

    def maintenance(self):
        edited = False

        # repeated years should not be negative
        if self.repeated_years < 0:
            self.repeated_years = 0
            edited = True

        # programme foundation year flag and local foundation year flag should not both be set; if they are, clear
        # the local flag
        if self.programme.foundation_year and self.foundation_year:
            self.foundation_year = False
            edited = True

        # check current academic year
        provisional_year = self._get_provisional_year(self.cohort, self.repeated_years)
        if provisional_year != self.academic_year:
            if provisional_year is not None and provisional_year < (
                0 if self.has_foundation_year else 1
            ):
                diff = self.repeated_years - abs(provisional_year)

                if diff >= 0:
                    self.repeated_years = self.repeated_years - diff
                    provisional_year = provisional_year + diff
                else:
                    provisional_year = None

            self.academic_year = provisional_year
            edited = True

        return edited


class StudentBatch(db.Model):
    """
    Model a batch import of student accounts
    """

    __tablename__ = "batch_student"

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
        backref=db.backref("student_batch_imports", lazy="dynamic"),
    )

    # tenants to assign to imported users
    tenants = db.relationship(
        "Tenant",
        secondary=student_batch_to_tenants,
        lazy="dynamic",
        backref=db.backref("student_batches", lazy="dynamic"),
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

    # were we told to trust cohort data?
    trust_cohort = db.Column(db.Boolean(), default=False)

    # were we told to trust registration numbers?
    trust_registration = db.Column(db.Boolean(), default=False)

    # are we ignoring Y0 students
    ignore_Y0 = db.Column(db.Boolean(), default=True)

    # what was the reference academic year (the one used to calculate all student years)
    academic_year = db.Column(db.Integer())

    # cached import report
    report = db.Column(db.Text())

    @property
    def number_items(self):
        return get_count(self.items)


class StudentBatchItem(db.Model):
    """
    Model an individual record in a batch import of student accounts
    """

    __tablename__ = "batch_student_items"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # parent StudentBatch instance
    parent_id = db.Column(db.Integer(), db.ForeignKey("batch_student.id"))
    parent = db.relationship(
        "StudentBatch",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref(
            "items", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # optional link to an existing StudentData instance
    existing_id = db.Column(db.Integer(), db.ForeignKey("student_data.id"))
    existing_record = db.relationship(
        "StudentData",
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

    # registration number
    registration_number = db.Column(db.Integer())

    # cohort
    cohort = db.Column(db.Integer())

    # degree programme
    programme_id = db.Column(db.Integer, db.ForeignKey("degree_programmes.id"))
    programme = db.relationship(
        "DegreeProgramme", foreign_keys=[programme_id], uselist=False
    )

    # did this student do a foundation year? if so, their admission cohort
    # needs to be treated differently when calculating academic years
    foundation_year = db.Column(db.Boolean(), default=False)

    # has this student had repeat years? If so, they also upset the academic year calculation
    repeated_years = db.Column(db.Integer(), default=0)

    # is this student intermitting?
    intermitting = db.Column(db.Boolean(), default=False)

    # METADATA

    # flag as "don't convert to user"
    dont_convert = db.Column(db.Boolean(), default=False)

    @property
    def has_foundation_year(self):
        from .academic import DegreeProgramme

        if self.programme is not None and self.programme.foundation_year:
            return True

        if self.programme_id is not None:
            programme = (
                db.session.query(DegreeProgramme)
                .filter_by(id=self.programme_id)
                .first()
            )
            if programme is not None and programme.foundation_year:
                return True

        return self.foundation_year

    @property
    def has_graduated(self):
        if self.programme is None:
            return None

        if self.academic_year is None:
            return None

        return self.academic_year > self.programme.degree_type.duration

    @property
    def academic_year(self):
        parent_year = None

        if self.parent is not None:
            parent_year = self.parent.academic_year

        elif self.parent_id is not None:
            parent = db.session.query(StudentBatch).filter_by(id=self.parent_id).first()
            if parent is not None:
                parent_year = parent.academic_year

        if parent_year is None:
            return None

        current_year = (
            parent_year
            - self.cohort
            + 1
            - (1 if self.has_foundation_year else 0)
            - self.repeated_years
        )

        if self.programme is not None and self.programme.year_out:
            if current_year == self.programme.year_out_value:
                return None
            elif current_year > self.programme.year_out_value:
                current_year = current_year - 1

        if current_year < 0:
            current_year = 0

        return current_year

    def academic_year_label(self, show_details=False):
        academic_year = self.academic_year

        if self.has_graduated:
            text = "Graduated"
            type = "primary"
        elif academic_year is None:
            text = "Year out"
            type = "secondary"
        elif academic_year < 0:
            text = "Error(<0)"
            type = "danger"
        else:
            text = "Y{y}".format(y=academic_year)
            type = "info"

            if show_details:
                if self.foundation_year:
                    text += " F"

                if self.repeated_years > 0:
                    text += " R{n}".format(n=self.repeated_years)

        return {"label": text, "type": type}

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

        if (
            self.registration_number is not None
            and self.existing_record.registration_number != self.registration_number
        ):
            w.append(
                f'Current registration number "{self.existing_record.registration_number}"'
            )

        if self.cohort is not None and self.existing_record.cohort != self.cohort:
            w.append(f"Current cohort {self.existing_record.cohort}")

        if (
            self.foundation_year is not None
            and self.existing_record.foundation_year != self.foundation_year
        ):
            w.append(
                f"Current foundation year flag ({str(self.existing_record.foundation_year)})"
            )

        if (
            self.repeated_years is not None
            and self.existing_record.repeated_years != self.repeated_years
        ):
            w.append(f"Current repeated years ({self.existing_record.repeated_years})")

        if (
            self.programme_id is not None
            and self.existing_record.programme_id != self.programme_id
        ):
            w.append(
                f'Current degree programme "{self.existing_record.programme.full_name}"'
            )

        return w
