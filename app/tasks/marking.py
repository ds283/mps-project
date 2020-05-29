#
# Created by David Seery on 20/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template
from flask_mail import Message
from sqlalchemy.exc import SQLAlchemyError

from celery import group, chain
from celery.exceptions import Ignore

from ..database import db
from ..models import SubmissionPeriodRecord, SubmissionRecord, User, SubmittedAsset, ProjectClassConfig, \
    ProjectClass, FacultyData, SubmittingStudent, StudentData, PeriodAttachment

from ..task_queue import register_task

from pathlib import Path
from dateutil import parser


def register_marking_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def send_marking_emails(self, record_id, cc_convenor, max_attachment, test_email, deadline, convenor_id):
        try:
            record: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionPeriodRecord from database')
            raise Ignore()

        print('-- Send marking emails for project class "{proj}", submission period '
              '"{period}"'.format(proj=record.config.name, period=record.display_name))
        print('-- configuration: CC convenor = {cc}, max attachment '
              'total = {max} Mb'.format(cc=cc_convenor, max=max_attachment))
        if test_email is not None:
            print('-- working in test mode: emails being sent to sink={email}'.format(email=test_email))
        print('-- supplied deadline is {deadline}'.format(deadline=parser.parse(deadline).date()))

        email_group = group(dispatch_emails.s(s.id, cc_convenor, max_attachment, test_email, deadline)
                            for s in record.submissions) | notify_dispatch.s(convenor_id)

        raise self.replace(email_group)


    @celery.task(bind=True, default_retry_delay=5)
    def notify_dispatch(self, result_data, convenor_id):
        try:
            user = db.session.query(User).filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state('FAILURE', meta='Could not load User record from database')
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
                                    if 'supervisor' in result:
                                        supv_sent += result['supervisor']
                                    if 'marker' in result:
                                        mark_sent += result['marker']
                                else:
                                    raise RuntimeError('Expected individual group results to be dictionaries')
                        else:
                            raise RuntimeError('Expected record result data to be a list')
            else:
                raise RuntimeError('Expected group result data to be a list')

        supv_plural = 's'
        mark_plural = 's'
        if supv_sent == 1:
            supv_plural = ''
        if mark_sent == 1:
            mark_plural = ''

        user.post_message('Dispatched {supv} notification{supv_pl} to project supervisors, '
                          'and {mark} notification{mark_pl} to project '
                          'examiners.'.format(supv=supv_sent, supv_pl=supv_plural, mark=mark_sent,
                                              mark_pl=mark_plural),
                          'info', autocommit=True)


    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_emails(self, record_id, cc_convenor, max_attachment, test_email, deadline):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionRecord from database')
            raise Ignore()

        # nothing to do if either (1) no project assigned, or (2) no report yet uploaded
        if record.project is None or record.report is None:
            return

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']

        asset: SubmittedAsset = record.report
        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class
        supervisor: FacultyData = record.project.owner
        marker: FacultyData = record.marker
        submitter: SubmittingStudent = record.owner
        student: StudentData = submitter.student

        filename_path: Path = Path(asset.filename)
        extension: str = filename_path.suffix.lower()

        tasks = []

        deadline = parser.parse(deadline).date()

        # check whether we need to email the supervisor
        if not record.email_to_supervisor and supervisor is not None:
            print('-- preparing email to supervisor')

            filename: Path = \
                Path('{year}_{abbv}_{last}{first}_candidate_{number}'.format(year=config.year, abbv=pclass.abbreviation,
                                                                             last=student.user.last_name,
                                                                             first=student.user.first_name,
                                                                             number=student.exam_number)) \
                    .with_suffix(extension)
            print('-- attachment filename = "{path}"'.format(path=str(filename)))

            msg = Message(subject='IMPORTANT: {abbv} project marking: {stu}'.format(abbv=pclass.abbreviation,
                                                                                    stu=student.user.name),
                          sender=current_app.config['MAIL_DEFAULT_SENDER'],
                          reply_to=pclass.convenor_email,
                          recipients=[test_email if test_email is not None else supervisor.user.email])

            if cc_convenor:
                msg.cc([config.convenor_email])

            attached_documents = _attach_documents(msg, record, filename, max_attachment, role='supervisor')

            msg.body = render_template('email/marking/supervisor.txt', config=config, pclass=pclass,
                                       period=period, marker=marker, supervisor=supervisor, submitter=submitter,
                                       project=record.project, student=student, record=record,
                                       deadline=deadline, attached_documents=attached_documents)

            # register a new task in the database
            task_id = register_task(msg.subject,
                                    description='Send supervisor marking request to '
                                                '{r}'.format(r=', '.join(msg.recipients)))

            # set up a task to email the supervisor
            taskchain = send_log_email.s(task_id, msg) | mark_supervisor_sent.s(record_id, test_email is None)
            tasks.append(taskchain)

        if not record.email_to_marker and marker is not None:
            print('-- preparing email to marker')

            filename: Path = \
                Path('{year}_{abbv}_candidate_{number}'.format(year=config.year, abbv=pclass.abbreviation,
                                                               number=student.exam_number)).with_suffix(extension)
            print('-- attachment filename = "{path}"'.format(path=str(filename)))

            msg = Message(subject='IMPORTANT: {abbv} project marking: '
                                  'candidate {number}'.format(abbv=pclass.abbreviation, number=student.exam_number),
                          sender=current_app.config['MAIL_DEFAULT_SENDER'],
                          reply_to=pclass.convenor_email,
                          recipients=[test_email if test_email is not None else marker.user.email])

            if cc_convenor:
                msg.cc([config.convenor_email])

            attached_documents = _attach_documents(msg, record, filename, max_attachment, role='marker')

            msg.body = render_template('email/marking/marker.txt', config=config, pclass=pclass,
                                       period=period, marker=marker, supervisor=supervisor, submitter=submitter,
                                       project=record.project, student=student, record=record,
                                       deadline=deadline, attached_documents=attached_documents)

            # register a new task in the database
            task_id = register_task(msg.subject,
                                    description='Send examiner marking request to '
                                                '{r}'.format(r=', '.join(msg.recipients)))

            taskchain = send_log_email.s(task_id, msg) | mark_marker_sent.s(record_id, test_email is None)
            tasks.append(taskchain)

        if len(tasks) > 0:
            return self.replace(group(tasks))

        return None


    def _attach_documents(msg: Message, record: SubmissionRecord, report_filename: Path, max_attachment: int,
                          role=None):
        # track cumulative size of added assets, packed on a 'first-come, first-served' system
        attached_size = 0

        # track attached documents
        attached_documents = []

        # extract location of report from SubmissionRecord; we can rely on record.report not being None
        report_asset: SubmittedAsset = record.report
        if report_asset is None:
            raise RuntimeError('_attach_documents() called with a null report')

        asset_folder: Path = Path(current_app.config.get('ASSETS_FOLDER'))
        submitted_subfolder: Path = Path(current_app.config.get('ASSETS_SUBMITTED_SUBFOLDER'))

        # attach report or generate link for download later
        report_abs_path = asset_folder / submitted_subfolder / report_asset.filename
        attached_size = _attach_asset(msg, report_asset, attached_size, attached_documents, report_abs_path,
                                      filename=report_filename, max_attachment=max_attachment,
                                      description="student's submitted report")

        # attach any other documents provided by the project convenor
        if role is not None:
            for attachment in record.period.attachments:
                attachment: PeriodAttachment

                if (role in ['marker'] and attachment.include_marker_emails) or \
                    (role in ['supervisor'] and attachment.include_supervisor_emails):
                    asset: SubmittedAsset = attachment.attachment

                    # TODO: consider rationalizing how filenames work with assets. Currently it's a bit inconsistent.
                    attachment_abs_path = asset_folder / submitted_subfolder / asset.filename
                    attached_size = _attach_asset(msg, asset, attached_size, attached_documents, attachment_abs_path,
                                                  max_attachment=max_attachment,
                                                  description=attachment.description)

        return attached_documents


    def _attach_asset(msg: Message, asset: SubmittedAsset, current_size: int, attached_documents,
                      asset_abs_path: Path, filename=None, max_attachment=None, description=None):
        if not asset_abs_path.exists():
            raise RuntimeError('_attach_documents() could not find asset at absolute path '
                               '"{path}"'.format(path=asset_abs_path))
        if not asset_abs_path.is_file():
            raise RuntimeError('_attach_documents() detected that asset at absolute path '
                               '"{path}" is not an ordinary file'.format(path=asset_abs_path))

        # get size of file to be attached, in bytes
        asset_size = asset_abs_path.stat().st_size

        # if attachment is too large, generate a link instead
        if max_attachment is not None \
                and float(current_size + asset_size)/(1024*1024) > max_attachment:
            link = 'https://mpsprojects.co.uk/admin/download_submitted_asset/{asset_id}'.format(asset_id=asset.id)
            attached_documents.append((False, link, description))

        # otherwise, perform the attachment
        else:
            attached_name = str(filename) if filename is not None else \
                str(asset.target_name) if asset.target_name is not None else \
                    str(asset.filename)

            with asset_abs_path.open(mode='rb') as f:
                msg.attach(filename=attached_name, content_type=asset.mimetype, data=f.read())

            attached_documents.append((True, attached_name, description))

            current_size += asset_size

        return current_size


    @celery.task(bind=True, default_retry_delay=30)
    def mark_supervisor_sent(self, result_data, record_id, test):
        # result_data is forwarded from previous task in the chain, and is not used in the current implementation

        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionRecord from database')
            raise Ignore()

        if not test and not record.email_to_supervisor:
            record.email_to_supervisor = True

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        return {'supervisor': 1}


    @celery.task(bind=True, default_retry_delay=30)
    def mark_marker_sent(self, result_data, record_id, test):
        # result_data is forwarded from previous task in the chain, and is not used in the current implementation

        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionRecord from database')
            raise Ignore()

        if not test and not record.email_to_marker:
            record.email_to_marker = True

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        return {'marker': 1}
