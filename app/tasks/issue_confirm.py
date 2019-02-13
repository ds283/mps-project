#
# Created by David Seery on 2019-01-20.
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

from ..database import db
from ..models import User, TaskRecord, BackupRecord, ProjectClassConfig, FacultyData, EnrollmentRecord

from ..task_queue import progress_update, register_task

from celery import chain, group
from celery.exceptions import Ignore

from datetime import datetime


def register_issue_confirm_tasks(celery):

    @celery.task(bind=True, serializer='pickle', default_retry_delay=30)
    def pclass_issue(self, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to issue confirmation requests...', autocommit=True)

        # get database records for this project class
        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None or convenor is None:
            if convenor is not None:
                convenor.post_message('Issuing confirmation requests failed because some database records '
                                      'could not be loaded.', 'danger', autocommit=True)

            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')

            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            return issue_fail.apply_async(args=(task_id, convenor_id))

        if not config.project_class.publish:
            return None

        year = config.year

        if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED:
            convenor.post_message('Confirmation requests for {name} {yra}-{yrb} '
                                  'have already been issued.'.format(name=config.name, yra=year, yrb=year + 1),
                                  'warning', autocommit=True)
            self.update_state('FAILURE', meta='Confirmation requests have not been issued')
            return issue_fail.apply_async(args=(task_id, convenor_id))

        config.confirmation_required = []
        faculty = set()

        # issue confirmation requests if this project is set up to require them
        if not config.require_confirm:
            return None

        # select faculty that are enrolled on this particular project class
        eq = db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id) \
            .filter_by(pclass_id=config.pclass_id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED).subquery()

        fd = db.session.query(eq.c.owner_id, User, FacultyData) \
            .join(User, User.id == eq.c.owner_id) \
            .join(FacultyData, FacultyData.id == eq.c.owner_id) \
            .filter(User.active == True)

        for id, user, data in fd:
            if data.id not in faculty:
                faculty.add(data.id)

        issue_group = group(issue_confirm.si(d, config_id) for d in faculty if d is not None)

        # get backup task from celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(issue_initialize.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_ISSUE_CONFIRM_FALLBACK, tag='issue_confirm',
                              description='Rollback snapshot for issuing confirmation requests for '
                                          '{proj} confirmations {yr}'.format(proj=config.name, yr=year)),
                    issue_group,
                    issue_update_db.s(task_id, config_id, convenor_id, deadline),
                    issue_notifications.s(task_id, config_id, convenor_id),
                    issue_finalize.si(task_id, config_id, convenor_id)).on_error(issue_fail.si(task_id, convenor_id))

        seq.apply_async()


    @celery.task()
    def issue_initialize(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building rollback confirmation requests snapshot...', autocommit=True)


    @celery.task(bind=True, serializer='pickle', default_retry_delay=30)
    def issue_update_db(self, notify_list, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.RUNNING, 80, 'Updating database records...', autocommit=False)

        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        config.requests_issued = True
        config.request_deadline = deadline
        config.requests_issued_id = convenor_id
        config.requests_timestamp = datetime.now()

        db.session.commit()

        return notify_list


    @celery.task(bind=True, default_retry_delay=30)
    def issue_notifications(self, notify_list, task_id, config_id, convenor_id):
        progress_update(task_id, TaskRecord.RUNNING, 90, 'Sending email notifications...', autocommit=True)

        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        notify = celery.tasks['app.tasks.utilities.email_notification']

        task = chain(group(send_notification_email.si(d, config_id) for d in notify_list if d is not None),
                     notify.s(convenor_id, '{n} confirmation request{pl} issued', 'info'))
        task.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def issue_finalize(self, task_id, config_id, convenor_id):
        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Issue confirmation requests complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is not None:
            # send direct message to user announcing successful Go Live event
            convenor.post_message('Issuing confirmation requests for "{proj}" '
                                  'for {yra}-{yrb} is now complete'.format(proj=config.name,
                                                                           yra=config.year,
                                                                           yrb=config.year+1),
                                  'success', autocommit=False)

        db.session.commit()


    @celery.task(bind=True, default_retry_delay=30)
    def issue_fail(self, task_id, convenor_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error when issuing confirmation requests', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if convenor is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        convenor.post_message('Issuing confirmation requests failed. Please contact a system administrator', 'error',
                              autocommit=False)
        db.session.commit()


    @celery.task(bind=True, default_retry_delay=30)
    def issue_confirm(self, faculty_id, config_id):
        try:
            data = FacultyData.query.filter_by(id=faculty_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if data is None or config is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        if data in config.confirmation_required:
            return None

        try:
            config.confirmation_required.append(data)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise self.retry()

        return faculty_id


    @celery.task(bind=True, default_retry_delay=30)
    def send_notification_email(self, faculty_id, config_id):
        try:
            data = FacultyData.query.filter_by(id=faculty_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if data is None or config is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = Message(subject='Please check projects for {name}'.format(name=config.project_class.name),
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[data.user.email])

        projects = data.projects_offered(config.project_class)

        msg.body = render_template('email/project_confirmation/confirmation_requested.txt', user=data.user,
                                   pclass=config.project_class, config=config,
                                   number_projects=len(projects), projects=projects)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send confirmation request email to {r}'.format(r=', '.join(msg.recipients)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1


    @celery.task(bind=True, default_retry_delay=30)
    def reminder_email(self, config_id, convenor_id):
        try:
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if config is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        recipients = set()

        for faculty in config.confirmation_required:
            recipients.add(faculty.id)

        notify = celery.tasks['app.tasks.utilities.email_notification']

        tasks = chain(group(send_reminder_email.si(r, config_id) for r in recipients if r is not None),
                      notify.s(convenor_id, '{n} reminder email{pl} issued', 'info'))
        tasks.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def send_reminder_email(self, faculty_id, config_id):
        try:
            data = FacultyData.query.filter_by(id=faculty_id).first()
            config = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if data is None or config is None:
            self.update_state('FAILURE', meta='Could not load database records')
            raise Ignore()

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = Message(subject='Reminder: please check projects for {name}'.format(name=config.project_class.name),
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[data.user.email])

        projects = data.projects_offered(config.project_class)

        msg.body = render_template('email/project_confirmation/confirmation_reminder.txt', user=data.user,
                                   pclass=config.project_class, config=config,
                                   number_projects=len(projects), projects=projects)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send confirmation reminder email to {r}'.format(r=', '.join(msg.recipients)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1
