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

from celery import chain, group

from .actions import register_user, estimate_CATS_load
from .forms import RoleSelectForm, \
    ConfirmRegisterOfficeForm, ConfirmRegisterFacultyForm, ConfirmRegisterStudentForm, \
    EditOfficeForm, EditFacultyForm, EditStudentForm, \
    AddResearchGroupForm, EditResearchGroupForm, \
    AddDegreeTypeForm, EditDegreeTypeForm, \
    AddDegreeProgrammeForm, EditDegreeProgrammeForm, \
    AddTransferableSkillForm, EditTransferableSkillForm, AddSkillGroupForm, EditSkillGroupForm, \
    AddProjectClassForm, EditProjectClassForm, \
    AddSupervisorForm, EditSupervisorForm, \
    FacultySettingsForm, EnrollmentRecordForm, EmailLogForm, \
    AddMessageForm, EditMessageForm, \
    ScheduleTypeForm, AddIntervalScheduledTask, AddCrontabScheduledTask, \
    EditIntervalScheduledTask, EditCrontabScheduledTask, \
    EditBackupOptionsForm, BackupManageForm, \
    AddRoleForm, EditRoleForm, \
    NewMatchForm

from ..models import db, MainConfig, User, FacultyData, StudentData, ResearchGroup,\
    DegreeType, DegreeProgramme, SkillGroup, TransferableSkill, ProjectClass, ProjectClassConfig, Supervisor, \
    EmailLog, MessageOfTheDay, DatabaseSchedulerEntry, IntervalSchedule, CrontabSchedule, \
    BackupRecord, TaskRecord, Notification, EnrollmentRecord, Role, MatchingAttempt, MatchingRecord, \
    LiveProject

from ..shared.utils import get_main_config, get_current_year, home_dashboard, get_matching_dashboard_data, \
    get_root_dashboard_data, get_automatch_pclasses
from ..shared.formatters import format_size
from ..shared.backup import get_backup_config, set_backup_config, get_backup_count, get_backup_size, remove_backup
from ..shared.validators import validate_is_convenor, validate_is_admin_or_convenor
from ..shared.conversions import is_integer

