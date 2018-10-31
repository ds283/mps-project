#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template, redirect, url_for, flash, request, jsonify, session
from werkzeug.local import LocalProxy
from flask_security import login_required, roles_required, roles_accepted, current_user, login_user
from flask_security.utils import config_value, get_message, do_flash, \
    send_mail
from flask_security.confirmable import generate_confirmation_link
from flask_security.signals import user_registered

from collections import deque

from celery import chain, group

import app.ajax.admin.skill_groups
from ..limiter import limiter
from .actions import register_user, estimate_CATS_load
from .forms import RoleSelectForm, \
    ConfirmRegisterOfficeForm, ConfirmRegisterFacultyForm, ConfirmRegisterStudentForm, \
    EditOfficeForm, EditFacultyForm, EditStudentForm, \
    AddResearchGroupForm, EditResearchGroupForm, \
    AddDegreeTypeForm, EditDegreeTypeForm, \
    AddDegreeProgrammeForm, EditDegreeProgrammeForm, \
    AddModuleForm, EditModuleForm, \
    AddTransferableSkillForm, EditTransferableSkillForm, AddSkillGroupForm, EditSkillGroupForm, \
    AddProjectClassForm, EditProjectClassForm, AddSubmissionPeriodForm, EditSubmissionPeriodForm, \
    AddSupervisorForm, EditSupervisorForm, \
    EnrollmentRecordForm, EmailLogForm, \
    AddMessageFormFactory, EditMessageFormFactory, \
    ScheduleTypeForm, AddIntervalScheduledTask, AddCrontabScheduledTask, \
    EditIntervalScheduledTask, EditCrontabScheduledTask, \
    EditBackupOptionsForm, BackupManageForm, \
    AddRoleForm, EditRoleForm, \
    NewMatchFormFactory, RenameMatchFormFactory, CompareMatchFormFactory, \
    AddPresentationAssessmentFormFactory, EditPresentationAssessmentFormFactory, \
    AddSessionForm, EditSessionForm, \
    AddBuildingForm, EditBuildingForm, AddRoomForm, EditRoomForm, AvailabilityForm, \
    NewScheduleFormFactory, RenameScheduleFormFactory, \
    LevelSelectorForm, \
    AddFHEQLevelForm, EditFHEQLevelForm

from ..database import db
from ..models import MainConfig, User, FacultyData, StudentData, ResearchGroup,\
    DegreeType, DegreeProgramme, SkillGroup, TransferableSkill, ProjectClass, ProjectClassConfig, Supervisor, \
    EmailLog, MessageOfTheDay, DatabaseSchedulerEntry, IntervalSchedule, CrontabSchedule, \
    BackupRecord, TaskRecord, Notification, EnrollmentRecord, Role, MatchingAttempt, MatchingRecord, \
    LiveProject, SubmissionPeriodRecord, SubmissionPeriodDefinition, PresentationAssessment, \
    PresentationSession, Room, Building, ScheduleAttempt, ScheduleSlot, SubmissionRecord, \
    Module, FHEQ_Level

from ..shared.utils import get_main_config, get_current_year, home_dashboard, get_matching_dashboard_data, \
    get_root_dashboard_data, get_automatch_pclasses
from ..shared.formatters import format_size
from ..shared.backup import get_backup_config, set_backup_config, get_backup_count, get_backup_size, remove_backup
from ..shared.validators import validate_is_convenor, validate_is_admin_or_convenor, validate_match_inspector, \
    validate_using_assessment, validate_assessment, validate_schedule_inspector
from ..shared.conversions import is_integer
from ..shared.sqlalchemy import get_count
from ..shared.forms.queries import GetFHEQLevels

from ..task_queue import register_task, progress_update

from sqlalchemy.exc import SQLAlchemyError
import app.ajax as ajax

from . import admin

from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
import json
import re

from math import pi
from bokeh.plotting import figure
from bokeh.embed import components

from numpy import histogram


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


