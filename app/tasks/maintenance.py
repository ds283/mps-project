#
# Created by David Seery on 2018-11-02.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, date, timedelta
from io import BytesIO
from pathlib import Path
from typing import List, Iterable, Mapping, Union

from celery import group
from celery import states
from celery.exceptions import Ignore
from flask import current_app, render_template
from flask_mailman import EmailMessage
from sqlalchemy import or_, and_
from sqlalchemy.exc import SQLAlchemyError

import app.shared.cloud_object_store.encryption_types as encryptions
from .. import register_task
from ..database import db
from ..models import (
    User,
    Project,
    LiveProject,
    AssessorAttendanceData,
    SubmitterAttendanceData,
    PresentationAssessment,
    GeneratedAsset,
    TemporaryAsset,
    ScheduleEnumeration,
    ProjectDescription,
    MatchingEnumeration,
    SubmittedAsset,
    SubmissionRecord,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    DegreeProgramme,
    DegreeType,
    BackupRecord,
    validate_nonce,
    SubmittingStudent,
    SelectingStudent,
    PopularityRecord,
)
from ..shared.asset_tools import AssetCloudAdapter, AssetCloudScratchContextManager, AssetUploadManager
from ..shared.cloud_object_store import ObjectStore
from ..shared.utils import get_current_year, get_count