from ..task_queue import register_task, progress_update

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
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
                           office=form.office.data,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        if form.submit.data:
            return redirect(url_for('admin.edit_affiliations', id=data.id, create=1))
        elif form.save_and_exit.data:
            return redirect(url_for('admin.edit_users'))
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

    return render_template('security/register_user.html', user_form=form, role=role,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/create_student/<string:role>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def create_student(role):

    # check whether role is ok
    if not (role == 'student'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterStudentForm(request.form)

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

        return redirect(url_for('admin.edit_users'))

    else:
        if request.method == 'GET':
            # populate cohort with default value on first load
            config = get_main_config()

            if config:
                form.cohort.data = config.year

            else:
                form.cohort.data = date.today().year

    return render_template('security/register_user.html', user_form=form, role=role,
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
                           programmes=programmes, cohorts=cohorts)


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

    if user.has_role('office'):
        return redirect(url_for('admin.edit_office', id=id))

    elif user.has_role('faculty'):
        return redirect(url_for('admin.edit_faculty', id=id))

    elif user.has_role('student'):
        return redirect(url_for('admin.edit_student', id=id))

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

        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.project_capacity = form.project_capacity.data if form.enforce_capacity.data else None
        data.enforce_capacity = form.enforce_capacity.data
        data.show_popularity = form.show_popularity.data
        data.CATS_supervision = form.CATS_supervision.data
        data.CATS_marking = form.CATS_marking.data
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
            form.CATS_supervision.data = data.CATS_supervision
            form.CATS_marking.data = data.CATS_marking
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

    if form.validate_on_submit():

        record.supervisor_state = form.supervisor_state.data
        record.supervisor_reenroll = None if record.supervisor_state != EnrollmentRecord.SUPERVISOR_SABBATICAL \
            else form.supervisor_reenroll.data
        record.supervisor_comment = form.supervisor_comment.data

        record.marker_state = form.marker_state.data
        record.marker_reenroll = None if record.marker_state != EnrollmentRecord.MARKER_SABBATICAL \
            else form.marker_reenroll.data
        record.marker_comment = form.marker_comment.data

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        db.session.commit()

        if returnid==0:
            return redirect(url_for('admin.edit_enrollments', id=record.owner_id))
        elif returnid==1:
            return redirect(url_for('convenor.faculty', id=record.pclass.id))
        else:
            return home_dashboard()

    return render_template('admin/edit_enrollment.html', record=record, form=form, returnid=returnid)


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
        data.add_enrollment(pclass, autocommit=True)

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
        data.remove_enrollment(pclass, autocommit=True)

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
                              creation_timestamp=datetime.now());
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


@admin.route('/degree_types_ajax', methods=['GET', 'POST'])
@roles_required('root')
def degree_types_ajax():
    """
    Ajax data point for degree type table
    :return:
    """

    types = DegreeType.query.all()
    return ajax.admin.degree_types_data(types)


@admin.route('/degree_programmes_ajax', methods=['GET', 'POST'])
@roles_required('root')
def degree_programmes_ajax():
    """
    Ajax data point for degree programmes tables
    :return:
    """

    programmes = DegreeProgramme.query.all()
    return ajax.admin.degree_programmes_data(programmes)



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

    degree_type = DegreeType.query.get_or_404(id)
    form = EditDegreeTypeForm(obj=degree_type)

    form.degree_type = degree_type

    if form.validate_on_submit():
        degree_type.name = form.name.data
        degree_type.last_edit_id = current_user.id
        degree_type.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_degree_types'))

    return render_template('admin/degree_types/edit_degree.html', type_form=form, type=degree_type, title='Edit degree type')


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
    return ajax.admin.skill_groups_data(groups)


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
                            number_markers=form.number_markers.data,
                            year=form.year.data,
                            extent=form.extent.data,
                            require_confirm=form.require_confirm.data,
                            supervisor_carryover=form.supervisor_carryover.data,
                            submissions=form.submissions.data,
                            uses_marker=form.uses_marker.data,
                            convenor=form.convenor.data,
                            coconvenors=coconvenors,
                            selection_open_to_all=form.selection_open_to_all.data,
                            programmes=form.programmes.data,
                            initial_choices=form.initial_choices.data,
                            switch_choices=form.switch_choices.data,
                            active=True,
                            CATS_supervision=form.CATS_supervision.data,
                            CATS_marking=form.CATS_marking.data,
                            keep_hourly_popularity=form.keep_hourly_popularity.data,
                            keep_daily_popularity=form.keep_daily_popularity.data,
                            creator_id=current_user.id,
                            creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.flush()

        # generate a corresponding configuration record for the current academic year
        current_year = get_current_year()

        config = ProjectClassConfig(year=current_year,
                                    pclass_id=data.id,
                                    convenor_id=data.convenor_id,
                                    requests_issued=False,
                                    live=False,
                                    selection_closed=False,
                                    feedback_open=False,
                                    CATS_supervision=data.CATS_supervision,
                                    CATS_marking=data.CATS_marking,
                                    creator_id=current_user.id,
                                    creation_timestamp=datetime.now(),
                                    submission_period=1)

        data.convenor.add_convenorship(data)

        db.session.add(config)
        db.session.commit()

        return redirect(url_for('admin.edit_project_classes'))

    else:

        if request.method == 'GET':
            form.number_markers.data = current_app.config['DEFAULT_SECOND_MARKERS']
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
        data.number_markers = form.number_markers.data
        data.extent = form.extent.data
        data.require_confirm = form.require_confirm.data
        data.supervisor_carryover = form.supervisor_carryover.data
        data.submissions = form.submissions.data
        data.uses_marker = form.uses_marker.data
        data.convenor = form.convenor.data
        data.coconvenors = coconvenors
        data.selection_open_to_all = form.selection_open_to_all.data
        data.programmes = form.programmes.data
        data.initial_choices = form.initial_choices.data
        data.switch_choices = form.switch_choices.data
        data.CATS_supervision = form.CATS_supervision.data
        data.CATS_marking = form.CATS_marking.data
        data.keep_hourly_popularity = form.keep_hourly_popularity.data
        data.keep_daily_popularity = form.keep_daily_popularity.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        if data.convenor.id != old_convenor.id:

            old_convenor.remove_convenorship(data)
            data.convenor.add_convenorship(data)

        db.session.commit()

        return redirect(url_for('admin.edit_project_classes'))

    else:

        if request.method == 'GET':
            if form.number_markers.data is None:
                form.number_markers.data = current_app.config['DEFAULT_SECOND_MARKERS']
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


@admin.route('/faculty_settings', methods=['GET', 'POST'])
@roles_required('faculty')
def faculty_settings():
    """
    Edit settings for a faculty member
    :return:
    """

    user = User.query.get_or_404(current_user.id)
    data = FacultyData.query.get_or_404(current_user.id)

    form = FacultySettingsForm(obj=data)
    form.user = user

    del form.CATS_supervision
    del form.CATS_marking

    if form.validate_on_submit():

        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.username = form.username.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.project_capacity = form.project_capacity.data
        data.enforce_capacity = form.enforce_capacity.data
        data.show_popularity = form.show_popularity.data
        data.office = form.office.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        flash('All changes saved')

        db.session.commit()

        return home_dashboard()

    else:

        # fill in fields that need data from 'User' and won't have been initialized from obj=data
        if request.method == 'GET':

            form.first_name.data = user.first_name
            form.last_name.data = user.last_name
            form.username.data = user.username

    return render_template('admin/faculty_settings.html', settings_form=form, data=data,
                           project_classes=ProjectClass.query.filter_by(active=True))


@admin.route('/confirm_global_rollover')
@roles_required('root')
def confirm_global_rollover():
    """
    Show confirmation box for global advance of academic year
    :return:
    """

    next_year = get_current_year() + 1

    title = 'Global rollover to {yeara}&ndash;{yearb}'.format(yeara=next_year, yearb=next_year + 1)
    panel_title = 'Global rollover of academic year to {yeara}&ndash;{yearb}'.format(yeara=next_year,
                                                                                     yearb=next_year + 1)
    action_url = url_for('admin.perform_global_rollover')
    message = 'Please confirm that you wish to advance the global academic year to ' \
              '{yeara}&ndash;{yearb}. ' \
              'This action cannot be undone.'.format(yeara=next_year, yearb=next_year + 1)
    submit_label = 'Rollover to {yr}'.format(yr=next_year)

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_global_rollover')
@roles_required('root')
def perform_global_rollover():
    """
    Globally advance the academic year
    (doesn't actually do anything directly; each project class must be advanced
    independently by its convenor or an administrator)
    :return:
    """

    next_year = get_current_year() + 1

    new_year = MainConfig(year=next_year)
    db.session.add(new_year)
    db.session.commit()

    return redirect(url_for('home.homepage'))


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

    roles = db.session.query(Role)
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
    message = 'Please confirm that you wish to delete all emails retained in the log. ' \
              'This action cannot be undone.'
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
    message = 'Please confirm that you wish to delete all emails older than {c} week{pl}. ' \
              'This action cannot be undone.'.format(c=cutoff, pl=pl)
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
        form = AddMessageForm(request.form, convenor_editing=True)
        del form.show_login
    else:
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

        form = EditMessageForm(obj=data, convenor_editing=True)
        del form.show_login

    else:

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
    message = 'Please confirm that you wish to delete all backups. ' \
              'This action cannot be undone.'
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
    message = 'Please confirm that you wish to delete all backups older than {c} week{pl}. ' \
              'This action cannot be undone.'.format(c=cutoff, pl=pl)
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
    message = 'Please confirm that you wish to delete the backup {d}. ' \
              'This action cannot be undone.'.format(d=backup.date.strftime("%a %d %b %Y %H:%M:%S"))
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


@admin.route('/notifications_ajax', methods=['GET', 'POST'])
@login_required
def notifications_ajax():
    """
    Retrieve all notifications for the current user
    :return:
    """

    # get timestamp that client wants messages from, if provided
    since = request.args.get('since', 0.0, type=float)

    # query for all tasks associated with the current user
    notifications = current_user.notifications.filter(Notification.timestamp > since).order_by(
        Notification.timestamp.asc()).all()

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
    config_list, current_year, rollover_ready, matching_ready = get_root_dashboard_data()
    if not matching_ready:
        flash('Automated matching is not yet available because some project classes are not ready', 'error')
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
    config_list, current_year, rollover_ready, matching_ready = get_root_dashboard_data()
    if not matching_ready:
        return jsonify({})

    current_year = get_current_year()

    matches = db.session.query(MatchingAttempt).filter_by(year=current_year).all()

    return ajax.admin.matches_data(matches)


@admin.route('/create_match', methods=['GET', 'POST'])
@roles_required('root')
def create_match():
    """
    Create the 'create match' dashboard view
    :return:
    """

    # check that all projects are ready to match
    config_list, current_year, rollover_ready, matching_ready = get_root_dashboard_data()
    if not matching_ready:
        flash('Automated matching is not yet available because some project classes are not ready', 'error')
        return redirect(request.referrer)

    info = get_matching_dashboard_data()

    form = NewMatchForm(request.form)

    if form.validate_on_submit():

        uuid = register_task('Match job "{name}"'.format(name=form.name.data),
                             owner=current_user, description="Automated project matching task")

        data = MatchingAttempt(year=current_year,
                               name=form.name.data,
                               celery_id=uuid,
                               finished=False,
                               outcome=None,
                               timestamp=datetime.now(),
                               construct_time=None,
                               compute_time=None,
                               owner_id=current_user.id,
                               ignore_per_faculty_limits=form.ignore_per_faculty_limits.data,
                               ignore_programme_prefs=form.ignore_programme_prefs.data,
                               years_memory=form.years_memory.data,
                               supervising_limit=form.supervising_limit.data,
                               marking_limit=form.marking_limit.data,
                               max_marking_multiplicity=form.max_marking_multiplicity.data,
                               levelling_bias=form.levelling_bias.data,
                               intra_group_tension=form.intra_group_tension.data,
                               programme_bias=form.programme_bias.data,
                               score=None)

        db.session.add(data)
        db.session.commit()

        celery = current_app.extensions['celery']
        match_task = celery.tasks['app.tasks.matching.create_match']

        match_task.apply_async(args=(data.id,), task_id=uuid)

        return redirect(url_for('admin.manage_matching'))

    # estimate equitable CATS loading
    supervising_CATS, marking_CATS, num_supervisors, num_markers = estimate_CATS_load()

    return render_template('admin/matching/create.html', pane='create', info=info, form=form,
                           supervising_CATS=supervising_CATS, marking_CATS=marking_CATS,
                           num_supervisors=num_supervisors, num_markers=num_markers)


@admin.route('/terminate_match/<int:id>')
@roles_required('root')
def terminate_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if record.finished:
        flash('Could not terminate matching task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    celery = current_app.extensions['celery']
    celery.control.revoke(record.celery_id)

    try:
        progress_update(record.celery_id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # delete all MatchingRecords associated with this MatchingAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(MatchingRecord).filter_by(matching_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not terminate matching task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(request.referrer)


@admin.route('/delete_match/<int:id>')
@roles_required('root')
def delete_match(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        flash('Could not delete match "{name}" because it has not terminated.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    try:
        # delete all MatchingRecords associated with this MatchingAttempt
        db.session.query(MatchingRecord).filter_by(matching_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not delete match "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

    return redirect(request.referrer)


@admin.route('/match_student_view/<int:id>')
@roles_required('root')
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

    pclass_filter = request.args.get('pclass_filter')

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    pclasses = get_automatch_pclasses()

    return render_template('admin/match_inspector/student.html', pane='student', record=record,
                           pclasses=pclasses, pclass_filter=pclass_filter)


@admin.route('/match_faculty_view/<int:id>')
@roles_required('root')
def match_faculty_view(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        flash('Match "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" is not available for inspection '
              'because it did not yield an optimal solution'.format(name=record.name), 'error')
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    pclasses = get_automatch_pclasses()

    return render_template('admin/match_inspector/faculty.html', pane='faculty', record=record,
                           pclasses=pclasses, pclass_filter=pclass_filter)


@admin.route('/match_dists_view/<int:id>')
@roles_required('root')
def match_dists_view(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        flash('Match "{name}" is not yet available for inspection '
              'because the solver has not terminated.'.format(name=record.name), 'error')
        return redirect(request.referrer)

    if record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Match "{name}" is not available for inspection '
              'because it did not yield an optimal solution'.format(name=record.name), 'error')
        return redirect(request.referrer)

    pclass_filter = request.args.get('pclass_filter')

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('admin_match_pclass_filter'):
        pclass_filter = session['admin_match_pclass_filter']

    flag, pclass_value = is_integer(pclass_filter)

    pclasses = get_automatch_pclasses()

    fsum = lambda x: x[0] + x[1]
    CATS_tot = [fsum(record.get_faculty_CATS(f, pclass_value if flag else None)) for f in record.faculty]

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

    deltas = [x[1] for x in delta_data_set]

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
                           delta_script=delta_script, delta_div=delta_div)


@admin.route('/match_student_view_ajax/<int:id>')
@roles_required('root')
def match_student_view_ajax(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished or record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        return jsonify({})

    pclass_filter = request.args.get('pclass_filter')
    flag, pclass_value = is_integer(pclass_filter)

    data_set = zip(record.selectors, record.selector_deltas)
    if flag:
        data_set = [x for x in data_set if (x[0])[0].selector.config.pclass_id == pclass_value]

    return ajax.admin.match_view_student.student_view_data(data_set)


@admin.route('/match_faculty_view_ajax/<int:id>')
@roles_required('root')
def match_faculty_view_ajax(id):

    record = MatchingAttempt.query.get_or_404(id)

    if not record.finished or record.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        return jsonify({})

    pclass_filter = request.args.get('pclass_filter')

    flag, pclass_value = is_integer(pclass_filter)

    return ajax.admin.match_view_faculty.faculty_view_data(record.faculty, record, pclass_value if flag else None)


@admin.route('/reassign_match_project/<int:id>/<int:pid>')
@roles_required('root')
def reassign_match_project(id, pid):

    record = MatchingRecord.query.get_or_404(id)
    project = LiveProject.query.get_or_404(pid)

    if record.selector.has_submitted:
        if record.selector.is_project_submitted(project):
            record.project_id = project.id
            record.supervisor_id = project.owner_id
            record.rank = record.selector.project_rank(project.id)
            db.session.commit()
        else:
            flash('Could not reassign "{proj}" to {name} this project '
                  'was not included in their submitted choices'.format(proj=project.name,
                                                                       name=record.selector.student.user.name),
                  'error')

    elif record.selector.has_bookmarks:
        if record.selector.is_project_bookmarked(project):
            record.project_id = project.id
            record.supervisor_id = project.owner_id
            record.rank = record.selector.project_rank(project.id)
            db.session.commit()
        else:
            flash('Could not reassign "{proj}" to {name} this project '
                  'was not included in their ranked bookmarks'.format(proj=project.name,
                                                                      name=record.selector.student.user.name),
                  'error')

    return redirect(request.referrer)


@admin.route('/reassign_match_marker/<int:id>/<int:mid>')
@roles_required('root')
def reassign_match_marker(id, mid):

    record = MatchingRecord.query.get_or_404(id)

    # check intended mid is in list of attached second markers
    q = record.project.second_markers.subquery()
    count = db.session.query(func.count(q.c.id)).filter(q.c.id == mid).scalar()

    if count == 0:
        marker = FacultyData.query.get_or_404(mid)
        flash('Could not assign {name} as 2nd marker since '
              'not tagged as available for assigned project "{proj}"'.format(name=marker.user.name,
                                                                             proj=record.project.name), 'error')

    elif count == 1:
        record.marker_id = mid
        db.session.commit()

    else:
        flash('Inconsistent marker counts for matching record (id={id}). '
              'Please contact a system administrator'.format(id=record.id), 'error')

    return redirect(request.referrer)


@admin.route('/terminate_background_task/<string:id>')
@roles_required('root')
def terminate_background_task(id):

    record = TaskRecord.query.get_or_404(id)

    if record.state == TaskRecord.SUCCESS or record.state == TaskRecord.FAILURE or record.state == TaskRecord.TERMINATED:
        flash('Could not terminate background task "{name}" because it has finished.'.format(name=record.name),
              'error')
        return redirect(request.referrer)

    celery = current_app.extensions['celery']
    celery.control.revoke(record.id)

    try:
        # update progress bar
        progress_update(record.id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # remove task from database
        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash('Could not terminate task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')

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
    login_user(user, remember=False)
    # don't commit changes to database to avoid confusing this with a real login

    return home_dashboard()