@admin.route('/create_user', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def create_user():
    """
    View function that handles creation of a user account
    """

    # check whether any active degree programmes exist, and raise an error if not
    if not DegreeProgramme.query.filter_by(active=True).first():
        flash('No degree programmes are available. '
              'Set up at least one active degree programme before adding new users.')
        return redirect(request.referrer)

    # first task is to capture the user role
    form = RoleSelectForm(request.form)

    if form.validate_on_submit():
        # get role and redirect to appropriate form
        role = form.roles.data

        if role == 'office':
            return redirect(url_for('admin.create_office', role=role))

        elif role == 'faculty':
            return redirect(url_for('admin.create_faculty', role=role))

        elif role == 'student':
            return redirect(url_for('admin.create_student', role=role))

        else:
            flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
            return redirect(url_for('admin.edit_users'))

    return render_template('security/register_role.html', role_form=form, title='Select new account role')


@admin.route('/create_office/<string:role>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def create_office(role):
    """
    Create an 'office' user
    :param role:
    :return:
    """

    # check whether role is ok
    if not (role == 'office'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterOfficeForm(request.form)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict()
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        db.session.commit()

        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, role=role,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/create_faculty/<string:role>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def create_faculty(role):
    """
    Create a 'faculty' user
    :param role:
    :return:
    """

    # check whether role is ok
    if not (role == 'faculty'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterFacultyForm(request.form)

    pane = request.args.get('pane', None)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict()
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        # insert extra data for faculty accounts

        data = FacultyData(id=user.id,
                           academic_title=form.academic_title.data,
                           use_academic_title=form.use_academic_title.data,
                           sign_off_students=form.sign_off_students.data,
                           project_capacity=form.project_capacity.data if form.enforce_capacity.data else None,
                           enforce_capacity=form.enforce_capacity.data,
                           show_popularity=form.show_popularity.data,
                           CATS_supervision=form.CATS_supervision.data,
                           CATS_marking=form.CATS_marking.data,
                           CATS_presentation=form.CATS_presentation,
                           office=form.office.data,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        if form.submit.data:
            return redirect(url_for('admin.edit_affiliations', id=data.id, create=1, pane=pane))
        elif form.save_and_exit.data:
            if pane is None or pane == 'accounts':
                return redirect(url_for('admin.edit_users'))
            elif pane == 'faculty':
                return redirect(url_for('admin.edit_users_faculty'))
            elif pane == 'students':
                return redirect(url_for('admin.edit_users_students'))
            else:
                raise RuntimeError('Unknown user pane "{pane}"'.format(pane=pane))
        else:
            raise RuntimeError('Unknown submit button in create_faculty')

    else:

        if request.method == 'GET':

            # dynamically set default project capacity
            form.project_capacity.data = current_app.config['DEFAULT_PROJECT_CAPACITY']

            form.sign_off_students.data = current_app.config['DEFAULT_SIGN_OFF_STUDENTS']
            form.enforce_capacity.data = current_app.config['DEFAULT_ENFORCE_CAPACITY']
            form.show_popularity.data = current_app.config['DEFAULT_SHOW_POPULARITY']

            form.use_academic_title.data = current_app.config['DEFAULT_USE_ACADEMIC_TITLE']

    return render_template('security/register_user.html', user_form=form, role=role, pane=pane,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/create_student/<string:role>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def create_student(role):

    # check whether role is ok
    if not (role == 'student'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterStudentForm(request.form)

    pane = request.args.get('pane', None)

    if form.validate_on_submit():

        # convert field values to a dictionary
        field_data = form.to_dict()
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        # insert extra data for student accounts

        rep_years = form.repeated_years.data
        ry = rep_years if rep_years is not None and rep_years >= 0 else 0
        data = StudentData(id=user.id,
                           exam_number=form.exam_number.data,
                           cohort=form.cohort.data,
                           programme=form.programme.data,
                           foundation_year=form.foundation_year.data,
                           repeated_years=ry,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        if pane is None or pane == 'accounts':
            return redirect(url_for('admin.edit_users'))
        elif pane == 'faculty':
            return redirect(url_for('admin.edit_users_faculty'))
        elif pane == 'students':
            return redirect(url_for('admin.edit_users_students'))
        else:
            raise RuntimeError('Unknown user pane "{pane}"'.format(pane=pane))

    else:
        if request.method == 'GET':
            # populate cohort with default value on first load
            config = get_main_config()

            if config:
                form.cohort.data = config.year

            else:
                form.cohort.data = date.today().year

    return render_template('security/register_user.html', user_form=form, role=role, pane=pane,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/edit_users')
@roles_accepted('admin', 'root')
def edit_users():
    """
    View function that handles listing of all registered users
    :return: HTML string
    """

    filter = request.args.get('filter')

    if filter is None and session.get('accounts_role_filter'):
        filter = session['accounts_role_filter']

    if filter is not None:
        session['accounts_role_filter'] = filter

    return render_template("admin/users_dashboard/accounts.html", filter=filter, pane='accounts')


@admin.route('/edit_users_students')
@roles_accepted('admin', 'root')
def edit_users_students():
    """
    View function that handles listing of all registered students
    :return: HTML string
    """

    prog_filter = request.args.get('prog_filter')

    if prog_filter is None and session.get('accounts_prog_filter'):
        prog_filter = session['accounts_prog_filter']

    if prog_filter is not None:
        session['accounts_prog_filter'] = prog_filter

    cohort_filter = request.args.get('cohort_filter')

    if cohort_filter is None and session.get('accounts_cohort_filter'):
        cohort_filter = session['accounts_cohort_filter']

    if cohort_filter is not None:
        session['accounts_cohort_filter'] = cohort_filter

    year_filter = request.args.get('year_filter')

    if year_filter is None and session.get('accounts_year_filter'):
        year_filter = session['accounts_year_filter']

    if year_filter is not None:
        session['accounts_year_filter'] = year_filter

    programmes = db.session.query(DegreeProgramme).filter(DegreeProgramme.active == True).all()
    cohort_data = db.session.query(StudentData.cohort) \
        .join(User, User.id == StudentData.id) \
        .filter(User.active == True).distinct().all()
    cohorts = [c[0] for c in cohort_data]

    return render_template("admin/users_dashboard/students.html", filter=prog_filter, pane='students',
                           prog_filter=prog_filter, cohort_filter=cohort_filter, year_filter=year_filter,
                           programmes=programmes, cohorts=sorted(cohorts))


@admin.route('/edit_users_faculty')
@roles_accepted('admin', 'root')
def edit_users_faculty():
    """
    View function that handles listing of all registered faculty
    :return: HTML string
    """

    group_filter = request.args.get('group_filter')

    if group_filter is None and session.get('accounts_group_filter'):
        group_filter = session['accounts_group_filter']

    if group_filter is not None:
        session['accounts_group_filter'] = group_filter

    pclass_filter = request.args.get('pclass_filter')

    if pclass_filter is None and session.get('accounts_pclass_filter'):
        pclass_filter = session['accounts_pclass_filter']

    if pclass_filter is not None:
        session['accounts_pclass_filter'] = pclass_filter

    groups = db.session.query(ResearchGroup).filter_by(active=True).order_by(ResearchGroup.name.asc()).all()
    pclasses = db.session.query(ProjectClass).filter_by(active=True).order_by(ProjectClass.name.asc()).all()

    return render_template("admin/users_dashboard/faculty.html", pane='faculty',
                           group_filter=group_filter, pclass_filter=pclass_filter,
                           groups=groups, pclasses=pclasses)


@admin.route('/users_ajax')
@roles_accepted('admin', 'root')
def users_ajax():
    """
    Return JSON structure representing users table
    :return:
    """

    filter = request.args.get('filter')

    if filter == 'active':
        users = User.query.filter_by(active=True).all()
    elif filter == 'inactive':
        users = User.query.filter_by(active=False).all()
    elif filter == 'student':
        users = User.query.filter(User.roles.any(Role.name == 'student')).all()
    elif filter == 'faculty':
        users = User.query.filter(User.roles.any(Role.name == 'faculty')).all()
    elif filter == 'exec':
        users = User.query.filter(User.roles.any(Role.name == 'exec')).all()
    elif filter == 'admin':
        users = User.query.filter(User.roles.any(Role.name == 'admin')).all()
    elif filter == 'root':
        users = User.query.filter(User.roles.any(Role.name == 'root')).all()
    else:
        users = User.query.all()

    return ajax.users.build_accounts_data(users)


@admin.route('/users_students_ajax')
@roles_accepted('admin', 'root')
def users_students_ajax():

    prog_filter = request.args.get('prog_filter')
    cohort_filter = request.args.get('cohort_filter')
    year_filter = request.args.get('year_filter')

    data = db.session.query(StudentData, User) \
        .join(User, User.id == StudentData.id)

    flag, prog_value = is_integer(prog_filter)
    if flag:
        data = data.filter(StudentData.programme_id == prog_value)

    flag, cohort_value = is_integer(cohort_filter)
    if flag:
        data = data.filter(StudentData.cohort == cohort_value)

    flag, year_value = is_integer(year_filter)
    if flag:
        current_year = get_current_year()
        nonf = data.filter(StudentData.foundation_year == False,
                           current_year - StudentData.cohort + 1 - StudentData.repeated_years == year_value)
        foun = data.filter(StudentData.foundation_year == True,
                           current_year - StudentData.cohort - StudentData.repeated_years == year_value)

        data = nonf.union(foun)
    elif year_filter == 'grad':
        current_year = get_current_year()
        nonf = data.filter(StudentData.foundation_year == False,
                           current_year - StudentData.cohort + 1 - StudentData.repeated_years > 4)
        foun = data.filter(StudentData.foundation_year == True,
                           current_year - StudentData.cohort - StudentData.repeated_years > 4)

        data = nonf.union(foun)

    return ajax.users.build_student_data(data.all())


@admin.route('/users_faculty_ajax')
@roles_accepted('admin', 'root')
def users_faculty_ajax():

    group_filter = request.args.get('group_filter')
    pclass_filter = request.args.get('pclass_filter')

    data = db.session.query(FacultyData, User) \
        .join(User, User.id == FacultyData.id)

    flag, group_value = is_integer(group_filter)
    if flag:
        data = data.filter(FacultyData.affiliations.any(id=group_value))

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        data = data.filter(FacultyData.enrollments.any(pclass_id=pclass_value))

    return ajax.users.build_faculty_data(data.all())


@admin.route('/make_admin/<int:id>')
@roles_accepted('admin', 'root')
def make_admin(id):
    """
    View function to add admin role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if not user.is_active:
        flash('Inactive users cannot be given admin privileges.')
        return redirect(request.referrer)

    _datastore.add_role_to_user(user, 'admin')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/remove_admin/<int:id>')
@roles_accepted('admin', 'root')
def remove_admin(id):
    """
    View function to remove admin role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('root'):
        flash('Administration privileges cannot be removed from a system administrator.')
        return redirect(request.referrer)

    _datastore.remove_role_from_user(user, 'admin')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/make_root/<int:id>')
@roles_required('root')
def make_root(id):
    """
    View function to add sysadmin=root role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if not user.is_active:
        flash('Inactive users cannot be given sysadmin privileges.')
        return redirect(request.referrer)

    _datastore.add_role_to_user(user, 'admin')
    _datastore.add_role_to_user(user, 'root')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/remove_root/<int:id>')
@roles_required('root')
def remove_root(id):
    """
    View function to remove sysadmin=root role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    _datastore.remove_role_from_user(user, 'root')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/make_exec/<int:id>')
@roles_required('admin', 'root')
def make_exec(id):

    user = User.query.get_or_404(id)

    _datastore.add_role_to_user(user, 'exec')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/remove_exec/<int:id>')
@roles_required('admin', 'root')
def remove_exec(id):

    user = User.query.get_or_404(id)

    _datastore.remove_role_from_user(user, 'exec')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/activate_user/<int:id>')
@roles_accepted('admin', 'root')
def activate_user(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    _datastore.activate_user(user)
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_user/<int:id>')
@roles_accepted('admin', 'root')
def deactivate_user(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('admin') or user.has_role('root'):
        flash('Administrative users cannot be made inactive. '
              'Remove administration status before marking the user as inactive.')
        return redirect(request.referrer)

    _datastore.deactivate_user(user)
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def edit_user(id):
    """
    View function to edit an individual user account
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    pane = request.args.get('pane', None)

    if user.has_role('office'):
        return redirect(url_for('admin.edit_office', id=id, pane=pane))

    elif user.has_role('faculty'):
        return redirect(url_for('admin.edit_faculty', id=id, pane=pane))

    elif user.has_role('student'):
        return redirect(url_for('admin.edit_student', id=id, pane=pane))

    flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
    return redirect(url_for('admin.edit_users'))


def _resend_confirm_email(user):
    confirmation_link, token = generate_confirmation_link(user)
    do_flash(*get_message('CONFIRM_REGISTRATION', email=user.email))

    user_registered.send(current_app._get_current_object(),
                         user=user, confirm_token=token)

    if config_value('SEND_REGISTER_EMAIL'):
        send_mail(config_value('EMAIL_SUBJECT_REGISTER'), user.email,
                  'welcome', user=user, confirmation_link=confirmation_link)


@admin.route('/edit_office/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def edit_office(id):

    user = User.query.get_or_404(id)
    form = EditOfficeForm(obj=user)

    form.user = user

    if form.validate_on_submit():

        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.theme = form.theme.data

        _datastore.commit()

        if resend_confirmation:
            _resend_confirm_email(user)

        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account')


@admin.route('/edit_faculty/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def edit_faculty(id):

    user = User.query.get_or_404(id)
    form = EditFacultyForm(obj=user)

    form.user = user

    data = FacultyData.query.get_or_404(id)

    pane = request.args.get('pane', default=None)

    if form.validate_on_submit():
        # determine whether to resend confirmation email
        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.theme = form.theme.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.project_capacity = form.project_capacity.data if form.enforce_capacity.data else None
        data.enforce_capacity = form.enforce_capacity.data
        data.show_popularity = form.show_popularity.data
        data.office = form.office.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        _datastore.commit()

        if resend_confirmation:
            _resend_confirm_email(user)

        if pane is None or pane == 'accounts':
            return redirect(url_for('admin.edit_users'))
        elif pane == 'faculty':
            return redirect(url_for('admin.edit_users_faculty'))
        elif pane == 'students':
            return redirect(url_for('admin.edit_users_students'))
        else:
            raise RuntimeWarning('Unknown user dashboard pane')

    else:

        # populate default values if this is the first time we are rendering the form,
        # distinguished by the method being 'GET' rather than 'POST'
        if request.method == 'GET':

            form.academic_title.data = data.academic_title
            form.use_academic_title.data = data.use_academic_title
            form.sign_off_students.data = data.sign_off_students
            form.project_capacity.data = data.project_capacity
            form.enforce_capacity.data = data.enforce_capacity
            form.show_popularity.data = data.show_popularity
            form.office.data = data.office

            if form.project_capacity.data is None and form.enforce_capacity.data:
                form.project_capacity.data = current_app.config['DEFAULT_PROJECT_CAPACITY']

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account',
                           pane=pane)


@admin.route('/edit_student/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def edit_student(id):

    user = User.query.get_or_404(id)
    form = EditStudentForm(obj=user)

    form.user = user

    data = StudentData.query.get_or_404(id)

    pane = request.args.get('pane', default=None)

    if form.validate_on_submit():

        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.theme = form.theme.data

        rep_years = form.repeated_years.data
        ry = rep_years if rep_years is not None and rep_years >= 0 else 0

        data.foundation_year = form.foundation_year.data
        data.exam_number = form.exam_number.data
        data.cohort = form.cohort.data
        data.repeated_years = ry
        data.programme_id = form.programme.data.id
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        _datastore.commit()

        if resend_confirmation:
            _resend_confirm_email(user)

        if pane is None or pane == 'accounts':
            return redirect(url_for('admin.edit_users'))
        elif pane == 'faculty':
            return redirect(url_for('admin.edit_users_faculty'))
        elif pane == 'students':
            return redirect(url_for('admin.edit_users_students'))
        else:
            raise RuntimeWarning('Unknown user dashboard pane')

    else:

        # populate default values if this is the first time we are rendering the form,
        # distinguished by the method being 'GET' rather than 'POST'
        if request.method == 'GET':
            form.foundation_year.data = data.foundation_year
            form.exam_number.data = data.exam_number
            form.cohort.data = data.cohort
            form.repeated_years.data = data.repeated_years
            form.programme.data = data.programme

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account',
                           pane=pane)


@admin.route('/edit_affiliations/<int:id>')
@roles_accepted('admin', 'root')
def edit_affiliations(id):
    """
    View to edit research group affiliations for a faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    research_groups = ResearchGroup.query.filter_by(active=True)

    create = request.args.get('create', default=None)
    pane = request.args.get('pane', default=None)

    return render_template('admin/edit_affiliations.html', user=user, data=data, research_groups=research_groups,
                           create=create, pane=pane)


@admin.route('/edit_enrollments/<int:id>')
@roles_accepted('admin', 'root')
def edit_enrollments(id):
    """
    View to edit project class enrollments for a faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    project_classes = ProjectClass.query.filter_by(active=True)

    create = request.args.get('create', default=None)
    pane = request.args.get('pane', default=None)

    return render_template('admin/edit_enrollments.html', user=user, data=data, project_classes=project_classes,
                           create=create, pane=pane)


@admin.route('/edit_enrollment/<int:id>/<int:returnid>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_enrollment(id, returnid):
    """
    Edit enrollment details
    :param id:
    :return:
    """

    # check logged-in user is administrator or a convenor for the project
    record = EnrollmentRecord.query.get_or_404(id)

    if not validate_is_convenor(record.pclass):
        return redirect(request.referrer)

    form = EnrollmentRecordForm(obj=record)

    pane = request.args.get('pane', None)

    if form.validate_on_submit():

        record.supervisor_state = form.supervisor_state.data
        record.supervisor_reenroll = None if record.supervisor_state != EnrollmentRecord.SUPERVISOR_SABBATICAL \
            else form.supervisor_reenroll.data
        record.supervisor_comment = form.supervisor_comment.data

        record.marker_state = form.marker_state.data
        record.marker_reenroll = None if record.marker_state != EnrollmentRecord.MARKER_SABBATICAL \
            else form.marker_reenroll.data
        record.marker_comment = form.marker_comment.data

        old_presentations_state = record.presentations_state
        record.presentations_state = form.presentations_state.data
        record.presentations_reenroll = None if record.presentations_state != EnrollmentRecord.PRESENTATIONS_SABBATICAL \
            else form.presentations_reenroll.data
        record.presentations_comment = form.presentations_comment.data

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        db.session.commit()

        # if enrollment state has changed for presentations, check whether we need to adjust our
        # availability status for any presentation assessment events.
        # To do that we kick off a background task via celery.
        if old_presentations_state != record.presentations_state:
            celery = current_app.extensions['celery']
            adjust_task = celery.tasks['app.tasks.availability.adjust']

            adjust_task.apply_async(args=(record.id, get_current_year()))

        if returnid == 0:
            return redirect(url_for('admin.edit_enrollments', id=record.owner_id, pane=pane))
        elif returnid == 1:
            return redirect(url_for('convenor.faculty', id=record.pclass.id))
        else:
            return home_dashboard()

    return render_template('admin/edit_enrollment.html', record=record, form=form, returnid=returnid, pane=pane)


@admin.route('/add_affiliation/<int:userid>/<int:groupid>')
@roles_accepted('admin', 'root')
def add_affiliation(userid, groupid):
    """
    View to add a research group affiliation to a faculty member
    :param userid:
    :param groupid:
    :return:
    """

    data = FacultyData.query.get_or_404(userid)
    group = ResearchGroup.query.get_or_404(groupid)

    if group not in data.affiliations:
        data.add_affiliation(group, autocommit=True)

    return redirect(request.referrer)


@admin.route('/remove_affiliation/<int:userid>/<int:groupid>')
@roles_accepted('admin', 'root')
def remove_affiliation(userid, groupid):
    """
    View to remove a research group affiliation to a faculty member
    :param userid:
    :param groupid:
    :return:
    """

    data = FacultyData.query.get_or_404(userid)
    group = ResearchGroup.query.get_or_404(groupid)

    if group in data.affiliations:
        data.remove_affiliation(group, autocommit=True)

    return redirect(request.referrer)


@admin.route('/add_enrollment/<int:userid>/<int:pclassid>')
@roles_accepted('admin', 'root')
def add_enrollment(userid, pclassid):
    """
    View to add a project class enrollment to a faculty member
    :param userid:
    :param pclassid:
    :return:
    """

    data = FacultyData.query.get_or_404(userid)
    pclass = ProjectClass.query.get_or_404(pclassid)

    if not data.is_enrolled(pclass):
        data.add_enrollment(pclass)

    return redirect(request.referrer)


@admin.route('/remove_enrollment/<int:userid>/<int:pclassid>')
@roles_accepted('admin', 'root')
def remove_enrollment(userid, pclassid):
    """
    View to remove a project class enrollment from a faculty member
    :param userid:
    :param pclassid:
    :return:
    """

    data = FacultyData.query.get_or_404(userid)
    pclass = ProjectClass.query.get_or_404(pclassid)

    if data.is_enrolled(pclass):
        data.remove_enrollment(pclass)

    return redirect(request.referrer)


@admin.route('/edit_groups')
@roles_required('root')
def edit_groups():
    """
    View function that handles listing of all registered research groups
    :return:
    """

    return render_template('admin/edit_groups.html')


@admin.route('/groups_ajax', methods=['GET', 'POST'])
@roles_required('root')
def groups_ajax():
    """
    Ajax data point for Edit Groups view

    :return:
    """

    groups = ResearchGroup.query.all()
    return ajax.admin.groups_data(groups)


@admin.route('/add_group', methods=['GET', 'POST'])
@roles_required('root')
def add_group():
    """
    View function to add a new research group
    :return:
    """

    form = AddResearchGroupForm(request.form)

    if form.validate_on_submit():
        url = form.website.data
        if not re.match(r'http(s?)\:', url):
            url = 'http://' + url
        r = urlsplit(url)     # canonicalize

        group = ResearchGroup(abbreviation=form.abbreviation.data,
                              name=form.name.data,
                              colour=form.colour.data,
                              website=r.geturl(),
                              active=True,
                              creator_id=current_user.id,
                              creation_timestamp=datetime.now())
        db.session.add(group)
        db.session.commit()

        return redirect(url_for('admin.edit_groups'))

    return render_template('admin/edit_group.html', group_form=form, title='Add new research group')


@admin.route('/edit_group/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_group(id):
    """
    View function to edit an existing research group
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    form = EditResearchGroupForm(obj=group)

    form.group = group

    if form.validate_on_submit():
        url = form.website.data
        if not re.match(r'http(s?)\:', url):
            url = 'http://' + url
        r = urlsplit(url)     # canonicalize

        group.abbreviation = form.abbreviation.data
        group.name = form.name.data
        group.colour = form.colour.data
        group.website = r.geturl()
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_groups'))

    return render_template('admin/edit_group.html', group_form=form, group=group, title='Edit research group')


@admin.route('/activate_group/<int:id>')
@roles_required('root')
def activate_group(id):
    """
    View to make a research group active
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    group.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_group/<int:id>')
@roles_required('root')
def deactivate_group(id):
    """
    View to make a research group inactive
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    group.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_degrees_types')
@roles_required('root')
def edit_degree_types():
    """
    View for editing degree types
    :return:
    """
    return render_template('admin/degree_types/edit_degrees.html', subpane='degrees')


@admin.route('/edit_degree_programmes')
@roles_required('root')
def edit_degree_programmes():
    """
    View for editing degree programmes
    :return:
    """
    return render_template('admin/degree_types/edit_programmes.html', subpane='programmes')


@admin.route('/edit_modules')
@roles_required('root')
def edit_modules():
    """
    View for editing modules
    :return:
    """
    return render_template('admin/degree_types/edit_modules.html', subpane='modules')


@admin.route('/edit_levels')
@roles_required('root')
def edit_levels():
    """
    View for editing FHEQ levels
    :return:
    """
    return render_template('admin/degree_types/edit_levels.html', subpane='levels')


@admin.route('/edit_levels_ajax')
@roles_required('root')
def edit_levels_ajax():
    """
    AJAX data point for FHEQ levels table
    :return: 
    """
    levels = FHEQ_Level.query.all()
    return ajax.admin.FHEQ_levels_data(levels)


@admin.route('/degree_types_ajax')
@roles_required('root')
def degree_types_ajax():
    """
    Ajax data point for degree type table
    :return:
    """
    types = DegreeType.query.all()
    return ajax.admin.degree_types_data(types)


@admin.route('/degree_programmes_ajax')
@roles_required('root')
def degree_programmes_ajax():
    """
    Ajax data point for degree programmes tables
    :return:
    """
    programmes = DegreeProgramme.query.all()
    levels = FHEQ_Level.query.filter_by(active=True).order_by(FHEQ_Level.name.asc()).all()
    return ajax.admin.degree_programmes_data(programmes, levels)


@admin.route('/modules_ajax')
@roles_required('root')
def modules_ajax():
    """
    Ajax data point for module table
    :return:
    """
    modules = Module.query.all()
    return ajax.admin.modules_data(modules)


@admin.route('/add_type', methods=['GET', 'POST'])
@roles_required('root')
def add_degree_type():
    """
    View to create a new degree type
    :return:
    """
    form = AddDegreeTypeForm(request.form)

    if form.validate_on_submit():
        degree_type = DegreeType(name=form.name.data,
                                 abbreviation=form.abbreviation.data,
                                 colour=form.colour.data,
                                 active=True,
                                 creator_id=current_user.id,
                                 creation_timestamp=datetime.now())
        db.session.add(degree_type)
        db.session.commit()

        return redirect(url_for('admin.edit_degree_types'))

    return render_template('admin/degree_types/edit_degree.html', type_form=form, title='Add new degree type')


@admin.route('/edit_type/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_degree_type(id):
    """
    View to edit a degree type
    :param id:
    :return:
    """
    type = DegreeType.query.get_or_404(id)
    form = EditDegreeTypeForm(obj=type)

    form.degree_type = type

    if form.validate_on_submit():
        type.name = form.name.data
        type.abbreviation = form.abbreviation.data
        type.colour = form.colour.data
        type.last_edit_id = current_user.id
        type.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_degree_types'))

    return render_template('admin/degree_types/edit_degree.html', type_form=form, type=type, title='Edit degree type')


@admin.route('/make_type_active/<int:id>')
@roles_required('root')
def activate_degree_type(id):
    """
    Make a degree type active
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_type_inactive/<int:id>')
@roles_required('root')
def deactivate_degree_type(id):
    """
    Make a degree type inactive
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/add_programme', methods=['GET', 'POST'])
@roles_required('root')
def add_degree_programme():
    """
    View to create a new degree programme
    :return:
    """
    # check whether any active degree types exist, and raise an error if not
    if not DegreeType.query.filter_by(active=True).first():
        flash('No degree types are available. Set up at least one active degree type before adding a '
              'degree programme.', 'error')
        return redirect(request.referrer)

    form = AddDegreeProgrammeForm(request.form)

    if form.validate_on_submit():
        degree_type = form.degree_type.data
        programme = DegreeProgramme(name=form.name.data,
                                    abbreviation=form.abbreviation.data,
                                    show_type=form.show_type.data,
                                    active=True,
                                    type_id=degree_type.id,
                                    creator_id=current_user.id,
                                    creation_timestamp=datetime.now())
        db.session.add(programme)
        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/degree_types/edit_programme.html', programme_form=form, title='Add new degree programme')


@admin.route('/edit_programme/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_degree_programme(id):
    """
    View to edit a degree programme
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    form = EditDegreeProgrammeForm(obj=programme)

    form.programme = programme

    if form.validate_on_submit():
        programme.name = form.name.data
        programme.abbreviation = form.abbreviation.data
        programme.show_type = form.show_type.data
        programme.type_id = form.degree_type.data.id
        programme.last_edit_id = current_user.id
        programme.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/degree_types/edit_programme.html', programme_form=form, programme=programme,
                           title='Edit degree programme')


@admin.route('/activate_programme/<int:id>')
@roles_required('root')
def activate_degree_programme(id):
    """
    Make a degree programme active
    :param id:
    :return:
    """
    programme = DegreeProgramme.query.get_or_404(id)
    programme.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_programme/<int:id>')
@roles_required('root')
def deactivate_degree_programme(id):
    """
    Make a degree programme inactive
    :param id:
    :return:
    """
    programme = DegreeProgramme.query.get_or_404(id)
    programme.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/attach_modules/<int:id>/<int:level_id>', methods=['GET', 'POST'])
@admin.route('/attach_modules/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def attach_modules(id, level_id=None):
    """
    Attach modules to a degree programme
    :param id:
    :return:
    """
    programme = DegreeProgramme.query.get_or_404(id)

    form = LevelSelectorForm(request.form)

    if not form.validate_on_submit() and request.method == 'GET':
        if level_id is None:
            form.selector.data = FHEQ_Level.query \
                .filter(FHEQ_Level.active == True) \
                .order_by(FHEQ_Level.name.asc()).first()
        else:
            form.selector.data = FHEQ_Level.query \
                .filter(FHEQ_Level.active == True, FHEQ_Level.id == level_id).first()

    # get list of modules for the current level_id
    if form.selector.data is not None:
        modules = Module.query \
            .filter(Module.active == True,
                    Module.level_id == form.selector.data.id) \
            .order_by(Module.semester.asc(), Module.name.asc())
    else:
        modules = []

    level_id = form.selector.data.id if form.selector.data is not None else None

    levels = FHEQ_Level.query.filter_by(active=True).order_by(FHEQ_Level.name.asc()).all()

    return render_template('admin/degree_types/attach_modules.html', prog=programme, modules=modules, form=form,
                           level_id=level_id, levels=levels, title='Attach modules')


@admin.route('/attach_module/<int:prog_id>/<int:mod_id>/<int:level_id>')
@roles_required('root')
def attach_module(prog_id, mod_id, level_id):
    """
    Attach a module to a degree programme
    :param prog_id:
    :param mod_id:
    :return:
    """
    programme = DegreeProgramme.query.get_or_404(prog_id)
    module = Module.query.get_or_404(mod_id)

    if module not in programme.modules:
        programme.modules.append(module)
        db.session.commit()

    return redirect(url_for('admin.attach_modules', id=prog_id, level_id=level_id))


@admin.route('/detach_module/<int:prog_id>/<int:mod_id>/<int:level_id>')
@roles_required('root')
def detach_module(prog_id, mod_id, level_id):
    """
    Detach a module from a degree programme
    :param prog_id:
    :param mod_id:
    :return:
    """
    programme = DegreeProgramme.query.get_or_404(prog_id)
    module = Module.query.get_or_404(mod_id)

    if module in programme.modules:
        programme.modules.remove(module)
        db.session.commit()

    return redirect(url_for('admin.attach_modules', id=prog_id, level_id=level_id))


@admin.route('/add_level', methods=['GET', 'POST'])
@roles_required('root')
def add_level():
    """
    Add a new FHEQ level record
    :return:
    """
    form = AddFHEQLevelForm(request.form)

    if form.validate_on_submit():
        level = FHEQ_Level(name=form.name.data,
                           short_name=form.short_name.data,
                           colour=form.colour.data,
                           active=True,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now(),
                           last_edit_id=None,
                           last_edit_timestamp=None)

        db.session.add(level)
        db.session.commit()

        return redirect(url_for('admin.edit_levels'))

    return render_template('admin/degree_types/edit_level.html', form=form, title='Add new FHEQ Level')


@admin.route('/edit_level/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_level(id):
    """
    Edit an existing FHEQ level record
    :return:
    """
    level = FHEQ_Level.query.get_or_404(id)
    form = EditFHEQLevelForm(obj=level)
    form.level = level

    if form.validate_on_submit():
        level.name = form.name.data
        level.short_name = form.short_name.data
        level.colour = form.colour.data
        level.last_edit_id = current_user.id
        level.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_levels'))

    return render_template('admin/degree_types/edit_level.html', form=form, level=level, title='Edit FHEQ Level')


@admin.route('/activate_level/<int:id>')
@roles_accepted('root')
def activate_level(id):
    """
    Make an FHEQ level active
    :param id:
    :return:
    """
    level = FHEQ_Level.query.get_or_404(id)
    level.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_level/<int:id>')
@roles_accepted('root;')
def deactivate_level(id):
    """
    Make an FHEQ level inactive
    :param id:
    :return:
    """
    skill = FHEQ_Level.query.get_or_404(id)
    skill.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/add_module', methods=['GET', 'POST'])
@roles_required('root')
def add_module():
    """
    Add a new module record
    :return:
    """
    # check whether any active FHEQ levels exist, and raise an error if not
    if not FHEQ_Level.query.filter_by(active=True).first():
        flash('No FHEQ Levels are available. Set up at least one active FHEQ Level before adding a '
              'module.', 'error')
        return redirect(request.referrer)

    form = AddModuleForm(request.form)

    if form.validate_on_submit():
        module = Module(code=form.code.data,
                        name=form.name.data,
                        level=form.level.data,
                        semester=form.semester.data,
                        first_taught=get_current_year(),
                        last_taught=None,
                        creator_id=current_user.id,
                        creation_timestamp=datetime.now(),
                        last_edit_id=None,
                        last_edit_timestamp=None)

        db.session.add(module)
        db.session.commit()

        return redirect(url_for('admin.edit_modules'))

    return render_template('admin/degree_types/edit_module.html', form=form, title='Add new module')


@admin.route('/edit_module/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_module(id):
    """
    id labels a Module
    :param id:
    :return:
    """
    module = Module.query.get_or_404(id)

    if not module.active:
        flash('Module "{code} {name}" cannot be edited because it is '
              'retired.'.format(code=module.code, name=module.name), 'info')
        return redirect(request.referrer)

    form = EditModuleForm(obj=module)
    form.module = module

    if form.validate_on_submit():
        module.code = form.code.data
        module.name = form.name.data
        module.level = form.level.data
        module.semester = form.semester.data
        module.last_edit_id = current_user.id
        module.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_modules'))

    return render_template('admin/degree_types/edit_module.html', form=form,
                           title='Edit module', module=module)


@admin.route('/retire_module/<int:id>')
@roles_required('root')
def retire_module(id):
    """
    Retire a current module
    :param id:
    :return:
    """
    module = Module.query.get_or_404(id)
    module.retire()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/unretire_module/<int:id>')
@roles_required('root')
def unretire_module(id):
    """
    Un-retire a current module
    :param id:
    :return:
    """
    module = Module.query.get_or_404(id)
    module.unretire()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_skills')
@roles_accepted('admin', 'root', 'faculty')
def edit_skills():
    """
    View for edit skills
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    return render_template('admin/transferable_skills/edit_skills.html', subpane='skills')


@admin.route('/skills_ajax', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def skills_ajax():
    """
    Ajax data point for transferable skills table
    :return:
    """
    if not validate_is_admin_or_convenor():
        return jsonify({})

    skills = TransferableSkill.query.all()
    return ajax.admin.skills_data(skills)


@admin.route('/add_skill', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def add_skill():
    """
    View to create a new transferable skill
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    # check whether any skill groups exist, and raise an error if not
    if not SkillGroup.query.filter_by(active=True).first():
        flash('No skill groups are available. Set up at least one active skill group before adding a '
              'transferable skill.', 'error')
        return redirect(request.referrer)

    form = AddTransferableSkillForm(request.form)

    if form.validate_on_submit():
        skill = TransferableSkill(name=form.name.data,
                                  group=form.group.data,
                                  active=True,
                                  creator_id=current_user.id,
                                  creation_timestamp=datetime.now())
        db.session.add(skill)
        db.session.commit()

        return redirect(url_for('admin.edit_skills'))

    return render_template('admin/transferable_skills/edit_skill.html',
                           skill_form=form, title='Add new transferable skill')


@admin.route('/edit_skill/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def edit_skill(id):
    """
    View to edit a transferable skill
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    form = EditTransferableSkillForm(obj=skill)

    form.skill = skill

    if form.validate_on_submit():
        skill.name = form.name.data
        skill.group = form.group.data
        skill.last_edit_id = current_user.id
        skill.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_skills'))

    return render_template('admin/transferable_skills/edit_skill.html',
                           skill_form=form, skill=skill, title='Edit transferable skill')


@admin.route('/activate_skill/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def activate_skill(id):
    """
    Make a transferable skill active
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    skill.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_skill/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def deactivate_skill(id):
    """
    Make a transferable skill inactive
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    skill.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_skill_groups')
@roles_accepted('admin', 'root', 'faculty')
def edit_skill_groups():
    """
    View for editing skill groups
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    return render_template('admin/transferable_skills/edit_skill_groups.html', subpane='groups')


@admin.route('/skill_groups_ajax', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def skill_groups_ajax():
    """
    Ajax data point for skill groups table
    :return:
    """
    if not validate_is_admin_or_convenor():
        return jsonify({})

    groups = SkillGroup.query.all()
    return app.ajax.admin.skill_groups.skill_groups_data(groups)


@admin.route('/add_skill_group', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def add_skill_group():
    """
    Add a new skill group
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    form = AddSkillGroupForm(request.form)

    if form.validate_on_submit():
        skill = SkillGroup(name=form.name.data,
                           colour=form.colour.data,
                           add_group=form.add_group.data,
                           active=True,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())
        db.session.add(skill)
        db.session.commit()

        return redirect(url_for('admin.edit_skill_groups'))

    return render_template('admin/transferable_skills/edit_skill_group.html',
                           group_form=form, title='Add new transferable skill group')


@admin.route('/edit_skill_group/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def edit_skill_group(id):
    """
    Edit an existing skill group
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    group = SkillGroup.query.get_or_404(id)
    form = EditSkillGroupForm(obj=group)

    form.group = group

    if form.validate_on_submit():
        group.name = form.name.data
        group.colour = form.colour.data
        group.add_group = form.add_group.data
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_skill_groups'))

    return render_template('admin/transferable_skills/edit_skill_group.html', group=group,
                           group_form=form, title='Edit transferable skill group')


@admin.route('/activate_skill_group/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def activate_skill_group(id):
    """
    Make a transferable skill group active
    :param id:
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    group = SkillGroup.query.get_or_404(id)
    group.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_skill_group/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def deactivate_skill_group(id):
    """
    Make a transferable skill group inactive
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor():
        return home_dashboard()

    group = SkillGroup.query.get_or_404(id)
    group.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_project_classes')
@roles_required('root')
def edit_project_classes():
    """
    Provide list and edit view for project classes
    :return:
    """
    return render_template('admin/edit_project_classes.html')


@admin.route('/pclasses_ajax', methods=['GET', 'POST'])
@roles_required('root')
def pclasses_ajax():
    """
    Ajax data point for project class tables
    :return:
    """
    classes = ProjectClass.query.all()
    return ajax.admin.pclasses_data(classes)


@admin.route('/add_pclass', methods=['GET', 'POST'])
@roles_required('root')
def add_pclass():
    """
    Create a new project class
    :return:
    """
    # check whether any active degree types exist, and raise an error if not
    if not DegreeType.query.filter_by(active=True).first():
        flash('No degree types are available. Set up at least one active degree type before adding a project class.')
        return redirect(request.referrer)

    form = AddProjectClassForm(request.form)

    if form.validate_on_submit():

        # make sure convenor and coconvenors don't have overlap
        coconvenors = form.coconvenors.data
        if form.convenor.data in coconvenors:
            coconvenors.remove(form.convenor.data)

        # insert a record for this project class
        data = ProjectClass(name=form.name.data,
                            abbreviation=form.abbreviation.data,
                            colour=form.colour.data,
                            do_matching=form.do_matching.data,
                            number_assessors=form.number_assessors.data,
                            year=form.year.data,
                            extent=form.extent.data,
                            require_confirm=form.require_confirm.data,
                            supervisor_carryover=form.supervisor_carryover.data,
                            submissions=form.submissions.data,
                            uses_marker=form.uses_marker.data,
                            uses_presentations=form.uses_presentations.data,
                            convenor=form.convenor.data,
                            coconvenors=coconvenors,
                            selection_open_to_all=form.selection_open_to_all.data,
                            programmes=form.programmes.data,
                            initial_choices=form.initial_choices.data,
                            switch_choices=form.switch_choices.data,
                            active=True,
                            CATS_supervision=form.CATS_supervision.data,
                            CATS_marking=form.CATS_marking.data,
                            CATS_presentation=form.CATS_presentation.data,
                            keep_hourly_popularity=form.keep_hourly_popularity.data,
                            keep_daily_popularity=form.keep_daily_popularity.data,
                            creator_id=current_user.id,
                            creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.flush()
        data.convenor.add_convenorship(data)

        # generate a corresponding configuration record for the current academic year
        current_year = get_current_year()

        config = ProjectClassConfig(year=current_year,
                                    pclass_id=data.id,
                                    convenor_id=data.convenor_id,
                                    requests_issued=False,
                                    live=False,
                                    selection_closed=False,
                                    CATS_supervision=data.CATS_supervision,
                                    CATS_marking=data.CATS_marking,
                                    CATS_presentation=data.CATS_presentation,
                                    creator_id=current_user.id,
                                    creation_timestamp=datetime.now(),
                                    submission_period=1)
        db.session.add(config)
        db.session.flush()

        for template in config.template_periods.all():
            period = SubmissionPeriodRecord(config_id=config.id,
                                            name=template.name,
                                            has_presentation=template.has_presentation,
                                            lecture_capture=template.lecture_capture,
                                            retired=False,
                                            submission_period=template.period,
                                            feedback_open=False,
                                            feedback_id=None,
                                            feedback_timestamp=None,
                                            feedback_deadline=None,
                                            closed=False,
                                            closed_id=None,
                                            closed_timestamp=None)
            db.session.add(period)

        db.session.commit()
        data.validate_presentations()

        return redirect(url_for('admin.edit_project_classes'))

    else:

        if request.method == 'GET':
            form.number_assessors.data = current_app.config['DEFAULT_ASSESSORS']
            form.uses_marker.data = True

    return render_template('admin/edit_project_class.html', pclass_form=form, title='Add new project class')


@admin.route('/edit_pclass/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_pclass(id):
    """
    Edit properties for an existing project class
    :param id:
    :return:
    """
    data = ProjectClass.query.get_or_404(id)
    form = EditProjectClassForm(obj=data)

    form.project_class = data

    # remember old convenor
    old_convenor = data.convenor

    if form.validate_on_submit():

        # make sure convenor and coconvenors don't have overlap
        coconvenors = form.coconvenors.data
        if form.convenor.data in coconvenors:
            coconvenors.remove(form.convenor.data)

        data.name = form.name.data
        data.abbreviation = form.abbreviation.data
        data.year = form.year.data
        data.colour = form.colour.data
        data.do_matching = form.do_matching.data
        data.number_assessors = form.number_assessors.data
        data.extent = form.extent.data
        data.require_confirm = form.require_confirm.data
        data.supervisor_carryover = form.supervisor_carryover.data
        data.uses_marker = form.uses_marker.data
        data.uses_presentations = form.uses_presentations.data
        data.convenor = form.convenor.data
        data.coconvenors = coconvenors
        data.selection_open_to_all = form.selection_open_to_all.data
        data.programmes = form.programmes.data
        data.initial_choices = form.initial_choices.data
        data.switch_choices = form.switch_choices.data
        data.CATS_supervision = form.CATS_supervision.data
        data.CATS_marking = form.CATS_marking.data
        data.CATS_presentation = form.CATS_presentation.data
        data.keep_hourly_popularity = form.keep_hourly_popularity.data
        data.keep_daily_popularity = form.keep_daily_popularity.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        if data.convenor.id != old_convenor.id:

            old_convenor.remove_convenorship(data)
            data.convenor.add_convenorship(data)

        db.session.commit()
        data.validate_presentations()

        return redirect(url_for('admin.edit_project_classes'))

    else:

        if request.method == 'GET':
            if form.number_assessors.data is None:
                form.number_assessors.data = current_app.config['DEFAULT_ASSESSORS']
            if form.uses_marker.data is None:
                form.uses_marker.data = True

    return render_template('admin/edit_project_class.html', pclass_form=form, pclass=data,
                           title='Edit project class')


@admin.route('/activate_pclass/<int:id>')
@roles_required('root')
def activate_pclass(id):
    """
    Make a project class active
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_pclass/<int:id>')
@roles_required('root')
def deactivate_pclass(id):
    """
    Make a project class inactive
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_submission_periods/<int:id>')
@roles_required('root')
def edit_submission_periods(id):
    """
    Set up submission periods for a given project class
    incorporated
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    return render_template('admin/edit_periods.html', pclass=data)


@admin.route('/submission_periods_ajax/<int:id>')
@roles_required('root')
def submission_periods_ajax(id):
    """
    Return AJAX data for the submission periods table
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    periods = data.periods.all()

    return ajax.admin.periods_data(periods)


@admin.route('/add_period/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def add_period(id):
    """
    Add a new submission period configuration to the given project class
    :param id:
    :return:
    """

    pclass = ProjectClass.query.get_or_404(id)
    form = AddSubmissionPeriodForm(form=request.form)

    if form.validate_on_submit():
        data = SubmissionPeriodDefinition(owner_id=pclass.id,
                                          period=pclass.submissions+1,
                                          name=form.name.data,
                                          has_presentation=form.has_presentation.data,
                                          lecture_capture=form.lecture_capture.data,
                                          creator_id=current_user.id,
                                          creation_timestamp=datetime.now())
        pclass.periods.append(data)

        db.session.commit()
        pclass.validate_presentations()

        return redirect(url_for('admin.edit_submission_periods', id=pclass.id))

    return render_template('admin/edit_period.html', form=form, pclass_id=pclass.id,
                           title='Add new submission period')


@admin.route('/edit_period/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_period(id):
    """
    Edit an existing submission period configuration
    :param id:
    :return:
    """

    data = SubmissionPeriodDefinition.query.get_or_404(id)
    form = EditSubmissionPeriodForm(obj=data)

    if form.validate_on_submit():
        data.name = form.name.data
        data.has_presentation = form.has_presentation.data
        data.lecture_capture = form.lecture_capture.data

        data.last_edit_id = current_user.id,
        data.last_edit_timestamp = datetime.now()

        db.session.commit()
        data.owner.validate_presentations()

        return redirect(url_for('admin.edit_submission_periods', id=data.owner.id))

    return render_template('admin/edit_period.html', form=form, period=data,
                           title='Edit submission period')


@admin.route('/delete_period/<int:id>')
@roles_required('root')
def delete_period(id):
    """
    Delete a submission period configuration
    :param id:
    :return:
    """

    data = SubmissionPeriodDefinition.query.get_or_404(id)
    pclass = data.owner

    db.session.delete(data)
    db.session.commit()
    pclass.validate_presentations()

    return redirect(request.referrer)



@admin.route('/edit_supervisors')
@roles_accepted('admin', 'root', 'faculty')
def edit_supervisors():
    """
    View to list and edit supervisory roles
    :return:
    """

    return render_template('admin/edit_supervisors.html')


@admin.route('/supervisors_ajax', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def supervisors_ajax():
    """
    Ajax datapoint for supervisors table
    :return:
    """

    roles = Supervisor.query.all()
    return ajax.admin.supervisors_data(roles)


@admin.route('/add_supervisor', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def add_supervisor():
    """
    Create a new supervisory role
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    form = AddSupervisorForm(request.form)

    if form.validate_on_submit():
        data = Supervisor(name=form.name.data,
                          abbreviation=form.abbreviation.data,
                          colour=form.colour.data,
                          active=True,
                          creator_id=current_user.id,
                          creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_supervisors'))

    return render_template('admin/edit_supervisor.html', supervisor_form=form, title='Add new supervisory role')


@admin.route('/edit_supervisor/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def edit_supervisor(id):
    """
    Edit a supervisory role
    :param id:
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    form = EditSupervisorForm(obj=data)

    form.supervisor = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.abbreviation = form.abbreviation.data
        data.colour = form.colour.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_supervisors'))

    return render_template('admin/edit_supervisor.html', supervisor_form=form, role=data,
                           title='Edit supervisory role')


@admin.route('/activate_supervisor/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def activate_supervisor(id):
    """
    Make a supervisor active
    :param id:
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_supervisor/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def deactivate_supervisor(id):
    """
    Make a supervisor inactive
    :param id:
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/confirm_global_rollover')
@roles_required('root')
def confirm_global_rollover():
    """
    Show confirmation box for global advance of academic year
    :return:
    """

    config_list, config_warning, current_year, rollover_ready, matching_ready, \
        rollover_in_progress, assessments, messages = get_root_dashboard_data()

    if not rollover_ready:
        flash('Can not initiate a rollover of the academic year because not all project classes are ready', 'info')
        return redirect(request.referrer)

    if rollover_in_progress:
        flash('Can not initiate a rollover of the academic year because one is already in progress', 'info')
        return redirect(request.referrer)

    next_year = get_current_year() + 1

    title = 'Global rollover to {yeara}&ndash;{yearb}'.format(yeara=next_year, yearb=next_year + 1)
    panel_title = 'Global rollover of academic year to {yeara}&ndash;{yearb}'.format(yeara=next_year,
                                                                                     yearb=next_year + 1)
    action_url = url_for('admin.perform_global_rollover')
    message = '<p>Please confirm that you wish to advance the global academic year to ' \
              '{yeara}&ndash;{yearb}.</p>' \
              '<p>This action cannot be undone.</p>'.format(yeara=next_year, yearb=next_year + 1)
    submit_label = 'Rollover to {yr}'.format(yr=next_year)

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_global_rollover')
@roles_required('root')
def perform_global_rollover():
    """
    Globally advance the academic year
    (doesn't actually do anything directly; the complex parts of rollover are done
    for each project class at a time decided by its convenor or an administrator)
    :return:
    """

    config_list, config_warning, current_year, rollover_ready, matching_ready, \
        rollover_in_progress, assessments, messages = get_root_dashboard_data()

    if not rollover_ready:
        flash('Can not initiate a rollover of the academic year because not all project classes are ready', 'info')
        return redirect(request.referrer)

    if rollover_in_progress:
        flash('Can not initiate a rollover of the academic year because one is already in progress', 'info')
        return redirect(request.referrer)

    next_year = get_current_year() + 1

    try:
        new_year = MainConfig(year=next_year)
        db.session.add(new_year)

        db.session.query(MatchingAttempt).filter_by(selected=False).delete()
        db.session.commit()
    except SQLAlchemyError:
        flash('Could not complete rollover due to database error. Please check the logs.', 'error')
        db.session.rollback()

    return home_dashboard()


@admin.route('/edit_roles')
@roles_required('root')
def edit_roles():
    """
    Display list of roles
    :return:
    """

    return render_template('admin/edit_roles.html')


@admin.route('/roles_ajax')
@roles_required('root')
def roles_ajax():
    """
    Ajax data point for roles list
    :return:
    """

    roles = db.session.query(Role).all()
    return ajax.admin.roles_data(roles)


@admin.route('/add_role', methods=['GET', 'POST'])
@roles_required('root')
def add_role():
    """
    Add a new user role
    :return:
    """

    form = AddRoleForm(request.form)

    if form.validate_on_submit():

        data = Role(name=form.name.data,
                    description=form.description.data)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_roles'))

    return render_template('admin/edit_role.html', title='Edit role', role_form=form)


@admin.route('/edit_role/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_role(id):
    """
    Edit an existing role
    :param id:
    :return:
    """

    data = Role.query.get_or_404(id)

    form = EditRoleForm(obj=data)
    form.role = data

    if form.validate_on_submit():

        data.name = form.name.data
        data.description = form.description.data
        db.session.commit()

        return redirect(url_for('admin.edit_roles'))

    return render_template('admin/edit_role.html', role=data, title='Edit role', role_form=form)


@admin.route('/email_log', methods=['GET', 'POST'])
@roles_required('root')
def email_log():
    """
    Display a log of sent emails
    :return: 
    """

    form = EmailLogForm(request.form)

    if form.validate_on_submit():

        if form.delete_age.data is True:
            return redirect(url_for('admin.confirm_delete_email_cutoff', cutoff=(form.weeks.data)))

    return render_template('admin/email_log.html', form=form)


@admin.route('/email_log_ajax', methods=['GET', 'POST'])
@roles_required('root')
def email_log_ajax():
    """
    Ajax data point for email log
    :return:
    """

    emails = db.session.query(EmailLog)
    return ajax.site.email_log_data(emails)


@admin.route('/display_email/<int:id>')
@roles_required('root')
def display_email(id):
    """
    Display a specific email
    :param id:
    :return:
    """

    email = EmailLog.query.get_or_404(id)

    return render_template('admin/display_email.html', email=email)


@admin.route('/delete_email/<int:id>')
@roles_required('root')
def delete_email(id):
    """
    Delete an email
    :param id:
    :return:
    """

    email = EmailLog.query.get_or_404(id)
    db.session.delete(email)
    db.session.commit()

    return redirect(url_for('admin.email_log'))


@admin.route('/confirm_delete_all_emails')
@roles_required('root')
def confirm_delete_all_emails():
    """
    Show confirmation box to delete all emails
    :return:
    """

    title = 'Confirm delete'
    panel_title = 'Confirm delete of all emails retained in log'

    action_url = url_for('admin.delete_all_emails')
    message = '<p>Please confirm that you wish to delete all emails retained in the log.</p>' \
              '<p>This action cannot be undone.</p>'
    submit_label = 'Delete all'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/delete_all_emails')
@roles_required('root')
def delete_all_emails():
    """
    Delete all emails stored in the log
    :return:
    """

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions['celery']
    delete_email = celery.tasks['app.tasks.prune_email.delete_all_email']

    tk_name = 'Manual delete email'
    tk_description = 'Manually delete all email'
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    seq = chain(init.si(task_id, tk_name),
                delete_email.si(),
                final.si(task_id, tk_name, current_user.id)).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for('admin.email_log'))



@admin.route('/confirm_delete_email_cutoff/<int:cutoff>')
@roles_required('root')
def confirm_delete_email_cutoff(cutoff):
    """
    Show confirmation box to delete emails with a cutoff
    :return:
    """

    pl = 's'
    if cutoff == 1:
        pl = ''

    title = 'Confirm delete'
    panel_title = 'Confirm delete all emails older than {c} week{pl}'.format(c=cutoff, pl=pl)

    action_url = url_for('admin.delete_email_cutoff', cutoff=cutoff)
    message = '<p>Please confirm that you wish to delete all emails older than {c} week{pl}.</p>' \
              '<p>This action cannot be undone.</p>'.format(c=cutoff, pl=pl)
    submit_label = 'Delete'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/delete_email_cutoff/<int:cutoff>')
@roles_required('root')
def delete_email_cutoff(cutoff):
    """
    Delete all emails older than the given cutoff
    :param cutoff:
    :return:
    """

    pl = 's'
    if cutoff == 1:
        pl = ''

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions['celery']
    prune_email = celery.tasks['app.tasks.prune_email.prune_email_log']

    tk_name = 'Manual delete email'
    tk_description = 'Manually delete email older than {c} week{pl}'.format(c=cutoff, pl=pl)
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    seq = chain(init.si(task_id, tk_name),
                prune_email.si(duration=cutoff, interval='weeks'),
                final.si(task_id, tk_name, current_user.id)).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for('admin.email_log'))


@admin.route('/edit_messages')
@roles_accepted('faculty', 'admin', 'root')
def edit_messages():
    """
    Edit message-of-the-day type messages
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    return render_template('admin/edit_messages.html')


@admin.route('/messages_ajax', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def messages_ajax():
    """
    Ajax data point for message-of-the-day list
    :return:
    """

    if not validate_is_admin_or_convenor():
        return jsonify({})

    if current_user.has_role('admin') or current_user.has_role('root'):

        # admin users can edit all messages
        messages = MessageOfTheDay.query.all()

    else:

        # convenors can only see their own messages
        messages = MessageOfTheDay.query.filter_by(user_id=current_user.id).all()

    return ajax.admin.messages_data(messages)


@admin.route('/add_message', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_message():
    """
    Add a new message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    # convenors can't show login-screen messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):
        AddMessageForm = AddMessageFormFactory(convenor_editing=True)
        form = AddMessageForm(request.form)
    else:
        AddMessageForm = AddMessageFormFactory(convenor_editing=False)
        form = AddMessageForm(request.form)

    if form.validate_on_submit():

        if 'show_login' in form._fields:
            show_login = form._fields.get('show_login').data
        else:
            show_login = False

        data = MessageOfTheDay(user_id=current_user.id,
                               issue_date=datetime.now(),
                               show_students=form.show_students.data,
                               show_faculty=form.show_faculty.data,
                               show_login=show_login,
                               dismissible=form.dismissible.data,
                               title=form.title.data,
                               body=form.body.data,
                               project_classes=form.project_classes.data)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_messages'))

    return render_template('admin/edit_message.html', form=form, title='Add new broadcast message')


@admin.route('/edit_message/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_message(id):
    """
    Edit a message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = MessageOfTheDay.query.get_or_404(id)

    # convenors can't show login-screen messages and can only edit their own messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):

        if data.user_id != current_user.id:
            flash('Only administrative users can edit messages that they do not own')
            return home_dashboard()

        EditMessageForm = EditMessageFormFactory(convenor_editing=True)
        form = EditMessageForm(obj=data)

    else:

        EditMessageForm = EditMessageFormFactory(convenor_editing=False)
        form = EditMessageForm(obj=data)

    if form.validate_on_submit():

        if 'show_login' in form._fields:
            show_login = form._fields.get('show_login').data
        else:
            show_login = False

        data.show_students = form.show_students.data
        data.show_faculty = form.show_faculty.data
        data.show_login = show_login
        data.dismissible = form.dismissible.data
        data.title = form.title.data
        data.body = form.body.data
        data.project_classes = form.project_classes.data

        db.session.commit()

        return redirect(url_for('admin.edit_messages'))

    return render_template('admin/edit_message.html', message=data, form=form, title='Edit broadcast message')


@admin.route('/delete_message/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def delete_message(id):
    """
    Delete message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = MessageOfTheDay.query.get_or_404(id)

    # convenors can only delete their own messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):

        if data.user_id != current_user.id:
            flash('Only administrative users can edit messages that are not their own.')
            return home_dashboard()

    db.session.delete(data)
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/dismiss_message/<int:id>')
@login_required
def dismiss_message(id):
    """
    Record that the current user has dismissed a particular message
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    if current_user not in message.dismissed_by:

        message.dismissed_by.append(current_user)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/reset_dismissals/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def reset_dismissals(id):
    """
    Remove dismissals from a message (eg. we might want to do this after updating the text)
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    # convenors can only reset their own messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):

        if message.user_id != current_user.id:
            flash('Only administrative users can reset dismissals for messages that are not their own.')
            return home_dashboard()

    message.dismissed_by = []
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/scheduled_tasks')
@roles_required('root')
def scheduled_tasks():
    """
    UI for scheduling periodic tasks (database backup, prune email log, etc.)
    :return:
    """

    return render_template('admin/scheduled_tasks.html')


@admin.route('/scheduled_ajax', methods=['GET', 'POST'])
@roles_required('root')
def scheduled_ajax():
    """
    Ajax data source for scheduled periodic tasks
    :return:
    """

    tasks = db.session.query(DatabaseSchedulerEntry).all()
    return ajax.site.scheduled_task_data(tasks)


@admin.route('/add_scheduled_task', methods=['GET', 'POST'])
@roles_required('root')
def add_scheduled_task():
    """
    Add a new scheduled task
    :return:
    """

    form = ScheduleTypeForm(request.form)

    if form.validate_on_submit():

        if form.type.data == 'interval':

            return redirect(url_for('admin.add_interval_task'))

        elif form.type.data == 'crontab':

            return redirect(url_for('admin.add_crontab_task'))

        else:

            flash('The task type was not recognized. If this error persists, please contact '
                  'the system administrator.')

            return redirect(url_for('admin.scheduled_tasks'))

    return render_template('admin/scheduled_type.html', form=form, title='Select schedule type')


@admin.route('/add_interval_task', methods=['GET', 'POST'])
@roles_required('root')
def add_interval_task():
    """
    Add a new task specified by a simple interval
    :return:
    """

    form = AddIntervalScheduledTask(request.form)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(every=form.every.data, period=form.period.data).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data,
                                   period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)
        now = datetime.now()

        data = DatabaseSchedulerEntry(name=form.name.data,
                                      owner_id=form.owner.data.id,
                                      task=form.task.data,
                                      interval_id=sch.id,
                                      crontab_id=None,
                                      args=args,
                                      kwargs=kwargs,
                                      queue=None,
                                      exchange=None,
                                      routing_key=None,
                                      expires=form.expires.data,
                                      enabled=True,
                                      last_run_at=now,
                                      total_run_count=0,
                                      date_changed=now)

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    return render_template('admin/edit_scheduled_task.html', form=form, title='Add new fixed-interval task')


@admin.route('/add_crontab_task', methods=['GET', 'POST'])
@roles_required('root')
def add_crontab_task():
    """
    Add a new task specified by a crontab
    :return:
    """

    form = AddCrontabScheduledTask(request.form)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(minute=form.minute.data,
                                              hour=form.hour.data,
                                              day_of_week=form.day_of_week.data,
                                              day_of_month=form.day_of_month.data,
                                              month_of_year=form.month_of_year.data).first()

        if sch is None:
            sch = CrontabSchedule(minute=form.minute.data,
                                  hour=form.hour.data,
                                  day_of_week=form.day_of_week.data,
                                  day_of_month=form.day_of_month.data,
                                  month_of_year=form.month_of_year.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)
        now = datetime.now()

        data = DatabaseSchedulerEntry(name=form.name.data,
                                      owner_id=form.owner.data.id,
                                      task=form.task.data,
                                      interval_id=None,
                                      crontab_id=sch.id,
                                      args=args,
                                      kwargs=kwargs,
                                      queue=None,
                                      exchange=None,
                                      routing_key=None,
                                      expires=form.expires.data,
                                      enabled=True,
                                      last_run_at=now,
                                      total_run_count=0,
                                      date_changed=now)

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    return render_template('admin/edit_scheduled_task.html', form=form, title='Add new crontab task')


@admin.route('/edit_interval_task/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_interval_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditIntervalScheduledTask(obj=data)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(every=form.every.data, period=form.period.data).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data,
                                   period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.interval_id = sch.id
        data.crontab_id = None
        data.args = args
        data.kwargs = kwargs
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    else:

        if request.method == 'GET':

            form.every.data = data.interval.every
            form.period.data = data.interval.period

    return render_template('admin/edit_scheduled_task.html', task=data, form=form, title='Edit fixed-interval task')


@admin.route('/edit_interval_task/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_crontab_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditCrontabScheduledTask(obj=data)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(minute=form.minute.data,
                                              hour=form.hour.data,
                                              day_of_week=form.day_of_week.data,
                                              day_of_month=form.day_of_month.data,
                                              month_of_year=form.month_of_year.data).first()

        if sch is None:
            sch = CrontabSchedule(minute=form.minute.data,
                                  hour=form.hour.data,
                                  day_of_week=form.day_of_week.data,
                                  day_of_month=form.day_of_month.data,
                                  month_of_year=form.month_of_year.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.interval_id = None
        data.crontab_id = sch.id
        data.args = args
        data.kwargs = kwargs
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    else:

        if request.method == 'GET':

            form.minute.data = data.crontab.minute
            form.hour.data = data.crontab.hour
            form.day_of_week.data = data.crontab.day_of_week
            form.day_of_month = data.crontab.day_of_month
            form.month_of_year = data.crontab.month_of_year

    return render_template('admin/edit_scheduled_task.html', task=data, form=form, title='Add new crontab task')



@admin.route('/delete_scheduled_task/<int:id>')
@roles_required('root')
def delete_scheduled_task(id):
    """
    Remove an existing scheduled task
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    db.session.delete(task)
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/activate_scheduled_task/<int:id>')
@roles_required('root')
def activate_scheduled_task(id):
    """
    Mark a scheduled task as active
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_scheduled_task/<int:id>')
@roles_required('root')
def deactivate_scheduled_task(id):
    """
    Mark a scheduled task as inactive
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/launch_scheduled_task/<int:id>')
@roles_required('root')
def launch_scheduled_task(id):
    """
    Launch a specified task as a background task
    :param id:
    :return:
    """

    record = DatabaseSchedulerEntry.query.get_or_404(id)

    task_id = register_task(record.name, current_user, 'Scheduled task launched from web user interface')

    celery = current_app.extensions['celery']
    tk = celery.tasks[record.task]

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    seq = chain(init.si(task_id, record.name),
                tk.signature(record.args, record.kwargs, immutable=True),
                final.si(task_id, record.name, current_user.id, notify=True)).on_error(
        error.si(task_id, record.name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(request.referrer)


@admin.route('/backups_overview', methods=['GET', 'POST'])
@roles_required('root')
def backups_overview():
    """
    Generate the backup overview
    :return:
    """

    form = EditBackupOptionsForm(request.form)

    keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()
    limit, units = lim

    backup_count = get_backup_count()
    backup_total_size = get_backup_size()

    if backup_total_size is None:
        size = '(no backups currently held)'
    else:
        size = format_size(backup_total_size)

    if form.validate_on_submit():

        set_backup_config(form.keep_hourly.data, form.keep_daily.data, form.backup_limit.data, form.limit_units.data)
        flash('Your new backup configuration has been saved', 'success')

    else:

        if request.method == 'GET':

            form.keep_hourly.data = keep_hourly
            form.keep_daily.data = keep_daily
            form.backup_limit.data = limit
            form.limit_units.data = units

    # if there are enough datapoints, generate some plots showing how the backup size is scaling with time
    if backup_count > 1:

        # extract lists of data points
        backup_dates = db.session.query(BackupRecord.date).order_by(BackupRecord.date).all()
        archive_size = db.session.query(BackupRecord.archive_size).order_by(BackupRecord.date).all()
        backup_size = db.session.query(BackupRecord.backup_size).order_by(BackupRecord.date).all()

        MB_SIZE = 1024*1024

        dates = [ x[0] for x in backup_dates ]
        arc_size = [ x[0] / MB_SIZE for x in archive_size ]
        bk_size = [ x[0] / MB_SIZE for x in backup_size ]

        archive_plot = figure(title='Archive size as a function of time',
                              x_axis_label='Time of backup', x_axis_type='datetime',
                              plot_width=800, plot_height=300)
        archive_plot.sizing_mode = 'scale_width'
        archive_plot.line(dates, arc_size, legend='archive size in Mb',
                          line_color='blue', line_width=2)
        archive_plot.toolbar.logo = None
        archive_plot.border_fill_color = None
        archive_plot.background_fill_color = 'lightgrey'
        archive_plot.legend.location = 'bottom_right'

        backup_plot = figure(title='Total backup size as a function of time',
                             x_axis_label='Time of backup', x_axis_type='datetime',
                             plot_width=800, plot_height=300)
        backup_plot.sizing_mode = 'scale_width'
        backup_plot.line(dates, bk_size, legend='backup size in Mb',
                          line_color='red', line_width=2)
        backup_plot.toolbar.logo = None
        backup_plot.border_fill_color = None
        backup_plot.background_fill_color = 'lightgrey'
        backup_plot.legend.location = 'bottom_right'

        archive_script, archive_div = components(archive_plot)
        backup_script, backup_div = components(backup_plot)

    else:

        archive_script = None
        archive_div = None
        backup_script = None
        backup_div = None

    # extract data on last few backups
    last_batch = BackupRecord.query.order_by(BackupRecord.date.desc()).limit(4).all()

    if backup_max is not None:

        # construct empty/full gauge
        how_full = float(backup_total_size) / float(backup_max)
        angle = 2*pi * how_full
        start_angle = pi/2.0
        end_angle = pi/2.0 - angle if angle < pi/2.0 else 5.0*pi/2.0 - angle

        gauge = figure(width=250, height=250, toolbar_location=None)
        gauge.sizing_mode = 'scale_width'
        gauge.annular_wedge(x=0, y=0, inner_radius=0.6, outer_radius=1, direction='clock', line_color=None,
                            start_angle=start_angle, end_angle=end_angle, fill_color='red')
        gauge.annular_wedge(x=0, y=0, inner_radius=0.6, outer_radius=1, direction='clock', line_color=None,
                            start_angle=end_angle, end_angle=start_angle, fill_color='grey')
        gauge.axis.visible = False
        gauge.xgrid.visible = False
        gauge.ygrid.visible = False
        gauge.border_fill_color = None
        gauge.toolbar.logo = None
        gauge.background_fill_color = None
        gauge.outline_line_color = None
        gauge.toolbar.active_drag = None

        gauge_script, gauge_div = components(gauge)

    else:

        gauge_script = None
        gauge_div = None

    return render_template('admin/backup_dashboard/overview.html', pane='overview', form=form,
                           backup_size=size, backup_count=backup_count, last_change=last_change,
                           archive_script=archive_script, archive_div=archive_div,
                           backup_script=backup_script, backup_div=backup_div,
                           capacity='{p:.2g}%'.format(p=how_full*100),
                           last_batch=last_batch, gauge_script=gauge_script, gauge_div=gauge_div)


@admin.route('/manage_backups', methods=['GET', 'POST'])
@roles_required('root')
def manage_backups():
    """
    Generate the backup-management view
    :return:
    """

    backup_count = get_backup_count()

    form = BackupManageForm(request.form)

    if form.validate_on_submit():

        if form.delete_age.data is True:
            return redirect(url_for('admin.confirm_delete_backup_cutoff', cutoff=(form.weeks.data)))

    return render_template('admin/backup_dashboard/manage.html', pane='view', backup_count=backup_count, form=form)


@admin.route('/manage_backups_ajax', methods=['GET', 'POST'])
@roles_required('root')
def manage_backups_ajax():
    """
    Ajax data point for backup-management view
    :return:
    """

    backups = db.session.query(BackupRecord)
    return ajax.site.backups_data(backups)


@admin.route('/confirm_delete_all_backups')
@roles_required('root')
def confirm_delete_all_backups():
    """
    Show confirmation box to delete all backups
    :return:
    """

    title = 'Confirm delete'
    panel_title = 'Confirm delete all backups'

    action_url = url_for('admin.delete_all_backups')
    message = '<p>Please confirm that you wish to delete all backups.</p>' \
              '<p>This action cannot be undone.</p>'
    submit_label = 'Delete all'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/delete_all_backups')
@roles_required('root')
def delete_all_backups():
    """
    Delete all backups
    :return:
    """

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions['celery']
    del_backup = celery.tasks['app.tasks.backup.delete_backup']

    tk_name = 'Manual delete backups'
    tk_description = 'Manually delete all backups'
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    backups = db.session.query(BackupRecord.id).all()
    work_group = group(del_backup.si(id) for id in backups)

    seq = chain(init.si(task_id, tk_name), work_group,
                final.si(task_id, tk_name, current_user.id)).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for('admin.manage_backups'))


@admin.route('/confirm_delete_backup_cutoff/<int:cutoff>')
@roles_required('root')
def confirm_delete_backup_cutoff(cutoff):
    """
    Show confirmation box to delete all backups older than a given cutoff
    :param cutoff:
    :return:
    """

    pl = 's'
    if cutoff == 1:
        pl = ''

    title = 'Confirm delete'
    panel_title = 'Confirm delete all backups older than {c} week{pl}'.format(c=cutoff, pl=pl)

    action_url = url_for('admin.delete_backup_cutoff', cutoff=cutoff)
    message = '<p>Please confirm that you wish to delete all backups older than {c} week{pl}.</p>' \
              '<p>This action cannot be undone.</p>'.format(c=cutoff, pl=pl)
    submit_label = 'Delete'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/delete_backup_cutoff/<int:cutoff>')
@roles_required('root')
def delete_backup_cutoff(cutoff):
    """
    Delete all backups older than the given cutoff
    :param cutoff:
    :return:
    """

    pl = 's'
    if cutoff == 1:
        pl = ''

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions['celery']
    del_backup = celery.tasks['app.tasks.backup.prune_backup_cutoff']

    tk_name = 'Manual delete backups'
    tk_description = 'Manually delete backups older than {c} week{pl}'.format(c=cutoff, pl=pl)
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    now = datetime.now()
    delta = timedelta(weeks=cutoff)
    limit = now - delta

    backups = db.session.query(BackupRecord.id).all()
    work_group = group(del_backup.si(id, limit) for id in backups)

    seq = chain(init.si(task_id, tk_name), work_group,
                final.si(task_id, tk_name, current_user.id)).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url_for('admin.manage_backups'))


@admin.route('/confirm_delete_backup/<int:id>')
@roles_required('root')
def confirm_delete_backup(id):
    """
    Show confirmation box to delete a backup
    :return:
    """

    backup = BackupRecord.query.get_or_404(id)

    title = 'Confirm delete'
    panel_title = 'Confirm delete of backup {d}'.format(d=backup.date.strftime("%a %d %b %Y %H:%M:%S"))

    action_url = url_for('admin.delete_backup', id=id)
    message = '<p>Please confirm that you wish to delete the backup {d}.</p>' \
              '<p>This action cannot be undone.</p>'.format(d=backup.date.strftime("%a %d %b %Y %H:%M:%S"))
    submit_label = 'Delete'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/delete_backup/<int:id>')
@roles_required('root')
def delete_backup(id):

    success, msg = remove_backup(id)

    if not success:

        flash('Could not delete backup: {msg}'.format(msg=msg), 'error')

    return redirect(url_for('admin.manage_backups'))


@admin.route('/background_tasks')
@roles_required('root')
def background_tasks():
    """
    List all background tasks
    :return:
    """

    return render_template("admin/background_tasks.html")


@admin.route('/background_ajax', methods=['GET', 'POST'])
@roles_required('root')
def background_ajax():
    """
    Ajax data point for background tasks view
    :return:
    """

    tasks = TaskRecord.query.all()
    return ajax.site.background_task_data(tasks)


@admin.route('/terminate_background_task/<string:id>')
@roles_required('root')
def terminate_background_task(id):

    record = TaskRecord.query.get_or_404(id)

    if record.state == TaskRecord.SUCCESS or record.state == TaskRecord.FAILURE \
            or record.state == TaskRecord.TERMINATED:
        flash('Could not terminate background task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    celery = current_app.extensions['celery']
    celery.control.revoke(record.id, terminate=True, signal='SIGUSR1')

    try:
        # update progress bar
        progress_update(record.id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # remove task from database
        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not terminate task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name), 'error')

    return redirect(request.referrer)


@admin.route('/delete_background_task/<string:id>')
@roles_required('root')
def delete_background_task(id):

    record = TaskRecord.query.get_or_404(id)

    if record.status == TaskRecord.PENDING or record.status == TaskRecord.RUNNING:
        flash('Could not delete match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    try:
        # remove task from database
        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not delete match "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(request.referrer)


@admin.route('/notifications_ajax', methods=['GET', 'POST'])
@limiter.exempt
def notifications_ajax():
    """
    Retrieve all notifications for the current user
    :return:
    """
    # return empty JSON if not logged in; we don't want this endpoint to require that the user is logged in,
    # otherwise we will end up triggering 'you do not have sufficient privileges to view this resource' errors
    # when the session ends but a webpage is still open
    if not current_user.is_authenticated:
        return jsonify({})

    # get timestamp that client wants messages from, if provided
    since = request.args.get('since', 0.0, type=float)

    # query for all notifications associated with the current user
    notifications = current_user.notifications \
        .filter(Notification.timestamp >= since) \
        .order_by(Notification.timestamp.asc()).all()

    # mark any messages or instructions (as opposed to task progress updates) for removal on next page load
    modified = False
    for n in notifications:
        if n.type == Notification.USER_MESSAGE \
                or n.type == Notification.SHOW_HIDE_REQUEST \
                or n.type == Notification.REPLACE_TEXT_REQUEST:

            n.remove_on_pageload = True
            modified = True

    if modified:
        db.session.commit()

    return ajax.polling.notifications_payload(notifications)


@admin.route('/manage_matching')
@roles_required('root')
def manage_matching():
    """
    Create the 'manage matching' dashboard view
    :return:
    """

    # check that all projects are ready to match
    config_list, config_warning, current_year, rollover_ready, matching_ready, \
        rollover_in_progress, assessments, messages = get_root_dashboard_data()

    if not matching_ready:
        flash('Automated matching is not yet available because some project classes are not ready', 'error')
        return redirect(request.referrer)

    if rollover_in_progress:
        flash('Automated matching is not available because a rollover of the academic year is underway', 'info'),
        return redirect(request.referrer)

    info = get_matching_dashboard_data()

    return render_template('admin/matching/manage.html', pane='manage', info=info)


@admin.route('/matches_ajax')
@roles_required('root')
def matches_ajax():
    """
    Create the 'manage matching' dashboard view
    :return:
    """

    # check that all projects are ready to match
    config_list, config_warning, current_year, rollover_ready, matching_ready, \
        rollover_in_progress, assessments, messages = get_root_dashboard_data()

    if not matching_ready or rollover_in_progress:
        return jsonify({})

    current_year = get_current_year()
    matches = db.session.query(MatchingAttempt).filter_by(year=current_year).all()

    return ajax.admin.matches_data(matches, text='matching dashboard', url=url_for('admin.manage_matching'))


@admin.route('/create_match', methods=['GET', 'POST'])
@roles_required('root')
def create_match():
    """
    Create the 'create match' dashboard view
    :return:
    """
    # check that all projects are ready to match
    config_list, config_warning, current_year, rollover_ready, matching_ready, \
        rollover_in_progress, assessments, messages = get_root_dashboard_data()

    if not matching_ready:
        flash('Automated matching is not yet available because some project classes are not ready', 'info')
        return redirect(request.referrer)

    if rollover_in_progress:
        flash('Automated matching is not available because a rollover of the academic year is underway', 'info'),
        return redirect(request.referrer)

    info = get_matching_dashboard_data()

    NewMatchForm = NewMatchFormFactory(current_year)
    form = NewMatchForm(request.form)

    if form.validate_on_submit():
        uuid = register_task('Match job "{name}"'.format(name=form.name.data),
                             owner=current_user, description="Automated project matching task")

        data = MatchingAttempt(year=current_year,
                               name=form.name.data,
                               celery_id=uuid,
                               finished=False,
                               outcome=None,
                               published=False,
                               selected=False,
                               construct_time=None,
                               compute_time=None,
                               ignore_per_faculty_limits=form.ignore_per_faculty_limits.data,
                               ignore_programme_prefs=form.ignore_programme_prefs.data,
                               years_memory=form.years_memory.data,
                               supervising_limit=form.supervising_limit.data,
                               marking_limit=form.marking_limit.data,
                               max_marking_multiplicity=form.max_marking_multiplicity.data,
                               levelling_bias=form.levelling_bias.data,
                               intra_group_tension=form.intra_group_tension.data,
                               programme_bias=form.programme_bias.data,
                               bookmark_bias=form.bookmark_bias.data,
                               use_hints=form.use_hints.data,
                               encourage_bias=form.encourage_bias.data,
                               discourage_bias=form.discourage_bias.data,
                               strong_encourage_bias=form.strong_encourage_bias.data,
                               strong_discourage_bias=form.strong_discourage_bias.data,
                               solver=form.solver.data,
                               creation_timestamp=datetime.now(),
                               creator_id=current_user.id,
                               last_edit_timestamp=None,
                               last_edit_id=None,
                               score=None)

        # check whether there is any work to do -- is there a current config entry for each
        # attached pclass?
        count = 0
        for pclass in form.pclasses_to_include.data:

            config = db.session.query(ProjectClassConfig) \
                .filter(ProjectClassConfig.pclass_id == pclass.id) \
                .order_by(ProjectClassConfig.year == current_year).first()

            if config is not None:
                if config not in data.config_members:
                    count += 1
                    data.config_members.append(config)

        if count == 0:
            flash('No project classes were specified for inclusion, so no match was computed.', 'error')
            return redirect(url_for('admin.manage_caching'))

        # for matches we are supposed to take account of when levelling workload, check that there is no overlap
        # with the projects we will include in this match
        for match in form.include_matches.data:

            if match not in data.include_matches:
                ok = True
                for pclass_a in data.config_members:
                    for pclass_b in match.config_members:
                        if pclass_a.id == pclass_b.id:
                            ok = False
                            flash('Excluded CATS from existing match "{name}" since it contains project class '
                                  '"{pname}" which overlaps with the current match'.format(name=match.label,
                                                                                           pname=pclass_a.name))
                            break

                if ok:
                    data.include_matches.append(match)

        db.session.add(data)
        db.session.commit()

        celery = current_app.extensions['celery']
        match_task = celery.tasks['app.tasks.matching.create_match']

        match_task.apply_async(args=(data.id,), task_id=uuid)

        return redirect(url_for('admin.manage_matching'))

    else:

        if request.method == 'GET':
            form.use_hints.data = True

    # estimate equitable CATS loading
    supervising_CATS, marking_CATS, presentation_CATS, \
        num_supervisors, num_markers, num_presentations = estimate_CATS_load()

    return render_template('admin/matching/create.html', pane='create', info=info, form=form,
                           supervising_CATS=supervising_CATS, marking_CATS=marking_CATS,
                           num_supervisors=num_supervisors, num_markers=num_markers)


@admin.route('/terminate_match/<int:id>')
@roles_required('root')
def terminate_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if record.finished:
        flash('Can not terminate matching task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    title = 'Terminate match'
    panel_title = 'Terminate match <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('admin.perform_terminate_match', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to terminate the matching job ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Terminate job'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_terminate_match/<int:id>')
@roles_required('root')
def perform_terminate_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('admin.manage_matching')

    if record.finished:
        flash('Can not terminate matching task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(url)

    celery = current_app.extensions['celery']
    celery.control.revoke(record.celery_id, terminate=True, signal='SIGUSR1')

    try:
        progress_update(record.celery_id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # delete all MatchingRecords associated with this MatchingAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(MatchingRecord).filter_by(matching_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Can not terminate matching task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(url)


@admin.route('/delete_match/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def delete_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year', 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Can not delete match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    title = 'Delete match'
    panel_title = 'Delete match <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('admin.perform_delete_match', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to delete the matching ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Delete match'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_delete_match/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def perform_delete_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('admin.manage_matching')

    if not validate_match_inspector(record):
        return redirect(url)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year', 'info')
        return redirect(url)

    if not record.finished:
        flash('Can not delete match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(url)

    if not current_user.has_role('root') and current_user.id != record.creator_id:
        flash('Match "{name}" cannot be deleted because it belongs to another user')
        return redirect(url)

    try:
        # delete all MatchingRecords associated with this MatchingAttempt
        db.session.query(MatchingRecord).filter_by(matching_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Can not delete match "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(url)


@admin.route('/revert_match/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def revert_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year', 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Can not revert match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not revert match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    title = 'Revert match'
    panel_title = 'Revert match <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('admin.perform_revert_match', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to revert the matching ' \
              '<strong>{name}</strong> to its original state.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Revert match'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_revert_match/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def perform_revert_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year', 'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    if url is None:
        # TODO consider an alternative implementation here
        url = url_for('admin.manage_matching')

    if not record.finished:
        flash('Can not revert match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not revert match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    # hand off revert job to asynchronous queue
    celery = current_app.extensions['celery']
    revert = celery.tasks['app.tasks.matching.revert']

    tk_name = 'Revert {name}'.format(name=record.name)
    tk_description = 'Revert matching to its original state'
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    seq = chain(init.si(task_id, tk_name),
                revert.si(record.id),
                final.si(task_id, tk_name, current_user.id)).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url)


@admin.route('/duplicate_match/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def duplicate_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year.', 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Can not duplicate match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not duplicate match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    suffix = 2
    while suffix < 100:
        new_name = '{name} #{suffix}'.format(name=record.name, suffix=suffix)

        if MatchingAttempt.query.filter_by(name=new_name, year=year).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash('Can not duplicate match "{name}" because a new unique tag could not '
              'be generated.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    # hand off duplicate job to asynchronous queue
    celery = current_app.extensions['celery']
    duplicate = celery.tasks['app.tasks.matching.duplicate']

    tk_name = 'Duplicate {name}'.format(name=record.name)
    tk_description = 'Duplicate a matching'
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    seq = chain(init.si(task_id, tk_name),
                duplicate.si(record.id, new_name, current_user.id),
                final.si(task_id, tk_name, current_user.id)).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(request.referrer)


@admin.route('/rename_match/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def rename_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year', 'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('admin.manage_matching')

    RenameMatchForm = RenameMatchFormFactory(year)
    form = RenameMatchForm(request.form)
    form.record = record

    if form.validate_on_submit():
        try:
            record.name = form.name.data
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash('Could not rename match "{name}" due to a database error. '
                  'Please contact a system administrator.'.format(name=record.name), 'error')

        return redirect(url)

    return render_template('admin/match_inspector/rename.html', form=form, record=record, url=url)


@admin.route('/compare_match/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def compare_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    if not record.finished:
        flash('Can not compare match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    year = get_current_year()
    our_pclasses = {x.id for x in record.available_pclasses}

    CompareMatchForm = CompareMatchFormFactory(year, record.id, our_pclasses)
    form = CompareMatchForm(request.form)

    if form.validate_on_submit():

        comparator = form.target.data
        return redirect(url_for('admin.do_compare', id1=id, id2=comparator.id, text=text, url=url))

    return render_template('admin/match_inspector/compare_setup.html', form=form, record=record, text=text, url=url)


@admin.route('/do_compare/<int:id1>/<int:id2>')
@roles_accepted('faculty', 'admin', 'root')
def do_compare(id1, id2):

    record1 = MatchingAttempt.query.get_or_404(id1)
    record2 = MatchingAttempt.query.get_or_404(id2)

    if not validate_match_inspector(record1) or not validate_match_inspector(record2):
        return redirect(request.referrer)

    if not record1.finished:
        flash('Can not compare match "{name}" because it has not terminated.'.format(name=record1.name),
              'error')
        return redirect(request.referrer)

    if record1.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record1.name),
              'error')
        return redirect(request.referrer)

    if not record2.finished:
        flash('Can not compare match "{name}" because it has not terminated.'.format(name=record2.name),
              'error')
        return redirect(request.referrer)

    if record2.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record2.name),
              'error')
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')
    text = request.args.get('text', None)
    url = request.args.get('url', None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    pclasses = record1.available_pclasses

    return render_template('admin/match_inspector/compare.html', record1=record1, record2=record2, text=text, url=url,
                           pclasses=pclasses, pclass_filter=pclass_filter)


@admin.route('/do_compare_ajax/<int:id1>/<int:id2>')
@roles_accepted('faculty', 'admin', 'root')
def do_compare_ajax(id1, id2):

    record1 = MatchingAttempt.query.get_or_404(id1)
    record2 = MatchingAttempt.query.get_or_404(id2)

    if not validate_match_inspector(record1) or not validate_match_inspector(record2):
        return redirect(request.referrer)

    if not record1.finished:
        flash('Can not compare match "{name}" because it has not terminated.'.format(name=record1.name),
              'error')
        return redirect(request.referrer)

    if record1.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record1.name),
              'error')
        return redirect(request.referrer)

    if not record2.finished:
        flash('Can not compare match "{name}" because it has not terminated.'.format(name=record2.name),
              'error')
        return redirect(request.referrer)

    if record2.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record2.name),
              'error')
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')
    flag, pclass_value = is_integer(pclass_filter)

    # we know record2 has at least the same pclasses included as record1, although it may in fact have more
    # (there seems no simple query to restrict record2 to have exactly the same pclasses, and anyway there might
    # be use cases where it's useful to compare a match on a subset to a match on a larger group)

    # that means we need to work through the list of records in record2, pairing them up with records in record1
    recs1 = deque(record1.records \
                  .order_by(MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc()).all())
    recs2 = deque(record2.records \
                  .order_by(MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc()).all())

    data = []

    # can assume there will be *some* data in both recs1 and recs2
    left = recs1.popleft()
    right = recs2.popleft()

    while left is not None:

        while right.selector_id < left.selector_id:
            right = recs2.popleft()

        if left.selector_id != right.selector_id:
            raise RuntimeError('Unexpected discrepancy between LHS and RHS selector_id')

        if left.submission_period != right.submission_period:
            raise RuntimeError('Unexpected discrepancy between LHS and RHS submission periods')

        if left.project_id != right.project_id or left.marker_id != right.marker_id:
            if not flag or pclass_value == left.selector.config.pclass_id:
                data.append((left, right))

        if len(recs1) > 0:
            left = recs1.popleft()
            right = recs2.popleft()
        else:
            left = None

    return ajax.admin.compare_match_data(data)


@admin.route('/merge_replace_records/<int:src_id>/<int:dest_id>')
@roles_accepted('faculty', 'admin', 'root')
def merge_replace_records(src_id, dest_id):

    source = MatchingRecord.query.get_or_404(src_id)
    dest = MatchingRecord.query.get_or_404(dest_id)

    if not validate_match_inspector(source.matching_attempt) or not validate_match_inspector(dest.matching_attempt):
        return redirect(request.referrer)

    year = get_current_year()
    if dest.matching_attempt.year != year:
        flash('Match "{name}" can no longer be edited because it belongs to a previous year', 'info')
        return redirect(request.referrer)

    if source.selector_id != dest.selector_id:
        flash('Cannot merge these matching records because they do not refer to the same selector', 'error')
        return redirect(request.referrer)

    if source.submission_period != dest.submission_period:
        flash('Cannot merge these matching records because they do not refer to the same submission period', 'error')
        return redirect(request.referrer)

    try:
        dest.project_id = source.project_id
        dest.supervisor_id = source.supervisor_id
        dest.marker_id = source.marker_id
        dest.rank = source.rank

        dest.matching_attempt.last_edit_id = current_user.id
        dest.matching_attempt.last_edit_timestamp = datetime.now()

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Can not merge matching records due to a database error. '
              'Please contact a system administrator.', 'error')

    return redirect(request.referrer)


@admin.route('/match_student_view/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def match_student_view(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        flash('Match "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" is not available for inspection '
              'because it did not yield an optimal solution'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')
    text = request.args.get('text', None)
    url = request.args.get('url', None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    pclasses = record.available_pclasses

    return render_template('admin/match_inspector/student.html', pane='student', record=record,
                           pclasses=pclasses, pclass_filter=pclass_filter,
                           text=text, url=url)


@admin.route('/match_faculty_view/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def match_faculty_view(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        flash('Match "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" is not available for inspection '
              'because it did not yield an optimal solution.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')
    text = request.args.get('text', None)
    url = request.args.get('url', None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    if pclass_filter is not None:
        session['admin_match_pclass_filter'] = pclass_filter

    pclasses = get_automatch_pclasses()

    return render_template('admin/match_inspector/faculty.html', pane='faculty', record=record,
                           pclasses=pclasses, pclass_filter=pclass_filter,
                           text=text, url=url)


@admin.route('/match_dists_view/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def match_dists_view(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        flash('Match "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" is not available for inspection '
              'because it did not yield an optimal solution.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')
    text = request.args.get('text', None)
    url = request.args.get('url', None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    if pclass_filter is not None:
        session['admin_match_pclass_filter'] = pclass_filter

    flag, pclass_value = is_integer(pclass_filter)

    pclasses = get_automatch_pclasses()

    fsum = lambda x: x[0] + x[1]
    CATS_tot = [fsum(record.get_faculty_CATS(f.id, pclass_value if flag else None)) for f in record.faculty]

    CATS_plot = figure(title='Workload distribution',
                       x_axis_label='CATS', plot_width=800, plot_height=300)
    CATS_hist, CATS_edges = histogram(CATS_tot, bins='auto')
    CATS_plot.quad(top=CATS_hist, bottom=0, left=CATS_edges[:-1], right=CATS_edges[1:],
                   fill_color="#036564", line_color="#033649")
    CATS_plot.sizing_mode = 'scale_width'
    CATS_plot.toolbar.logo = None
    CATS_plot.border_fill_color = None
    CATS_plot.background_fill_color = 'lightgrey'

    CATS_script, CATS_div = components(CATS_plot)

    delta_data_set = zip(record.selectors, record.selector_deltas)
    if flag:
        delta_data_set = [x for x in delta_data_set if (x[0])[0].selector.config.pclass_id == pclass_value]

    deltas = [x[1] for x in delta_data_set if x[1] is not None]

    delta_plot = figure(title='Delta distribution',
                       x_axis_label='Total delta', plot_width=800, plot_height=300)
    delta_hist, delta_edges = histogram(deltas, bins='auto')
    delta_plot.quad(top=delta_hist, bottom=0, left=delta_edges[:-1], right=delta_edges[1:],
                   fill_color="#036564", line_color="#033649")
    delta_plot.sizing_mode = 'scale_width'
    delta_plot.toolbar.logo = None
    delta_plot.border_fill_color = None
    delta_plot.background_fill_color = 'lightgrey'

    delta_script, delta_div = components(delta_plot)

    return render_template('admin/match_inspector/dists.html', pane='dists', record=record, pclasses=pclasses,
                           pclass_filter=pclass_filter, CATS_script=CATS_script, CATS_div=CATS_div,
                           delta_script=delta_script, delta_div=delta_div,
                           text=text, url=url)


@admin.route('/match_student_view_ajax/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def match_student_view_ajax(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return jsonify({})

    if not record.finished or record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        return jsonify({})

    pclass_filter = request.args.get('pclass_filter')
    flag, pclass_value = is_integer(pclass_filter)

    data_set = zip(record.selectors, record.selector_deltas)
    if flag:
        data_set = [x for x in data_set if (x[0])[0].selector.config.pclass_id == pclass_value]

    return ajax.admin.student_view_data(data_set)


@admin.route('/match_faculty_view_ajax/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def match_faculty_view_ajax(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return jsonify({})

    if not record.finished or record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        return jsonify({})

    pclass_filter = request.args.get('pclass_filter')

    flag, pclass_value = is_integer(pclass_filter)

    return ajax.admin.faculty_view_data(record.faculty, record, pclass_value if flag else None)


@admin.route('/reassign_match_project/<int:id>/<int:pid>')
@roles_accepted('faculty', 'admin', 'root')
def reassign_match_project(id, pid):

    record = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(request.referrer)

    if record.matching_attempt.selected:
        flash('Match "{name}" cannot be edited because an administrative user has marked it as '
              '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
              'info')
        return redirect(request.referrer)

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash('Match "{name}" can no longer be edited because '
              'it belongs to a previous year'.format(name=record.name), 'info')
        return redirect(request.referrer)

    project = LiveProject.query.get_or_404(pid)

    if record.selector.has_submitted:
        if record.selector.is_project_submitted(project):
            record.project_id = project.id
            record.rank = record.selector.project_rank(project.id)

            record.matching_attempt.last_edit_id = current_user.id
            record.matching_attempt.last_edit_timestamp = datetime.now()

            db.session.commit()
        else:
            flash("Could not reassign '{proj}' to {name}; this project "
                  "was not included in this selector's choices".format(proj=project.name,
                                                                       name=record.selector.student.user.name),
                  'error')

    return redirect(request.referrer)


@admin.route('/reassign_match_marker/<int:id>/<int:mid>')
@roles_accepted('faculty', 'admin', 'root')
def reassign_match_marker(id, mid):

    record = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(request.referrer)

    if record.matching_attempt.selected:
        flash('Match "{name}" cannot be edited because an administrative user has marked it as '
              '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
              'info')
        return redirect(request.referrer)

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash('Match "{name}" can no longer be edited because '
              'it belongs to a previous year'.format(name=record.name), 'info')
        return redirect(request.referrer)

    # check intended mid is in list of attached second markers
    count = get_count(record.project.assessor_list_query.filter_by(id=mid))

    if count == 0:
        marker = FacultyData.query.get_or_404(mid)
        flash('Could not assign {name} as 2nd marker since '
              'not tagged as available for assigned project "{proj}"'.format(name=marker.user.name,
                                                                             proj=record.project.name), 'error')

    elif count == 1:
        record.marker_id = mid

        record.matching_attempt.last_edit_id = current_user.id
        record.matching_attempt.last_edit_timestamp = datetime.now()

        db.session.commit()

    else:
        flash('Inconsistent marker counts for matching record (id={id}). '
              'Please contact a system administrator'.format(id=record.id), 'error')

    return redirect(request.referrer)


@admin.route('/publish_match/<int:id>')
@roles_required('root')
def publish_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because '
              'it belongs to a previous year'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Match "{name}" cannot be published until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" did not yield an optimal solution and is not available for use during rollover. '
              'It cannot be shared with convenors.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    record.published = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/unpublish_match/<int:id>')
@roles_required('root')
def unpublish_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because '
              'it belongs to a previous year'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Match "{name}" cannot be unpublished until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" did not yield an optimal solution and is not available for use during rollover. '
              'It cannot be shared with convenors.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    record.published = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/select_match/<int:id>')
@roles_required('root')
def select_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because '
              'it belongs to a previous year'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Match "{name}" cannot be selected until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" did not yield an optimal solution '
              'and is not available for use during rollover.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not record.is_valid:
        flash('Match "{name}" cannot be selected because it is not '
              'in a valid state.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    # determine whether any already-selected projects have allocations for a pclass we own
    our_pclasses = set()
    for item in record.available_pclasses:
        our_pclasses.add(item.id)

    selected_pclasses = set()
    selected = db.session.query(MatchingAttempt) \
        .filter_by(year=year, selected=True).all()
    for match in selected:
        for item in match.available_pclasses:
            selected_pclasses.add(item.id)

    intersection = our_pclasses & selected_pclasses
    if len(intersection) > 0:
        flash('Cannot select match "{name}" because some project classes it handles are already '
              'determined by selected matches.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    record.selected = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deselect_match/<int:id>')
@roles_required('root')
def deselect_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(request.referrer)

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be edited because '
              'it belongs to a previous year'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not record.finished:
        flash('Match "{name}" cannot be selected until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" did not yield an optimal solution '
              'and is not available for use during rollover.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    record.selected = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/manage_assessments')
@roles_required('root')
def manage_assessments():
    """
    Create the 'manage assessments' view
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    return render_template('admin/presentations/manage.html')


@admin.route('/presentation_assessments_ajax')
@roles_required('root')
def presentation_assessments_ajax():
    """
    AJAX endpoint to generate data for populating the 'manage assessments' view
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    current_year = get_current_year()
    assessments = db.session.query(PresentationAssessment).filter_by(year=current_year).all()

    return ajax.admin.presentation_assessments_data(assessments)


@admin.route('/add_assessment', methods=['GET', 'POST'])
@roles_required('root')
def add_assessment():
    """
    Add a new named assessment event
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    current_year = get_current_year()
    AddPresentationAssessmentForm = AddPresentationAssessmentFormFactory(current_year)
    form = AddPresentationAssessmentForm(request.form)

    print(form.name.validators)

    if form.validate_on_submit():
        data = PresentationAssessment(name=form.name.data,
                                      year=current_year,
                                      submission_periods=form.submission_periods.data,
                                      number_assessors=form.number_assessors.data,
                                      requested_availability=False,
                                      availability_closed=False,
                                      availability_deadline=None,
                                      feedback_open=True,
                                      creator_id=current_user.id,
                                      creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.manage_assessments'))

    return render_template('admin/presentations/edit_assessment.html', form=form,
                           title='Add new presentation assessment event')


@admin.route('/edit_assessment/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_assessment(id):
    """
    Edit an existing named assessment event
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    if data.requested_availability:
        flash('It is no longer possible to change settings for an assessment once '
              'availability requests have been issued.', 'info')
        return redirect(request.referrer)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    EditPresentationAssessmentForm = EditPresentationAssessmentFormFactory(current_year, data.id)
    form = EditPresentationAssessmentForm(obj=data)
    form.assessment = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.submission_periods = form.submission_periods.data
        data.number_assessors = form.number_assessors.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.manage_assessments'))

    return render_template('admin/presentations/edit_assessment.html', form=form, assessment=data,
                           title='Edit existing presentation assessment event')


@admin.route('/delete_assessment/<int:id>')
@roles_required('root')
def delete_assessment(id):
    """
    Delete an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if data.is_deployed:
        flash('Assessment "{name}" has a deployed schedule and cannot be deleted.'.format(name=data.name), 'info')
        return redirect(request.referrer)

    title = 'Delete presentation assessment'
    panel_title = 'Delete presentation assessment <strong>{name}</strong>'.format(name=data.name)

    action_url = url_for('admin.perform_delete_assessment', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to delete the assessment ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=data.name)
    submit_label = 'Delete assessment'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_delete_assessment/<int:id>')
@roles_required('root')
def perform_delete_assessment(id):
    """
    Delete an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    url = request.args.get('url', url_for('admin.manage_assessments'))

    db.session.delete(data)
    db.session.commit()

    return redirect(url)


@admin.route('/close_assessment/<int:id>')
@roles_required('root')
def close_assessment(id):
    """
    Close feedback for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.feedback_open:
        return redirect(request.referrer)

    if not data.is_closable:
        flash('Cannot close assessment "{name}" because one or more closing criteria have not been met. Check '
              'that all scheduled sessions are in the past.'.format(name=data.name), 'info')
        return redirect(request.referrer)

    title = 'Close feedback for assessment'
    panel_title = 'Close feedback for assessment <strong>{name}</strong>'.format(name=data.name)

    action_url = url_for('admin.perform_close_assessment', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to close feedback for the assessment ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=data.name)
    submit_label = 'Close feedback'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_close_assessment/<int:id>')
@roles_required('root')
def perform_close_assessment(id):
    """
    Close feedback for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.feedback_open:
        return redirect(request.referrer)

    if not data.is_closable:
        flash('Cannot close assessment "{name}" because one or more closing criteria have not been met. Check '
              'that all scheduled sessions are in the past.'.format(name=data.name), 'info')
        return redirect(request.referrer)

    url = request.args.get('url', url_for('admin.manage_assessments'))

    data.feedback_open = False
    db.session.commit()

    return redirect(url)


@admin.route('/assessment_availability/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def assessment_availability(id):
    """
    Request availability information from faculty
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.is_valid and data.availability_lifecycle < PresentationAssessment.AVAILABILITY_REQUESTED:
        flash('Cannot request availability for an invalid assessment. Correct any validation errors before '
              'attempting to proceed.', 'info')
        return redirect(request.referrer)

    form = AvailabilityForm(obj=data)

    if form.is_submitted() and form.issue_requests.data is True:

        if not data.requested_availability:

            if get_count(data.submission_periods) == 0:
                flash('Availability requests not issued since this assessment is not attached to any '
                      'submission periods', 'info')

            elif get_count(data.sessions) == 0:
                flash('Availability requests not issued since this assessment does not contain any sessions',
                      'info')

            else:

                uuid = register_task('Issue availability requests for "{name}"'.format(name=data.name),
                                     owner=current_user, description="Issue availability requests to faculty assessors")

                celery = current_app.extensions['celery']
                availability_task = celery.tasks['app.tasks.availability.issue']

                availability_task.apply_async(args=(data.id, current_user.id, uuid), task_id=uuid)

        data.requested_availability = True
        data.availability_deadline = form.availability_deadline.data

        db.session.commit()

        return redirect(url_for('admin.manage_assessments'))

    else:

        if request.method == 'GET':
            if form.availability_deadline.data is None:
                form.availability_deadline.data = date.today() + timedelta(weeks=2)

    if data.availability_lifecycle > PresentationAssessment.AVAILABILITY_NOT_REQUESTED:
        form.issue_requests.label.text = 'Save changes'

    return render_template('admin/presentations/availability.html', form=form, assessment=data)


@admin.route('/close_availability/<int:id>')
@roles_required('root')
def close_availability(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot close availability collection for this assessment because it has not yet been opened', 'info')
        return redirect(request.referrer)

    data.availability_closed = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/reopen_availability/<int:id>')
@roles_required('root')
def reopen_availability(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot reopen availability collection for this assessment because it has not yet been opened', 'info')
        return redirect(request.referrer)

    if not data.availability_closed:
        flash('Cannot reopen availability collection for this assessment because it has not yet been closed', 'info')
        return redirect(request.referrer)

    if data.is_deployed:
        flash('Cannot reopen availability collection for this assessment because it has a deployed schedule', 'info')
        return redirect(request.referrer)

    data.availability_closed = False
    if data.availability_deadline < date.today():
        data.availability_deadline = date.today() + timedelta(weeks=1)

    db.session.commit()

    return redirect(request.referrer)


@admin.route('/outstanding_availability/<int:id>')
@roles_required('root')
def outstanding_availability(id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot show outstanding availability responses for this assessment because it has not yet been opened',
              'info')
        return redirect(request.referrer)

    return render_template('admin/presentations/availability/outstanding.html', assessment=data)


@admin.route('/outstanding_availability_ajax/<int:id>')
@roles_required('root')
def outstanding_availability_ajax(id):
    if not validate_using_assessment():
        return jsonify({})

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return jsonify({})

    if not data.requested_availability:
        flash('Cannot show outstanding availability responses for this assessment because it has not yet been opened',
              'info')
        return jsonify({})

    return ajax.admin.outstanding_availability_data(data.availability_outstanding, data)


@admin.route('/force_confirm_availability/<int:assessment_id>/<int:faculty_id>')
@roles_required('root')
def force_confirm_availability(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(assessment_id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.requested_availability:
        flash('Cannot force confirm an availability response for this assessment because it has not yet been opened',
              'info')
        return redirect(request.referrer)

    faculty = FacultyData.query.get_or_404(faculty_id)

    if faculty not in data.assessors:
        flash('Cannot force confirm availability response for {name} because this faculty member is not attached '
              'to this assessment'.format(name=faculty.user.name), 'error')
        return redirect(request.referrer)

    if faculty in data.availability_outstanding:
        data.availability_outstanding.remove(faculty)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/assessment_manage_sessions/<int:id>')
@roles_required('root')
def assessment_manage_sessions(id):
    """
    Manage dates for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(request.referrer)

    return render_template('admin/presentations/manage_sessions.html', assessment=data)


@admin.route('/attach_sessions_ajax/<int:id>')
@roles_required('root')
def attach_sessions_ajax(id):
    if not validate_using_assessment():
        return jsonify({})

    data = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return jsonify({})

    return ajax.admin.assessment_sessions_data(data.sessions)


@admin.route('/add_session/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def add_session(id):
    """
    Attach a new session to the specified assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(request.referrer)

    form = AddSessionForm(request.form)

    if form.validate_on_submit():
        sess = PresentationSession(owner_id=data.id,
                                   date=form.date.data,
                                   session_type=form.session_type.data,
                                   rooms=form.rooms.data,
                                   creator_id=current_user.id,
                                   creation_timestamp=datetime.now())
        db.session.add(sess)
        db.session.commit()

        return redirect(url_for('admin.assessment_manage_sessions', id=id))

    return render_template('admin/presentations/edit_session.html', form=form, assessment=data)


@admin.route('/edit_session/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_session(id):
    """
    Edit an existing assessment event session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    sess = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return redirect(request.referrer)

    if not sess.owner.feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be '
              'edited'.format(name=sess.owner.name), 'info')
        return redirect(request.referrer)

    form = EditSessionForm(obj=sess)
    form.session = sess

    if form.validate_on_submit():
        sess.date = form.date.data
        sess.session_type = form.session_type.data
        sess.rooms = form.rooms.data

        sess.last_edit_id = current_user.id
        sess.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.assessment_manage_sessions', id=sess.owner_id))

    return render_template('admin/presentations/edit_session.html', form=form, assessment=sess.owner, sess=sess)


@admin.route('/delete_session/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def delete_session(id):
    """
    Delete the specified session from an assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    sess = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return redirect(request.referrer)

    if not sess.owner.feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be '
              'edited'.format(name=sess.owner.name), 'info')
        return redirect(request.referrer)

    db.session.delete(sess)
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_availabilities/<int:id>')
@roles_required('root')
def edit_availabilities(id):
    """
    Edit/inspect faculty availabilities for an assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    sess = PresentationSession.query.get_or_404(id)

    if not sess.owner.feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be '
              'edited'.format(name=sess.owner.name), 'info')
        return redirect(request.referrer)

    if not validate_assessment(sess.owner):
        return redirect(request.referrer)

    return render_template('admin/presentations/edit_availabilities.html', assessment=sess.owner, sess=sess)


@admin.route('/edit_availabilities_ajax/<int:id>')
@roles_required('root')
def edit_availabilities_ajax(id):
    """
    AJAX data entrypoint for edit/inspect faculty availability viee
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    sess = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return jsonify({})

    return ajax.admin.edit_availability_data(sess.owner, sess)


@admin.route('/session_available/<int:f_id>/<int:s_id>')
@roles_accepted('root')
def session_available(f_id, s_id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationSession.query.get_or_404(s_id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(request.referrer)

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    fac = FacultyData.query.get_or_404(f_id)

    present = data.in_session(fac.id)
    if not present:
        data.faculty.append(fac)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/session_unavailable/<int:f_id>/<int:s_id>')
@roles_accepted('root')
def session_unavailable(f_id, s_id):
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationSession.query.get_or_404(s_id)

    current_year = get_current_year()
    if not validate_assessment(data.owner, current_year=current_year):
        return redirect(request.referrer)

    if not data.owner.requested_availability:
        flash('Cannot set availability for this session because its parent assessment has not yet been opened', 'info')
        return redirect(request.referrer)

    fac = FacultyData.query.get_or_404(f_id)

    present = data.in_session(fac.id)
    if present:
        data.faculty.remove(fac)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/assessment_schedules/<int:id>')
@roles_required('root')
def assessment_schedules(id):
    """
    Manage schedules associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.availability_closed:
        flash('It is only possible to generate schedules once collection of faculty availabilities is closed',
              'info')
        return redirect(request.referrer)

    matches = get_count(data.scheduling_attempts)

    return render_template('admin/presentations/scheduling/manage.html', pane='manage', info=matches, assessment=data)


@admin.route('/assessment_schedules_ajax/<int:id>')
@roles_required('root')
def assessment_schedules_ajax(id):
    """
    AJAX data point for schedules associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return jsonify({})

    if not data.availability_closed:
        return jsonify({})

    return ajax.admin.assessment_schedules_data(data.scheduling_attempts, text='assessment schedule manager',
                                                url=url_for('admin.assessment_schedules', id=id))


def _validate_number_slots(assessment, max_group_size):
    # perform absolute basic validation, to check that there are enough dates available
    # with the specified maximum group size
    available_slots = assessment.number_slots
    required_slots = 0

    for period in assessment.submission_periods:
        projects = period.number_projects
        p, r = divmod(projects, max_group_size)

        # whatever strategy we choose to deal with the leftover students in the remainder r,
        # we are always going to require *at least* p+1 slots
        required_slots += p + 1

    if required_slots > available_slots:
        flash('Can not construct a schedule. The minimum possible number of slots ({min}) exceeds the '
              'available number ({avail}), so the scheduling problem is infeasible. Please increase the number '
              'of rooms, or dates, or both.'.format(min=required_slots, avail=available_slots), 'error')
        return False

    return True


@admin.route('/create_assessment_schedule/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def create_assessment_schedule(id):
    """
    Create a new schedule associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(data, current_year=current_year):
        return redirect(request.referrer)

    if not data.availability_closed:
        flash('It is only possible to generate schedules once collection of faculty availabilities is closed',
              'info')
        return redirect(request.referrer)

    if not data.is_valid and len(data.errors) > 0:
        flash('It is not possible to generate a schedule for an assessment that contains validation errors. '
              'Correct any indicated errors before attempting to try again.', 'info')
        return redirect(request.referrer)

    NewScheduleForm = NewScheduleFormFactory(data)
    form = NewScheduleForm(request.form)

    if form.validate_on_submit():
        if _validate_number_slots(data, form.max_group_size.data):
            uuid = register_task('Schedule job "{name}"'.format(name=form.name.data),
                                 owner=current_user, description="Automated assessment scheduling task")

            schedule = ScheduleAttempt(owner_id=data.id,
                                       name=form.name.data,
                                       celery_id=uuid,
                                       finished=False,
                                       outcome=None,
                                       published=False,
                                       deployed=False,
                                       construct_time=None,
                                       compute_time=None,
                                       max_group_size=form.max_group_size.data,
                                       solver=form.solver.data,
                                       creation_timestamp=datetime.now(),
                                       creator_id=current_user.id,
                                       last_edit_timestamp=None,
                                       last_edit_id=None,
                                       score=None)

            db.session.add(schedule)
            db.session.commit()

            celery = current_app.extensions['celery']
            schedule_task = celery.tasks['app.tasks.scheduling.create_schedule']

            schedule_task.apply_async(args=(schedule.id,), task_id=uuid)

            return redirect(url_for('admin.assessment_schedules', id=data.id))

    matches = get_count(data.scheduling_attempts)

    return render_template('admin/presentations/scheduling/create.html', pane='create', info=matches, form=form,
                           assessment=data)


@admin.route('/adjust_assessment_schedule/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def adjust_assessment_schedule(id):
    """
    Create a new schedule associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    old_schedule = ScheduleAttempt.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(old_schedule.owner, current_year=current_year):
        return redirect(request.referrer)

    if not old_schedule.owner.availability_closed:
        flash('It is only possible to adjust a schedule once collection of faculty availabilities is closed.',
              'info')
        return redirect(request.referrer)

    if not old_schedule.owner.is_valid and len(old_schedule.owner.errors) > 0:
        flash('It is not possible to adjust a schedule for an assessment that contains validation errors. '
              'Correct any indicated errors before attempting to try again.', 'info')
        return redirect(request.referrer)

    if old_schedule.is_valid:
        flash('This schedule does not contain any validation errors, so does not require adjustment.', 'info')
        return redirect(request.referrer)

    if _validate_number_slots(old_schedule.owner, old_schedule.max_group_size):
        # find name for adjusted schedule
        suffix = 2
        while suffix < 100:
            new_name = '{name} #{suffix}'.format(name=old_schedule.name, suffix=suffix)

            if ScheduleAttempt.query.filter_by(name=new_name, owner_id=old_schedule.owner_id).first() is None:
                break

            suffix += 1

        if suffix > 100:
            flash('Can not adjust schedule "{name}" because a new unique tag could not '
                  'be generated.'.format(name=old_schedule.name), 'error')
            return redirect(request.referrer)

        uuid = register_task('Schedule job "{name}"'.format(name=new_name),
                             owner=current_user, description="Automated assessment scheduling task")

        new_schedule = ScheduleAttempt(owner_id=old_schedule.owner_id,
                                       name=new_name,
                                       celery_id=uuid,
                                       finished=False,
                                       outcome=None,
                                       published=old_schedule.published,
                                       construct_time=None,
                                       compute_time=None,
                                       max_group_size=old_schedule.max_group_size,
                                       solver=old_schedule.solver,
                                       creation_timestamp=datetime.now(),
                                       creator_id=current_user.id,
                                       last_edit_timestamp=None,
                                       last_edit_id=None,
                                       score=None)

        db.session.add(new_schedule)
        db.session.commit()

        celery = current_app.extensions['celery']
        schedule_task = celery.tasks['app.tasks.scheduling.recompute_schedule']

        schedule_task.apply_async(args=(new_schedule.id, old_schedule.id,), task_id=uuid)

    return redirect(url_for('admin.assessment_schedules', id=old_schedule.owner.id))


@admin.route('/terminate_schedule/<int:id>')
@roles_required('root')
def terminate_schedule(id):

    record = ScheduleAttempt.query.get_or_404(id)

    if record.finished:
        flash('Can not terminate scheduling task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    title = 'Terminate schedule'
    panel_title = 'Terminate schedule <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('admin.perform_terminate_schedule', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to terminate the scheduling job ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Terminate job'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_terminate_schedule/<int:id>')
@roles_required('root')
def perform_terminate_schedule(id):

    record = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('admin.assessment_schedules', record.owner_id)

    if record.finished:
        flash('Can not terminate scheduling task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(url)

    celery = current_app.extensions['celery']
    celery.control.revoke(record.celery_id, terminate=True, signal='SIGUSR1')

    try:
        progress_update(record.celery_id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # delete all ScheduleSlot records associated with this ScheduleAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(ScheduleSlot).filter_by(owner_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        flash('Can not terminate scheduling task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(url)


@admin.route('/delete_schedule/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def delete_schedule(id):

    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if not record.finished:
        flash('Can not delete schedule "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    title = 'Delete schedule'
    panel_title = 'Delete schedule <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('admin.perform_delete_schedule', id=id, url=request.referrer)
    message = '<p>Please confirm that you wish to delete the schedule ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Delete schedule'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_delete_schedule/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def perform_delete_schedule(id):

    record = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('admin.assessment_schedules', id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(url)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if not record.finished:
        flash('Can not delete schedule "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(url)

    if not current_user.has_role('root') and current_user.id != record.creator_id:
        flash('Schedule "{name}" cannot be deleted because it belongs to another user')
        return redirect(url)

    try:
        # delete all ScheduleSlots associated with this ScheduleAttempt
        for slot in record.slots:
            slot.assessors = []
            slot.talks = []
            db.session.delete(slot)
        db.session.flush()

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        flash('Can not delete schedule "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(url)


@admin.route('/rename_schedule/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def rename_schedule(id):
    record = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('admin.assessment_schedules', id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    RenameScheduleForm = RenameScheduleFormFactory(record.owner)
    form = RenameScheduleForm(request.form)
    form.schedule = record

    if form.validate_on_submit():
        try:
            record.name = form.name.data
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash('Could not rename schedule "{name}" due to a database error. '
                  'Please contact a system administrator.'.format(name=record.name), 'error')

        return redirect(url)

    return render_template('admin/presentations/scheduling/rename.html', form=form, record=record, url=url)


@admin.route('/publish_schedule/<int:id>')
@roles_required('root')
def publish_schedule(id):
    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if not record.finished:
        flash('Schedule "{name}" cannot be published until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != ScheduleAttempt.OUTCOME_OPTIMAL:
        flash('Schedule "{name}" did not yield an optimal solution and is not available for use. '
              'It cannot be shared with convenors.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.deployed:
        flash('Schedule "{name}" is deployed and is not available to be published.'.format(name=record.name),
              'info')
        return redirect(request.referrer)

    record.published = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/unpublish_schedule/<int:id>')
@roles_required('root')
def unpublish_schedule(id):
    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if not record.finished:
        flash('Schedule "{name}" cannot be unpublished until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != ScheduleAttempt.OUTCOME_OPTIMAL:
        flash('Schedule "{name}" did not yield an optimal solution and is not available for use. '
              'It cannot be shared with convenors.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    record.published = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deploy_schedule/<int:id>')
@roles_required('root')
def deploy_schedule(id):
    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if record.owner.is_deployed:
        flash('The assessment "{name}" already has a deployed schedule. Only one schedule can be '
              'deployed at a time.'.format(name=record.owner.name), 'info')

    if not record.finished:
        flash('Schedule "{name}" cannot be deployed until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != ScheduleAttempt.OUTCOME_OPTIMAL:
        flash('Schedule "{name}" did not yield an optimal solution and is not available for '
              'deployment.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    record.deployed = True
    record.published = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/undeploy_schedule/<int:id>')
@roles_required('root')
def undeploy_schedule(id):
    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if not record.finished:
        flash('Schedule "{name}" cannot be deployed or revoked until it has '
              'completed successfully.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != ScheduleAttempt.OUTCOME_OPTIMAL:
        flash('Schedule "{name}" did not yield an optimal solution and is not available for '
              'deployment.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not record.is_revokable:
        flash('Schedule "{name}" is not revokable. This may be because some scheduled slots are in '
              'the past, or because some feedback has already been entered.'.format(name=record.name), 'error')

    record.deployed = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/schedule_view_sessions/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def schedule_view_sessions(id):
    """
    Sessions view in schedule inspector
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return redirect(request.referrer)

    if not record.finished:
        flash('Schedule "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if record.outcome != ScheduleAttempt.OUTCOME_OPTIMAL:
        flash('Schedule "{name}" is not available for inspection '
              'because it did not yield an optimal solution.'.format(name=record.name), 'info')
        return redirect(request.referrer)

    if not validate_schedule_inspector(record):
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')
    building_filter = request.args.get('building_filter')
    room_filter = request.args.get('room_filter')
    session_filter = request.args.get('session_filter')
    text = request.args.get('text', None)
    url = request.args.get('url', None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_schedule_pclass_filter'):
        pclass_filter = session['admin_schedule_pclass_filter']

    if pclass_filter is not None:
        session['admin_match_pclass_filter'] = pclass_filter

    if building_filter is None and session.get('admin_schedule_building_filter'):
        building_filter = session['admin_schedule_building_filter']

    if building_filter is not None:
        session['admin_match_building_filter'] = building_filter

    if room_filter is None and session.get('admin_schedule_room_filter'):
        building_filter = session['admin_schedule_room_filter']

    if room_filter is not None:
        session['admin_match_room_filter'] = room_filter

    if session_filter is None and session.get('admin_schedule_session_filter'):
        session_filter = session['admin_schedule_session_filter']

    if session_filter is not None:
        session['admin_match_session_filter'] = session_filter

    pclasses = record.available_pclasses
    buildings = record.available_buildings
    rooms = record.available_rooms
    sessions = record.available_sessions

    return render_template('admin/presentations/schedule_inspector/sessions.html', pane='sessions', record=record,
                           pclasses=pclasses, buildings=buildings, rooms=rooms, sessions=sessions,
                           pclass_filter=pclass_filter, building_filter=building_filter, room_filter=room_filter,
                           session_filter=session_filter,
                           text=text, url=url)


@admin.route('/schedule_view_sessions_ajax/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def schedule_view_sessions_ajax(id):
    """
    AJAX data point for Sessions view in Schedule inspector
    """
    if not validate_using_assessment():
        return jsonify({})

    record = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        flash('Schedule "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'info')
        return jsonify({})

    if record.outcome != ScheduleAttempt.OUTCOME_OPTIMAL:
        flash('Schedule "{name}" is not available for inspection '
              'because it did not yield an optimal solution.'.format(name=record.name), 'info')
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    pclass_filter = request.args.get('pclass_filter')
    building_filter = request.args.get('building_filter')
    room_filter = request.args.get('room_filter')
    session_filter = request.args.get('session_filter')

    # now want to extract all slots from 'record' that satisfy the filters
    slots = record.slots
    joined_room = False

    flag, session_value = is_integer(session_filter)
    if flag:
        slots = slots.filter_by(session_id=session_value)

    flag, building_value = is_integer(building_filter)
    if flag:
        slots = slots.join(Room, Room.id == ScheduleSlot.room_id).filter(Room.building_id == building_value)
        joined_room = True

    flag, room_value = is_integer(room_filter)
    if flag:
        if not joined_room:
            slots = slots.join(Room, Room.id == ScheduleSlot.room_id)
        slots = slots.filter(Room.id == room_value)

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        slots = [t for t in slots.all() if t.has_pclass(pclass_value)]
    else:
        slots = slots.all()

    return ajax.admin.schedule_view_sessions(slots, record)


@admin.route('/assessment_manage_attendees/<int:id>')
@roles_required('root')
def assessment_manage_attendees(id):
    """
    Manage student attendees for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(request.referrer)

    if data.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be'
              ' altered'.format(name=data.name), 'info')
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')

    if pclass_filter is None and session.get('attendees_pclass_filter'):
        pclass_filter = session['attendees_pclass_filter']

    if pclass_filter is not None:
        session['attendees_pclass_filter'] = pclass_filter

    attend_filter = request.args.get('attend_filter')

    if attend_filter is None and session.get('attendees_attend_filter'):
        attend_filter = session['attendees_attend_filter']

    if attend_filter is not None:
        session['attendees_attend_filter'] = attend_filter

    pclasses = data.available_pclasses

    return render_template('admin/presentations/manage_attendees.html', assessment=data, pclass_filter=pclass_filter,
                           attend_filter=attend_filter, pclasses=pclasses)


@admin.route('/manage_attendees_ajax/<int:id>')
@roles_required('root')
def manage_attendees_ajax(id):
    """
    AJAX data point for managing student attendees
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    data = PresentationAssessment.query.get_or_404(id)

    pclass_filter = request.args.get('pclass_filter')
    attend_filter = request.args.get('attend_filter')

    talks = data.available_talks
    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        talks = [t for t in talks if t.owner.config.pclass_id == pclass_value]

    if attend_filter == 'attending':
        talks = [t for t in talks if not data.not_attending(t.id)]
    elif attend_filter == 'not-attending':
        talks = [t for t in talks if data.not_attending(t.id)]

    if not validate_assessment(data):
        return jsonify({})

    return ajax.admin.presentation_attendees_data(talks, data)


@admin.route('/assessment_attending/<int:a_id>/<int:s_id>')
@roles_required('root')
def assessment_attending(a_id, s_id):
    """
    Mark a student/talk as able to attend the assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(request.referrer)

    if data.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be'
              ' altered'.format(name=data.name), 'info')
        return redirect(request.referrer)

    talk = SubmissionRecord.query.get_or_404(s_id)

    if talk not in data.available_talks:
        flash('Cannot mark the specified talk as attending because it is not included in this presentation assessment',
              'error')
        return redirect(request.referrer)

    if talk in data.cant_attend:
        data.cant_attend.remove(talk)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/assessment_not_attending/<int:a_id>/<int:s_id>')
@roles_required('root')
def assessment_not_attending(a_id, s_id):
    """
    Mark a student/talk as not able to attend the assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(request.referrer)

    data = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(request.referrer)

    if data.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be'
              ' altered'.format(name=data.name), 'info')
        return redirect(request.referrer)

    talk = SubmissionRecord.query.get_or_404(s_id)

    if talk not in data.available_talks:
        flash('Cannot mark the specified talk as not attending because it is not included in this presentation assessment',
              'error')
        return redirect(request.referrer)

    if talk not in data.cant_attend:
        data.cant_attend.append(talk)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_rooms')
@roles_required('root')
def edit_rooms():
    """
    Manage bookable venues for presentation sessions
    :return:
    """
    return render_template('admin/presentations/edit_rooms.html', pane='rooms')


@admin.route('/rooms_ajax')
@roles_required('root')
def rooms_ajax():
    """
    AJAX entrypoint for list of available rooms
    :return:
    """

    rooms = db.session.query(Room).all()
    return ajax.admin.rooms_data(rooms)


@admin.route('/add_room', methods=['GET', 'POST'])
@roles_required('root')
def add_room():
    # check whether any active buildings exist, and raise an error if not
    if not db.session.query(Building).filter_by(active=True).first():
        flash('No buildings are available. Set up at least one active building before adding a room.', 'error')
        return redirect(request.referrer)

    form = AddRoomForm(request.form)

    if form.validate_on_submit():

        data = Room(building_id=form.building.data.id,
                    name=form.name.data,
                    capacity=form.capacity.data,
                    lecture_capture=form.lecture_capture.data,
                    active=True,
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_rooms'))

    return render_template('admin/presentations/edit_room.html', form=form, title='Add new venue')


@admin.route('/edit_room/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    form = EditRoomForm(obj=data)
    form.room = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.capacity = form.capacity.data
        data.lecture_capture = form.lecture_capture.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_rooms'))

    return render_template('admin/presentations/edit_room.html', form=form, room=data, title='Edit venue')


@admin.route('/activate_room/<int:id>')
@roles_required('root')
def activate_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_room/<int:id>')
@roles_required('root')
def deactivate_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_buildings')
@roles_required('root')
def edit_buildings():
    """
    Manage list of buildings to which bookable venues can belong.
    Essentially used to identify rooms in the same building with a coloured tag.
    :return:
    """
    return render_template('admin/presentations/edit_buildings.html', pane='buildings')


@admin.route('/buildings_ajax')
@roles_required('root')
def buildings_ajax():
    """
    AJAX entrypoint for list of available buildings
    :return:
    """

    buildings = db.session.query(Building).all()
    return ajax.admin.buildings_data(buildings)


@admin.route('/add_building', methods=['GET', 'POST'])
@roles_required('root')
def add_building():
    form = AddBuildingForm(request.form)

    if form.validate_on_submit():
        data = Building(name=form.name.data,
                        colour=form.colour.data,
                        active=True,
                        creator_id=current_user.id,
                        creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_buildings'))

    return render_template('admin/presentations/edit_building.html', form=form, title='Add new building')


@admin.route('/edit_building/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    form = EditBuildingForm(obj=data)
    form.building = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.colour = form.colour.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_buildings'))

    return render_template('admin/presentations/edit_building.html', form=form, building=data,
                           title='Edit building')


@admin.route('/activate_building/<int:id>')
@roles_required('root')
def activate_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_building/<int:id>')
@roles_required('root')
def deactivate_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/launch_test_task')
@roles_required('root')
def launch_test_task():

    task_id = register_task('Test task', owner=current_user, description="Long-running test task")

    celery = current_app.extensions['celery']
    test_task = celery.tasks['app.tasks.test.test_task']

    test_task.apply_async(task_id=task_id)

    return 'success'


@admin.route('/login_as/<int:id>')
@roles_required('root')
def login_as(id):

    user = User.query.get_or_404(id)

    # store previous login identifier
    # this is OK provided we only ever use server-side sessions for security, so that the session
    # variables can not be edited, inspected or faked by the user
    session['previous_login'] = current_user.id

    current_app.logger.info('{real} used superuser powers to log in as '
                            'alternative user {fake}'.format(real=current_user.name, fake=user.name))

    login_user(user, remember=False)
    # don't commit changes to database to avoid confusing this with a real login

    return home_dashboard()
