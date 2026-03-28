#
# Created by David Seery on 28/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from celery.exceptions import Ignore
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    CustomOfferHint,
    FacultyData,
    ProjectClassConfig,
    SelectingStudent,
    StudentData,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    User,
)
from ..shared.workflow_logging import log_db_commit


def generate_hints_for_selector(
    selector: SelectingStudent,
    config: ProjectClassConfig,
    restrict_to_faculty_id: int = None,
) -> int:
    """
    For a single SelectingStudent, examine retired SubmittingStudent instances from previous
    cycles (of any project class) for the same StudentData.  For each SubmissionRecord where:
      (a) a previous faculty member who had a supervision role, and has live projects in the current config, AND
      (b) no hint already exists for this (selector, submission_record) pair,
    create a CustomOfferHint.

    If restrict_to_faculty_id is provided, only consider supervision history involving that
    specific faculty member (identified by their FacultyData/User id).  This is used when
    hints are being regenerated after a single LiveProject injection, to avoid recreating
    hints for other faculty members whose hints were previously rejected.

    Returns the number of new hints created.
    Raises SQLAlchemyError on database failure; the caller is responsible for rollback.
    """
    student: StudentData = selector.student
    suser: User = student.user
    student_id = selector.student_id

    # Find all previous supervisors for this student, in any project class, where the
    # parent SubmittingStudent has been retired (so these come from a previous academic cycle)
    retired_supervisors_q = (
        db.session.query(SubmissionRole)
        .join(SubmissionRecord, SubmissionRecord.id == SubmissionRole.submission_id)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .filter(
            SubmissionRole.role.in_(
                [
                    SubmissionRole.ROLE_SUPERVISOR,
                    SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                ]
            ),
            SubmittingStudent.student_id == student_id,
            SubmittingStudent.retired.is_(True),
        )
    )

    if restrict_to_faculty_id is not None:
        retired_supervisors_q = retired_supervisors_q.filter(
            SubmissionRole.user_id == restrict_to_faculty_id
        )

    retired_supervisors = retired_supervisors_q.all()

    hints_created = 0

    for supervisor in retired_supervisors:
        supervisor: SubmissionRole
        record: SubmissionRecord = supervisor.submission
        fuser: User = supervisor.user
        fd: FacultyData = fuser.faculty_data

        if fd is not None:
            # Only create a hint if the faculty member has live projects in the current config
            has_live_projects = (
                config.live_projects.filter_by(owner_id=fd.id).count() > 0
            )
            if not has_live_projects:
                print(
                    f"@@ student {suser.name} has previous supervisor {fuser.name} (#{fd.id}), but this supervisor has no projects in the current cycle"
                )
                continue

            # Skip if a hint already exists for this (selector, submission_record) pair
            exists = (
                db.session.query(CustomOfferHint)
                .filter_by(selector_id=selector.id, submission_record_id=record.id)
                .first()
                is not None
            )
            if exists:
                print(
                    f"@@ student {suser.name} has previous supervisor {fuser.name} (#{fd.id}), but a hint already exists for this (selector, submission_record) pair"
                )
                continue

            hint = CustomOfferHint(
                selector_id=selector.id,
                submission_record_id=record.id,
                faculty_id=fd.id,
                creation_timestamp=datetime.now(),
            )
            db.session.add(hint)
            print(
                f"@@ student {suser.name} has previous supervisor {fuser.name} (#{fd.id}), so creating a hint for this (selector, submission_record) pair"
            )
            hints_created += 1

    if hints_created > 0:
        db.session.flush()

    return hints_created


def register_custom_offer_hint_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def generate_hints_for_config(self, config_id, restrict_to_faculty_id=None):
        """
        Generate CustomOfferHints for all active (non-retired) SelectingStudents in
        the given ProjectClassConfig.  Called fire-and-forget after Go Live finalisation
        and after inject_liveproject completes (when the config is still live).

        If restrict_to_faculty_id is provided, only hints relating to that specific faculty
        member are generated.  This prevents previously-rejected hints from being
        recreated when a single new LiveProject is injected during the selection period.
        """
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(
                id=config_id
            ).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load ProjectClassConfig record from database"},
            )
            raise Ignore()

        selectors = config.selecting_students.filter_by(retired=False).all()
        total_hints = 0

        for selector in selectors:
            try:
                n = generate_hints_for_selector(
                    selector, config, restrict_to_faculty_id=restrict_to_faculty_id
                )
                total_hints += n
                if n > 0:
                    log_db_commit(
                        f"Generated {n} CustomOfferHint(s) for selector "
                        f"{selector.student.user.name} in {config.name}",
                        project_classes=config.project_class,
                        endpoint=self.name,
                    )
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                # Continue with next selector rather than aborting the whole run

        # Mark hint generation as complete on the config
        try:
            config.offer_hints_generated = True
            config.offer_hints_generated_timestamp = datetime.now()
            log_db_commit(
                f"CustomOfferHint generation complete for {config.name}: "
                f"{total_hints} hint(s) created across {len(selectors)} selector(s)",
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
