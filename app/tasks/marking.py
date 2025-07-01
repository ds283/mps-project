#
# Created by David Seery on 20/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import date, datetime
from pathlib import Path
from typing import List, Union, Optional
from urllib.parse import quote

from celery import group, chain
from celery.exceptions import Ignore
from dateutil import parser
from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives, EmailMessage
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    SubmissionPeriodRecord,
    SubmissionRecord,
    User,
    SubmittedAsset,
    ProjectClassConfig,
    ProjectClass,
    SubmittingStudent,
    StudentData,
    PeriodAttachment,
    SubmissionAttachment,
    GeneratedAsset,
    SubmissionRole,
)
from ..shared.asset_tools import AssetCloudAdapter
from ..task_queue import register_task


def report_error(msg: str, source: str, user: Optional[User]):
    print(f"!! {source}: {msg}")
    if user is not None:
        user.post_message(msg, "error", autocommit=True)


def report_info(msg: str, source: str, user: Optional[User]):
    print(f">> {source}: {msg}")
    if user is not None:
        user.post_message(msg, "info", autocommit=True)


def register_marking_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def send_marking_emails(self, record_id, cc_convenor, max_attachment, test_email, deadline, convenor_id):
        try:
            record: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmissionPeriodRecord from database"})
            raise Ignore()

        print(
            '-- Send marking emails for project class "{proj}", submission period '
            '"{period}"'.format(proj=record.config.name, period=record.display_name)
        )
        print("-- configuration: CC convenor = {cc}, max attachment total = {max} Mb".format(cc=cc_convenor, max=max_attachment))

        if test_email is not None:
            print("-- working in test mode: emails being sent to sink={email}".format(email=test_email))

        print("-- supplied deadline is {deadline}".format(deadline=parser.parse(deadline).date()))

        email_group = group(
            dispatch_emails.s(s.id, cc_convenor, max_attachment, test_email, deadline) for s in record.submissions
        ) | notify_dispatch.s(convenor_id)

        raise self.replace(email_group)

    @celery.task(bind=True, default_retry_delay=5)
    def notify_dispatch(self, result_data, convenor_id):
        try:
            user = db.session.query(User).filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state("FAILURE", meta={"msg": "Could not load User record from database"})
            raise Ignore()

        # result data should be a list of lists
        supv_sent = 0
        mark_sent = 0

        if result_data is not None:
            if isinstance(result_data, list):
                for group_result in result_data:
                    if group_result is not None:
                        if isinstance(group_result, list):
                            for result in group_result:
                                if isinstance(result, dict):
                                    if "supervisor" in result:
                                        supv_sent += result["supervisor"]
                                    if "marker" in result:
                                        mark_sent += result["marker"]
                                else:
                                    raise RuntimeError("Expected individual group results to be dictionaries")
                        else:
                            raise RuntimeError("Expected record result data to be a list")
            else:
                raise RuntimeError("Expected group result data to be a list")

        supv_plural = "s"
        mark_plural = "s"
        if supv_sent == 1:
            supv_plural = ""
        if mark_sent == 1:
            mark_plural = ""

        report_info(
            f"Dispatched {supv_sent} notification{supv_plural} to project supervisors, and {mark_sent} notification{mark_plural} to examiners",
            "notify_dispatch",
            user,
        )

    def _build_supervisor_email(
        role: SubmissionRole,
        record: SubmissionRecord,
        config: ProjectClassConfig,
        pclass: ProjectClass,
        submitter: SubmittingStudent,
        student: StudentData,
        period: SubmissionPeriodRecord,
        asset: GeneratedAsset,
        deadline: date,
        supervisors: List[SubmissionRole],
        markers: List[SubmissionRole],
        test_email: str,
        cc_convenor: bool,
        max_attachment: int,
    ) -> EmailMultiAlternatives:
        if hasattr(asset, "filename"):
            filename_path: Path = Path(asset.filename)
        else:
            filename_path: Path = Path(asset.target_name)

        extension: str = filename_path.suffix.lower()
        user: User = role.user

        print('-- preparing email to supervisor "{name}" for submitter ' '"{sub_name}"'.format(name=user.name, sub_name=student.user.name))

        filename: Path = Path(
            "{year}_{abbv}_candidate_{number}".format(year=config.year, abbv=pclass.abbreviation, number=student.exam_number)
        ).with_suffix(extension)
        print('-- attachment filename = "{path}"'.format(path=str(filename)))

        subject = "IMPORTANT: {abbv} project marking: {stu} - DEADLINE {deadline} - DO NOT REPLY".format(
            abbv=pclass.abbreviation, stu=student.user.name, deadline=deadline.strftime("%a %d %b")
        )

        msg = EmailMultiAlternatives(
            subject=subject,
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[pclass.convenor_email],
            to=[test_email if test_email is not None else user.email],
        )

        if cc_convenor:
            msg.cc = [config.convenor_email]

        attached_documents = _attach_documents(msg, record, filename, max_attachment, role="supervisor")

        msg.body = render_template(
            "email/marking/supervisor.txt",
            role=role,
            config=config,
            pclass=pclass,
            period=period,
            markers=markers,
            supervisors=supervisors,
            submitter=submitter,
            project=record.project,
            student=student,
            record=record,
            deadline=deadline,
            attached_documents=attached_documents,
        )

        html = render_template(
            "email/marking/supervisor.html",
            role=role,
            config=config,
            pclass=pclass,
            period=period,
            markers=markers,
            supervisors=supervisors,
            submitter=submitter,
            project=record.project,
            student=student,
            record=record,
            deadline=deadline,
            attached_documents=attached_documents,
        )
        msg.attach_alternative(html, "text/html")

        return msg

    def _build_marker_email(
        role: SubmissionRole,
        record: SubmissionRecord,
        config: ProjectClassConfig,
        pclass: ProjectClass,
        submitter: SubmittingStudent,
        student: StudentData,
        period: SubmissionPeriodRecord,
        asset: GeneratedAsset,
        deadline: date,
        supervisors: List[SubmissionRole],
        markers: List[SubmissionRole],
        test_email: str,
        cc_convenor: bool,
        max_attachment: int,
    ) -> EmailMultiAlternatives:
        if hasattr(asset, "filename"):
            filename_path: Path = Path(asset.filename)
        else:
            filename_path: Path = Path(asset.target_name)

        extension: str = filename_path.suffix.lower()
        user: User = role.user

        print('-- preparing email to marker "{name}" for submitter ' '"{sub_name}"'.format(name=user.name, sub_name=student.user.name))

        filename: Path = Path(
            "{year}_{abbv}_candidate_{number}".format(year=config.year, abbv=pclass.abbreviation, number=student.exam_number)
        ).with_suffix(extension)
        print('-- attachment filename = "{path}"'.format(path=str(filename)))

        subject = "IMPORTANT: {abbv} project marking: candidate {number} - DEADLINE {deadline} - DO NOT REPLY".format(
            abbv=pclass.abbreviation, number=student.exam_number, deadline=deadline.strftime("%a %d %b")
        )

        msg = EmailMultiAlternatives(
            subject=subject,
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[pclass.convenor_email],
            to=[test_email if test_email is not None else user.email],
        )

        if cc_convenor:
            msg.cc = [config.convenor_email]

        attached_documents = _attach_documents(msg, record, filename, max_attachment, role="marker")

        msg.body = render_template(
            "email/marking/marker.txt",
            role=role,
            config=config,
            pclass=pclass,
            period=period,
            markers=markers,
            supervisors=supervisors,
            submitter=submitter,
            project=record.project,
            student=student,
            record=record,
            deadline=deadline,
            attached_documents=attached_documents,
        )

        html = render_template(
            "email/marking/marker.html",
            role=role,
            config=config,
            pclass=pclass,
            period=period,
            markers=markers,
            supervisors=supervisors,
            submitter=submitter,
            project=record.project,
            student=student,
            record=record,
            deadline=deadline,
            attached_documents=attached_documents,
        )
        msg.attach_alternative(html, "text/html")

        return msg

    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_emails(self, record_id, cc_convenor, max_attachment, test_email, deadline):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmissionRecord from database"})
            raise Ignore()

        # nothing to do if either (1) no project assigned, or (2) no report yet uploaded, or
        # (3) processed report not yet generated; SubmissionRecord instances in this position will
        # need to have marking emails sent later
        if record.project is None or record.processed_report is None:
            return

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

        asset: GeneratedAsset = record.processed_report
        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class
        submitter: SubmittingStudent = record.owner
        student: StudentData = submitter.student

        supervisors: List[SubmissionRole] = record.supervisor_roles
        markers: List[SubmissionRole] = record.marker_roles

        tasks = []

        deadline: date = parser.parse(deadline).date()

        # check which supervisors need to be sent a marking notification, if any
        for role in supervisors:
            role: SubmissionRole
            if not role.marking_distributed:
                filtered_supervisors: List[SubmissionRole] = [x for x in supervisors if x.id != role.id]

                msg: EmailMultiAlternatives = _build_supervisor_email(
                    role,
                    record,
                    config,
                    pclass,
                    submitter,
                    student,
                    period,
                    asset,
                    deadline,
                    filtered_supervisors,
                    markers,
                    test_email,
                    cc_convenor,
                    max_attachment,
                )

                # register a new task in the database
                task_id = register_task(msg.subject, description="Send supervisor marking request to {r}".format(r=", ".join(msg.to)))

                # set up a task to email the supervisor
                taskchain = chain(send_log_email.si(task_id, msg), record_marking_email_sent.si(role.id, test_email is not None, "supervisor")).set(
                    serializer="pickle"
                )
                tasks.append(taskchain)

        # check which markers need to be sent a marking notification, if any
        for role in markers:
            role: SubmissionRole
            if not role.marking_distributed:
                filtered_markers: List[SubmissionRole] = [x for x in markers if x.id != role.id]

                msg: EmailMultiAlternatives = _build_marker_email(
                    role,
                    record,
                    config,
                    pclass,
                    submitter,
                    student,
                    period,
                    asset,
                    deadline,
                    supervisors,
                    filtered_markers,
                    test_email,
                    cc_convenor,
                    max_attachment,
                )

                # register a new task in the database
                task_id = register_task(msg.subject, description="Send examiner marking request to {r}".format(r=", ".join(msg.to)))

                taskchain = chain(send_log_email.si(task_id, msg), record_marking_email_sent.si(role.id, test_email is not None, "marker")).set(
                    serializer="pickle"
                )
                tasks.append(taskchain)

        if len(tasks) > 0:
            return self.replace(group(tasks).set(serializer="pickle"))

        return None

    def _attach_documents(msg: EmailMessage, record: SubmissionRecord, report_filename: Path, max_attached_size: int, role=None):
        # track cumulative size of added assets, packed on a 'first-come, first-served' system
        current_size = 0

        # track attached documents
        attached_documents = []

        # extract location of (processed) report from SubmissionRecord; we can rely on record.processed_report not being None
        report_asset: GeneratedAsset = record.processed_report
        if report_asset is None:
            raise RuntimeError("_attach_documents() called with a null processed report")

        # attach report or generate link for download later
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        report_storage = AssetCloudAdapter(report_asset, object_store, audit_data=f"marking._attach_documents #1 (submission record #{record.id})")
        current_size += _attach_asset(
            msg,
            report_storage,
            current_size,
            attached_documents,
            filename=report_filename,
            max_attached_size=max_attached_size,
            description="student's submitted report",
            endpoint="download_generated_asset",
        )

        # attach any other documents provided by the project convenor
        if role is not None:
            for attachment in record.period.ordered_attachments:
                attachment: PeriodAttachment

                if (role in ["marker"] and attachment.include_marker_emails) or (role in ["supervisor"] and attachment.include_supervisor_emails):
                    asset: SubmittedAsset = attachment.attachment
                    asset_storage = AssetCloudAdapter(
                        asset, object_store, audit_data=f"marking._attach_documents #2 (submission record #{record.id})"
                    )

                    current_size += _attach_asset(
                        msg,
                        asset_storage,
                        current_size,
                        attached_documents,
                        max_attached_size=max_attached_size,
                        description=attachment.description,
                        endpoint="download_submitted_asset",
                    )

            for attachment in record.ordered_attachments:
                attachment: SubmissionAttachment

                if (role in ["marker"] and attachment.include_marker_emails) or (role in ["supervisor"] and attachment.include_supervisor_emails):
                    asset: SubmittedAsset = attachment.attachment
                    asset_storage = AssetCloudAdapter(
                        asset, object_store, audit_data=f"marking._attach_documents #3 (submission record #{record.id})"
                    )

                    current_size += _attach_asset(
                        msg,
                        asset_storage,
                        current_size,
                        attached_documents,
                        max_attached_size=max_attached_size,
                        description=attachment.description,
                        endpoint="download_submitted_asset",
                    )

        return attached_documents

    def _attach_asset(
        msg: EmailMessage,
        storage: AssetCloudAdapter,
        current_size: int,
        attached_documents,
        filename=None,
        max_attached_size=None,
        description=None,
        endpoint="download_submitted_asset",
    ):
        if not storage.exists():
            raise RuntimeError("_attach_documents() could not find asset in object store")

        # get size of file to be attached, in bytes
        asset: Union[SubmittedAsset, GeneratedAsset] = storage.record()
        asset_size = asset.filesize

        # if attachment is too large, generate a link instead
        if max_attached_size is not None and float(current_size + asset_size) / (1024 * 1024) > max_attached_size:
            if filename is not None:
                try:
                    link = "https://mpsprojects.sussex.ac.uk/admin/{endpoint}/{asset_id}?filename={fnam}".format(
                        endpoint=endpoint, asset_id=asset.id, fnam=quote(filename)
                    )
                except TypeError as e:
                    link = "https://mpsprojects.sussex.ac.uk/admin/{endpoint}/{asset_id}".format(endpoint=endpoint, asset_id=asset.id)
                    print(f'_attach_asset: TypeError received with filename="{filename}"')
            else:
                link = "https://mpsprojects.sussex.ac.uk/admin/{endpoint}/{asset_id}".format(endpoint=endpoint, asset_id=asset.id)
            attached_documents.append((False, link, description))
            asset_size = 0

        # otherwise, perform the attachment
        else:
            attached_name = (
                str(filename) if filename is not None else str(asset.target_name) if asset.target_name is not None else str(asset.unique_name)
            )

            msg.attach(filename=attached_name, mimetype=asset.mimetype, content=storage.get())

            attached_documents.append((True, attached_name, description))

        return asset_size

    @celery.task(bind=True, default_retry_delay=30)
    def record_marking_email_sent(self, role_id, test, role_string):
        # result_data is forwarded from previous task in the chain, and is not used in the current implementation

        try:
            role: SubmissionRole = db.session.query(SubmissionRole).filter_by(id=role_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if role is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmissionRole from database"})
            raise Ignore()

        if not test and not role.marking_distributed:
            role.marking_distributed = True

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        return {role_string: 1}

    @celery.task(bind=True, default_retry_delay=30)
    def conflate_marks_for_period(self, period_id: int, convenor_id: Optional[int]):
        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmissionPeriodRecord from database"})
            raise Ignore()

        # set up a task group to perform conflation for each record associated with this period
        tasks = group(conflate_marks.s(record.id, convenor_id) for record in period.submissions) | notify_period_conflation.s(period.id, convenor_id)

        raise self.replace(tasks)

    def sanity_check_grade(role: SubmissionRole, person: User, student: User, convenor: Optional[User]):
        fail = False

        label: str = role._role_labels[role.role].capitalize()
        if role.grade < 0:
            fail = True
            report_error(
                f"{label} {person.name} for submitter {student.name} has recorded grade < 0. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )
        if role.grade > 100:
            fail = True
            report_error(
                f"{label} {person.name} for submitter {student.name} has recorded grade > 100. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )

        if role.weight is not None:
            if role.weight <= 0.0:
                fail = True
                report_error(
                    f"{label} {person.name} for submitter {student.name} has assigned weight < 0. This submitter has been ignored.",
                    "conflate_marks",
                    convenor,
                )
            if role.weight > 1.0:
                fail = True
                report_error(
                    f"{label} {person.name} for submitter {student.name} has assigned weight > 1. This submitter has been ignored.",
                    "conflate_marks",
                    convenor,
                )

        return fail

    @celery.task(bind=True, default_retry_delay=30)
    def conflate_marks(self, record_id: int, convenor_id: Optional[int]):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        convenor: Optional[User] = None
        if convenor_id is not None:
            try:
                convenor = db.session.query(User).filter_by(id=convenor_id).first()
            except SQLAlchemyError as e:
                convenor = None

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmissionRecord from database"})
            return {"not_conflated": 1}

        # TODO: allow adjustable conflation rules
        sub: SubmittingStudent = record.owner
        sd: StudentData = sub.student
        student: User = sd.user

        fail: bool = False

        # conflate supervisor marks
        supervisor_marks = []
        for role in record.supervisor_roles:
            person: User = role.user
            if role.role == SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR:
                if not role.signed_off:
                    fail = True
                    report_info(
                        f"Warning: responsible supervisor {person.name} for submitter {student.name} has not approved. This submitter has beem ignored.",
                        "conflate_marks",
                        convenor,
                    )

            if role.grade is not None:
                if role.signed_off:
                    fail = sanity_check_grade(role, person, student, convenor)
                    supervisor_marks.append({"grade": float(role.grade), "weight": float(role.weight) if role.weight is not None else 1.0})

                else:
                    report_info(
                        f"Warning: supervisor {person.name} for submitter {student.name} has a recorded grade, but it is not signed off. Marks for this student have been conflated, but this supervisor has been ignored.",
                        "conflate_marks",
                        convenor,
                    )
            else:
                if role.role != SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR:
                    report_info(
                        f"Warning: supervisor {person.name} for submitter {student.name} has not recorded a grade. Marks for this student have been conflated, but this supervisor has been ignored.",
                        "conflate_marks",
                        convenor,
                    )

        if fail:
            return {"not_conflated": 1}

        sum_weight = sum(m["weight"] for m in supervisor_marks)
        if not 1 - 1e-5 < sum_weight < 1 + 1e-5:
            report_error(
                f"Supervisor weights for submitter {student.name} do not sum to 1.0 (weight total={sum_weight:.3f}. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )
            return {"not_conflated": 1}

        # conflate examiner/markers
        marker_marks = []
        for role in record.marker_roles:
            person: User = role.user
            if role.grade is not None:
                if role.signed_off:
                    fail = sanity_check_grade(role, person, student, convenor)
                    marker_marks.append({"grade": float(role.grade), "weight": float(role.weight) if role.weight is not None else 1.0})

                else:
                    report_info(
                        f"Warning: marker {person.name} for submitter {student.name} has a recorded grade, but it is not signed off. Marks for this student have been conflated, but this marker has been ignored.",
                        "conflate_marks",
                        convenor,
                    )
            else:
                report_info(
                    f"Warning: marker {person.name} for submitter {student.name} has not recorded a grade. Marks for this student have been conflated, but this supervisor has been ignored.",
                    "conflate_marks",
                    convenor,
                )

        if fail:
            return {"not_conflated": 1}

        sum_weight = sum(m["weight"] for m in marker_marks)
        if not 1 - 1e-5 < sum_weight < 1 + 1e-5:
            report_error(
                f"Marker weights for submitter {student.name} do not sum to 1.0 (weight total={sum_weight:.3f}. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )
            return {"not_conflated": 1}

        # round up from 0.45%
        record.supervision_grade = round(sum(m["weight"] * m["grade"] for m in supervisor_marks) + 0.05, 0)
        record.report_grade = round(sum(m["weight"] * m["grade"] for m in marker_marks) + 0.05, 0)

        record.grade_generated_id = convenor_id
        record.grade_generated_timestamp = datetime.now()

        config: ProjectClassConfig = sub.config
        print(
            f'>> conflate_marks: {config.abbreviation} submitted "{student.name}" was assigned supervision grade={record.supervision_grade:.1f}%, report grade={record.report_grade:.1f}%'
        )

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {"conflated": 1}

    @celery.task(bind=True, default_retry_delay=5)
    def notify_period_conflation(self, result_data, period_id, convenor_id):
        try:
            convenor: Optional[User] = db.session.query(User).filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is None:
            self.update_state("FAILURE", meta={"msg": "Could not load convenor User record from database"})
            raise Ignore()

        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load period record from database"})
            raise Ignore()

        # result data should be a list of lists
        marks_conflated = 0
        marks_not_conflated = 0

        if result_data is not None:
            if isinstance(result_data, list):
                for result in result_data:
                    if isinstance(result, dict):
                        if "conflated" in result:
                            marks_conflated += result["conflated"]
                        if "not_conflated" in result:
                            marks_not_conflated += result["not_conflated"]
                    else:
                        raise RuntimeError("Expected individual results to be dictionaries")
            else:
                raise RuntimeError("Expected result data to be a list")

        conflated_plural = "s"
        not_conflated_plural = "s"
        if marks_conflated == 1:
            conflated_plural = ""
        if marks_not_conflated == 1:
            not_conflated_plural = ""

        report_info(
            f"{period.display_name}: {marks_conflated} submitters{conflated_plural} conflated successfully, and {marks_not_conflated} submitter{not_conflated_plural} not conflated",
            "notify_period_conflation",
            convenor,
        )
