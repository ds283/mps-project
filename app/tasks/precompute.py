#
# Created by David Seery on 2019-02-03.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_

from celery import group
from celery.exceptions import Ignore

from ..database import db
from ..models import User, FacultyData, StudentData, SelectingStudent, LiveProject

from ..shared.precompute import do_precompute

import app.ajax as ajax


def register_precompute_tasks(celery):

    @celery.task(bind=True)
    def student_liveprojects(self, user_id):
        # find all current selecting students
        try:
            data = db.session.query(StudentData).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if data is None:
            raise Ignore()

        task = group(selector_liveprojects.si(sel.id) for sel in data.selecting.filter_by(retired=False).all())
        task.apply_async()


    @celery.task(bind=True)
    def selector_liveprojects(self, sel_id):
        try:
            sel = db.session.query(SelectingStudent).filter_by(id=sel_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if sel is None:
            raise Ignore()

        task = group(cache_liveproject.si(sel_id, proj.id) for proj in sel.config.live_projects.all())
        task.apply_async()


    @celery.task(bind=True)
    def cache_liveproject(self, sel_id, proj_id):
        try:
            proj = db.session.query(LiveProject).filter_by(id=proj_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if proj is None:
            raise Ignore()

        # request generation of table data for this selector id and project_id
        # will force it to be generated and cached if not already present
        ajax.student.liveprojects_data(sel_id, [proj_id])


    @celery.task(bind=True)
    def user_approvals(self, user_id):
        try:
            data = db.session.query(StudentData) \
                .filter(StudentData.validation_state == StudentData.VALIDATION_QUEUED,
                        or_(and_(StudentData.last_edit_id == None, StudentData.creator_id != user_id),
                            and_(StudentData.last_edit_id != None, StudentData.last_edit_id != user_id))) \
                .all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(cache_user_approval.si(student.id) for student in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_user_approval(self, user_id):
        # request generation of table data for this validation line
        ajax.user_approver.validate_data([user_id])


    @celery.task(bind=True)
    def user_corrections(self, user_id):
        try:
            data = db.session.query(StudentData) \
                .filter(StudentData.validation_state == StudentData.VALIDATION_REJECTED,
                         or_(and_(StudentData.last_edit_id == None, StudentData.creator_id == user_id),
                             and_(StudentData.last_edit_id != None, StudentData.last_edit_id == user_id))) \
                    .all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(cache_user_correct.si(student.id) for student in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_user_correct(self, user_id):
        # request generation of table data for this validation line
        ajax.user_approver.correction_data([user_id])


    @celery.task(bind=True)
    def administrator(self, user_id):
        task = group(user_data.si(user_id),)
        task.apply_async()


    @celery.task(bind=True)
    def user_data(self, user_id):
        task = group(user_account_data.si(user_id), user_faculty_data.si(user_id), user_student_data.si(user_id))
        task.apply_async()


    @celery.task(bind=True)
    def user_account_data(self, user_id):
        try:
            data = db.session.query(User).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(cache_user_account.si(user.id, user_id) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def user_faculty_data(self, user_id):
        try:
            data = db.session.query(FacultyData).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(cache_user_faculty.si(user.id, user_id) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def user_student_data(self, user_id):
        try:
            data = db.session.query(StudentData).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(cache_user_student.si(user.id, user_id) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def cache_user_account(self, user_id, current_user_id):
        ajax.users.build_accounts_data([user_id], current_user_id)


    @celery.task(bind=True)
    def cache_user_faculty(self, user_id, current_user_id):
        ajax.users.build_faculty_data([user_id], current_user_id)


    @celery.task(bind=True)
    def cache_user_student(self, user_id, current_user_id):
        ajax.users.build_student_data([user_id], current_user_id)


    @celery.task(bind=True)
    def executive(self):
        task = group(workload_data.si(),)
        task.apply_async()


    @celery.task(bind=True)
    def workload_data(self):
        try:
            data = db.session.query(FacultyData) \
                .join(User, User.id == FacultyData.id) \
                .filter(User.active == True).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(workload_faculty.si(f.id) for f in data)
        task.apply_async()


    @celery.task(bind=True)
    def workload_faculty(self, user_id):
        ajax.exec.workload_data([user_id])


    @celery.task(bind=True)
    def periodic_precompute(self, interval_secs=10*60):
        try:
            data = db.session.query(User).filter_by(active=True).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(periodic_precompute_user.si(user.id, interval_secs) for user in data)
        task.apply_async()


    @celery.task(bind=True)
    def periodic_precompute_user(self, user_id, interval_secs):
        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if user is None:
            raise Ignore()

        if user.last_active is not None and user.last_precompute is not None:
            delta = user.last_active - user.last_precompute
            if delta.seconds > interval_secs:
                do_precompute(user)
