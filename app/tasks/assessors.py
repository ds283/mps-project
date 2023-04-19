#
# Created by David Seery on 2018-11-29.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from sqlalchemy.exc import SQLAlchemyError

from celery.exceptions import Ignore

from ..database import db
from ..models import User, ProjectClassConfig, EnrollmentRecord, Project, LiveProject
from ..shared.sqlalchemy import get_count


def register_assessor_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def projects(self, enroll_id, pclass_id, user_id):
        self.update_state(state='STARTED', meta={'msg': 'Looking for database records'})

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=enroll_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load EnrollmentRecord record from database'})
            raise Ignore()

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load User record from database'})
            raise Ignore()

        faculty = record.owner

        if record.marker_state != EnrollmentRecord.MARKER_ENROLLED \
                and record.presentations_state != EnrollmentRecord.PRESENTATIONS_ENROLLED:
            user.post_message('Cannot attach {name} as an assessor for projects in class "{pclass}" because they '
                              'do not have an appropriate enrolment.'.format(name=faculty.user.name,
                                                                             pclass=record.pclass.name), 'error',
                              autocommit=True)
            raise Ignore()

        projects = db.session.query(Project).filter(Project.project_classes.any(id=pclass_id)).all()

        count = 0
        for p in projects:
            if get_count(p.assessors.filter_by(id=faculty.id)) == 0:
                p.assessors.append(faculty)
                count += 1

        if count > 0:
            user.post_message('Attached {name} as an assessor for {n} library projects.'.format(name=faculty.user.name,
                                                                                                n=count), 'info')
        else:
            user.post_message('{name} has already been attached as an assessor to all library projects in this '
                              'class.'.format(name=faculty.user.name), 'info')

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def live_projects(self, enroll_id, pclass_id, current_year, user_id):
        self.update_state(state='STARTED', meta={'msg': 'Looking for database records'})

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=enroll_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load EnrollmentRecord record from database'})
            raise Ignore()

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load User record from database'})
            raise Ignore()

        faculty = record.owner

        if record.marker_state != EnrollmentRecord.MARKER_ENROLLED \
                and record.presentations_state != EnrollmentRecord.PRESENTATIONS_ENROLLED:
            user.post_message('Cannot attach {name} as an assessor for projects in class "{pclass}" because they '
                              'do not have an appropriate enrolment.'.format(name=faculty.user.name,
                                                                             pclass=record.pclass.name), 'error',
                              autocommit=True)
            raise Ignore()

        projects = db.session.query(LiveProject) \
            .join(ProjectClassConfig, ProjectClassConfig.id == LiveProject.config_id) \
            .filter(ProjectClassConfig.year == current_year - 1,
                    ProjectClassConfig.pclass_id == pclass_id).all()

        count = 0
        for p in projects:
            if get_count(p.assessors.filter_by(id=faculty.id)) == 0:
                p.assessors.append(faculty)
                count += 1

        if count > 0:
            user.post_message('Attached {name} as an assessor for {n} live projects.'.format(name=faculty.user.name,
                                                                                             n=count), 'info')
        else:
            user.post_message('{name} has already been attached as an assessor to all live projects in this '
                              'class.'.format(name=faculty.user.name), 'info')

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
