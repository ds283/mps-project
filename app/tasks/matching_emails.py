#
# Created by ds283$ on 08/06/2021$.
# Copyright (c) 2021$ University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283$ <$>
#

from distutils.util import strtobool
from datetime import datetime

from celery import group, chain
from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import MatchingAttempt, TaskRecord,  MatchingRecord, FacultyData
from ..task_queue import progress_update, register_task


def register_matching_email_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def publish_to_selectors(self, match_id, user_id, task_id):
        try:
            record = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise self.retry()

        progress_update(task_id, TaskRecord.RUNNING, 10, "Building list of student selectors...", autocommit=True)

        recipients = set()
        for mrec in record.records:
            recipients.add(mrec.selector_id)

        notify = celery.tasks['app.tasks.utilities.email_notification']

        task = chain(group(publish_email_to_selector.si(match_id, sel_id, not bool(record.selected)) for sel_id in recipients),
                     notify.s(user_id, '{n} email notification{pl} issued', 'info'),
                     publish_to_selectors_finalize.si(match_id, task_id))

        raise self.replace(task)


    @celery.task(bind=True)
    def publish_to_selectors_finalize(self, match_id, task_id):
        try:
            record = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise self.retry()

        progress_update(task_id, TaskRecord.SUCCESS, 100, "Notification emails to selectors complete", autocommit=False)

        # record timestamp for when emails were sent
        if record.selected:
            record.final_to_selectors = datetime.now()
        else:
            record.draft_to_selectors = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 0


    @celery.task(bind=True, default_retry_delay=30)
    def publish_email_to_selector(self, match_id, sel_id, is_draft):
        if isinstance(is_draft, str):
            is_draft = strtobool(is_draft)

        try:
            record: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            matches = db.session.query(MatchingRecord) \
                .filter_by(matching_id=match_id, selector_id=sel_id) \
                .order_by(MatchingRecord.submission_period).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise self.retry()

        if len(matches) == 0:
            self.update_state('FAILURE', meta='Could not load MatchingRecord record from database')
            raise self.retry()

        user = matches[0].selector.student.user
        config = matches[0].selector.config
        pclass = config.project_class

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = EmailMultiAlternatives(from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                                     reply_to=[current_app.config['MAIL_REPLY_TO']],
                                     to=[user.email])

        if is_draft:
            msg.subject ='Notification: Draft project allocation for "{name}" ' \
                         '{yra}-{yrb}'.format(name=config.name, yra=record.submit_year_a, yrb=record.submit_year_b)
            msg.body = render_template('email/matching/draft_notify_students.txt', user=user,
                                       config=config, pclass=pclass, attempt=record, matches=matches,
                                       number=len(matches))

            html = render_template('email/matching/draft_notify_students.html', user=user,
                                   config=config, pclass=pclass, attempt=record, matches=matches,
                                   number=len(matches))
            msg.attach_alternative(html, "text/html")

        else:
            msg.subject ='Notification: Final project allocation for "{name}" ' \
                         '{yra}-{yrb}'.format(name=config.name, yra=record.submit_year_a, yrb=record.submit_year_b)
            msg.body = render_template('email/matching/final_notify_students.txt', user=user,
                                       config=config, pclass=pclass, attempt=record, matches=matches,
                                       number=len(matches))

            html = render_template('email/matching/final_notify_students.html', user=user,
                                   config=config, pclass=pclass, attempt=record, matches=matches,
                                   number=len(matches))
            msg.attach_alternative(html, "text/html")

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send schedule email to {r}'.format(r=', '.join(msg.to)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1


    @celery.task(bind=True, default_retry_delay=30)
    def publish_to_supervisors(self, match_id, user_id, task_id):
        try:
            record = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise self.retry()

        progress_update(task_id, TaskRecord.RUNNING, 10, "Building list of project supervisors...", autocommit=True)

        recipients = set()
        for fac in record.supervisors:
            recipients.add(fac.id)

        notify = celery.tasks['app.tasks.utilities.email_notification']

        task = chain(group(publish_email_to_supervisor.si(match_id, fac_id, not bool(record.selected)) for fac_id in recipients),
                     notify.s(user_id, '{n} email notification{pl} issued', 'info'),
                     publish_to_supervisors_finalize.si(match_id, task_id))

        raise self.replace(task)


    @celery.task(bind=True)
    def publish_to_supervisors_finalize(self, match_id, task_id):
        try:
            record = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise self.retry()

        progress_update(task_id, TaskRecord.SUCCESS, 100, "Notification emails to faculty complete", autocommit=False)

        # record timestamp for when emails were sent
        if record.selected:
            record.final_to_supervisors = datetime.now()
        else:
            record.draft_to_supervisors = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 0


    @celery.task(bind=True, default_retry_delay=30)
    def publish_email_to_supervisor(self, match_id, fac_id, is_draft):
        if isinstance(is_draft, str):
            is_draft = strtobool(is_draft)

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=match_id).first()
            fac = db.session.query(FacultyData).filter_by(id=fac_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            raise self.retry()

        if fac is None:
            self.update_state('FAILURE', meta='Could not load FacultyData record from database')
            raise self.retry()

        user = fac.user
        matches = record.get_supervisor_records(fac.id).all()

        binned_matches = {}
        convenors = set()
        for match in matches:
            pclass_id = match.selector.config.pclass_id
            if pclass_id not in binned_matches:
                binned_matches[pclass_id] = []

            binned_matches[pclass_id].append(match)
            convenors.add(match.selector.config.project_class.convenor)

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = EmailMultiAlternatives(from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                                     reply_to=[current_app.config['MAIL_REPLY_TO']],
                                     to=[user.email])

        if is_draft:
            msg.subject ='Notification: Draft project allocation for ' \
                         '{yra}-{yrb}'.format(yra=record.submit_year_a, yrb=record.submit_year_b)

            # check whether we are notifying of an assignment, or that a faculty member is not needed for an
            # assignment
            if len(matches) > 0:
                msg.body = render_template('email/matching/draft_notify_faculty.txt', user=user, fac=fac,
                                           attempt=record, matches=binned_matches, convenors=convenors)

                html = render_template('email/matching/draft_notify_faculty.html', user=user, fac=fac,
                                       attempt=record, matches=binned_matches, convenors=convenors)
                msg.attach_alternative(html, "text/html")

            else:

                msg.body = render_template('email/matching/draft_unneeded_faculty.txt', user=user, fac=fac,
                                           attempt=record)

                html = render_template('email/matching/draft_unneeded_faculty.html', user=user, fac=fac,
                                       attempt=record)
                msg.attach_alternative(html, "text/html")

        else:
            msg.subject ='Notification: Final project allocation for ' \
                         '{yra}-{yrb}'.format(yra=record.submit_year_a, yrb=record.submit_year_b)

            # check whether we are notifying of an assignment, or that a faculty member is not needed for an
            # assignment
            if len(matches) > 0:
                msg.body = render_template('email/matching/final_notify_faculty.txt', user=user, fac=fac,
                                           attempt=record, matches=binned_matches, convenors=convenors)

                html = render_template('email/matching/final_notify_faculty.html', user=user, fac=fac,
                                       attempt=record, matches=binned_matches, convenors=convenors)
                msg.attach_alternative(html, "text/html")

            else:

                msg.body = render_template('email/matching/final_unneeded_faculty.txt', user=user, fac=fac,
                                           attempt=record)

                html = render_template('email/matching/final_unneeded_faculty.html', user=user, fac=fac,
                                       attempt=record)
                msg.attach_alternative(html, "text/html")

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send schedule email to {r}'.format(r=', '.join(msg.to)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1
