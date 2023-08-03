#
# Created by ds283$ on 05/05/2022$.
# Copyright (c) 2022$ University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283$ <$>
#

from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from celery import group, chain
from celery.exceptions import Ignore
from flask import current_app
from nameparser import HumanName
from sqlalchemy import or_, func
from sqlalchemy.exc import SQLAlchemyError
from url_normalize import url_normalize

from ..database import db
from ..models import ProjectClass, ProjectClassConfig, SubmissionPeriodRecord, SubmissionRecord, SubmittingStudent, \
    CanvasStudent, StudentData, User, SubmittedAsset, AssetLicense, MainConfig
from ..shared.asset_tools import AssetUploadManager, AssetCloudAdapter
from ..shared.utils import get_main_config


def _URL_query(session: requests.Session, URL, **kwargs):
    print('>> Querying API URL: {url}'.format(url=URL))

    response = session.get(URL, **kwargs)

    if not response:
        print('>> API returned NOT OK response: {msg}'.format(msg=response))
        return None

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
        self.update_state(state='STARTED', meta={'msg': 'Initiating Canvas synchronization of user data'})

        tasks = []

        try:
            pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

            for pcl in pclasses:
                pcl: ProjectClass
                config: ProjectClassConfig = pcl.most_recent_config
                print('** Checking Canvas integration for project class "{pcl}"'.format(pcl=pcl.name))

                API_root = config.main_config.canvas_root_API

                if API_root is None:
                    print('** Canvas API integration not enabled globally for cycle '
                          '{yra}-{yrb}'.format(yra=config.submit_year_a, yrb=config.submit_year_b))
                    break
                print('** API root URL is {root}'.format(root=API_root))

                if config is not None and config.canvas_enabled:
                    print('**   Canvas integration is enabled; scheduling user check-in for this project in the current cycle')
                    tasks.append(canvas_user_checkin_module.s(config.id, API_root))
                else:
                    print('**   Canvas integration is not enabled for this project class for cycle '
                          '{yra}-{yrb}'.format(yra=config.submit_year_a, yrb=config.submit_year_b))

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='STARTED', meta={'msg': 'Spawning Canvas subtasks for synchronization of user data'})

        c_tasks = group(*tasks)
        raise self.replace(c_tasks)


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_user_checkin_module(self, pid, API_root: str):
        self.update_state(state='STARTED', meta={'msg': 'Initiating Canvas checkin for synchronization of student submitters'})

        try:
            config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state(state='FAILED', meta={'msg': 'Could not read ProjectClassConfig from database'})
            raise Ignore()

        # if canvas integration is not enabled, assume we can exit
        if not config.canvas_enabled:
            return

        print('** Querying Canvas API for student list on module for {pcl} '
              '(module id={mid})'.format(pcl=config.name, mid=config.canvas_module_id))

        # set up requests session; safe to assume config.canvas_login is not zero
        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer {token}'.format(token=config.canvas_login.canvas_API_token)})

        API_URL = url_normalize(urljoin(API_root, "courses/{course_id}/users".format(course_id=config.canvas_module_id)))
        user_list = _URL_query(session, API_URL, params={'enrollment_type': 'student'})

        if user_list is None:
            print('** [{pcl}]: recovered no students from Canvas API'.format(pcl=config.name))
            return

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
                    .filter(or_(User.email == email,
                                func.concat(User.first_name, ' ', User.last_name) == name,
                                func.concat(func.left(User.first_name, 1), '.', User.last_name, '@sussex.ac.uk') == email)).all()
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

                    # sync candidate name if possible
                    if 'sortable_name' in user:
                        sortable_name = user['sortable_name']
                        exam_number_prefix = 'Candidate No :  '
                        if sortable_name.startswith(exam_number_prefix):
                            exam_number = sortable_name.removeprefix(exam_number_prefix)
                            sub.student.exam_number = int(exam_number)

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

        self.update_state(state='FINISHED', meta={'msg': 'Finished successfully'})


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_submission_checkin(self):
        self.update_state(state='STARTED', meta={'msg': 'Initiating Canvas synchronization of submission availability'})

        main_config: MainConfig = get_main_config()
        API_root = main_config.canvas_root_API

        if API_root is None:
            print('** Canvas API integration is not enabled; skipping')
            self.update_state(state='FINISHED', meta={'msg': 'Canvas API integration is not enabled; skipped'})
            return
        print('** API root URL is {root}'.format(root=API_root))

        tasks = []

        try:
            pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

            for pcl in pclasses:
                pcl: ProjectClass
                config: ProjectClassConfig = pcl.most_recent_config
                print('** Checking Canvas integration for project class "{pcl}"'.format(pcl=pcl.name))

                API_root = config.main_config.canvas_root_API

                if API_root is None:
                    print('** Canvas API integration not enabled globally for cycle '
                          '{yra}-{yrb}'.format(yra=config.submit_year_a, yrb=config.submit_year_b))
                    break
                print('** API root URL is {root}'.format(root=API_root))

                if config is not None and config.canvas_enabled:
                    period: SubmissionPeriodRecord = config.current_period
                    print('** Checking Canvas integration for submission period "{pd}"'.format(pd=period.display_name))

                    if not period.closed and period.canvas_enabled:
                        print('**   Canvas integration is enabled; scheduling submission check-in for this project in the current cycle')
                        tasks.append(canvas_submission_checkin_module.s(period.id, API_root))
                    else:
                        print('**  Submission period is closed, or canvas integration not enabled for this submission period')
                else:
                    print('**   Canvas integration is not enabled for this project class for cycle '
                          '{yra}-{yrb}'.format(yra=config.submit_year_a, yrb=config.submit_year_b))

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='STARTED', meta={'msg': 'Spawning Canvas subtasks for synchronization of submission availability'})

        c_tasks = group(*tasks)
        c_tasks.apply_async()


    @celery.task(bind=True, default_retry_delay=30)
    def canvas_submission_checkin_module(self, pid, API_root: str):
        self.update_state(state='STARTED', meta={'msg': 'Initiating Canvas checkin for synchronization of submission availability'})

        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=pid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state(state='FAILED', meta={'msg': 'Could not read SubmissionPeriodRecord from database'})
            raise Ignore()

        # if canvas integration is not enabled, assume we can exit
        if not period.canvas_enabled:
            return

        config: ProjectClassConfig = period.config

        print('** Querying Canvas API for submission list on module for {pcl} '
              '(module id={mid}, assigment id={aid})'.format(pcl=config.name, mid=period.canvas_module_id,
                                                             aid=period.canvas_assignment_id))

        # reset the Canvas submission availability flag
        for sub in period.submissions:
            sub: SubmissionRecord
            sub.canvas_submission_available = False

        # set up requests session; safe to assume config.canvas_login is not zero
        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer {token}'.format(token=config.canvas_login.canvas_API_token)})

        API_URL = url_normalize(
            urljoin(API_root,
                    "courses/{course_id}/assignments/{assign_id}/submissions".format(course_id=period.canvas_module_id,
                                                                                     assign_id=period.canvas_assignment_id)))
        submission_list = _URL_query(session, API_URL)

        if submission_list is None:
            print('** [{pcl}]: no submissions available from Canvas API'.format(pcl=config.name))
            return

        # now loop through submissions
        for sub in submission_list:
            if sub['workflow_state'] != 'unsubmitted':
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

        self.update_state(state='FINISHED', meta={'msg': 'Finished successfully'})


    @celery.task(bind=True, default_retry_delay=30)
    def pull_report(self, rid, user_id):
        main_config: MainConfig = get_main_config()
        API_root = main_config.canvas_root_API

        if API_root is None:
            print('** Canvas API integration is not enabled; skipping')
            self.update_state(state='FINISHED', meta={'msg': 'Canvas API integration is not enabled; skipped'})
            return

        user = None

        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=rid).first()

            if user_id is not None:
                user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta={'msg': 'Could not load SubmissionRecord instance from database'})
            raise Ignore()

        period: SubmissionPeriodRecord = record.period
        submitter: SubmittingStudent = record.owner
        config: ProjectClassConfig = submitter.config

        if period.closed:
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name} because this '
                                  'submission period has been closed.'.format(name=submitter.student.user.name),
                                  'danger', autocommit=True)
            raise RuntimeError('Period is closed')

        if not period.canvas_enabled:
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name} because Canvas '
                                  'integration is not currently enabled for this submission '
                                  'period.'.format(name=submitter.student.user.name),
                                  'danger', autocommit=True)
            raise RuntimeError('Canvas is not enabled')

        if record.report is not None:
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name} because a report '
                                  'has already been uploaded.'.format(name=submitter.student.user.name),
                                  'warning', autocommit=True)
            raise RuntimeError('A report is already uploaded')

        if submitter.canvas_user_id is None:
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name} because this record '
                                  'has not been synchronized with a Canvas user. Please contact a system '
                                  'administator.'.format(name=submitter.student.user.name),
                                  'danger', autocommit=True)
            raise RuntimeError('Canvas user id is missing from SubmittingStudent instance')

        # set up requests session; safe to assume config.canvas_login is not zero
        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer {token}'.format(token=config.canvas_login.canvas_API_token)})

        API_URL = url_normalize(
            urljoin(API_root,
                    "courses/{course_id}/assignments/{assign_id}/"
                    "submissions/{user_id}".format(course_id=period.canvas_module_id, assign_id=period.canvas_assignment_id,
                                                   user_id=submitter.canvas_user_id)))
        response = session.get(API_URL)
        data = response.json()

        if data['workflow_state'] == 'unsubmitted':
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name}, because the '
                                  'matched Canvas submission is in workflow state "unsubmitted".'.format(name=submitter.student.user.name),
                                  'warning', autocommit=True)
            raise RuntimeError('Canvas workflow state is "unsubmitted"')

        attachments = data['attachments']

        if len(attachments) == 0:
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name} because no attachments '
                                  'are present in the Canvas record.'.format(name=submitter.student.user.name),
                                  'danger', autocommit=True)
            raise RuntimeError('No attachments present')

        elif len(attachments) > 1:
            if user is not None:
                user.post_message('More than one attachment is present in the Canvas record for submitter {name}. '
                                  'To avoid attaching the wrong file, please upload the report for this '
                                  'submitter manually.'.format(name=submitter.student.user.name),
                                  'info', autocommit=True)
            return

        attachment = attachments[0]

        if 'url' not in attachment:
            if user is not None:
                user.post_message('Can not pull report from Canvas for submitter {name} because no URL was present '
                                  'in the Canvas response.'.format(name=submitter.student.user.name),
                                  'danger', autocommit=True)
            raise RuntimeError('No attachments present')

        print('** [Canvas, {pcl}]: Downloading attachment "{file}" for submitting student {name}'.format(pcl=config.name, file=attachment['id'], name=submitter.student.user.name))

        default_report_license = db.session.query(AssetLicense).filter_by(abbreviation='Exam').first()
        if default_report_license is None:
            default_report_license = submitter.student.user.default_license

        get_pdf_report = session.get(attachment['url'])

        asset = SubmittedAsset(timestamp=datetime.now(),
                               uploaded_id=user_id,
                               expiry=None,
                               target_name=attachment['filename'],
                               license=default_report_license)

        object_store = current_app.config.get('OBJECT_STORAGE_ASSETS')
        with AssetUploadManager(asset, bytes=get_pdf_report.content, storage=object_store, length=attachment['size'],
                                mimetype=attachment['content-type']) as upload_mgr:
            pass

        adapter = AssetCloudAdapter(asset, object_store)

        similarity_score = None
        web_overlap = None
        publication_overlap = None
        student_overlap = None
        turnitin_outcome = None

        if 'turnitin_data' in data:
            turnitin_attachments = data['turnitin_data']

            if len(turnitin_attachments) >= 1:
                key = next(iter(turnitin_attachments))
                turnitin_data = turnitin_attachments[key]

                if turnitin_data['status'] == 'scored':
                    if 'similarity_score' in turnitin_data:
                        similarity_score = turnitin_data['similarity_score']

                    if 'web_overlap' in turnitin_data:
                        web_overlap = turnitin_data['web_overlap']

                    if 'publication_overlap' in turnitin_data:
                        publication_overlap = turnitin_data['publication_overlap']

                    if 'student_overlap' in turnitin_data:
                        student_overlap = turnitin_data['student_overlap']

                    if 'state' in turnitin_data:
                        turnitin_outcome = turnitin_data['state']

        try:
            db.session.add(asset)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            adapter.delete()
            raise Ignore()

        return {'asset_id': asset.id,
                'turnitin_outcome': turnitin_outcome,
                'similarity_score': similarity_score,
                'web_overlap': web_overlap,
                'publication_overlap': publication_overlap,
                'student_overlap': student_overlap}


    @celery.task(bind=True, default_retry_delay=30)
    def pull_report_finalize(self, data, rid, user_id) -> bool:
        asset_id = data['asset_id']
        if asset_id is None:
            return False

        turnitin_outcome = data['turnitin_outcome']
        similarity_score = data['similarity_score']
        web_overlap = data['web_overlap']
        publication_overlap = data['publication_overlap']
        student_overlap = data['student_overlap']

        user = None

        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=rid).first()
            asset: SubmittedAsset = db.session.query(SubmittedAsset).filter_by(id=asset_id).first()

            if user_id is not None:
                user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load SubmissionRecord instance from database'})
            raise Ignore()

        if asset is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load SubmittedAsset model from database'})

        # attach this asset as the uploaded report
        record.report_id = asset.id

        # uploading user has access
        if user_id is not None:
            asset.grant_user(user_id)

        # users with appropriate roles have access
        for role in record.roles:
            asset.grant_user(role.user)

        # student can download their own report
        if record.owner is not None and record.owner.student is not None:
            asset.grant_user(record.owner.student.user)

        # set up list of roles that should have access, if they exist
        asset.grant_roles(['office', 'convenor', 'moderator', 'exam_board', 'external_examiner'])

        # remove processed report, if that has not already been done
        if record.processed_report is not None:
            expiry_date = datetime.now() + timedelta(days=30)
            record.processed_report.expiry = expiry_date
            record.processed_report_id = None

        record.celery_started = True
        record.celery_finished = None
        record.timestamp = None
        record.report_exemplar = False

        record.turnitin_outcome = turnitin_outcome
        record.turnitin_score = similarity_score
        record.turnitin_web_overlap = web_overlap
        record.turnitin_publication_overlap = publication_overlap
        record.turnitin_student_overlap = student_overlap

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise Ignore()

        process = celery.tasks['app.tasks.process_report.process']
        finalize = celery.tasks['app.tasks.process_report.finalize']
        error = celery.tasks['app.tasks.process_report.error']

        work = chain(process.si(record.id),
                     finalize.si(record.id)).on_error(error.si(record.id, user_id))
        work.apply_async()

        if user is not None:
            user.post_message('Successfully pulled report from Canvas for submitter '
                              '{name}'.format(name=record.owner.student.user.name), 'success', autocommit=True)

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def pull_report_error(self, rid, user_id):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=rid).first()
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta={'msg': 'Could not load SubmissionRecord instance from database'})
            raise Ignore()

        if user is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load User model from database'})
            raise Ignore()

        user.post_message('An error occurred when pulling the report for submitter {name} from '
                          'Canvas'.format(name=record.owner.student.user.name), 'danger', autocommit=True)

        raise RuntimeError('Errors occurred when pulling report from Canvas')


    @celery.task(bind=True, defauly_retry_delay=30)
    def pull_all_reports_summary(self, data, user_id):
        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        success = sum(1 if x is True else 0 for x in data)
        fail = len(data) - success

        if user is None:
            self.update_state(state='FAILURE', meta={'msg': 'Could not load User model from database'})
            raise Ignore()

        tag = 'success' if fail == 0 else 'danger'

        msg = ''
        if success > 0:
            msg = msg + 'Successfully pulled {n} reports from Canvas.'.format(n=success)

        if fail > 0:
            if len(msg) > 0:
                msg = msg + ' '
            msg = msg + 'Some reports could not be pulled automatically, and may require manual intervention.'

        user.post_message(msg, tag, autocommit=True)
