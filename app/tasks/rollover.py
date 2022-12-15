#
# Created by David Seery on 08/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime
from typing import List

from celery import chain, group
from celery.exceptions import Ignore
from dateutil.relativedelta import relativedelta
from flask import current_app
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User, TaskRecord, ProjectClassConfig, \
    SelectingStudent, SubmittingStudent, StudentData, EnrollmentRecord, MatchingAttempt, SubmissionRecord, \
    SubmissionPeriodRecord, add_notification, EmailNotification, ProjectClass, Project, \
    ProjectDescription, ConfirmRequest, ConvenorGenericTask, MatchingRecord, DegreeProgramme, DegreeType, \
    SubmissionPeriodDefinition
from ..shared.convenor import add_selector, add_blank_submitter
from ..shared.sqlalchemy import get_count
from ..shared.utils import get_current_year
from ..task_queue import progress_update


def register_rollover_tasks(celery):

    @celery.task(bind=True)
    def prune_matches(self, task_id, current_year, admin_id):
        progress_update(task_id, TaskRecord.RUNNING, 10, "Pruning unneeded matching attempts...",
                        autocommit=True)

        # try to prune unused matching attempts from the database, to keep things tidy
        unused_attempts = db.session.query(MatchingAttempt).filter_by(year=current_year, selected=False).all()

        try:
            for attempt in unused_attempts:
                accomodating: List[ProjectClassConfig] = attempt.accommodations.all()
                for item in accomodating:
                    item.accommodate_matching_id = None

                # null any references to this attempt as a base
                descendants: List[MatchingAttempt] = \
                    db.session.query(MatchingAttempt).filter_by(year=current_year, base_id=attempt.id).all()
                for item in descendants:
                    item.base_id = None

                attempt.config_members = []
                attempt.include_matches = []

                attempt.supervisors = []
                attempt.markers = []
                attempt.projects = []

                db.session.flush()
                db.session.delete(attempt)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True)
    def pclass_rollover(self, task_id, use_markers, current_id, convenor_id):
        progress_update(task_id, TaskRecord.RUNNING, 0, 'Preparing to rollover...', autocommit=True)

        # if use_markers is not directly a boolean type, try to cast it to something boolean
        if not isinstance(use_markers, bool):
            use_markers = bool(int(use_markers))

        # get new academic year
        year = get_current_year()

        # get database records for this project class
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=current_id).first()
            convenor: User = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        # if could not read database records for config and convenor, can hardly proceed
        if convenor is None or config is None:
            if convenor is not None:
                convenor.post_message('Rollover failed because some database records could not be loaded.',
                                      'danger', autocommit=True)

            if config is None:
                self.update_state('FAILURE', meta='Could not load ProjectClassConfig record from database')

            if convenor is None:
                self.update_state('FAILURE', meta='Could not load convenor User record from database')

            raise self.replace(rollover_fail.s(task_id, convenor_id))

        # if selector lifecycle is not ready to rollover, bail out
        if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER:
            convenor.post_message('Cannot yet rollover for {name} {yra}-{yrb} '
                                  'because not all selector activities have been '
                                  'finalised. (Lifecycle stage={l}.)'.format(name=config.name, yra=year, yrb=year + 1,
                                                                             l=config.selector_lifecycle),
                                  'info', autocommit=True)
            self.update_state('FAILURE', meta='Selector lifecycle state is not ready for rollover')
            raise self.replace(rollover_fail.s(task_id, convenor_id))

        # if submitter lifecycle is not ready to rollover, bail out
        if config.submitter_lifecycle < ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
            convenor.post_message('Cannot yet rollover for {name} {yra}-{yrb} '
                                  'because not all submitter activities have been '
                                  'finalised. (Lifecycle stage={l}.)'.format(name=config.name, yra=year, yrb=year + 1,
                                                                             l=config.submitter_lifecycle),
                                  'info', autocommit=True)
            self.update_state('FAILURE', meta='Submitter lifecycle state is not ready for rollover')
            raise self.replace(rollover_fail.s(task_id, convenor_id))

        # if automated matching is being used, find the selected MatchingAttempt that contains allocations for this
        # project class
        match = None
        if config.do_matching:
            match = config.allocated_match

            if match is None:
                convenor.post_message('Could not find allocated matches for {name} '
                                      '{yra}-{yrb}'.format(name=config.name, yra=year, yrb=year + 1),
                                      'info', autocommit=True)
                self.update_state('FAILURE', meta='Could not find selected MatchingAttempt record')
                raise self.replace(rollover_fail.s(task_id, convenor_id))

        # build task group to convert SelectingStudent instances from the current config into
        # SubmittingStudent instances for next year's config
        convert_selectors = group(convert_selector.s(current_id, s.id,
                                                     match.id if match is not None else None, use_markers)
                                  for s in config.selecting_students)

        # build task group to perform attachment of new records;
        # these will attach all new SelectingStudent instances, and mop up any eligible
        # SubmittingStudent instances that weren't automatically created by conversion of
        # SelectingStudent instances

        # students contains all active student records (so this does not scale well as the number of users goes up);
        # we want to process these to attach submitters/selectors, bearing in mind that some submitter
        # records will have been generated from conversion of selector records via convert_selectors
        # TODO: probably want to do this in a more intelligent way!
        students = db.session.query(StudentData) \
            .join(User, User.id == StudentData.id) \
            .filter(User.active == True).all()
        attach_group = group(attach_selectors_submitters.s(current_id, s.id, year) for s in students)

        # build group of tasks to perform retirements: these will be done *last*
        retire_selectors = [retire_selector.s(s.id) for s in config.selecting_students]
        retire_submitters = [retire_submitter.s(s.id) for s in config.submitting_students]

        retire_group = group(retire_selectors + retire_submitters)

        # build group of tasks to check for faculty re-enrolment after buyout or sabbatical
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

        # build set of tasks to reset project descriptions
        descs_group = group(reset_project_description.s(d_id) for d_id in project_descs)

        # remove ConfirmRequest items that were never actioned
        confirm_request_query = db.session.query(ConfirmRequest) \
            .join(SelectingStudent, SelectingStudent.id == ConfirmRequest.owner_id) \
            .join(ProjectClassConfig, ProjectClassConfig.id == SelectingStudent.config_id) \
            .filter(ProjectClassConfig.pclass_id == config.pclass_id,
                    ConfirmRequest.state == ConfirmRequest.REQUESTED).all()
        confirm_request_group = group(remove_confirm_request.s(rec.id) for rec in confirm_request_query)

        rollover_chain = chain(rollover_new_config_msg.si(task_id),
                               build_new_pclass_config.si(task_id, config.pclass_id, convenor_id, current_id))

        if len(convert_selectors) > 0:
            rollover_chain = rollover_chain | rollover_convert_msg.s(task_id) | convert_selectors

        if len(attach_group) > 0:
            rollover_chain = rollover_chain | rollover_attach_msg.s(task_id) | attach_group

        if len(retire_group) > 0:
            rollover_chain = rollover_chain | rollover_retire_msg.s(task_id) | retire_group

        # omit re-enroll group if it has length zero, otherwise we get an empty list passed into
        # rollover_finalize()
        if len(reenroll_group) > 0:
            rollover_chain = rollover_chain | rollover_reenroll_msg.s(task_id) | reenroll_group

        if len(maintenance_group) > 0:
            rollover_chain = rollover_chain | rollover_maintenance_msg.s(task_id) | maintenance_group

        if len(project_descs) > 0:
            rollover_chain = rollover_chain | reset_descriptions_msg.s(task_id) | descs_group

        if len(confirm_request_group) > 0:
            rollover_chain = rollover_chain | confirm_request_msg.s(task_id) | confirm_request_group

        rollover_chain = rollover_chain | rollover_finalize.s(task_id, convenor_id)

        return self.replace(rollover_chain)


    @celery.task()
    def rollover_backup_msg(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, 'Building rollback snapshot...', autocommit=True)


    @celery.task()
    def rollover_new_config_msg(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 10, 'Generating database records for new academic year...',
                        autocommit=True)


    @celery.task(bind=True)
    def rollover_convert_msg(self, results, task_id):
        # currently think it's safe to assume results_bundle[0] is new_config_id, since if any previous task in the chain
        # errored and returned None, execution of the whole chain should have halted

        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 20, 'Converting selector records into submitter records...',
                        autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_attach_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
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
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
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
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.RUNNING, 50, 'Checking for faculty re-enrolments...', autocommit=True)
        return new_config_id


    @celery.task(bind=True)
    def rollover_maintenance_msg(self, results, task_id):
        if isinstance(results, int):
            new_config_id = results
        elif isinstance(results, list):
            new_config_id = results[0]
        else:
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
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
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
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
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
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
            self.update_state('FAILURE', 'Unexpected type forwarded in rollover chain')
            raise RuntimeError('Unexpected type forwarded in rollover chain')

        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Rollover complete', autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config = ProjectClassConfig.query.filter_by(id=new_config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state('FAILURE', 'Could not load new ProjectClassConfig')
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
            return new_config_id

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
            return new_config_id

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

            pclass = old_config.project_class
            new_config = ProjectClassConfig(year=new_year,
                                            pclass_id=pclass_id,
                                            convenor_id=pclass.convenor_id,
                                            creator_id=convenor_id,
                                            creation_timestamp=datetime.now(),
                                            uses_supervisor=pclass.uses_supervisor,
                                            uses_marker=pclass.uses_marker,
                                            uses_moderator=pclass.uses_moderator,
                                            uses_presentations=pclass.uses_presentations,
                                            display_marker=pclass.display_marker,
                                            display_presentations=pclass.display_presentations,
                                            requests_issued=False,
                                            requests_issued_id=None,
                                            requests_timestamp=None,
                                            request_deadline=None,
                                            requests_skipped=False,
                                            requests_skipped_id=None,
                                            requests_skipped_timestamp=None,
                                            use_project_hub=old_config.use_project_hub,
                                            live=False,
                                            live_deadline=None,
                                            selection_closed=False,
                                            CATS_supervision=pclass.CATS_supervision,
                                            CATS_marking=pclass.CATS_marking,
                                            CATS_moderation=pclass.CATS_moderation,
                                            CATS_presentation=pclass.CATS_presentation,
                                            submission_period=1,
                                            canvas_module_id=None,
                                            canvas_login_id=None)
            db.session.add(new_config)
            db.session.flush()

            # generate new submission periods
            for t in old_config.template_periods.all():
                period = SubmissionPeriodRecord(config_id=new_config.id,
                                                name=t.name,
                                                number_markers=t.number_markers,
                                                number_moderators=t.number_moderators,
                                                start_date=t.start_date,
                                                has_presentation=t.has_presentation,
                                                lecture_capture=t.lecture_capture,
                                                collect_presentation_feedback=t.collect_presentation_feedback,
                                                collect_project_feedback=t.collect_project_feedback,
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
                                                closed_timestamp=None,
                                                canvas_module_id=None,
                                                canvas_assignment_id=None)
                db.session.add(period)

            # retire old SubmissionPeriodRecords:
            for rec in old_config.periods:
                rec.retired = True

            # clear out list of go live notification recipients to keep association table trim
            rec.golive_notified = []

            # attach any tasks that are marked as rolling over to the new ProjectClassConfig instance
            rollover_tasks = set()
            for tk in old_config.tasks:
                tk: ConvenorGenericTask
                if tk.rollover and not (tk.complete or tk.dropped):
                    rollover_tasks.add(tk)

            for tk in rollover_tasks:
                old_config.tasks.remove(tk)
                new_config.tasks.append(tk)

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

        # no need to check if ProjectClass.do_matching or ProjectClassConfig.skip_matching flags are set,
        # since match_id will be None if these flags imply that we should ignore any MatchingAttempt
        match = None

        # get current configuration records
        try:
            new_config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=new_config_id).first()
            old_config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=old_config_id).first()
            selector: SelectingStudent = SelectingStudent.query.filter_by(id=sel_id).first()
            if match_id is not None:
                match: MatchingAttempt = MatchingAttempt.query.filter_by(id=match_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if new_config is None:
            self.update_state('FAILURE', meta='Could not load rolled-over ProjectClassConfig record '
                                              'while converting selector records')
            return new_config_id

        if old_config is None:
            self.update_state('FAILURE', meta='Could not load previous ProjectClassConfig record '
                                              'while converting selector records')
            return new_config_id

        if selector is None:
            self.update_state('FAILURE', meta='Could not load SelectingStudent record while converting selector records')
            return new_config_id

        if not selector.convert_to_submitter:
            return new_config_id

        if match_id is not None and match is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record while converting selector records')
            return new_config_id

        if match is not None and selector.config.project_class not in match.available_pclasses:
            self.update_state('FAILURE', meta='Supplied match is not appropriate for the SelectingStudent')
            return new_config_id

        if int(selector.config.year) != int(new_config.year)-int(1):
            self.update_state('FAILURE', meta='Inconsistent arrangement of years in configuration records')
            return new_config_id

        # get list of match records, if one exists
        match_records = None
        if match is not None:
            match_records: List[MatchingRecord] = match.records.filter_by(selector_id=sel_id).all()

            if len(match_records) == 0:
                match_records = None

        # if a match has been assigned, use this to generate a SubmittingStudent record and populate its
        # SubmissionRecord list
        if match_records is not None:
            try:
                new_submitter = SubmittingStudent(config_id=new_config_id,
                                                  student_id=selector.student_id,
                                                  selector_id=selector.id,
                                                  published=False,
                                                  retired=False)
                db.session.add(new_submitter)
                db.session.flush()

                for match_rec in match_records:
                    match_rec: MatchingRecord
                    new_period = new_config.get_period(match_rec.submission_period)
                    new_rec = SubmissionRecord(period_id=new_period.id,
                                               retired=False,
                                               owner_id=new_submitter.id,
                                               project_id=match_rec.project_id,
                                               marker_id=match_rec.marker_id if use_markers else None,
                                               selection_config_id=old_config_id,
                                               matching_record_id=match_rec.id,
                                               student_engaged=False,
                                               report_id=None,
                                               report_exemplar=False,
                                               email_to_supervisor=False,
                                               email_to_marker=False,
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

                    db.session.add(new_rec)

                db.session.commit()

            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()

        else:
            print('## Converting selector "{name}" without a MatchingRecord list'.format(name=selector.student.user.name))

            try:

                if selector.academic_year is not None and not selector.student.has_graduated \
                        and selector.academic_year == new_config.start_year - 1:

                    print('##    selector is in first year of project')

                    if new_config.selection_open_to_all:
                        # interpret no allocation to mean that the selector chose not to participate
                        print('##    dropping selector: assume has elected not to participate')

                    else:

                        if not new_config.do_matching:
                            # allocation is being done manually; generate an empty submitter
                            print('##    allocation is being done manually: creating blank submitter')
                            add_blank_submitter(selector.student, old_config_id, new_config_id, autocommit=False)
                        else:
                            self.update_state('FAILURE', meta='Unexpected missing selector allocation')
                            return new_config_id

                elif selector.academic_year is not None and not selector.student.has_graduated \
                        and selector.academic_year >= new_config.start_year:

                    print('##    selector is in year {yr} of '
                          'project'.format(yr=selector.academic_year - new_config.start_year + 1))

                    if new_config.supervisor_carryover:
                        print('##    new submitter should carry over project from previous year')
                        # if possible, we should carry over supervisor allocations from the previous year
                        old_submitter: SubmittingStudent = db.session.query(SubmittingStudent) \
                            .filter(SubmittingStudent.config_id == selector.config_id,
                                    SubmittingStudent.student_id == selector.student_id).first()

                        if old_submitter is not None:
                            print('##    located previous submitter record')
                            new_submitter = SubmittingStudent(config_id=new_config_id,
                                                              student_id=selector.student_id,
                                                              selector_id=selector.id,
                                                              published=False,
                                                              retired=False)
                            db.session.add(new_submitter)
                            db.session.flush()

                            for old_rec in old_submitter.records:
                                print('##    converting previous submission record "{pdname}" for project '
                                      '"{proj}"'.format(pdname=old_rec.period.display_name,
                                                        proj=old_rec.project.name if old_rec.project is not None else "<unset>"))
                                old_rec: SubmissionRecord

                                new_period = new_config.get_period(old_rec.submission_period)

                                new_project = None
                                if old_rec.project is not None:
                                    new_project = old_config.live_projects.filter_by(parent_id=old_rec.project.parent_id).first()
                                print('##    located new counterpart project '
                                      '"{proj}"'.format(proj=new_project.name if new_project is not None else "<unset>"))

                                new_rec = SubmissionRecord(period_id=new_period.id,
                                                           retired=False,
                                                           owner_id=new_submitter.id,
                                                           project_id=new_project.id if new_project is not None else None,
                                                           marker_id=old_rec.marker_id,
                                                           selection_config_id=old_config_id,
                                                           matching_record_id=None,
                                                           student_engaged=False,
                                                           report_id=None,
                                                           report_exemplar=False,
                                                           email_to_supervisor=False,
                                                           email_to_marker=False,
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

                                db.session.add(new_rec)

                            db.session.commit()

                        else:
                            print('!!     failed to locate previous submitter record')
                            # previous record is missing, for whatever reason, so generate a blank
                            add_blank_submitter(selector.student, old_config_id, new_config_id, autocommit=False)

                    else:

                        if not new_config.do_matching:
                            # allocation is being done manually; generate an empty selector
                            add_blank_submitter(selector.student, old_config_id, new_config_id, autocommit=False)

                        else:
                            print('!! Unexpected missing selector allocation')
                            self.update_state('FAILURE', meta='Unexpected missing selector allocation')
                            return new_config_id

                else:
                    self.update_state('FAILURE', meta='Unexpected academic year')
                    return new_config_id

            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def attach_selectors_submitters(self, new_config_id, old_config_id, sid, current_year):
        # get current configuration record
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=new_config_id).first()
            student: StudentData = StudentData.query.filter_by(id=sid).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            print("attach_selectors_submitters: could not load rolled-over ProjectClassConfig "
                  "record, new_config_id = {n}".format(n=new_config_id))
            raise self.retry()

        if student is None:
            print("attach_selectors_submittres: could not load StudentData record, "
                  "new_config_id = {n}".format(n=new_config_id))
            raise self.retry()

        # compute current academic year for this student
        academic_year = student.compute_academic_year(current_year)

        # cache student's programme and programme type (BSc, MPhys, etc.)
        programme: DegreeProgramme = student.programme
        programme_type: DegreeType = programme.degree_type

        # if we succeeded in obtaining the academic year, try to auto-enroll selectors and submitters
        if academic_year is None:
            msg = 'Could not compute academic year (new_config_id={nid}, old_config_id={oid}, sid={sid}, ' \
                  'current_year={cyr}'.format(nid=new_config_id, oid=old_config_id, sid=sid, cyr=current_year)
            self.update_state('FAILURE', msg)
            print(msg)
            raise Ignore()

        # keep track of the selector id that was generated (if we generate one)
        # when submission is in the same cycle as selection, we can use this to link the
        # submitter and selector records
        generated_selector_id = None

        try:
            # enrol selectors if auto-enrolment is enabled
            if config.auto_enrol_enable:

                # define a function to test whether a student meets the criteria to attach as a selector
                def check_attach_selector():
                    # if student is not at the correct level (UG, PGT, PGR), do not attach
                    if programme_type.level != config.student_level:
                        return False

                    # do not attach if student's programme is not associated with the project type
                    if not config.selection_open_to_all and programme not in config.programmes:
                        return False

                    # does selection occur in the same academic cycle as submission, or the one before?
                    # this determines the first and last years when students are eligible to select
                    first_year = config.start_year
                    last_year = config.start_year + config.extent
                    if config.select_in_previous_cycle:
                        first_year = first_year - 1
                        last_year = last_year - 1

                    # if only enrolling in the first year, check whether there is a match
                    if config.auto_enroll_years == ProjectClass.AUTO_ENROLL_FIRST_YEAR:
                        if academic_year != first_year:
                            return False

                    # otherwise, check whether this student falls in the first-to-last window
                    elif config.auto_enroll_years == ProjectClass.AUTO_ENROLL_ALL_YEARS:
                        if academic_year < first_year or academic_year > last_year:
                            return False

                    else:
                        # should not get here
                        assert False

                    return True

                # if this student meets all the criteria, generate a selector for them
                if check_attach_selector():
                    # check whether a SelectingStudent has already been generated for this student
                    # (eg. could happen if the task is accidentally run twice)
                    count = get_count(student.selecting.filter_by(retired=False, config_id=new_config_id))
                    if count == 0:
                        generated_selector_id = add_selector(student, new_config_id, autocommit=False)

            # define a function to test whether a student meets the criteria to attach as a submitter
            def check_attach_submitter():
                # if student is not at the correct level (UG, PGT, PGR), do not attach
                if programme_type.level != config.student_level:
                    return False

                first_year = config.start_year
                last_year = config.start_year + config.extent

                # auto-attach only if student's programme is associated with the project type
                if programme not in config.programmes:
                    return False

                if academic_year < first_year or academic_year > last_year:
                    return False

                return True

            # if this student meets all the criteria, generate a submitter record *provided* no existing
            # submitter record exists, e.g., perhaps generated by conversion from a SelectingStudent
            # record in the previous cycle
            if check_attach_submitter():
                # check whether a SubmittingStudent has already been generated for this student
                count_sub = get_count(student.submitting.filter_by(retired=False, config_id=new_config_id))

                # check whether there is a SelectingStudent record from a previous cycle that has been marked
                # as disabled; if there is, we should not generate the SubmittingStudent instance
                if config.select_in_previous_cycle:
                    count_disable = get_count(student.selecting.filter_by(retired=False, config_id=old_config_id,
                                                                          convert_to_submitter=False))
                if count_sub == 0 and count_disable == 0:
                    selecting_config_id = old_config_id if config.select_in_previous_cycle else new_config_id
                    add_blank_submitter(student, selecting_config_id, new_config_id, autocommit=False,
                                        linked_selector_id=generated_selector_id)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id


    @celery.task(bind=True)
    def enrollment_maintenance(self, new_config_id, rec_id):
        # get faculty enrolment record
        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord')
            return new_config_id

        record.CATS_supervision = None
        record.CATS_marking = None
        record.CATS_moderation = None
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
        # get faculty enrolment record
        try:
            record: EnrollmentRecord = db.session.query(EnrollmentRecord).filter_by(id=rec_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord')
            return new_config_id

        if not record.owner.user.active:
            return

        # supervisors re-enroll in the year *before* they come off sabbatical, so they can offer
        # projects during the selection cycle
        if record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
            # supervisors are sometimes re-enrolled one year early, because projects are *offered*
            # in the academic year before the run
            renroll_offset = -1 if record.pclass.reenroll_supervisors_early else 0

            if record.supervisor_reenroll is not None and record.supervisor_reenroll + renroll_offset <= current_year:
                record.supervisor_state = EnrollmentRecord.SUPERVISOR_ENROLLED
                record.supervisor_reenroll = None
                record.supervisor_comment = 'Automatically re-enrolled during academic year rollover'
                if record.pclass.uses_supervisor:
                    add_notification(record.owner, EmailNotification.FACULTY_REENROLL_SUPERVISOR, record)

        # re-enrol markers in the year they come off sabbatical
        if record.marker_state != EnrollmentRecord.MARKER_ENROLLED:
            if record.marker_reenroll is not None and record.marker_reenroll <= current_year:
                record.marker_state = EnrollmentRecord.MARKER_ENROLLED
                record.marker_reenroll = None
                record.marker_comment = 'Automatically re-enrolled during academic year rollover'
                if record.pclass.uses_marker:
                    add_notification(record.owner, EmailNotification.FACULTY_REENROLL_MARKER, record)

        # re-enrol moderator in the year they come off sabbatical
        if record.moderator_state != EnrollmentRecord.MODERATOR_ENROLLED:
            if record.moderator_reenroll is not None and record.moderator_reenroll <= current_year:
                record.moderator_state = EnrollmentRecord.MODERATOR_ENROLLED
                record.moderator_reenroll = None
                record.moderator_comment = 'Automatically re-enrolled during academic year rollover'
                if record.pclass.uses_moderator:
                    add_notification(record.owner, EmailNotification.FACULTY_REENROLL_MODERATOR, record)

        # re-enrol presentation assessors in the year they come off sabbatical
        if record.presentations_state != EnrollmentRecord.PRESENTATIONS_ENROLLED:
            if record.presentations_reenroll is not None and record.presentations_reenroll <= current_year:
                record.presentations_state = EnrollmentRecord.PRESENTATIONS_ENROLLED
                record.presentations_reenroll = None
                record.presentations_comment = 'Automatically re-enrolled during academic year rollover'

                notify = False
                for p in record.pclass.period:
                    p: SubmissionPeriodDefinition
                    if p.has_presentation:
                        notify = True
                        break
                if notify:
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
            record: ProjectDescription = db.session.query(ProjectDescription).filter_by(id=desc_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', 'Could not load ProjectDescription')
            return new_config_id

        # mark description as not confirmed
        record.confirmed = False

        if record.parent.active:
            # if the parent project is active, then validation information can be carried through;
            # there will be no need to re-validate this project in the new cycle unless it is edited.
            # However we *do* enforce that the fields are consistent.
            if record.validator_id is None or record.validated_timestamp is None \
                    or record.workflow_state != ProjectDescription.WORKFLOW_APPROVAL_VALIDATED:
                record.validated_id = None
                record.validated_timestamp = None

            # change projects marked as 'Rejected' back the 'Queued', except that we
            # test for the converse statement so that we pick up any stray meaningless values
            # for workflow_state
            if record.workflow_state != ProjectDescription.WORKFLOW_APPROVAL_QUEUED and \
                    record.workflow_state != ProjectDescription.WORKFLOW_APPROVAL_VALIDATED:
                record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_QUEUED

        else:
            # if the parent project is not active, force the description to be queued and with
            # no validation data
            record.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_QUEUED
            record.validated_id = None
            record.validated_timestamp = None

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
            return new_config_id

        db.session.delete(record)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state='SUCCESS')
        return new_config_id
