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
from typing import List, Iterable, Dict, Mapping

from celery import group
from celery.exceptions import Ignore
from flask import current_app, render_template
from flask_mailman import EmailMessage
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from .. import register_task
from ..database import db
from ..models import User, Project, LiveProject, AssessorAttendanceData, SubmitterAttendanceData, \
    PresentationAssessment, GeneratedAsset, TemporaryAsset, ScheduleEnumeration, ProjectDescription, \
    MatchingEnumeration, SubmittedAsset, SubmissionRecord, ProjectClass, ProjectClassConfig, StudentData, \
    DegreeProgramme, DegreeType
from ..shared.asset_tools import AssetCloudAdapter
from ..shared.utils import get_current_year, get_count


def register_maintenance_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def maintenance(self):
        self.update_state(state='STARTED')

        projects_maintenance(self)
        liveprojects_maintenance(self)

        project_descriptions_maintenance(self)

        students_data_maintenance(self)

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


    def students_data_maintenance(self):
        try:
            # to prevent this job growing unboundedly with the databse, restrict calculation
            # to current students and those who graduated up to last year,
            # or those without a currently calculated value
            records = db.session.query(StudentData) \
                .join(User, User.id == StudentData.id) \
                .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id) \
                .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
                .filter(User.active,
                        or_(StudentData.academic_year <= DegreeType.duration + 1,
                            StudentData.academic_year == None)).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(student_data_maintenance.s(p.id) for p in records)
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
    def student_data_maintenance(self, sid):
        try:
            record = db.session.query(StudentData).filter_by(id=sid).first()
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


    def _collect_expirable_assets(self, AssetType):
        try:
            # only filter out records that have a finite lifetime set
            records: List[AssetType] = \
                db.session.query(GeneratedAsset).filter(AssetType.expiry != None).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return records


    def _collect_all_assets(self, AssetType):
        try:
            # only filter out records that have a finite lifetime set
            records: List[AssetType] = \
                db.session.query(GeneratedAsset).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return records


    @celery.task(bind=True, default_retry_delay=30)
    def asset_garbage_collection(self):
        generated_records = _collect_expirable_assets(self, GeneratedAsset)
        temporary_records = _collect_expirable_assets(self, TemporaryAsset)
        submitted_records = _collect_expirable_assets(self, SubmittedAsset)

        tasks = [asset_check_expiry.s(r.id, GeneratedAsset, "OBJECT_STORAGE_ASSETS") for r in generated_records] \
                + [asset_check_expiry.s(r.id, TemporaryAsset, "OBJECT_STORAGE_ASSETS") for r in temporary_records] \
                + [asset_check_expiry.s(r.id, SubmittedAsset, "OBJECT_STORAGE_ASSETS") for r in submitted_records]

        raise self.replace(group(*tasks))


    @celery.task(bind=True, default_retry_delay=30)
    def asset_check_lost(self, notify_email):
        # previously we checked for lost assets at the same time as garbage collection, but in the context of
        # a cloud object store this generates a huge number of API calls for which we are billed! e.g., on
        # Google Cloud Storate this was the number of API calls was the single biggest contributor to the
        # storage bill in August 2023. We need to generate many fewer API calls by using them more intelligently.
        # At a minimum, this means that checking for lost assets should be done in a separate job that can be
        # scheduled much more infrequently.
        generated_records = _collect_all_assets(self, GeneratedAsset)
        temporary_records = _collect_all_assets(self, TemporaryAsset)
        submitted_records = _collect_all_assets(self, SubmittedAsset)

        tasks = [asset_check_lost.s(r.id, GeneratedAsset, "OBJECT_STORAGE_ASSETS") for r in generated_records] \
                + [asset_check_lost.s(r.id, TemporaryAsset, "OBJECT_STORAGE_ASSETS") for r in temporary_records] \
                + [asset_check_lost.s(r.id, SubmittedAsset, "OBJECT_STORAGE_ASSETS") for r in submitted_records]

        raise self.replace(group(*tasks) | process_lost_assets.s(notify_email))


    @celery.task(bind=True, default_retry_delay=30)
    def asset_check_attached(self, notify_email):
        submitted_records = _collect_all_assets(self, SubmittedAsset)

        tasks = [asset_check_attached.si(r.id, SubmittedAsset, "OBJECT_STORAGE_ASSETS") for r in submitted_records]

        raise self.replace(group(*tasks) | process_unattached_assets.s(notify_email))


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_expiry(self, id, RecordType, storage_key: str):
        try:
            record: RecordType = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        if record.expiry >= datetime.now():
            return None

        asset_name = record.target_name if record.target_name is not None else record.unique_name

        storage = AssetCloudAdapter(record, current_app.config.get(storage_key))
        storage.delete()

        try:
            db.session.delete(record)
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        print(f'** Garbage collection removed expired {type(RecordType)} object "{asset_name}" (id={record.id})')
        return asset_name


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_lost(self, id, RecordType, storage_key: str):
        try:
            record: RecordType = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        storage = AssetCloudAdapter(record, current_app.config.get(storage_key))

        # check if asset exists in the object store
        if storage.exists():
            return None

        asset_name = record.target_name if record.target_name is not None else record.unique_name

        print(f'** Detected lost {type(RecordType)} object "{asset_name}" (id={record.id})')
        return {'type': f'{type(RecordType)}',
                'id': record.id,
                'name': asset_name}


    @celery.task(bind=True, default_retry_delay=30)
    def process_lost_assets(self, lost_assets, notify_email):
        now = datetime.now()

        app_name = current_app.config.get('APP_NAME', 'mpsprojects')

        to_list = notify_email if isinstance(notify_email, Iterable) else [notify_email]

        stripped_assets = [x for x in lost_assets if isinstance(x, Mapping)]
        if len(stripped_assets) == 0:
            raise Ignore()

        msg = EmailMessage(subject='[{appname}] Lost assets report at '
                                   '{time}'.format(appname=app_name, time=now.strftime("%a %d %b %Y %H:%M:%S")),
                           from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                           reply_to=[current_app.config['MAIL_REPLY_TO']],
                           to=to_list)
        msg.body = render_template('email/maintenance/lost_assets.txt', assets=stripped_assets)

        task_id = register_task(msg.subject, description='Send lost assets report to {r}'.format(r=', '.join(to_list)))

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def process_unattached_assets(self, lost_assets, notify_email):
        now = datetime.now()

        app_name = current_app.config.get('APP_NAME', 'mpsprojects')

        to_list = notify_email if isinstance(notify_email, Iterable) else [notify_email]

        stripped_assets = [x for x in lost_assets if isinstance(x, Mapping)]
        if len(stripped_assets) == 0:
            raise Ignore()

        msg = EmailMessage(subject='[{appname}] Lost assets report at '
                                   '{time}'.format(appname=app_name, time=now.strftime("%a %d %b %Y %H:%M:%S")),
                           from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                           reply_to=[current_app.config['MAIL_REPLY_TO']],
                           to=to_list)
        msg.body = render_template('email/maintenance/unattached_assets.txt', assets=stripped_assets)

        task_id = register_task(msg.subject, description='Send unattached assets report to {r}'.format(r=', '.join(to_list)))

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30, serializer='pickle')
    def asset_check_attached(self, id, RecordType):
        try:
            record: RecordType = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        # check if attached
        attached = record.submission_attachment is not None \
                   or record.period_attachment is not None \
                   or get_count(db.session.query(SubmissionRecord).filter_by(report_id=id)) > 0
        if attached:
            return None

        asset_name = record.target_name if record.target_name is not None else record.unique_name

        print(f'** Detected unattached {type(RecordType)} object "{asset_name}" (id={record.id})')
        return {'type': f'{type(RecordType)}',
                'id': record.id,
                'name': asset_name}


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
