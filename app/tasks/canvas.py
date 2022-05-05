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
    CanvasStudent

import requests
from nameparser import HumanName


def register_canvas_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def canvas_user_checkin(self):
        self.update_state(state='STARTED', meta='Initiating Canvas pull')

        tasks = []

        try:
            pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

            for pcl in pclasses:
                pcl: ProjectClass
                config: ProjectClassConfig = pcl.most_recent_config
                print('** Checking Canvas integration for project class "{pcl}"'.format(pcl=pcl.name))

                if config is not None and config.canvas_enabled:
                    print('**   Canvas integration is enabled; scheduling use check-in for this project in the current cycle')
                    tasks.append(canvas_user_checkin_module.s(config.id))
                else:
                    print('**   Canvas integration is not enabled for this project class in the current cycle')

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='STARTED', meta='Spawning Canvas subtasks')

        c_tasks = group(*tasks)
        c_tasks.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_user_checkin_module(self, pid):
        self.update_state(state='STARTED', meta='Initiating Canvas checkin for student submitters')

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
              '(module id={mid}'.format(pcl=config.name, mid=config.canvas_id))

        # set up requests session; safe to assume config.canvas_login is not zero
        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer {token}'.format(token=config.canvas_login.canvas_API_token)})

        response = session.get(
            "https://canvas.sussex.ac.uk/api/v1/courses/{course_id}/users".format(course_id=config.canvas_id),
            params={'enrollment_type': 'student'})

        user_list = []
        finished = False

        while not finished:
            json = response.json()
            user_list = user_list + json

            links = response.links
            if 'next' in links:
                next_dict = links['next']
                if 'url' in next_dict:
                    response = session.get(next_dict['url'])
                else:
                    finished = True
            else:
                finished = True

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
                match = list(filter(lambda s: s.student.user.email == email, config.submitting_students))

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
                    record = list(filter(lambda s: s.canvas_user_id == canvas_user_id, config.missing_canvas_students))

                    num_record = len(record)
                    if num_record == 0:
                        # need to add a new record
                        hn = HumanName(name)
                        c_add_list.append(CanvasStudent(config_id=config.id,
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

            msg = 'Could not synchronize submitter list with Canvas for project "{pname}" because of a database error'
            print(msg)
            current_app.logger.error(msg)
