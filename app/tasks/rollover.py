#
# Created by David Seery on 08/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord, BackupRecord, ProjectClassConfig, \
    SelectingStudent, SubmittingStudent, StudentData, EnrollmentRecord, MatchingAttempt, MatchingRecord, \
    SubmissionRecord, SubmissionPeriodRecord, add_notification, EmailNotification, ProjectClass, Project, \
    ProjectDescription, ConfirmRequest

from ..task_queue import progress_update

from ..shared.utils import get_current_year
from ..shared.convenor import add_selector, add_blank_submitter
from ..shared.sqlalchemy import get_count

from celery import chain, group
from celery.exceptions import Ignore

from datetime import datetime
from dateutil.relativedelta import relativedelta


def register_rollover_tasks(celery):

    @celery.task(bind=True)
    def pclass_rollover(self, task_id, use_markers, current_id, convenor_id):
        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to rollover...', autocommit=True)

        if not isinstance(use_markers, bool):
            use_markers = bool(int(use_markers))

        # get new academic year
        year = get_current_year()

        # get database records for this project class
        try:
            config = ProjectClassConfig.query.filter_by(id=current_id).first()
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is None or config is None:
            if convenor is not None:
                convenor.post_message('Rollover failed because some database records could not be loaded.',
                                      'danger', autocommit=True)

            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')

            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            return rollover_fail.apply_async(args=(task_id, convenor_id))

        if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER:
            convenor.post_message('Cannot yet rollover for {name} {yra}--{yrb} '
                                  'because not all selector activities have been '
                                  'finalised.'.format(name=config.name, yra=year, yrb=year + 1))
            self.update_state('FAILURE', meta='Selector lifecycle state is not ready for rollover')
            return rollover_fail.apply_async(args=(task_id, convenor_id))

        if config.submitter_lifecycle < ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
            convenor.post_message('Cannot yet rollover for {name} {yra}--{yrb} '
                                  'because not all submitter activities have been '
                                  'finalised.'.format(name=config.name, yra=year, yrb=year + 1))
            self.update_state('FAILURE', meta='Submitter lifecycle state is not ready for rollover')
            return rollover_fail.apply_async(args=(task_id, convenor_id))

        # find selected MatchingAttempt that contains allocations for this project class, if used
        match = None
        if config.do_matching:
            match = config.allocated_match

            if match is None:
                convenor.post_message('Could not find allocated matches for {name} '
                                      '{yra}--{yrb}'.format(name=config.name, yra=year, yrb=year + 1))
                self.update_state('FAILURE', meta='Could not find selected MatchingAttempt record')
                return rollover_fail.apply_async(args=(task_id, convenor_id))

        # build group of tasks to convert SelectingStudent instances from the current config into
        # SubmittingStudent instances for next year's config
        convert_selectors = group(convert_selector.s(current_id, s.id,
                                                     match.id if match is not None else None, use_markers)
                                  for s in config.selecting_students)

        # build group of tasks to perform attachment of new records;
        # these will attach all new SelectingStudent instances, and mop up any eligible
        # SubmittingStudent instances that weren't automatically created by conversion of
        # SelectingStudent instances
        students = db.session.query(StudentData) \
            .join(User, User.id == StudentData.id) \
            .filter(User.active == True).all()
        attach_group = group(attach_records.s(current_id, s.id, year) for s in students)

        # build group of tasks to perform retirements: these will be done *last*
        retire_selectors = [retire_selector.s(s.id) for s in config.selecting_students]
        retire_submitters = [retire_submitter.s(s.id) for s in config.submitting_students]

        retire_group = group(retire_selectors + retire_submitters)

        # build group of tasks to check for faculty re-enrollment after buyout or sabbatical
        reenroll_query = db.session.query(EnrollmentRecord.id) \
            .filter(EnrollmentRecord.pclass_id == config.pclass_id,
                    or_(EnrollmentRecord.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED,
                        EnrollmentRecord.marker_state != EnrollmentRecord.MARKER_ENROLLED))
        reenroll_group = group(reenroll_faculty.s(rec.id, year) for rec in reenroll_query.all())

        # perform maintenance on EnrollmentRecords
        maintenance_query = db.session.query(EnrollmentRecord.id) \
            .filter(EnrollmentRecord.pclass_id == config.pclass_id)
        maintenance_group = group(enrollment_maintenance.s(rec.id) for rec in maintenance_query.all())

        # build group of project descriptions attached to this project class
        project_descs = set()

        projects = db.session.query(Project) \
            .filter(Project.project_classes.any(id=config.pclass_id)).all()

        # want to use get_description() to get ProjectDescription, to account for logic
        # associated with having a default
        for p in projects:
            desc = p.get_description(config.pclass_id)
            if desc is not None:
                project_descs.add(desc.id)

        descs_group = group(reset_project_description.s(d_id) for d_id in project_descs)

        # remove ConfirmRequest items that were never actioned
        confirm_request_query = db.session.query(ConfirmRequest) \
            .join(SelectingStudent, SelectingStudent.id == ConfirmRequest.owner_id) \
            .join(ProjectClassConfig, ProjectClassConfig.id == SelectingStudent.config_id) \
            .filter(ProjectClassConfig.pclass_id == config.pclass_id,
                    ConfirmRequest.state == ConfirmRequest.REQUESTED).all()
        confirm_request_group = group(remove_confirm_request.s(rec.id) for rec in confirm_request_query)

        # get backup task from Celery instance
        celery = current_app.extensions['celery']
        backup = celery.tasks['app.tasks.backup.backup']

        seq = chain(rollover_initialize_msg.si(task_id),
                    backup.si(convenor_id, type=BackupRecord.PROJECT_ROLLOVER_FALLBACK, tag='rollover',
                              description='Rollback snapshot for {proj} rollover to '
                                          '{yr}'.format(proj=config.name, yr=year)),
                    rollover_new_config_msg.si(task_id),
                    build_new_pclass_config.si(task_id, config.pclass_id, convenor_id, current_id))

        if len(convert_selectors) > 0:
            seq = seq | rollover_convert_msg.s(task_id) | convert_selectors

        if len(attach_group) > 0:
            seq = seq | rollover_attach_msg.s(task_id) | attach_group

        if len(retire_group) > 0:
            seq = seq | rollover_retire_msg.s(task_id) | retire_group

        # omit re-enroll group if it has length zero, otherwise we get an empty list passed into
        # rollover_finalize()
        if len(reenroll_group) > 0:
            seq = seq | rollover_reenroll_msg.s(task_id) | reenroll_group

        if len(maintenance_group) > 0:
            seq = seq | rollover_maintenance_msg.s(task_id) | maintenance_group

        if len(project_descs) > 0:
            seq = seq | reset_descriptions_msg.s(task_id) | descs_group

        if len(confirm_request_group) > 0:
            seq = seq | confirm_request_msg.s(task_id) | confirm_request_group

        seq = (seq | rollover_finalize.s(task_id, convenor_id)).on_error(rollover_fail.si(task_id, convenor_id))
        raise self.replace(seq)


    @celery.task()
    def rollover_initialize_msg(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building rollback snapshot...', autocommit=True)


    @celery.task()
    def rollover_new_config_msg(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 10, 'Generating database records for new academic year...', autocommit=True)


    @celery.task(bind=True)
    def rollover_convert_msg(self, results, task_id):
        # currently think it's safe to assume results_bundle[0] is new_config_id, since if any previous task in the chain
        # errored and returned None, execution of the whole chain should have halted

        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 20, 'Converting selector records into submitter records...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_attach_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 30, 'Attaching new student records...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_retire_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 40, 'Retiring current student records...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_reenroll_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 50, 'Checking for faculty re-enrollments...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_maintenance_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 60, 'Performing routine maintenance...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def reset_descriptions_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 70, 'Reset project description lifecycles...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def confirm_request_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 80, 'Remove unused confirmation requests...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_finalize(self, results, task_id, convenor_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Rollover complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config = ProjectClassConfig.query.filter_by(id=new_config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update('FAILURE', 'Could not load new ProjectClassConfig')
            return

        self.update_state(state='SUCCESS')

        if convenor is not None:
            # ask web page to dynamically hide the rollover panel
            convenor.send_showhide('rollover-panel', 'hide', autocommit=False)
            # send direct message to user announcing successful rollover
            convenor.post_message('Rollover of academic year is now complete', 'success', autocommit=False)
            convenor.send_replacetext('selector-count', '{c}'.format(c=config.selecting_students.count()), autocommit=False)
            convenor.send_replacetext('submitter-count', '{c}'.format(c=config.submitting_students.count()), autocommit=False)

        db.session.commit()


    @celery.task(bind=True)
    def rollover_fail(self, task_id, convenor_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, 'Encountered error during rollover', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='FAILURE')

        if convenor is not None:
            convenor.post_message('Rollover of academic year failed. Please contact a system administrator', 'danger',
                                  autocommit=True)


    @celery.task(bind=True)
    def retire_selector(self, new_config_id, sid):
        # get current configuration record
        try:
            item = SelectingStudent.query.filter_by(id=sid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if item is None:
            self.update_state(state='FAILED',
                              meta='Could not read SelectingStudent record for sid={id}'.format(id=sid))
            return

        item.retired = True

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def retire_submitter(self, new_config_id, sid):
        # get current configuration record
        try:
            item = SubmittingStudent.query.filter_by(id=sid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if item is None:
            self.update_state(state='FAILED',
                              meta='Could not read SubmittingStudent record for sid={id}'.format(id=sid))
            return

        item.retired = True

        # retire all SubmissionRecords:
        for rec in item.records:
            rec.retired = True

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def build_new_pclass_config(self, task_id, pclass_id, convenor_id, current_id):
        # get new, rolled-over academic year
        new_year = get_current_year()

        # get current configuration record; makes this task idempotent, so it's safe to run twice or more
        try:
            old_config = ProjectClassConfig.query.filter_by(id=current_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        # check whether a new configuration record needs to be inserted;
        # we expect so, but if we are retrying and there is for some reason
        # an already-inserted record then we just want to be idempotent
        if old_config.year == new_year:
            return old_config.id

        # generate a new ProjectClassConfig for this year
        try:
            # update any start dates in SubmissionPeriodDefinitions
            for t in old_config.template_periods.all():
                if t.start_date is not None:
                    t.start_date = t.start_date + relativedelta(years=1)
            db.session.flush()

            new_config = ProjectClassConfig(year=new_year,
                                            pclass_id=pclass_id,
                                            convenor_id=old_config.project_class.convenor_id,
                                            creator_id=convenor_id,
                                            creation_timestamp=datetime.now(),
                                            requests_issued=False,
                                            request_deadline=None,
                                            live=False,
                                            live_deadline=None,
                                            selection_closed=False,
                                            CATS_supervision=old_config.project_class.CATS_supervision,
                                            CATS_marking=old_config.project_class.CATS_marking,
                                            CATS_presentation=old_config.project_class.CATS_presentation,
                                            submission_period=1)
            db.session.add(new_config)
            db.session.flush()

            # generate new submission periods
            for t in old_config.template_periods.all():
                period = SubmissionPeriodRecord(config_id=new_config.id,
                                                name=t.name,
                                                start_date=t.start_date,
                                                has_presentation=t.has_presentation,
                                                lecture_capture=t.lecture_capture,
                                                collect_presentation_feedback=t.collect_presentation_feedback,
                                                number_assessors=t.number_assessors,
                                                max_group_size=t.max_group_size,
                                                morning_session=t.morning_session,
                                                afternoon_session=t.afternoon_session,
                                                talk_format=t.talk_format,
                                                retired=False,
                                                submission_period=t.period,
                                                feedback_open=False,
                                                feedback_id=None,
                                                feedback_timestamp=None,
                                                feedback_deadline=None,
                                                closed=False,
                                                closed_id=None,
                                                closed_timestamp=None)
                db.session.add(period)

            # retire old SubmissionPeriodRecords:
            for rec in old_config.periods:
                rec.retired = True

            # clear out list of go live notification recipients to keep associate table trim
            rec.golive_notified = []

            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config.id


    @celery.task(bind=True)
    def convert_selector(self, new_config_id, old_config_id, sel_id, match_id, use_markers):
        if not isinstance(use_markers, bool):
            use_markers = bool(int(use_markers))

        match = None

        # get current configuration records
        try:
            config = ProjectClassConfig.query.filter_by(id=new_config_id).first()
            selector = SelectingStudent.query.filter_by(id=sel_id).first()
            if match_id is not None:
                match = MatchingAttempt.query.filter_by(id=match_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state('FAILURE', meta='Could not load rolled-over ProjectClassConfig record '
                                              'while converting selector records')
            return

        if selector is None:
            self.update_state('FAILURE', meta='Could not load SelectingStudent record while converting selector records')
            return

        if not selector.convert_to_submitter:
            return

        if match_id is not None and match is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record while converting selector records')
            return

        if match is not None:
            if selector.config.project_class not in match.available_pclasses:
                self.update_state('FAILURE', meta='Supplied match is not appropriate for the SelectingStudent')
                return

        if int(selector.config.year) != int(config.year)-int(1):
            self.update_state('FAILURE', meta='Inconsistent arrangement of years in configuration records')
            return

        # get list of match records, if one exists
        match_records = None
        if match is not None:
            match_records = match.records.filter_by(selector_id=sel_id).all()

            if len(match_records) == 0:
                match_records = None

        # if a match has been assigned, use this to generate a SubmittingStudent record
        if match_records is not None:
            try:
                student_record = SubmittingStudent(config_id=new_config_id,
                                                   student_id=selector.student_id,
                                                   selector_id=selector.id,
                                                   published=False,
                                                   retired=False)
                db.session.add(student_record)
                db.session.flush()

                for rec in match_records:
                    period = config.get_period(rec.submission_period)
                    sub_record = SubmissionRecord(period_id=period.id,
                                                  retired=False,
                                                  owner_id=student_record.id,
                                                  project_id=rec.project_id,
                                                  marker_id=rec.marker_id if use_markers else None,
                                                  selection_config_id=old_config_id,
                                                  matching_record_id=rec.id,
                                                  student_engaged=False,
                                                  supervisor_positive=None,
                                                  supervisor_negative=None,
                                                  supervisor_submitted=False,
                                                  supervisor_timestamp=None,
                                                  marker_positive=None,
                                                  marker_negative=None,
                                                  marker_submitted=False,
                                                  marker_timestamp=None,
                                                  student_feedback=None,
                                                  student_feedback_submitted=False,
                                                  student_feedback_timestamp=None,
                                                  acknowledge_feedback=False,
                                                  faculty_response=None,
                                                  faculty_response_submitted=False,
                                                  faculty_response_timestamp=None)
                    db.session.add(sub_record)

                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()

        else:
            try:
                if selector.academic_year == config.start_year - 1:
                    if config.selection_open_to_all:
                        # no allocation here means that the selector chose not to participate
                        pass
                    else:
                        if not config.do_matching:
                            # allocation is being done manually; generate an empty submitter
                            add_blank_submitter(selector.student, old_config_id, new_config_id, autocommit=False)
                        else:
                            self.update_state('FAILURE', meta='Unexpected missing selector allocation')
                            return

                elif selector.academic_year >= config.start_year:
                    if config.supervisor_carryover:
                        # if possible, we should carry over supervisor allocations from the previous year
                        prev_record = db.session.query(SubmittingStudent) \
                            .filter(SubmittingStudent.config_id == selector.config_id,
                                    SubmittingStudent.student_id == selector.student_id).first()

                        if prev_record is not None:
                            student_record = SubmittingStudent(config_id=new_config_id,
                                                               student_id=selector.student_id,
                                                               selector_id=selector.id,
                                                               published=False,
                                                               retired=False)
                            db.session.add(student_record)
                            db.session.flush()

                            for rec in prev_record.records:
                                period = config.get_period(rec.submission_period)
                                sub_record = SubmissionRecord(period_id=period.id,
                                                              retired=False,
                                                              owner_id=student_record.id,
                                                              project_id=rec.project_id,
                                                              marker_id=rec.marker_id,
                                                              selection_config_id=old_config_id,
                                                              matching_record_id=None,
                                                              student_engaged=False,
                                                              supervisor_positive=None,
                                                              supervisor_negative=None,
                                                              supervisor_submitted=False,
                                                              supervisor_timestamp=None,
                                                              marker_positive=None,
                                                              marker_negative=None,
                                                              marker_submitted=False,
                                                              marker_timestamp=None,
                                                              student_feedback=None,
                                                              student_feedback_submitted=False,
                                                              student_feedback_timestamp=None,
                                                              acknowledge_feedback=False,
                                                              faculty_response=None,
                                                              faculty_response_submitted=False,
                                                              faculty_response_timestamp=None)
                                db.session.add(sub_record)
                        else:
                            # previous record is missing, for whatever reason, so generate a blank
                            add_blank_submitter(selector.student, old_config_id, new_config_id, autocommit=False)

                    else:
                        if not config.do_matching:
                            # allocation is being done manually; generate an empty selector
                            add_blank_submitter(selector.student, old_config_id, new_config_id, autocommit=False)
                        else:
                            self.update_state('FAILURE', meta='Unexpected missing selector allocation')
                            return

                else:
                    self.update_state('FAILURE', meta='Unexpected academic year')
                    return

            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def attach_records(self, new_config_id, old_config_id, sid, current_year):
        # get current configuration record
        try:
            config = ProjectClassConfig.query.filter_by(id=new_config_id).first()
            student = StudentData.query.filter_by(id=sid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state('FAILURE', meta='Could not load rolled-over ProjectClassConfig record '
                                              'while attaching student records')
            return

        if student is None:
            self.update_state('FAILURE', meta='Could not load StudentData record while attaching student records')
            return

        # compute current academic year for this student
        academic_year = student.academic_year(current_year)

        try:
            # generate selector records for students:
            #  - if student is an an appropriate academic year, either the year before the project first runs
            #    or any year for the extent of the project, depending what auto-enroll settings are in force
            #  - the student is on an appropirate programme or selection is open to all
            if (config.auto_enroll_years == ProjectClass.AUTO_ENROLL_PREVIOUS_YEAR
                    and academic_year == config.start_year - 1) \
                or (config.auto_enroll_years == ProjectClass.AUTO_ENROLL_ANY_YEAR
                        and config.start_year - 1 <= academic_year < config.start_year + config.extent - 1):

                if config.selection_open_to_all or (student.programme in config.programmes):
                    # check whether a SelectingStudent has already been generated for this student
                    # (eg. could happen if the task is accidentally run twice)
                    count = get_count(student.selecting.filter_by(retired=False, config_id=new_config_id))
                    if count == 0:
                        add_selector(student, new_config_id, autocommit=False)


            # generate submitter records for students, only if no existing submitter record exists
            # (eg. generated by conversion from a previous SelectingStudent record)
            if config.start_year <= academic_year < config.start_year + config.extent \
                    and student.programme in config.programmes:

                # check whether a SubmittingStudent has already been generated for this student
                count_sub = get_count(student.submitting.filter_by(retired=False, config_id=new_config_id))
                # check whether there is a SelectingStudent that has been marked to disable
                count_disable = get_count(student.selecting.filter_by(retired=False, config_id=old_config_id,
                                                                      convert_to_submitter=False))
                if count_sub == 0 and count_disable == 0:
                    add_blank_submitter(student, old_config_id, new_config_id, autocommit=False)

            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def enrollment_maintenance(self, new_config_id, rec_id):
        # get faculty enrollment record
        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord')
            raise Ignore()

        record.CATS_supervision = None
        record.CATS_marking = None
        record.CATS_presentation = None

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def reenroll_faculty(self, new_config_id, rec_id, current_year):
        # get faculty enrollment record
        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord')
            raise Ignore()

        # supervisors re-enroll in the year *before* they come off sabbatical, so they can offer
        # projects during the selection cycle
        if record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
            # supervisors are sometimes re-enrolled one year early, because projects are *offered*
            # in the academic year before the run
            renroll_offset = -1 if record.pclass.reenroll_supervisors_early else 0

            if record.supervisor_reenroll is not None and record.supervisor_reenroll + renroll_offset <= current_year:
                record.supervisor_state = EnrollmentRecord.SUPERVISOR_ENROLLED
                record.supervisor_comment = 'Automatically re-enrolled during academic year rollover'
                add_notification(record.owner, EmailNotification.FACULTY_REENROLL_SUPERVISOR, record)

        # markers (and presentation assessors) re-enroll in the year they come off sabbatical
        if record.marker_state != EnrollmentRecord.MARKER_ENROLLED:
            if record.marker_reenroll is not None and record.marker_reenroll <= current_year:
                record.marker_state = EnrollmentRecord.MARKER_ENROLLED
                record.marker_comment = 'Automatically re-enrolled during academic year rollover'
                add_notification(record.owner, EmailNotification.FACULTY_REENROLL_MARKER, record)

        if record.presentations_state != EnrollmentRecord.PRESENTATIONS_ENROLLED:
            if record.presentations_reenroll is not None and record.presentations_reenroll <= current_year:
                record.presentations_state = EnrollmentRecord.PRESENTATIONS_ENROLLED
                record.presentations_comment = 'Automatically re-enrolled during academic year rollover'
                add_notification(record.owner, EmailNotification.FACULTY_REENROLL_PRESENTATIONS, record)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def reset_project_description(self, new_config_id, desc_id):
        # get ProjectDescription
        try:
            record = db.session.query(ProjectDescription).filter_by(id=desc_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', 'Could not load ProjectDescription')
            raise Ignore()

        record.confirmed = False

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id

    @celery.task(bind=True)
    def remove_confirm_request(self, new_config_id, request_id):
        # get ConfirmRequest corresponding to request_id
        try:
            record = db.session.query(ConfirmRequest).filter_by(id=request_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', 'Could not not ConfirmRequest')
            raise Ignore()

        db.session.delete(record)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id
