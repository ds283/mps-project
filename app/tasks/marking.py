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
from ..models import SubmissionPeriodRecord, SubmissionRecord, User

from ..task_queue import register_task

from pathlib import Path


def register_marking_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def send_marking_emails(self, record_id, convenor_id):
        try:
            record = db.session.query(SubmissionPeriodRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionPeriodRecord from database')
            raise Ignore()

        email_group = group(dispatch_emails.s(s.id) for s in record.submissions) | notify_dispatch.s(convenor_id)

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
    def dispatch_emails(self, record_id):
        try:
            record = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
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

        asset_folder = Path(current_app.config.get('ASSETS_FOLDER'))
        submitted_subfolder = Path(current_app.config.get('ASSETS_SUBMITTED_SUBFOLDER'))
        periods_subfolder = Path(current_app.config.get('ASSETS_PERIODS_SUBFOLDER'))

        asset = record.report
        period = record.period
        config = period.config
        pclass = config.project_class
        supervisor = record.project.owner
        marker = record.marker
        submitter = record.owner
        student = submitter.student

        filename_path = Path(asset.filename)
        extension = filename_path.suffix.lower()

        supervisor_filename = \
            Path('{year}_{abbv}_{last}{first}'.format(year=config.year, abbv=pclass.abbreviation,
                                                      last=student.user.last_name,
                                                      first=student.user.first_name)).with_suffix(extension)
        marker_filename = \
            Path('{year}_{abbv}_candidate_{number}'.format(year=config.year, abbv=pclass.abbreviation,
                                                           number=student.exam_number)).with_suffix(extension)

        report_path = asset_folder / submitted_subfolder / asset.filename

        tasks = []

        if not record.email_to_supervisor and supervisor is not None:
            msg = Message(subject='IMPORTANT: {abbv} project marking: {stu}'.format(abbv=pclass.abbreviation,
                                                                                    stu=student.user.name),
                          sender=current_app.config['MAIL_DEFAULT_SENDER'],
                          reply_to=pclass.convenor_email,
                          recipients=[supervisor.user.email],
                          cc=[config.convenor_email])

            msg.body = render_template('email/marking/supervisor.txt', config=config, pclass=pclass,
                                       period=period, marker=marker, supervisor=supervisor, submitter=submitter,
                                       project=record.project, student=student, record=record,
                                       report_filename=str(supervisor_filename))

            _attach_document(msg, asset, asset_folder, record, report_path, periods_subfolder, supervisor_filename)

            # register a new task in the database
            task_id = register_task(msg.subject,
                                    description='Send supervisor marking request to '
                                                '{r}'.format(r=', '.join(msg.recipients)))

            taskchain = chain(send_log_email.s(task_id, msg), mark_supervisor_sent.s(record_id))
            tasks.append(taskchain)

        if not record.email_to_marker and marker is not None:
            msg = Message(subject='IMPORTANT: {abbv} project marking: '
                                  'candidate {number}'.format(abbv=pclass.abbreviation, number=student.exam_number),
                          sender=current_app.config['MAIL_DEFAULT_SENDER'],
                          reply_to=pclass.convenor_email,
                          recipients=[marker.user.email],
                          cc=[config.convenor_email])

            msg.body = render_template('email/marking/marker.txt', config=config, pclass=pclass,
                                       period=period, marker=marker, supervisor=supervisor, submitter=submitter,
                                       project=record.project, student=student, record=record,
                                       report_filename=str(marker_filename))

            _attach_document(msg, asset, asset_folder, record, report_path, periods_subfolder, marker_filename)

            # register a new task in the database
            task_id = register_task(msg.subject,
                                    description='Send examiner marking request to '
                                                '{r}'.format(r=', '.join(msg.recipients)))

            taskchain = chain(send_log_email.s(task_id, msg), mark_marker_sent.s(record_id))
            tasks.append(taskchain)

        if len(tasks) > 0:
            return self.replace(group(tasks))

        return None


    def _attach_document(msg, asset, asset_folder, record, report_path, periods_subfolder, report_filename):
        # attach report
        with open(report_path, 'rb') as fd:
            msg.attach(filename=str(report_filename), content_type=asset.mimetype, data=fd.read())

        # attach other documents provided by project convenor
        for attachment in record.period.attachments:    # attachment: PeriodAttachment
            if attachment.include_marking_emails:
                asset_path = asset_folder / periods_subfolder / attachment.attachment.filename
                with open(asset_path, 'rb') as fd:
                    msg.attach(
                        filename=attachment.attachment.target_name
                        if attachment.attachment.target_name else attachment.attachment.filename,
                        content_type=attachment.attachment.mimetype, data=fd.read())


    @celery.task(bind=True, default_retry_delay=30)
    def mark_supervisor_sent(self, result_data, record_id):
        try:
            record = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionRecord from database')
            raise Ignore()

        if not record.email_to_supervisor:
            record.email_to_supervisor = True

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        return {'supervisor': 1}


    @celery.task(bind=True, default_retry_delay=30)
    def mark_marker_sent(self, result_data, record_id):
        try:
            record = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load SubmissionRecord from database')
            raise Ignore()

        if not record.email_to_marker:
            record.email_to_marker = True

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        return {'marker': 1}
