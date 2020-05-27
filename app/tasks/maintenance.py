#
# Created by David Seery on 2018-11-02.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from pathlib import Path

from celery import group
from celery.exceptions import Ignore
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import Project, LiveProject, AssessorAttendanceData, SubmitterAttendanceData, \
    PresentationAssessment, GeneratedAsset, TemporaryAsset, ScheduleEnumeration, ProjectDescription, \
    MatchingEnumeration, SubmittedAsset, SubmissionRecord, ProjectClass, ProjectClassConfig
from ..shared.asset_tools import canonical_generated_asset_filename, canonical_temporary_asset_filename, \
    canonical_submitted_asset_filename
from ..shared.utils import get_current_year, get_count


def register_maintenance_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def maintenance(self):
        self.update_state(state='STARTED')

        projects_maintenance(self)
        liveprojects_maintenance(self)

        project_descriptions_maintenance(self)

        assessor_attendance_maintenance(self)
        submitter_attendance_maintenance(self)

        matching_enumeration_maintenance(self)
        schedule_enumeration_maintenance(self)

        submission_record_maintenance(self)

        self.update_state(state='SUCCESS')


    def submitter_attendance_maintenance(self):
        current_year = get_current_year()
        try:
            records = db.session.query(SubmitterAttendanceData) \
                .join(PresentationAssessment, PresentationAssessment.id == SubmitterAttendanceData.assessment_id) \
                .filter(PresentationAssessment.year == current_year).all()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(submitter_attendance_record_maintenance.s(r.id) for r in records)
        task.apply_async()


    def assessor_attendance_maintenance(self):
        current_year = get_current_year()
        try:
            records = db.session.query(AssessorAttendanceData) \
                .join(PresentationAssessment, PresentationAssessment.id == AssessorAttendanceData.assessment_id) \
                .filter(PresentationAssessment.year == current_year).all()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(assessor_attendance_record_maintenance.s(r.id) for r in records)
        task.apply_async()


    def projects_maintenance(self):
        try:
            records = db.session.query(Project).filter_by(active=True).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(project_record_maintenance.s(p.id) for p in records)
        task.apply_async()


    def liveprojects_maintenance(self):
        task = None

        try:
            pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

            for pcl in pclasses:
                config: ProjectClassConfig = pcl.most_recent_config

                if config is not None:
                    records = db.session.query(LiveProject).filter_by(config_id=config.id).all()

                    if task is None:
                        task = [liveproject_record_maintenance.s(p.id) for p in records]
                    else:
                        task += [liveproject_record_maintenance.s(p.id) for p in records]

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        tk_group = group(*task)
        tk_group.apply_async()


    def schedule_enumeration_maintenance(self):
        try:
            records = db.session.query(ScheduleEnumeration).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(schedule_enumeration_record_maintenance.s(r.id) for r in records)
        task.apply_async()


    def matching_enumeration_maintenance(self):
        try:
            records = db.session.query(MatchingEnumeration).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(matching_enumeration_record_maintenance.s(r.id) for r in records)
        task.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def project_record_maintenance(self, pid):
        try:
            project = db.session.query(Project).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if project is None:
            raise Ignore()

        if project.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def liveproject_record_maintenance(self, pid):
        try:
            project = db.session.query(LiveProject).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if project is None:
            raise Ignore()

        if project.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    def project_descriptions_maintenance(self):
        try:
            records = db.session.query(ProjectDescription).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(project_description_record_maintenance.s(pd.id) for pd in records)
        task.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def project_description_record_maintenance(self, pd_id):
        try:
            desc = db.session.query(ProjectDescription).filter_by(id=pd_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if desc is None:
            raise Ignore()

        if desc.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def assessor_attendance_record_maintenance(self, id):
        try:
            record = db.session.query(AssessorAttendanceData).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if record.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def submitter_attendance_record_maintenance(self, id):
        try:
            record = db.session.query(SubmitterAttendanceData).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if record.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def schedule_enumeration_record_maintenance(self, id):
        try:
            record = db.session.query(ScheduleEnumeration).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if not record.schedule.awaiting_upload:
            # can purge this record
            try:
                db.session.delete(record)
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def matching_enumeration_record_maintenance(self, id):
        try:
            record = db.session.query(MatchingEnumeration).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if not record.matching.awaiting_upload:
            # can purge this record
            try:
                db.session.delete(record)
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def asset_garbage_collection(self):
        collect_generated_garbage(self)
        collect_uploaded_garbage(self)
        collect_submitted_garbage(self)


    def collect_generated_garbage(self):
        try:
            # only filter out records that have a finite lifetime set
            records = db.session.query(GeneratedAsset).filter(GeneratedAsset.expiry != None).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        expiry = group(asset_check_expiry.si(r.id, GeneratedAsset, canonical_generated_asset_filename) for r in records)
        expiry.apply_async()

        orphan = group(asset_check_orphan.si(r.id, GeneratedAsset, canonical_generated_asset_filename) for r in records)
        orphan.apply_async()


    def collect_uploaded_garbage(self):
        try:
            # only filter out records that have a finite lifetime set
            records = db.session.query(TemporaryAsset).filter(TemporaryAsset.expiry != None).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        expiry = group(asset_check_expiry.si(r.id, TemporaryAsset, canonical_temporary_asset_filename) for r in records)
        expiry.apply_async()

        orphan = group(asset_check_orphan.si(r.id, TemporaryAsset, canonical_temporary_asset_filename) for r in records)
        orphan.apply_async()


    def collect_submitted_garbage(self):
        try:
            # only filter out records that have a finite lifetime set
            records = db.session.query(SubmittedAsset).filter(SubmittedAsset.expiry != None).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        expiry = group(asset_check_expiry.si(r.id, SubmittedAsset, canonical_submitted_asset_filename) for r in records)
        expiry.apply_async()

        orphan = group(asset_check_orphan.si(r.id, SubmittedAsset, canonical_submitted_asset_filename) for r in records)
        orphan.apply_async()

        try:
            # this time check all records that have no lifetime, to ensure they are attached
            records = db.session.query(SubmittedAsset).filter(SubmittedAsset.expiry == None).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        unattached = group(asset_check_attached.si(r.id, SubmittedAsset) for r in records)
        unattached.apply_async()


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_expiry(self, id, RecordType, canonicalizer):
        try:
            record = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if record.expiry < datetime.now():
            # canonicalizer is expected to return an object of type Path, or a class interoperable with it
            asset: Path = canonicalizer(record.filename)

            if asset.exists() and asset.is_file():
                try:
                    asset.unlink()
                except FileNotFoundError as e:
                    print('** Garbage collection failed to remove file "{file}"'.format(file=asset))
                    raise Ignore()

                print('** Garbage collection removed file "{file}"'.format(file=asset))

                try:
                    db.session.delete(record)
                    db.session.commit()
                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    raise self.retry()


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_orphan(self, id, RecordType, canonicalizer):
        try:
            record = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        asset: Path = canonicalizer(record.filename)

        # check if asset exists on disk; if not, remove the database record
        if not asset.exists():
            try:
                db.session.delete(record)
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_attached(self, id, RecordType):
        try:
            record = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        # check if attached
        if record.submission_attachment is None and record.period_attachment is None \
                and get_count(db.session.query(SubmissionRecord).filter_by(report_id=id)) == 0:
            print('** Garbage collection detected unattached SubmittedAsset record, id = {id}'.format(id=record.id))

            try:
                record.expiry = datetime.now() + timedelta(days=30)

                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()


    def submission_record_maintenance(self):
        try:
            records = db.session.query(SubmissionRecord).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(subrecord_maintenance.s(r.id) for r in records)
        task.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def subrecord_maintenance(self, rec_id):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if record.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state='SUCCESS')
