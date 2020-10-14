#
# Created by David Seery on 2019-02-03.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_

from celery import group, chain
from celery.exceptions import Ignore

from ..database import db
from ..models import User, FacultyData, StudentData, SelectingStudent, Project, LiveProject, WorkflowMixin, \
    ProjectDescription

import app.ajax as ajax


def register_precompute_tasks(celery):

    @celery.task(bind=True)
    def student_liveprojects(self, user_id):
        # find all current selecting students
        try:
            data = db.session.query(StudentData).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            raise Ignore()

        task = group(selector_liveprojects.si(sel.id) for sel in data.selecting.filter_by(retired=False).all())
        task.apply_async()


    @celery.task(bind=True)
    def selector_liveprojects(self, sel_id):
        try:
            sel = db.session.query(SelectingStudent).filter_by(id=sel_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if sel is None:
            raise Ignore()

        task = group(cache_liveproject.si(sel_id, proj.id) for proj in sel.config.live_projects.all())
        task.apply_async()


    @celery.task(bind=True)
    def cache_liveproject(self, sel_id, proj_id):
        try:
            proj = db.session.query(LiveProject).filter_by(id=proj_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if proj is None:
            raise Ignore()

        # request generation of table data for this selector id and project_id
        # will force it to be generated and cached if not already present
        ajax.student.selector_liveprojects_data(sel_id, [proj_id])


    @celery.task(bind=True)
    def user_approvals(self):
        try:
            data = db.session.query(StudentData) \
                .filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_user_approval.si(student.id) for student in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_user_approval(self, user_id):
        # request generation of table data for this validation line
        ajax.user_approver.validate_data([user_id])


    @celery.task(bind=True)
    def user_corrections(self, current_user_id):
        try:
            data = db.session.query(StudentData) \
                .filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED,
                        or_(and_(StudentData.last_edit_id == None, StudentData.creator_id == current_user_id),
                            and_(StudentData.last_edit_id != None, StudentData.last_edit_id == current_user_id))).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_user_correction.si(student.id) for student in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_user_correction(self, user_id):
        # request generation of table data for this validation line
        ajax.user_approver.correction_data([user_id])


    @celery.task(bind=True)
    def project_approval(self, current_user_id):
        try:
            data = db.session.query(ProjectDescription) \
                .filter(ProjectDescription.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_project_approval.si(desc.id, current_user_id) for desc in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_project_approval(self, project_id, current_user_id):
        ajax.project_approver.validate_data([project_id], current_user_id)


    @celery.task(bind=True)
    def project_rejected(self, current_user_id):
        try:
            data = db.session.query(ProjectDescription) \
                .filter(ProjectDescription.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_project_rejected.si(desc.id, current_user_id) for desc in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_project_rejected(self, project_id, current_user_id):
        ajax.project_approver.rejected_data([project_id], current_user_id)


    @celery.task(bind=True)
    def user_account_data(self, current_user_id):
        try:
            data = db.session.query(User).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_user_account.si(user.id, current_user_id) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def user_faculty_data(self, current_user_id):
        try:
            data = db.session.query(FacultyData).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_user_faculty.si(user.id, current_user_id) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def user_student_data(self, current_user_id):
        try:
            data = db.session.query(StudentData).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_user_student.si(user.id, current_user_id) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_user_account(self, user_id, current_user_id):
        ajax.users.build_accounts_data(current_user_id, [user_id])


    @celery.task(bind=True)
    def cache_user_faculty(self, user_id, current_user_id):
        ajax.users.build_faculty_data(current_user_id, [user_id])


    @celery.task(bind=True)
    def cache_user_student(self, user_id, current_user_id):
        ajax.users.build_student_data(current_user_id, [user_id])


    @celery.task(bind=True)
    def assessor_data(self, current_user_id):
        # generate 'assessor' project data for each project belonging to active faculty
        try:
            projects = db.session.query(Project) \
                .join(User, User.id == Project.owner_id) \
                .filter(User.active == True).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_assessor_data.si(p.id, current_user_id) for p in projects)
        task.apply_async()


    @celery.task(bind=True)
    def cache_assessor_data(self, project_id, current_user_id):
        ajax.project.build_data([(project_id, None)])


    @celery.task(bind=True)
    def reporting(self):
        task = group(workload_data.si(), projects_data.si())
        task.apply_async()


    @celery.task(bind=True)
    def workload_data(self):
        # generate workload line for each active faculty member
        try:
            data = db.session.query(FacultyData) \
                .join(User, User.id == FacultyData.id) \
                .filter(User.active == True).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(workload_faculty.si(f.id) for f in data)
        task.apply_async()


    @celery.task(bind=True)
    def workload_faculty(self, user_id):
        # need both simple and non-simple versions
        ajax.reports.workload_data([user_id], False)
        ajax.reports.workload_data([user_id], True)


    @celery.task(bind=True)
    def projects_data(self):
        # generate project line for each project
        try:
            data = db.session.query(Project).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        task = group(cache_project.si(p.id) for p in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_project(self, project_id):
        ajax.project.build_data([(project_id, None)])