def register_maintenance_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def maintenance(self):
        self.update_state(state=states.STARTED)

        print("database maintenance: performing maintenance for ProjectClass records")
        project_classes_maintenance(self)

        print("database maintenance: performing maintenance for Project records")
        projects_maintenance(self)
        print("database maintenance: performing maintenance for LiveProject records")
        liveprojects_maintenance(self)

        print("database maintenance: performing maintenance for ProjectDescription records")
        project_descriptions_maintenance(self)

        print("database maintenance: performing maintenance for StudentData records")
        students_data_maintenance(self)
        print("database maintenance: performing maintenance for SubmittingStudent records")
        submitting_student_maintenance(self)

        print("database maintenance: performing maintenance for AssessorAttendanceData records")
        assessor_attendance_maintenance(self)
        print("database maintenance: performing maintenance for SubmitterAttendanceData records")
        submitter_attendance_maintenance(self)

        print("database maintenance: performing maintenance for MatchingEnumeration records")
        matching_enumeration_maintenance(self)
        print("database maintenance: performing maintenance for ScheduleEnumeration records")
        schedule_enumeration_maintenance(self)

        print("database maintenance: performing maintenance for SubmissionRecord records")
        submission_record_maintenance(self)

        print("database maintenance: performing maintenance for PopularityRecord records")
        popularity_record_maintenance(self)

        self.update_state(state=states.SUCCESS)

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def fix_unencrypted_assets(self):
        self.update_state(state=states.STARTED)

        asset_maintenance(self, SubmittedAsset)
        asset_maintenance(self, TemporaryAsset)
        asset_maintenance(self, GeneratedAsset)

        backup_maintenance(self)

        self.update_state(state=states.SUCCESS)

    def popularity_record_maintenance(self):
        # remove any stale PopularityRecord instances (at least 1 day old) that did not get properly filled in
        now = datetime.now()
        cutoff = now - timedelta(days=1)

        try:
            db.session.query(PopularityRecord).filter(
                and_(
                    PopularityRecord.datestamp <= cutoff,
                    or_(
                        PopularityRecord.score_rank == None,
                        PopularityRecord.selections_rank == None,
                        PopularityRecord.bookmarks_rank == None,
                        PopularityRecord.views_rank == None,
                    ),
                )
            ).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    def submitting_student_maintenance(self):
        current_year = get_current_year()
        try:
            records = (
                db.session.query(SubmittingStudent)
                .filter(SubmittingStudent.retired == False)
                .join(ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id)
                .filter(ProjectClassConfig.live == True, ProjectClassConfig.selection_closed == False)
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(submitting_student_record_maintenance.s(r.id) for r in records)
        task.apply_async()

    def submitter_attendance_maintenance(self):
        current_year = get_current_year()
        try:
            records = (
                db.session.query(SubmitterAttendanceData)
                .join(PresentationAssessment, PresentationAssessment.id == SubmitterAttendanceData.assessment_id)
                .filter(PresentationAssessment.year == current_year)
                .all()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(submitter_attendance_record_maintenance.s(r.id) for r in records)
        task.apply_async()

    def assessor_attendance_maintenance(self):
        current_year = get_current_year()
        try:
            records = (
                db.session.query(AssessorAttendanceData)
                .join(PresentationAssessment, PresentationAssessment.id == AssessorAttendanceData.assessment_id)
                .filter(PresentationAssessment.year == current_year)
                .all()
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(assessor_attendance_record_maintenance.s(r.id) for r in records)
        task.apply_async()

    def project_classes_maintenance(self):
        try:
            records = db.session.query(ProjectClass).filter(ProjectClass.active, ProjectClass.publish).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(project_class_maintenance.s(p.id) for p in records)
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
            records = (
                db.session.query(StudentData)
                .join(User, User.id == StudentData.id)
                .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id)
                .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
                .filter(User.active, or_(StudentData.academic_year <= DegreeType.duration + 1, StudentData.academic_year == None))
                .all()
            )
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
            records: List[MatchingEnumeration] = db.session.query(MatchingEnumeration).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(matching_enumeration_record_maintenance.s(r.id) for r in records)
        task.apply_async()

    @celery.task(bind=True, default_retry_delay=30)
    def student_data_maintenance(self, sid):
        try:
            record: StudentData = db.session.query(StudentData).filter_by(id=sid).first()
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

        self.update_state(state=states.SUCCESS)

    @celery.task(bind=True, default_retry_delay=30)
    def submitting_student_record_maintenance(self, sid):
        try:
            record: SubmittingStudent = db.session.query(SubmittingStudent).filter_by(id=sid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        config: ProjectClassConfig = record.config

        if not config.select_in_previous_cycle:
            if record.selector is not None:
                existing_selector: SelectingStudent = record.selector

                if existing_selector.student_id != record.student_id:
                    current_app.logger.warning(
                        f'SubmittingStudent (id={record.id}) for student "{record.student.user.name}" has a paired SelectingStudent for a mismatching student "{existing_selector.student.user.name}"'
                    )
                    record.selector = None
                elif existing_selector.config_id != record.config_id:
                    current_app.logger.warning(
                        f'SubmittingStudent (id={record.id}) for student "{record.student.user.name}" has a paired selector for a mismatching ProjectClassConfig instance (submitter config_id={record.config_id}, selector config_id={existing_selector.config_id})'
                    )
                    record.selector = None

            # test whether there is a corresponding SelectingStudent instance
            paired_selector: SelectingStudent = (
                db.session.query(SelectingStudent)
                .filter(SelectingStudent.student_id == record.student_id, SelectingStudent.config_id == record.config_id)
                .first()
            )

            record.selector = paired_selector
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

            self.update_state(state=states.SUCCESS)

    @celery.task(bind=True, default_retry_delay=30)
    def project_class_maintenance(self, pid):
        try:
            pclass = db.session.query(ProjectClass).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if pclass is None:
            raise Ignore()

        if pclass.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

    def _collect_expirable_assets(self, AssetType):
        try:
            # only filter out records that have a finite lifetime set
            records: List[AssetType] = db.session.query(AssetType).filter(AssetType.expiry != None).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return records

    def _collect_all_assets(self, AssetType):
        try:
            # only filter out records that have a finite lifetime set
            records: List[AssetType] = db.session.query(AssetType).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return records

    @celery.task(bind=True, default_retry_delay=30)
    def asset_garbage_collection(self):
        generated_records = _collect_expirable_assets(self, GeneratedAsset)
        temporary_records = _collect_expirable_assets(self, TemporaryAsset)
        submitted_records = _collect_expirable_assets(self, SubmittedAsset)

        tasks = (
            [asset_test_expiry.s(r.id, GeneratedAsset, "OBJECT_STORAGE_ASSETS") for r in generated_records]
            + [asset_test_expiry.s(r.id, TemporaryAsset, "OBJECT_STORAGE_ASSETS") for r in temporary_records]
            + [asset_test_expiry.s(r.id, SubmittedAsset, "OBJECT_STORAGE_ASSETS") for r in submitted_records]
        )

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

        tasks = (
            [asset_test_lost.s(r.id, GeneratedAsset, "OBJECT_STORAGE_ASSETS") for r in generated_records]
            + [asset_test_lost.s(r.id, TemporaryAsset, "OBJECT_STORAGE_ASSETS") for r in temporary_records]
            + [asset_test_lost.s(r.id, SubmittedAsset, "OBJECT_STORAGE_ASSETS") for r in submitted_records]
        )

        raise self.replace(
            group(*tasks) | issue_asset_report.s("email/maintenance/lost_assets.txt", "[{app_name}] Lost asset report at {time}", notify_email)
        )

    @celery.task(bind=True, default_retry_delay=30)
    def asset_check_unattached(self, notify_email):
        submitted_records = _collect_all_assets(self, SubmittedAsset)

        tasks = [asset_test_attached.si(r.id, SubmittedAsset, "OBJECT_STORAGE_ASSETS") for r in submitted_records]

        raise self.replace(
            group(*tasks)
            | issue_asset_report.s("email/maintenance/unattached_assets.txt", "[{app_name}] Unattached asset report at {time}", notify_email)
        )

    @celery.task(bind=True, default_retry_delay=30, serializer="pickle")
    def asset_test_expiry(self, id, RecordType, storage_key: str):
        try:
            record: RecordType = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            return

        if record.expiry >= datetime.now():
            return

        if hasattr(record, "target_name"):
            asset_name = record.target_name if record.target_name is not None else record.unique_name
        else:
            asset_name = record.unique_name

        asset_type = RecordType.get_type()

        storage = AssetCloudAdapter(
            record, current_app.config.get(storage_key), audit_data=f'maintenance.asset_test_expiry (record type="{asset_type}", record id #{id})'
        )
        try:
            storage.delete()
        except FileNotFoundError:
            # silently ignore if cloud object cannot be found
            pass

        try:
            db.session.delete(record)
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        print(f'** Garbage collection removed expired {asset_type} object "{asset_name}" (id={record.id})')
        return asset_name

    @celery.task(bind=True, default_retry_delay=30, serializer="pickle")
    def asset_test_lost(self, id, RecordType, storage_key: str):
        try:
            record: RecordType = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            return

        if hasattr(record, "target_name"):
            asset_name = record.target_name if record.target_name is not None else record.unique_name
        else:
            asset_name = record.unique_name

        asset_type = RecordType.get_type()

        storage = AssetCloudAdapter(
            record, current_app.config.get(storage_key), audit_data=f'maintenance.asset_test_lost (record type="{asset_type}", record id #{id})'
        )

        # check if asset exists in the object store
        if storage.exists():
            return

        print(f'** Detected lost {asset_type} object "{asset_name}" (id={record.id})')
        return {"type": f"{asset_type}", "id": record.id, "name": asset_name}

    @celery.task(bind=True, default_retry_delay=30, serializer="pickle")
    def asset_test_attached(self, id, RecordType, storage_key: str):
        try:
            record: RecordType = db.session.query(RecordType).filter_by(id=id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        # check if attached
        attached = (
            record.submission_attachment is not None
            or record.period_attachment is not None
            or get_count(db.session.query(SubmissionRecord).filter_by(report_id=id)) > 0
        )
        if attached:
            return None

        asset_name = record.target_name if record.target_name is not None else record.unique_name
        asset_type = RecordType.get_type()

        print(f'** Detected unattached {asset_type} object "{asset_name}" (id={record.id})')
        return {"type": f"{asset_type}", "id": record.id, "name": asset_name}

    @celery.task(bind=True, default_retry_delay=30)
    def issue_asset_report(self, lost_assets, template: str, subject: str, notify_email: Union[str, List[str]]):
        now = datetime.now()
        now_human = now.strftime("%a %d %b %Y %H:%M:%S")

        app_name = current_app.config.get("APP_NAME", "mpsprojects")

        to_list = notify_email if isinstance(notify_email, Iterable) and not isinstance(notify_email, str) else [notify_email]

        stripped_assets = [x for x in lost_assets if isinstance(x, Mapping)]
        if len(stripped_assets) == 0:
            raise Ignore()

        msg = EmailMessage(
            subject=subject.format(app_name=app_name, time=now_human),
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=to_list,
        )
        msg.body = render_template(template, assets=stripped_assets, date=now)

        task_id = register_task(msg.subject, description="Send assets report to {r}".format(r=", ".join(to_list)))

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        self.update_state(state=states.SUCCESS)

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

        self.update_state(state=states.SUCCESS)

    def asset_maintenance(self, RecordType):
        try:
            records = db.session.query(RecordType).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(assetrecord_maintenance.s(r.id, RecordType) for r in records)
        task.apply_async()

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def assetrecord_maintenance(self, rec_id, RecordType):
        try:
            asset = db.session.query(RecordType).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if asset is None:
            raise Ignore()

        object_store: ObjectStore = current_app.config.get("OBJECT_STORAGE_ASSETS")
        asset_type = RecordType.get_type()

        # ensure object is encrypted, if storage supports that
        if object_store.encrypted and asset.encryption == encryptions.ENCRYPTION_NONE:
            storage: AssetCloudAdapter = AssetCloudAdapter(
                asset, object_store, audit_data=f'maintenance.assetrecord_maintenance #1 (record type="{asset_type}", record id #{id})'
            )

            try:
                # download asset and then re-upload, which will transparently encrypt the asset
                with storage.download_to_scratch() as mgr:
                    mgr: AssetCloudScratchContextManager

                    with open(mgr.path, "rb") as f:
                        with AssetUploadManager(
                            asset,
                            data=BytesIO(f.read()),
                            storage=object_store,
                            audit_data=f'maintenance.assetrecord_maintenance #2 (record type="{asset_type}", record id #{rec_id})',
                            length=asset.filesize,
                            mimetype=asset.mimetype if hasattr(asset, "mimetype") else None,
                            validate_nonce=validate_nonce,
                        ) as upload_mgr:
                            pass

                try:
                    db.session.commit()
                    storage.delete()
                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    raise self.retry()

            except FileNotFoundError:
                print(f"!! Was not able to perform maintenance on asset #{asset.id}, " f'key="{asset.unique_name}"')

    def backup_maintenance(self):
        try:
            records = db.session.query(BackupRecord).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(backuprecord_maintenance.s(r.id) for r in records)
        task.apply_async()

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def backuprecord_maintenance(self, rec_id):
        try:
            record: BackupRecord = db.session.query(BackupRecord).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            raise Ignore()

        object_store: ObjectStore = current_app.config.get("OBJECT_STORAGE_BACKUP")

        # ensure object is encrypted, if storage supports that
        if object_store.encrypted and record.encryption == encryptions.ENCRYPTION_NONE:
            storage: AssetCloudAdapter = AssetCloudAdapter(
                record, object_store, audit_data=f"maintenance.backuprecord_maintenance #1 (record if #{rec_id})", size_attr="archive_size"
            )

            old_key: Path = Path(record.unique_name)
            while old_key.suffix:
                old_key = old_key.with_suffix("")

            new_key = Path(str(old_key) + "-encrypted").with_suffix(".tar.gz")

            print(f"Old key after stripping = {old_key}")
            print(f"New key = {new_key}")

            try:
                with storage.download_to_scratch() as scratch_path:
                    scratch_path: AssetCloudScratchContextManager

                    with open(scratch_path.path, "rb") as f:
                        with AssetUploadManager(
                            record,
                            data=BytesIO(f.read()),
                            storage=object_store,
                            audit_data=f"maintenance.backuprecord_maintenance #2 (record id #{rec_id})",
                            key=str(new_key),
                            length=record.archive_size,
                            size_attr="archive_size",
                            mimetype="application/gzip",
                            validate_nonce=validate_nonce,
                        ) as upload_mgr:
                            pass

                try:
                    db.session.commit()
                    storage.delete()
                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    raise self.retry()

            except FileNotFoundError:
                print(f"!! Was not able to perform maintenance on backup record #{record.id}, " f'key="{record.unique_name}"')

        now = date.today()
        if record.locked and record.unlock_date is not None and now >= record.unlock_date:
            record.locked = False
            record.unlock_date = None

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()
