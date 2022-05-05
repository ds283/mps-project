#
# Created by ds283$ on 05/05/2022$.
# Copyright (c) 2022$ University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283$ <$>
#

from flask import current_app, flash

from sqlalchemy.exc import SQLAlchemyError

from celery import group
from celery.exceptions import Ignore

from ..database import db
from ..models import ProjectClass, ProjectClassConfig, SubmissionPeriodRecord, SubmissionRecord, SubmittingStudent, \
    CanvasStudent, StudentData, User

import requests
from nameparser import HumanName

def _URL_query(session, URL, **kwargs):
    response = session.get(URL, **kwargs)

    response_list = []
    finished = False

    while not finished:
        json = response.json()
        response_list = response_list + json

        links = response.links
        if 'next' in links:
            next_dict = links['next']
            if 'url' in next_dict:
                response = session.get(next_dict['url'])
            else:
                finished = True
        else:
            finished = True

    return response_list


def register_canvas_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def canvas_user_checkin(self):
        self.update_state(state='STARTED', meta='Initiating Canvas synchronization of user data')

        tasks = []

        try:
            pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

            for pcl in pclasses:
                pcl: ProjectClass
                config: ProjectClassConfig = pcl.most_recent_config
                print('** Checking Canvas integration for project class "{pcl}"'.format(pcl=pcl.name))

                if config is not None and config.canvas_enabled:
                    print('**   Canvas integration is enabled; scheduling user check-in for this project in the current cycle')
                    tasks.append(canvas_user_checkin_module.s(config.id))
                else:
                    print('**   Canvas integration is not enabled for this project class in the current cycle')

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='STARTED', meta='Spawning Canvas subtasks for synchronization of user data')

        c_tasks = group(*tasks)
        c_tasks.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_user_checkin_module(self, pid):
        self.update_state(state='STARTED', meta='Initiating Canvas checkin for synchronization of student submitters')

        try:
            config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(state='FAILED', meta='Could not read ProjectClassConfig from database')
            raise Ignore()

        # if canvas integration is not enabled, assume we can exit
        if not config.canvas_enabled:
            return

        print('** Querying Canvas API for student list on module for {pcl} '
              '(module id={mid})'.format(pcl=config.name, mid=config.canvas_id))

        # set up requests session; safe to assume config.canvas_login is not zero
        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer {token}'.format(token=config.canvas_login.canvas_API_token)})

        API_URL = "https://canvas.sussex.ac.uk/api/v1/courses/{course_id}/users".format(course_id=config.canvas_id)
        user_list = _URL_query(session, API_URL, params={'enrollment_type': 'student'})

        # now loop through recovered students, matching them to SubmittingStudent instances if possible
        print('** [{pcl}]: recovered {n} students from Canvas API'.format(pcl=config.name, n=len(user_list)))

        # initially, mark all students as missing, and get a list of all CanvasStudent records (if any)
        # that represent students present in the Canvas database, but not present as submitters in our
        # database
        for sub in config.submitting_students:
            sub.canvas_user_id = None
            sub.canvas_missing = True

        # get a list of CanvasStudent items to delete (to keep our list of missing students in sync)
        canvas_student_delete_list = [c.id for c in config.missing_canvas_students]

        # keep a list of CanvasStudent instances to add
        c_add_list = []

        for user in user_list:
            if 'email' in user:
                email = user['email']
                name = user['name']
                canvas_user_id = user['id']

                # try to find a submitting student with this email address
                match = config.submitting_students \
                    .join(StudentData, StudentData.id == SubmittingStudent.student_id) \
                    .join(User, User.id == StudentData.id) \
                    .filter(User.email == email).all()
                num = len(match)

                if num > 1:
                    msg = '** [{pcl}]: Found multiple matches for Canvas user with email address "{email}", ' \
                          'name={name}'.format(pcl=config.name, email=email, name=name)
                    print(msg)
                    current_app.logger.warning(msg)

                elif num == 0:
                    print('** [{pcl}]: Student "{name}" was not found in submitter '
                          'list'.format(pcl=config.name, name=name))

                    # the student isn't in our submitter list; check whether we already have a record of that
                    record = config.missing_canvas_students.filter_by(canvas_user_id=canvas_user_id).all()
                    num_record = len(record)

                    if num_record == 0:
                        # need to add a new record

                        # parse name to human-readable format with first name/last name
                        hn = HumanName(name)

                        # try to find match in our own user database
                        found_user = db.session.query(StudentData) \
                            .join(User, User.id == StudentData.id) \
                            .filter(User.email == email).first()

                        c_add_list.append(CanvasStudent(config_id=config.id,
                                                        student_id=found_user.id if found_user is not None else None,
                                                        email=email,
                                                        canvas_user_id=canvas_user_id,
                                                        first_name=hn.first,
                                                        last_name=hn.last))
                    elif num_record == 1:
                        # remove from list of CanvasStudent entries to delete
                        if record[0].id in canvas_student_delete_list:
                            canvas_student_delete_list.remove(record[0].id)

                    else:
                        msg = '** [{pcl}] Unexpected number of CanvasStudent record matches for user with ' \
                              'email address "{email}", name={name}'.format(pcl=config.name, email=email, name=name)
                        print(msg)
                        current_app.logger.warning(msg)

                elif num == 1:
                    print('** [{pcl}]: Student "{name}" was matched to a student in the '
                          'submitter list'.format(pcl=config.name, name=name))

                    sub: SubmittingStudent = match[0]
                    sub.canvas_missing = False
                    sub.canvas_user_id = canvas_user_id

                else:
                    msg = '** [{pcl}]Unexpected number of matches for Canvas user with email address "{email}", ' \
                          'name={name}'.format(pcl=config.name, email=email, name=name)
                    print(msg)
                    current_app.logger.warning(msg)

        try:
            # add new CanvasStudent instances
            for c in c_add_list:
                db.session.add(c)

            # remove unneeded instances
            for sid in canvas_student_delete_list:
                db.session.query(CanvasStudent).filter_by(id=sid).delete()

            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            msg = 'Could not synchronize submitter list with Canvas for project "{pname}" because of a database error'.format(pname=config.name)
            print(msg)
            current_app.logger.error(msg)

        self.update_state(state='FINISHED', meta='Finished successfully')


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_submission_checkin(self):
        self.update_state(state='STARTED', meta='Initiating Canvas synchronization of submission availability')

        tasks = []

        try:
            pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

            for pcl in pclasses:
                pcl: ProjectClass
                config: ProjectClassConfig = pcl.most_recent_config
                print('** Checking Canvas integration for project class "{pcl}"'.format(pcl=pcl.name))

                if config is not None and config.canvas_enabled:
                    period: SubmissionPeriodRecord = config.current_period
                    print('** Checking Canvas integration for submission period "{pd}"'.format(pd=period.display_name))

                    if not period.closed and period.canvas_enabled:
                        print('**   Canvas integration is enabled; scheduling submission check-in for this project in the current cycle')
                        tasks.append(canvas_submission_checkin_module.s(period.id))
                    else:
                        print('**  Canvas integration is not enabled for this submission period')
                else:
                    print('**   Canvas integration is not enabled for this project class in the current cycle')

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='STARTED', meta='Spawning Canvas subtasks for synchronization of submission availability')

        c_tasks = group(*tasks)
        c_tasks.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_submission_checkin_module(self, pid):
        self.update_state(state='STARTED', meta='Initiating Canvas checkin for synchronization of submission availability')

        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state(state='FAILED', meta='Could not read SubmissionPeriodRecord from database')
            raise Ignore()

        # if canvas integration is not enabled, assume we can exit
        if not period.canvas_enabled:
            return

        config: ProjectClassConfig = period.config

        print('** Querying Canvas API for submission list on module for {pcl} '
              '(module id={mid}, assigment id={aid})'.format(pcl=config.name, mid=config.canvas_id,
                                                             aid=period.canvas_id))

        # reset the Canvas submission availability flag
        for sub in period.submissions:
            sub: SubmissionRecord
            sub.canvas_submission_available = False

        # set up requests session; safe to assume config.canvas_login is not zero
        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer {token}'.format(token=config.canvas_login.canvas_API_token)})

        API_URL = "https://canvas.sussex.ac.uk/api/v1/courses/{course_id}/assignments/{assign_id}/submissions".format(course_id=config.canvas_id, assign_id=period.canvas_id)
        submission_list = _URL_query(session, API_URL)

        # now loop through submissions
        for sub in submission_list:
            if sub['workflow_state'] == 'submitted':
                canvas_id = sub['user_id']

                # find a submitting user with this user id
                student = config.submitting_students.filter_by(canvas_user_id=canvas_id).all()
                num_student = len(student)

                if num_student == 1:
                    record = student[0].records.filter_by(period_id=period.id).first()
                    sd = student[0].student

                    if record is not None:
                        print('** [{pcl}]: Student "{name}" with email address "{email}" has a Canvas submission available'.format(pcl=config.name, name=sd.user.name, email=sd.user.email))
                        record.canvas_submission_available = True
                    else:
                        print('** [{pcl}]: Submission record for student "{name}" with email address "{name}" is None'.format(pcl=config.name, name=sd.user.name, email=sd.user.email))

                elif num_student > 1:
                    msg =  '** [{pcl}]: Canvas user with userid {uid} matches multiple (N={n}) submitting student records'.format(pcl=config.name, uid=canvas_id, n=num_student)
                    print(msg)
                    current_app.logger.warning(msg)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            msg = 'Could not synchronize submission availability with Canvas for project "{pname}" because of a database error'.format(pname=config.name)
            print(msg)
            current_app.logger.error(msg)

        self.update_state(state='FINISHED', meta='Finished successfully')
