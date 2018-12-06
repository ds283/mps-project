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
    PresentationAssessment, GeneratedAsset, UploadedAsset
from ..shared.utils import get_current_year, canonical_generated_asset_filename, canonical_uploaded_asset_filename

from datetime import datetime
from os import path, remove


def register_maintenance_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def maintenance(self):
        projects_maintenance(self)
        assessor_attendance_maintenance()
        submitter_attendance_maintenance(self)

        self.update_state(state='SUCCESS')


    def submitter_attendance_maintenance(self):
        current_year = get_current_year()
        try:
            records = db.session.query(SubmitterAttendanceData) \
                .join(PresentationAssessment, PresentationAssessment.id == SubmitterAttendanceData.assessment_id) \
                .filter(PresentationAssessment.year == current_year).all()

        except SQLAlchemyError:
            raise self.retry()

        task = group(submitter_attendance_record_maintenance.s(r.id) for r in records)
        task.apply_async()


    def assessor_attendance_maintenance(self):
        current_year = get_current_year()
        try:
            records = db.session.query(AssessorAttendanceData) \
                .join(PresentationAssessment, PresentationAssessment.id == AssessorAttendanceData.assessment_id) \
                .filter(PresentationAssessment.year == current_year).all()

        except SQLAlchemyError:
            raise self.retry()

        task = group(assessor_attendance_record_maintenance.s(r.id) for r in records)
        task.apply_async()


    def projects_maintenance(self):
        try:
            records = db.session.query(Project).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(project_record_maintenance.s(p.id) for p in records)
        task.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def project_record_maintenance(self, pid):
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
    def assessor_attendance_record_maintenance(self, id):
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
    def submitter_attendance_record_maintenance(self, id):
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


    @celery.task(bind=True, default_retry_delay=30)
    def asset_garbage_collection(self):
        collect_generated_garbage(self)
        collect_uploaded_garbage(self)


    def collect_generated_garbage(self):
        try:
            records = db.session.query(GeneratedAsset).all()
        except SQLAlchemyError:
            raise self.retry()

        expiry = group(asset_check_expiry.si(r.id, GeneratedAsset, canonical_generated_asset_filename) for r in records)
        expiry.apply_async()

        orphan = group(asset_check_orphan.si(r.id, GeneratedAsset, canonical_generated_asset_filename) for r in records)
        orphan.apply_async()


    def collect_uploaded_garbage(self):
        try:
            records = db.session.query(UploadedAsset).all()
        except SQLAlchemyError:
            raise self.retry()

        expiry = group(asset_check_expiry.si(r.id, UploadedAsset, canonical_uploaded_asset_filename) for r in records)
        expiry.apply_async()

        orphan = group(asset_check_orphan.si(r.id, UploadedAsset, canonical_uploaded_asset_filename) for r in records)
        orphan.apply_async()


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_expiry(self, id, RecordType, canonicalizer):
        try:
            record = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            raise Ignore

        now = datetime.now()
        age = now - record.timestamp

        if age.total_seconds() > record.lifetime:
            abs_asset_path = canonicalizer(record.filename)

            if path.exists(abs_asset_path) and path.isfile(abs_asset_path):
                try:
                    remove(abs_asset_path)
                except OSError:
                    raise Ignore

                try:
                    db.session.delete(record)
                    db.session.commit()
                except SQLAlchemyError:
                    raise self.retry()


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_orphan(self, id, RecordType, canonicalizer):
        try:
            record = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            raise Ignore

        abs_asset_path = canonicalizer(record.filename)
        if not path.exists(abs_asset_path):
            try:
                db.session.delete(record)
                db.session.commit()
            except SQLAlchemyError:
                raise self.retry()
