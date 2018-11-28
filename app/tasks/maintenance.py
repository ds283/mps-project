#
# Created by David Seery on 2018-11-02.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from sqlalchemy.exc import SQLAlchemyError

from celery import group
from celery.exceptions import Ignore

from ..database import db
from ..models import Project, AssessorAttendanceData, SubmitterAttendanceData, PresentationSession, \
    PresentationAssessment
from ..shared.utils import get_current_year


def register_maintenance_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def maintenance(self):
        try:
            projects = db.session.query(Project).all()
        except SQLAlchemyError:
            raise self.retry()

        projects_task = group(project_maintenance.s(p.id) for p in projects)
        projects_task.apply_async()

        current_year = get_current_year()

        try:
            assessor_attendance = db.session.query(AssessorAttendanceData) \
                .join(PresentationAssessment, PresentationAssessment.id == AssessorAttendanceData.assessment_id) \
                .filter(PresentationAssessment.year == current_year).all()
        except SQLAlchemyError:
            raise self.retry()

        assessors_task = group(assessor_maintenance.s(r.id) for r in assessor_attendance)
        assessors_task.apply_async()

        try:
            submitter_attendance = db.session.query(SubmitterAttendanceData) \
                .join(PresentationAssessment, PresentationAssessment.id == SubmitterAttendanceData.assessment_id) \
                .filter(PresentationAssessment.year == current_year).all()
        except SQLAlchemyError:
            raise self.retry()

        submitters_task = group(submitter_maintenance.s(r.id) for r in submitter_attendance)
        submitters_task.apply_async()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def project_maintenance(self, pid):
        try:
            project = db.session.query(Project).filter_by(id=pid).first()
        except SQLAlchemyError:
            raise self.retry()

        if project is None:
            raise Ignore

        if project.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def assessor_maintenance(self, id):
        try:
            record = db.session.query(AssessorAttendanceData).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            raise Ignore

        if record.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def submitter_maintenance(self, id):
        try:
            record = db.session.query(SubmitterAttendanceData).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            raise Ignore

        if record.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()

        self.update_state(state='SUCCESS')
